import logging
import math
import re
import time
import urllib.parse
from datetime import datetime, timezone, timedelta

YAKUTSK = timezone(timedelta(hours=9))

def to_ykt(utc_str):
    if not utc_str:
        return ''
    dt = datetime.strptime(utc_str, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
    return dt.astimezone(YAKUTSK).strftime('%d.%m %H:%M')

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand, WebAppInfo
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters

import config
import db

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

FUEL_LABELS = {'92': 'АИ-92', '95': 'АИ-95', '98': 'АИ-98', '100': 'АИ-100', 'dt': 'ДТ', 'gas': 'Газ'}
STATUS_LABELS = {'yes': '✅ Есть', 'no': '❌ Нет', 'queue': '⏳ Очередь', 'limit': '🔒 Лимит'}
STATUS_EMOJI = {'yes': '🟢', 'no': '🔴', 'queue': '🟡', 'limit': '🟠'}

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    from telegram import WebAppInfo
    import time
    ts = int(time.time())
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🗺 Интерактивная карта", web_app=WebAppInfo(url=f"https://fuel-map.tiinservice.online/?v={ts}"))],
        [InlineKeyboardButton("🔔 Подписки и уведомления", callback_data="sub_menu"), InlineKeyboardButton("📢 Наш канал", url=f"https://t.me/{config.CHANNEL_USERNAME.lstrip('@')}")] ,
        [InlineKeyboardButton("💬 Обратная связь", callback_data="feedback_prompt"), InlineKeyboardButton("❓ Помощь", callback_data="help")],
    ])
    await update.message.reply_text(
        "⛽ <b>Топливо Якутия</b>\n\n"
        "Отмечайте наличие топлива на АЗС и смотрите актуальную ситуацию.\n\n"
        "Все отметки помогают водителям — участвуйте!",
        reply_markup=keyboard,
        parse_mode='HTML'
    )

async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Как пользоваться:\n"
        "1. Открой /map — интерактивная карта АЗС\n"
        "2. Выбери АЗС → выбери тип топлива → отметь статус\n\n"
        "Все отметки анонимны и помогают другим водителям!"
    )

async def map_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    from telegram import WebAppInfo
    import time
    ts = int(time.time())
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🗺 Открыть карту", web_app=WebAppInfo(url=f"https://fuel-map.tiinservice.online/?v={ts}"))]
    ])
    await update.message.reply_text(
        "🗺 Интерактивная карта АЗС Якутска.\n"
        "Цвет пинов: 🟢 есть топливо, 🔴 нет, 🟡 очередь/лимит.",
        reply_markup=keyboard
    )

async def channel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"📢 Подпишись на наш канал: {config.CHANNEL_USERNAME}\n"
        "Там публикуем сводки по топливу, новости и изменения цен."
    )

async def stations_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    stations = db.load_stations()
    msg = "⛽ Все АЗС Якутска:\n\n"
    for s in stations:
        brand = f"[{s['brand']}] " if s['brand'] else ""
        addr = f" — {s['address']}" if s['address'] else ""
        msg += f"• {brand}{s['name']}{addr}\n"
    msg += f"\nВсего: {len(stations)} АЗС"
    await update.message.reply_text(msg)



