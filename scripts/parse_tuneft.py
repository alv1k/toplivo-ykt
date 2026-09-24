import json
import logging
import os
import re
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db

logging.basicConfig(
    format='%(asctime)s TUNEFT %(levelname)s %(message)s',
    level=logging.INFO,
    datefmt='%Y-%m-%d %H:%M:%S'
)

URL = 'https://tuneft.ru/'

STATIONS_RAW = [
    {"address": "Улица Дзержинского, 56а",              "lat": 62.053585,  "lon": 129.740519,  "city": "Якутск"},
    {"address": "Вилюйский тракт 4 километр, 6а",        "lat": 62.034444,  "lon": 129.679113,  "city": "Якутск"},
    {"address": "Улица Автострада 50 лет Октября, 14з",  "lat": 62.072245,  "lon": 129.742776,  "city": "Якутск"},
    {"address": "Улица Билибина, 68Б",                   "lat": 62.027390,  "lon": 129.634725,  "city": "Якутск"},
    {"address": "Улица 50 лет Советской Армии, 55Б",     "lat": 62.079880,  "lon": 129.798879,  "city": "Якутск"},
    {"address": "Проспект Михаила Николаева, 31а",       "lat": 61.988540,  "lon": 129.682590,  "city": "Якутск"},
    {"address": "Покровский тракт 5 километр, 2Б",       "lat": 61.993110,  "lon": 129.704684,  "city": "Якутск"},
    {"address": "Хатын-Юряхское шоссе 9 км, 7/1а",       "lat": 62.048667,  "lon": 129.652423,  "city": "Якутск"},
    {"address": "Улица Намская, 1Б",                     "lat": 62.110231,  "lon": 129.763708,  "city": "Якутск"},
    {"address": "Улица Автострада 50 лет Октября, 1з",   "lat": 62.072953,  "lon": 129.741016,  "city": "Якутск"},
    {"address": "Улица Автострада 50 лет Октября, 10/1Б","lat": 62.070272,  "lon": 129.743299,  "city": "Якутск", "is_gas": True},
    {"address": "Ленина, 66, пгт Нижний Бестях",         "lat": 61.950579,  "lon": 129.901188,  "city": "Нижний Бестях"},
    {"address": "Ленина, 109/1, пгт Нижний Бестях",      "lat": 61.973600,  "lon": 129.933213,  "city": "Нижний Бестях"},
    {"address": "Пристанская, 12, пгт Нижний Бестях",    "lat": 61.986743,  "lon": 129.915614,  "city": "Нижний Бестях"},
    {"address": "Подстанционная, 1 к1, с. Майя",         "lat": 61.743237,  "lon": 130.265660,  "city": "Майя"},
    {"address": "Мамыканская, 1 к1, с. Майя",            "lat": 61.750079,  "lon": 130.258354,  "city": "Майя"},
    {"address": "Р-504 180 км, с. Чурапча",              "lat": 61.991525,  "lon": 132.472856,  "city": "Чурапча"},
    {"address": "Трактовая, 2д, с. Чурапча",             "lat": 61.981525,  "lon": 132.430103,  "city": "Чурапча"},
    {"address": "с. Улахан-Ан, Хангаласский улус",       "lat": 61.308107,  "lon": 128.281385,  "city": "Улахан-Ан"},
    {"address": "Верхняя деревня, 10з, с. Амга",         "lat": 60.896888,  "lon": 131.906272,  "city": "Амга"},
    {"address": "Мира, 135, г. Вилюйск",                "lat": 63.751503,  "lon": 121.693298,  "city": "Вилюйск"},
    {"address": "Ленина, 76, с. Мындаба",               "lat": 62.653430,  "lon": 131.198102,  "city": "Мындаба"},
    {"address": "пгт Усть-Нера, Оймяконский улус",       "lat": 64.566364,  "lon": 143.257436,  "city": "Усть-Нера"},
    {"address": "Заправочная станция, с. Диринг",        "lat": 61.825625,  "lon": 132.105213,  "city": "Диринг"},
]

# Default base prices (Якутск most stations)
BASE_PRICES = {'92': 93.0, '95': 96.0, '98': 87.0, 'dt': 106.0}

