---
name: schierare
description: Decidi chi schierare nell'XI di una giornata del Fantamondiale 2026 (formazione, capitano, vice, panchina) bilanciando classifica totale e scontro diretto. Usa quando l'utente chiede "chi schiero alla giornata X", "che formazione metto", "chi capitano" o incolla la probabile formazione di un avversario H2H.
---

# Schierare l'XI di giornata

Questa skill copre la decisione **per-giornata** (chi metto in campo oggi), che è diversa
dalla costruzione della rosa. La rosa è già fissata in `ROSTER.md`; qui scegli i 18 (XI +
7 panchina) e il capitano **massimizzando i fantapunti attesi di QUESTA giornata**, non
l'ETP globale dei 25.

> **Nota implementazione**: oggi questa è una guida cognitiva — il calcolo lo fai a mano
> ragionando sui dati. È predisposta per agganciare in futuro uno
> `scripts/lineup_matchday.py` che automatizzi i passi 4–5. Finché non esiste, segui i
> passi sotto.

## Regole del gioco da tenere a mente (da CLAUDE.md)

- **Doppio obiettivo**: classifica totale (somma punti) **e** scontri diretti (fasce di
  4 punti di scarto = 1 gol nella sfida; servono ~3 vittorie su 5 nel girone per i play-off).
- **Capitano**: bonus sul **voto base senza bonus/malus** → ≥7 = +1, ≥9 = +3. Il vice
  prende il bonus **solo** se il capitano non gioca.
- **Modificatore difesa**: attivo se nell'XI c'è il portiere + almeno 4 difensori (modulo
  difesa a 4 obbligatorio). Va quasi sempre preservato.
- **Gol subito −1**: solo per il portiere.
- **XI = 11 titolari + 7 riserve** (18 su 25), vincolo modulo 3P/8D/8C/6A nella rosa ma in
  campo difesa a 4.

## Cosa serve sapere (input) e dove prenderlo

| Input | Dove | Note |
|---|---|---|
| **Rosa attuale (25)** | `ROSTER.md` (+ `output/roster_optimal.csv`) | Aggiornata per i trasferimenti già usati. Se l'utente ha fatto cambi, chiediglielo. |
| **Proiezioni base** | `data/projections.csv` | `base_voto`, `etp`, `per_match_pts`, `starter_prob`. È la **baseline neutra**: va corretta per l'avversario di giornata. |
| **Forza nazionali / avversari** | `data/wc2026_team_strength.csv` (elo, win_odds), `data/wc2026_sim.csv` | Per stimare quanto è forte l'avversario della nazionale del mio giocatore in questa partita. |
| **Disponibilità (infortuni/condizione)** | `data/player_context.csv` (colonna `avail`) | Da rinfrescare via web a ridosso della giornata. |
| **Probabili formazioni** | `data/lineup_sentiment.csv` (`status`: starter/likely/rotation/fringe) | Fotografia ~giugno 2026: **va riverificata** per la giornata specifica (turnover dopo qualificazione, rientri). |
| **Calendario partite** | ❌ non in repo | **Web search**: chi gioca contro chi in questa giornata. |
| **Avversario H2H + sua formazione** | ❌ non in repo | **Lo incolla l'utente.** Se non lo dà, chiediglielo (serve per differenziale e capitano anti-avversario). |
| **Situazione di classifica** | l'utente | Determina la priorità: inseguo il totale o devo *vincere lo scontro*? |

### Dati freschi → web search

A ridosso della giornata, **cerca sul web** e aggiorna mentalmente (o nei CSV, se l'utente
vuole persistere):
1. Il **calendario**: quali nazionali della mia rosa giocano in questa giornata e contro chi.
2. **Infortuni/squalifiche** dell'ultim'ora (un titolare KO ribalta la scelta).
3. **Probabili formazioni** aggiornate: dopo la qualificazione le big ruotano → un titolare
   abituale può partire in panchina.

Cita sempre la data delle fonti e segnala quando un dato è incerto.

## Flusso cognitivo (i 6 passi)

