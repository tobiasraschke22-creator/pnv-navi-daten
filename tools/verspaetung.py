#!/usr/bin/env python3
"""Verspätungsstatistik für PNV Navi.

Quelle: offener Datensatz piebro/deutsche-bahn-data (Deutsche Bahn, Lizenz CC BY 4.0),
eine Parquet-Datei pro Monat mit jeder Ankunft/Abfahrt an jedem DB-Bahnhof.

Zwei Schritte:
  python3 tools/verspaetung.py monat data-2026-09.parquet
      → tools/daten/zeiten-2026-09.json.gz  (pro Bahnhof/Linie/Uhrzeit, für das gleitende Fenster)
      → tools/daten/linien-2026-09.json.gz  (pro Bahnhof/Linie, bleibt für den Jahresvergleich)
  python3 tools/verspaetung.py bauen
      → app/data/vs/index.json + eine Datei pro Bahnhof

Zähler je Eintrag: [Fahrten, Ausfälle, 0–2, 3–5, 6–9, 10–14, 15–29, ≥30 min, Summe der Minuten]
"""
import glob, gzip, json, os, re, sys
from datetime import date

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
# Ordner lassen sich überschreiben (im Daten-Repository pnv-navi-daten: daten/ und vs/)
DATEN = os.environ.get('VS_DATEN') or os.path.join(ROOT, 'tools', 'daten')
OUT = os.environ.get('VS_OUT') or os.path.join(ROOT, 'app', 'data', 'vs')
REGIO = "('S', 'RE', 'RB', 'OE', 'NEB')"
FENSTER = 2          # Monate für die Werte pro Uhrzeit
JAHR = 13            # Monate für den Jahresvergleich pro Linie
QUELLE = 'Deutsche Bahn, Datensatz piebro/deutsche-bahn-data, CC BY 4.0'


