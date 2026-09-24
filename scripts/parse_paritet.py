import json
import logging
import os
import re
import sys
import urllib.request
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db

logging.basicConfig(
    format='%(asctime)s PARITET %(levelname)s %(message)s',
    level=logging.INFO,
    datefmt='%Y-%m-%d %H:%M:%S'
)

URL = 'http://gkparitet.ru/price'

# Station data: name, address, city, coords
STATIONS = [
    {"number": "1", "name": "АЗС Паритет №1", "address": "Нерюнгри, пересечение ул. Ленина-Геологов", "city": "Нерюнгри", "group": "neryungri"},
    {"number": "3", "name": "АЗС Паритет №3", "address": "Нерюнгри, УМИТ", "city": "Нерюнгри", "group": "neryungri"},
    {"number": "6", "name": "АЗС Паритет №6", "address": "Алдан, ул. Билибина (636 км ФАД Лена)", "city": "Алдан", "group": "aldan"},
    {"number": "7", "name": "АЗС Паритет №7", "address": "Алдан, ул. Тихая, 6, мкр. Солнечный", "city": "Алдан", "group": "aldan"},
    {"number": "8", "name": "АЗС Паритет №8", "address": "Алдан, ул. 50 лет ВЛКСМ, 91", "city": "Алдан", "group": "aldan"},
    {"number": "9", "name": "АЗС Паритет №9", "address": "Куранах, 662 км ФАД Лена", "city": "Алданский район", "group": "aldan"},
    {"number": "10", "name": "АЗС Паритет №10", "address": "Томмот, 720 км ФАД Лена", "city": "Томмот", "group": "aldan"},
]

# Approximate coordinates (would benefit from geocoding)
# Neryungri area
NER_COORDS = (56.66, 124.72)
# Aldan area
ALD_COORDS = (58.60, 125.36)
KUR_COORDS = (58.13, 125.50)
TOM_COORDS = (58.97, 126.27)

COORDS = {
    "1": (56.660, 124.710),
    "3": (56.655, 124.745),
    "6": (58.598, 125.365),
    "7": (58.610, 125.330),
    "8": (58.602, 125.380),
    "9": (58.135, 125.500),
    "10": (58.970, 126.270),
}

def fetch_page():
    req = urllib.request.Request(URL, headers={
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'
    })
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read().decode('utf-8')

def parse_prices(html):
    # Extract tn-atom text content
    texts = re.findall(r'tn-atom[^>]*>([^<]+)', html)
    texts = [t.strip() for t in texts if t.strip()]

    price_rows = []
    for t in texts:
        if t.startswith('99') and ',' in t:
            price_rows.append(('kerosene', float(t.replace(',', '.'))))
        elif t.startswith('95') and ',' in t:
            price_rows.append(('dt', float(t.replace(',', '.'))))
        elif t.startswith('90') and ',' in t:
            price_rows.append(('98', float(t.replace(',', '.'))))
        elif t.startswith('83') and ',' in t:
            price_rows.append(('95', float(t.replace(',', '.'))))
        elif t.startswith('79') and ',' in t:
            price_rows.append(('92', float(t.replace(',', '.'))))

    prices_neryungri = {}
    prices_aldan = {}
    for fc, val in price_rows:
        if fc == '92':
            prices_neryungri[fc] = val
            prices_aldan[fc] = val
        elif fc == '95':
            prices_neryungri[fc] = val
            prices_aldan[fc] = val
        elif fc == '98':
            prices_neryungri[fc] = val
            prices_aldan[fc] = val
        elif fc == 'dt':
            prices_neryungri[fc] = val
            prices_aldan[fc] = val
        elif fc == 'kerosene':
            prices_aldan[fc] = val

    return {'neryungri': prices_neryungri, 'aldan': prices_aldan}

def import_stations(prices_by_group):
    conn = db.get_conn()

    updated = 0
    inserted = 0
    for s in STATIONS:
        prices = prices_by_group.get(s['group'], {})
        lat, lon = COORDS.get(s['number'], (0, 0))

        existing = conn.execute(
            "SELECT id FROM stations WHERE brand = 'Паритет' AND name = ?",
            (s['name'],)
        ).fetchone()

        if existing:
            sid = existing['id']
            conn.execute(
                "UPDATE stations SET lat = ?, lon = ?, address = ?, city = ? WHERE id = ?",
                (lat, lon, s['address'], s['city'], sid)
            )
            updated += 1
        else:
            cursor = conn.execute(
                "INSERT INTO stations (name, brand, lat, lon, address, city) VALUES (?, ?, ?, ?, ?, ?)",
                (s['name'], 'Паритет', lat, lon, s['address'], s['city'])
            )
            sid = cursor.lastrowid
            inserted += 1

        for fc, price in prices.items():
            if fc != 'kerosene':
                conn.execute("""
                    INSERT INTO fuel_prices(station_id, fuel_code, price, updated_at)
                    VALUES (?, ?, ?, datetime('now'))
                    ON CONFLICT(station_id, fuel_code) DO UPDATE SET
                        price=excluded.price, updated_at=excluded.updated_at
                """, (sid, fc, price))

    conn.commit()
    conn.close()
    logging.info('Паритет stations processed: %d updated, %d inserted', updated, inserted)

def generate_stations_json():
    entries = []
    for s in STATIONS:
        lat, lon = COORDS.get(s['number'], (0, 0))
        entries.append({
            'name': s['name'],
            'brand': 'Паритет',
            'lat': lat,
            'lon': lon,
            'address': s['address'],
            'card_only': False,
            'excluded_fuels': [],
            'city': s['city'],
        })

    json_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'stations.json')
    with open(json_path, 'r', encoding='utf-8') as f:
        existing = json.load(f)

    # Remove old Паритет entries
    non_paritet = [e for e in existing if e.get('brand') != 'Паритет']
    updated = non_paritet + entries

    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(updated, f, ensure_ascii=False, indent=2)
    logging.info('Updated stations.json: %d entries', len(updated))
    return len(entries)

def main():
    logging.info('Fetching %s ...', URL)
    html = fetch_page()

    prices = parse_prices(html)
    logging.info('Prices: Neryungri=%s, Aldan=%s', prices['neryungri'], prices['aldan'])

    import_stations(prices)
    count = generate_stations_json()
    logging.info('Done. %d Paritet stations', count)

if __name__ == '__main__':
    main()
