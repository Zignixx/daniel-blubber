# Blubberzähler 🫧

Ein kleines Tool zum Wörterzählen in wissenschaftlichen Texten – nach
formatierten **Kapiteln/Überschriften**, mit Ausschluss von **Harvard-Zitaten
(runde Klammern)** und **Tabellen**.

## Features

- **Upload** von **Word (.docx)** oder **PDF**
- **Kapitelauswahl**: alle Kapitel, ein Bereich (von–bis) oder Einzelauswahl
- **Checkboxen**:
  - Überschriften mitzählen (ja/nein)
  - Klammern mitzählen (ja/nein) – Harvard-Zitate
  - Fußnoten mitzählen (ja/nein)
- **Tabellen werden immer ausgeschlossen**
- **Ausgabe**: Gesamtwortzahl + pro Hauptkapitel eine Zahl; Unterkapitel werden
  einzeln aufgeführt, aber in den Hauptkapitel-Count **mit aufaddiert**
- **Report-Download** als `.txt`

## Installation

```bash
pip install -r requirements.txt
```

## Starten

```bash
streamlit run blubberzaehler.py
```

Es öffnet sich automatisch der Browser (sonst: http://localhost:8501).

## Als Docker-Container

Lokal bauen und starten:

```bash
docker compose up -d --build
```

Danach erreichbar unter http://localhost:8501. Stoppen mit `docker compose down`.

Nur mit Docker (ohne Compose):

```bash
docker build -t blubberzaehler .
docker run -d --name blubberzaehler -p 8501:8501 blubberzaehler
```

### Deployment in Portainer

**Variante A – Repository-Stack (empfohlen):**
1. Portainer → **Stacks** → **Add stack** → **Repository**.
2. Repository-URL dieses Projekts eintragen, Branch `main`.
3. **Compose path**: `docker-compose.yml`.
4. **Deploy the stack** – Portainer baut das Image aus dem Repo und startet es.

**Variante B – Web editor:**
1. Portainer → **Stacks** → **Add stack** → **Web editor**.
2. Inhalt von `docker-compose.yml` einfügen und deployen (Build-Context/Repo muss erreichbar sein).

Der Port lässt sich im Stack über das `ports`-Mapping ändern (z. B. `"9000:8501"`).
Die App bringt einen Healthcheck auf Streamlits `/_stcore/health` mit, sodass
Portainer den Container-Status korrekt anzeigt.

## Hinweise zur Genauigkeit

- **Word (.docx)** ist der Idealfall: Überschriften werden über die
  Formatvorlage (`Überschrift 1`, `Überschrift 2`, …) erkannt, Tabellen und
  Fußnoten sind im Dokument klar markiert.
- **PDF** hat keine verlässlichen Überschriften-Formatvorlagen. Die Erkennung
  ist **heuristisch** (Schriftgröße, Fettung, Nummerierung wie „2.1") und daher
  nicht immer perfekt. Für exakte Zahlen empfiehlt sich ein `.docx`.

## Wortdefinition

Als „Wort" zählt eine Folge aus Buchstaben/Ziffern (inkl. Umlauten), die durch
Binde- oder Apostroph-Striche verbunden sein darf (z. B. `E-Mail` = 1 Wort).
Klammer-Inhalte werden vor dem Zählen entfernt (auch verschachtelt), wenn die
Option „Klammern mitzählen" **nicht** aktiv ist.
