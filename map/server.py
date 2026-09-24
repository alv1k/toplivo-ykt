import json
import http.server
import os
import sys
import urllib.parse
import urllib.request
import hashlib
import hmac
import logging
import re as re_module
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db
import config

logging.basicConfig(
    format='%(asctime)s MAP %(levelname)s %(message)s',
    level=logging.INFO,
    datefmt='%Y-%m-%d %H:%M:%S'
)

FUEL_LABELS = {'92': 'АИ-92', '95': 'АИ-95', '98': 'АИ-98', '100': 'АИ-100', 'dt': 'ДТ', 'gas': 'Газ', 'ts1': 'ТС-1', '92ef': '92 Эф.'}
STATUS_EMOJI = {'yes': '🟢', 'no': '🔴', 'queue': '🟡', 'limit': '🟠'}
STATUS_LABEL = {'yes': 'Есть', 'no': 'Нет', 'queue': 'Очередь', 'limit': 'Лимит'}

_rate_limit = {}
_guest_rate_limit = {}
_cache = {}
CACHE_STATIONS_TTL = 15
CACHE_ACTIVITY_TTL = 10

import asyncio
import websockets

_ws_clients = set()
_ws_loop = None

async def _ws_handler(websocket):
    _ws_clients.add(websocket)
    try:
        await websocket.send(json.dumps({'type': 'connected', 'ts': time.time()}))
        async for message in websocket:
            pass
    except Exception:
        pass
    finally:
        _ws_clients.discard(websocket)

def _broadcast_ws(data):
    if not _ws_loop or not _ws_clients:
        return
    msg = json.dumps(data)
    for ws in list(_ws_clients):
        try:
            asyncio.run_coroutine_threadsafe(ws.send(msg), _ws_loop)
        except Exception:
            pass

def _start_ws_server(port=8766):
    global _ws_loop
    _ws_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_ws_loop)

    async def run():
        async with websockets.serve(_ws_handler, "127.0.0.1", port):
            logging.info(f"WebSocket server running on ws://127.0.0.1:{port}")
            await asyncio.Future()

    _ws_loop.run_until_complete(run())

def _invalidate_cache():
    _cache.clear()
    _broadcast_ws({'type': 'stations_updated', 'ts': time.time()})

def _notify_admins(msg):
    for admin_id in config.ADMIN_IDS:
        try:
            url = f'https://api.telegram.org/bot{config.BOT_TOKEN}/sendMessage'
            body = json.dumps({'chat_id': admin_id, 'text': msg, 'parse_mode': 'HTML'}).encode()
            urllib.request.urlopen(urllib.request.Request(url, data=body, headers={'Content-Type': 'application/json'}), timeout=10)
        except Exception as e:
            logging.error(f'Admin notification failed for {admin_id}: {e}')

def _notify_all_users(msg):
    users = db.get_all_users()
    for uid in users:
        try:
            url = f'https://api.telegram.org/bot{config.BOT_TOKEN}/sendMessage'
            body = json.dumps({'chat_id': uid, 'text': msg, 'parse_mode': 'HTML'}).encode()
            urllib.request.urlopen(urllib.request.Request(url, data=body, headers={'Content-Type': 'application/json'}), timeout=10)
        except Exception as e:
            logging.error(f'User notification failed for {uid}: {e}')

ALLOWED_ORIGINS = {'https://344988.snk.wtf', 'https://fuel-map.tiinservice.online'}