async def station_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split('|')
    action = parts[0] if parts else ''
    
    if action == 'station':
        if len(parts) < 2:
            await query.edit_message_text("Ошибка: не указана АЗС")
            return
        try:
            station_id = int(parts[1])
        except (ValueError, IndexError):
            await query.edit_message_text("Ошибка: неверный ID АЗС")
            return
        if len(parts) > 2:
            ctx.user_data['back_to'] = parts[2]
        back_to = ctx.user_data.get('back_to', 'menu')
        ctx.user_data['station_id'] = station_id
        station = next((s for s in db.load_stations() if s['id'] == station_id), None)
        if not station:
            await query.edit_message_text("АЗС не найдена")
            return

        marks = db.get_latest_marks(station_id)
        text = f"⛽ <b>{station['name']}</b>\n"
        if station['brand']:
            text += f"Сеть: {station['brand']}\n"
        if station['address']:
            text += f"📍 {station['address']}\n"
        text += "\n<b>Топливо:</b>\n"
        for fc in ['92', '95', '98', '100', 'dt', 'gas']:
            label = FUEL_LABELS[fc]
            if fc in marks:
                m = marks[fc]
                text += f"{STATUS_EMOJI.get(m['status'],'❓')} {label} — {STATUS_LABELS.get(m['status'], m['status'])} ({to_ykt(m['time'])})\n"
            else:
                text += f"⚪ {label} — нет данных\n"

        await query.message.delete()

        await query.message.reply_venue(
            latitude=station['lat'],
            longitude=station['lon'],
            title=station['name'],
            address=station['address'] or station['name']
        )

        keyboard = [
            [InlineKeyboardButton("✅ Отметить наличие", callback_data=f"mark|{station_id}")],
            [InlineKeyboardButton("🔙 Назад", callback_data="back")],
        ]
        await query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    
    elif action == 'mark':
        if len(parts) < 2:
            await query.edit_message_text("Ошибка: не указана АЗС")
            return
        try:
            station_id = int(parts[1])
        except (ValueError, IndexError):
            await query.edit_message_text("Ошибка: неверный ID АЗС")
            return
        ctx.user_data['mark_station_id'] = station_id
        keyboard = [
            [InlineKeyboardButton(f"{FUEL_LABELS['92']}", callback_data=f"fuel|92"),
             InlineKeyboardButton(f"{FUEL_LABELS['95']}", callback_data=f"fuel|95")],
            [InlineKeyboardButton(f"{FUEL_LABELS['98']}", callback_data=f"fuel|98"),
             InlineKeyboardButton(f"{FUEL_LABELS['dt']}", callback_data=f"fuel|dt"),
             InlineKeyboardButton(f"{FUEL_LABELS['gas']}", callback_data=f"fuel|gas")],
            [InlineKeyboardButton("🔙 Назад", callback_data=f"station|{station_id}")],
        ]
        await query.edit_message_text("Выбери тип топлива:", reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif action == 'fuel':
        if len(parts) < 2:
            await query.edit_message_text("Ошибка: не указано топливо")
            return
        fuel_code = parts[1]
        ctx.user_data['fuel_code'] = fuel_code
        station_id = ctx.user_data.get('mark_station_id')
        keyboard = [
            [InlineKeyboardButton("✅ Есть", callback_data=f"set|yes"),
             InlineKeyboardButton("❌ Нет", callback_data=f"set|no")],
            [InlineKeyboardButton("⏳ Очередь", callback_data=f"set|queue"),
             InlineKeyboardButton("🔒 Лимит", callback_data=f"set|limit")],
            [InlineKeyboardButton("🔙 Назад", callback_data=f"mark|{station_id}")],
        ]
        await query.edit_message_text(
            f"{FUEL_LABELS.get(fuel_code, fuel_code)} — какой статус?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    elif action == 'set':
        if len(parts) < 2:
            await query.edit_message_text("Ошибка: не указан статус")
            return
        status = parts[1]
        station_id = ctx.user_data.get('mark_station_id')
        fuel_code = ctx.user_data.get('fuel_code')
        user = query.from_user
        
        if station_id and fuel_code:
            db.add_mark(station_id, fuel_code, status, user.id, user.username or '')
            
            await query.edit_message_text(
                f"✅ Отмечено: {FUEL_LABELS.get(fuel_code, fuel_code)} — {STATUS_LABELS.get(status, status)}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 К АЗС", callback_data=f"station|{station_id}")],
                    [InlineKeyboardButton("✅ Отметить ещё", callback_data=f"mark|{station_id}")],
                ])
            )
    
    elif action == 'sub_menu':
        await subscribe_cmd(update, ctx)

    elif action == 'my_subs':
        await my_subs_cmd(update, ctx)

    elif action == 'sub_fuel':
        if len(parts) < 2:
            return
        fuel_code = parts[1]
        fc_label = FUEL_LABELS.get(fuel_code, fuel_code)
        keyboard = [
            [InlineKeyboardButton("🌍 По всему Якутску (любая АЗС)", callback_data=f"sub_confirm|0|{fuel_code}")],
            [InlineKeyboardButton("🔙 К выбору топлива", callback_data="sub_menu")],
        ]
        await query.edit_message_text(
            f"🔔 <b>Подписка на {fc_label}</b>\n\n"
            f"Где отслеживать появление {fc_label}?",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )

    elif action == 'sub_confirm':
        if len(parts) < 3:
            return
        st_id = int(parts[1])
        fuel_code = parts[2]
        fc_label = FUEL_LABELS.get(fuel_code, fuel_code)
        db.subscribe(query.from_user.id, st_id, fuel_code)
        target_name = "по всему городу" if st_id == 0 else f"на АЗС #{st_id}"
        keyboard = [
            [InlineKeyboardButton("📋 Мои подписки", callback_data="my_subs")],
            [InlineKeyboardButton("➕ Добавить ещё", callback_data="sub_menu")],
            [InlineKeyboardButton("🔙 Главное меню", callback_data="back")],
        ]
        await query.edit_message_text(
            f"✅ <b>Подписка оформлена!</b>\n\n"
            f"Мы пришлем вам мгновенное уведомление в Telegram, как только <b>{fc_label}</b> появится {target_name}.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )

    elif action == 'unsub':
        if len(parts) < 3:
            return
        st_id = int(parts[1])
        fuel_code = parts[2]
        db.unsubscribe(query.from_user.id, st_id, fuel_code)
        await query.answer("Подписка удалена", show_alert=True)
        await my_subs_cmd(update, ctx)

    elif action == 'help':
        await query.edit_message_text(
            "Как пользоваться:\n"
            "1. Открой 🗺 карту — выбери АЗС на карте\n"
            "2. Нажми «Заправился» или «Подъехал» → отметь статус\n\n"
            "Все отметки анонимны и помогают другим водителям!"
        )

    elif action == 'feedback_prompt':
        ctx.user_data['waiting_feedback'] = True
        await query.message.reply_text(
            "💬 <b>Обратная связь и предложения</b>\n\n"
            "Напишите ваше сообщение (предложение, неточность на АЗС или найденную ошибку) в ответном сообщении 👇",
            parse_mode='HTML'
        )

    elif action == 'back':
        await query.edit_message_text(
            "⛽ <b>Топливо Якутия</b>\n\n"
            "Отмечайте наличие топлива на АЗС и смотрите актуальную ситуацию.\n\n"
            "Команды:\n"
            "/map — интерактивная карта АЗС\n"
            "/subscribe — умные подписки и уведомления\n"
            "/my_subs — мои активные подписки\n"
            "/channel — наш канал с новостями\n"
            "/help — помощь",
            parse_mode='HTML'
        )

async def subscribe_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🔔 АИ-95 (появление)", callback_data="sub_fuel|95"),
         InlineKeyboardButton("🔔 АИ-98 (появление)", callback_data="sub_fuel|98")],
        [InlineKeyboardButton("🔔 Газ / АГЗС", callback_data="sub_fuel|gas"),
         InlineKeyboardButton("🔔 АИ-92", callback_data="sub_fuel|92")],
        [InlineKeyboardButton("📋 Мои активные подписки", callback_data="my_subs")],
    ]
    text = (
        "🔔 <b>Умные уведомления по топливу</b>\n\n"
        "Выберите марку топлива, чтобы получать мгновенные пуш-уведомления в Telegram, "
        "когда топливо появится в продаже или спадет очередь:"
    )
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