### 1. Perimetro: chi è effettivamente disponibile
Filtra i 25 togliendo: infortunati (`avail` basso), squalificati (cartellini accumulati),
e chi NON è titolare previsto in questa giornata. Tieni le riserve di nazionali già
eliminate solo come tappabuchi (sono candidati al trasferimento, vedi `ROSTER.md`).

### 2. Fantapunti attesi DI GIORNATA per ogni candidato
Per ogni giocatore disponibile parti dal `base_voto`/`per_match_pts` di `projections.csv` e
**correggilo per questa partita**:
- **Forza avversario**: avversario debole → alza il voto atteso e la P(bonus) di
  attaccanti/rifinitori; avversario forte → abbassa, e per il portiere/difesa cresce il
  rischio di gol subiti.
- **Bonus attesi**: gol/assist (rigoristi e tiratori da `player_context.csv` pen_share/freekick;
  attaccanti con quote capocannoniere alte in `data/topscorer_odds.csv`).
- **Malus attesi**: cartellini (difensori ARG ecc.), gol subiti (solo portiere).
- **P(titolare)** della giornata e minutaggio atteso (rientri da infortunio = rischio
  spezzone).

### 3. XI ottimo per la classifica totale
Componi l'XI che **massimizza la somma dei fantapunti attesi** rispettando: P + ≥4D (per il
modificatore difesa) + completamento C/A fino a 11. Questo è l'XI "neutro", il riferimento
per la classifica totale. Schiera sempre i migliori, a prescindere dall'avversario.

### 4. Aggiustamento scontro diretto (H2H)
Solo se conta vincere *questa* sfida (vedi passo 6). Con la formazione avversaria incollata
dall'utente:
- **Giocatori in comune** (io e l'avversario schieriamo lo stesso): si **annullano** nel
  differenziale → ininfluenti, non spostarti per loro.
- **Differenziali**: dove ho giocatori esclusivi. Se devo recuperare/allargare il margine,
  sposta marginalmente verso **ceiling** (alto upside) sui differenziali — anche a costo di
  un filo di ETP atteso. Se sono in vantaggio o l'obiettivo è solo il totale, resta sull'XI
  del passo 3.

### 5. Capitano e vice
- **Priorità classifica totale** → capitano "6 assicurato": titolare affidabile della
  nazionale più forte in campo (tipicamente un difensore/centrocampista spagnolo di vertice),
  massima P(voto≥7) con varianza minima.
- **Priorità scontro diretto** → capitano con la **massima P(voto≥7) su un giocatore
  esclusivo** (non in comune con l'avversario), privilegiando il ceiling: un attaccante
  contro un avversario debole. Se l'avversario capitana il mio stesso giocatore, il bonus si
  annulla nel differenziale → **spostati su un esclusivo**.
- **Vice**: il miglior candidato in una partita diversa/più sicura, così copre se il capitano
  non scende in campo.

### 6. Priorità del momento: totale o scontro?
Chiedi (o deduci dalla situazione di classifica) quale obiettivo pesa di più ORA:
- A inizio torneo o quando i play-off sono fuori portata/già acquisiti → **totale** (XI del
  passo 3, capitano a bassa varianza).
- Quando una singola sfida decide la qualificazione → **scontro** (aggiustamento passo 4 +
  capitano anti-avversario passo 5).
Nel dubbio, default sul **totale** e segnala all'utente la leva H2W disponibile.

## Output da produrre

1. **XI titolare** (11) con ruolo, nazionale, avversario di giornata e fantapunti attesi.
2. **Capitano ⭐ e vice (V)** con il razionale (totale vs scontro).
3. **Panchina** (7) ordinata per priorità di subentro.
4. **Razionale sintetico**: perché questo XI, dove ho corretto per l'avversario, eventuale
   trade-off totale↔scontro, e i differenziali chiave vs l'avversario H2H (se fornito).
5. **Avvisi**: dati incerti, rientri da infortunio, titolarità a rischio, capitano alternativo.

## Cosa chiedere all'utente se manca

- Quali **trasferimenti** ha già fatto (la rosa potrebbe non essere più quella di `ROSTER.md`).
- L'**avversario H2H** di questa giornata e la sua **probabile formazione** (per i passi 4–5).
- La **priorità** del momento (totale vs vincere lo scontro), se non deducibile.