class FuelHandler(http.server.SimpleHTTPRequestHandler):
    def _allowed_origin(self):
        origin = self.headers.get('Origin', '')
        if origin in ALLOWED_ORIGINS:
            return origin
        return 'https://344988.snk.wtf'

    def _get_client_ip(self):
        real_ip = self.headers.get('X-Real-IP')
        if real_ip:
            return real_ip.strip()
        fwd = self.headers.get('X-Forwarded-For')
        if fwd:
            return fwd.split(',')[0].strip()
        return self.client_address[0]

    def _send_json(self, data, status=200, cache_ttl=None):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', self._allowed_origin())
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        if cache_ttl is not None:
            self.send_header('Cache-Control', f'public, max-age={cache_ttl}')
        self.end_headers()
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.wfile.write(body)

    def _check_rate_limit(self):
        ip = self._get_client_ip()
        now = __import__('time').time()
        entry = _rate_limit.get(ip)
        if entry:
            count, window = entry
            if now - window < 60:
                if count >= 10:
                    return False
                _rate_limit[ip] = (count + 1, window)
            else:
                _rate_limit[ip] = (1, now)
        else:
            _rate_limit[ip] = (1, now)
        return True

    def _check_guest_rate_limit(self):
        ip = self._get_client_ip()
        now = __import__('time').time()
        entry = _guest_rate_limit.get(ip)
        if entry:
            count, window = entry
            if now - window < 60:
                if count >= 3:
                    return False
                _guest_rate_limit[ip] = (count + 1, window)
            else:
                _guest_rate_limit[ip] = (1, now)
        else:
            _guest_rate_limit[ip] = (1, now)
        return True

    def _validate_init_data(self, init_data):
        if not init_data:
            return None
        pairs = init_data.split('&')
        params = {}
        hash_val = None
        for pair in pairs:
            if '=' not in pair:
                continue
            key, _, val = pair.partition('=')
            key = urllib.parse.unquote(key)
            val = urllib.parse.unquote(val)
            if key == 'hash':
                hash_val = val
            else:
                params[key] = val
        if not hash_val:
            return None
        items = sorted(params.items())
        check_string = '\n'.join(f'{k}={v}' for k, v in items)
        secret = hmac.new(b"WebAppData", config.BOT_TOKEN.encode(), hashlib.sha256).digest()
        sig = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
        if sig != hash_val:
            return None
        user_json = params.get('user', '{}')
        try:
            user = json.loads(user_json)
            return (user.get('id'), user.get('username', ''))
        except (json.JSONDecodeError, TypeError):
            return None

    def _read_body(self):
        length = int(self.headers.get('Content-Length', 0))
        if length == 0:
            return None
        return self.rfile.read(length)

    def _check_admin_auth(self):
        admin_token = self.headers.get('X-Admin-Token', '').strip()
        if not admin_token:
            auth_header = self.headers.get('Authorization', '').strip()
            if auth_header.startswith('Bearer '):
                admin_token = auth_header[7:].strip()
        if not admin_token:
            cookie_header = self.headers.get('Cookie', '')
            for cookie in cookie_header.split(';'):
                if 'admin_token=' in cookie:
                    admin_token = cookie.split('admin_token=')[1].strip()
                    break
        if not admin_token:
            parsed_url = urllib.parse.urlparse(self.path)
            qs = urllib.parse.parse_qs(parsed_url.query)
            admin_token = qs.get('token', [''])[0].strip()

        if config.ADMIN_TOKEN and admin_token and hmac.compare_digest(admin_token, config.ADMIN_TOKEN):
            return True, "admin"

        init_data = self.headers.get('X-Telegram-Init-Data', '')
        if not init_data:
            parsed_url = urllib.parse.urlparse(self.path)
            qs = urllib.parse.parse_qs(parsed_url.query)
            init_data = qs.get('initData', [''])[0]

        user_info = self._validate_init_data(init_data)
        if user_info:
            tg_id, username = user_info
            if tg_id in config.ADMIN_IDS:
                return True, username or str(tg_id)

        return False, None

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', self._allowed_origin())
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, X-Admin-Token, Authorization, X-Telegram-Init-Data')
        self.end_headers()

    def do_GET(self):
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path
        if path.startswith('/fuel-map/'):
            path = path[len('/fuel-map'):]
        qs = urllib.parse.parse_qs(parsed_url.query)

        if path in ('/admin', '/admin/', '/admin.html'):
            admin_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'admin.html')
            if os.path.exists(admin_path):
                with open(admin_path, 'rb') as f:
                    data = f.read()
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(data)))
                self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate, max-age=0')
                self.send_header('Access-Control-Allow-Origin', self._allowed_origin())
                self.end_headers()
                self.wfile.write(data)
                return
            else:
                self._send_json({'error': 'admin page not found'}, 404)
                return

        elif path == '/api/admin/auth-check':
            is_auth, user = self._check_admin_auth()
            self._send_json({'authenticated': is_auth, 'user': user if is_auth else None})
            return

        elif path == '/api/admin/analytics':
            is_auth, _ = self._check_admin_auth()
            if not is_auth:
                self._send_json({'error': 'unauthorized'}, 401)
                return
            try:
                hours = int(qs.get('hours', ['24'])[0])
            except Exception:
                hours = 24
            hours = max(1, min(720, hours))
            summary = db.get_user_events_summary(hours=hours)
            self._send_json(summary)
            return

        elif path == '/api/admin/marks':
            is_auth, _ = self._check_admin_auth()
            if not is_auth:
                self._send_json({'error': 'unauthorized'}, 401)
                return
            st_id = qs.get('station_id', [''])[0]
            fc = qs.get('fuel_code', [''])[0]
            status = qs.get('status', [''])[0]
            mt = qs.get('mark_type', [''])[0]
            search = qs.get('search', [''])[0]
            limit = int(qs.get('limit', ['50'])[0])
            offset = int(qs.get('offset', ['0'])[0])
            res = db.get_admin_marks(
                station_id=int(st_id) if st_id else None,
                fuel_code=fc or None,
                status=status or None,
                mark_type=mt or None,
                search=search or None,
                limit=limit,
                offset=offset
            )
            self._send_json(res)
            return

        elif path == '/api/admin/comments':
            is_auth, _ = self._check_admin_auth()
            if not is_auth:
                self._send_json({'error': 'unauthorized'}, 401)
                return
            st_id = qs.get('station_id', [''])[0]
            search = qs.get('search', [''])[0]
            limit = int(qs.get('limit', ['50'])[0])
            offset = int(qs.get('offset', ['0'])[0])
            res = db.get_admin_comments(
                station_id=int(st_id) if st_id else None,
                search=search or None,
                limit=limit,
                offset=offset
            )
            self._send_json(res)
            return

        elif path == '/api/admin/stations':
            is_auth, _ = self._check_admin_auth()
            if not is_auth:
                self._send_json({'error': 'unauthorized'}, 401)
                return
            stations = db.load_stations()
            self._send_json([
                {
                    'id': s['id'],
                    'name': s['name'],
                    'brand': s.get('brand', ''),
                    'address': s.get('address', ''),
                    'city': s.get('city', 'Якутск'),
                    'is_closed': s.get('is_closed', 0),
                    'unloading_until': s.get('unloading_until', '')
                } for s in stations
            ])
            return

        elif path == '/partner' or path == '/partner/' or path == '/partner.html':
            partner_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'partner.html')
            if os.path.exists(partner_path):
                with open(partner_path, 'rb') as f:
                    data = f.read()
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(data)))
                self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate, max-age=0')
                self.send_header('Access-Control-Allow-Origin', self._allowed_origin())
                self.end_headers()
                self.wfile.write(data)
                return
            else:
                self._send_json({'error': 'partner page not found'}, 404)
                return

        elif path == '/api/partner/stations':
            token = qs.get('token', [''])[0].strip()
            partner_info = db.get_partner_by_token(token)
            if not partner_info:
                self._send_json({'error': 'invalid token'}, 403)
                return
            stations = db.get_partner_stations(partner_info)
            self._send_json({'brand_name': partner_info['brand_name'], 'stations': stations})
            return

        elif path == '/api/stations':
            period = qs.get('period', ['24h'])[0]
            cache_key = f'stations_{period}'
            now = time.time()
            cached = _cache.get(cache_key)
            if cached and now - _cache.get(f'{cache_key}_ts', 0) < CACHE_STATIONS_TTL:
                self._send_json(cached, cache_ttl=CACHE_STATIONS_TTL)
            else:
                stations = db.get_stations_full(period=period)
                _cache[cache_key] = stations
                _cache[f'{cache_key}_ts'] = now
                self._send_json(stations, cache_ttl=CACHE_STATIONS_TTL)
        elif path == '/api/suggestions':
            suggestions = db.get_station_suggestions()
            self._send_json(suggestions)
        elif path == '/api/cities':
            now = time.time()
            cached = _cache.get('cities')
            if cached and now - _cache.get('cities_ts', 0) < CACHE_STATIONS_TTL:
                self._send_json(cached, cache_ttl=CACHE_STATIONS_TTL)
            else:
                cities = db.get_cities()
                _cache['cities'] = cities
                _cache['cities_ts'] = now
                self._send_json(cities, cache_ttl=CACHE_STATIONS_TTL)
        elif path == '/api/station-roads':
            roads_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'station_roads.json')
            if os.path.exists(roads_file):
                with open(roads_file, 'r', encoding='utf-8') as f:
                    self._send_json(json.load(f), cache_ttl=3600)
            else:
                self._send_json({})
        elif path == '/api/stats':
            stats = db.get_visitor_stats()
            self._send_json(stats, cache_ttl=30)
        elif path == '/api/activity':
            now = time.time()
            cached = _cache.get('activity')
            if cached and now - _cache.get('activity_ts', 0) < CACHE_ACTIVITY_TTL:
                self._send_json(cached, cache_ttl=CACHE_ACTIVITY_TTL)
            else:
                activity = db.get_recent_activity(60)
                _cache['activity'] = activity
                _cache['activity_ts'] = now
                self._send_json(activity, cache_ttl=CACHE_ACTIVITY_TTL)
        elif path == '/api/photos':
            now = time.time()
            cached = _cache.get('photos')
            if cached and now - _cache.get('photos_ts', 0) < CACHE_ACTIVITY_TTL:
                self._send_json(cached, cache_ttl=CACHE_ACTIVITY_TTL)
            else:
                photos = db.get_recent_photos(20)
                _cache['photos'] = photos
                _cache['photos_ts'] = now
                self._send_json(photos, cache_ttl=CACHE_ACTIVITY_TTL)
        elif path.startswith('/api/stations/') and '/marks/' in path:
            parts = path.split('/')
            try:
                station_id = int(parts[3])
                fuel_code = parts[5]
            except (IndexError, ValueError):
                self._send_json({'error': 'invalid path'}, 400)
                return
            marks = db.get_station_fuel_marks(station_id, fuel_code)
            self._send_json(marks)
        elif re_module.match(r'^/api/comments/(\d+)(\?.*)?$', path):
            m = re_module.match(r'^/api/comments/(\d+)', path)
            station_id = int(m.group(1))
            init_data = qs.get('init_data', [None])[0]
            user_info = self._validate_init_data(init_data) if init_data else None
            if user_info:
                user_tg_id = user_info[0]
            else:
                guest_id = qs.get('guest_id', [None])[0]
                if guest_id:
                    user_tg_id = -(abs(hash(guest_id)) % 1000000000)
                else:
                    client_ip = self._get_client_ip()
                    user_tg_id = -(abs(hash(client_ip)) % 1000000000)
            comments = db.get_station_comments(station_id, user_tg_id=user_tg_id)
            self._send_json(comments)
        elif path.startswith('/media/'):
            filename = os.path.basename(path.split('?')[0])
            base_media = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'media')
            media_paths = [
                os.path.join(base_media, 'whatsapp', filename),
                os.path.join(base_media, 'telegram', filename),
                os.path.join(base_media, 'uploads', filename),
                os.path.join(base_media, 'images', filename),
                os.path.join(base_media, filename),
            ]
            target_file = None
            for mp in media_paths:
                if os.path.exists(mp):
                    target_file = mp
                    break

            if target_file:
                content_type = 'image/jpeg'
                if filename.endswith('.png'): content_type = 'image/png'
                elif filename.endswith('.webp'): content_type = 'image/webp'
                elif filename.endswith('.svg'): content_type = 'image/svg+xml'
                with open(target_file, 'rb') as f:
                    data = f.read()
                self.send_response(200)
                self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', str(len(data)))
                self.send_header('Cache-Control', 'public, max-age=86400')
                self.send_header('Access-Control-Allow-Origin', self._allowed_origin())
                self.end_headers()
                self.wfile.write(data)
            else:
                self.send_response(404)
                self.send_header('Content-Type', 'text/plain; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', self._allowed_origin())
                self.end_headers()
                self.wfile.write(b'404 Not Found')
        elif path == '/' or path == '/index.html' or path == '':
            index_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'index.html')
            with open(index_path, 'rb') as f:
                data = f.read()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate, max-age=0')
            self.send_header('Pragma', 'no-cache')
            self.send_header('Expires', '0')
            self.send_header('Access-Control-Allow-Origin', self._allowed_origin())
            self.end_headers()
            self.wfile.write(data)
            threading.Thread(target=db.record_visit,
                args=(self._get_client_ip(), self.headers.get('User-Agent', '')),
                daemon=True).start()
        else:
            super().do_GET()

    def do_POST(self):
        if not self._check_rate_limit():
            self._send_json({'error': 'too many requests'}, 429)
            return

        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path
        if path.startswith('/fuel-map/'):
            path = path[len('/fuel-map'):]

        if path == '/api/partner/update':
            raw = self._read_body()
            if not raw:
                self._send_json({'error': 'empty body'}, 400)
                return
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                self._send_json({'error': 'invalid json'}, 400)
                return

            token = data.get('token', '').strip()
            partner_info = db.get_partner_by_token(token)
            if not partner_info:
                self._send_json({'error': 'unauthorized'}, 403)
                return

            station_id = data.get('station_id')
            fuel_code = data.get('fuel_code')
            status = data.get('status')
            limit_liters = data.get('limit_liters')

            if not all([station_id, fuel_code, status]):
                self._send_json({'error': 'station_id, fuel_code, status required'}, 400)
                return
            if status not in ('yes', 'no', 'queue', 'limit'):
                self._send_json({'error': 'invalid status'}, 400)
                return

            try:
                station_id = int(station_id)
            except (ValueError, TypeError):
                self._send_json({'error': 'invalid station_id'}, 400)
                return

            if limit_liters is not None:
                try:
                    limit_liters = int(limit_liters)
                except (ValueError, TypeError):
                    limit_liters = None

            # Verify station belongs to this partner
            partner_stations = db.get_partner_stations(partner_info)
            allowed_ids = {s['id'] for s in partner_stations}
            if station_id not in allowed_ids:
                self._send_json({'error': 'station does not belong to your network'}, 403)
                return

            db.add_partner_mark(station_id, fuel_code, status, limit_liters=limit_liters, brand_name=partner_info['brand_name'])
            _invalidate_cache()

            station_name = db.get_station_name(station_id)
            fuel_label = FUEL_LABELS.get(fuel_code, fuel_code)
            status_text = STATUS_LABEL.get(status, status)
            if status == 'limit' and limit_liters:
                status_text += f' ({limit_liters} л)'
            admin_msg = (
                f'🏢 <b>Обновление от оператора ({partner_info["brand_name"]})</b>\n'
                f'📍 {station_name}\n'
                f'⛽ {fuel_label}: {STATUS_EMOJI.get(status, "⚪")} {status_text}'
            )
            threading.Thread(target=_notify_admins, args=(admin_msg,), daemon=True).start()

            self._send_json({'ok': True})
            return

        elif path == '/api/mark':
            raw = self._read_body()
            if not raw:
                self._send_json({'error': 'empty body'}, 400)
                return
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                self._send_json({'error': 'invalid json'}, 400)
                return

            user_info = self._validate_init_data(data.get('init_data', ''))
            is_guest = False
            if not user_info:
                if not self._check_guest_rate_limit():
                    self._send_json({'error': 'too many requests'}, 429)
                    return
                is_guest = True
                user_id = 0
                username = data.get('guest_id', '')[:50] or 'guest'
            else:
                user_id, username = user_info

            station_id = data.get('station_id')
            fuel_code = data.get('fuel_code')
            status = data.get('status')
            mark_type = data.get('mark_type', 'full')

            if not all([station_id, fuel_code, status]):
                self._send_json({'error': 'station_id, fuel_code, status required'}, 400)
                return
            if not isinstance(station_id, int) or station_id < 1:
                self._send_json({'error': 'invalid station_id'}, 400)
                return
            if status not in ('yes', 'no', 'queue', 'limit'):
                self._send_json({'error': 'invalid status'}, 400)
                return
            if mark_type not in ('full', 'arrival', 'passby'):
                self._send_json({'error': 'invalid mark_type'}, 400)
                return

            queue_count = data.get('queue_count')
            if queue_count is not None:
                try:
                    queue_count = int(queue_count)
                    if queue_count < 0 or queue_count > 100:
                        self._send_json({'error': 'invalid queue_count'}, 400)
                        return
                except (ValueError, TypeError):
                    self._send_json({'error': 'invalid queue_count'}, 400)
                    return

            payment_method = data.get('payment_method')
            if payment_method not in ('card', 'cash', None):
                self._send_json({'error': 'invalid payment_method'}, 400)
                return

            bonus_card = data.get('bonus_card')
            if bonus_card is not None:
                bonus_card = bool(bonus_card)

            pump_number = data.get('pump_number')
            if pump_number is not None:
                pump_number = str(pump_number)[:50]

            if mark_type == 'passby':
                passby_status = data.get('status', 'queue')
                if passby_status not in ('yes', 'no', 'queue', 'limit'):
                    passby_status = 'queue'
                db.add_mark_v2(
                    station_id, '_station_', passby_status, user_id, username,
                    mark_type='passby', queue_count=queue_count,
                    payment_method=None, bonus_card=None, pump_number=pump_number
                )
            else:
                db.add_mark_v2(
                    station_id, fuel_code, status, user_id, username,
                    mark_type=mark_type,
                    queue_count=queue_count,
                    payment_method=payment_method,
                    bonus_card=bonus_card,
                    pump_number=pump_number
                )

            self._send_json({'ok': True, 'id': station_id})
            _invalidate_cache()

            station_name = db.get_station_name(station_id)
            mark_type_label = {'full': '⛽ Заправился', 'arrival': '🚗 Подъехал', 'passby': '👀 Проехал мимо'}.get(mark_type, '⛽ Заправился')

            if mark_type == 'passby':
                msg = (
                    f'🆕 <b>Проехал мимо</b>\n'
                    f'📍 {station_name}\n'
                    f'{STATUS_EMOJI.get(status, "⚪")} {STATUS_LABEL.get(status, status)}\n'
                    f'{mark_type_label}'
                )
            else:
                fuel_label = FUEL_LABELS.get(fuel_code, fuel_code)
                msg = (
                    f'🆕 <b>Новая отметка</b>\n'
                    f'📍 {station_name}\n'
                    f'⛽ {fuel_label}: {STATUS_EMOJI.get(status, "⚪")} {STATUS_LABEL.get(status, status)}\n'
                    f'{mark_type_label}'
                )
            if queue_count:
                msg += f'\n🚗 Очередь: {queue_count}'
            if payment_method:
                msg += f'\n💳 {"Карта" if payment_method == "card" else "Наличные"}'
            if bonus_card is not None:
                msg += f'\n👍 Бонусная карта: {"да" if bonus_card else "нет"}'
            if pump_number:
                msg += f'\n⛽ Колонка: {pump_number}'
            if not is_guest:
                threading.Thread(target=_notify_admins, args=(msg,), daemon=True).start()
            if not is_guest and fuel_code != '_station_':
                threading.Thread(target=_notify_all_users, args=(msg,), daemon=True).start()

        elif path == '/api/trigger-update':
            _invalidate_cache()
            self._send_json({'ok': True, 'broadcasted': True})
            return

        elif path == '/api/mark/delete':
            raw = self._read_body()
            if not raw:
                self._send_json({'error': 'empty body'}, 400)
                return
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                self._send_json({'error': 'invalid json'}, 400)
                return

            user_info = self._validate_init_data(data.get('init_data', ''))
            if not user_info:
                self._send_json({'error': 'unauthorized'}, 403)
                return
            user_id, _ = user_info

            mark_id = data.get('mark_id')
            if not mark_id:
                self._send_json({'error': 'mark_id required'}, 400)
                return
            try:
                mark_id = int(mark_id)
            except (ValueError, TypeError):
                self._send_json({'error': 'invalid mark_id'}, 400)
                return

            ok = db.delete_mark(mark_id, int(user_id))
            if ok:
                self._send_json({'ok': True})
                _invalidate_cache()
            else:
                self._send_json({'error': 'not found or not yours'}, 404)

        elif path == '/api/comment':
            raw = self._read_body()
            if not raw:
                self._send_json({'error': 'empty body'}, 400)
                return
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                self._send_json({'error': 'invalid json'}, 400)
                return

            user_info = self._validate_init_data(data.get('init_data', ''))
            is_guest = False
            if not user_info:
                if not self._check_guest_rate_limit():
                    self._send_json({'error': 'too many requests'}, 429)
                    return
                is_guest = True
                user_id = 0
                guest_name = data.get('guest_id', '')[:30] or 'Водитель'
                username = f"guest:{guest_name}"
            else:
                user_id, username = user_info

            station_id = data.get('station_id')
            if not isinstance(station_id, int) or station_id < 1:
                self._send_json({'error': 'invalid station_id'}, 400)
                return

            comment = data.get('comment', '').strip()
            if not comment:
                self._send_json({'error': 'comment required'}, 400)
                return
            comment = re_module.sub(r'<[^>]+>', '', comment)[:500]

            db.add_comment(station_id, user_id, username, comment)
            self._send_json({'ok': True})
            _invalidate_cache()

            station_name = db.get_station_name(station_id)
            username_str = f'\nОт: @{username}' if username else ''
            msg = (
                f'💬 <b>Новый комментарий</b>\n'
                f'📍 {station_name}\n'
                f'💬 {comment}'
                f'{username_str}'
            )
            threading.Thread(target=_notify_admins, args=(msg,), daemon=True).start()
            threading.Thread(target=_notify_all_users, args=(msg,), daemon=True).start()

        elif re_module.match(r'^/api/comment/(\d+)/react$', path):
            raw = self._read_body()
            if not raw:
                self._send_json({'error': 'empty body'}, 400)
                return
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                self._send_json({'error': 'invalid json'}, 400)
                return

            user_info = self._validate_init_data(data.get('init_data', ''))
            if user_info:
                user_id = user_info[0]
            else:
                guest_id = data.get('guest_id', '')
                if not guest_id:
                    # Создаём или получаем синтетический id на основе IP клиента
                    client_ip = self._get_client_ip()
                    user_id = -(abs(hash(client_ip)) % 1000000000)
                else:
                    user_id = -(abs(hash(guest_id)) % 1000000000)

            parts = path.split('/')
            comment_id = int(parts[3])
            reaction = data.get('reaction')
            if reaction not in (1, -1, 0):
                self._send_json({'error': 'reaction must be 1, -1 or 0'}, 400)
                return

            db.add_reaction(comment_id, user_id, reaction)
            self._send_json({'ok': True})

        elif path == '/api/suggest-station':
            raw = self._read_body()
            if not raw:
                self._send_json({'error': 'empty body'}, 400)
                return
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                self._send_json({'error': 'invalid json'}, 400)
                return

            user_info = self._validate_init_data(data.get('init_data', ''))
            if not user_info:
                if not self._check_guest_rate_limit():
                    self._send_json({'error': 'too many requests'}, 429)
                    return
                user_id = 0
                guest_name = data.get('guest_id', '')[:30] or 'Гость'
                username = f"guest:{guest_name}"
            else:
                user_id, username = user_info

            lat = data.get('lat')
            lon = data.get('lon')
            try:
                lat = float(lat)
                lon = float(lon)
            except (TypeError, ValueError):
                self._send_json({'error': 'invalid coordinates'}, 400)
                return
            if abs(lat) > 90 or abs(lon) > 180:
                self._send_json({'error': 'invalid coordinates'}, 400)
                return

            name = data.get('name', '').strip()
            name = re_module.sub(r'<[^>]+>', '', name)[:100]
            if not name:
                name = f'Новая АЗС ({lat:.4f}, {lon:.4f})'

            brand = data.get('brand', '').strip()[:50]
            address = data.get('address', '').strip()[:200]
            comment = data.get('comment', '').strip()[:500]
            comment = re_module.sub(r'<[^>]+>', '', comment)

            db.add_suggestion(name, lat, lon, brand=brand, address=address, comment=comment, user_tg_id=user_id, username=username)
            self._send_json({'ok': True})
            _invalidate_cache()

            user_from = f"\nОт: @{username}" if username else ""
            msg = (
                f'🆕 <b>Предложена новая АЗС</b>\n'
                f'Название: {name}\n'
                f'Сеть: {brand or "—"}\n'
                f'Адрес: {address or "—"}\n'
                f'Координаты: <code>{lat:.5f}, {lon:.5f}</code>\n'
                f'Комментарий: {comment or "—"}'
                f'{user_from}'
            )
            threading.Thread(target=_notify_admins, args=(msg,), daemon=True).start()

        elif path == '/api/feedback':
            raw = self._read_body()
            if not raw:
                self._send_json({'error': 'empty body'}, 400)
                return
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                self._send_json({'error': 'invalid json'}, 400)
                return

            message = data.get('message', '').strip()
            if not message:
                self._send_json({'error': 'message cannot be empty'}, 400)
                return
            message = re_module.sub(r'<[^>]+>', '', message)[:1000]

            feedback_type = data.get('type', 'other').strip()[:30]
            station_id = data.get('station_id')
            if station_id is not None:
                try:
                    station_id = int(station_id)
                except (ValueError, TypeError):
                    station_id = None

            contact = data.get('contact', '').strip()[:100]
            contact = re_module.sub(r'<[^>]+>', '', contact)

            user_info = self._validate_init_data(data.get('init_data', ''))
            if user_info:
                user_id, username = user_info
            else:
                if not self._check_guest_rate_limit():
                    self._send_json({'error': 'too many requests'}, 429)
                    return
                user_id = None
                username = data.get('guest_id', '')[:50] or ''

            fid = db.add_feedback(
                message=message,
                feedback_type=feedback_type,
                station_id=station_id,
                user_tg_id=user_id,
                username=username,
                contact=contact
            )
            self._send_json({'ok': True, 'id': fid})

            type_labels = {
                'station_issue': '⛽ Неточность по АЗС',
                'ads': '📢 Реклама / Партнёрство (B2B)',
                'suggestion': '💡 Идея / Предложение',
                'bug': '🐛 Ошибка в работе',
                'other': '💬 Обратная связь'
            }
            type_title = type_labels.get(feedback_type, '💬 Обратная связь')
            
            station_text = ''
            if station_id:
                st_name = db.get_station_name(station_id)
                station_text = f'\n⛽ <b>АЗС:</b> {st_name} (ID: {station_id})'

            user_text = ''
            if username:
                user_text = f'\n👤 <b>Пользователь:</b> @{username}'
            elif user_id:
                user_text = f'\n👤 <b>Telegram ID:</b> <code>{user_id}</code>'
            
            contact_text = f'\n📞 <b>Контакт:</b> {contact}' if contact else ''

            msg = (
                f'📩 <b>Новое обращение (#{fid})</b>\n'
                f'🏷 <b>Категория:</b> {type_title}'
                f'{station_text}'
                f'{user_text}'
                f'{contact_text}\n\n'
                f'💬 <b>Сообщение:</b>\n{message}'
            )
            threading.Thread(target=_notify_admins, args=(msg,), daemon=True).start()

        elif path == '/api/events':
            raw = self._read_body()
            if not raw:
                self._send_json({'error': 'empty body'}, 400)
                return
            try:
                payload = json.loads(raw)
            except Exception:
                self._send_json({'error': 'invalid json'}, 400)
                return

            if isinstance(payload, dict) and 'events' in payload:
                events = payload['events']
                init_data = payload.get('init_data', '')
            elif isinstance(payload, list):
                events = payload
                init_data = ''
            else:
                events = [payload]
                init_data = payload.get('init_data', '') if isinstance(payload, dict) else ''

            if not isinstance(events, list):
                events = [events]

            ip = self._get_client_ip()
            ua = self.headers.get('User-Agent', '')

            user_info = self._validate_init_data(init_data) if init_data else None
            tg_id, username = user_info if user_info else (None, '')

            for ev in events:
                if isinstance(ev, dict):
                    if tg_id and not ev.get('user_tg_id'):
                        ev['user_tg_id'] = tg_id
                    if username and not ev.get('username'):
                        ev['username'] = username

            saved_count = db.log_user_events(events, ip=ip, user_agent=ua)
            self._send_json({'ok': True, 'count': saved_count})
            return

        elif path == '/api/admin/marks':
            is_auth, admin_name = self._check_admin_auth()
            if not is_auth:
                self._send_json({'error': 'unauthorized'}, 401)
                return
            raw = self._read_body()
            if not raw:
                self._send_json({'error': 'empty body'}, 400)
                return
            try:
                data = json.loads(raw)
            except Exception:
                self._send_json({'error': 'invalid json'}, 400)
                return
            st_id = int(data.get('station_id', 0))
            fc = data.get('fuel_code', '')
            st = data.get('status', 'yes')
            if not st_id or not fc:
                self._send_json({'error': 'station_id and fuel_code required'}, 400)
                return
            lim = data.get('limit_liters')
            qc = data.get('queue_count')
            db.add_mark_v2(
                station_id=st_id,
                fuel_code=fc,
                status=st,
                user_tg_id=1,
                username=f"admin:{admin_name or 'dispatcher'}",
                mark_type='admin',
                queue_count=int(qc) if qc not in (None, '') else None,
                limit_liters=int(lim) if lim not in (None, '') else None
            )
            _invalidate_cache()
            self._send_json({'ok': True, 'message': 'Mark created'})
            return

        elif path == '/api/admin/unloading':
            is_auth, _ = self._check_admin_auth()
            if not is_auth:
                self._send_json({'error': 'unauthorized'}, 401)
                return
            raw = self._read_body()
            if not raw:
                self._send_json({'error': 'empty body'}, 400)
                return
            try:
                data = json.loads(raw)
                st_id = int(data.get('station_id', 0))
                clear = bool(data.get('clear', False))
                minutes = int(data.get('minutes', 35))
                note = data.get('note', 'Идёт слив цистерны / бензовоза')
                if clear:
                    db.set_station_unloading(st_id, minutes=0, note='')
                    # Clear unloading_until in DB
                    conn = db.get_conn()
                    conn.execute("UPDATE stations SET unloading_until = '', unloading_note = '' WHERE id = ?", (st_id,))
                    conn.commit()
                    conn.close()
                else:
                    db.set_station_unloading(st_id, minutes=minutes, note=note)
                _invalidate_cache()
                self._send_json({'ok': True})
            except Exception as e:
                self._send_json({'error': str(e)}, 500)
            return

        elif path == '/api/admin/station-closed':
            is_auth, _ = self._check_admin_auth()
            if not is_auth:
                self._send_json({'error': 'unauthorized'}, 401)
                return
            raw = self._read_body()
            try:
                data = json.loads(raw)
                st_id = int(data.get('station_id', 0))
                is_closed = int(data.get('is_closed', 0))
                closed_reason = data.get('closed_reason', '')
                reopen_date = data.get('reopen_date', '')
                db.set_station_closed(st_id, is_closed=is_closed, closed_reason=closed_reason, reopen_date=reopen_date)
                _invalidate_cache()
                self._send_json({'ok': True})
            except Exception as e:
                self._send_json({'error': str(e)}, 500)
            return

        elif path == '/api/admin/cache-clear':
            is_auth, _ = self._check_admin_auth()
            if not is_auth:
                self._send_json({'error': 'unauthorized'}, 401)
                return
            _invalidate_cache()
            self._send_json({'ok': True, 'message': 'Cache cleared and WebSocket broadcast sent'})
            return

        elif path == '/api/internal/hermes-learn':
            key = self.headers.get('X-Internal-Key', '')
            client_ip = self.client_address[0]
            if not (client_ip in ('127.0.0.1', '::1') or client_ip.startswith('172.') or key == 'c1f2119335fb922ccb4fd2e898901448ab1b587eb849106b'):
                self._send_json({'error': 'unauthorized'}, 401)
                return

            limit = 50
            raw = self._read_body()
            if raw:
                try:
                    p = json.loads(raw)
                    if 'limit' in p:
                        limit = int(p['limit'])
                except Exception:
                    pass

            try:
                from scripts.learn_from_history import run_history_learning
                stats = run_history_learning(limit=limit)
                self._send_json({'ok': True, 'stats': stats})
            except Exception as e:
                logging.error(f"Hermes learning execution failed: {e}")
                self._send_json({'ok': False, 'error': str(e)}, 500)

        else:
            self._send_json({'error': 'not found'}, 404)

    def do_PUT(self):
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path
        if path.startswith('/fuel-map/'):
            path = path[len('/fuel-map'):]

        if path.startswith('/api/admin/marks/'):
            is_auth, _ = self._check_admin_auth()
            if not is_auth:
                self._send_json({'error': 'unauthorized'}, 401)
                return
            try:
                mark_id = int(path.split('/')[4])
            except (IndexError, ValueError):
                self._send_json({'error': 'invalid mark id'}, 400)
                return

            raw = self._read_body()
            if not raw:
                self._send_json({'error': 'empty body'}, 400)
                return
            try:
                data = json.loads(raw)
                db.update_admin_mark(
                    mark_id=mark_id,
                    station_id=data.get('station_id'),
                    fuel_code=data.get('fuel_code'),
                    status=data.get('status'),
                    limit_liters=data.get('limit_liters'),
                    queue_count=data.get('queue_count'),
                    username=data.get('username')
                )
                _invalidate_cache()
                self._send_json({'ok': True, 'updated_id': mark_id})
            except Exception as e:
                self._send_json({'error': str(e)}, 500)
            return
        else:
            self._send_json({'error': 'not found'}, 404)

    def do_DELETE(self):
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path
        if path.startswith('/fuel-map/'):
            path = path[len('/fuel-map'):]

        if path.startswith('/api/admin/marks/'):
            is_auth, _ = self._check_admin_auth()
            if not is_auth:
                self._send_json({'error': 'unauthorized'}, 401)
                return
            try:
                mark_id = int(path.split('/')[4])
                db.delete_admin_mark(mark_id)
                _invalidate_cache()
                self._send_json({'ok': True, 'deleted_id': mark_id})
            except (IndexError, ValueError):
                self._send_json({'error': 'invalid mark id'}, 400)
            except Exception as e:
                self._send_json({'error': str(e)}, 500)
            return

        elif path.startswith('/api/admin/comments/'):
            is_auth, _ = self._check_admin_auth()
            if not is_auth:
                self._send_json({'error': 'unauthorized'}, 401)
                return
            try:
                comment_id = int(path.split('/')[4])
                db.delete_admin_comment(comment_id)
                self._send_json({'ok': True, 'deleted_id': comment_id})
            except (IndexError, ValueError):
                self._send_json({'error': 'invalid comment id'}, 400)
            except Exception as e:
                self._send_json({'error': str(e)}, 500)
            return
        else:
            self._send_json({'error': 'not found'}, 404)

    def log_message(self, format, *args):
        logging.info("%s - %s", self.client_address[0], format % args)

if __name__ == '__main__':
    db.init_db()
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    ws_port = 8766
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    
    ws_thread = threading.Thread(target=_start_ws_server, args=(ws_port,), daemon=True)
    ws_thread.start()

    httpd = http.server.ThreadingHTTPServer(('0.0.0.0', port), FuelHandler)
    print(f'Map server on http://0.0.0.0:{port}, WebSocket on ws://127.0.0.1:{ws_port}')
    httpd.serve_forever()
