# Fantamondiale 2026 — Decisioni, assunzioni e roadmap

Documento di accompagnamento alla rosa in [`ROSTER.md`](ROSTER.md). Spiega **come** è
stata costruita la rosa, **su quali ipotesi** si regge e **come la migliorerei**.

---

## 1. Obiettivo e inquadramento

- **Modalità listone**: 250 crediti, 12 manager, nessuna esclusiva tra le rose, **10 cambi**
  effettuabili in qualsiasi momento del torneo. Non c'è scarsità → l'obiettivo è
  **massimizzare i fantapunti totali attesi**, non gestire risorse contese.
- **Deliverable**: la **rosa iniziale ottimale** (25 = 3P/8D/8C/6A, difesa a 4). Gestione
  giornaliera, capitano e cambi sono informativi.
- **Intuizione centrale**: i 10 cambi "in qualsiasi momento" **accorciano l'orizzonte** della
  rosa iniziale. I giocatori di nazionali eliminate si rimpiazzano in corsa, quindi non si
  sovra-paga ora per profili che valgono solo arrivando in finale: si ottimizza su un orizzonte
  breve-medio (gironi — 3 gare garantite per tutte e 48 — più i primi turni a eliminazione),
  tenendo un **core di nazionali profonde** per minimizzare i cambi necessari più avanti.

## 2. Pipeline

```
fantapazz_listone_enriched.csv ─┐
data/wc2026_team_strength.csv ──┤
data/player_context.csv ────────┤
data/lineup_sentiment.csv ──────┼─► build_projections.py ─► data/projections.csv  ─► optimize_roster.py ─► roster_optimal.csv
data/topscorer_odds.csv ────────┘    (Monte Carlo + ETP)     data/wc2026_sim.csv      (ILP best-XI)        ROSTER.md
```

Esecuzione:
```bash
pip install --index-url https://pypi.org/simple/ pulp        # pip di default punta a CodeArtifact privato
python scripts/build_projections.py --sims 20000
python scripts/optimize_roster.py
python scripts/sensitivity.py --sims 8000                    # opzionale: robustezza
```

## 3. Decisioni di modellazione

### 3.1 Simulazione del Mondiale (Monte Carlo)
- **Elo → gol attesi**: ogni partita è due Poisson con medie derivate dallo scarto Elo
  (`ELO_SCALE=125`: ~1 gol di supremazia ogni 125 punti) attorno a 2.6 gol totali/partita.
- **Tabellone ufficiale FIFA 48 squadre** cablato (R32→finale), incluse le 8 migliori terze
  assegnate agli slot rispettando i gruppi ammessi. 20.000 simulazioni.
- Output per nazionale: **partite attese** e **partite attese pesate per fase**.

### 3.2 Sconto delle fasi (il punto più "opinabile")
I round a eliminazione sono pesati in modo decrescente
(`gironi 1.0, R32 0.9, R16 0.75, QF 0.6, SF 0.45, F 0.35`): riflette che i giocatori delle
eliminate si sostituiscono coi 10 cambi, quindi la rosa iniziale non deve pagare la profondità
"recuperabile". **È un'assunzione, non un dato** — vedi sensibilità (§5).

### 3.3 Fantapunti netti attesi a partita (per ruolo)
Bonus/malus dalle immagini ufficiali (gol +3, rigore +3, assist +1, gol-vittoria +1, ammonizione
−0,5, espulsione −1, autogol −3; **rigore parato +3 e porta inviolata +1 solo P**).
- **A/C**: `voto_base + 3·E[gol] + 1·E[assist] − cartellini`. E[gol] stimato da gol in
  nazionale (se ≥4 presenze) e gol di club normalizzati a "per partita", regrediti verso la media
  di ruolo, scontati 0.85 (contesto Mondiale più duro), con tetto per ruolo; bonus rigoristi e
  specialisti su palla inattiva da `player_context.csv`.
- **D**: come sopra con contributi offensivi minori; il valore del **modificatore difesa** è
  modellato a parte (§3.5).
- **P**: `voto_base + P(porta inviolata) − E[gol subiti] + bonus`. Porta inviolata e gol subiti
  **si inferiscono dalla forza della nazionale** (più è forte, meno subisce).
- **Voto base** ≈ `6.0 + 0.6·forza_normalizzata` (6.0 + 0.4 per i portieri).

