import json
import logging
import os
import re
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bs4 import BeautifulSoup
import db

logging.basicConfig(
    format='%(asctime)s SIBOIL %(levelname)s %(message)s',
    level=logging.INFO,
    datefmt='%Y-%m-%d %H:%M:%S'
)

URL = 'https://xn--90anbmnp.xn--p1ai/products_services/fuel/'

FUEL_MAP = {
    '98': '98',
    '95': '95',
    '92': '92',
    '92 эф.': '92ef',
    '92эф.': '92ef',
    'дт': 'dt',
    'тс-1': 'ts1',
    'пба': 'gas',
}

AGZS_COLUMNS = ['number', 'address', 'price']

def parse_price(val):
    val = val.strip()
    if not val or val.lower() == 'нет':
        return None
    m = re.search(r'([\d]+[.,][\d]+)', val.replace('\xa0', ' '))
    if m:
        return float(m.group(1).replace(',', '.'))
    return None

def fetch_page():
    req = urllib.request.Request(URL, headers={
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'
    })
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read().decode('utf-8')

def parse_table(html):
    soup = BeautifulSoup(html, 'lxml')
    tbl = soup.find('table')
    if not tbl:
        logging.error('No table found on page')
        return []

    rows = tbl.find_all('tr')
    results = []
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
            if 'АГЗС' in second and not any(x in second for x in ['район', 'Якутск', 'улус', 'итого', 'Всего']):
                is_agzs = True
                current_brand = 'Газ'
                current_region = 'АГЗС'
            elif 'АЗС' in second:
                is_agzs = False
                region_match = re.match(r'АЗС\s+(.+?)\s+(.+)$', second)
                if region_match:
                    current_brand = region_match.group(1)
                    current_region = region_match.group(2)
                else:
                    current_brand = 'СибОйл'
                    current_region = second
            continue

        if not first and not second:
            continue

        if first.isdigit() and second:
            station_num = int(first)

            if is_agzs:
                price = parse_price(cells[2]) if len(cells) > 2 else None
                if price is not None:
                    results.append({
                        'number': 100 + station_num,
                        'address': second,
                        'brand': 'Газ',
                        'region': 'АГЗС',
                        'prices': {'gas': price},
                    })
            else:
                col_map = ['98', '95', '92', '92ef', 'dt', 'ts1']
                prices = {}
                for idx, fc in enumerate(col_map):
                    if idx + 2 < len(cells):
                        p = parse_price(cells[idx + 2])
                        if p is not None:
                            prices[fc] = p
                results.append({
                    'number': station_num,
                    'address': second,
                    'brand': current_brand,
                    'region': current_region or '',
                    'prices': prices,
                })

    return results


def update_prices(entries):
    changes = []
    for e in entries:
        station_id = db.get_station_by_siboil_number(e['number'])
        if not station_id:
            continue
        for fc, price in e['prices'].items():
            old = db.get_prices(station_id).get(fc)
            old_price = old['price'] if old else None
            if old_price != price:
                db.set_price(station_id, fc, price)
                changes.append({
                    'station_id': station_id,
                    'siboil_number': e['number'],
                    'fuel_code': fc,
                    'old_price': old_price,
                    'new_price': price,
                })
    return changes


def main():
    logging.info('Fetching %s ...', URL)
    html = fetch_page()

    entries = parse_table(html)
    logging.info('Parsed %d station entries', len(entries))

    changes = update_prices(entries)
    if changes:
        for c in changes:
            old = f'{c["old_price"]:.1f}' if c['old_price'] is not None else '—'
            new = f'{c["new_price"]:.1f}' if c['new_price'] is not None else '—'
            logging.info('Station #%d fuel %s: %s -> %s', c['siboil_number'], c['fuel_code'], old, new)
    else:
        logging.info('No price changes')

    # Summary
    unmatched = [e for e in entries if not db.get_station_by_siboil_number(e['number'])]
    if unmatched:
        nums = sorted(set(e['number'] for e in unmatched))
        logging.warning('Unmatched siboil station numbers: %s', nums)

    logging.info('Done')
    return changes


if __name__ == '__main__':
    main()
