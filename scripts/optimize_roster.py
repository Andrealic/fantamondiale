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
OUT_CSV = PROJECT_ROOT / "roster_optimal.csv"
OUT_MD = PROJECT_ROOT / "ROSTER.md"

ROLE_QUOTA = {"gk": 3, "cb": 8, "m": 8, "st": 6}
XI_GK, XI_CB, XI_OUT = 1, 4, 6          # 1 portiere + 4 difensori + 6 tra C/A
ROLE_LABEL = {"gk": "Portieri (P)", "cb": "Difensori (D)", "m": "Centrocampisti (C)", "st": "Attaccanti (A)"}
ROLE_ORDER = ["gk", "cb", "m", "st"]

START_THRESH = 0.55     # soglia per essere schierabile nell'XI tipo
ALIVE_THRESH = 0.18     # soglia minima per occupare uno slot rosa (no "morti")
BENCH_WEIGHT = 0.05     # peso residuo dell'ETP delle riserve (qualita panchina, tie-break)


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


def optimize(players, budget):
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
        # schierabile solo se titolare plausibile
        if players[i]["starter_prob"] < START_THRESH:
            P += f[i] == 0
        # nessuna riserva "morta"
        if players[i]["starter_prob"] < ALIVE_THRESH:
            P += x[i] == 0

    P.solve(pulp.PULP_CBC_CMD(msg=0))
    status = pulp.LpStatus[P.status]
    chosen = [i for i in x if x[i].value() > 0.5]
    fielded = {i for i in x if f[i].value() > 0.5}
    return status, chosen, fielded


def main(budget):
    players = load_players()
    status, chosen, fielded = optimize(players, budget)
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
    with OUT_CSV.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for p in roster:
            w.writerow(p)
    print(f"Scritto {OUT_CSV}")

    write_markdown(roster, spent, budget)
    print(f"Scritto {OUT_MD}")

    # --- sintesi a video ---
    print(f"\nStatus: {status} | speso {spent}/{budget} crediti | XI tipo: {len(fielded)} giocatori")
    print(f"ETP XI tipo (a giornata): {sum(p['etp_obj'] for p in roster if p['_xi']):.1f}")


def write_markdown(roster, spent, budget):
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

    lines = []
    lines.append("# Rosa ottimale — Fantamondiale 2026\n")
    lines.append(f"**Budget**: {spent}/{budget} crediti spesi "
                 f"(residuo {budget - spent}).  ")
    lines.append("**Modulo**: difesa a 4 (P + 4D + 6 tra C/A) per attivare il modificatore difesa.  ")
    lines.append(f"**Capitano 1ª giornata**: {cap['name']} ({cap['team_code']}) — "
                 f"vice {vice['name']} ({vice['team_code']}).\n")

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
    lines.append("- **Nota concentrazione**: nessun cap per nazionale → conviene un blocco sulla nazionale "
                 "più forte e profonda (Spagna, ~7 partite attese, minor rischio eliminazione). Trade-off: "
                 "rischio di correlazione (giornata-no della Spagna), mitigabile coi cambi.")

    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget", type=int, default=250)
    main(ap.parse_args().budget)
