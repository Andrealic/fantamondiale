#!/usr/bin/env python3
"""Costruisce le proiezioni di fantapunti attesi (ETP) per ogni giocatore del listone.

Pipeline:
  1. Simulazione Monte Carlo del Mondiale 2026 (gironi + tabellone) basata su rating Elo
     -> partite attese per nazionale (grezze e scontate per orizzonte/sostituibilita coi 10 cambi).
  2. Per ogni giocatore: probabilita di titolarita + fantapunti netti attesi a partita per ruolo
     (gol/assist/rigori per A-C; voto+modificatore per D; clean sheet/gol subiti per P).
  3. Scrive data/projections.csv con ETP e componenti.

Uso: python scripts/build_projections.py [--sims 20000]
"""
from __future__ import annotations

import argparse
import csv
import random
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA = PROJECT_ROOT / "data"
LISTONE = PROJECT_ROOT / "fantapazz_listone_enriched.csv"
STRENGTH = DATA / "wc2026_team_strength.csv"
CONTEXT = DATA / "player_context.csv"
LINEUP = DATA / "lineup_sentiment.csv"
ODDS = DATA / "topscorer_odds.csv"
OUT_PROJ = DATA / "projections.csv"
OUT_SIM = DATA / "wc2026_sim.csv"

# ----------------------------------------------------------------------------
# Modello partita (Elo -> gol attesi via Poisson)
# ----------------------------------------------------------------------------
ELO_SCALE = 125.0   # 1 gol di supremazia ogni ~125 punti Elo di scarto
TOTAL_GOALS = 2.6   # gol totali medi a partita

# Pesi di sconto per fase: i gironi (3 gare garantite per tutti) valgono pieno;
# i turni a eliminazione decrescono perche i giocatori delle eliminate si
# sostituiscono coi 10 cambi e ci si puo riposizionare sulle superstiti.
ROUND_WEIGHTS = {"group": 1.0, "R32": 0.9, "R16": 0.75, "QF": 0.6, "SF": 0.45, "F": 0.35}

# Bracket Round of 32 (mapping ufficiale FIFA: vincenti/seconde fisse, terze a slot).
# Ogni voce: (id, slotA, slotB). slot = ("W"/"RU", group) oppure ("3", [gruppi ammessi]).
R32 = [
    ("M73", ("RU", "A"), ("RU", "B")),
    ("M74", ("W", "E"), ("3", list("ABCDF"))),
    ("M75", ("W", "F"), ("RU", "C")),
    ("M76", ("W", "C"), ("RU", "F")),
    ("M77", ("W", "I"), ("3", list("CDFGH"))),
    ("M78", ("RU", "E"), ("RU", "I")),
    ("M79", ("W", "A"), ("3", list("CEFHI"))),
    ("M80", ("W", "L"), ("3", list("EHIJK"))),
    ("M81", ("W", "D"), ("3", list("BEFIJ"))),
    ("M82", ("W", "G"), ("3", list("AEHIJ"))),
    ("M83", ("RU", "K"), ("RU", "L")),
    ("M84", ("W", "H"), ("RU", "J")),
    ("M85", ("W", "B"), ("3", list("EFGIJ"))),
    ("M86", ("W", "J"), ("RU", "H")),
    ("M87", ("W", "K"), ("3", list("DEIJL"))),
    ("M88", ("RU", "D"), ("RU", "G")),
]
R16 = [("M89", "M74", "M77"), ("M90", "M73", "M75"), ("M91", "M76", "M78"),
       ("M92", "M79", "M80"), ("M93", "M83", "M84"), ("M94", "M81", "M82"),
       ("M95", "M86", "M88"), ("M96", "M85", "M87")]
QF = [("M97", "M89", "M90"), ("M98", "M93", "M94"),
      ("M99", "M91", "M92"), ("M100", "M95", "M96")]
SF = [("M101", "M97", "M98"), ("M102", "M99", "M100")]
FINAL = ("M104", "M101", "M102")


