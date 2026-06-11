#!/usr/bin/env python3
"""Stress test di robustezza delle rose agli scenari 'big eliminata'.

Per ogni rosa (file roster_*.csv) e per ogni scenario in cui una/più nazionali
escono ai gironi, ricalcola il valore dell'XI schierabile DALLA STESSA rosa di 25.
Una rosa concentrata perde molto quando la sua big crolla; una con panchina-
assicurazione riesce a rimpiazzare e tiene di più.

Approssimazione: se una nazionale esce ai gironi, i suoi giocatori valgono solo le
3 gare del girone -> etp scalato per (3.0 / partite_pesate_attese). Poi si rischiera
il miglior XI legale (1P+4D, C 3..5, A 1..3) dalla rosa, sui valori di scenario.

Uso: python scripts/stress_test.py [roster_a.csv roster_b.csv ...]
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import pulp

PROJECT_ROOT = Path(__file__).resolve().parent.parent
GROUP_WEIGHTED = 3.0   # partite pesate se la nazionale si ferma ai gironi (3 x peso 1.0)
START_THRESH = 0.55

SCENARIOS = {
    "Base": set(),
    "SPA fuori gironi": {"SPA"},
    "ARG fuori gironi": {"ARG"},
    "SPA+ARG fuori": {"SPA", "ARG"},
}


def load_roster(path):
    rows = []
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            r["etp_obj"] = float(r["etp_obj"])
            r["starter_prob"] = float(r["starter_prob"])
            r["exp_weighted_matches"] = float(r["exp_weighted_matches"])
            rows.append(r)
    return rows


def scenario_scores(roster, eliminated):
    out = []
    for p in roster:
        s = p["etp_obj"]
        if p["team_code"] in eliminated and p["exp_weighted_matches"] > 0:
            s *= GROUP_WEIGHTED / p["exp_weighted_matches"]
        out.append(s)
    return out


def best_xi(roster, scores):
    """Miglior XI legale dalla rosa data, sui punteggi forniti."""
    P = pulp.LpProblem("xi", pulp.LpMaximize)
    f = {i: pulp.LpVariable(f"f_{i}", cat="Binary") for i in range(len(roster))}
    P += pulp.lpSum(scores[i] * f[i] for i in f)
    byr = {"gk": [], "cb": [], "m": [], "st": []}
    for i, p in enumerate(roster):
        byr[p["fanta_role"]].append(i)
        if p["starter_prob"] < START_THRESH:
            P += f[i] == 0
    P += pulp.lpSum(f[i] for i in byr["gk"]) == 1
    P += pulp.lpSum(f[i] for i in byr["cb"]) == 4
    P += pulp.lpSum(f[i] for i in byr["m"] + byr["st"]) == 6
    P += pulp.lpSum(f[i] for i in byr["m"]) >= 3
    P += pulp.lpSum(f[i] for i in byr["m"]) <= 5
    P += pulp.lpSum(f[i] for i in byr["st"]) >= 1
    P += pulp.lpSum(f[i] for i in byr["st"]) <= 3
    P.solve(pulp.PULP_CBC_CMD(msg=0))
    if pulp.LpStatus[P.status] != "Optimal":
        return None
    return sum(scores[i] for i in f if f[i].value() > 0.5)


def main(paths):
    rosters = {Path(p).stem.replace("roster_", ""): load_roster(p) for p in paths}
    print(f"\n=== Stress test robustezza ({len(rosters)} rose) ===")
    print("Valore dell'XI schierabile dalla rosa in ogni scenario (cala = perdita).\n")

    head = f"{'Scenario':<20}" + "".join(f"{name:>14}" for name in rosters)
    print(head)
    print("-" * len(head))
    base = {}
    for sc, elim in SCENARIOS.items():
        cells = []
        for name, roster in rosters.items():
            val = best_xi(roster, scenario_scores(roster, elim))
            if sc == "Base":
                base[name] = val
                cells.append(f"{val:>14.1f}")
            else:
                drop = 100 * (val - base[name]) / base[name]
                cells.append(f"{val:>8.1f}({drop:+.0f}%)")
        print(f"{sc:<20}" + "".join(cells))
    print("\nNota: '(-X%)' = perdita di valore XI rispetto allo scenario Base della stessa rosa.")


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        args = [str(PROJECT_ROOT / f"roster_{l}.csv") for l in ("optimal", "balanced", "aggressive")]
    main(args)
