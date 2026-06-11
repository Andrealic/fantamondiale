# Piano: rosa ottimale Fantamondiale 2026

## Context

L'utente partecipa a un fantamondiale (Mondiale FIFA 2026, 48 nazionali, al via **oggi 11/06/2026**) con
modalità **listone**: 250 crediti, nessuna esclusiva tra i 12 manager → l'obiettivo è **massimizzare i punti
totali attesi**, non gestire la scarsità. Vuole che la rosa sia scelta interamente dall'AI per vincere.
Deliverable richiesto: **la sola rosa iniziale ottimale** (gestione giornaliera, cambi e capitano restano
informativi ma non sono output richiesti).

Nel repo è già presente `fantapazz_listone_enriched.csv` (1250 giocatori; gol club/nazionale, presenze e
ratio nazionale per cb/m/st) più gli script di scraping Transfermarkt (`scripts/enrich_transfermarkt.py`,
`scripts/transfermarkt_team_map.py`) e cache in `data/cache/transfermarkt/`. **I portieri non sono arricchiti**
(lo script salta il ruolo `gk`) e **17 giocatori risultano non matchati** (`transfermarkt_unmatched_players.csv`).

## Regole bloccate (con l'utente)

- **Rosa**: 25 giocatori = **3 P / 8 D / 8 C / 6 A**. Difesa a 4 (per attivare il modificatore).
- **Bonus/malus** (uguali per ruolo salvo note): gol **+3**, rigore segnato **+3**, assist **+1**,
  gol-vittoria **+1**; rigore parato **+3** (solo P), porta inviolata **+1** (solo P);
  malus: **gol subito −1 solo al portiere**, rigore sbagliato **−3**, autogol **−3**, ammonizione **−0,5**,
  espulsione **−1**. Voto base ≈ 6.
- **Modificatore difesa** (classico): media dei migliori 3 D + P della giornata → ≥6 **+1**, ≥6,5 **+3**, ≥7 **+6**.
- **Capitano**: incrementale **−3…+3** sul voto base (≥9 → +3; ≤3 → −3).
- **Nessun cap** di giocatori per nazionale.
- Punteggio automatico 65,5 a chi non schiera; 0-0 → 1-0 se scarto ≥10 (rilevanti per la coppa, non per la rosa).

## Idea chiave

Il valore di un giocatore = **(quanti match gioca nell'orizzonte rilevante) × (fantapunti netti attesi a match)**.

**I 10 cambi "in qualsiasi momento" accorciano l'orizzonte della rosa iniziale**: i giocatori di nazionali
eliminate si sostituiscono in corsa, quindi non serve sovra-pagare ora per profili che valgono solo se si va
in finale — ci si ri-orienta sulle superstiti via trasferimenti. La rosa iniziale si ottimizza quindi su un
**orizzonte breve-medio**: la fase a gironi (dove **tutte le 48 nazionali giocano 3 partite garantite**) più
i primi turni a eliminazione, con un **core** di squadre probabilmente profonde così da minimizzare i cambi
necessari più avanti. La profondità nel tabellone resta importante ma è in parte "recuperabile".

Si massimizza la somma dei punti attesi (ETP) sotto i 250 crediti, privilegiando: titolari inamovibili,
rigoristi/specialisti su palla inattiva (moltiplicatori di bonus) e un **blocco difensivo coeso** di una/due
nazionali solide (il modificatore vale fino a +6/giornata e premia D+P che giocano la stessa giornata con
voti alti). Budget concentrato sui titolari forti; slot panchina al minimo prezzo (rimpiazzabili coi cambi).

## Fase 1 — Completare il dataset

1. **Struttura Mondiale 2026** → `data/wc2026_structure.csv`. Via WebSearch/WebFetch (FIFA/Wikipedia):
   12 gironi, calendario gironi, tabellone a eliminazione (round of 32 → finale), sedi/orari.
2. **Forza squadre + probabilità di avanzamento** → `data/wc2026_team_strength.csv`. Rating Elo
   (eloratings.net) e/o quote bookmaker (vincente torneo, qualificazione per fase). Servono per simulare.
3. **Specialisti su palla inattiva**: per le ~16 nazionali più forti, raccogliere i **rigoristi + battitori di
   punizioni** (web) — sono i moltiplicatori di bonus. La `national_presence_ratio` esistente è il proxy di
   titolarità, da correggere a mano solo per i casi noti (infortuni/squalifiche, esperimenti in amichevole).
   Output: `data/player_context.csv` (starter_prob, set_piece_role, injury_flag).

   *Esclusi per scelta dell'utente:* arricchimento portieri (il titolare è ovvio; la solidità difensiva si
   inferisce dalla forza/prob. di vittoria della squadra) e risoluzione dei 17 non matchati (irrilevanti).

## Fase 2 — Modello di proiezione (ETP) → `scripts/build_projections.py`

Per ogni giocatore:

