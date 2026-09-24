#!/usr/bin/env python3
"""
SberAZS (sberazs.ru) Stations & Fuel Status Parser via RU VPS.
Fetches API data through ru-server to maintain clean IP reputation and bypass geo-blocks.
Includes Circuit Breaker (auto-disable flag) and instant Telegram alerts on API schema change or failures.
"""
import sys
import os
import json
import logging
import subprocess
import re
import traceback
import time
import urllib.request
from datetime import datetime, timezone
import math

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import db
import config

DISABLED_FLAG_PATH = os.path.join(BASE_DIR, 'data', 'sberazs_disabled.flag')

logging.basicConfig(
    format='%(asctime)s SBERAZS %(levelname)s %(message)s',
    level=logging.INFO,
    datefmt='%Y-%m-%d %H:%M:%S'
)

SBER_API_URL = "https://sberazs.ru/api/stations"

FUEL_CODE_MAP = {
    'ai92': '92',
    'ai95': '95',
    'ai98': '98',
    'ai100': '100',
    'diesel': 'dt',
    'gas': 'gas',
    'cng': 'gas',
    'lpg': 'gas',
    'propane': 'gas',
    'methane': 'gas',
}

def notify_admins_failure(reason: str, tb_text: str = ""):
    """Sends alert to Telegram admins when parser encounters critical error."""
    tb_snippet = tb_text.strip()[-600:] if tb_text else ""
    text = (
        f"🚨 <b>Сбой парсера SberAZS (sberazs.ru)</b>\n\n"
        f"⚠️ <b>Причина:</b> <code>{reason}</code>\n"
        f"⛔ <b>Задача парсинга временно остановлена</b> (создан защитный флаг <code>sberazs_disabled.flag</code>).\n"
    )
    if tb_snippet:
        text += f"\n🔍 <b>Детали / Трейсбек:</b>\n<pre>{tb_snippet}</pre>\n"
    text += (
        f"\n🔄 <i>Для возобновления парсинга выполните:</i>\n"
        f"<code>python scripts/parse_sberazs.py --reset</code>"
    )

    if not config.BOT_TOKEN or not config.ADMIN_IDS:
        logging.warning("Cannot send TG alert: BOT_TOKEN or ADMIN_IDS not configured")
        return

    for admin_id in config.ADMIN_IDS:
        url = f"https://api.telegram.org/bot{config.BOT_TOKEN}/sendMessage"
        body = json.dumps({
            "chat_id": admin_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }).encode("utf-8")
        try:
            req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                pass
        except Exception as e:
            logging.error(f"Failed to send TG alert to admin {admin_id}: {e}")

def fetch_data_via_ru_server():
    """
    Executes curl on ru-server over persistent SSH ControlMaster.
    Includes automatic retries for transient network/timeout glitches.
    """
    cmd = [
        "ssh", "ru-server",
        f"curl -s --compressed --connect-timeout 15 -m 60 -H 'User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36' '{SBER_API_URL}'"
    ]
    logging.info("Fetching SberAZS data via ru-server...")
    
    max_attempts = 3
    last_err = ""
    res = None
    for attempt in range(1, max_attempts + 1):
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=False, timeout=90)
        if res.returncode == 0:
            break
        last_err = res.stderr.decode('utf-8', errors='ignore')
        logging.warning(f"SberAZS fetch attempt {attempt}/{max_attempts} failed (code {res.returncode}): {last_err}")
        if attempt < max_attempts:
            time.sleep(3)
    else:
        err_code = res.returncode if res is not None else -1
        raise RuntimeError(f"SSH curl failed after {max_attempts} attempts (code {err_code}): {last_err}")
    
    raw_data = res.stdout.decode('utf-8')
    try:
        data = json.loads(raw_data)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON from SberAZS API (length {len(raw_data)}): {e}")

    # Validate high level schema
    if not isinstance(data, dict):
        raise ValueError(f"SberAZS API returned unexpected root type: {type(data)}")
    if 'stations' not in data:
        raise ValueError("SberAZS API missing 'stations' root key. Possible API structure change.")
    if not isinstance(data['stations'], list) or len(data['stations']) == 0:
        raise ValueError(f"SberAZS API returned empty stations list ({len(data.get('stations', []))})")

    # Save snapshot to data/sberazs_raw_latest.json
    try:
        data_dir = os.path.join(BASE_DIR, 'data')
        os.makedirs(data_dir, exist_ok=True)
        dump_path = os.path.join(data_dir, 'sberazs_raw_latest.json')
        with open(dump_path, 'w', encoding='utf-8') as f:
            f.write(raw_data)
        logging.info(f"Saved raw SberAZS snapshot to {dump_path}")
    except Exception as e:
        logging.warning(f"Could not save sberazs snapshot: {e}")

    return data

