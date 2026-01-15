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