# Per-station price overrides (address -> {fuel: price})
PRICE_OVERRIDES = {
    "Ленина, 66, пгт Нижний Бестях":        {'92': 76.5, '95': 80.5, '98': 87.0, 'dt': 94.0},
    "Ленина, 109/1, пгт Нижний Бестях":     {'92': 76.5, '95': 80.5, 'dt': 94.0},
    "Подстанционная, 1 к1, с. Майя":        {'92': 76.5, '95': 80.5, 'dt': 94.0},
    "Мамыканская, 1 к1, с. Майя":           {'92': 76.5, '95': 80.5, '98': 87.0, 'dt': 94.0},
    "Р-504 180 км, с. Чурапча":             {'92': 77.5, '95': 81.0, 'dt': 95.0},
    "с. Улахан-Ан, Хангаласский улус":      {'92': 78.9, '95': 81.5, 'dt': 95.0},
    "Верхняя деревня, 10з, с. Амга":        {'92': 77.5, '95': 81.0, '100': 100.0},
    "Мира, 135, г. Вилюйск":               {'92': 88.0, '95': 82.0, 'dt': 95.0},
    "Ленина, 76, с. Мындаба":              {'92': 77.5, '95': 81.0, 'dt': 95.0},
    "пгт Усть-Нера, Оймяконский улус":      {'92': 86.1, '95': 91.0, 'dt': 112.0},
    "Заправочная станция, с. Диринг":       {'92': 91.0, '95': 100.0, '98': 100.0, '100': 100.0, 'dt': 100.0},
    "Пристанская, 12, пгт Нижний Бестях":    {'92': 90.1, '95': 100.0, '98': 100.0, '100': 100.0, 'dt': 100.0},
    "Трактовая, 2д, с. Чурапча":            {'95': 81.0, '98': 87.0},
}

def get_name_from_address(addr):
    short = addr.split(',')[0].strip()
    if 'Дзержинского' in short: return "АЗС Туймаада-Нефть Дзержинского"
    if 'Вилюйский тракт' in short or 'Вилюйский' in short: return "АЗС Туймаада-Нефть Вилюйский тракт"
    if 'Автострада' in short and '14з' in addr: return "АЗС Туймаада-Нефть Автострада 14"
    if 'Автострада' in short and '1з' in addr: return "АЗС Туймаада-Нефть Автострада 1"
    if 'Автострада' in short and '10' in addr: return "АЗС Туймаада-Нефть Автострада 10"
    if 'Билибина' in short: return "АЗС Туймаада-Нефть Билибина"
    if '50 лет Советской' in short or 'Советской' in short: return "АЗС Туймаада-Нефть 50 лет СА"
    if 'Николаева' in short: return "АЗС Туймаада-Нефть Николаева"
    if 'Покровский' in short: return "АЗС Туймаада-Нефть Покровский тракт"
    if 'Хатын-Юрях' in short: return "АЗС Туймаада-Нефть Хатын-Юрях"
    if 'Намская' in short: return "АЗС Туймаада-Нефть Намская"
    if 'Нижний Бестях' in addr:
        if 'Ленина, 66' in addr: return "АЗС Туймаада-Нефть Нижний Бестях (Ленина 66)"
        if 'Ленина, 109' in addr: return "АЗС Туймаада-Нефть Нижний Бестях (Ленина 109)"
        if 'Пристанская' in addr: return "АЗС Туймаада-Нефть Нижний Бестях (Пристанская)"
    if 'Майя' in addr:
        if 'Подстанционная' in addr: return "АЗС Туймаада-Нефть Майя (Подстанционная)"
        if 'Мамыканская' in addr: return "АЗС Туймаада-Нефть Майя (Мамыканская)"
    if 'Чурапча' in addr:
        if 'Р-504' in addr: return "АЗС Туймаада-Нефть Чурапча (Р-504)"
        if 'Трактовая' in addr: return "АЗС Туймаада-Нефть Чурапча (Трактовая)"
    if 'Улахан-Ан' in addr: return "АЗС Туймаада-Нефть Улахан-Ан"
    if 'Амга' in addr: return "АЗС Туймаада-Нефть Амга"
    if 'Вилюйск' in addr: return "АЗС Туймаада-Нефть Вилюйск"
    if 'Мындаба' in addr: return "АЗС Туймаада-Нефть Мындаба"
    if 'Усть-Нера' in addr: return "АЗС Туймаада-Нефть Усть-Нера"
    if 'Диринг' in addr: return "АЗС Туймаада-Нефть Диринг"
    return f"АЗС Туймаада-Нефть ({short})"