def calc_distance(lat1, lon1, lat2, lon2):
    """Haversine distance in meters."""
    R = 6371000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def find_matching_db_station(s_name, s_addr, s_lat, s_lon, db_stations):
    """
    Matches SberAZS station to local fuel.db stations by finding the CLOSEST station within 300m
    with brand/address priority.
    """
    s_name_lower = (s_name or '').lower()
    s_addr_clean = (s_addr or '').lower().replace('г. якутск,', '').replace('улица', '').replace('ул.', '').strip()

    best_match = None
    best_dist = 999999

    if s_lat and s_lon:
        for dbs in db_stations:
            dist = calc_distance(s_lat, s_lon, dbs['lat'], dbs['lon'])
            if dist <= 350:
                # Check brand similarity bonus
                db_brand_lower = (dbs['brand'] or '').lower()
                db_name_lower = (dbs['name'] or '').lower()
                is_same_brand = False
                if ('саханефтегазсбыт' in s_name_lower or 'снгс' in s_name_lower) and ('саханефтегазсбыт' in db_brand_lower or 'снгс' in db_name_lower):
                    is_same_brand = True
                elif 'сибойл' in s_name_lower and ('сибойл' in db_brand_lower or 'сибойл' in db_name_lower):
                    is_same_brand = True
                elif 'туймаада' in s_name_lower and ('туймаада' in db_brand_lower or 'туймаада' in db_name_lower):
                    is_same_brand = True
                elif 'опти' in s_name_lower and ('опти' in db_brand_lower or 'опти' in db_name_lower):
                    is_same_brand = True

                effective_dist = dist - (150 if is_same_brand else 0)
                if effective_dist < best_dist:
                    best_dist = effective_dist
                    best_match = (dbs['id'], dbs['name'], dist)

    if best_match and best_match[2] <= 350:
        return best_match

    # Address heuristic fallback
    for dbs in db_stations:
        db_addr_clean = (dbs['address'] or '').lower().replace('г. якутск,', '').replace('улица', '').replace('ул.', '').strip()
        if len(s_addr_clean) > 8 and (s_addr_clean in db_addr_clean or db_addr_clean in s_addr_clean):
            return dbs['id'], dbs['name'], None

    return None, None, None

