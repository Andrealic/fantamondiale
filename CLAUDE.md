# Fantamondiale 2026 — Regole e Strategia

## Struttura del torneo

- **Formato listone**: 250 crediti, 12 manager, nessuna esclusiva
- **Rosa**: 25 giocatori (3P / 8D / 8C / 6A), modulo obbligatorio difesa a 4
- **Schieramento**: 11 titolari + 7 riserve per giornata (18 su 25)
- **Trasferimenti**: 10 cambi totali durante il torneo, utilizzabili in qualsiasi momento

## Classifiche — DOPPIO OBIETTIVO

### 1. Classifica totale
Punteggio cumulativo di tutte le giornate. Massimizzare ETP (Expected Total Points) su tutto il torneo.

### 2. Classifica scontri diretti (HEAD-TO-HEAD)
- 2 gironi da 6 squadre (round-robin, si gioca 1 volta contro ogni avversario)
- Le **prime 4 di ogni girone** passano alla fase finale
- Il risultato dello scontro è determinato da **fasce di 4 punti**: ogni 4 punti di scarto corrispondono a un gol di differenza nel punteggio della sfida
- Qualificarsi ai play-off richiede di vincere almeno ~3 delle 5 sfide del girone

### Implicazioni strategiche del doppio obiettivo

1. **Classifica totale**: massimizzare ETP atteso → schiera sempre il migliore XI indipendentemente dall'avversario
2. **Scontri diretti**: il margine conta (fasce 4pt) → in certe situazioni preferire giocatori ad alto ceiling su un avversario specifico
3. **Captaincy**: il bonus capitano (voto base ≥7→+1, ≥9→+3) è il principale leva per allargare il gap nello scontro diretto. Va sempre scelto sulla base dell'avversario specifico di giornata, non solo sull'ETP globale
4. **Giocatori in comune con l'avversario** si cancellano nel differenziale: l'attenzione va sui giocatori esclusivi e sul bonus capitano

## Regole di punteggio (confermate)

- Gol subito −1: **solo per il portiere** (non difensori/centrocampisti)
- Bonus capitano sul **voto base senza bonus/malus**: ≥7 → +1 pt, ≥9 → +3 pt
- Il vice-capitano prende il bonus solo se il capitano NON gioca (non è un doppio bonus)
- Modificatore difesa: attivato se nell'XI ci sono P + almeno 4D (bonus difesa squadra)

## Capitano — criteri di scelta

- **Classifica totale**: capitanare un "6 assicurato" (titolare affidabile della nazionale più forte, tipicamente difensore spagnolo). Minimizza varianza.
- **Scontri diretti**: capitanare il giocatore con **la maggiore P(voto ≥7)** tenendo conto dell'avversario di turno. Se l'avversario del match capita lo stesso giocatore come titolare, quella scelta è neutrale nel differenziale → spostarsi su un giocatore esclusivo con alto ceiling (attaccante vs avversario debole).

## Fase a gironi → fase finale

Dopo i 3 turni del girone i trasferimenti vanno orientati verso le nazioni superstiti. Le riserve attuali di nazioni con minor E[match] (CAN, CRO, MEX, ECU) sono le prime candidate al rimpiazzo dopo il turno 3.

## File chiave

- `ROSTER.md` — rosa ottimale scelta, XI tipo, razionale
- `DECISIONI.md` — log decisioni/assunzioni
- `data/projections.csv` — ETP per giocatore
- `scripts/build_projections.py` — Monte Carlo + ETP
- `scripts/optimize_roster.py` — ILP (pulp) → rosa ottimale
- Esecuzione: `python3 scripts/build_projections.py --sims 20000 && python3 scripts/optimize_roster.py`
- `pulp` su PyPI pubblico: `pip install --index-url https://pypi.org/simple/ pulp`
