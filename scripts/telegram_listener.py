#!/usr/bin/env python3
"""
Telegram Channel Monitor for Toplivo Yakutsk.
Listens to @ao_sngs2 and driver channels/groups, parses updates into fuel.db.
"""
import sys
import os
import asyncio
import json
import re
import logging
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from telethon import TelegramClient, events
import config
from scripts.parse_whatsapp_message import process_message

logging.basicConfig(
    format='%(asctime)s TG-MONITOR %(levelname)s %(message)s',
    level=logging.INFO,
    datefmt='%Y-%m-%d %H:%M:%S'
)

API_ID = 2040
API_HASH = "b18441a1ff607e10a989891a5462e627"

SESSION_FILE = os.path.join(BASE_DIR, "data", "toplivo_tg_user")
MEDIA_DIR = os.path.join(BASE_DIR, "media", "telegram")
os.makedirs(os.path.dirname(SESSION_FILE), exist_ok=True)
os.makedirs(MEDIA_DIR, exist_ok=True)

# Целевые каналы и группы
TARGET_CHANNELS = [
    'ao_sngs2',         # Официальный канал Саханефтегазсбыт
    'gasolineykt',      # Ситуация с топливом / Бензин Якутск
    'toplivo14',        # Канал Топливо 14
    'yakutiaopershtab', # Оперштаб Республики Саха (Якутия)
    -1004416785721,     # Группа "Бензин газ якутск"
]

# Новостные каналы общей тематики (требуют обязательной фильтрации по ключевым словам)
NEWS_CHANNELS = {'yakutiaopershtab'}

# Ключевые слова для проверки новостных каналов
FUEL_KEYWORDS_REGEX = re.compile(
    r'(?:сибойл|саханефтегазсбыт|снгс|туймаада|паритет|экто-ойл|сервис-ойл|опти|'
    r'топливн|бензин|дизель|\bдт\b|\bазс\b|\bмазс\b|\bагзс\b|талон|заправк|нефтепродукт)',
    re.IGNORECASE
)

client = TelegramClient(SESSION_FILE, API_ID, API_HASH)

def parse_multiline_sngs_post(text, chat_title, sender):
    """
    Парсит официальные и сводные посты со списком АЗС (СНГС, Туймаада-Нефть, СибОйл, Сервис-Ойл).
    """
    lines = text.split('\n')
    has_list = any(re.search(r'(?:АЗС|МАЗС)\s*(?:№\s*)?\d+|по адресу|по покровскому|по вилюйскому', line, re.IGNORECASE) for line in lines)
    
    if has_list and len(lines) > 2:
        current_brand = "СНГС"
        for line in lines:
            line_str = line.strip()
            if not line_str:
                continue

            # Отслеживаем смену бренда в сводке
            if re.search(r'туймаада-нефть', line_str, re.I):
                current_brand = "Туймаада-Нефть"
            elif re.search(r'саханефтегазсбыт|снгс', line_str, re.I):
                current_brand = "СНГС"
            elif re.search(r'сибойл', line_str, re.I):
                current_brand = "СибОйл"
            elif re.search(r'сервис-ойл', line_str, re.I):
                current_brand = "Сервис-Ойл"

            # Если строка содержит конкретную станцию
            if re.search(r'(?:АЗС|МАЗС)\s*[-–—№]?\s*\d+|покровск|вилюйск|дзержинск|автострад|труда|жатай|маганск|хатын', line_str, re.I):
                clean_line = f"{current_brand} {line_str}"
                
                # Дополняем контекстом если это сводка о наличии/лимите
                if re.search(r'лимит|до\s*\d+\s*л', text, re.I) and not re.search(r'лимит|до\s*\d+\s*л|нет|нету|суох', clean_line, re.I):
                    clean_line += " лимит"
                elif re.search(r'можно заправиться|в наличии|отпуск|работают|за наличный', text, re.I) and not re.search(r'92|95|98|дт|дизель|газ', clean_line, re.I):
                    clean_line += " 92 есть 95 есть"
                    
                process_message({
                    "text": clean_line,
                    "pushName": chat_title,
                    "sender": sender,
                    "imagePath": None
                })
        return True
    return False

_recent_tg_posts = []  # list of {"text": ..., "ts": ...}

def is_recent_tg_duplicate(text, window_seconds=2700):
    global _recent_tg_posts
    if not text or len(text.strip()) < 10:
        return False
    now = datetime.now().timestamp()
    _recent_tg_posts = [p for p in _recent_tg_posts if now - p["ts"] < window_seconds]
    for p in _recent_tg_posts:
        if db.is_duplicate_text(text, p["text"]):
            return True
    _recent_tg_posts.append({"text": text, "ts": now})
    return False

@client.on(events.NewMessage(chats=TARGET_CHANNELS))
async def handle_new_message(event):
    chat = await event.get_chat()
    chat_title = getattr(chat, 'title', getattr(chat, 'username', 'Unknown Chat'))
    chat_username = (getattr(chat, 'username', '') or '').lower()

    text = event.raw_text or ''
    logging.info(f"New post from [{chat_title} (@{chat_username})]:\n{text[:120]}...")

    # Проверка на дублирование сообщений между каналами / повторные посты
    if text and is_recent_tg_duplicate(text):
        logging.info(f"[TG Monitor / Deduplication 🔁] Пропущен повторный пост: '{text[:60]}...'")
        return

    # Для новостных каналов (SD Новости Якутии, Пряная Якутия) фильтруем только посты с ключевыми словами
    is_news_channel = chat_username in NEWS_CHANNELS
    if is_news_channel:
        if not text or not FUEL_KEYWORDS_REGEX.search(text):
            logging.info(f"Skipping non-fuel news from @{chat_username}")
            return

    image_path = None
    # Для новостных каналов не дублируем фото (смотрим только на совпадение по тексту/ключевым словам)
    if event.photo and not is_news_channel:
        try:
            filename = f"tg_{int(datetime.now().timestamp())}_{event.id}.jpg"
            image_path = os.path.join(MEDIA_DIR, filename)
            await event.download_media(file=image_path)
            logging.info(f"Photo downloaded: {image_path}")
        except Exception as e:
            logging.error(f"Failed to download photo: {e}")

    # 1. Извлекаем контекст ответа (если это Reply на предыдущий вопрос)
    reply_text = ''
    if event.is_reply:
        try:
            reply_msg = await event.get_reply_message()
            if reply_msg and reply_msg.raw_text:
                reply_text = reply_msg.raw_text
                logging.info(f"Reply context: {reply_text[:100]}...")
        except Exception as e:
            logging.error(f"Failed to fetch reply message: {e}")

    # 2. Проверяем, не составная ли это сводка-список АЗС
    if text:
        handled_as_list = parse_multiline_sngs_post(text, chat_title, f"tg:@{chat_username or event.chat_id}")
        if handled_as_list:
            logging.info("Handled as multiline station list.")
            return

    # 3. Обычное сообщение / одиночный пост (с контекстом ответа)
    payload = {
        "text": text,
        "replyText": reply_text,
        "pushName": f"TG: {chat_title}",
        "sender": f"tg:@{chat_username or event.chat_id}",
        "imagePath": image_path
    }

    try:
        process_message(payload)
    except Exception as e:
        logging.error(f"Error in process_message: {e}")

async def main():
    await client.start()
    logging.info("Telegram Client connected successfully!")
    
    me = await client.get_me()
    logging.info(f"Logged in as: {me.first_name} (@{me.username or me.phone})")

    logging.info(f"Listening to channels: {TARGET_CHANNELS}")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
