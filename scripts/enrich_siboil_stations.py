import json
import logging
import os
import re
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bs4 import BeautifulSoup

logging.basicConfig(
    format='%(asctime)s ENRICH %(levelname)s %(message)s',
    level=logging.INFO,
    datefmt='%Y-%m-%d %H:%M:%S'
)

FUEL_URL = 'https://xn--90anbmnp.xn--p1ai/products_services/fuel/'
STATION_URL = 'https://xn--90anbmnp.xn--p1ai/products_services/station/'
NOMINATIM_URL = 'https://nominatim.openstreetmap.org/search'

def fetch(url):
    req = urllib.request.Request(url, headers={
        'User-Agent': 'ToplivoYakutskEnrich/1.0 (alvik@344988.snk.wtf)'
    })
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read().decode('utf-8')

def parse_fuel_table(html):
    soup = BeautifulSoup(html, 'lxml')
    tbl = soup.find('table')
    if not tbl:
        return {}

    rows = tbl.find_all('tr')
    stations = {}
    current_region = None
    current_brand = 'СибОйл'
    is_agzs = False

    for r in rows:
        cells = [c.get_text(strip=True) for c in r.find_all(['th', 'td'])]
        if not cells:
            continue

        first = cells[0] if len(cells) > 0 else ''
        second = cells[1] if len(cells) > 1 else ''

        if not first and second and ('АЗС' in second or 'АГЗС' in second):
            if 'АГЗС' in second:
                is_agzs = True
                current_brand = 'Газ'
                current_region = 'АГЗС'
            else:
                is_agzs = False
                m = re.match(r'АЗС\s+(.+?)\s+(.+)$', second)
                if m:
                    current_brand = m.group(1)
                    current_region = m.group(2)
                else:
                    current_brand = 'СибОйл'
                    current_region = second
            continue

        if not first and not second:
            continue

        if first.isdigit() and second:
            num = int(first)
            if is_agzs:
                name = f'АГЗС №{num}'
                brand = 'Газ'
            else:
                name = f'АЗС СибОйл №{num}'
                brand = current_brand

            if num not in stations:
                stations[num] = {
                    'number': num,
                    'name': name,
                    'brand': brand,
                    'address': second,
                    'region': current_region or '',
                    'city': extract_city(second, current_region or ''),
                }

    return stations

def parse_station_page(html):
    soup = BeautifulSoup(html, 'lxml')
    # The station list is in the page content as text lines
    content = soup.get_text()
    stations = {}
    # Pattern: АЗС №\d+: address
    for m in re.finditer(r'(АЗС|АГЗС|МАЗС)\s*№(\d+)[:.]*\s*(.*?)(?=(?:\n\s*(?:АЗС|АГЗС|МАЗС)\s*№)|$)', content, re.DOTALL):
        stype = m.group(1)
        num = int(m.group(2))
        addr = m.group(3).strip()
        stations[num] = {'type': stype, 'address': addr}
    return stations

def extract_city(address, region):
    address_lower = address.lower()
    if 'якутск' in address_lower:
        return 'Якутск'
    if 'покровск' in address_lower:
        return 'Покровск'
    if 'майя' in address_lower or 'майа' in address_lower:
        return 'Майя'
    if 'бестях' in address_lower:
        return 'Нижний Бестях'
    if 'вилюйск' in address_lower:
        return 'Вилюйск'
    if 'кысыл-сыр' in address_lower or 'кысыл сыр' in address_lower:
        return 'Кысыл-Сыр'
    if 'илбенге' in address_lower:
        return 'Илбенге'
    if 'октемцы' in address_lower:
        return 'Октемцы'
    if 'хангалас' in region.lower():
        return 'Хангаласский улус'
    if 'мегино' in region.lower():
        return 'Мегино-Кангаласский улус'
    if 'вилюй' in region.lower():
        return 'Вилюйский улус'
    return 'Якутск'

def geocode(address, retries=3):
    params = (
        f'{NOMINATIM_URL}?q={urllib.request.quote(address)}'
        f'&format=json&limit=1&accept-language=ru'
    )
    for attempt in range(retries):
        try:
            req = urllib.request.Request(params, headers={
                'User-Agent': 'ToplivoYakutskEnrich/1.0'
            })
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            if data:
                return float(data[0]['lat']), float(data[0]['lon'])
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2)
            else:
                logging.warning('Geocode failed for %s: %s', address, e)
    return None, None