def load_strength():
    teams = {}
    with STRENGTH.open(newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            teams[r["team_code"]] = {
                "name": r["team_name"], "group": r["group"], "elo": float(r["elo"]),
            }
    return teams


def sample_match(elo_a, elo_b, rng):
    sup = (elo_a - elo_b) / ELO_SCALE
    la = max(0.12, TOTAL_GOALS / 2 + sup / 2)
    lb = max(0.12, TOTAL_GOALS / 2 - sup / 2)
    return rng.poisson(la), rng.poisson(lb)


class RNG:
    """Wrapper minimale per Poisson senza numpy."""
    def __init__(self, seed):
        self._r = random.Random(seed)

    def poisson(self, lam):
        # algoritmo di Knuth
        import math
        L = math.exp(-lam)
        k, p = 0, 1.0
        while True:
            k += 1
            p *= self._r.random()
            if p <= L:
                return k - 1

    def random(self):
        return self._r.random()


def ko_winner(a, b, teams, rng):
    ga, gb = sample_match(teams[a]["elo"], teams[b]["elo"], rng)
    if ga > gb:
        return a
    if gb > ga:
        return b
    # rigori: prob ~ Elo logistica smorzata verso 0.5
    pa = 1.0 / (1.0 + 10 ** (-(teams[a]["elo"] - teams[b]["elo"]) / 400.0))
    pa = 0.5 + 0.6 * (pa - 0.5)
    return a if rng.random() < pa else b


def simulate(teams, sims, seed=12345):
    groups = defaultdict(list)
    for code, t in teams.items():
        groups[t["group"]].append(code)

    matches = defaultdict(float)   # partite attese grezze
    weighted = defaultdict(float)  # partite attese scontate per fase
    rng = RNG(seed)

    for _ in range(sims):
        winners, runners = {}, {}
        thirds = []  # (code, pts, gd, gf)
        for g, codes in groups.items():
            tab = {c: [0, 0, 0] for c in codes}  # pts, gd, gf
            for i in range(len(codes)):
                for j in range(i + 1, len(codes)):
                    a, b = codes[i], codes[j]
                    ga, gb = sample_match(teams[a]["elo"], teams[b]["elo"], rng)
                    tab[a][2] += ga; tab[b][2] += gb
                    tab[a][1] += ga - gb; tab[b][1] += gb - ga
                    if ga > gb:
                        tab[a][0] += 3
                    elif gb > ga:
                        tab[b][0] += 3
                    else:
                        tab[a][0] += 1; tab[b][0] += 1
            order = sorted(codes, key=lambda c: (tab[c][0], tab[c][1], tab[c][2],
                                                 teams[c]["elo"], rng.random()), reverse=True)
            for c in codes:  # 3 gare di girone per tutti
                matches[c] += 3
                weighted[c] += 3 * ROUND_WEIGHTS["group"]
            winners[g] = order[0]
            runners[g] = order[1]
            t = order[2]
            thirds.append((t, tab[t][0], tab[t][1], tab[t][2]))

        best_thirds = sorted(thirds, key=lambda x: (x[1], x[2], x[3], teams[x[0]]["elo"], rng.random()),
                             reverse=True)[:8]
        third_pool = [t[0] for t in best_thirds]
        third_by_group = {teams[c]["group"]: c for c in third_pool}

        # assegnazione terze agli slot (greedy rispettando i gruppi ammessi)
        results = {}
        used_thirds = set()

        def resolve(slot):
            kind, val = slot
            if kind == "W":
                return winners[val]
            if kind == "RU":
                return runners[val]
            # terza: scegli un gruppo ammesso la cui terza si e' qualificata e non usata
            for g in val:
                c = third_by_group.get(g)
                if c and c not in used_thirds:
                    used_thirds.add(c)
                    return c
            for c in third_pool:  # fallback
                if c not in used_thirds:
                    used_thirds.add(c)
                    return c
            return third_pool[0]

        for mid, sa, sb in R32:
            a, b = resolve(sa), resolve(sb)
            for c in (a, b):
                matches[c] += 1; weighted[c] += ROUND_WEIGHTS["R32"]
            results[mid] = ko_winner(a, b, teams, rng)

        for rnd, weight_key in ((R16, "R16"), (QF, "QF"), (SF, "SF")):
            for mid, ma, mb in rnd:
                a, b = results[ma], results[mb]
                for c in (a, b):
                    matches[c] += 1; weighted[c] += ROUND_WEIGHTS[weight_key]
                results[mid] = ko_winner(a, b, teams, rng)

        mid, ma, mb = FINAL
        a, b = results[ma], results[mb]
        for c in (a, b):
            matches[c] += 1; weighted[c] += ROUND_WEIGHTS["F"]
        results[mid] = ko_winner(a, b, teams, rng)

    for c in matches:
        matches[c] /= sims
        weighted[c] /= sims
    return matches, weighted


# ----------------------------------------------------------------------------
# Proiezione giocatori
# ----------------------------------------------------------------------------
ROLE_MEAN_EG = {"st": 0.30, "m": 0.12, "cb": 0.04}
EG_CAP = {"st": 0.85, "m": 0.50, "cb": 0.20}
CLUB_MATCHES = 38.0
CARDS = 0.22


def fnum(s):
    try:
        return float(s) if s not in (None, "") else None
    except ValueError:
        return None


def load_context():
    ctx = {}
    with CONTEXT.open(newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            ctx[(r["team_code"], r["name"].strip().lower())] = {
                "pen": float(r["pen_share"]), "fk": float(r["freekick"]),
                "avail": float(r["avail"]),
            }
    return ctx


# Confidenza di titolarita per status da probabili formazioni (vedi lineup_sentiment.csv).
STATUS_CONF = {"starter": 0.92, "likely": 0.78, "rotation": 0.5, "doubt": 0.42, "fringe": 0.3}


def load_lineup():
    """Carica lo status di titolarita dalle probabili formazioni (solo nazionali coperte)."""
    flags = {}
    if not LINEUP.exists():
        return flags
    with LINEUP.open(newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            code = (r.get("team_code") or "").strip()
            if not code or code.startswith("#"):
                continue
            status = (r.get("status") or "").strip()
            if status in STATUS_CONF:
                flags[(code, r["name"].strip().lower())] = status
    return flags


# Calibrazione da quote capocannoniere (vedi topscorer_odds.csv).
ODDS_W = 0.6        # peso del segnale di mercato nel blend con la stima da rendimento
ODDS_ANCHOR = 0.8   # tasso gol/partita assegnato al favorito assoluto del mercato
ODDS_EXP = 0.6      # esponente: P(capocannoniere) e' convessa in E[gol] -> radice per invertire


def load_topscorer_odds():
    """Quote capocannoniere -> probabilita implicita per (team_code, name)."""
    imp = {}
    if not ODDS.exists():
        return imp
    with ODDS.open(newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            code = (r.get("team_code") or "").strip()
            name = (r.get("name") or "").strip()
            if not code or not name or name.startswith("#"):
                continue
            try:
                am = float(r["american_odds"])
            except (KeyError, ValueError, TypeError):
                continue
            imp[(code, name.lower())] = 100.0 / (am + 100.0)
    return imp


def odds_goal_rates(imp, e_matches):
    """Converte le prob. implicite in un tasso gol/partita, NETTO del cammino atteso.

    P(capocannoniere) ~ E[gol totali] = tasso/partita x partite attese. Si divide
    quindi per le partite attese della squadra (rimuove il doppio conteggio della
    profondita), si inverte la convessita con una radice e si ancora il favorito a
    ODDS_ANCHOR gol/partita. Restituisce {(code, name): eg_odds}.
    """
    raw = {}
    for (code, name), p in imp.items():
        em = e_matches.get(code)
        if em and em > 0:
            raw[(code, name)] = (p ** ODDS_EXP) / em
    if not raw:
        return {}
    mx = max(raw.values())
    return {k: ODDS_ANCHOR * (v / mx) for k, v in raw.items()}


def rank_based_starter(role, rank):
    if role == "gk":
        return [0.92, 0.12][rank] if rank < 2 else 0.03
    if role == "cb":
        table = [0.88, 0.86, 0.84, 0.82, 0.5, 0.28]
    elif role == "m":
        table = [0.88, 0.86, 0.84, 0.80, 0.45, 0.22]
    else:  # st
        table = [0.88, 0.84, 0.55, 0.30, 0.18]
    return table[rank] if rank < len(table) else 0.1


def build_projections(sims):
    teams = load_strength()
    print(f"Simulo il Mondiale ({sims} run)...", flush=True)
    e_matches, e_weighted = simulate(teams, sims)

    with OUT_SIM.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["team_code", "team_name", "elo", "exp_matches", "exp_weighted_matches"])
        for c in sorted(teams, key=lambda x: -e_matches[x]):
            w.writerow([c, teams[c]["name"], int(teams[c]["elo"]),
                        round(e_matches[c], 3), round(e_weighted[c], 3)])
    print(f"Scritto {OUT_SIM}")

    elos = [t["elo"] for t in teams.values()]
    emin, emax = min(elos), max(elos)

    ctx = load_context()
    lineup = load_lineup()
    eg_odds_map = odds_goal_rates(load_topscorer_odds(), e_matches)
    rows = list(csv.DictReader(LISTONE.open(newline="", encoding="utf-8")))

    # rank per (team, role) sul valore per stimare la titolarita
    by_tr = defaultdict(list)
    for r in rows:
        by_tr[(r["team_name"], r["fanta_role"])].append(r)
    rank = {}
    for key, lst in by_tr.items():
        for i, r in enumerate(sorted(lst, key=lambda x: -float(x["value"]))):
            rank[id(r)] = i

    out = []
    for r in rows:
        role = r["fanta_role"]
        code = r["team_name"]
        value = float(r["value"])
        t = teams.get(code)
        if not t:
            continue
        tnorm = (t["elo"] - emin) / (emax - emin)
        c = ctx.get((code, r["name"].strip().lower()), {"pen": 0.0, "fk": 0.0, "avail": 1.0})

        # --- titolarita ---
        # Segnale primario: lo status dalle probabili formazioni (lineup_sentiment.csv)
        # per le nazionali di interesse. E' l'indicatore piu affidabile di chi gioca.
        status = lineup.get((code, r["name"].strip().lower()))
        if status:
            sp = STATUS_CONF[status]
        else:
            # Fallback (nazionali non coperte): la presenza nazionale recente e' un
            # campione piccolo e distorto (gli europei giocano poche gare ufficiali,
            # i sudamericani 10+ di qualificazione; infortuni/esperimenti la abbassano),
            # quindi la usiamo solo per CONFERMARE un titolare quando e' alta, mai per
            # declassare un big. Segnale base: il rank di quotazione nel reparto.
            ratio = fnum(r.get("national_presence_ratio_current_season"))
            napp = fnum(r.get("national_appearances_current_season"))
            rb = rank_based_starter(role, rank[id(r)])
            if napp is not None and napp >= 5 and ratio is not None:
                sp = 0.5 * rb + 0.5 * min(1.0, ratio + 0.15)
            elif ratio is not None and ratio >= 0.5:
                sp = 0.65 * rb + 0.35 * min(1.0, ratio + 0.2)
            else:
                sp = rb
            # rigoristi/battitori designati sono per definizione titolari
            if c["pen"] >= 0.5 or c["fk"] >= 1:
                sp = max(sp, 0.85)
        sp = max(0.0, min(0.97, sp)) * c["avail"]

        # --- fantapunti netti attesi a partita ---
        base_voto = 6.0 + 0.6 * tnorm
        if role == "gk":
            # Gol subito -1 e portiere imbattuto +1 valgono SOLO per il portiere.
            base_voto = 6.0 + 0.4 * tnorm
            p_cs = max(0.05, min(0.55, 0.08 + 0.45 * tnorm))   # portiere imbattuto +1
            e_gc = max(0.4, min(2.3, 1.7 - 1.3 * tnorm))       # gol subiti attesi
            per_match = base_voto + p_cs - e_gc + 0.03
        else:
            ng = fnum(r.get("national_goals_current_season"))
            na = fnum(r.get("national_appearances_current_season"))
            cg = fnum(r.get("club_goals_current_season"))
            nat_gpm = (ng / na) if (ng is not None and na and na >= 4) else None
            club_gpm = (cg / CLUB_MATCHES) if cg is not None else None
            if nat_gpm is not None and club_gpm is not None:
                eg0 = 0.55 * nat_gpm + 0.45 * club_gpm
            elif nat_gpm is not None:
                eg0 = nat_gpm
            elif club_gpm is not None:
                eg0 = club_gpm
            else:
                eg0 = ROLE_MEAN_EG[role]
            eg = 0.7 * eg0 + 0.3 * ROLE_MEAN_EG[role]
            eg *= 0.85  # contesto nazionale/Mondiale piu' duro del club
            # calibrazione di mercato: per i giocatori quotati capocannoniere si
            # fonde la stima da rendimento col tasso gol/partita implicito nelle quote.
            eo = eg_odds_map.get((code, r["name"].strip().lower()))
            if eo is not None:
                eg = ODDS_W * eo + (1 - ODDS_W) * eg
            eg = min(eg, EG_CAP[role])
            eg += c["pen"] * 0.07          # rigorista designato
            ea = 0.35 * eg + c["fk"] * 0.03 + 0.04
            per_match = base_voto + 3 * eg + 1 * ea - CARDS

        # --- ETP (obiettivo di ottimizzazione) ---
        etp = sp * e_weighted[code] * per_match
        # proxy modificatore difesa per D e P: premia voti base alti (squadre forti)
        mod_proxy = 0.0
        if role in ("cb", "gk"):
            mod_proxy = sp * e_weighted[code] * (tnorm * 1.2)
        etp_obj = etp + mod_proxy

        out.append({
            "fanta_role": role, "name": r["name"], "team_code": code,
            "team_name": t["name"], "value": int(value),
            "elo": int(t["elo"]), "starter_prob": round(sp, 3),
            "exp_matches": round(e_matches[code], 2),
            "exp_weighted_matches": round(e_weighted[code], 2),
            "base_voto": round(base_voto, 3),
            "per_match_pts": round(per_match, 3),
            "etp": round(etp, 2),
            "mod_proxy": round(mod_proxy, 2),
            "etp_obj": round(etp_obj, 2),
            "etp_per_credit": round(etp_obj / value, 3) if value > 0 else 0,
        })

    out.sort(key=lambda x: -x["etp_obj"])
    fields = list(out[0].keys())
    with OUT_PROJ.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(out)
    print(f"Scritto {OUT_PROJ} ({len(out)} giocatori)")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--sims", type=int, default=20000)
    args = ap.parse_args()
    build_projections(args.sims)