def norm(name):
    """Bahnhofsname vereinheitlichen – muss zu normStation() in app.js passen."""
    s = (name or '').lower()
    s = re.sub(r'\(.*?\)', ' ', s)
    s = s.replace('ß', 'ss').replace('strasse', 'str').replace('str.', 'str')
    s = s.replace('hauptbahnhof', 'hbf')
    s = re.sub(r',?\s*bahnhof\b', ' ', s)
    s = re.sub(r'\bbhf\b', ' ', s)
    s = re.sub(r'^(s\+u|s|u)\s+', '', s.strip())
    s = re.sub(r'^berlin[- ]', '', s.strip())
    s = re.sub(r'[^0-9a-zäöü ]+', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()


def dateiname(key):
    s = key.replace('ä', 'ae').replace('ö', 'oe').replace('ü', 'ue')
    return re.sub(r'[^a-z0-9]+', '_', s).strip('_') + '.json'


def monat(datei):
    import duckdb
    m = re.search(r'(\d{4}-\d{2})', os.path.basename(datei)).group(1)
    c = duckdb.connect()
    c.create_function('norm', norm, ['VARCHAR'], 'VARCHAR')
    c.sql(f"""create table t as select station_name, train_type, train_number, line_number, train_line_ride_id,
                departure_planned_time, departure_change_time, coalesce(departure_is_canceled, false) dcx,
                arrival_planned_time, arrival_change_time, coalesce(arrival_is_canceled, false) acx
              from read_parquet('{datei}') where train_type <> 'Bus' and coalesce(is_replacement_train, false) = false""")
    # Region: alle Halte von Regio-/S-Bahn-Fahrten, die durch Berlin fahren
    c.sql(f"""create table st as select distinct station_name from t where train_line_ride_id in
              (select train_line_ride_id from t where (station_name like 'Berlin %' or station_name like 'Berlin-%')
               and train_type in {REGIO})""")
    q = """
      with x as (select norm(station_name) st, coalesce(line_number, train_type || ' ' || train_number) ln,
                   strftime({p}, '%H:%M') hm, {cx} cx, greatest(date_diff('minute', {p}, coalesce({ch}, {p})), 0) d
                 from t where station_name in (select station_name from st) and {p} is not null)
      select st, ln, hm, count(*), sum(cx::int),
        sum((not cx and d <= 2)::int), sum((not cx and d between 3 and 5)::int), sum((not cx and d between 6 and 9)::int),
        sum((not cx and d between 10 and 14)::int), sum((not cx and d between 15 and 29)::int), sum((not cx and d >= 30)::int),
        sum(case when cx then 0 else d end)
      from x where ln is not null group by all"""
    zeiten, linien = {}, {}
    for kind, p, ch, cx in (('d', 'departure_planned_time', 'departure_change_time', 'dcx'),
                            ('a', 'arrival_planned_time', 'arrival_change_time', 'acx')):
        for st, ln, hm, *z in c.sql(q.format(p=p, ch=ch, cx=cx)).fetchall():
            z = [int(v) for v in z]
            slot = zeiten.setdefault(st, {}).setdefault(ln, {}).setdefault(kind, {})
            slot[hm] = add(slot.get(hm), z)   # gleiche Linie, gleiche Minute (z. B. Flügelzug) – zusammenlegen
            lk = linien.setdefault(st, {}).setdefault(ln, {})
            lk[kind] = add(lk.get(kind), z)
    os.makedirs(DATEN, exist_ok=True)
    for name, obj in (('zeiten', zeiten), ('linien', linien)):
        with gzip.open(os.path.join(DATEN, f'{name}-{m}.json.gz'), 'wt', encoding='utf-8') as f:
            json.dump({'monat': m, 's': obj}, f, ensure_ascii=False, separators=(',', ':'))
    print(f'{m}: {len(zeiten)} Bahnhöfe')


def sline(ln):
    """S-Bahn-Linien stehen im Datensatz teils nur als Zahl ("25" statt "S25")."""
    return 'S' + ln if ln.isdigit() else ln


def add(a, b):
    return list(b) if a is None else [x + y for x, y in zip(a, b)]


def kurz(z):
    """Zähler → [Fahrten, Ausfälle, 0–2, 3–5, 6–9, 10–14, 15–29, ≥30 min, Schnitt×10]"""
    n, c, *h, summe = z
    fahrten = n - c
    return [n, c, *h, round(summe * 10 / fahrten) if fahrten else 0]


def lade(name):
    out = {}
    for f in sorted(glob.glob(os.path.join(DATEN, f'{name}-*.json.gz'))):
        with gzip.open(f, 'rt', encoding='utf-8') as fh:
            d = json.load(fh)
        out[d['monat']] = d['s']
    return out


def bauen():
    zeiten, linien = lade('zeiten'), lade('linien')
    monate = sorted(zeiten)[-FENSTER:]
    jahr = sorted(linien)[-JAHR:]
    res = {}
    for m in monate:
        for st, lns in zeiten[m].items():
            for ln, kinds in lns.items():
                for kind, slots in kinds.items():
                    tgt = res.setdefault(st, {}).setdefault(sline(ln), {}).setdefault(kind, {})
                    for hm, z in slots.items():
                        tgt[hm] = add(tgt.get(hm), z)
    for st, lns in res.items():
        for ln, kinds in lns.items():
            for kind in ('d', 'a'):
                if kind in kinds:
                    kinds[kind] = {hm: kurz(z) for hm, z in sorted(kinds[kind].items()) if z[0] >= 4}
            # Jahresvergleich: Monatswerte der Linie an diesem Bahnhof (Abfahrt, sonst Ankunft)
            mw = {}
            for m in jahr:
                z = None
                for raw, lk in linien[m].get(st, {}).items():   # "25" und "S25" sind dieselbe Linie
                    if sline(raw) == ln:
                        z = add(z, lk.get('d') or lk.get('a'))
                if z and z[0] >= 10:
                    k = kurz(z)
                    mw[m] = [k[0], k[1], k[0] - k[1] - k[2], k[8]]   # Fahrten, Ausfälle, ab 3 min, Schnitt×10
            kinds['m'] = mw
    os.makedirs(OUT, exist_ok=True)
    for f in glob.glob(os.path.join(OUT, '*.json')):
        os.remove(f)
    files = {}
    for st, lns in sorted(res.items()):
        fn = dateiname(st)
        files[st] = fn
        with open(os.path.join(OUT, fn), 'w', encoding='utf-8') as f:
            json.dump(lns, f, ensure_ascii=False, separators=(',', ':'))
    # Zeiten-Dateien außerhalb des Fensters braucht es nicht mehr (Linien-Dateien bleiben für den Jahresvergleich)
    for m in sorted(zeiten)[:-FENSTER]:
        os.remove(os.path.join(DATEN, f'zeiten-{m}.json.gz'))
    for m in sorted(linien)[:-JAHR]:
        os.remove(os.path.join(DATEN, f'linien-{m}.json.gz'))
    idx = {'stand': date.today().isoformat(), 'fenster': monate, 'jahr': jahr, 'quelle': QUELLE,
           'feld': ['Fahrten', 'Ausfälle', '0–2', '3–5', '6–9', '10–14', '15–29', '≥30 min', 'Schnitt×10'],
           'feld_m': ['Fahrten', 'Ausfälle', 'ab 3 min', 'Schnitt×10'], 'files': files}
    with open(os.path.join(OUT, 'index.json'), 'w', encoding='utf-8') as f:
        json.dump(idx, f, ensure_ascii=False, separators=(',', ':'))
    size = sum(os.path.getsize(os.path.join(OUT, f)) for f in os.listdir(OUT))
    print(f'{len(files)} Bahnhöfe, Fenster {monate}, Jahresvergleich {jahr[0]}…{jahr[-1]}, {size / 1e6:.1f} MB → {OUT}')


if __name__ == '__main__':
    if len(sys.argv) >= 3 and sys.argv[1] == 'monat':
        for f in sys.argv[2:]:
            monat(f)
    elif len(sys.argv) == 2 and sys.argv[1] == 'bauen':
        bauen()
    else:
        print(__doc__)
        sys.exit(1)