async def my_subs_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    subs = db.get_user_subscriptions(user.id)
    if not subs:
        text = "📋 У вас пока нет активных подписок.\n\nИспользуйте /subscribe для настройки уведомлений."
        keyboard = [[InlineKeyboardButton("➕ Добавить подписку", callback_data="sub_menu")]]
        if update.callback_query:
            await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        return

    text = "📋 <b>Ваши активные подписки:</b>\n\n"
    keyboard = []
    for s in subs:
        fc_label = FUEL_LABELS.get(s['fuel_code'], s['fuel_code'])
        text += f"• 🔔 <b>{fc_label}</b> — {s['name']}\n"
        keyboard.append([InlineKeyboardButton(f"❌ Отписаться: {fc_label} ({s['name'][:18]})", callback_data=f"unsub|{s['station_id']}|{s['fuel_code']}")])
    
    keyboard.append([InlineKeyboardButton("➕ Добавить ещё", callback_data="sub_menu")])
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

def generate_summary():
    stations = db.load_stations()
    total = len(stations)
    marked_stations = 0
    fuel_counts = {}
    stations_with_fuel = {}
    latest_time = None

    for s in stations:
        marks = db.get_latest_marks(s['id'])
        if marks:
            marked_stations += 1
            for fc, m in marks.items():
                if fc not in fuel_counts:
                    fuel_counts[fc] = {'yes': 0, 'no': 0, 'queue': 0, 'limit': 0}
                fuel_counts[fc][m['status']] = fuel_counts[fc].get(m['status'], 0) + 1
                if m['status'] == 'yes':
                    if fc not in stations_with_fuel:
                        stations_with_fuel[fc] = 0
                    stations_with_fuel[fc] += 1
                t = m['time']
                if t and (not latest_time or t > latest_time):
                    latest_time = t

    text = f"⛽ <b>Сводка по топливу в Якутске</b>\n"
    text += f"📅 {datetime.now(YAKUTSK).strftime('%d.%m.%Y %H:%M')}\n\n"

    for fc in ['92', '95', '98', '100', 'dt', 'gas']:
        label = FUEL_LABELS.get(fc, fc)
        if fc in fuel_counts:
            c = fuel_counts[fc]
            yes = c.get('yes', 0)
            no = c.get('no', 0)
            queue = c.get('queue', 0)
            limit = c.get('limit', 0)
            parts = []
            if yes: parts.append(f"🟢 есть на {yes}")
            if no: parts.append(f"🔴 нет на {no}")
            if queue: parts.append(f"🟡 очередь {queue}")
            if limit: parts.append(f"🟠 лимит {limit}")
            text += f"<b>{label}</b>: {'; '.join(parts)}\n"
        else:
            text += f"<b>{label}</b>: нет данных\n"

    text += f"\nОтмечено АЗС: {marked_stations} из {total}"
    if latest_time:
        text += f"\n⏱ последняя отметка: {to_ykt(latest_time)}"

    return text