def process_stations(data):
    stations = data.get('stations', [])
    logging.info(f"Total stations received from SberAZS: {len(stations)}")

    conn = db.get_conn()
    db_stations = [
        {"id": row[0], "name": row[1], "lat": row[2], "lon": row[3], "address": row[4], "brand": row[5]}
        for row in conn.execute("SELECT id, name, lat, lon, address, brand FROM stations").fetchall()
    ]

    matched_count = 0
    updated_marks = 0

    for st in stations:
        addr = st.get('address', '')
        loc = st.get('location', {})
        lat = loc.get('lat')
        lon = loc.get('lon')

        # Filter only Yakutia region
        is_yakutia = 'якут' in addr.lower() or 'саха' in addr.lower()
        if not is_yakutia and lat and lon:
            if 55.0 <= lat <= 73.0 and 110.0 <= lon <= 145.0:
                is_yakutia = True

        if not is_yakutia:
            continue

        matched_id, db_name, dist = find_matching_db_station(st.get('name', ''), addr, lat, lon, db_stations)
        
        last_payment_at = st.get('lastPaymentAt')
        fuels = st.get('fuels', [])
        
        if matched_id:
            matched_count += 1
            excl_rows = conn.execute("SELECT fuel_code FROM station_fuel_exclusions WHERE station_id = ?", (matched_id,)).fetchall()
            station_exclusions = {r[0] for r in excl_rows}

            # Add fuel status marks
            for f in fuels:
                raw_type = f.get('type')
                fuel_code = FUEL_CODE_MAP.get(raw_type)
                if not fuel_code or fuel_code in station_exclusions:
                    continue

                available = f.get('available')
                status_str = f.get('availabilityStatus')
                limit_liters = f.get('limitLiters')

                status = None
                if fuel_code == '98' and is_yakutia:
                    status = 'no'
                elif 'саханефтегазсбыт' in (st.get('name', '') + ' ' + db_name).lower() and is_yakutia:
                    if available is False or status_str == 'unavailable':
                        status = 'no'
                    elif fuel_code in ('92', '95'):
                        status, limit_liters = 'limit', 20
                    elif fuel_code == 'dt':
                        status, limit_liters = 'limit', 30
                    elif available is True or status_str == 'available':
                        status = 'yes'
                elif limit_liters and limit_liters > 0:
                    status = 'limit'
                elif available is True or status_str == 'available':
                    status = 'yes'
                elif available is False or status_str == 'unavailable':
                    status = 'no'

                # Не перетирать свежие отчёты реальных водителей о том, что топлива нет (за последние 3 часа)
                driver_no = conn.execute("""
                    SELECT id FROM marks 
                    WHERE station_id = ? AND fuel_code = ? AND status = 'no' 
                      AND mark_type != 'sberazs' AND created_at >= datetime('now', '-3 hours')
                """, (matched_id, fuel_code)).fetchone()
                if driver_no and status in ('yes', 'limit'):
                    continue

                # Record mark in fuel.db only if status is strictly determined
                if status:
                    conn.execute("""
                        INSERT INTO marks (station_id, fuel_code, status, mark_type, limit_liters, user_tg_id, username, created_at)
                        VALUES (?, ?, ?, 'sberazs', ?, 999999002, 'SberAZS Bot', datetime('now'))
                    """, (matched_id, fuel_code, status, limit_liters if limit_liters and limit_liters > 0 else None))
                    updated_marks += 1

            # Determine specific fuel codes
            recent_fuels = []
            best_fuel_time = None
            now_utc = datetime.now(timezone.utc)
            for f in fuels:
                raw_type = f.get('type')
                fc = FUEL_CODE_MAP.get(raw_type)
                if not fc or fc in station_exclusions:
                    continue
                fuel_time_str = f.get('lastFuelingAt')
                if fuel_time_str:
                    try:
                        ft = datetime.fromisoformat(fuel_time_str.replace('Z', '+00:00'))
                        if best_fuel_time is None or ft > best_fuel_time:
                            best_fuel_time = ft
                        # Only include fuels fueled within last 60 minutes
                        diff_m = (now_utc - ft).total_seconds() / 60
                        if 0 <= diff_m <= 60 and fc not in recent_fuels and not (fc == '98' and is_yakutia):
                            recent_fuels.append(fc)
                    except Exception:
                        pass

            # Fallback: if lastFuelingAt was not provided, but station has recent lastPaymentAt
            if not recent_fuels and last_payment_at:
                clean_name = (st.get('name', '') + ' ' + db_name).lower().replace('саханефтегазсбыт', '').replace('саханефтегаз', '')
                is_gas_station = bool(re.search(r'\b(?:газ|агзс|агнкс|пропан|метан)\b', clean_name))
                if is_gas_station:
                    recent_fuels = ['gas']
                else:
                    for f in fuels:
                        raw_type = f.get('type')
                        fc = FUEL_CODE_MAP.get(raw_type)
                        if not fc or fc in station_exclusions or (fc == '98' and is_yakutia):
                            continue
                        avail = f.get('available')
                        avail_st = f.get('availabilityStatus')
                        if avail is True or avail_st == 'available' or f.get('limitLiters'):
                            if fc not in recent_fuels:
                                recent_fuels.append(fc)
                    if not recent_fuels:
                        for f in fuels:
                            raw_type = f.get('type')
                            fc = FUEL_CODE_MAP.get(raw_type)
                            if not fc or fc in station_exclusions or (fc == '98' and is_yakutia):
                                continue
                            avail = f.get('available')
                            avail_st = f.get('availabilityStatus')
                            if avail is not False and avail_st != 'unavailable':
                                if fc not in recent_fuels:
                                    recent_fuels.append(fc)

            best_fuel_code = ','.join(recent_fuels) if recent_fuels else ''

            effective_pay_time = (best_fuel_time.isoformat() if best_fuel_time else last_payment_at)
            if effective_pay_time:
                conn.execute("""
                    UPDATE stations 
                    SET last_payment_at = ?, last_fuel_code = ?
                    WHERE id = ?
                """, (effective_pay_time, best_fuel_code, matched_id))

            # If lastPaymentAt is recent (last 2 hours), log activity
            if effective_pay_time:
                try:
                    pay_time = datetime.fromisoformat(effective_pay_time.replace('Z', '+00:00'))
                    now_utc = datetime.now(timezone.utc)
                    diff_mins = (now_utc - pay_time).total_seconds() / 60
                    if 0 <= diff_mins <= 120:
                        logging.info(f"Station #{matched_id} ({db_name}): Recent fueling [{best_fuel_code}] {int(diff_mins)} min ago")
                except Exception:
                    pass

    conn.commit()
    conn.close()

    if len(stations) > 1000 and matched_count == 0:
        raise ValueError("0 Yakutia stations matched out of full stations list. Possible coordinates / schema anomaly.")

    logging.info(f"SberAZS parsing completed: {matched_count} stations matched, {updated_marks} fuel marks updated.")

