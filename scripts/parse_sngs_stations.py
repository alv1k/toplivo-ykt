import json
import logging
import os
import re
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db

logging.basicConfig(
    format='%(asctime)s SNGS %(levelname)s %(message)s',
    level=logging.INFO,
    datefmt='%Y-%m-%d %H:%M:%S'
)

URL = 'https://aosngs.ru/klientam/karta-azs/'

FUEL_MAP = {
    't100': '100',
    't98': '98',
    't95': '95',
    't92': '92',
    'd': 'dt',
    'm': 'gas',
}

def fetch_page():
    req = urllib.request.Request(URL, headers={
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode('utf-8')

def extract_azs_array(html):
    start_marker = 'let azs_items = ['
    start_idx = html.find(start_marker)
    if start_idx == -1:
        return None
    start_idx += len(start_marker) - 1
    depth = 0
    for i in range(start_idx, len(html)):
        ch = html[i]
        if ch == '[':
            depth += 1
        elif ch == ']':
            depth -= 1
            if depth == 0:
                return html[start_idx:i+1]
    return None

def extract_objects(text):
    objects = []
    i = 0
    while i < len(text):
        brace_start = text.find('{', i)
        if brace_start == -1:
            break
        depth = 0
        for j in range(brace_start, len(text)):
            ch = text[j]
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    objects.append(text[brace_start:j+1])
                    i = j + 1
                    break
        else:
            break
    return objects

def extract_field(obj_text, key):
    patterns = [
        rf'{key}\s*:\s*"((?:[^"\\]|\\.)*)"',
        rf"{key}\s*:\s*'((?:[^'\\]|\\.)*)'",
        rf'{key}\s*:\s*([^,\s}}]+)',
    ]
    for pat in patterns:
        m = re.search(pat, obj_text)
        if m:
            return m.group(1)
    return None

def extract_object_field(obj_text, key):
    pat = rf'{key}\s*:\s*(\{{)'
    m = re.search(pat, obj_text)
    if not m:
        return None
    start = m.start(1)
    depth = 0
    for i in range(start, len(obj_text)):
        if obj_text[i] == '{':
            depth += 1
        elif obj_text[i] == '}':
            depth -= 1
            if depth == 0:
                return obj_text[start:i+1]
    return None

def parse_toplivo(toplivo_text):
    prices = {}
    for js_key, db_key in FUEL_MAP.items():
        val = extract_field(toplivo_text, js_key)
        if val and val != '-' and val.strip():
            try:
                prices[db_key] = float(val.strip())
            except ValueError:
                pass
    return prices

def normalize_city(city):
    if city in ('ГО г.Якутск', 'городской округ Якутск', 'г. Якутск', 'ГО Якутск'):
        return 'Якутск'
    return city

def parse_station(obj_text):
    station = {}
    station['id'] = int(extract_field(obj_text, 'id') or 0)
    station['city'] = normalize_city(extract_field(obj_text, 'city') or '')
    station['name'] = extract_field(obj_text, 'name') or ''
    station['address'] = extract_field(obj_text, 'address') or ''
    station['phone'] = extract_field(obj_text, 'phone') or ''
    station['posX'] = float(extract_field(obj_text, 'posX') or 0)
    station['posY'] = float(extract_field(obj_text, 'posY') or 0)
    station['workTime'] = extract_field(obj_text, 'workTime') or ''
    toplivo_text = extract_object_field(obj_text, 'toplivo')
    station['prices'] = parse_toplivo(toplivo_text) if toplivo_text else {}
    return station

def parse_stations(array_text):
    raw_objects = extract_objects(array_text)
    stations = []
    for obj_text in raw_objects:
        s = parse_station(obj_text)
        if s['id']:
            stations.append(s)
    return stations

def build_station_json_entry(s):
    lat = 62.070384 if s['id'] == 1046 else s['posX']
    lon = 129.795541 if s['id'] == 1046 else s['posY']
    return {
        'name': s['name'],
        'brand': 'Саханефтегазсбыт',
        'lat': lat,
        'lon': lon,
        'address': s['address'],
        'card_only': False,
        'excluded_fuels': [],
        'city': s['city'],
        'sngs_id': s['id'],
    }

def import_stations(stations):
    conn = db.get_conn()

    updated = 0
    inserted = 0
    for s in stations:
        existing = conn.execute(
            "SELECT id FROM stations WHERE brand = 'Саханефтегазсбыт' AND (sngs_id = ? OR address = ?)",
            (s['id'], s['address'])
        ).fetchone()

        if existing:
            sid = existing['id']
            if sid == 535 or s['id'] == 1046:
                # Фиксированные точные координаты для АЗС №51 (ул. 50 лет Советской Армии, 49Б)
                conn.execute(
                    "UPDATE stations SET name = ?, address = ?, city = ?, sngs_id = ? WHERE id = ?",
                    (s['name'], s['address'], s['city'], s['id'], sid)
                )
            else:
                conn.execute(
                    "UPDATE stations SET name = ?, lat = ?, lon = ?, address = ?, city = ?, sngs_id = ? WHERE id = ?",
                    (s['name'], s['posX'], s['posY'], s['address'], s['city'], s['id'], sid)
                )
            updated += 1
        else:
            cursor = conn.execute(
                "INSERT INTO stations (name, brand, lat, lon, address, city, sngs_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (s['name'], 'Саханефтегазсбыт', s['posX'], s['posY'], s['address'], s['city'], s['id'])
            )
            sid = cursor.lastrowid
            inserted += 1

        for fc, price in s['prices'].items():
            if price is not None:
                conn.execute("""
                    INSERT INTO fuel_prices(station_id, fuel_code, price, updated_at)
                    VALUES (?, ?, ?, datetime('now'))
                    ON CONFLICT(station_id, fuel_code) DO UPDATE SET
                        price=excluded.price, updated_at=excluded.updated_at
                """, (sid, fc, price))

    conn.commit()
    conn.close()
    logging.info('SNGS stations processed: %d updated, %d inserted', updated, inserted)

def generate_stations_json(stations):
    entries = [build_station_json_entry(s) for s in stations]
    json_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'stations.json')
    with open(json_path, 'r', encoding='utf-8') as f:
        existing = json.load(f)
    non_sngs = [e for e in existing if e.get('brand') != 'Саханефтегазсбыт']
    updated = non_sngs + entries
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(updated, f, ensure_ascii=False, indent=2)
    logging.info('Updated stations.json: %d non-SNGS + %d SNGS = %d total',
                 len(non_sngs), len(entries), len(updated))
    return len(entries)

def main():
    logging.info('Fetching %s ...', URL)
    html = fetch_page()

    array_text = extract_azs_array(html)
    if not array_text:
        logging.error('Could not find azs_items array in page')
        return

    stations = parse_stations(array_text)
    logging.info('Parsed %d stations from page', len(stations))

    import_stations(stations)
    count = generate_stations_json(stations)

    logging.info('Done. Total SNGS stations: %d', count)

if __name__ == '__main__':
    main()
