#!/usr/bin/env python3
"""
WhatsApp Message NLP/Parser & Photo Notifier for Toplivo Yakutsk.
"""
import sys
import json
import re
import os
import urllib.request
import urllib.parse
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import db
import config

# Названия топлива и статусов для читаемых логов
FUEL_NAMES_RU = {
    '92': 'АИ-92',
    '95': 'АИ-95',
    '98': 'АИ-98',
    '100': 'АИ-100',
    'dt': 'ДТ (дизель)',
    'gas': 'Газ'
}

STATUS_NAMES_RU = {
    'yes': '🟢 Есть',
    'no': '🔴 Нет',
    'limit': '🟠 Лимит / По талонам',
    'queue': '🟡 Очередь'
}

# Синонимы брендов
BRAND_SYNONYMS = {
    'Саханефтегазсбыт': ['снгс', 'снг', 'стнгз', 'стнгс', 'саханефть', 'саханефтегазсбыт', 'саханефтегазсбыта', 'саханефтегазсбыте', 'саханефтегаз', 'сахнефть', 'сахнефти', 'сн'],
    'Туймаада-Нефть': ['тн', 'туймаада', 'туймада', 'туймаада-нефть', 'туймаданефть', 'туймаада нефть', 'туймада нефть'],
    'СибОйл': ['сибойл', 'сиб ойл', 'сиб-ойл', 'сиб', 'сибойле', 'сибойлу', 'сибола', 'сибойла', 'сибоил', 'сибоиле', 'сибоилу'],
    'Паритет': ['паритет', 'паритете'],
    'Газ': ['сахатранснефтегаз', 'стнг', 'агзс', 'газ', 'стнг газ', 'газовая'],
    'ОПТИ': ['опти', 'газпромнефть', 'гпн', 'opti'],
    'Экто-Ойл': ['экто', 'экто-ойл', 'экто ойл', 'эктоойл'],
    'ТЗК Аэропорт': ['тзк', 'тзк аэропорт', 'керосин']
}

# Синонимы локаций/улиц Якутска и улусов
LOCATION_PATTERNS = [
    (r'(203\s*мкр\w*|203\s*м/р|203\s*микрорайон\w*|на\s*203|сибойл\s*203|203\b|202\s*мкр\w*|лодочн\w*\s*станци\w*|чернышевск\w*\s*1\s*я|чернышевск\w*\s*1-я|1-я\s*чернышевск\w*|1\s*я\s*чернышевск\w*)', ['чернышевского 1 я', '203']),
    (r'(илбэ[нҥг]+[эеа-я]*|илбенг\w*|илбэн\w*)', ['илбенг', 'илбэҥэ', 'илбенге']),
    (r'(бердигест\w*|бэрдьигэс\w*)', ['бердигест']),
    (r'(верхневилюйск\w*|в\.?\s*вилюйск\w*|верхне\s*вилюйск\w*|үөһээ\s*бүлүү\w*)', ['верхневилюйск']),
    (r'(вилюйск\w*|вил\b|вт\b|вилюй\w*|бүлүү\w*)', ['вилюйск']),
    (r'(покровск\w*|пт\b)', ['покровск']),
    (r'(автодорожн\w*|авторож\w*|михаила\s*николаев\w*|михаила\s*ник\w*|мих\s*ник\w*|м\.?\s*ник\w*|николаева\b|авт\b)', ['автодорожн', 'михаила николаева', 'николаева']),
    (r'(окружн\w*|объездн\w*)', ['окружное', 'объездное', 'окружное шоссе']),
    (r'(сергелях\w*)', ['сергелях', 'сергеляхское']),
    (r'(дежнев\w*|дежнёв\w*)', ['дежнев', 'дежнёва']),
    (r'(дзержинск\w*|дз\b)', ['дзержинск']),
    (r'(50\s*лет\s*октябр\w*|автострад\w*|ураса\w*|ураһа\w*)', ['50 лет октября', 'автострад']),
    (r'(50\s*лет\s*советск\w*|50\s*лет\s*са\b|советск\w*\s*арми\w*|соварми\w*|сов\s*арми\w*|гр[еэ]с\w*|даркылах\w*)', ['50 лет советской армии']),
    (r'(хатын\W*юр\w*|хюр\w*|хатынг\w*|хатыҥ\w*)', ['хатын-юрях', 'хатын']),
    (r'(тамар\w*)', ['дзержинск', 'дзержинского']),
    (r'(намск\w*|намцы|намцы\w*|нам\b)', ['намск', 'намцы']),
    (r'(калвиц\w*)', ['калвиц']),
    (r'(лерин\w*|лермонтов\w*)', ['лермонтов']),
    (r'(петра\s*алексеев\w*|п\.?\s*алексеев\w*)', ['петра алексеева', 'алексеев']),
    (r'(чернышевск\w*)', ['чернышевск']),
    (r'(жатай\w*)', ['жатай']),
    (r'(марх\w*)', ['марх']),
    (r'(бестях\w*|н\.?\s*бестях\w*|нижний\s*бестях\w*)', ['бестях']),
    (r'(майя\b|майинск\w*)', ['майя']),
    (r'(чурапч\w*|чурапчы\w*)', ['чурапч']),
    (r'(труда\b|труд\w*)', ['труда']),
    (r'(кулаковск\w*)', ['кулаковск']),
    (r'(очиченко\w*)', ['очиченко']),
    (r'(столичк\w*|портовск\w*)', ['50 лет советской армии', 'автострада 50 лет октября']),
    (r'(маганск\w*|маган\b)', ['маган']),
    (r'(боровгон\w*|борогон\w*|бороҕон\w*)', ['борогон', 'боро']),
    (r'(хандыг\w*)', ['хандыг']),
    (r'(гимеин\w*)', ['михаила николаева', 'лермонтов']),
    (r'(птичк\w*|птицефабрик\w*)', ['птицефабрика', 'покровск']),
    (r'(кысыл\W*сыр\w*)', ['кысыл-сыр', 'кысыл сыр']),
    (r'(амг\w*|амгинск\w*|амма\b)', ['амга', 'амгинск']),
    (r'(улахан\W*ан\w*)', ['улахан-ан', 'улахан ан']),
    (r'(диринг\w*|дириҥ\w*)', ['диринг', 'дириҥ']),
    (r'(мындаб\w*)', ['мындаба']),
    (r'(томмот\w*)', ['томмот']),
    (r'(алдан\w*)', ['алдан']),
    (r'(нерюнгр\w*)', ['нерюнгр']),
    (r'(мирн\w*|мирнинск\w*)', ['мирн', 'мирный']),
    (r'(нюрб\w*|ньурб\w*)', ['нюрб', 'ньурб']),
    (r'(сунтар\w*|сунтаар\w*)', ['сунтар']),
    (r'(олекминск\w*|олёкминск\w*|өлүөхүм\w*)', ['олекминск', 'олёкминск']),
    (r'(ытык\W*кю[её]л\w*|таттинск\w*|татта\b)', ['ытык-кюель', 'татта']),
]

