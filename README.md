# PNV Navi – Verspätungsstatistik

Ausgewertete Verspätungsdaten für die App **PNV Navi**: Wie oft ist ein Zug an einem Bahnhof in Berlin/Brandenburg
zu spät? Pro Bahnhof, Linie und planmäßiger Minute (letzte zwei Monate) sowie Monatswerte jeder Linie für den
Jahresvergleich. Die App holt sich neue Werte nachts beim Laden – nur für die Bahnhöfe, die man nutzt.

**Quelle:** Deutsche Bahn, Datensatz [piebro/deutsche-bahn-data](https://huggingface.co/datasets/piebro/deutsche-bahn-data),
Lizenz [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Die Dateien hier sind daraus abgeleitet und stehen
ebenfalls unter CC BY 4.0.

## Inhalt

- `vs/index.json` – Stand, Zeitraum, Bahnhof → Datei
- `vs/<bahnhof>.json` – pro Linie: `d` (Abfahrt) und `a` (Ankunft) je Minute
  `[Fahrten, Ausfälle, 0–2, 3–5, 6–9, 10–14, 15–29, ≥30 min, Schnitt×10]`, `m` Monatswerte `[Fahrten, Ausfälle, ab 3 min, Schnitt×10]`
- `daten/` – Monatsauszüge, aus denen `vs/` gebaut wird
- `tools/verspaetung.py` – Auswertung

## Aktualisierung

Der Workflow „Neuer Monat“ sieht täglich nach, ob der Datensatz einen neuen Monat hat, wertet ihn aus und checkt das
Ergebnis ein. Von Hand:

```bash
pip install duckdb
VS_DATEN=daten VS_OUT=vs python3 tools/verspaetung.py monat data-2026-10.parquet
VS_DATEN=daten VS_OUT=vs python3 tools/verspaetung.py bauen
```