- **E[match giocati] su orizzonte pesato** = simulazione Monte Carlo del tabellone (10k run) usando Elo/quote →
  P(la nazionale gioca il round r) sommata sui round, × `starter_prob`. I round vengono **pesati con un fattore
  di sconto** che riflette la sostituibilità via i 10 cambi: gironi a peso pieno (3 match garantiti), turni a
  eliminazione a peso decrescente (i giocatori delle eliminate si rimpiazzano, e si può entrare sulle superstiti
  più avanti). Così la rosa iniziale non sovra-paga la "finale" e resta ribilanciabile in corsa.
- **Fantapunti netti attesi a match**:
  - *A/C*: `6 + 3·E[gol] + 1·E[assist] − 0,2 (cartellini)`. E[gol]/E[assist] stimati da gol club e
    gol/presenze in nazionale, normalizzati a "per match Mondiale" e regrediti verso la media per ruolo;
    bonus rigoristi (xG da rigore atteso) e specialisti palla inattiva.
  - *D*: `6 + contributi offensivi (minori) + valore-modificatore` (vedi sotto). Nessun malus gol subito.
  - *P*: `6 + 1·P(clean sheet) − 1·E[gol subiti] + bonus rigore parato`. **P(clean sheet) ed E[gol subiti] si
    inferiscono dalla forza/probabilità di vittoria della squadra** (più una squadra è forte/favorita nella
    partita, meno gol subisce) — nessun dato preciso sui portieri necessario. Il titolare è ovvio.
- **Valore del modificatore difesa**: termine a livello di blocco, non di singolo. Stima del contributo per
  D/P in funzione di (solidità difensiva nazionale, prob. titolarità, E[match], voto atteso): difensori/
  portieri di nazionali che subiscono poco e vanno avanti alzano la media migliori-3+P sopra le soglie.
  Implementazione pragmatica: punteggio di "contributo-modificatore" sommato all'ETP di D/P, poi
  **valutazione/iterazione post-ottimizzazione** sul blocco effettivamente scelto.
- **Opzione capitano**: il bonus capitano (−3…+3) è sul **voto base**, non sui bonus/malus. Quindi premia chi
  garantisce **voti base alti e costanti** — un titolarissimo affidabile di **qualunque ruolo** (portiere,
  difensore solido, regista, oltre agli attaccanti). Si modella come premio all'ETP per affidabilità/media voto
  attesa (alta media, bassa varianza), senza fissarsi sui profili a tanti bonus.

Output: `data/projections.csv` (player, role, value, ETP, e componenti).

## Fase 3 — Ottimizzazione rosa → `scripts/optimize_roster.py`

ILP (libreria `pulp`, da aggiungere a `requirements.txt`) — massimizza **Σ ETP·x** con vincoli:

- Σ value·x ≤ 250
- esattamente 3 `gk`, 8 `cb`, 8 `m`, 6 `st`
- solo giocatori con `starter_prob` ≥ soglia (esclude riserve "morte"; eccezione per slot panchina economici).

Raffinamento (la rosa schiera 11/giornata): seconda passata che massimizza l'**XI atteso per giornata**
(spendere sui ~11–13 titolari forti e da nazionali profonde, riempire gli altri slot con titolari
inamovibili al minimo prezzo per coprire modificatore difesa e rotazione capitano). Si confronta l'ILP
"somma 25" con la variante "best-XI" e si verifica che il blocco difensivo resti coeso (stesse giornate).

## Fase 4 — Output

- `roster_optimal.csv`: i 25 giocatori (ruolo, nazionale, valore, ETP, E[match], note).
- `ROSTER.md`: rosa finale con XI di partenza tipo (modulo a 4 dietro), capitano/vice suggeriti per la prima
  giornata, budget speso/residuo, e razionale sintetico per i titolari chiave e per il blocco difensivo.
  Include una breve nota su **quali slot sono i primi candidati ai cambi** (giocatori di nazionali a rischio
  eliminazione precoce), così la rosa iniziale è già pensata per essere ri-orientata coi 10 trasferimenti.

## File toccati / creati

- Nuovi: `data/wc2026_structure.csv`, `data/wc2026_team_strength.csv`, `data/player_context.csv`,
  `data/projections.csv`, `scripts/build_projections.py`, `scripts/optimize_roster.py`, `roster_optimal.csv`,
  `ROSTER.md`.
- Modificati: `requirements.txt` (+`pulp`).
- Riuso: `fantapazz_listone_enriched.csv` (incluse le colonne già presenti), `transfermarkt_team_map.py`.
- Non necessari (per scelta dell'utente): arricchimento portieri, risoluzione dei 17 non matchati.

## Verifica

1. `python scripts/build_projections.py` → `projections.csv` con ETP plausibili (top per ruolo = big attesi).
2. `python scripts/optimize_roster.py` → rosa che rispetta 3/8/8/6 e ≤250 crediti (assert nel codice).
3. Sanity check manuale: i titolari delle favorite e i rigoristi compaiono; il blocco difensivo è di
   nazionali solide e profonde; nessun "buco" di budget e nessun titolare improbabile tra i previsti in campo.
4. Analisi di sensibilità: variare le probabilità di avanzamento (±) e confermare che la rosa resta stabile.