def send_telegram_photo(photo_path, caption):
    """Отправка фото админам в Telegram через Bot API."""
    bot_token = config.BOT_TOKEN
    admin_ids = config.ADMIN_IDS

    if not bot_token or not admin_ids:
        print("[TG Notify] BOT_TOKEN or ADMIN_IDS not set, skipping TG notify.")
        return

    url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"

    # Формируем multipart/form-data
    boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
    
    with open(photo_path, 'rb') as f:
        file_bytes = f.read()

    filename = os.path.basename(photo_path)

    for admin_id in admin_ids:
        try:
            body = []
            body.append(f'--{boundary}'.encode())
            body.append(f'Content-Disposition: form-data; name="chat_id"'.encode())
            body.append(''.encode())
            body.append(str(admin_id).encode())

            body.append(f'--{boundary}'.encode())
            body.append(f'Content-Disposition: form-data; name="caption"'.encode())
            body.append(''.encode())
            body.append(caption.encode('utf-8'))

            body.append(f'--{boundary}'.encode())
            body.append(f'Content-Disposition: form-data; name="parse_mode"'.encode())
            body.append(''.encode())
            body.append(b'HTML')

            body.append(f'--{boundary}'.encode())
            body.append(f'Content-Disposition: form-data; name="photo"; filename="{filename}"'.encode())
            body.append(b'Content-Type: image/jpeg')
            body.append(''.encode())
            body.append(file_bytes)
            body.append(f'--{boundary}--'.encode())
            body.append(''.encode())

            req_body = b'\r\n'.join(body)

            req = urllib.request.Request(url, data=req_body)
            req.add_header('Content-Type', f'multipart/form-data; boundary={boundary}')
            with urllib.request.urlopen(req, timeout=10) as resp:
                print(f"[TG Notify] Photo sent to admin {admin_id}, status {resp.status}")
        except Exception as e:
            print(f"[TG Notify Error] Failed to send photo to {admin_id}: {e}", file=sys.stderr)

RECENT_QUESTIONS_FILE = os.path.join(BASE_DIR, "data", "recent_questions_buffer.json")

def get_recent_questions():
    """Загружает недавние вопросы водителей за последние 10 минут."""
    if not os.path.exists(RECENT_QUESTIONS_FILE):
        return []
    try:
        with open(RECENT_QUESTIONS_FILE, "r", encoding="utf-8") as f:
            items = json.load(f)
            now = datetime.now().timestamp()
            # Оставляем только вопросы свежее 10 минут (600 сек)
            return [it for it in items if now - it.get("ts", 0) < 600]
    except Exception:
        return []