### 3.3-bis Calibrazione di mercato per E[gol] (quote capocannoniere)
Per gli attaccanti/rifinitori quotati per il Golden Boot (`data/topscorer_odds.csv`, ~17 giocatori,
quote consolidate FOX/SI) si **fonde** la stima da rendimento con il tasso gol/partita implicito nel
mercato (`ODDS_W = 0.6` sul mercato). **Anti-doppio-conteggio**: la quota capocannoniere incorpora già
quante partite uno gioca e i rigori, mentre l'ETP moltiplica già per le partite attese; quindi la
probabilità implicita (`100/(odds+100)`) viene **divisa per le partite attese della squadra** per
ottenere un *tasso per partita*, se ne inverte la convessità con una radice (`P(capocannoniere)` cresce
più che linearmente in E[gol]) e si **ancora il favorito** a 0.8 gol/partita. Effetto: riordina il
vertice offensivo secondo il mercato (Mbappé/Oyarzabal/Messi su, Olise/Lautaro giù) — es. Mbappé entra
nell'XI al posto di Olise. Copre solo i bomber di vertice; per gli altri resta la stima da rendimento.

### 3.4 Probabilità di titolarità (la leva più importante)
Il segnale primario è lo **status dalle probabili formazioni** raccolte sul web (~11/06/2026) per le
**nazionali di interesse**, in `data/lineup_sentiment.csv`: `starter` → 0.92, `likely` → 0.78,
`rotation` → 0.50, `doubt` → 0.42, `fringe` → 0.30. È l'indicatore più affidabile di chi gioca
davvero e ha corretto errori grossi (es. in Spagna Grimaldo/Porro/Zubimendi/Ferran Torres **non**
sono titolari previsti; in Francia Barcola è fuori dall'XI — il modello li schierava).

**Perché non bastano le presenze**: la `national_presence_ratio` del listone è `presenze/10`,
campione piccolo e **distorto per confederazione** (gli europei giocano poche gare ufficiali, i
sudamericani 10+ di qualificazione) → premiava i sudamericani e affossava i big europei
(Mbappé/Kane/Yamal a ~0.4). Per le nazionali **non coperte** dalle formazioni si usa quindi un
fallback: rank di quotazione nel reparto come base, col ratio solo a *confermare* (mai a declassare),
e override per i rigoristi designati. `avail` da `player_context.csv` applica gli infortuni noti
(es. Yamal rientro stimato dalla 3ª di girone, Lukaku condizione).

Nazionali coperte dalle formazioni: SPA, FRA, ARG, ING, BRA, POR, OLA, GER, COL, BEL, CRO (quelle che
possono fornire titolari all'XI). Le altre contribuiscono solo riserve a basso costo, dove la
precisione conta poco.

### 3.5 Modificatore difesa
È un effetto **di blocco** (media migliori 3 D + P della giornata: ≥6 → +1, ≥6,5 → +3, ≥7 → +6),
non additivo per singolo. Approssimato con un termine `mod_proxy` scommato all'ETP di D e P che
premia D/P di nazionali forti (che vincono e prendono voti alti), così l'ottimizzatore tende a
**concentrare un blocco difensivo coeso** di una nazionale solida. Coerenza verificata a posteriori
sulla rosa scelta (qui: P + 4 D tutti spagnoli → giocano sempre la stessa giornata).

### 3.6 Capitano
Il bonus capitano (−3…+3) è sul **voto base senza bonus/malus** (≥7 → +1, ≥9 → +3). Premia quindi
un **"6 assicurato"**: titolare affidabile della nazionale più forte (alto voto base, alta
probabilità di gioco) — tipicamente un difensore/centrocampista di vertice. Un attaccante dà più
upside ma più varianza. Scelta del codice: massimo voto base tra i titolari con `P(tit) ≥ 0.78`.

### 3.7 Ottimizzazione (ILP)
`pulp` massimizza l'**ETP dell'XI tipo** (1 P + 4 D + 6 tra C/A in **modulo legale**: C 3–5, A 1–3)
più un peso residuo (0.05) sulla qualità della panchina. Vincoli: composizione 3/8/8/6, budget ≤250,
XI solo da titolari plausibili (`P(tit) ≥ 0.55`), nessuna riserva "morta" (`P(tit) ≥ 0.18`).
**Razionale**: si schierano 11/giornata, non 25 → si spende sui titolari forti e sul blocco difensivo,
e si riempiono gli slot panchina al minor prezzo perché rimpiazzabili coi 10 cambi.

## 4. Assunzioni esplicite (da validare)

1. **Forza = Elo** di eloratings.net (più quote come sanity check). Niente forma recente fine,
   infortuni dell'ultimo minuto, meteo, allenatore, modulo specifico per nazionale.
2. **Sconto delle fasi** (§3.2): scelta di design, non misurata.
3. **E[gol]/E[assist]** da club+nazionale normalizzati e regrediti: i rigoristi/specialisti
   corretti a mano solo per i casi noti in `player_context.csv` (~30 giocatori delle top).
4. **Portieri non arricchiti** e **17 giocatori non matchati** esclusi (scelta dell'utente):
   il titolare di una big è ovvio e la solidità si inferisce dalla forza squadra.
5. **Modificatore difesa** trattato come proxy lineare, non come vera media-migliori-3 stocastica.
6. **Nessun cap per nazionale** → concentrazione ottimale ma correlata (vedi §6).

## 5. Analisi di sensibilità (`scripts/sensitivity.py`)

Variando le ipotesi chiave e ri-ottimizzando (8.000 sim/scenario):

| Scenario | Rosa ∩ base /25 | XI ∩ base /11 |
|---|---|---|
| Elo più determinante (scale=100) | 22 | 11 |
| Elo meno determinante (scale=160) | 23 | 11 |
| Pesi ripidi (conta solo il girone) | 19 | 10 |
| Pesi piatti (premia le fasi avanzate) | 22 | 11 |
| Rumore Elo ±40 | 23 | 11 |
| Rumore Elo ±80 | 14 | 6 |

**Lettura**: con i flag delle probabili formazioni l'**XI core è molto robusto** (10–11/11 sotto tutte
le perturbazioni ragionevoli: i titolari sono "ancorati" dalle formazioni, non dalla simulazione). Il
turnover è quasi tutto sulla **panchina**, fodder a basso costo e per definizione volatile/rimpiazzabile
coi cambi. Solo con rumore estremo ±80 (che riscrive i favoriti del torneo) il core si muove davvero. Lo
scenario "pesi ripidi" resta quello che sposta di più (entra Raphinha): **lo sconto delle fasi (§3.2) è
l'ipotesi residua più influente** e va calibrato sull'aggressività con cui si conta di usare i 10 cambi.

## 5-bis. Rischio di concentrazione e varianti di rosa

Obiezione (corretta): l'XF "ottimale" prende ~80% dell'ETP da Spagna+Argentina → forte esposizione
se una big crolla. Tre interventi, applicati a **tutte** le varianti:
- **Malus cartellini per-giocatore** (`player_context.csv` colonna `cards`): Romero/Otamendi/De Paul
  pesati di più → Romero esce dall'XI in tutte le varianti.
- **Panchina-assicurazione**: riserve solo da nazionali che arrivano ≥ ottavi (`BENCH_TEAM_MIN`,
  E[match] ≥ 4.5) — niente gente di squadre che escono ai gironi (sarebbe un cambio obbligato
  mascherato). Include un mezzo blocco difensivo secondario (Croazia) come copertura.
- **Cap di concentrazione** opzionale nell'ILP: `--max-per-nation N` (titolari/naz nell'XI) e
  `--attack-cap N` (solo attaccanti, lascia libero il blocco difensivo). Forzature manuali:
  `--include-xi CODE:Nome`, `--include CODE:Nome` (panchina), `--exclude CODE:Nome`.

**Stress test** (`scripts/stress_test.py`): valore dell'XI schierabile dalla stessa rosa se una big
esce ai gironi (suoi giocatori scalati a sole 3 gare). Sulle tre versioni finali (con le forzature §5-ter):

| Scenario | roster/optimal | balanced (4/naz) | aggressive (3/naz) |
|---|---|---|---|
| Base | 427 | 425 | 421 |
| SPA fuori ai gironi | 368 (−14%) | 381 (−10%) | 390 (−7%) |
| SPA+ARG fuori | 340 (−20%) | 348 (−18%) | 352 (−16%) |

**Conclusioni**: (1) Il cap sui soli attaccanti (`--attack-cap 2`, usato dalla *roster* scelta) non spezza
il **blocco difensivo** spagnolo — cioè il motore del modificatore — ma diversifica centrocampo e attacco.
(2) Ridurre oltre il rischio-Spagna richiede spezzare quel blocco (balanced/aggressive), perdendo coerenza
del modificatore (D+P che avanzano insieme) — costo che il `mod_proxy` lineare **sottostima**. (3) La Spagna
è la big **meno** probabile da eliminare (Elo massimo, ~7 partite attese) e, se cade, il blocco si
**trasferisce in blocco** coi 10 cambi. → Per un obiettivo "arrivare primi" (massimo EV/ceiling, varianza
non penalizzante) la *roster* scelta resta la migliore; *balanced* è l'hedge per tagliare un po' di coda.

## 5-ter. Rosa scelta (versione "roster")

Versione adottata dall'utente (le altre due sono solo riferimento). Preferenze applicate sopra al modello:
**portieri tutti francesi** (Maignan titolare + Risser/Samba riserve), **fuori Mac Allister** (poco
prolifico e non sempre titolare in nazionale) e **fuori Pedri** (per non concentrare ancora di più sulla
Spagna a centrocampo). Slot liberato preso da **Raphinha** (altro "bug listone": ala quotata come C).
Comando riproducibile:

```bash
python scripts/optimize_roster.py --attack-cap 2 \
  --include-xi "FRA:Maignan" --include "FRA:Risser" --include "FRA:Samba" \
  --exclude "ARG:Mac Allister" --exclude "SPA:Pedri" --label optimal
```

XI: Maignan (FRA); Llorente, Cubarsí, Cucurella (SPA), Molina (ARG); Enzo Fernández (ARG), Nico Williams
(SPA), Raphinha (BRA); Kane (ING), Oyarzabal (SPA), Mbappé (FRA). Capitano: il "6 assicurato" indicato in
`ROSTER.md`. Concentrazione top-2 nazionali scesa da 80% a **65%**.

## 6. Limiti noti

- **Rischio di correlazione**: blocco molto spagnolo → una giornata-no della Spagna o
  un'eliminazione a sorpresa colpisce l'intero XI. Mitigato dai 10 cambi, ma da monitorare.
- **mod_proxy** non garantisce di superare le soglie del modificatore in ogni giornata: è una
  stima media, non la media-migliori-3 reale partita per partita.
- **Voto base quasi piatto** (6.0–6.6): il modello distingue poco i titolari per qualità "da voto",
  quindi la scelta del capitano tra spagnoli equivalenti è in parte arbitraria.
- **Niente meteo, fuso/sede, minutaggio reale, calendario fitto** (sedi USA/Messico/Canada con
  caldo e altitudine possono incidere su gol e rotazioni).
- **player_context.csv** è curato a mano solo per le top: per le nazionali minori la titolarità
  resta basata sul rank di quotazione.

## 7. Come lo migliorerei (in ordine di impatto)

1. **✅ FATTO — Probabilità di titolarità da probabili formazioni** (`data/lineup_sentiment.csv`,
   §3.4). Prossimo passo: aggiornarle alla vigilia di ogni giornata (le formazioni cambiano per
   infortuni/scelte tecniche) ed estenderle alle nazionali oggi non coperte se servono i loro
   giocatori dopo i primi cambi.
2. **Modificatore difesa stocastico**: simulare i voti di D+P giornata per giornata (voto ~ N(media
   da forza/avversario, σ)) e calcolare l'**E[modificatore]** reale come media-migliori-3+P sopra le
   soglie, invece del proxy lineare. Spinge verso il blocco difensivo davvero ottimale.
3. **Calibrazione dello sconto delle fasi sui cambi**: modellare esplicitamente la politica dei 10
   trasferimenti (quando e su chi) e derivare i pesi di fase, invece di fissarli a mano (§3.2 è
   l'ipotesi più sensibile).
4. **xG/xA invece dei gol grezzi**: usare expected goals/assist (più stabili dei gol realizzati) e
   il rigore atteso esplicito; integrare la qualità degli avversari nel girone, non solo la media.
   *Parzialmente coperto* (§3.3-bis): le quote capocannoniere calibrano già E[gol] dei bomber di
   vertice. Estensioni: quote "marcatore in ogni momento" per partita (mappa più diretta a E[gol]),
   quote assist/uomo-assist, e quote esito partita per stimare gol fatti/subiti per ogni gara invece
   della sola forza media (migliora anche clean sheet dei portieri e modificatore difesa).
5. **Ottimizzazione robusta / multi-scenario**: massimizzare l'ETP medio su molti scenari di
   tabellone (o un CVaR) per penalizzare la correlazione, invece dell'ottimo del solo caso atteso.
6. **Modello di voto base più informativo**: legare il voto base a rating individuali
   (es. valutazioni di campionato) così la scelta di capitano e dei titolari "da voto" sia meno piatta.
7. **Arricchire i portieri** e **risolvere i 17 non matchati** se si vuole coprire anche le scelte
   marginali; integrare meteo/sede per le partite più estreme.
8. **Backtesting** del modello di fantapunti su un torneo passato (es. Mondiale 2022) per tarare i
   coefficienti (sconto 0.85, tetti di ruolo, σ dei voti) sui dati invece che a intuito.