async def post_summary_to_channel(ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = getattr(config, 'CHANNEL_ID', None)
    if not chat_id:
        logging.warning("CHANNEL_ID not configured")
        return
    try:
        text = generate_summary()
        await ctx.bot.send_message(chat_id=chat_id, text=text, parse_mode='HTML')
        logging.info("Summary posted to channel")
    except Exception as e:
        logging.error(f"Failed to post summary: {e}")

async def job_post_summary(ctx: ContextTypes.DEFAULT_TYPE):
    await post_summary_to_channel(ctx)

async def post_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    if user.id not in config.ADMIN_IDS:
        await update.message.reply_text("Эта команда только для администраторов.")
        return
    await post_summary_to_channel(ctx)
    await update.message.reply_text("✅ Сводка опубликована в канале.")

async def process_feedback_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE, text: str):
    user = update.effective_user
    fid = db.add_feedback(
        message=text,
        feedback_type='bot',
        user_tg_id=user.id,
        username=user.username or user.first_name or ''
    )
    
    user_mention = user.mention_html()
    msg = (
        f"📩 <b>Новое обращение из бота (#{fid})</b>\n"
        f"👤 От: {user_mention} (ID: <code>{user.id}</code>)\n\n"
        f"💬 <b>Сообщение:</b>\n{text}"
    )
    for admin_id in config.ADMIN_IDS:
        try:
            await ctx.bot.send_message(chat_id=admin_id, text=msg, parse_mode='HTML')
        except Exception as e:
            logging.error(f"Failed to send feedback to admin {admin_id}: {e}")

    await update.message.reply_text(
        "✅ <b>Спасибо за обратную связь!</b>\n"
        "Ваше сообщение передано администраторам.",
        parse_mode='HTML'
    )

async def feedback_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    args = ctx.args
    if not args:
        ctx.user_data['waiting_feedback'] = True
        await update.message.reply_text(
            "💬 <b>Обратная связь и предложения</b>\n\n"
            "Напишите ваше сообщение (предложение, неточность на АЗС или найденную ошибку) в ответном сообщении 👇\n\n"
            "Или отправьте сразу командой:\n<code>/feedback ваш текст</code>",
            parse_mode='HTML'
        )
        return

    text = ' '.join(args).strip()
    await process_feedback_message(update, ctx, text)

