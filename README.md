# Fantamondiale 2026 — rosa ottimale via modello

Pipeline per scegliere la rosa iniziale ottimale di un Fantamondiale (Mondiale FIFA 2026,
modalità listone, 250 crediti) massimizzando i fantapunti totali attesi.

## Output principale
- **[`ROSTER.md`](ROSTER.md)** — la rosa adottata (XI tipo, capitano, panchina, candidati ai cambi).
- **[`DECISIONI.md`](DECISIONI.md)** — decisioni di modellazione, assunzioni, analisi e roadmap.

## Tre approcci (si usa solo `roster`/`ROSTER.md`)
| File | Approccio | Note |
|---|---|---|
| `ROSTER.md` / `roster_optimal.csv` | **scelto** | blocco difesa libero + max 2 attaccanti/naz |
| `ROSTER_balanced.md` / `roster_balanced.csv` | bilanciato | max 4 titolari/naz nell'XI |
| `ROSTER_aggressive.md` / `roster_aggressive.csv` | aggressivo | max 3 titolari/naz nell'XI |

## Come si rigenera
```bash
pip install --index-url https://pypi.org/simple/ pulp     # il pip di default punta a un index privato
python scripts/build_projections.py --sims 20000          # -> data/projections.csv, data/wc2026_sim.csv
python scripts/optimize_roster.py --attack-cap 2 \        # -> roster_optimal.csv, ROSTER.md
  --include-xi "FRA:Maignan" --include "FRA:Risser" --include "FRA:Samba" \
  --exclude "ARG:Mac Allister" --exclude "SPA:Pedri"
python scripts/stress_test.py                             # robustezza "big fuori"
python scripts/sensitivity.py --sims 8000                 # stabilità della rosa
```

## Componenti
- `scripts/build_projections.py` — simulazione Monte Carlo del tabellone (Elo) + fantapunti attesi per ruolo (ETP).
- `scripts/optimize_roster.py` — ILP (`pulp`) che sceglie i 25 e l'XI tipo; cap di diversificazione e forzature manuali.
- `scripts/stress_test.py`, `scripts/sensitivity.py` — robustezza e stabilità.
- `data/` — input: `wc2026_team_strength.csv` (Elo), `player_context.csv` (rigoristi/disponibilità/cartellini),
  `lineup_sentiment.csv` (probabili formazioni), `topscorer_odds.csv` (quote capocannoniere). `data/cache/` è ignorata.

Dettagli completi in [`DECISIONI.md`](DECISIONI.md).