def get_prices_for_station(addr):
    if addr in PRICE_OVERRIDES:
        return PRICE_OVERRIDES[addr]
    return dict(BASE_PRICES)

def extract_updated_prices(html):
    matches = re.findall(r'"latitude"\s*:\s*([\d.]+).*?"longitude"\s*:\s*([\d.]+)', html[:10000])
    if len(matches) < 23:
        return None

    prices = re.findall(r'([\d.]+)\s*,\s*[\d.]+\s*,\s*[\d.]+\)', html)
    return len(matches)

def import_stations():
    conn = db.get_conn()

    updated = 0
    inserted = 0
    for s in STATIONS_RAW:
        is_gas = s.get('is_gas', False)
        prices = {'gas': 27.5} if is_gas else get_prices_for_station(s['address'])
        name = ('АГЗС Туймаада-Нефть (Автострада 10)' if is_gas else get_name_from_address(s['address']))
        brand = 'Газ' if is_gas else 'Туймаада-Нефть'

        existing = conn.execute(
            "SELECT id FROM stations WHERE address = ?",
            (s['address'],)
        ).fetchone()

        if existing:
            sid = existing['id']
            conn.execute(
                "UPDATE stations SET name = ?, brand = ?, lat = ?, lon = ?, city = ? WHERE id = ?",
                (name, brand, s['lat'], s['lon'], s['city'], sid)
            )
            updated += 1
        else:
            cursor = conn.execute(
                "INSERT INTO stations (name, brand, lat, lon, address, city) VALUES (?, ?, ?, ?, ?, ?)",
                (name, brand, s['lat'], s['lon'], s['address'], s['city'])
            )
            sid = cursor.lastrowid
            inserted += 1

        if is_gas:
            for fc in ["92", "95", "98", "100", "dt", "ts1"]:
                conn.execute("INSERT OR IGNORE INTO station_fuel_exclusions (station_id, fuel_code) VALUES (?, ?)", (sid, fc))

        for fc, price in prices.items():
            conn.execute("""
                INSERT INTO fuel_prices(station_id, fuel_code, price, updated_at)
                VALUES (?, ?, ?, datetime('now'))
                ON CONFLICT(station_id, fuel_code) DO UPDATE SET
                    price=excluded.price, updated_at=excluded.updated_at
            """, (sid, fc, price))

    conn.commit()
    conn.close()
    logging.info('Туймаада-Нефть stations processed: %d updated, %d inserted', updated, inserted)

def generate_stations_json():
    entries = []
    for s in STATIONS_RAW:
        entries.append({
            'name': get_name_from_address(s['address']),
            'brand': 'Туймаада-Нефть',
            'lat': s['lat'],
            'lon': s['lon'],
            'address': s['address'],
            'card_only': False,
            'excluded_fuels': [],
            'city': s['city'],
        })

    json_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'stations.json')
    with open(json_path, 'r', encoding='utf-8') as f:
        existing = json.load(f)

    non_tuneft = [e for e in existing if e.get('brand') != 'Туймаада-Нефть']
    updated = non_tuneft + entries

    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(updated, f, ensure_ascii=False, indent=2)
    logging.info('Updated stations.json: %d non-Tuymaada + %d Tuymaada = %d total',
                 len(non_tuneft), len(entries), len(updated))
    return len(entries)

def main():
    logging.info('Fetching %s ...', URL)
    try:
        req = urllib.request.Request(URL, headers={
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode('utf-8')
        count = extract_updated_prices(html)
        if count:
            logging.info('Page loaded: %d stations found', count)
    except Exception as e:
        logging.warning('Could not fetch page: %s. Using default prices.', e)

    import_stations()
    count = generate_stations_json()
    logging.info('Done. %d Туймаада-Нефть stations', count)

if __name__ == '__main__':
    main()