BRAND_PATTERNS = [
    (re.compile(r'\b(сибойл\w*|сиб\s*ойл\w*|siboil\w*)\b', re.I), 'СибОйл'),
    (re.compile(r'\b(снгс\w*|саханефтегазсбыт\w*|саханефт\w*)\b', re.I), 'Саханефтегазсбыт'),
    (re.compile(r'\b(туймаад\w*|туймад\w*|тн)\b', re.I), 'Туймаада-Нефть'),
    (re.compile(r'\b(паритет\w*)\b', re.I), 'Паритет'),
    (re.compile(r'\b(газпром\w*|опти\w*)\b', re.I), 'Газпром'),
    (re.compile(r'\b(экто-ойл\w*|экто\w*)\b', re.I), 'Экто-Ойл'),
    (re.compile(r'\b(игвас\w*)\b', re.I), 'Игвас'),
    (re.compile(r'\b(агзс\w*|газ\w*|пропан\w*|метан\w*|баллон\w*)\b', re.I), 'Газ'),
]

FUEL_PATTERNS = [
    (re.compile(r'\b(95|аи-95|аи95|ай-95|ай95)\b', re.I), '95'),
    (re.compile(r'\b(92|аи-92|аи92|ай-92|ай92)\b', re.I), '92'),
    (re.compile(r'\b(98|аи-98|аи98|ай-98|ай98)\b', re.I), '98'),
    (re.compile(r'\b(100|аи-100|аи100)\b', re.I), '100'),
    (re.compile(r'\b(дт|дизель|дизельное|солярка|соляра|солярку)\b', re.I), 'dt'),
    (re.compile(r'\b(газ|агзс|пропан|метан|суг|баллон)\b', re.I), 'gas'),
]

async def handle_user_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if ctx.user_data.get('waiting_feedback'):
        ctx.user_data['waiting_feedback'] = False
        text = update.message.text.strip()
        await process_feedback_message(update, ctx, text)
        return

    text = update.message.text.strip()
    if not text:
        return

    # 1. Распознаем бренд и марку топлива из запроса
    matched_brand = None
    for pattern, brand_name in BRAND_PATTERNS:
        if pattern.search(text):
            matched_brand = brand_name
            break

    matched_fuel = None
    for pattern, fuel_code in FUEL_PATTERNS:
        if pattern.search(text):
            matched_fuel = fuel_code
            break

    # Если не распознали ни бренд, ни топливо
    if not matched_brand and not matched_fuel:
        ts = int(time.time())
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🗺 Открыть карту АЗС", web_app=WebAppInfo(url=f"https://fuel-map.tiinservice.online/?v={ts}"))],
            [InlineKeyboardButton("🔔 Настроить подписки", callback_data="sub_menu")]
        ])
        await update.message.reply_text(
            "⛽ <b>Поиск топлива и АЗС в Якутске</b>\n\n"
            "Вы можете написать в чат, например:\n"
            "• <i>«В каком Сибойле есть АИ-95?»</i>\n"
            "• <i>«Где есть 95»</i>\n"
            "• <i>«СНГС 92»</i>\n"
            "• <i>«Туймаада»</i> или <i>«АГЗС»</i>\n\n"
            "Или открыть интерактивную карту 👇",
            reply_markup=keyboard,
            parse_mode='HTML'
        )
        return

    # 2. Выполняем выборку подходящих АЗС
    stations = db.load_stations()
    candidates = []

    for s in stations:
        is_closed = bool(s.get('is_closed'))
        is_gas = (s.get('brand') == 'Газ' or 'агзс' in (s.get('name') or '').lower() or 'газ' in (s.get('name') or '').lower() or s.get('id') in (648, 650))
        if matched_brand:
            if matched_brand == 'Газ':
                if not is_gas:
                    continue
            else:
                st_brand = (s.get('brand') or '').lower()
                if matched_brand.lower() not in st_brand:
                    continue

        marks = db.get_latest_marks(s['id'])
        
        # Определяем статус для ранжирования
        if is_closed:
            st_status = 'closed'
            st_time = ''
        elif matched_fuel:
            m = marks.get(matched_fuel)
            st_status = m['status'] if m else ('yes' if matched_fuel == 'gas' and is_gas else 'none')
            st_time = m['time'] if m else ''
        else:
            has_yes = any(mk['status'] == 'yes' for mk in marks.values()) or is_gas
            has_queue = any(mk['status'] == 'queue' for mk in marks.values())
            has_limit = any(mk['status'] == 'limit' for mk in marks.values())
            st_status = 'yes' if has_yes else ('queue' if has_queue else ('limit' if has_limit else ('no' if marks else 'none')))
            st_time = max([mk['time'] for mk in marks.values() if mk.get('time')], default='')

        score_map = {'yes': 1, 'queue': 2, 'limit': 3, 'no': 4, 'none': 5, 'closed': 6}
        score = score_map.get(st_status, 5)
        candidates.append({
            'station': s,
            'marks': marks,
            'status': st_status,
            'time': st_time,
            'score': score
        })

    candidates.sort(key=lambda x: (x['score'], x['station'].get('name', '')))

    # 3. Формируем ответ пользователю
    title_brand = f"сети «{matched_brand}»" if matched_brand else "по Якутску"
    title_fuel = FUEL_LABELS.get(matched_fuel, matched_fuel) if matched_fuel else "топливу"
    
    msg_lines = [f"⛽ <b>Наличие: {title_fuel} ({title_brand})</b>\n"]
    
    if not candidates:
        msg_lines.append("К сожалению, заправок по данному запросу не найдено.")
    else:
        shown = candidates[:8]
        for c in shown:
            st = c['station']
            st_name = st.get('name') or 'АЗС'
            addr = f" ({st['address']})" if st.get('address') else ""
            if c['status'] == 'closed':
                status_em = '🛠'
                status_lbl = st.get('closed_reason') or 'Закрыта на ремонт'
            else:
                status_em = STATUS_EMOJI.get(c['status'], '⚪')
                status_lbl = STATUS_LABELS.get(c['status'], 'Нет свежих отметок')
            time_str = f" · {to_ykt(c['time'])}" if c['time'] else ""
            msg_lines.append(f"{status_em} <b>{st_name}</b>{addr}\n   └ {status_lbl}{time_str}")

        if len(candidates) > 8:
            msg_lines.append(f"\n<i>...и ещё {len(candidates) - 8} АЗС на карте</i>")

    # 4. Формируем интерактивные кнопки
    ts = int(time.time())
    query_parts = []
    if matched_brand:
        query_parts.append(f"brand={urllib.parse.quote(matched_brand)}")
    if matched_fuel:
        query_parts.append(f"fuel={matched_fuel}")
    query_parts.append(f"v={ts}")
    web_url = f"https://fuel-map.tiinservice.online/?{'&'.join(query_parts)}"

    btn_label = f"🗺 Показать на карте ({matched_brand or 'Все'} • {title_fuel})"
    keyboard = [
        [InlineKeyboardButton(btn_label, web_app=WebAppInfo(url=web_url))],
    ]
    if matched_fuel:
        keyboard.append([InlineKeyboardButton(f"🔔 Подписка на {title_fuel}", callback_data=f"sub_fuel|{matched_fuel}")])

    await update.message.reply_text(
        "\n".join(msg_lines),
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='HTML'
    )