def main():
    # Handle reset command
    if '--reset' in sys.argv:
        if os.path.exists(DISABLED_FLAG_PATH):
            try:
                os.remove(DISABLED_FLAG_PATH)
                logging.info(f"Successfully removed disable flag: {DISABLED_FLAG_PATH}")
                print(f"✓ Flag {DISABLED_FLAG_PATH} removed. SberAZS parser re-enabled.")
            except Exception as e:
                logging.error(f"Failed to remove disable flag: {e}")
        else:
            print("✓ Parser was not disabled (no flag found).")
        return

    # Check circuit breaker
    if os.path.exists(DISABLED_FLAG_PATH) and '--force' not in sys.argv:
        try:
            with open(DISABLED_FLAG_PATH, 'r', encoding='utf-8') as f:
                reason = f.read().strip()
        except Exception:
            reason = "Unknown error"
        logging.warning(f"SberAZS parser is currently DISABLED via flag: {reason}. Skipping run. Use --reset to re-enable.")
        return

    try:
        data = fetch_data_via_ru_server()
        process_stations(data)
    except Exception as e:
        err_desc = str(e)
        tb_str = traceback.format_exc()
        logging.error(f"SberAZS parser CRITICAL error: {err_desc}", exc_info=True)

        # Write emergency disable flag
        try:
            os.makedirs(os.path.dirname(DISABLED_FLAG_PATH), exist_ok=True)
            with open(DISABLED_FLAG_PATH, 'w', encoding='utf-8') as f:
                f.write(f"[{datetime.now().isoformat()}] {err_desc}\n\n{tb_str}")
            logging.warning(f"Written circuit-breaker flag to {DISABLED_FLAG_PATH}")
        except Exception as fe:
            logging.error(f"Failed to write disable flag: {fe}")

        # Send alert to Telegram admins
        try:
            notify_admins_failure(err_desc, tb_str)
        except Exception as ne:
            logging.error(f"Failed to send notification: {ne}")

        sys.exit(1)

if __name__ == '__main__':
    main()