def main():
    logging.info('Fetching fuel page...')
    fuel_html = fetch(FUEL_URL)
    fuel_stations = parse_fuel_table(fuel_html)

    logging.info('Fetching station page...')
    try:
        station_html = fetch(STATION_URL)
        station_details = parse_station_page(station_html)
    except Exception as e:
        logging.warning('Failed to fetch station page: %s', e)
        station_details = {}

    logging.info('Found %d stations in fuel table', len(fuel_stations))

    # Build search queries for geocoding
    geocode_queries = {}
    for num, s in sorted(fuel_stations.items()):
        addr = s['address']
        if 'якутск' in addr.lower():
            query = f'{addr}, Якутск, Россия'
        elif 'покровск' in addr.lower():
            query = f'{addr}, Покровск, Россия'
        elif 'майя' in addr.lower():
            query = f'{addr}, Майя, Якутия, Россия'
        elif 'бестях' in addr.lower():
            query = f'{addr}, Нижний Бестях, Якутия, Россия'
        elif 'вилюйск' in addr.lower():
            query = f'{addr}, Вилюйск, Якутия, Россия'
        elif 'кысыл' in addr.lower():
            query = f'{addr}, Кысыл-Сыр, Якутия, Россия'
        elif 'илбенге' in addr.lower():
            query = f'{addr}, Илбенге, Якутия, Россия'
        elif 'октемцы' in addr.lower():
            query = f'{addr}, Октемцы, Якутия, Россия'
        else:
            query = f'{addr}, Якутия, Россия'
        geocode_queries[num] = query

    # Load existing stations
    stations_json_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'stations.json')
    with open(stations_json_path, 'r', encoding='utf-8') as f:
        existing_stations = json.load(f)

    # Build lookup by address pattern
    existing_by_addr = {}
    for s in existing_stations:
        addr_key = s.get('address', '').strip().lower()
        if addr_key:
            existing_by_addr[addr_key] = s

    # Add/update siboil stations
    added = 0
    updated = 0
    new_stations = []
    siboil_numbers_used = set()

    for num, s in sorted(fuel_stations.items()):
        siboil_numbers_used.add(num)
        address_lower = s['address'].lower()

        # Check if station already exists by address pattern
        matched = False
        for existing in existing_stations:
            ex_addr = existing.get('address', '').strip().lower()
            if ex_addr and (ex_addr in address_lower or address_lower in ex_addr):
                existing['brand'] = s['brand']
                existing['siboil_number'] = num
                if s.get('city'):
                    existing['city'] = s['city']
                updated += 1
                matched = True
                break

        if matched:
            continue

        # Also check existing stations with empty address but matching name/coordinates
        for existing in existing_stations:
            ex_name = existing.get('name', '').lower()
            if not existing.get('address') and s['brand'] == 'СибОйл' and ('азс' in ex_name or 'сибойл' in ex_name):
                # These exist but we can't reliably match - skip re-adding
                pass

        # Geocode new station
        lat, lon = None, None
        query = geocode_queries[num]
        logging.info('Geocoding station #%d: %s', num, query)
        lat, lon = geocode(query)
        if lat is None:
            # Try shorter query
            short = s['address'].split(',')[0].strip()
            logging.info('Retry with: %s, Якутск', short)
            lat, lon = geocode(f'{short}, Якутск, Россия')
        time.sleep(1.5)

        new_entry = {
            'name': s['name'],
            'brand': s['brand'],
            'lat': lat or 0.0,
            'lon': lon or 0.0,
            'address': s['address'],
            'card_only': s['brand'] == 'СибОйл',
            'excluded_fuels': [],
            'city': s.get('city', 'Якутск'),
            'siboil_number': num,
        }
        new_stations.append(new_entry)
        added += 1

    # Output
    logging.info('Updated %d existing stations with siboil brand', updated)
    logging.info('Added %d new stations (geocoded)', added)

    # Merge existing + new
    all_stations = existing_stations + new_stations

    output_path = stations_json_path
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(all_stations, f, ensure_ascii=False, indent=2)

    logging.info('Written %d stations to %s', len(all_stations), output_path)
    logging.info('Siboil numbers used: %s', sorted(siboil_numbers_used))

    print(f'\nSiboil stations added: {added}')
    print(f'Existing stations updated: {updated}')
    print(f'Total stations in JSON: {len(all_stations)}')
    if new_stations:
        print('\nNew stations (need coordinate check):')
        for ns in new_stations:
            flag = '⚠️' if ns['lat'] == 0 else '✅'
            print(f'  {flag} #{ns["siboil_number"]} {ns["name"]} '
                  f'({ns["lat"]:.4f}, {ns["lon"]:.4f}) — {ns["address"][:50]}')


if __name__ == '__main__':
    main()
