import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "@toplivo_ykt")
CHANNEL_ID = os.getenv("CHANNEL_ID")
if CHANNEL_ID:
    CHANNEL_ID = int(CHANNEL_ID)
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x]
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "toplivo_admin_2026")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

DB_PATH = os.getenv("DB_PATH", "fuel.db")
if not os.path.isabs(DB_PATH):
    DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), DB_PATH)
