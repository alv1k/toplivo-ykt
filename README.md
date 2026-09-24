# ⛽ Топливо Якутия (Toplivo Yakutsk)

> Интеллектуальный сервис мониторинга цен, наличия и очередей на АЗС/АГЗС в Республике Саха (Якутия). Интерактивная карта (Telegram WebApp), автоматический парсинг сетей АЗС, краудсорсинг водителей, WhatsApp/Telegram слушатели и AI-анализ сообщений.

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org/)
[![Telegram Bot API](https://img.shields.io/badge/Telegram_Bot-PTB_20.7-2CA5E0?style=flat-square&logo=telegram&logoColor=white)](https://core.telegram.org/bots/api)
[![Leaflet](https://img.shields.io/badge/Leaflet-1.9-199900?style=flat-square&logo=leaflet&logoColor=white)](https://leafletjs.com/)
[![Node.js](https://img.shields.io/badge/Node.js-Baileys-339933?style=flat-square&logo=node.js&logoColor=white)](https://nodejs.org/)
[![SQLite](https://img.shields.io/badge/SQLite-WAL_Mode-003B57?style=flat-square&logo=sqlite&logoColor=white)](https://sqlite.org/)
[![License](https://img.shields.io/badge/license-MIT-green?style=flat-square)](#)

---

## 🌟 Возможности системы

### 🤖 1. Telegram-бот ([@toplivo_ykt_bot](https://t.me/toplivo_ykt_bot))
- **Поиск по геолокации** — отправка геопозиции и мгновенный расчет расстояний до ближайших заправок.
- **Фильтрация по типам топлива** — АИ-92, АИ-95, АИ-98, АИ-100, Дизельное топливо (ДТ), СУГ (Газ), ТС-1.
- **Подписки и уведомления** — пуши при изменении цен или появлении топлива на избранных заправках.
- **Telegram WebApp** — открытие интерактивной карты в 1 клик прямо внутри Telegram с авторизацией по `initData` (HMAC-SHA256).

### 🗺️ 2. Интерактивная карта Leaflet & WebSockets
- **Интерактивная карта** — отображение всех АЗС Якутска и районов республики.
- **Цветовая индикация доступности**:
  - 🟢 **Есть** — топливо в наличии без ограничений.
  - 🟡 **Очередь** — наблюдается скопление автомобилей.
  - 🟠 **Лимит** — отпуск по талонам, лимитам или спецкартам.
  - 🔴 **Нет** — топливо временно отсутствует.
- **Live-обновления по WebSockets** — моментальное отображение новых отметок без перезагрузки страницы.
- **Кабинет партнера и админка** — модерация отметок, ручная корректировка остатков и цен сетей.

### 🕷️ 3. Мультисетевой парсинг АЗС
Сервис регулярно собирает данные из официальных источников и агрегаторов:
- **Сибойл** (`scripts/parse_siboil_prices.py`) — актуальные цены сети.
- **Саханефтегазсбыт (СНГС)** (`scripts/parse_sngs_stations.py`) — каталог и прайс-листы филиалов по всей республике.
- **Паритет** (`scripts/parse_paritet.py`) — мониторинг АГЗС и АЗС.
- **Туймаада-Нефть** (`scripts/parse_tuneft.py`) — сводки наличия и стоимости.
- **СберАЗС** (`scripts/parse_sberazs.py`) — автоматизированные остатки колонок.
- **SakhaDay** (`scripts/parse_sakhaday.py`) — новости и сообщения об ограничениях.

### 🧠 4. Слушатели чатов и AI-парсер сообщений
- **WhatsApp Listener (Node.js Baileys)** — перехват сообщений водителей из профильных групп в реальном времени.
- **Telegram Channel & Group Listener (Telethon)** — мониторинг сводок и чатов автолюбителей.
- **AI NLP Extractor (Hermes / LLM)** — извлечение ориентиров, названий станций, видов топлива и статусов («на Вилюйском 95-й по 50л», «на Автодорожной дизеля нет») с самообучающимся словарем синонимов (`data/hermes_synonyms.json`).

---

## 📂 Архитектура и структура проекта

```text
toplivo-yakutsk/
├── bot.py                     # Основной модуль Telegram-бота (python-telegram-bot)
├── db.py                      # Слой работы с БД SQLite (станции, цены, подписки, отметки)
├── config.py                  # Конфигурация проекта и переменные окружения
├── stations.json              # Базовый реестр АЗС с координатами и адресами
├── requirements.txt           # Python-зависимости
├── toplivo-bot.service        # Systemd unit для запуска бота в фоне
│
├── map/                       # Модуль веб-карты (Telegram WebApp & Web)
│   ├── server.py              # HTTP & WebSocket сервер (API, раздача статики, HMAC auth)
│   ├── index.html             # Карта на Leaflet.js
│   ├── admin.html             # Панель администратора
│   ├── partner.html           # Кабинет партнера АЗС
│   └── station_roads.json     # Геометрия дорог и маршрутов к станциям
│
├── whatsapp/                  # Модуль интеграции с WhatsApp
│   ├── index.mjs              # Слушатель чатов на базе @whiskeysockets/baileys
│   ├── config.json            # Идентификаторы целевых групп
│   └── package.json           # Зависимости Node.js
│
├── scripts/                   # Парсеры и автоматизация
│   ├── telegram_listener.py   # Telethon MTProto слушатель Telegram-чатов
│   ├── parse_siboil_prices.py # Парсер цен Сибойл
│   ├── parse_sngs_stations.py # Парсер АЗС СНГС
│   ├── parse_paritet.py       # Парсер АЗС Паритет
│   ├── parse_tuneft.py        # Парсер АЗС Туймаада-Нефть
│   ├── parse_sberazs.py       # Парсер доступности СберАЗС
│   ├── parse_sakhaday.py      # Парсер новостей SakhaDay
│   ├── hermes_parser.py       # AI-парсер сообщений естественного языка
│   ├── hermes_insights.py     # Аналитический AI-модуль
│   ├── learn_from_history.py  # Дообучение словаря ориентиров на истории
│   └── post_to_channel.py     # Публикация дайджестов в канал @toplivo_ykt
│
└── data/                      # Рабочие словари и кэши
    ├── hermes_synonyms.json   # Словарь топонимов и синонимов АЗС
    └── hermes_insights.json   # Аналитические срезы
```

---

## 🚀 Установка и запуск

### 1. Клонирование репозитория:
```bash
git clone git@github.com:alv1k/toplivo-ykt.git
cd toplivo-ykt
```

### 2. Настройка виртуального окружения (Python):
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Настройка переменных окружения:
Скопируйте пример конфига:
```bash
cp .env.example .env
```
Заполните параметры в `.env`:
```ini
BOT_TOKEN=your_telegram_bot_token
CHANNEL_USERNAME=@toplivo_ykt
CHANNEL_ID=-100xxxxxxxxxx
ADMIN_IDS=123456789,987654321
ADMIN_TOKEN=your_secure_admin_token
DB_PATH=fuel.db
GEMINI_API_KEY=your_gemini_or_gateway_key
```

### 4. Инициализация WhatsApp слушателя (Node.js):
```bash
cd whatsapp
npm install
node index.mjs
# Отсканируйте QR-код для привязки сессии
cd ..
```

### 5. Запуск сервисов:
- **Запуск Telegram-бота:**
  ```bash
  python3 bot.py
  ```
- **Запуск веб-сервера карты (HTTP + WebSockets):**
  ```bash
  python3 map/server.py
  ```

---

## ⏰ Расписание автоматических парсеров (Crontab)

Для автономного сбора данных рекомендуются следующие интервалы:

```cron
# Парсинг цен и наличия
0 8,20 * * * /home/alvik/toplivo-yakutsk/venv/bin/python3 /home/alvik/toplivo-yakutsk/scripts/parse_siboil_prices.py
0 8,20 * * * /home/alvik/toplivo-yakutsk/venv/bin/python3 /home/alvik/toplivo-yakutsk/scripts/parse_sngs_stations.py
0 9,21 * * * /home/alvik/toplivo-yakutsk/venv/bin/python3 /home/alvik/toplivo-yakutsk/scripts/parse_paritet.py
0 7,19 * * * /home/alvik/toplivo-yakutsk/venv/bin/python3 /home/alvik/toplivo-yakutsk/scripts/parse_tuneft.py
*/30 * * * * /home/alvik/toplivo-yakutsk/venv/bin/python3 /home/alvik/toplivo-yakutsk/scripts/parse_sberazs.py

# Обучение AI-парсера ориентиров
30 3 * * * /home/alvik/toplivo-yakutsk/venv/bin/python3 /home/alvik/toplivo-yakutsk/scripts/learn_from_history.py
```

---

## 🛡️ Безопасность и конфиденциальность

- Сессионные ключи (`whatsapp/auth_info/`, `data/*.session`), переменные окружения (`.env`), базы данных (`*.db`) и кэши исключены из системы контроля версий [.gitignore](.gitignore).
- WebApp валидирует подлинность входящих данных через криптографическую подпись Telegram HMAC-SHA256.

---

## 👤 Автор

**Алена Алексеева**
- **Проект:** [@toplivo_ykt_bot](https://t.me/toplivo_ykt_bot)
- **Канал:** [@toplivo_ykt](https://t.me/toplivo_ykt)