def save_recent_question(text, station_id=None, station_name=None):
    """Сохраняет вопрос в буфер ожидания ответа."""
    if not text or len(text.strip()) < 5:
        return
    items = get_recent_questions()
    items.append({
        "text": text.strip(),
        "station_id": station_id,
        "station_name": station_name,
        "ts": datetime.now().timestamp()
    })
    # Храним не более 20 последних
    items = items[-20:]
    try:
        os.makedirs(os.path.dirname(RECENT_QUESTIONS_FILE), exist_ok=True)
        with open(RECENT_QUESTIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[Buffer Error] Failed to save question: {e}", file=sys.stderr)

def is_pure_question(text: str) -> bool:
    """Определяет, является ли сообщение вопросом без фактической информации о наличии."""
    if not text:
        return False
    t = text.lower().strip()

    # 1. Знаки вопроса
    has_q_mark = any(q in t for q in ['?', '⁇', '¿'])

    # 2. Вопросительные слова и обороты (русский и якутский)
    has_q_word = bool(re.search(
        r'\b(как|где|куда|есть ли|ханна|баар да|баара дуу|баар ду|подскажите|узнать|'
        r'работает ли|до скольки|со скольки|почем|почём|кто знает|кто-нибудь знает|'
        r'подскажет|че по|что по|что там|как там|со скольких|было ли|будет ли|'
        r'кто был|кто видел|продают ли|отпускают ли|льют ли|заправляют ли|'
        r'где продают|где льют|где заправляют|где есть|где свободно|где 95|где 92|где газ|'
        r'свободно ли|большая ли|хайдах|тоҕо|көрдөһөбүн)\b',
        t
    ))

    if not (has_q_mark or has_q_word):
        return False

    # 3. Проверяем, есть ли отдельное утвердительное предложение с фактом
    # (например: "На Красильникова 92 залил. А на 51 95 есть?")
    sentences = re.split(r'[.!?\n]+', t)
    for s in sentences:
        s = s.strip()
        if not s:
            continue
        is_sub_q = any(q in s for q in ['?', '⁇', '¿']) or bool(re.search(
            r'\b(как|где|куда|есть ли|ханна|баар да|баар ду|подскажите|кто знает|че по|что по|что там|работает ли|продают ли|льют ли|заправляют ли)\b', s
        ))
        if not is_sub_q and re.search(r'\b(залил|заправил|стою|стоят\s+\d+|нету|суох|свободно|закрыто|кончился|бүппүт|наливают\s+до|отпускают\s+по)\b', s):
            return False

    return True

def is_news_or_spam(text: str) -> tuple[bool, str]:
    """
    Определяет, является ли текст новостной статьёй, пресс-релизом, спамом
    или общей сводкой, не относящейся к отзыву по конкретной АЗС.
    """
    if not text:
        return False, ""
    t = text.lower().strip()

    # 1. Реклама, вакансии, найм и спекуляция
    if re.search(r'^\s*реклама\b|деликатес-ас|чистка печки|вашему бизнесу нужна|куплю место в очереди|продам бенз\b|требует[ся|ся]|ваканси[я|и]|грузчик|подработк|сда[её]тся\s+квартир|займ\b|кредит\b|звонить\s+по\s+номеру', t):
        return True, "реклама / спам / вакансии"

    # 2. Новости, политика, статьи, пресс-релизы (ОНФ, прокуратура, форумы, скандалы)
    if re.search(r'онф|народн\w*\s+фронт|генпрокуратур|прокуратур|сопредседатель|лаптев\s+алексей|аварийная дорога|голодомор|совещани\w*\s+с\s+директор|скандал\w*\s+в\s+среднеколым|чиновник\w*\s+с\s+министерств|указ\w*\s+президент|восточн\w*\s+экономическ\w*\s+форум|старт\s+к\s+вершинам|следов\s+бурог|детей\s+сотрудников|приз\w*\s+зрительских|усть-\s*куйгинская нефтебаза|выгрузили в нижнем бестяхе|выгружено.*тонн топлива|барж\w*|нефтяной и газовой промышленности|сво,\s*бюджетн|чорбойдор', t):
        return True, "новостная статья / политика / пресс-релиз"

    # 3. Репосты СМИ
    if re.search(r'#дляsakhaday|max\.ru/sakhaday|#новости', t) and len(text) > 150:
        return True, "репост СМИ"

    # 4. Общегородские сводки (не привязаны к конкретной АЗС)
    if re.search(r'памятка водителям|отпуск топлива на азс:\s*данные на|обстановка на \d\d:\d\d|по состоянию на \d\d:\d\d|по состоянию на утро|оперативная информация по отпуску|большинство сетей приостановили', t):
        return True, "общегородская сводка"

    # 5. Сводка сразу по нескольким сетям/станциям (>350 символов)
    if len(text) > 350:
        brand_count = sum(1 for b in ['снгс', 'туймаад', 'сибойл', 'паритет', 'экто'] if b in t)
        if brand_count >= 2:
            return True, "мульти-станционная сводка"

    # 6. Ссылки на каналы, соцсети и блогерские посты
    if re.search(r'подпишись|подписывайтесь|сообщи свою новость|треш\s*-\s*контент|перчики\s*🌶|секс-террорист', t):
        return True, "блогерский пост / призыв к подписке"

    if re.search(r'https?://(?:t\.me|vk\.com|max\.ru)/[^\s]+', t):
        return True, "промо-ссылки на соцсети/каналы"

    return False, ""

def clean_driver_comment(raw_text: str) -> str:
    """
    Очищает текст комментария от артефактов парсера, цитирования станций и промо-хвостов.
    """
    if not raw_text:
        return ""
    t = raw_text.strip()

    # 1. Удаляем промо-подписи и ссылки
    t = re.sub(r'📢\s*Перешлите тому[^\n]*', '', t, flags=re.IGNORECASE)
    t = re.sub(r'Наш ИИ читает чаты водителей 24/7[^\n]*', '', t, flags=re.IGNORECASE)
    t = re.sub(r'⛽\s*(?:Проверить|Карта)[^\n]*', '', t, flags=re.IGNORECASE)
    t = re.sub(r'https?://t\.me/toplivo14[^\s]*', '', t, flags=re.IGNORECASE)

    # 2. Удаляем маркеры локации в конце строки (📍 ОПТИ · улица Маганский перекрёсток, 1)
    t = re.sub(r'📍\s*[^·\n]+·[^\n]+$', '', t, flags=re.MULTILINE)
    t = re.sub(r'📍\s*[^\n]+$', '', t, flags=re.MULTILINE)

    # 3. Удаляем префиксы '💬:', ':', '💬 Из чата водителей:'
    t = re.sub(r'^(?:💬\s*(?:Из чата водителей:)?\s*)?(?::\s*)?', '', t, flags=re.IGNORECASE)

    # 4. Снимаем внешние кавычки «...» или "..." если текст ими обрамлен
    t = t.strip()
    if (t.startswith('«') and t.endswith('»')) or (t.startswith('"') and t.endswith('"')):
        t = t[1:-1].strip()

    # Убираем повторные пустые строки
    t = re.sub(r'\n{3,}', '\n\n', t)
    return t.strip()

HERMES_SYNONYMS_FILE = os.path.join(BASE_DIR, "data", "hermes_synonyms.json")
_cached_synonyms = None
_synonyms_mtime = 0

def get_hermes_synonyms():
    global _cached_synonyms, _synonyms_mtime
    if not os.path.exists(HERMES_SYNONYMS_FILE):
        return {}
    try:
        mtime = os.path.getmtime(HERMES_SYNONYMS_FILE)
        if _cached_synonyms is None or mtime > _synonyms_mtime:
            with open(HERMES_SYNONYMS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                _cached_synonyms = data.get("synonyms", {})
                _synonyms_mtime = mtime
        return _cached_synonyms
    except Exception:
        return {}

def _match_station_internal(text, stations, sender="", push_name=""):
    """Внутренний поиск подходящей АЗС по тексту (словарь Hermes + регулярки)."""
    if not text:
        return None
    text_lower = text.lower()

    # 1. Проверяем упоминание брендов и жидкого моторного топлива
    has_liquid_fuel = bool(re.search(r'\b(?:92|95|98|100|дт|дизел\w*|солярк\w*|бензин\w*)\b', text_lower))

    matched_brands = []
    for brand, b_syns in BRAND_SYNONYMS.items():
        for syn in b_syns:
            if re.search(rf'(?:\b|_){re.escape(syn)}(?:\b|_)', text_lower):
                matched_brands.append(brand)
                break

    # Учитываем бренд из источника сообщения (официальные каналы)
    sender_lower = (sender or "").lower()
    push_lower = (push_name or "").lower()
    if 'ao_sngs2' in sender_lower or 'саханефтегаз' in push_lower or 'снгс' in push_lower:
        if 'Саханефтегазсбыт' not in matched_brands:
            matched_brands.append('Саханефтегазсбыт')
    elif 'сибойл' in push_lower or 'siboil' in sender_lower:
        if 'СибОйл' not in matched_brands:
            matched_brands.append('СибОйл')
    elif 'туймаада' in push_lower or 'tuimaada' in sender_lower:
        if 'Туймаада-Нефть' not in matched_brands:
            matched_brands.append('Туймаада-Нефть')

    # Если в сообщении фигурирует СТНГ / СНГ / Сахатранснефтегаз, но речь идёт о бензине/дизеле (92/95/98/ДТ),
    # водители имеют в виду заправку Саханефтегазсбыт (СНГС), а не газовую АГЗС СТНГ
    if has_liquid_fuel and ('Газ' in matched_brands or 'Саханефтегазсбыт' in matched_brands):
        if 'Саханефтегазсбыт' not in matched_brands:
            matched_brands.append('Саханефтегазсбыт')
        if 'Газ' in matched_brands and not re.search(r'\b(?:газ|пропан|метан|агзс)\b', text_lower):
            matched_brands.remove('Газ')

    # 2. Проверяем обученные синонимы Hermes (сортируем по убыванию длины)
    syns = get_hermes_synonyms()
    if syns:
        for phrase in sorted(syns.keys(), key=lambda p: len(p), reverse=True):
            phrase_words = phrase.split()
            if len(phrase_words) > 1:
                phrase_regex = r'(?:\b|_)' + r'[\s,.-]+'.join(re.escape(w) for w in phrase_words) + r'(?:\b|_)'
            else:
                phrase_regex = rf'(?:\b|_){re.escape(phrase)}(?:\b|_)'
            if re.search(phrase_regex, text_lower):
                info = syns[phrase]
                st_id = info.get("station_id")
                if st_id:
                    st = next((s for s in stations if s.get("id") == st_id), None)
                    if st:
                        # Если в тексте явно указан другой бренд (например 'сибойл' при синониме СНГС) — не форсируем синоним
                        if matched_brands and st.get('brand') not in matched_brands:
                            pass
                        else:
                            return st
                target_addr = (info.get("target_address") or "").lower()
                target_brand = info.get("brand") or ""
                if target_addr:
                    for s in stations:
                        addr = (s.get("address") or "").lower()
                        brand = s.get("brand") or ""
                        if target_addr in addr:
                            if matched_brands:
                                if brand in matched_brands:
                                    return s
                            elif not target_brand or target_brand == brand:
                                return s

    # Разделение: город Вилюйск (населенный пункт) vs Вилюйский тракт в Якутске (улица / шоссе)
    pat_city_vilyuysk = r'\b(?:в\s+вилюйске|вилюйск\b|вилюйске|вилюйску|г\.?\s*вилюйск|бүлүү\b|бүлүүгэ)\b'
    pat_tract_vilyuysk = r'\b(?:вилюйск(?:ий|ом|ого|ому|им|ая|ую|их)?\s*(?:тракт\w*|тр\b|шоссе)|вилюйк[еауой]|на\s+вилюйк[еау]|на\s+вилюйском|вил\s*тр\b|вт\b)\b'

    is_city_vilyuysk = bool(re.search(pat_city_vilyuysk, text_lower))
    is_tract_vilyuysk = bool(re.search(pat_tract_vilyuysk, text_lower)) and not is_city_vilyuysk

    matched_location_keys = []
    for regex_pat, loc_keys in LOCATION_PATTERNS:
        if 'вилюйск' in loc_keys:
            if is_city_vilyuysk:
                matched_location_keys.extend(['г. вилюйск', 'вилюйск (город)'])
                continue
            elif is_tract_vilyuysk:
                matched_location_keys.extend(['вилюйский тракт', 'вилюйский тр'])
                continue
            else:
                continue
        if re.search(regex_pat, text_lower):
            matched_location_keys.extend(loc_keys)

    num_match = re.search(r'(?:азс|мазс|казс|№|номер)\s*[-–—№]?\s*(\d+)', text_lower)

    # Если не указана локация (улица/ориентир/тракт) и не указан номер АЗС — это общий диалог/рассуждение о бренде, не привязанный к станции
    if not matched_location_keys and not num_match and not is_city_vilyuysk and not is_tract_vilyuysk:
        return None

    best_station = None
    best_score = 0

    for st in stations:
        score = 0
        st_name_lower = (st.get('name') or '').lower()
        st_addr_lower = (st.get('address') or '').lower()
        st_brand = st.get('brand') or ''
        st_city = (st.get('city') or 'Якутск').lower()

        # Разграничение оценок: город Вилюйск vs Вилюйский тракт
        if is_city_vilyuysk:
            if 'вилюйск' in st_city or 'г.вилюйск' in st_name_lower or 'г. вилюйск' in st_name_lower or 'г. вилюйск' in st_addr_lower:
                score += 25
            elif 'якутск' in st_city:
                score -= 15
        elif is_tract_vilyuysk:
            if 'якутск' in st_city and ('вилюйск' in st_addr_lower or 'вилюйск' in st_name_lower):
                score += 20
            elif 'вилюйск' in st_city:
                score -= 15
        else:
            if 'якутск' in st_city:
                score += 2

        # Если в тексте не упоминается газ/пропан/агзс, отдаём приоритет полноценным АЗС (бензин/дизель) над АГЗС
        if st_brand == 'Газ' and not re.search(r'\b(?:газ|пропан|метан|агзс)\b', text_lower):
            score -= 5
        elif st_brand != 'Газ' and not re.search(r'\b(?:газ|пропан|метан|агзс)\b', text_lower):
            score += 3

        if matched_brands:
            if st_brand in matched_brands:
                score += 10
            else:
                score -= 15

        loc_matched = False
        for loc in matched_location_keys:
            if loc in st_name_lower or loc in st_addr_lower:
                score += 15
                loc_matched = True
                break

        if matched_location_keys and not loc_matched:
            score -= 5

        if num_match:
            num = num_match.group(1)
            if f'№ {num}' in st['name'] or f'№{num}' in st['name'] or f' {num} ' in st['name']:
                score += 20
                # Проверяем совпадение населенного пункта / улицы из адреса улусных АЗС
                for token in re.findall(r'[а-яёА-ЯЁ]{4,}', st_addr_lower):
                    if token in text_lower:
                        score += 15
                        break

        # Приоритет АЗС №1 СНГС (528) на проспекте Михаила Николаева по умолчанию
        if st['id'] == 528 and any(k in matched_location_keys for k in ['михаила николаева', 'автодорожн']) and not matched_brands:
            score += 5

        if score > best_score and score >= 17:
            best_score = score
            best_station = st

    return best_station

def extract_geotag(text):
    """Извлекает геометку из текста вида '📍 СНГС · улица 50 лет Советской Армии, 49Б'."""
    if not text or '📍' not in text:
        return None
    m = re.search(r'📍\s*([^·\n\r]+?)(?:\s*·\s*([^\n\r]+))?(?:$|\n|\r)', text)
    if m:
        brand = m.group(1).strip() if m.group(1) else ""
        addr = m.group(2).strip() if m.group(2) else ""
        return {"raw": m.group(0).strip(), "brand": brand, "address": addr}
    return None

def match_station_by_geotag(geo, stations):
    if not geo:
        return None
    addr = geo.get("address", "").strip().lower()
    brand = geo.get("brand", "").strip()
    
    # 1. Поиск по части адреса станции (номера дома / улицы)
    if addr:
        clean_addr = re.sub(r'\b(улица|ул\.?|г\.?\s*якутск,?)\b', '', addr).strip()
        for s in stations:
            s_addr = (s.get("address") or "").lower()
            if clean_addr and clean_addr in s_addr:
                return s
    # 2. Поиск через внутренний матчер
    full = f"{brand} {addr}".strip()
    return _match_station_internal(full, stations)

def find_matching_station(text, stations, sender="", push_name=""):
    """Находит подходящую АЗС по тексту сообщения с автономным учетом геометок (📍) и контекста диалогов."""
    if not text:
        return None

    geo = extract_geotag(text)
    geo_st = match_station_by_geotag(geo, stations)

    # Текст без строки геометки для контентного анализа
    text_no_geo = re.sub(r'📍[^\n\r]+', '', text).strip()

    if geo_st:
        content_st = _match_station_internal(text_no_geo, stations, sender=sender, push_name=push_name)
        if content_st and content_st['id'] != geo_st['id']:
            c_addr = (content_st.get('address') or '').lower()
            g_addr = (geo_st.get('address') or '').lower()
            same_street = any(k in c_addr and k in g_addr for k in ['советск', 'вилюйск', 'хатын', 'дзержинск', 'автодор', 'николаев', 'труда', 'жатай', 'покровск', 'октябр', 'богдан'])
            if same_street:
                return geo_st

            syns = get_hermes_synonyms()
            text_lower = text_no_geo.lower()
            has_explicit_hermes = any(re.search(rf'(?:\b|_){re.escape(k)}(?:\b|_)', text_lower) for k, v in syns.items() if v.get('station_id') == content_st['id'])
            if has_explicit_hermes:
                return content_st
        return geo_st

    lines = [line.strip() for line in text_no_geo.split('\n') if line.strip()]
    if len(lines) >= 2:
        q_lines = [l for l in lines if '?' in l or is_pure_question(l)]
        ans_lines = [l for l in lines if '?' not in l and not is_pure_question(l)]

        q_st = _match_station_internal('\n'.join(q_lines), stations, sender=sender, push_name=push_name) if q_lines else None
        ans_st = _match_station_internal('\n'.join(ans_lines), stations, sender=sender, push_name=push_name) if ans_lines else None

        # В диалогах вопрос задает основную целевую АЗС, ответ описывает ситуацию на ней
        if q_st:
            return q_st
        if ans_st:
            return ans_st

    return _match_station_internal(text_no_geo, stations, sender=sender, push_name=push_name)

def extract_payment_tags(text):
    """Извлекает теги способов оплаты из текста отзыва."""
    text_lower = text.lower()
    tags = []
    if re.search(r'куар\w*|квар\w*|qr\b|по\s+приложени\w*|через\s+приложени\w*|тн\s+азс\b|в\s+приложени\w*', text_lower):
        tags.append('📱 QR / Приложение')
    if re.search(r'топл\w*\s*карт\w*|по\s+топливной|госкарт\w*|пластик\w*\s+юрлиц|безнал\s+юрлиц', text_lower):
        tags.append('💳 Топливная карта')
    if re.search(r'наличк\w*|\bнал\b|через\s+касс\w*|по\s+карт\w*|безнал\b|терминал\w*|сбер\b|банковск\w*', text_lower):
        if '💳 Топливная карта' not in tags and '📱 QR / Приложение' not in tags:
            tags.append('💵 Нал / Банковская карта')
    return tags

def extract_fuel_prices(text: str) -> dict[str, float]:
    """Извлекает цены на топливо из текста (например: 'по 36', 'газ 36 руб', '95 по 78.50')."""
    if not text:
        return {}
    text_lower = text.lower()
    prices = {}
    
    # Специфичный поиск цены газа (типичный диапазон 20 - 55 руб)
    gas_match = re.search(r'(?:газ\w*|пропан\w*|агзс)\s*(?:по|цена|стоимость|стоит)?\s*(\d{2}(?:[.,]\d{1,2})?)\s*(?:руб\w*|р\b|рб|\bза\s*л)?|(?:по|цена|стоимость)\s*(\d{2}(?:[.,]\d{1,2})?)\s*(?:руб\w*|р\b)?\s*(?:на\s+газ|за\s+газ)', text_lower)
    if gas_match:
        val = (gas_match.group(1) or gas_match.group(2)).replace(',', '.')
        try:
            p = float(val)
            if 20.0 <= p <= 65.0:
                prices['gas'] = p
        except ValueError:
            pass

    # Поиск цен на бензин / дизель (типичный диапазон 45 - 120 руб)
    for fc, pat in [('92', r'92'), ('95', r'95'), ('98', r'98'), ('100', r'100'), ('dt', r'(?:дт|дизел\w*|соляр\w*)')]:
        m = re.search(rf'{pat}\s*(?:по|цена|стоимость|стоит)?\s*(\d{{2,3}}(?:[.,]\d{{1,2}})?)\s*(?:руб\w*|р\b|рб|\bза\s*л)?|(?:по|цена|стоимость)\s*(\d{{2,3}}(?:[.,]\d{{1,2}})?)\s*(?:руб\w*|р\b)?\s*(?:на|за)?\s*{pat}', text_lower)
        if m:
            val = (m.group(1) or m.group(2)).replace(',', '.')
            try:
                p = float(val)
                if 45.0 <= p <= 130.0:
                    prices[fc] = p
            except ValueError:
                pass
                
    # Если просто сказано "по 36" и в тексте или на АГЗС упоминается газ
    if 'gas' not in prices:
        m = re.search(r'(?:по|цена|стоимость)\s*(\d{2}(?:[.,]\d{1,2})?)\b', text_lower)
        if m and re.search(r'\b(?:газ|пропан|агзс)\b', text_lower):
            try:
                p = float(m.group(1).replace(',', '.'))
                if 20.0 <= p <= 65.0:
                    prices['gas'] = p
            except ValueError:
                pass

    return prices

def parse_fuel_statuses(text, reply_text=""):
    """Определяет статус топлива из текста (с учетом контекста ответа/reply)."""
    text_lower = text.lower()
    reply_lower = (reply_text or "").lower()
    results = {}
    queue_count = None

    # Вопросительные частицы (включая якутский: ду, дуо, баар ду, хайдах, эбитэ буолуо, хас эрэ)
    is_question = bool(re.search(r'\?|подскажите|как там|есть ли|кто знает|че там|что там|как очередь|\bду\b|\bдуо\b|баар\s*ду|хайдах\b|тоҕо\b|баар\s*эбитэ|хас\s*масыына|көрдөһөбүн', text_lower))

    # 1. Поиск точного количества машин
    q_match = re.search(r'очеред[ьи]\s*(?:машин\s*|авто\s*)?(\d+)|уочарат\s*(\d+)|(\d+)\s*(?:машин|масыына|авто|тачек)', text_lower)
    if q_match:
        try:
            val = q_match.group(1) or q_match.group(2) or q_match.group(3)
            queue_count = int(val)
        except ValueError:
            pass

    # 2. Поиск времени ожидания в минутах / часах
    time_min_match = re.search(r'(?:сто[яи][лмь]|просто[яи][лмь]|уочаракка\s*турдум|ждал[иа]?)\s*(?:около|примерно|мин|минут)?\s*(\d+)\s*(?:мин|минут|мүнүүтэ)', text_lower)
    if not time_min_match:
        time_min_match = re.search(r'(\d+)\s*(?:мин|минут|мүнүүтэ)\s*(?:сто[яи][лмь]|стояли|уочарат|очередь|турдум)', text_lower)
    
    if time_min_match and queue_count is None:
        try:
            mins = int(time_min_match.group(1))
            # Расчёт: 1 машина ~ 2-3 минуты
            queue_count = max(1, min(40, round(mins / 2.5)))
        except ValueError:
            pass
    elif re.search(r'(полчаса|жарым\s*чаас|30\s*минут)', text_lower) and queue_count is None:
        queue_count = 12
    elif re.search(r'(час\s*стояли|чаас\s*турдум|более\s*часа|час\s*уже|1\s*час)', text_lower) and queue_count is None:
        queue_count = 20

    # 3. Качественные описания очередей на русском и якутском
    if queue_count is None:
        if re.search(r'(большая очередь|пробка|много машин|очередь огромная|хвост\b|улахан уочарат|элбэх масыына|уочарат элбэх|(?:очередь|пробка|хвост|тянется|уочарат)\s*(?:на\s*)?\d*\s*километр\w*|до\s*перекрестк\w*|с\s*остановк\w*|на\s*дорог\w*|затором)', text_lower):
            queue_count = 15
        elif re.search(r'(мало машин|быстро идет|небольшая очередь|аҕыйах масыына|түргэнник|кыра уочарат|очередь кыра|пару машин|2-3 машины|1-2 машины)', text_lower):
            queue_count = 2
        elif re.search(r'(без очереди|очереди нет|нет очереди|нет уочарат|свободно|пусто|народу ноль|уочарат суох|кураанах|суох уочарат|сразу к колонке|заехал и залил|бы[hһ]а\s*бардылар|үчүгэйдик\s*бара\s*турар)', text_lower):
            queue_count = 0

    # 4. Если сообщение является вопросом (и нет ответа reply_text), не возвращаем статусы топлива
    if is_pure_question(text) and not reply_text:
        return results, queue_count

    fuel_tokens = {
        '92': [r'\b92\b', r'аи-?92', r'регуляр', r'тохсус\s*икки'],
        '95': [r'\b95\b', r'аи-?95', r'премиум', r'тохсус\s*биэс'],
        '98': [r'\b98\b', r'аи-?98', r'тохсус\s*аҕыс'],
        '100': [r'\b100\b', r'аи-?100', r'сотка', r'сүүс'],
        'dt': [r'\bдт\b', r'д/т', r'дизел\w*', r'солярк\w*', r'соляр\w*', r'дизель'],
        'gas': [r'\bгаз\b', r'пропан', r'метан', r'сжиженный газ', r'\bагзс\b', r'гаас\b']
    }

    # Регулярки с учетом якутского языка, лимитов в литрах, заправки по талонам, безналу и юрлицам
    re_limit = (
        r'(?<!без\s)(?<!нет\s)(?<!не\s)лимит\b|по\s*\d+\s*л(?:итр\w*)?|до\s*\d+\s*л(?:итр\w*)?|'
        r'не\s*более\s*\d+\s*л|не\s*больше\s*\d+\s*л|'
        r'по\s+приложени\w*|через\s+приложени\w*|приложени\w*|'
        r'по\s+талон\w*|талон\w*|талонунан|талоннарынан|купон\w*|'
        r'по\s+карт\w*|по\s+топливной|(?<!без\s)(?<!нет\s)(?<!не\s)ограничени\w*|норма\b|лимитинэн|'
        r'юрлиц\w*|юрик\w*|для\s+юрик\w*|только\s+юр\w*|юр\s*лиц\w*|'
        r'по\s+безнал\w*|только\s+безнал|безнал\w*|'
        r'организаци\w*|предприяти\w*|по\s+договор\w*|по\s+контракт\w*|'
        r'канистр\w*\s*(?:не\s*заправл\w*|не\s*налива\w*|не\s*отпуска\w*|куппаттар)|'
        r'только\s+в\s+бак|эрэ\s+бакка|в\s+канистр\w*\s*нет'
    )
    re_no = r'\bнет\b|\bнету\b|\bсуох\b|бүппүт|бүттэ|кончил\w*|закончил\w*|\bслив\b|корова\s*кута\s*турар|корова\s*турар|корова\s*слива\w*|не отпуска\w*|не дают\b|биэрбэттэр|закрыт\w*|сабыллыбыт|сухо\b|алдьаммыт|испэт|акведук'
    re_yes = r'\bесть\b|\bбаар\b|биэрэллэр|аҕаллылар|в наличии|появил\w*|завезли|привезли|свободно|без\s+очеред\w*|очеред[ьи]\s+нет|нет\s+очеред\w*|уочарат\s+суох|суох\s+уочарат|нет\s+уочарат\w*|по\s+\d+(?:[.,]\d+)?\s*(?:руб\w*|\bр\b|\bрб\b)?|цена\s*\d+|без\s+ограничени\w*|без\s+лимит\w*|лимит\w*\s+нет|нет\s+лимит\w*|отпуска\w*|дают\b|заправл\w*|залива\w*|кутал\w*|прода\w*|нал\s+безнал|атыылыыллар|онно\s*эрэ\s*баар|манна\s*баар'

    # Фразы отсутствия очередей ("очереди нет", "уочарат суох") и лимитов не должны триггерить отсутствие топлива
    re_queue_limit_no = (
        r'(?:очеред\w*|уочарат\w*|пробк\w*|лимит\w*|ограничен\w*)\s+(?:нет\b|нету\b|суох\b)|'
        r'(?:нет\b|нету\b|суох\b|без\b)\s+(?:очеред\w*|уочарат\w*|пробк\w*|лимит\w*|ограничен\w*|проблем\w*)'
    )
    text_for_no = re.sub(re_queue_limit_no, ' ', text_lower)

    # Фразы "без ограничений" не должны триггерить лимит
    re_no_limit_phrases = r'без\s+ограничени\w*|без\s+лимит\w*|нет\s+лимит\w*|лимит\w*\s+нет|без\s+ограничения|не\s+ограничен\w*'
    has_no_limit_phrase = bool(re.search(re_no_limit_phrases, text_lower))
    text_for_limit = re.sub(re_no_limit_phrases, ' ', text_lower)

    # Извлечение объема лимита в литрах
    limit_liters = None
    liters_match = re.search(r'(?:лимит|до|по|не\s*более|не\s*больше)\s*(\d+)\s*(?:л\b|литр\w*|л\.)|(\d+)\s*(?:л\b|литр\w*)\s*(?:эрэ|лимит|в\s*бак)', text_lower)
    if liters_match and not has_no_limit_phrase:
        val = liters_match.group(1) or liters_match.group(2)
        try:
            limit_liters = int(val)
        except ValueError:
            limit_liters = None

    has_limit_global = bool(re.search(re_limit, text_for_limit))
    has_no_global = bool(re.search(re_no, text_for_no))
    has_yes_global = bool(re.search(re_yes, text_lower) or has_no_limit_phrase)

    # Если текст содержит цитату вопроса и ответ (например: "— 95 есть нет кто знает? \n— Там нет 95"),
    # отделяем ответ от вопроса для точного определения фактического статуса
    effective_text = text_lower
    parts = re.split(r'\?|;|\n|—|–', text_lower)
    parts = [p.strip() for p in parts if p.strip()]
    if len(parts) > 1:
        # Ищем часть, содержащую утвердительный или отрицательный ответ (исключая вопросительные фразы)
        answer_parts = [
            p for p in parts 
            if re.search(rf'{re_no}|{re_yes}|{re_limit}', p) and 
               not re.search(r'кто\s*знает|кто\s*нибудь\s*знает|подскажите|как\s*там|есть\s*нет|\bду\b|\bдуо\b|баар\s*ду', p)
        ]
        if answer_parts:
            effective_text = answer_parts[-1]

    effective_text_for_no = re.sub(re_queue_limit_no, ' ', effective_text)
    has_limit_answer = bool(re.search(re_limit, effective_text))
    has_no_answer = bool(re.search(re_no, effective_text_for_no))
    has_yes_answer = bool(re.search(re_yes, effective_text))

    for fuel_code, patterns in fuel_tokens.items():
        matched_span = None
        # Сначала ищем упоминание топлива в самом ответе
        for p in patterns:
            m = re.search(p, effective_text)
            if m:
                matched_span = m
                break
        
        # Если в ответе цифры нет (например: "— 95 есть? — Нету"), берем из всего текста
        in_answer = bool(matched_span)
        if not matched_span:
            for p in patterns:
                m = re.search(p, text_lower)
                if m:
                    matched_span = m
                    break
        
        if matched_span:
            search_scope = effective_text if in_answer else text_lower
            after_text = search_scope[matched_span.end():min(len(search_scope), matched_span.end() + 25)]
            before_text = search_scope[max(0, matched_span.start() - 25):matched_span.start()]

            after_text_no = re.sub(re_queue_limit_no, ' ', after_text)
            before_text_no = re.sub(re_queue_limit_no, ' ', before_text)

            # Если в ответе чётко сказано "нет" / "суох" / "кончился"
            if has_no_answer and not has_yes_answer and not has_limit_answer:
                results[fuel_code] = 'no'
            elif has_limit_answer:
                results[fuel_code] = 'limit'
            elif has_yes_answer and not has_no_answer:
                results[fuel_code] = 'yes'
            elif re.search(rf'^\s*(?:-|–|—|:)?\s*(?:{re_limit})', after_text) or re.search(rf'(?:{re_limit})\s*(?:-|–|—|:)?\s*$', before_text):
                results[fuel_code] = 'limit'
            elif re.search(rf'^\s*(?:-|–|—|:)?\s*(?:{re_yes})', after_text) or re.search(rf'(?:{re_yes})\s*(?:-|–|—|:)?\s*$', before_text):
                results[fuel_code] = 'yes'
            elif re.search(rf'^\s*(?:-|–|—|:)?\s*(?:{re_no})', after_text_no) or re.search(rf'(?:{re_no})\s*(?:-|–|—|:)?\s*$', before_text_no):
                results[fuel_code] = 'no'
            else:
                if has_limit_global:
                    results[fuel_code] = 'limit'
                elif has_no_global and not has_yes_global:
                    results[fuel_code] = 'no'
                elif has_yes_global and not has_no_global:
                    results[fuel_code] = 'yes'

    # Если в ответе не названо конкретное топливо, но в вопросе (reply_text) было упоминание марки
    if not results and reply_lower:
        reply_fuels = []
        for fc, patterns in fuel_tokens.items():
            for p in patterns:
                if re.search(p, reply_lower):
                    reply_fuels.append(fc)
                    break

        if reply_fuels:
            if has_no_answer and not has_yes_answer:
                for fc in reply_fuels: results[fc] = 'no'
            elif has_yes_answer and not has_no_answer:
                for fc in reply_fuels: results[fc] = 'yes'
            elif has_limit_answer:
                for fc in reply_fuels: results[fc] = 'limit'

    # Если конкретные цифры 92/95 не названы, но есть фраза 'нет бензина' / 'бензин закончился' / 'топлива нет' / 'закрыто'
    if not results or (re.search(r'нет\s+(?:там\s+)?бензин\w*|нет\s+никакого\s+бензин\w*|бензин\w*\s+(?:закончил\w*|кончил\w*|бүттэ|бүппүт)', effective_text)):
        if re.search(r'(?:нет\s+(?:(?:там|никакого)\s+)?бензин\w*|бензин\w*\s+нет|топлив\w*\s+нет|нет\s+топлив\w*|бензин\w*\s+(?:закончил\w*|кончил\w*|бүттэ|бүппүт)|топлив\w*\s+(?:закончил\w*|кончил\w*|бүттэ|бүппүт)|все\s+пусто|сухо|закрыт\w*|сабыллыбыт)', effective_text):
            for fc in ['92', '95', '98', '100', 'dt']:
                results[fc] = 'no'
        elif re.search(r'(?:все\s+есть|весь\s+бензин\s+есть|топливо\s+есть|все\s+в\s+наличии|барыта\s+баар)', effective_text):
            for fc in ['92', '95', '98', '100', 'dt']:
                results[fc] = 'yes'

    # Если топливо отсутствует ("no") и нет явного упоминания очереди, сбрасываем фантомную очередь
    if results and all(st == 'no' for st in results.values()) and not re.search(r'очеред[ьи]\s*\d+|уочарат\s*\d+|\d+\s*машин', effective_text):
        queue_count = None

    return results, queue_count, limit_liters

def parse_multi_station_summary(text, stations):
    """
    Извлекает список всех АЗС, упомянутых в сводном сообщении (через точку с запятой, перенос строки, нумерацию).
    Например: "Работающие станции: ул. Петра Алексеева, 70/2; Вилюйский тракт, 6/1; Окружное шоссе, 4-й км"
    """
    if not text:
        return []
    
    brand = ''
    t_low = text.lower()
    if 'сибойл' in t_low or 'сиб ойл' in t_low or 'сиб-ойл' in t_low: brand = 'СибОйл'
    elif 'снгс' in t_low or 'саханефтегаз' in t_low: brand = 'Саханефтегазсбыт'
    elif 'туймаад' in t_low: brand = 'Туймаада-Нефть'
    elif 'паритет' in t_low: brand = 'Паритет'
    elif 'экто' in t_low: brand = 'Экто-Ойл'
    
    list_match = re.search(r'(?:работающие\s+станции|список\s+азс|отпускают\s+(?:на\s+)?(?:следующих\s+)?(?:азс|станциях)|работают(?:\s+азс)?|станции|адреса):\s*(.*)', text, re.I | re.DOTALL)
    if list_match:
        items_str = list_match.group(1)
        items = re.split(r'[;\n•]+|(?:\d+\.\s*)', items_str)
    else:
        if ';' in text or ('\n' in text and len(text.split('\n')) >= 2):
            items = re.split(r'[;\n•]+', text)
        else:
            items = []
        
    found_stations = []
    for it in items:
        it_clean = it.strip()
        if not it_clean or len(it_clean) < 4:
            continue
        test_q = f"{brand} {it_clean}" if brand else it_clean
        st = _match_station_internal(test_q, stations)
        if st and st['id'] not in [s['id'] for s in found_stations]:
            found_stations.append(st)
            
    return found_stations

def process_message(data):
    text = data.get("text", "").strip()
    reply_text = data.get("replyText", "") or data.get("quotedText", "") or ""
    push_name = data.get("pushName", "WhatsApp User")
    sender = data.get("sender", "")
    image_path = data.get("imagePath")

    # Лог для анализа
    log_file = os.path.join(BASE_DIR, "logs", "whatsapp_messages.log")
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"[{datetime.now().isoformat()}] [{sender} ({push_name})] [Photo: {bool(image_path)}] [Reply: {bool(reply_text)}]: {text}\n")
        if reply_text:
            f.write(f"   ↳ Reply to: {reply_text}\n")

    if not text and not image_path:
        return

    # Проверка на рекламу, спам, общие новости и сводки
    is_junk, junk_reason = is_news_or_spam(text)
    if is_junk:
        print(f"[WA Parser / Filter ⛔] Отклонено ({junk_reason}): '{text[:70]}...'")
        return

    # 2. Проверка: сводный ли это пост по нескольким станциям сети
    stations = db.load_stations()
    multi_stations = parse_multi_station_summary(text, stations)
    if len(multi_stations) >= 2:
        print(f"[WA Parser / Multi-Station 📋] Обнаружен список из {len(multi_stations)} АЗС: {[s['name'] for s in multi_stations]}")
        statuses, queue_count, limit_liters = parse_fuel_statuses(text, reply_text)
        tg_user_id = 999999000
        username = f"wa:{push_name[:20]}"
        cleaned_comment_text = clean_driver_comment(text or "")
        rel_photo = os.path.basename(image_path) if (image_path and os.path.exists(image_path)) else None

        for st in multi_stations:
            if rel_photo or cleaned_comment_text:
                db.add_comment(
                    station_id=st['id'],
                    user_tg_id=tg_user_id,
                    username=username,
                    comment=cleaned_comment_text or "Фото из группы",
                    has_photo=1 if rel_photo else 0,
                    photo_path=rel_photo
                )
            if statuses:
                for fuel_code, status in statuses.items():
                    db.add_mark_v2(
                        station_id=st['id'],
                        fuel_code=fuel_code,
                        status=status,
                        user_tg_id=tg_user_id,
                        username=username,
                        mark_type='whatsapp',
                        queue_count=queue_count,
                        limit_liters=limit_liters if status == 'limit' else None
                    )
                    print(f" -> [{st['name']}] Записано: {FUEL_NAMES_RU.get(fuel_code, fuel_code)} -> {STATUS_NAMES_RU.get(status, status)}")
        return

    # 3. Одиночный отзыв / отметка по конкретной АЗС
    station = find_matching_station(text, stations, sender=sender, push_name=push_name)
    
    # 2.1. Если АЗС нет в основном тексте, проверяем явный reply_text
    if not station and reply_text:
        station = find_matching_station(reply_text, stations, sender=sender, push_name=push_name)
        if station:
            print(f"[WA Parser] АЗС найдена из контекста ответа (reply): {station['name']}")

    # 2.2. Если АЗС всё ещё нет, но сообщение похоже на ответ/статус, проверяем буфер недавних вопросов
    if not station and not is_pure_question(text):
        recent_qs = get_recent_questions()
        if recent_qs:
            last_q = recent_qs[-1]
            if last_q.get("station_id"):
                station = next((s for s in stations if s["id"] == last_q["station_id"]), None)
                if station:
                    if not reply_text:
                        reply_text = last_q["text"]
                    print(f"[WA Parser / Window ⏳] АЗС '{station['name']}' взята из недавнего вопроса водителя: '{last_q['text'][:50]}'")

    hermes_data = None
    if not station and text:
        try:
            from scripts.hermes_parser import parse_with_hermes
            hermes_res = parse_with_hermes(text, reply_text=reply_text)
            if hermes_res and hermes_res.get("station_id"):
                st_id = hermes_res["station_id"]
                station = next((s for s in stations if s["id"] == st_id), None)
                if station:
                    print(f"[WA Parser / Hermes ✨] АЗС распознана через Hermes: {station['name']} ({station['address']})")
                    hermes_data = hermes_res
        except Exception as e:
            print(f"[WA Parser] Hermes fallback error: {e}", file=sys.stderr)

    # 2.3. Если это голый вопрос водителя (без ответа/фактов) или Hermes определил вопрос
    if is_pure_question(text) or (hermes_data and hermes_data.get("is_question")):
        save_recent_question(text, station_id=station['id'] if station else None, station_name=station['name'] if station else None)
        print(f"[WA Parser] ❓ Сообщение является вопросом, сохранено в буфер ожидания ответа: '{text[:60]}'")
        return

    if not station:
        print(f"[WA Parser] АЗС не найдена в тексте: '{text}'" + (f" (ответ на: '{reply_text}')" if reply_text else ""))
        return

    statuses, queue_count, limit_liters = parse_fuel_statuses(text, reply_text)
    
    statuses_ru = [f"{FUEL_NAMES_RU.get(fc, fc)}: {STATUS_NAMES_RU.get(st, st)}" + (f" ({limit_liters}л)" if st == 'limit' and limit_liters else "") for fc, st in statuses.items()]
    statuses_str = ", ".join(statuses_ru) if statuses_ru else "нет конкретного топлива"
    queue_str = f"машин: {queue_count}" if queue_count is not None else "не указана"

    print(f"[WA Parser] Найдена АЗС: {station['name']} ({station['address']}) | Статусы: [{statuses_str}] | Очередь: {queue_str}")

    # Запись в БД
    tg_user_id = 999999000
    username = f"wa:{push_name[:20]}"

    # Очистка промо-подписей, локаций и декораторов из текста комментария
    cleaned_comment_text = clean_driver_comment(text or "")

    # Если есть фото или содержательный отзыв — добавляем в ленту комментариев АЗС
    rel_photo = os.path.basename(image_path) if (image_path and os.path.exists(image_path)) else None
    
    # Проверяем ключевые слова для режимов работы, графиков, перерывов и официальных объявлений
    is_schedule_or_official_info = bool(re.search(
        r'режим\s*работ\w*|график\w*|перерыв\w*|обед\w*|выходн\w*|переходит\s*на|'
        r'самообслуживан\w*|терминал\w*|\bтсо\b|круглосуточн\w*|техперерыв\w*|санитарн\w*|'
        r'уважаемые\s*клиенты|администраци\w*|санитарный\s*день|закрыва\w*\s*на\s*ремонт|'
        r'возобнов\w*|гибридн\w*\s*режим',
        cleaned_comment_text, re.I
    ))
    is_official_source = bool('ao_sngs2' in sender.lower() or 'саханефтегаз' in push_name.lower() or 'снгс' in push_name.lower() or 'сибойл' in push_name.lower() or 'туймаада' in push_name.lower())

    is_informative_text = bool(
        cleaned_comment_text and len(cleaned_comment_text) >= 12 and (
            statuses or 
            queue_count is not None or 
            is_schedule_or_official_info or 
            is_official_source or
            re.search(r'минут|мин|очеред|стоял|залил|купил|карт|приложен|лимит|нал|литр|машин|движ|быстр', cleaned_comment_text, re.I)
        )
    )

    if rel_photo or is_informative_text:
        db.add_comment(
            station_id=station['id'],
            user_tg_id=tg_user_id,
            username=username,
            comment=cleaned_comment_text or "Фото из группы",
            has_photo=1 if rel_photo else 0,
            photo_path=rel_photo
        )
        print(f" -> Добавлен комментарий к АЗС {station['name']}: {cleaned_comment_text[:60]}...")

    # Извлечение и обновление цен на топливо
    extracted_prices = extract_fuel_prices(text or "")
    if extracted_prices:
        for fc, price_val in extracted_prices.items():
            try:
                db.set_price(station['id'], fc, price_val)
                print(f" -> 💰 Обновлена цена на АЗС {station['name']}: {FUEL_NAMES_RU.get(fc, fc)} = {price_val} руб.")
            except Exception as e:
                print(f" -> Ошибка записи цены: {e}")

    if statuses:
        for fuel_code, status in statuses.items():
            db.add_mark_v2(
                station_id=station['id'],
                fuel_code=fuel_code,
                status=status,
                user_tg_id=tg_user_id,
                username=username,
                mark_type='whatsapp',
                queue_count=queue_count,
                limit_liters=limit_liters if status == 'limit' else None
            )
            print(f" -> Записано в БД: {FUEL_NAMES_RU.get(fuel_code, fuel_code)} -> {STATUS_NAMES_RU.get(status, status)}" + (f" ({limit_liters}л)" if status == 'limit' and limit_liters else ""))

        # Если в тексте упоминается слив топлива / бензовоз / корова
        is_unloading_msg = bool(re.search(
            r'корова\s*кута\s*турар|корова\s*турар|корова\s*слива\w*|корова\s*кутар|корова\s*кэлбит|'
            r'бензовоз\s*(?:слива\w*|приехал|стоит|разгружа\w*)|газовоз\s*слива\w*|'
            r'слив\s*(?:топлива|цистерны|газа|бензина|92|95|98|100|дт|дизел\w*)|'
            r'сливается\s*(?:бензовоз|газовоз|топливо)|прием\s*бензовоза',
            (text or "").lower()
        ))
        if is_unloading_msg:
            try:
                db.set_station_unloading(station['id'], minutes=35, note='Идёт слив цистерны / бензовоза')
                print(f" -> 🚛 Установлен статус слива топлива на АЗС {station['name']} (~35 мин)")
            except Exception as e:
                print(f" -> Ошибка установки статуса слива: {e}")

    elif queue_count is not None:
        is_gas_station = station.get('brand') == 'Газ' or 'агзс' in station.get('name', '').lower() or re.search(r'\b(?:газ|пропан|агзс)\b', (text or '').lower())
        fuel_code = 'gas' if is_gas_station else '_station_'
        db.add_mark_v2(
            station_id=station['id'],
            fuel_code=fuel_code,
            status='queue' if queue_count > 5 else 'yes',
            user_tg_id=tg_user_id,
            username=username,
            mark_type='whatsapp',
            queue_count=queue_count
        )
        print(f" -> Записана отметка ({fuel_code}) в БД: очередь {queue_count} машин")
    elif image_path:
        # Если только фото без статуса — создаем отметку активности
        db.add_mark_v2(
            station_id=station['id'],
            fuel_code='_station_',
            status='yes',
            user_tg_id=tg_user_id,
            username=username,
            mark_type='whatsapp',
            queue_count=None
        )

    # Триггерим сброс кэша и рассылку WebSocket на карту
    try:
        req = urllib.request.Request(
            'http://127.0.0.1:8765/api/trigger-update',
            data=b'{}',
            headers={'Content-Type': 'application/json'}
        )
        urllib.request.urlopen(req, timeout=2)
    except Exception:
        pass

def main():
    try:
        raw_input = sys.stdin.read()
        if not raw_input.strip():
            return
        data = json.loads(raw_input)
        process_message(data)
    except Exception as e:
        print(f"[WA Parser Error] {e}", file=sys.stderr)

if __name__ == "__main__":
    main()
