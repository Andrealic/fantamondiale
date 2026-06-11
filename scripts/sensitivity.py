#!/usr/bin/env python3
"""Analisi di sensibilita della rosa ottimale.

Varia le ipotesi chiave del modello (quanto conta l'Elo nello scarto gol, quanto
si scontano i turni a eliminazione, rumore sugli Elo) e ri-ottimizza, misurando
quanto la rosa resta stabile rispetto al caso base. Una rosa robusta condivide
gran parte dei 25 (e soprattutto dell'XI) tra gli scenari.

Uso: python scripts/sensitivity.py [--sims 8000]
NB: ogni scenario riscrive data/projections.csv come effetto collaterale; alla
fine rilanciare il baseline:
    python scripts/build_projections.py --sims 20000 && python scripts/optimize_roster.py
"""
from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_projections as bp   # noqa: E402
import optimize_roster as opt     # noqa: E402

BUDGET = 250


def key(p):
    return f"{p['name']} ({p['team_code']})"


def run_scenario(sims, elo_scale=None, round_weights=None, elo_noise=0.0, seed=99):
    orig_scale = bp.ELO_SCALE
    orig_weights = dict(bp.ROUND_WEIGHTS)
    orig_load = bp.load_strength
    try:
        if elo_scale is not None:
            bp.ELO_SCALE = elo_scale
        if round_weights is not None:
            bp.ROUND_WEIGHTS = round_weights
        if elo_noise:
            rng = random.Random(seed)

            def noisy():
                teams = orig_load()
                for t in teams.values():
                    t["elo"] += rng.uniform(-elo_noise, elo_noise)
                return teams
            bp.load_strength = noisy

        out = bp.build_projections(sims)
        status, chosen, fielded = opt.optimize(out, BUDGET)
        assert status == "Optimal"
        roster = {key(out[i]) for i in chosen}
        xi = {key(out[i]) for i in fielded}
        return roster, xi
    finally:
        bp.ELO_SCALE = orig_scale
        bp.ROUND_WEIGHTS = orig_weights
        bp.load_strength = orig_load


def steeper():   # valorizza quasi solo i gironi
    return {"group": 1.0, "R32": 0.7, "R16": 0.45, "QF": 0.3, "SF": 0.2, "F": 0.12}


def flatter():   # valorizza di piu le fasi avanzate
    return {"group": 1.0, "R32": 0.95, "R16": 0.88, "QF": 0.8, "SF": 0.72, "F": 0.65}


def main(sims):
    scenarios = [
        ("Baseline (ELO_SCALE=125, pesi std)", {}),
        ("Elo piu determinante (scale=100)", {"elo_scale": 100}),
        ("Elo meno determinante (scale=160)", {"elo_scale": 160}),
        ("Pesi ripidi (conta solo il girone)", {"round_weights": steeper()}),
        ("Pesi piatti (premia le fasi avanzate)", {"round_weights": flatter()}),
        ("Rumore Elo +-40", {"elo_noise": 40.0}),
        ("Rumore Elo +-80", {"elo_noise": 80.0}),
    ]

    print(f"\n=== Analisi di sensibilita ({sims} sim/scenario) ===\n")
    base_roster, base_xi = run_scenario(sims, **scenarios[0][1])

    rows = [("Scenario", "Rosa ∩ base /25", "XI ∩ base /11", "Nuovi ingressi rosa")]
    rows.append((scenarios[0][0], "25/25", "11/11", "-"))
    for label, kw in scenarios[1:]:
        roster, xi = run_scenario(sims, **kw)
        shared_r = len(roster & base_roster)
        shared_x = len(xi & base_xi)
        newcomers = ", ".join(sorted(roster - base_roster)) or "-"
        rows.append((label, f"{shared_r}/25", f"{shared_x}/11", newcomers))

    w0 = max(len(r[0]) for r in rows)
    print(f"{rows[0][0]:<{w0}}  {rows[0][1]:<14}  {rows[0][2]:<13}  {rows[0][3]}")
    print("-" * (w0 + 50))
    for r in rows[1:]:
        print(f"{r[0]:<{w0}}  {r[1]:<14}  {r[2]:<13}  {r[3]}")
    print("\nXI base:", ", ".join(sorted(base_xi)))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--sims", type=int, default=8000)
    main(ap.parse_args().sims)
