#!/usr/bin/env python3
"""Ottimizza la rosa iniziale del Fantamondiale via ILP (pulp).

Idea (dal piano): si schierano 11/giornata, non 25. La rosa iniziale quindi
massimizza l'ETP dell'**XI tipo** (1 P + 4 D + 6 tra C/A, difesa a 4 per il
modificatore) spendendo il budget sui titolari forti e su un blocco difensivo
coeso; gli altri 14 slot (panchina/riserve) si riempiono al minor prezzo perche
sono rimpiazzabili coi 10 cambi in corso di torneo.

Vincoli:
  - composizione rosa: 3 P / 8 D / 8 C / 6 A (= 25)
  - Sum(value) <= 250
  - XI tipo: 1 P, 4 D, 6 tra C/A; solo titolari plausibili (starter_prob >= soglia)
  - le riserve devono comunque essere giocatori "vivi" (starter_prob >= soglia bassa)

Uso: python scripts/optimize_roster.py [--budget 250]
"""
from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path

import pulp

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA = PROJECT_ROOT / "data"
PROJ = DATA / "projections.csv"

ROLE_QUOTA = {"gk": 3, "cb": 8, "m": 8, "st": 6}
XI_GK, XI_CB, XI_OUT = 1, 4, 6          # 1 portiere + 4 difensori + 6 tra C/A
ROLE_LABEL = {"gk": "Portieri (P)", "cb": "Difensori (D)", "m": "Centrocampisti (C)", "st": "Attaccanti (A)"}
ROLE_ORDER = ["gk", "cb", "m", "st"]

START_THRESH = 0.55     # soglia per essere schierabile nell'XI tipo
BENCH_WEIGHT = 0.05     # peso residuo dell'ETP delle riserve (qualita panchina, tie-break)
# La panchina deve dare copertura reale: solo titolari/riserve di nazionali che
# arrivano almeno agli ottavi (E[match] >= soglia). Una riserva di una squadra che
# esce ai gironi e' un cambio obbligato mascherato, non un'assicurazione.
BENCH_TEAM_MIN = 4.5    # E[match] minimo della nazionale per occupare uno slot rosa
ALIVE_THRESH = 0.30     # soglia minima di titolarita per occupare uno slot rosa


