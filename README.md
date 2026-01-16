# El-labb

Ett webbaserat verktyg för att rita och simulera AC/DC‑scheman med symbolbibliotek, multimeter, kontaktorer och motorer.

## Funktioner

- Dra och släpp komponenter från biblioteket.
- AC 1‑fas, AC 3‑fas (Y/Delta) och DC‑källor.
- Kontaktorer (standard och omkastande) med valfritt antal poler.
- Lampor med valbar ljusfärg.
- Multimetrar som kan ligga kvar i schemat.
- Simulering körs på serversidan (Flask).
- Spara och ladda labbar som JSON.
- Knäckpunkter på kablar (lägg till/drag/ta bort).
- Manuell resize av canvas (sparas i labb).
- Debug‑logg för simuleringar.

## Krav

- Python 3.10+

## Starta lokalt

Installera beroenden:

```bash
pip install -r requirements.txt
```

Starta servern:

```bash
python app.py
```

Öppna sedan:

```
http://127.0.0.1:5000
```

## Användning

- Välj verktyg: Markera, Ledning, Multimeter, Radera.
- Lägg komponenter från biblioteket genom att klicka på komponenten och sedan klicka på canvas.
- Dra ledningar mellan terminaler.
- Lägg knäckpunkter på en ledning:
  - Vid skapande: klicka på tom yta för att lägga knäckpunkter.
  - I efterhand: dubbelklicka på en ledning för att skapa en ny knäckpunkt.
  - Dra knäckpunkter för att justera. I radera‑läge kan de tas bort.
- Starta simulering med `Kör simulering` och växla `Simläge`.
- Multimeter: välj läge och klicka på komponent/terminaler.
- Spara labb i panelen “Spara & ladda”.
- Justera canvas‑storlek genom att dra i handtaget nere till höger.

## Timers

Det finns två typer av timers:

- **Timer** (spolstyrd): När spolen får spänning börjar timern räkna ner. Efter fördröjningen växlar den kontakt (C/NO/NC). Du kan välja om den ska loopa eller bara gå en gång. Om spolen tappar matning återställs den till ursprungsläget.
- **Timer (klocka)**: Styrs av datorns lokala tid. Du anger start‑ och stopptid (HH:MM) och den sluter/öppnar kontakten därefter.

Tips: I simläge uppdateras timers och visar återstående tid eller PÅ/AV som etikett.

## PLC‑programmering (LAD‑text)

PLC‑komponenten kan programmeras med enkel LAD‑text som liknar Siemens‑stil.

### Grundinstruktioner

- `A I1` – AND med ingång I1
- `AN I2` – AND NOT med ingång I2
- `U I1` – AND (Siemens‑alias för A)
- `UN I2` – AND NOT (Siemens‑alias för AN)
- `O I3` – OR med ingång I3
- `ON I4` – OR NOT med ingång I4
- `= Q1` – Sätt utgång Q1 från aktuellt logikresultat
- `= M1` – Sätt minnesbit M1 från aktuellt logikresultat
- `S Q1` / `R Q1` – Set/Reset utgång
- `S M1` / `R M1` – Set/Reset minne
- `L I1` – Ladda operand i ackumulatorn
- `T Q1` – Transferera ackumulatorn till Q1/M1
- `MOVE I1 Q1` – Flytta värde från I1 till Q1/M1
- `R_TRIG M1` – Positiv flank, skriver puls till M1 eller Q1
- `F_TRIG M1` – Negativ flank, skriver puls till M1 eller Q1
- `CTU C1 PV=5` – Räknare upp, Q blir sann vid PV
- `CTD C1 PV=5` – Räknare ned, Q blir sann när CV <= 0
- `R C1` – Reset räknare
- `TON T1 2.5` – Fördröjd till (sekunder)
- `TOF T1 2.5` – Fördröjd från (sekunder)
- `TP T1 2.5` – Puls (sekunder)

### Exempel

```
A I1
AN I2
= Q1
```

Tolkas som: Q1 blir sann när I1 är sann och I2 är falsk.

Exempel med timer:

```
A I1
TON T1 3.0
= Q1
```

Tolkas som: Q1 blir sann 3 sekunder efter att I1 blir sann.

Exempel med minne (M‑bit):

```
A I1
= M1

A M1
= Q1
```

Exempel med räknare:

```
A I1
CTU C1 PV=3
= Q1
```

Q1 blir sann efter tre pulser på I1.

Exempel med MOVE:

```
MOVE I1 Q1
```

## Multimeter

- **DC**: Volt, Ampere, Ohm
- **AC**: Volt RMS, Ampere RMS, fasvinkel, P/Q/S och cos φ

Placera multimetern genom att välja läge och klicka på komponent eller terminaler.

## Kontaktorer

- Standard (NO/NC per pol) och omkastande kontaktor.
- Välj antal poler (1–6).
- Spole A1/A2 styr när polerna växlar.

## Struktur

- `app.py` – Flask‑server, simulering och API.
- `templates/index.html` – UI‑layout.
- `static/js/app.js` – Klientlogik, canvas‑ritning.
- `static/css/style.css` – Stil.
- `saves/` – Sparade labbar som JSON.

## Notiser

- Projektet är i ett väldigt tidigt stadie och är vibe‑kodat.
- Simuleringen är avsedd för utbildning och visualisering, inte för verkliga elsystem.
- AC‑simulering stöder en frekvens åt gången.