async def post_init(app):
    commands = [
        BotCommand("start", "Главное меню"),
        BotCommand("map", "Интерактивная карта АЗС"),
        BotCommand("subscribe", "🔔 Умные подписки по топливу"),
        BotCommand("my_subs", "📋 Мои активные подписки"),
        BotCommand("feedback", "Обратная связь и предложения"),
        BotCommand("channel", "Наш канал @toplivo_ykt"),
        BotCommand("help", "Помощь"),
    ]
    await app.bot.set_my_commands(commands)
    await app.bot.set_my_description(
        "🗺 Интерактивная карта всех АЗС и АГЗС Якутии.\n\n"
        "Отмечайте где есть топливо, где очередь, а где заправка закрыта.\n"
        "Добавлены газовые заправки, автоматические АЗС.\n"
        "Можно настроить умные уведомления (/subscribe) на появление АИ-95, АИ-98 или автогаза.\n"
        "Откройте карту и помогайте другим водителям!"
    )

def main():
    db.init_db()
    db.import_stations_from_json('stations.json')
    
    app = Application.builder().token(config.BOT_TOKEN).post_init(post_init).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("channel", channel))
    app.add_handler(CommandHandler("stations", stations_list))
    app.add_handler(CommandHandler("map", map_cmd))
    app.add_handler(CommandHandler("subscribe", subscribe_cmd))
    app.add_handler(CommandHandler("my_subs", my_subs_cmd))
    app.add_handler(CommandHandler("feedback", feedback_cmd))
    app.add_handler(CommandHandler("post", post_cmd))
    app.add_handler(CallbackQueryHandler(station_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_user_text))

    print("Бот запущен...")
    app.run_polling()

if __name__ == '__main__':
    main()