def load_players():
    rows = []
    with PROJ.open(newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            r["value"] = int(r["value"])
            r["etp_obj"] = float(r["etp_obj"])
            r["etp"] = float(r["etp"])
            r["starter_prob"] = float(r["starter_prob"])
            r["base_voto"] = float(r["base_voto"])
            r["per_match_pts"] = float(r["per_match_pts"])
            r["exp_matches"] = float(r["exp_matches"])
            r["exp_weighted_matches"] = float(r["exp_weighted_matches"])
            rows.append(r)
    return rows


def optimize(players, budget, max_per_nation=None, attack_cap=None,
             bench_team_min=BENCH_TEAM_MIN, include_xi=(), include_roster=(), exclude=()):
    include_xi, include_roster, exclude = set(include_xi), set(include_roster), set(exclude)
    P = pulp.LpProblem("fantamondiale_roster", pulp.LpMaximize)

    # x = in rosa; f = schierato nell'XI tipo (f <= x)
    x = {i: pulp.LpVariable(f"x_{i}", cat="Binary") for i in range(len(players))}
    f = {i: pulp.LpVariable(f"f_{i}", cat="Binary") for i in range(len(players))}

    # Obiettivo: ETP dell'XI tipo + piccolo peso sulla qualita della panchina
    P += (
        pulp.lpSum(players[i]["etp_obj"] * f[i] for i in x)
        + BENCH_WEIGHT * pulp.lpSum(players[i]["etp"] * (x[i] - f[i]) for i in x)
    )

    # Budget
    P += pulp.lpSum(players[i]["value"] * x[i] for i in x) <= budget

    by_role = defaultdict(list)
    for i, p in enumerate(players):
        by_role[p["fanta_role"]].append(i)

    # Composizione rosa
    for role, q in ROLE_QUOTA.items():
        P += pulp.lpSum(x[i] for i in by_role[role]) == q

    # XI tipo: 1 P, 4 D, 6 tra C/A in un modulo legale a 4 dietro
    # (4-3-3 / 4-4-2 / 4-5-1 -> centrocampisti 3..5, attaccanti 1..3).
    P += pulp.lpSum(f[i] for i in by_role["gk"]) == XI_GK
    P += pulp.lpSum(f[i] for i in by_role["cb"]) == XI_CB
    P += pulp.lpSum(f[i] for i in by_role["m"] + by_role["st"]) == XI_OUT
    P += pulp.lpSum(f[i] for i in by_role["m"]) >= 3
    P += pulp.lpSum(f[i] for i in by_role["m"]) <= 5
    P += pulp.lpSum(f[i] for i in by_role["st"]) >= 1
    P += pulp.lpSum(f[i] for i in by_role["st"]) <= 3

    for i in x:
        P += f[i] <= x[i]
        key = (players[i]["team_code"], players[i]["name"].strip().lower())
        if key in exclude:                       # forzato fuori
            P += x[i] == 0
            continue
        forced_x = key in include_roster or key in include_xi
        forced_f = key in include_xi
        if forced_x:
            P += x[i] == 1
        if forced_f:
            P += f[i] == 1
        # schierabile solo se titolare plausibile (salvo forzatura)
        if not forced_f and players[i]["starter_prob"] < START_THRESH:
            P += f[i] == 0
        # in rosa solo giocatori "vivi" di nazionali che vanno avanti (salvo forzatura)
        if not forced_x and (players[i]["starter_prob"] < ALIVE_THRESH
                             or players[i]["exp_matches"] < bench_team_min):
            P += x[i] == 0

    # Cap di concentrazione: max titolari per nazionale nell'XI (riduce il rischio
    # di crollo se una big esce; None = nessun cap).
    by_nat = defaultdict(list)
    for i, p in enumerate(players):
        by_nat[p["team_code"]].append(i)
    if max_per_nation is not None:
        for nat, idxs in by_nat.items():
            P += pulp.lpSum(f[i] for i in idxs) <= max_per_nation
    # Variante ibrida: cap solo sugli ATTACCANTI (m+st) per nazionale, lasciando
    # libero il blocco difensivo (GK+D) -> resta coeso per il modificatore, ma
    # l'attacco e' diversificato su piu nazionali.
    if attack_cap is not None:
        for nat, idxs in by_nat.items():
            atk = [i for i in idxs if players[i]["fanta_role"] in ("m", "st")]
            if atk:
                P += pulp.lpSum(f[i] for i in atk) <= attack_cap

    P.solve(pulp.PULP_CBC_CMD(msg=0))
    status = pulp.LpStatus[P.status]
    chosen = [i for i in x if x[i].value() > 0.5]
    fielded = {i for i in x if f[i].value() > 0.5}
    return status, chosen, fielded


def parse_keys(items):
    """Converte 'CODE:Nome' -> (CODE, nome.lower())."""
    out = []
    for s in items or []:
        code, _, name = s.partition(":")
        out.append((code.strip(), name.strip().lower()))
    return out


def main(budget=250, max_per_nation=None, attack_cap=None, label="optimal", title="Rosa ottimale",
         include_xi=(), include_roster=(), exclude=()):
    out_csv = PROJECT_ROOT / f"roster_{label}.csv"
    out_md = PROJECT_ROOT / (f"ROSTER_{label}.md" if label != "optimal" else "ROSTER.md")

    players = load_players()
    status, chosen, fielded = optimize(players, budget, max_per_nation=max_per_nation,
                                       attack_cap=attack_cap, include_xi=include_xi,
                                       include_roster=include_roster, exclude=exclude)
    assert status == "Optimal", f"ILP non risolto: {status}"

    # --- asserzioni vincoli ---
    cnt = defaultdict(int)
    for i in chosen:
        cnt[players[i]["fanta_role"]] += 1
    assert cnt == ROLE_QUOTA, f"composizione errata: {dict(cnt)}"
    spent = sum(players[i]["value"] for i in chosen)
    assert spent <= budget, f"budget sforato: {spent}"
    assert len(fielded) == 11, f"XI != 11: {len(fielded)}"

    roster = sorted(
        (players[i] | {"_xi": i in fielded} for i in chosen),
        key=lambda p: (ROLE_ORDER.index(p["fanta_role"]), -p["_xi"], -p["etp_obj"]),
    )

    # --- CSV ---
    fields = ["fanta_role", "name", "team_code", "team_name", "value", "elo",
              "starter_prob", "exp_matches", "exp_weighted_matches", "base_voto",
              "per_match_pts", "etp", "etp_obj", "_xi"]
    with out_csv.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for p in roster:
            w.writerow(p)

    div_txt = (f"cap {max_per_nation} titolari/nazionale" if max_per_nation
               else f"blocco difensivo libero + max {attack_cap} attaccanti/nazionale" if attack_cap
               else "nessun cap per nazionale")
    write_markdown(roster, spent, budget, out_md, title, div_txt,
                   diversified=bool(max_per_nation or attack_cap))

    # --- sintesi a video ---
    xi = [p for p in roster if p["_xi"]]
    nat = defaultdict(float)
    tot = sum(p["etp_obj"] for p in xi)
    for p in xi:
        nat[p["team_code"]] += p["etp_obj"]
    top2 = sorted(nat.values(), reverse=True)[:2]
    print(f"[{label}] cap/naz={max_per_nation} | speso {spent}/{budget} | "
          f"ETP XI {tot:.1f} | top-2 naz {100*sum(top2)/tot:.0f}% dell'ETP | "
          f"-> {out_csv.name}, {out_md.name}")


def write_markdown(roster, spent, budget, out_md, title, div_txt, diversified):
    xi = [p for p in roster if p["_xi"]]
    bench = [p for p in roster if not p["_xi"]]
    # Il bonus capitano premia il VOTO BASE senza bonus/malus (>=7 -> +1, >=9 -> +3).
    # Si capitana quindi un "6 assicurato": titolare affidabile della nazionale piu
    # forte, alto voto base e alta probabilita di gioco (tipicamente un difensore o
    # centrocampista di vertice). Un attaccante da' piu upside ma piu varianza.
    def cap_key(p):
        return (p["base_voto"], p["starter_prob"])
    pool = [p for p in xi if p["starter_prob"] >= 0.78] or xi
    cap = max(pool, key=cap_key)
    vice = max((p for p in pool if p is not cap), key=cap_key)
    # candidati ai cambi: titolari/riserve da nazionali con poche partite attese
    transfer = sorted(roster, key=lambda p: (p["exp_matches"], -p["value"]))[:6]

    def row(p):
        flag = " ⭐" if p is cap else (" (V)" if p is vice else "")
        return (f"| {p['name']}{flag} | {p['team_code']} | {p['value']} | "
                f"{p['starter_prob']:.2f} | {p['exp_matches']:.1f} | "
                f"{p['base_voto']:.2f} | {p['etp_obj']:.1f} |")

    # esposizione per nazionale nell'XI
    nat_etp = defaultdict(float)
    nat_xi = defaultdict(int)
    tot_etp = sum(p["etp_obj"] for p in xi)
    for p in xi:
        nat_etp[p["team_code"]] += p["etp_obj"]
        nat_xi[p["team_code"]] += 1

    lines = []
    lines.append(f"# {title} — Fantamondiale 2026\n")
    lines.append(f"**Budget**: {spent}/{budget} crediti spesi "
                 f"(residuo {budget - spent}).  ")
    lines.append("**Modulo**: difesa a 4 (P + 4D + 6 tra C/A) per attivare il modificatore difesa.  ")
    lines.append(f"**Diversificazione**: {div_txt}.  ")
    lines.append(f"**Capitano 1ª giornata**: {cap['name']} ({cap['team_code']}) — "
                 f"vice {vice['name']} ({vice['team_code']}).\n")

    lines.append("## Esposizione per nazionale (XI)\n")
    lines.append("| Naz | Titolari XI | % ETP XI |")
    lines.append("|---|---|---|")
    for n in sorted(nat_etp, key=lambda x: -nat_etp[x]):
        lines.append(f"| {n} | {nat_xi[n]} | {100*nat_etp[n]/tot_etp:.0f}% |")
    lines.append("")

    lines.append("## XI tipo di partenza\n")
    lines.append("| Giocatore | Naz | Cr | P(tit) | E[match] | Voto base | ETP |")
    lines.append("|---|---|---|---|---|---|---|")
    for role in ROLE_ORDER:
        for p in xi:
            if p["fanta_role"] == role:
                lines.append(row(p))
    lines.append("")

    lines.append("## Rosa completa (25)\n")
    for role in ROLE_ORDER:
        grp = [p for p in roster if p["fanta_role"] == role]
        tot = sum(p["value"] for p in grp)
        lines.append(f"### {ROLE_LABEL[role]} — {len(grp)} ({tot} cr)\n")
        lines.append("| Giocatore | Naz | Cr | P(tit) | E[match] | Voto base | ETP | XI |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for p in grp:
            lines.append(row(p)[:-1] + f" {'✅' if p['_xi'] else '—'} |")
        lines.append("")

    lines.append("## Primi candidati ai cambi\n")
    lines.append("Giocatori da nazionali con meno partite attese: primi da rimpiazzare "
                 "coi 10 trasferimenti dopo i gironi (riorientarsi sulle superstiti).\n")
    lines.append("| Giocatore | Naz | Ruolo | E[match] | Cr |")
    lines.append("|---|---|---|---|---|")
    for p in transfer:
        lines.append(f"| {p['name']} | {p['team_code']} | {p['fanta_role']} | "
                     f"{p['exp_matches']:.1f} | {p['value']} |")
    lines.append("")

    lines.append("## Razionale\n")
    lines.append("- **Obiettivo**: massimizzare i fantapunti totali attesi (ETP) dell'XI "
                 "schierato per giornata, non la somma dei 25; gli slot panchina vanno al "
                 "minor prezzo perche rimpiazzabili coi cambi.")
    lines.append("- **Titolarità**: per le nazionali di interesse la probabilità di gioco viene dalle "
                 "**probabili formazioni** (web, ~11/06/2026, `data/lineup_sentiment.csv`), non dalle sole "
                 "presenze recenti — così si schierano i titolari veri e non gregari con tante amichevoli.")
    lines.append("- **ETP** = P(titolarita) × E[partite pesate per fase] × fantapunti netti/partita. "
                 "I turni a eliminazione sono scontati: i giocatori delle eliminate si sostituiscono "
                 "in corsa, quindi la rosa iniziale non sovra-paga la 'finale'.")
    lines.append("- **Blocco difensivo**: difensori e portiere di nazionali solide e profonde "
                 "alzano la media migliori-3-D+P sopra le soglie del modificatore (+1/+3/+6).")
    lines.append("- **Capitano**: il bonus (−3…+3) premia il **voto base senza bonus/malus** "
                 "(≥7 → +1, ≥9 → +3), quindi si capitana un \"6 assicurato\": titolare affidabile "
                 "della nazionale più forte (qui un difensore/centrocampista spagnolo di vertice). "
                 "Un attaccante darebbe più upside ma con più varianza.")
    lines.append("- **Panchina-assicurazione**: le riserve sono titolari/giocatori low-cost di sole "
                 "nazionali che arrivano almeno agli ottavi (E[match] ≥ soglia) — niente gente di squadre "
                 "che escono ai gironi (sarebbe un cambio obbligato mascherato).")
    if diversified:
        lines.append(f"- **Diversificazione ({div_txt})**: l'XI non dipende da una sola nazionale, così "
                     "l'eliminazione a sorpresa di una big non azzera il rendimento mentre gli altri manager "
                     "continuano a segnare. Costo: qualche punto di ETP atteso in meno (e, se si cappano anche "
                     "i difensori, minore coerenza del blocco-modificatore).")
    else:
        lines.append("- **Nota concentrazione**: nessun cap per nazionale → blocco sulla nazionale più forte "
                     "e profonda. Massimo ETP atteso ma alta correlazione (esposto al crollo di una big).")
    lines.append("- **Cartellini**: malus gialli stimato per-giocatore (es. Romero/Otamendi, difensori "
                 "argentini propensi al giallo, pesati di più della media).")

    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget", type=int, default=250)
    ap.add_argument("--max-per-nation", type=int, default=None,
                    help="cap titolari per nazionale nell'XI (default: nessun cap)")
    ap.add_argument("--attack-cap", type=int, default=None,
                    help="cap attaccanti (C+A) per nazionale; lascia libero il blocco difensivo")
    ap.add_argument("--label", default="optimal", help="suffisso dei file di output")
    ap.add_argument("--title", default="Rosa ottimale")
    ap.add_argument("--variants", action="store_true",
                    help="genera optimal / balanced / aggressive / hybrid in un colpo")
    ap.add_argument("--include-xi", action="append", default=[], metavar="CODE:Nome",
                    help="forza un giocatore nell'XI (ripetibile)")
    ap.add_argument("--include", action="append", default=[], metavar="CODE:Nome",
                    help="forza un giocatore in rosa (panchina ok; ripetibile)")
    ap.add_argument("--exclude", action="append", default=[], metavar="CODE:Nome",
                    help="esclude un giocatore dalla rosa (ripetibile)")
    args = ap.parse_args()

    inc_xi = parse_keys(args.include_xi)
    inc_r = parse_keys(args.include)
    exc = parse_keys(args.exclude)

    if args.variants:
        for lbl, kw in [("optimal", {}), ("balanced", {"max_per_nation": 4}),
                        ("aggressive", {"max_per_nation": 3}), ("hybrid", {"attack_cap": 2})]:
            main(args.budget, label=lbl, title=f"Rosa {lbl}",
                 include_xi=inc_xi, include_roster=inc_r, exclude=exc, **kw)
    else:
        main(args.budget, max_per_nation=args.max_per_nation, attack_cap=args.attack_cap,
             label=args.label, title=args.title,
             include_xi=inc_xi, include_roster=inc_r, exclude=exc)
