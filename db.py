import sqlite3
import json
import re
from datetime import datetime, timedelta
from config import DB_PATH

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def init_db():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS stations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            brand TEXT DEFAULT '',
            lat REAL NOT NULL,
            lon REAL NOT NULL,
            address TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS fuel_marks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE NOT NULL,
            label TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS marks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            station_id INTEGER NOT NULL,
            fuel_code TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('yes','no','queue','limit')),
            mark_type TEXT DEFAULT 'full',
            queue_count INTEGER,
            payment_method TEXT,
            bonus_card INTEGER,
            pump_number TEXT,
            user_tg_id INTEGER,
            username TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(station_id) REFERENCES stations(id)
        );

        CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_tg_id INTEGER NOT NULL,
            station_id INTEGER NOT NULL,
            fuel_code TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_tg_id, station_id, fuel_code),
            FOREIGN KEY(station_id) REFERENCES stations(id)
        );

        CREATE TABLE IF NOT EXISTS station_fuel_exclusions (
            station_id INTEGER NOT NULL,
            fuel_code TEXT NOT NULL,
            PRIMARY KEY (station_id, fuel_code),
            FOREIGN KEY(station_id) REFERENCES stations(id)
        );

        CREATE TABLE IF NOT EXISTS fuel_prices (
            station_id INTEGER NOT NULL,
            fuel_code TEXT NOT NULL,
            price REAL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(station_id, fuel_code),
            FOREIGN KEY(station_id) REFERENCES stations(id)
        );

        CREATE TABLE IF NOT EXISTS comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            station_id INTEGER NOT NULL,
            user_tg_id INTEGER,
            username TEXT DEFAULT '',
            comment TEXT,
            has_photo INTEGER DEFAULT 0,
            photo_path TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(station_id) REFERENCES stations(id)
        );

        CREATE TABLE IF NOT EXISTS comment_reactions (
            comment_id INTEGER NOT NULL,
            user_tg_id INTEGER NOT NULL,
            reaction INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(comment_id, user_tg_id),
            FOREIGN KEY(comment_id) REFERENCES comments(id)
        );

        CREATE TABLE IF NOT EXISTS station_suggestions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            brand TEXT DEFAULT '',
            lat REAL NOT NULL,
            lon REAL NOT NULL,
            address TEXT DEFAULT '',
            city TEXT DEFAULT 'Якутск',
            comment TEXT DEFAULT '',
            user_tg_id INTEGER,
            username TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_marks_station ON marks(station_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_marks_fuel ON marks(fuel_code, created_at);
        CREATE INDEX IF NOT EXISTS idx_marks_created_at ON marks(created_at);
        CREATE INDEX IF NOT EXISTS idx_comments_station ON comments(station_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_comments_created_at ON comments(created_at);
        CREATE INDEX IF NOT EXISTS idx_reactions_comment ON comment_reactions(comment_id);

        CREATE TABLE IF NOT EXISTS page_views (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ip TEXT NOT NULL,
            user_agent TEXT DEFAULT '',
            visited_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_page_views_ip ON page_views(ip, visited_at);
        CREATE INDEX IF NOT EXISTS idx_page_views_date ON page_views(visited_at);

        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_tg_id INTEGER,
            username TEXT DEFAULT '',
            feedback_type TEXT DEFAULT 'other',
            station_id INTEGER,
            message TEXT NOT NULL,
            contact TEXT DEFAULT '',
            status TEXT DEFAULT 'new',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(station_id) REFERENCES stations(id)
        );
        CREATE INDEX IF NOT EXISTS idx_feedback_created ON feedback(created_at);

        CREATE TABLE IF NOT EXISTS user_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT DEFAULT '',
            guest_id TEXT DEFAULT '',
            user_tg_id INTEGER,
            username TEXT DEFAULT '',
            event_name TEXT NOT NULL,
            station_id INTEGER,
            event_data TEXT DEFAULT '{}',
            ip TEXT DEFAULT '',
            user_agent TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_user_events_name_time ON user_events(event_name, created_at);
        CREATE INDEX IF NOT EXISTS idx_user_events_station ON user_events(station_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_user_events_guest ON user_events(guest_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_user_events_created ON user_events(created_at);
    """)
    fuels = [('92', 'АИ-92'), ('95', 'АИ-95'), ('98', 'АИ-98'), ('100', 'АИ-100'), ('dt', 'ДТ'), ('gas', 'Газ'), ('ts1', 'ТС-1'), ('92ef', '92 Эф.')]
    for code, label in fuels:
        conn.execute("INSERT OR IGNORE INTO fuel_marks(code, label) VALUES (?, ?)", (code, label))
    conn.commit()
    _run_migrations(conn)
    conn.close()

def _run_migrations(conn):
    migrations = [
        "ALTER TABLE stations ADD COLUMN city TEXT DEFAULT 'Якутск'",
        "ALTER TABLE stations ADD COLUMN card_only INTEGER DEFAULT 0",
        "ALTER TABLE marks ADD COLUMN mark_type TEXT DEFAULT 'full'",
        "ALTER TABLE marks ADD COLUMN queue_count INTEGER",
        "ALTER TABLE marks ADD COLUMN payment_method TEXT",
        "ALTER TABLE marks ADD COLUMN bonus_card INTEGER",
        "ALTER TABLE marks ADD COLUMN pump_number TEXT",
        "ALTER TABLE stations ADD COLUMN siboil_number INTEGER",
        "ALTER TABLE stations ADD COLUMN sngs_id INTEGER",
        "ALTER TABLE stations ADD COLUMN automatic INTEGER DEFAULT 0",
        "ALTER TABLE stations ADD COLUMN is_closed INTEGER DEFAULT 0",
        "ALTER TABLE stations ADD COLUMN reopen_date TEXT DEFAULT ''",
        "ALTER TABLE stations ADD COLUMN closed_reason TEXT DEFAULT ''",
    ]
    for sql in migrations:
        try:
            conn.execute(sql)
        except sqlite3.OperationalError:
            pass
    conn.commit()

def load_stations():
    conn = get_conn()
    rows = conn.execute("""
        SELECT id, name, brand, lat, lon, address, 
               COALESCE(city, 'Якутск') as city,
               COALESCE(card_only, 0) as card_only,
               COALESCE(automatic, 0) as automatic,
               COALESCE(is_closed, 0) as is_closed,
               COALESCE(closed_reason, '') as closed_reason,
               COALESCE(reopen_date, '') as reopen_date
        FROM stations ORDER BY name
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_station_fuel_marks(station_id, fuel_code):
    conn = get_conn()
    rows = conn.execute("""
        SELECT id, mark_type, status, queue_count, payment_method, bonus_card,
               pump_number, user_tg_id, username, created_at
        FROM marks
        WHERE station_id = ? AND fuel_code = ? AND fuel_code != '_station_'
        ORDER BY created_at DESC
        LIMIT 30
    """, (station_id, fuel_code)).fetchall()
    conn.close()
    
    result = []
    for r in rows:
        d = dict(r)
        # Explicit date fields for API consumers
        d['date'] = r['created_at']
        result.append(d)
    return result

def delete_mark(mark_id, user_tg_id):
    conn = get_conn()
    conn.execute(
        "DELETE FROM marks WHERE id = ? AND user_tg_id = ?",
        (mark_id, user_tg_id)
    )
    affected = conn.total_changes
    conn.commit()
    conn.close()
    return affected > 0

def get_station_exclusions(station_id):
    conn = get_conn()
    rows = conn.execute(
        "SELECT fuel_code FROM station_fuel_exclusions WHERE station_id = ?", (station_id,)
    ).fetchall()
    conn.close()
    return [r['fuel_code'] for r in rows]

def get_stations_full(period='24h'):
    conn = get_conn()
    stations = conn.execute("""
        SELECT s.id, s.name, s.brand, s.lat, s.lon, s.address, 
                COALESCE(s.city, 'Якутск') as city, 
                COALESCE(s.card_only, 0) as card_only, 
                COALESCE(s.automatic, 0) as automatic,
                COALESCE(s.has_priority_lane, 0) as has_priority_lane,
                COALESCE(s.priority_note, '') as priority_note,
                COALESCE(s.is_closed, 0) as is_closed,
                COALESCE(s.reopen_date, '') as reopen_date,
                COALESCE(s.closed_reason, '') as closed_reason,
                COALESCE(s.unloading_until, '') as unloading_until,
                COALESCE(s.unloading_note, '') as unloading_note,
                s.last_payment_at,
                s.last_fuel_code
        FROM stations s ORDER BY s.name
    """).fetchall()
    all_prices = {}
    price_rows = conn.execute("SELECT station_id, fuel_code, price, updated_at FROM fuel_prices").fetchall()
    for r in price_rows:
        sid = r['station_id']
        if sid not in all_prices:
            all_prices[sid] = {}
        all_prices[sid][r['fuel_code']] = {'price': r['price'], 'updated_at': r['updated_at']}

    excl_rows = conn.execute("SELECT station_id, fuel_code FROM station_fuel_exclusions").fetchall()
    exclusions_by_station = {}
    for r in excl_rows:
        exclusions_by_station.setdefault(r['station_id'], []).append(r['fuel_code'])

    comment_counts = {}
    cc_rows = conn.execute("SELECT station_id, COUNT(*) AS cnt FROM comments GROUP BY station_id").fetchall()
    for r in cc_rows:
        comment_counts[r['station_id']] = r['cnt']

    recent_comment_counts = {}
    last_comment_times = {}
    rcc_rows = conn.execute("""
        SELECT station_id, COUNT(*) AS cnt, MAX(created_at) AS last_at 
        FROM comments 
        WHERE created_at >= datetime('now', '-24 hours')
        GROUP BY station_id
    """).fetchall()
    for r in rcc_rows:
        recent_comment_counts[r['station_id']] = r['cnt']
        last_comment_times[r['station_id']] = r['last_at']

    recent_comments_by_station = {}
    c_rows = conn.execute("""
        SELECT station_id, comment, username, created_at 
        FROM comments 
        WHERE created_at >= datetime('now', '-24 hours') AND comment IS NOT NULL AND comment != ''
        ORDER BY created_at DESC
    """).fetchall()
    for r in c_rows:
        if len(recent_comments_by_station.get(r['station_id'], [])) < 3:
            recent_comments_by_station.setdefault(r['station_id'], []).append({
                'comment': r['comment'],
                'username': r['username'],
                'created_at': r['created_at']
            })

    photos_by_station = {}
    photo_rows = conn.execute("""
        SELECT station_id, photo_path, comment, username, created_at 
        FROM comments 
        WHERE has_photo=1 AND photo_path IS NOT NULL AND photo_path != ''
        ORDER BY created_at DESC
    """).fetchall()
    for r in photo_rows:
        photos_by_station.setdefault(r['station_id'], []).append({
            'photo_path': r['photo_path'],
            'comment': r['comment'],
            'username': r['username'],
            'created_at': r['created_at']
        })
    
    if period == '24h':
        time_filter = (datetime.now() - timedelta(hours=24)).strftime('%Y-%m-%d %H:%M:%S')
        marks_rows = conn.execute("""
            SELECT station_id, fuel_code, status, mark_type, limit_liters, queue_count,
                   payment_method, bonus_card, pump_number, user_tg_id,
                   username, created_at
            FROM marks 
            WHERE created_at >= ?
            ORDER BY created_at DESC
        """, (time_filter,)).fetchall()
    else:
        marks_rows = conn.execute("""
            SELECT station_id, fuel_code, status, mark_type, limit_liters, queue_count,
                   payment_method, bonus_card, pump_number, user_tg_id,
                   username, created_at
            FROM marks ORDER BY created_at DESC
        """).fetchall()

    marks_by_station = {}
    for r in marks_rows:
        marks_by_station.setdefault(r['station_id'], []).append(r)

    cutoff = (datetime.now() - timedelta(hours=24)).strftime('%Y-%m-%d %H:%M:%S')
    result = []
    for s in stations:
        sid = s['id']
        exclusions = exclusions_by_station.get(sid, [])
        station_marks = marks_by_station.get(sid, [])
        marks = {}
        fuel_count = {}
        station_queue = None
        cutoff_queue = (datetime.now() - timedelta(hours=6)).strftime('%Y-%m-%d %H:%M:%S')
        for r in station_marks:
            fc = r['fuel_code']
            if (fc == '_station_' or r['queue_count'] is not None) and r['status'] != 'no' and (r['queue_count'] is None or r['queue_count'] > 0 or r['status'] == 'queue'):
                if r['created_at'] >= cutoff_queue and (station_queue is None or r['created_at'] > station_queue['time']):
                    station_queue = {
                        'queue_count': r['queue_count'],
                        'time': r['created_at'],
                        'status': r['status'],
                        'mark_type': r['mark_type']
                    }
                if fc == '_station_':
                    continue

            if fc not in marks:
                marks[fc] = {'status': r['status'], 'time': r['created_at'],
                             'limit_liters': r['limit_liters'],
                             'mark_type': r['mark_type'], 'count': 0, 'confident': False,
                             'recent_count': 0, 'stale': False}
                fuel_count[fc] = {'yes': 0, 'no': 0, 'queue': 0, 'limit': 0, 'total': 0}
            fuel_count[fc]['total'] += 1
            fuel_count[fc][r['status']] = fuel_count[fc].get(r['status'], 0) + 1
            if r['created_at'] >= cutoff:
                marks[fc]['recent_count'] += 1
        for fc, cnt in fuel_count.items():
            if cnt['total'] >= 3:
                marks[fc]['confident'] = True
            marks[fc]['count'] = cnt['total']
            marks[fc]['stale'] = marks[fc]['recent_count'] == 0
            dominant = max(['yes', 'no', 'queue', 'limit'], key=lambda x: cnt.get(x, 0))
            marks[fc]['status'] = dominant
        st_photos = photos_by_station.get(sid, [])
        result.append({
            'id': sid, 'name': s['name'], 'brand': s['brand'],
            'city': s['city'],
            'lat': s['lat'], 'lon': s['lon'], 'address': s['address'],
            'card_only': bool(s['card_only']),
            'automatic': bool(s['automatic']),
            'has_priority_lane': bool(s['has_priority_lane']),
            'priority_note': s['priority_note'] or '',
            'is_closed': bool(s['is_closed']),
            'reopen_date': s['reopen_date'] or '',
            'closed_reason': s['closed_reason'] or '',
            'excluded_fuels': exclusions,
            'marks': marks,
            'prices': all_prices.get(sid, {}),
            'queue': station_queue,
            'comment_count': comment_counts.get(sid, 0),
            'recent_comment_count': recent_comment_counts.get(sid, 0),
            'last_comment_at': last_comment_times.get(sid),
            'photos': st_photos,
            'photo_count': len(st_photos),
            'last_payment_at': s['last_payment_at'],
            'last_fuel_code': s['last_fuel_code'],
            'unloading_until': s['unloading_until'] or '',
            'unloading_note': s['unloading_note'] or '',
            'latest_comments': recent_comments_by_station.get(sid, []),
        })
    conn.close()
    return result

def get_cities():
    conn = get_conn()
    rows = conn.execute("""
        SELECT COALESCE(city, 'Якутск') as city, COUNT(*) as count 
        FROM stations 
        GROUP BY COALESCE(city, 'Якутск') 
        ORDER BY count DESC
    """).fetchall()
    conn.close()
    return [{'city': r['city'], 'count': r['count']} for r in rows]

def set_station_unloading(station_id: int, minutes: int = 35, note: str = 'Идёт слив цистерны'):
    conn = get_conn()
    until_dt = (datetime.utcnow() + timedelta(minutes=minutes)).strftime('%Y-%m-%d %H:%M:%S')
    conn.execute("""
        UPDATE stations
        SET unloading_until = ?, unloading_note = ?
        WHERE id = ?
    """, (until_dt, note, station_id))
    conn.commit()
    conn.close()

def import_stations_from_json(json_path):
    with open(json_path, 'r', encoding='utf-8') as f:
        stations = json.load(f)
    conn = get_conn()
    for s in stations:
        existing = None
        if s.get('id'):
            existing = conn.execute("SELECT id, card_only, automatic FROM stations WHERE id = ?", (s['id'],)).fetchone()
        if not existing and s.get('brand') == 'СибОйл' and s.get('siboil_number') is not None:
            existing = conn.execute("SELECT id, card_only, automatic FROM stations WHERE brand = 'СибОйл' AND siboil_number = ?", (s['siboil_number'],)).fetchone()
        if not existing and s.get('sngs_id') is not None:
            existing = conn.execute("SELECT id, card_only, automatic FROM stations WHERE sngs_id = ?", (s['sngs_id'],)).fetchone()
        if not existing:
            existing = conn.execute(
                "SELECT id, card_only, automatic FROM stations WHERE name=? AND lat=? AND lon=?",
                (s['name'], s['lat'], s['lon'])
            ).fetchone()
        if not existing and s.get('address'):
            existing = conn.execute(
                "SELECT id, card_only, automatic FROM stations WHERE name=? AND address=?",
                (s['name'], s.get('address', ''))
            ).fetchone()

        if existing:
            sid = existing['id']
            updates = []
            params = []
            if s.get('card_only') and not existing['card_only']:
                updates.append("card_only = 1")
            if s.get('siboil_number') is not None:
                updates.append("siboil_number = ?")
                params.append(s['siboil_number'])
            if s.get('automatic') and not existing['automatic']:
                updates.append("automatic = 1")
            if updates:
                conn.execute(f"UPDATE stations SET {', '.join(updates)} WHERE id = ?", (*params, sid))
        else:
            cursor = conn.execute(
                "INSERT INTO stations(name, brand, lat, lon, address, city, siboil_number, automatic) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (s['name'], s.get('brand', ''), s['lat'], s['lon'], s.get('address', ''), s.get('city', 'Якутск'), s.get('siboil_number'), 1 if s.get('automatic') else 0)
            )
            sid = cursor.lastrowid
            if s.get('card_only'):
                conn.execute("UPDATE stations SET card_only = 1 WHERE id = ?", (sid,))
        if sid and s.get('excluded_fuels'):
            for fc in s['excluded_fuels']:
                conn.execute(
                    "INSERT OR IGNORE INTO station_fuel_exclusions(station_id, fuel_code) VALUES (?, ?)",
                    (sid, fc)
                )
    conn.commit()
    conn.close()
    return len(stations)

def add_mark(station_id, fuel_code, status, user_tg_id, username=''):
    conn = get_conn()
    conn.execute(
        "INSERT INTO marks(station_id, fuel_code, status, user_tg_id, username) VALUES (?, ?, ?, ?, ?)",
        (station_id, fuel_code, status, user_tg_id, username)
    )
    conn.commit()
    conn.close()

def get_station_name(station_id):
    conn = get_conn()
    row = conn.execute("SELECT name FROM stations WHERE id = ?", (station_id,)).fetchone()
    conn.close()
    return row['name'] if row else 'Неизвестная АЗС'

def normalize_text_for_dedup(text: str) -> str:
    if not text:
        return ""
    t = text.lower().strip()
    # Strip emojis and unicode symbols
    t = re.sub(r'[\U00010000-\U0010ffff]', '', t)
    # Strip bullet points, leading dashes, quotes, markdown
    t = re.sub(r'^[—–\-\*\•\>\s"«\']+', '', t)
    # Replace multiple whitespaces and newlines
    t = re.sub(r'\s+', ' ', t)
    # Remove punctuation
    t = re.sub(r'[^\w\s]', '', t)
    return t.strip()

def is_duplicate_text(t1: str, t2: str, min_match_len: int = 25) -> bool:
    n1 = normalize_text_for_dedup(t1)
    n2 = normalize_text_for_dedup(t2)
    if not n1 or not n2:
        return False
    if n1 == n2:
        return True
    
    # 1. Проверка совпадения по началу (startswith или одинаковый префикс)
    min_len = min(len(n1), len(n2))
    if min_len >= min_match_len:
        if n1[:min_match_len] == n2[:min_match_len]:
            return True
        if n1.startswith(n2) or n2.startswith(n1):
            return True
            
    # 2. Проверка вложенного цитирования / репоста
    if len(n1) >= 30 and n1[:30] in n2:
        return True
    if len(n2) >= 30 and n2[:30] in n1:
        return True

    return False

def add_mark_v2(station_id, fuel_code, status, user_tg_id, username='',
                mark_type='full', queue_count=None, payment_method=None,
                bonus_card=None, pump_number=None, limit_liters=None, deduplicate=True):
    conn = get_conn()
    if deduplicate:
        # Проверяем недавнюю отметку по этой же АЗС и марке топлива за последние 20 минут
        recent_mark = conn.execute("""
            SELECT id, status, mark_type, queue_count, limit_liters, created_at
            FROM marks
            WHERE station_id = ? AND fuel_code = ? AND created_at >= datetime('now', '-20 minutes')
            ORDER BY id DESC LIMIT 1
        """, (station_id, fuel_code)).fetchone()

        if recent_mark:
            # Обновляем существующую отметку вместо создания дублирующей строки
            conn.execute("""
                UPDATE marks
                SET status = ?, queue_count = COALESCE(?, queue_count),
                    limit_liters = COALESCE(?, limit_liters),
                    username = ?, mark_type = ?, created_at = datetime('now')
                WHERE id = ?
            """, (status, queue_count, limit_liters, username, mark_type, recent_mark['id']))
            conn.commit()
            conn.close()
            return recent_mark['id']

    cursor = conn.execute("""
        INSERT INTO marks(station_id, fuel_code, status, mark_type,
                          queue_count, payment_method, bonus_card, pump_number,
                          user_tg_id, username, limit_liters)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (station_id, fuel_code, status, mark_type,
          queue_count, payment_method, bonus_card, pump_number,
          user_tg_id, username, limit_liters))
    new_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return new_id

def get_latest_marks(station_id, limit=1):
    conn = get_conn()
    rows = conn.execute("""
        SELECT fuel_code, status, created_at FROM marks
        WHERE station_id = ?
        ORDER BY created_at DESC
    """, (station_id,)).fetchall()
    conn.close()
    result = {}
    for r in rows:
        fc = r['fuel_code']
        if fc not in result:
            result[fc] = {'status': r['status'], 'time': r['created_at']}
    return result

def get_nearby_stations(lat, lon, radius_km=5):
    conn = get_conn()
    import math
    lat_deg = radius_km / 111.0
    lon_deg = radius_km / (111.0 * math.cos(math.radians(lat)))
    rows = conn.execute("""
        SELECT id, name, brand, lat, lon, address FROM stations
        WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?
    """, (lat - lat_deg, lat + lat_deg, lon - lon_deg, lon + lon_deg)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def subscribe(user_tg_id, station_id, fuel_code):
    conn = get_conn()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO subscriptions(user_tg_id, station_id, fuel_code) VALUES (?, ?, ?)",
            (user_tg_id, station_id, fuel_code)
        )
        conn.commit()
    except Exception:
        pass
    conn.close()

def unsubscribe(user_tg_id, station_id, fuel_code):
    conn = get_conn()
    conn.execute(
        "DELETE FROM subscriptions WHERE user_tg_id=? AND station_id=? AND fuel_code=?",
        (user_tg_id, station_id, fuel_code)
    )
    conn.commit()
    conn.close()

def get_user_subscriptions(user_tg_id):
    conn = get_conn()
    rows = conn.execute("""
        SELECT s.station_id, COALESCE(st.name, 'Все АЗС города') as name, s.fuel_code, COALESCE(f.label, s.fuel_code) as label
        FROM subscriptions s
        LEFT JOIN stations st ON st.id = s.station_id
        LEFT JOIN fuel_marks f ON f.code = s.fuel_code
        WHERE s.user_tg_id = ?
    """, (user_tg_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def check_subscriptions(station_id, fuel_code):
    conn = get_conn()
    rows = conn.execute(
        "SELECT DISTINCT user_tg_id FROM subscriptions WHERE (station_id=? OR station_id=0) AND fuel_code=?",
        (station_id, fuel_code)
    ).fetchall()
    conn.close()
    return [r['user_tg_id'] for r in rows]

def get_all_users():
    conn = get_conn()
    rows = conn.execute(
        "SELECT DISTINCT user_tg_id FROM (SELECT user_tg_id FROM marks WHERE user_tg_id > 0 UNION SELECT user_tg_id FROM comments WHERE user_tg_id > 0)"
    ).fetchall()
    conn.close()
    return [r['user_tg_id'] for r in rows]

def add_comment(station_id, user_tg_id, username, comment, has_photo=0, photo_path=None, deduplicate=True):
    conn = get_conn()
    if deduplicate and comment:
        # Проверяем недавние отзывы по этой же АЗС за последние 45 минут
        recent_comments = conn.execute("""
            SELECT id, comment, has_photo, photo_path, created_at 
            FROM comments 
            WHERE station_id = ? AND created_at >= datetime('now', '-45 minutes')
            ORDER BY id DESC
        """, (station_id,)).fetchall()
        
        for rc in recent_comments:
            old_comment = rc['comment'] or ''
            if is_duplicate_text(comment, old_comment):
                # Если новое сообщение содержит уточнение/дополнение или фото — обновляем существующий отзыв
                if len(comment.strip()) >= len(old_comment.strip()) or (photo_path and not rc['photo_path']):
                    conn.execute("""
                        UPDATE comments 
                        SET comment = ?, has_photo = ?, photo_path = COALESCE(?, photo_path), created_at = datetime('now')
                        WHERE id = ?
                    """, (comment, 1 if (has_photo or photo_path or rc['has_photo']) else 0, photo_path, rc['id']))
                    conn.commit()
                conn.close()
                return rc['id']

    cursor = conn.execute("""
        INSERT INTO comments(station_id, user_tg_id, username, comment, has_photo, photo_path)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (station_id, user_tg_id, username, comment, 1 if has_photo or photo_path else 0, photo_path))
    new_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return new_id

def add_reaction(comment_id, user_tg_id, reaction):
    conn = get_conn()
    if reaction == 0:
        conn.execute(
            "DELETE FROM comment_reactions WHERE comment_id=? AND user_tg_id=?",
            (comment_id, user_tg_id))
    else:
        conn.execute("""
            INSERT INTO comment_reactions(comment_id, user_tg_id, reaction)
            VALUES (?, ?, ?)
            ON CONFLICT(comment_id, user_tg_id) DO UPDATE SET reaction=excluded.reaction
        """, (comment_id, user_tg_id, reaction))
    conn.commit()
    conn.close()

def get_station_comments(station_id, user_tg_id=None, limit=20):
    conn = get_conn()
    my_sql = ', (SELECT reaction FROM comment_reactions WHERE comment_id=c.id AND user_tg_id=?) AS my_reaction' if user_tg_id else ''
    params = (user_tg_id, station_id, limit) if user_tg_id else (station_id, limit)
    rows = conn.execute(f"""
        SELECT
            c.id, c.comment, c.username, c.created_at, c.has_photo, c.photo_path,
            COALESCE(l.cnt, 0) AS likes,
            COALESCE(d.cnt, 0) AS dislikes
            {my_sql}
        FROM comments c
        LEFT JOIN (SELECT comment_id, COUNT(*) AS cnt FROM comment_reactions WHERE reaction=1 GROUP BY comment_id) l ON l.comment_id=c.id
        LEFT JOIN (SELECT comment_id, COUNT(*) AS cnt FROM comment_reactions WHERE reaction=-1 GROUP BY comment_id) d ON d.comment_id=c.id
        WHERE c.station_id = ? AND c.created_at >= datetime('now', '-24 hours')
        ORDER BY c.created_at DESC LIMIT ?
    """, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def set_price(station_id, fuel_code, price):
    conn = get_conn()
    conn.execute("""
        INSERT INTO fuel_prices(station_id, fuel_code, price, updated_at)
        VALUES (?, ?, ?, datetime('now'))
        ON CONFLICT(station_id, fuel_code) DO UPDATE SET
            price=excluded.price, updated_at=excluded.updated_at
    """, (station_id, fuel_code, price))
    conn.commit()
    conn.close()

def get_prices(station_id):
    conn = get_conn()
    rows = conn.execute(
        "SELECT fuel_code, price, updated_at FROM fuel_prices WHERE station_id = ?",
        (station_id,)
    ).fetchall()
    conn.close()
    return {r['fuel_code']: {'price': r['price'], 'updated_at': r['updated_at']} for r in rows}

def get_all_prices():
    conn = get_conn()
    rows = conn.execute(
        "SELECT station_id, fuel_code, price, updated_at FROM fuel_prices"
    ).fetchall()
    conn.close()
    result = {}
    for r in rows:
        sid = r['station_id']
        if sid not in result:
            result[sid] = {}
        result[sid][r['fuel_code']] = {'price': r['price'], 'updated_at': r['updated_at']}
    return result

def get_station_by_siboil_number(number):
    conn = get_conn()
    row = conn.execute(
        "SELECT id FROM stations WHERE siboil_number = ?", (number,)
    ).fetchone()
    conn.close()
    return row['id'] if row else None

def get_station_suggestions():
    conn = get_conn()
    rows = conn.execute("SELECT id, name, brand, lat, lon, address, city, username, created_at FROM station_suggestions ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def add_suggestion(name, lat, lon, brand='', address='', city='Якутск', comment='', user_tg_id=None, username=''):
    conn = get_conn()
    conn.execute(
        "INSERT INTO station_suggestions(name, brand, lat, lon, address, city, comment, user_tg_id, username) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (name, brand, lat, lon, address, city, comment, user_tg_id, username)
    )
    conn.commit()
    conn.close()

STATUS_EMOJI = {'yes': '🟢', 'no': '🔴', 'queue': '🟡', 'limit': '🟠'}
STATUS_LABEL = {'yes': 'Есть', 'no': 'Нет', 'queue': 'Очередь', 'limit': 'Лимит'}
FUEL_LABELS = {'92': 'АИ-92', '95': 'АИ-95', '98': 'АИ-98', '100': 'АИ-100', 'dt': 'ДТ', 'gas': 'Газ', 'ts1': 'ТС-1', '92ef': '92 Эф.'}

def get_recent_activity(limit=20):
    conn = get_conn()
    items = []
    
    # 1. Свежие отметки топлива и очередей
    rows = conn.execute("""
        SELECT m.id, m.station_id, s.name AS station_name, m.fuel_code,
               m.status, m.mark_type, m.queue_count, m.username, m.created_at
        FROM marks m
        JOIN stations s ON s.id = m.station_id
        ORDER BY m.created_at DESC
        LIMIT ?
    """, (limit,)).fetchall()
    for r in rows:
        item = dict(r)
        item['type'] = 'mark'
        fuel_label = FUEL_LABELS.get(r['fuel_code'], r['fuel_code']) if r['fuel_code'] != '_station_' else ''
        emoji = STATUS_EMOJI.get(r['status'], '⚪')
        st_label = STATUS_LABEL.get(r['status'], r['status'])
        
        if r['queue_count'] is not None and r['queue_count'] > 0:
            text = f"Очередь ~{r['queue_count']} машин"
            if fuel_label: text += f" ({fuel_label}: {st_label})"
        elif r['queue_count'] == 0:
            text = f"Без очереди ({fuel_label or 'Топливо'}: {st_label})"
        else:
            text = f"{fuel_label}: {emoji} {st_label}" if fuel_label else f"Статус: {emoji} {st_label}"
            
        item['text'] = text
        item['source'] = 'WhatsApp / Чат' if 'wa:' in (r['username'] or '') else ('Telegram' if 'tg:' in (r['username'] or '') else 'Водитель')
        items.append(item)

    # 2. Комментарии и фотографии
    rows = conn.execute("""
        SELECT c.id, c.station_id, s.name AS station_name, c.comment, c.has_photo, c.photo_path,
               c.username, c.created_at
        FROM comments c
        JOIN stations s ON s.id = c.station_id
        WHERE c.created_at >= datetime('now', '-5 days')
        ORDER BY c.created_at DESC
        LIMIT ?
    """, (limit,)).fetchall()
    for r in rows:
        item = dict(r)
        item['type'] = 'comment'
        item['text'] = ('📷 Фото: ' + r['comment']) if r['has_photo'] else r['comment']
        item['source'] = 'WhatsApp / Чат' if 'wa:' in (r['username'] or '') else ('Telegram' if 'tg:' in (r['username'] or '') else 'Водитель')
        items.append(item)

    items.sort(key=lambda x: x['created_at'], reverse=True)
    conn.close()
    return items[:limit]

def get_recent_photos(limit=20):
    conn = get_conn()
    rows = conn.execute("""
        SELECT c.id, c.station_id, s.name AS station_name, c.comment, c.photo_path,
               c.username, c.created_at
        FROM comments c
        JOIN stations s ON s.id = c.station_id
        WHERE c.has_photo = 1 AND c.photo_path IS NOT NULL AND c.photo_path != ''
          AND c.created_at >= datetime('now', '-5 days')
        ORDER BY c.created_at DESC
        LIMIT ?
    """, (limit,)).fetchall()
    items = []
    for r in rows:
        item = dict(r)
        item['source'] = 'WhatsApp / Чат' if 'wa:' in (r['username'] or '') else ('Telegram' if 'tg:' in (r['username'] or '') else 'Водитель')
        items.append(item)
    conn.close()
    return items

def record_visit(ip, user_agent=''):
    conn = get_conn()
    conn.execute("INSERT INTO page_views(ip, user_agent) VALUES (?, ?)", (ip, user_agent))
    conn.commit()
    conn.close()

def get_visitor_stats():
    conn = get_conn()
    total = conn.execute("SELECT COUNT(*) AS c FROM page_views").fetchone()['c']
    unique_total = conn.execute("SELECT COUNT(DISTINCT ip) AS c FROM page_views").fetchone()['c']
    today = conn.execute("SELECT COUNT(*) AS c FROM page_views WHERE date(visited_at) = date('now')").fetchone()['c']
    online = conn.execute("SELECT COUNT(DISTINCT ip) AS c FROM page_views WHERE visited_at > datetime('now', '-5 minutes')").fetchone()['c']
    conn.close()
    return {'total_views': total, 'unique_visitors': unique_total, 'today_views': today, 'online_now': online}

def add_feedback(message, feedback_type='other', station_id=None, user_tg_id=None, username='', contact=''):
    conn = get_conn()
    cursor = conn.execute("""
        INSERT INTO feedback(message, feedback_type, station_id, user_tg_id, username, contact)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (message, feedback_type, station_id, user_tg_id, username, contact))
    fid = cursor.lastrowid
    conn.commit()
    conn.close()
    return fid

def get_feedback_list(limit=50):
    conn = get_conn()
    rows = conn.execute("""
        SELECT f.id, f.user_tg_id, f.username, f.feedback_type, f.station_id,
               f.message, f.contact, f.status, f.created_at, s.name AS station_name, s.brand
        FROM feedback f
        LEFT JOIN stations s ON s.id = f.station_id
        ORDER BY f.created_at DESC
        LIMIT ?
    """, (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_partner_by_token(token):
    if not token:
        return None
    conn = get_conn()
    row = conn.execute(
        "SELECT token, network_id, brand_name, filter_type, filter_value FROM partner_tokens WHERE token = ?",
        (token.strip(),)
    ).fetchone()
    conn.close()
    return dict(row) if row else None

def get_partner_stations(partner_info):
    conn = get_conn()
    f_type = partner_info['filter_type']
    f_val = partner_info['filter_value']

    if f_type == 'name_like':
        rows = conn.execute("""
            SELECT id, name, brand, address, city, is_closed
            FROM stations
            WHERE name LIKE ?
            ORDER BY city = 'Якутск' DESC, name ASC
        """, (f_val,)).fetchall()
    else:
        rows = conn.execute("""
            SELECT id, name, brand, address, city, is_closed
            FROM stations
            WHERE brand = ?
            ORDER BY city = 'Якутск' DESC, name ASC
        """, (f_val,)).fetchall()

    stations = [dict(r) for r in rows]

    # Get exclusions for these stations
    station_ids = [s['id'] for s in stations]
    exclusions_by_station = {}
    if station_ids:
        placeholders = ','.join('?' for _ in station_ids)
        excl_rows = conn.execute(f"""
            SELECT station_id, fuel_code
            FROM station_fuel_exclusions
            WHERE station_id IN ({placeholders})
        """, station_ids).fetchall()
        for er in excl_rows:
            exclusions_by_station.setdefault(er['station_id'], set()).add(er['fuel_code'])

    # Get latest marks for these stations
    marks_by_station = {}
    if station_ids:
        placeholders = ','.join('?' for _ in station_ids)
        m_rows = conn.execute(f"""
            SELECT station_id, fuel_code, status, limit_liters, mark_type, created_at
            FROM marks
            WHERE station_id IN ({placeholders})
            ORDER BY created_at DESC
        """, station_ids).fetchall()
        for mr in m_rows:
            sid = mr['station_id']
            fc = mr['fuel_code']
            if sid not in marks_by_station:
                marks_by_station[sid] = {}
            if fc not in marks_by_station[sid]:
                marks_by_station[sid][fc] = {
                    'status': mr['status'],
                    'limit_liters': mr['limit_liters'],
                    'mark_type': mr['mark_type'],
                    'created_at': mr['created_at']
                }

    # All fuel codes
    all_fuels = [('92', 'АИ-92'), ('95', 'АИ-95'), ('98', 'АИ-98'), ('100', 'АИ-100'), ('dt', 'ДТ'), ('gas', 'Газ')]

    for s in stations:
        sid = s['id']
        excluded = exclusions_by_station.get(sid, set())
        station_fuels = []
        for code, label in all_fuels:
            if code in excluded:
                continue
            last_m = marks_by_station.get(sid, {}).get(code, {})
            station_fuels.append({
                'code': code,
                'label': label,
                'status': last_m.get('status', 'none'),
                'limit_liters': last_m.get('limit_liters'),
                'mark_type': last_m.get('mark_type', 'full'),
                'updated_at': last_m.get('created_at')
            })
        s['fuels'] = station_fuels

    conn.close()
    return stations


def generate_analytics_dump():
    import json, os, datetime
    try:
        conn = get_conn()
        dump = {}

        # 1. Page views (Fuel Map)
        dump['page_views_total'] = conn.execute("SELECT COUNT(*) FROM page_views").fetchone()[0]
        dump['page_views_unique_ip'] = conn.execute("SELECT COUNT(DISTINCT ip) FROM page_views").fetchone()[0]
        dump['page_views_today'] = conn.execute("SELECT COUNT(*) FROM page_views WHERE date(visited_at) = date('now')").fetchone()[0]
        dump['page_views_unique_ip_today'] = conn.execute("SELECT COUNT(DISTINCT ip) FROM page_views WHERE date(visited_at) = date('now')").fetchone()[0]
        dump['page_views_7d'] = conn.execute("SELECT COUNT(*) FROM page_views WHERE visited_at >= datetime('now', '-7 days')").fetchone()[0]
        dump['page_views_unique_ip_7d'] = conn.execute("SELECT COUNT(DISTINCT ip) FROM page_views WHERE visited_at >= datetime('now', '-7 days')").fetchone()[0]
        dump['page_views_30d'] = conn.execute("SELECT COUNT(*) FROM page_views WHERE visited_at >= datetime('now', '-30 days')").fetchone()[0]
        dump['page_views_unique_ip_30d'] = conn.execute("SELECT COUNT(DISTINCT ip) FROM page_views WHERE visited_at >= datetime('now', '-30 days')").fetchone()[0]
        
        # Daily page views for last 14 days
        daily_pv = conn.execute("""
            SELECT date(visited_at) as day, COUNT(*) as views, COUNT(DISTINCT ip) as unique_ips
            FROM page_views
            GROUP BY date(visited_at)
            ORDER BY day DESC
            LIMIT 14
        """).fetchall()
        dump['page_views_daily'] = [dict(r) for r in daily_pv]

        # Top User Agents
        dump['top_user_agents'] = [dict(r) for r in conn.execute("""
            SELECT user_agent, COUNT(*) as count, COUNT(DISTINCT ip) as unique_ips
            FROM page_views
            GROUP BY user_agent
            ORDER BY count DESC
            LIMIT 10
        """).fetchall()]

        # 2. Telegram Bot & DB Users
        # Unique TG IDs across marks, comments, feedback, subscriptions, suggestions, reactions
        all_tg_users = conn.execute("""
            SELECT DISTINCT user_tg_id FROM (
                SELECT user_tg_id FROM marks WHERE user_tg_id > 0 AND user_tg_id != 999999003
                UNION
                SELECT user_tg_id FROM comments WHERE user_tg_id > 0 AND user_tg_id != 999999003
                UNION
                SELECT user_tg_id FROM subscriptions WHERE user_tg_id > 0
                UNION
                SELECT user_tg_id FROM feedback WHERE user_tg_id > 0
                UNION
                SELECT user_tg_id FROM station_suggestions WHERE user_tg_id > 0
                UNION
                SELECT user_tg_id FROM comment_reactions WHERE user_tg_id > 0
            )
        """).fetchall()
        dump['tg_users_total_unique'] = len(all_tg_users)

        # Unique TG IDs by activity table
        dump['tg_users_in_marks'] = conn.execute("SELECT COUNT(DISTINCT user_tg_id) FROM marks WHERE user_tg_id > 0 AND user_tg_id != 999999003").fetchone()[0]
        dump['tg_users_in_comments'] = conn.execute("SELECT COUNT(DISTINCT user_tg_id) FROM comments WHERE user_tg_id > 0 AND user_tg_id != 999999003").fetchone()[0]
        dump['tg_users_in_subscriptions'] = conn.execute("SELECT COUNT(DISTINCT user_tg_id) FROM subscriptions WHERE user_tg_id > 0").fetchone()[0]
        dump['tg_users_in_feedback'] = conn.execute("SELECT COUNT(DISTINCT user_tg_id) FROM feedback WHERE user_tg_id > 0").fetchone()[0]
        dump['tg_users_in_suggestions'] = conn.execute("SELECT COUNT(DISTINCT user_tg_id) FROM station_suggestions WHERE user_tg_id > 0").fetchone()[0]
        dump['tg_users_in_reactions'] = conn.execute("SELECT COUNT(DISTINCT user_tg_id) FROM comment_reactions WHERE user_tg_id > 0").fetchone()[0]

        # Active TG users by time range (last 24h, 7d, 30d)
        for days, label in [(1, '24h'), (7, '7d'), (30, '30d')]:
            query = f"""
                SELECT COUNT(DISTINCT user_tg_id) FROM (
                    SELECT user_tg_id FROM marks WHERE user_tg_id > 0 AND user_tg_id != 999999003 AND created_at >= datetime('now', '-{days} days')
                    UNION
                    SELECT user_tg_id FROM comments WHERE user_tg_id > 0 AND user_tg_id != 999999003 AND created_at >= datetime('now', '-{days} days')
                    UNION
                    SELECT user_tg_id FROM feedback WHERE user_tg_id > 0 AND created_at >= datetime('now', '-{days} days')
                    UNION
                    SELECT user_tg_id FROM comment_reactions WHERE user_tg_id > 0 AND created_at >= datetime('now', '-{days} days')
                )
            """
            dump[f'tg_active_users_{label}'] = conn.execute(query).fetchone()[0]

        # 3. Subscriptions Breakdown
        dump['subscriptions_total_rows'] = conn.execute("SELECT COUNT(*) FROM subscriptions").fetchone()[0]
        dump['subscriptions_unique_users'] = conn.execute("SELECT COUNT(DISTINCT user_tg_id) FROM subscriptions").fetchone()[0]
        
        subs_by_fuel = conn.execute("""
            SELECT fuel_code, COUNT(*) as cnt, COUNT(DISTINCT user_tg_id) as users_cnt
            FROM subscriptions
            GROUP BY fuel_code
            ORDER BY cnt DESC
        """).fetchall()
        dump['subscriptions_by_fuel'] = [dict(r) for r in subs_by_fuel]

        subs_city_vs_station = conn.execute("""
            SELECT CASE WHEN station_id = 0 THEN 'all_city' ELSE 'specific_station' END as sub_type,
                   COUNT(*) as cnt, COUNT(DISTINCT user_tg_id) as users_cnt
            FROM subscriptions
            GROUP BY sub_type
        """).fetchall()
        dump['subscriptions_by_type'] = [dict(r) for r in subs_city_vs_station]

        # 4. WhatsApp Activity
        wa_marks_cnt = conn.execute("SELECT COUNT(*) FROM marks WHERE username LIKE 'wa:%'").fetchone()[0]
        wa_marks_unique_users = conn.execute("SELECT COUNT(DISTINCT username) FROM marks WHERE username LIKE 'wa:%'").fetchone()[0]
        wa_comments_cnt = conn.execute("SELECT COUNT(*) FROM comments WHERE username LIKE 'wa:%'").fetchone()[0]
        wa_comments_unique_users = conn.execute("SELECT COUNT(DISTINCT username) FROM comments WHERE username LIKE 'wa:%'").fetchone()[0]
        
        wa_all_users = conn.execute("""
            SELECT DISTINCT username FROM (
                SELECT username FROM marks WHERE username LIKE 'wa:%'
                UNION
                SELECT username FROM comments WHERE username LIKE 'wa:%'
            )
        """).fetchall()
        dump['whatsapp_total_unique_senders'] = len(wa_all_users)
        dump['whatsapp_marks_total'] = wa_marks_cnt
        dump['whatsapp_marks_unique_users'] = wa_marks_unique_users
        dump['whatsapp_comments_total'] = wa_comments_cnt
        dump['whatsapp_comments_unique_users'] = wa_comments_unique_users

        # 5. Web / Guest Activity
        guest_marks = conn.execute("SELECT COUNT(*) FROM marks WHERE username LIKE 'guest:%' OR user_tg_id = 0").fetchone()[0]
        guest_comments = conn.execute("SELECT COUNT(*) FROM comments WHERE username LIKE 'guest:%' OR user_tg_id = 0").fetchone()[0]
        dump['web_guest_marks_total'] = guest_marks
        dump['web_guest_comments_total'] = guest_comments

        # 6. Overall Content Totals & Timeline
        dump['stations_total'] = conn.execute("SELECT COUNT(*) FROM stations").fetchone()[0]
        dump['stations_active'] = conn.execute("SELECT COUNT(*) FROM stations WHERE is_closed = 0").fetchone()[0]
        dump['stations_by_city'] = [dict(r) for r in conn.execute("SELECT COALESCE(city, 'Якутск') as city, COUNT(*) as cnt FROM stations GROUP BY city ORDER BY cnt DESC").fetchall()]
        dump['stations_by_brand'] = [dict(r) for r in conn.execute("SELECT brand, COUNT(*) as cnt FROM stations GROUP BY brand ORDER BY cnt DESC").fetchall()]

        dump['marks_total'] = conn.execute("SELECT COUNT(*) FROM marks").fetchone()[0]
        dump['marks_7d'] = conn.execute("SELECT COUNT(*) FROM marks WHERE created_at >= datetime('now', '-7 days')").fetchone()[0]
        dump['marks_30d'] = conn.execute("SELECT COUNT(*) FROM marks WHERE created_at >= datetime('now', '-30 days')").fetchone()[0]
        
        dump['comments_total'] = conn.execute("SELECT COUNT(*) FROM comments").fetchone()[0]
        dump['comments_with_photo'] = conn.execute("SELECT COUNT(*) FROM comments WHERE has_photo = 1").fetchone()[0]
        dump['comments_7d'] = conn.execute("SELECT COUNT(*) FROM comments WHERE created_at >= datetime('now', '-7 days')").fetchone()[0]

        dump['feedback_total'] = conn.execute("SELECT COUNT(*) FROM feedback").fetchone()[0]
        dump['suggestions_total'] = conn.execute("SELECT COUNT(*) FROM station_suggestions").fetchone()[0]
        dump['prices_total'] = conn.execute("SELECT COUNT(*) FROM fuel_prices").fetchone()[0]

        # First & Last Timestamps
        dump['first_mark_date'] = conn.execute("SELECT MIN(created_at) FROM marks").fetchone()[0]
        dump['last_mark_date'] = conn.execute("SELECT MAX(created_at) FROM marks").fetchone()[0]
        dump['first_comment_date'] = conn.execute("SELECT MIN(created_at) FROM comments").fetchone()[0]
        dump['last_comment_date'] = conn.execute("SELECT MAX(created_at) FROM comments").fetchone()[0]
        dump['first_visit_date'] = conn.execute("SELECT MIN(visited_at) FROM page_views").fetchone()[0]
        dump['last_visit_date'] = conn.execute("SELECT MAX(visited_at) FROM page_views").fetchone()[0]

        dump['generated_at'] = datetime.datetime.now().isoformat()
        conn.close()

        out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'stats_dump.json')
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(dump, f, ensure_ascii=False, indent=2)
        return dump
    except Exception as e:
        import traceback
        err_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'stats_error.txt')
        with open(err_path, 'w', encoding='utf-8') as f:
            f.write(f"Error: {e}\n{traceback.format_exc()}")
        return None

# Auto-run once if stats_dump.json doesn't exist or is older than 1 minute
try:
    _dpath = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'stats_dump.json')
    import time
    if not os.path.exists(_dpath) or (time.time() - os.path.getmtime(_dpath) > 30):
        generate_analytics_dump()
except Exception:
    pass

# --- Admin Panel CRUD Operations ---

def get_admin_marks(station_id=None, fuel_code=None, status=None, mark_type=None, search=None, limit=50, offset=0):
    conn = get_conn()
    select_fields = """
        SELECT m.id, m.station_id, m.fuel_code, m.status, m.mark_type, m.limit_liters,
               m.queue_count, m.user_tg_id, m.username, m.created_at,
               s.name AS station_name, s.brand AS station_brand, s.address AS station_address, s.city AS station_city,
               (
                   SELECT c.comment 
                   FROM comments c 
                   WHERE c.station_id = m.station_id 
                     AND (c.username = m.username OR (c.user_tg_id = m.user_tg_id AND c.user_tg_id != 0))
                     AND c.created_at <= datetime(m.created_at, '+5 seconds')
                     AND c.created_at >= datetime(m.created_at, '-120 seconds')
                   ORDER BY c.created_at DESC, c.id DESC LIMIT 1
               ) AS comment_text,
               (
                   SELECT c.photo_path 
                   FROM comments c 
                   WHERE c.station_id = m.station_id 
                     AND (c.username = m.username OR (c.user_tg_id = m.user_tg_id AND c.user_tg_id != 0))
                     AND c.created_at <= datetime(m.created_at, '+5 seconds')
                     AND c.created_at >= datetime(m.created_at, '-120 seconds')
                     AND c.photo_path IS NOT NULL AND c.photo_path != ''
                   ORDER BY c.created_at DESC, c.id DESC LIMIT 1
               ) AS photo_path
        FROM marks m
        LEFT JOIN stations s ON s.id = m.station_id
    """
    where_sql = " WHERE 1=1"
    params = []
    if station_id:
        where_sql += " AND m.station_id = ?"
        params.append(station_id)
    if fuel_code:
        where_sql += " AND m.fuel_code = ?"
        params.append(fuel_code)
    if status:
        where_sql += " AND m.status = ?"
        params.append(status)
    if mark_type:
        if mark_type == 'whatsapp':
            where_sql += " AND (m.mark_type = 'whatsapp' OR m.username LIKE 'wa:%')"
        elif mark_type == 'telegram':
            where_sql += " AND (m.mark_type = 'telegram' OR m.username LIKE 'tg:%')"
        elif mark_type == 'bot':
            where_sql += " AND m.mark_type = 'full' AND m.username NOT LIKE 'wa:%' AND m.username NOT LIKE 'tg:%' AND m.username NOT LIKE 'guest:%'"
        elif mark_type == 'guest':
            where_sql += " AND (m.username LIKE 'guest:%' OR m.mark_type = 'guest')"
        elif mark_type == 'sberazs' or mark_type == 'parser':
            where_sql += " AND (m.mark_type = 'sberazs' OR m.mark_type = 'parser' OR m.username LIKE '%sberazs%')"
        else:
            where_sql += " AND m.mark_type = ?"
            params.append(mark_type)
    if search:
        s_clean = search.strip()
        search_term = f"%{s_clean}%"
        if s_clean.isdigit():
            where_sql += """ AND (
                m.id = ? OR s.name LIKE ? OR s.address LIKE ? OR m.username LIKE ? 
                OR EXISTS (
                    SELECT 1 FROM comments c 
                    WHERE c.station_id = m.station_id 
                      AND (c.username = m.username OR c.user_tg_id = m.user_tg_id) 
                      AND c.comment LIKE ? 
                      AND c.created_at <= datetime(m.created_at, '+5 seconds')
                      AND c.created_at >= datetime(m.created_at, '-120 seconds')
                )
            )"""
            params.extend([int(s_clean), search_term, search_term, search_term, search_term])
        else:
            where_sql += """ AND (
                s.name LIKE ? OR s.address LIKE ? OR m.username LIKE ? 
                OR EXISTS (
                    SELECT 1 FROM comments c 
                    WHERE c.station_id = m.station_id 
                      AND (c.username = m.username OR c.user_tg_id = m.user_tg_id) 
                      AND c.comment LIKE ? 
                      AND c.created_at <= datetime(m.created_at, '+5 seconds')
                      AND c.created_at >= datetime(m.created_at, '-120 seconds')
                )
            )"""
            params.extend([search_term, search_term, search_term, search_term])

    # Count total
    count_query = f"SELECT COUNT(*) FROM marks m LEFT JOIN stations s ON s.id = m.station_id {where_sql}"
    total_count = conn.execute(count_query, params).fetchone()[0]

    query = select_fields + where_sql + " ORDER BY m.created_at DESC, m.id DESC LIMIT ? OFFSET ?"
    fetch_params = list(params) + [limit, offset]

    rows = conn.execute(query, fetch_params).fetchall()
    conn.close()
    return {
        'items': [dict(r) for r in rows],
        'total': total_count,
        'limit': limit,
        'offset': offset
    }

def get_mark_by_id(mark_id):
    conn = get_conn()
    row = conn.execute("""
        SELECT m.id, m.station_id, m.fuel_code, m.status, m.mark_type, m.limit_liters,
               m.queue_count, m.user_tg_id, m.username, m.created_at,
               s.name AS station_name, s.brand AS station_brand, s.address AS station_address,
               (
                   SELECT c.comment 
                   FROM comments c 
                   WHERE c.station_id = m.station_id 
                     AND (c.username = m.username OR (c.user_tg_id = m.user_tg_id AND c.user_tg_id != 0))
                     AND c.created_at <= datetime(m.created_at, '+5 seconds')
                     AND c.created_at >= datetime(m.created_at, '-120 seconds')
                   ORDER BY c.created_at DESC, c.id DESC LIMIT 1
               ) AS comment_text,
               (
                   SELECT c.photo_path 
                   FROM comments c 
                   WHERE c.station_id = m.station_id 
                     AND (c.username = m.username OR (c.user_tg_id = m.user_tg_id AND c.user_tg_id != 0))
                     AND c.created_at <= datetime(m.created_at, '+5 seconds')
                     AND c.created_at >= datetime(m.created_at, '-120 seconds')
                     AND c.photo_path IS NOT NULL AND c.photo_path != ''
                   ORDER BY c.created_at DESC, c.id DESC LIMIT 1
               ) AS photo_path
        FROM marks m
        LEFT JOIN stations s ON s.id = m.station_id
        WHERE m.id = ?
    """, (mark_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def update_admin_mark(mark_id, station_id=None, fuel_code=None, status=None, limit_liters=None, queue_count=None, username=None):
    conn = get_conn()
    updates = []
    params = []
    if station_id is not None:
        updates.append("station_id = ?")
        params.append(int(station_id))
    if fuel_code is not None:
        updates.append("fuel_code = ?")
        params.append(fuel_code)
    if status is not None:
        updates.append("status = ?")
        params.append(status)
    if limit_liters is not None and limit_liters != '':
        updates.append("limit_liters = ?")
        params.append(int(limit_liters))
    elif limit_liters == '' or limit_liters is None:
        updates.append("limit_liters = NULL")
    if queue_count is not None and queue_count != '':
        updates.append("queue_count = ?")
        params.append(int(queue_count))
    elif queue_count == '' or queue_count is None:
        updates.append("queue_count = NULL")
    if username is not None:
        updates.append("username = ?")
        params.append(username)

    if updates:
        params.append(mark_id)
        conn.execute(f"UPDATE marks SET {', '.join(updates)} WHERE id = ?", params)
        conn.commit()
    conn.close()
    return True

def delete_admin_mark(mark_id):
    conn = get_conn()
    conn.execute("DELETE FROM marks WHERE id = ?", (mark_id,))
    conn.commit()
    conn.close()
    return True

def get_admin_comments(station_id=None, search=None, limit=50, offset=0):
    conn = get_conn()
    query = """
        SELECT c.id, c.station_id, c.user_tg_id, c.username, c.comment, c.has_photo, c.photo_path, c.created_at,
               s.name AS station_name, s.brand AS station_brand, s.address AS station_address
        FROM comments c
        LEFT JOIN stations s ON s.id = c.station_id
        WHERE 1=1
    """
    params = []
    if station_id:
        query += " AND c.station_id = ?"
        params.append(station_id)
    if search:
        search_term = f"%{search.strip()}%"
        query += " AND (c.comment LIKE ? OR s.name LIKE ? OR c.username LIKE ?)"
        params.extend([search_term, search_term, search_term])

    count_query = f"SELECT COUNT(*) FROM ({query})"
    total_count = conn.execute(count_query, params).fetchone()[0]

    query += " ORDER BY c.created_at DESC, c.id DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    rows = conn.execute(query, params).fetchall()
    conn.close()
    return {
        'items': [dict(r) for r in rows],
        'total': total_count,
        'limit': limit,
        'offset': offset
    }

def delete_admin_comment(comment_id):
    conn = get_conn()
    conn.execute("DELETE FROM comments WHERE id = ?", (comment_id,))
    conn.commit()
    conn.close()
    return True

def set_station_closed(station_id: int, is_closed: int = 1, closed_reason: str = '', reopen_date: str = ''):
    conn = get_conn()
    conn.execute("""
        UPDATE stations
        SET is_closed = ?, closed_reason = ?, reopen_date = ?
        WHERE id = ?
    """, (is_closed, closed_reason, reopen_date, station_id))
    conn.commit()
    conn.close()
    return True

def log_user_events(events: list, ip: str = '', user_agent: str = ''):
    """
    Saves a batch of user behavior events into user_events table.
    """
    if not events:
        return 0
    conn = get_conn()
    records = []
    for ev in events:
        if not isinstance(ev, dict):
            continue
        event_name = str(ev.get('event_name') or ev.get('name') or '').strip()
        if not event_name:
            continue
        session_id = str(ev.get('session_id') or '')[:64]
        guest_id = str(ev.get('guest_id') or '')[:64]
        user_tg_id = ev.get('user_tg_id') or ev.get('user_id')
        try:
            user_tg_id = int(user_tg_id) if user_tg_id else None
        except Exception:
            user_tg_id = None
        username = str(ev.get('username') or '')[:64]
        station_id = ev.get('station_id')
        try:
            station_id = int(station_id) if station_id is not None else None
        except Exception:
            station_id = None
        
        raw_data = ev.get('data') or ev.get('event_data') or {}
        event_data_str = json.dumps(raw_data, ensure_ascii=False) if isinstance(raw_data, (dict, list)) else str(raw_data)
        
        records.append((
            session_id,
            guest_id,
            user_tg_id,
            username,
            event_name,
            station_id,
            event_data_str,
            ip,
            user_agent[:255]
        ))
    
    if records:
        conn.executemany("""
            INSERT INTO user_events (
                session_id, guest_id, user_tg_id, username, event_name,
                station_id, event_data, ip, user_agent
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, records)
        conn.commit()
    conn.close()
    return len(records)

def get_user_events_summary(hours: int = 24):
    """
    Aggregates user analytics metrics for the last N hours.
    """
    conn = get_conn()
    since = (datetime.utcnow() - timedelta(hours=hours)).strftime('%Y-%m-%d %H:%M:%S')

    # 1. Total events & unique sessions / guests
    stats_row = conn.execute("""
        SELECT 
            COUNT(*) AS total_events,
            COUNT(DISTINCT session_id) AS unique_sessions,
            COUNT(DISTINCT NULLIF(guest_id, '')) AS unique_guests,
            COUNT(DISTINCT user_tg_id) AS unique_tg_users
        FROM user_events
        WHERE created_at >= ?
    """, (since,)).fetchone()

    # 2. Events breakdown by name
    name_rows = conn.execute("""
        SELECT event_name, COUNT(*) AS cnt
        FROM user_events
        WHERE created_at >= ?
        GROUP BY event_name
        ORDER BY cnt DESC
    """, (since,)).fetchall()

    # 3. Top stations clicked
    station_rows = conn.execute("""
        SELECT ue.station_id, s.name, s.brand, s.address, COUNT(*) AS clicks
        FROM user_events ue
        JOIN stations s ON s.id = ue.station_id
        WHERE ue.created_at >= ? AND ue.event_name IN ('station_click', 'station_panel_open')
        GROUP BY ue.station_id
        ORDER BY clicks DESC
        LIMIT 10
    """, (since,)).fetchall()

    # 4. Top routes built (navigator clicks)
    route_rows = conn.execute("""
        SELECT ue.station_id, s.name, s.brand, COUNT(*) AS routes
        FROM user_events ue
        JOIN stations s ON s.id = ue.station_id
        WHERE ue.created_at >= ? AND ue.event_name = 'route_build'
        GROUP BY ue.station_id
        ORDER BY routes DESC
        LIMIT 10
    """, (since,)).fetchall()

    # 5. Top fuel search filters
    fuel_filter_rows = conn.execute("""
        SELECT 
            json_extract(event_data, '$.fuel_code') AS fuel_code,
            COUNT(*) AS cnt
        FROM user_events
        WHERE created_at >= ? AND event_name = 'filter_fuel'
        GROUP BY fuel_code
        ORDER BY cnt DESC
    """, (since,)).fetchall()

    # 6. Urgent search mode stats
    urgent_rows = conn.execute("""
        SELECT 
            json_extract(event_data, '$.tab') AS mode_tab,
            COUNT(*) AS cnt
        FROM user_events
        WHERE created_at >= ? AND event_name IN ('urgent_open', 'urgent_tab_switch')
        GROUP BY mode_tab
        ORDER BY cnt DESC
    """, (since,)).fetchall()

    # 7. Promo and Ad banner clicks
    promo_rows = conn.execute("""
        SELECT 
            COALESCE(json_extract(event_data, '$.title'), 'Баннер') AS title,
            COALESCE(json_extract(event_data, '$.placement'), 'map') AS placement,
            COALESCE(json_extract(event_data, '$.target'), 'link') AS target,
            COUNT(*) AS cnt
        FROM user_events
        WHERE created_at >= ? AND event_name = 'promo_click'
        GROUP BY title, placement, target
        ORDER BY cnt DESC
    """, (since,)).fetchall()

    conn.close()

    return {
        'period_hours': hours,
        'since': since,
        'total_events': stats_row['total_events'] if stats_row else 0,
        'unique_sessions': stats_row['unique_sessions'] if stats_row else 0,
        'unique_guests': stats_row['unique_guests'] if stats_row else 0,
        'unique_tg_users': stats_row['unique_tg_users'] if stats_row else 0,
        'events_by_name': {r['event_name']: r['cnt'] for r in name_rows},
        'top_stations': [dict(r) for r in station_rows],
        'top_routes': [dict(r) for r in route_rows],
        'fuel_filters': [dict(r) for r in fuel_filter_rows if r['fuel_code']],
        'urgent_modes': [dict(r) for r in urgent_rows if r['mode_tab']],
        'promo_clicks': [dict(r) for r in promo_rows]
    }



