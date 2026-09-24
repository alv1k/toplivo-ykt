#!/usr/bin/env python3
import os
import json
import urllib.request
import urllib.parse
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE_DIR, '.env'))

token = os.getenv("BOT_TOKEN")
channel = os.getenv("CHANNEL_ID") or os.getenv("CHANNEL_USERNAME", "@toplivo_ykt")

text = """🎉 <b>Большое обновление сервиса «Топливо Якутия»!</b>

Мы обновили Telegram-бота и интерактивную карту, добавив функции, о которых вы чаще всего просили в чатах и комментариях:

🔔 <b>1. Умные персональные подписки на топливо</b>
Ищете АИ-98, АИ-95 или автогаз? Теперь вам не нужно вручную мониторить чаты!
Нажмите команду /subscribe в боте @toplivo_ykt_bot и выберите нужное топливо. Как только колонка заработает — бот мгновенно пришлет персональное уведомление в Telegram.

🚛 <b>2. Статус «Идёт слив цистерны / бензовоза»</b>
При сообщениях о сливе бензовоза/пропановоза на карте теперь включается специальный статус с ориентировочным таймером ожидания (~30–35 минут), чтобы вы не стояли в неожиданном перерыве.

⚡ <b>3. Телеметрия реальных заправок</b>
В карточках станций появилась плашка «Онлайн-заправка»: теперь видно точное время последнего успешного пролива топлива через онлайн-терминалы.

💬 <b>4. Очищенная лента очевидцев</b>
Наш NLP-парсер теперь понимает еще больше выражений на саха тыла («быhа бардылар», «онно эрэ баар») и автоматически фильтрует рекламу, спам и объявления о работе.

🗺 <b>Открыть карту:</b> https://fuel-map.tiinservice.online/
🤖 <b>Настроить подписки в боте:</b> @toplivo_ykt_bot (/subscribe)"""

data = urllib.parse.urlencode({
    "chat_id": channel,
    "text": text,
    "parse_mode": "HTML",
    "disable_web_page_preview": "false"
}).encode("utf-8")

url = f"https://api.telegram.org/bot{token}/sendMessage"
req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded; charset=utf-8"})
with urllib.request.urlopen(req) as resp:
    res = json.loads(resp.read().decode())
    print("Post 2 published successfully:", res.get("ok"))
