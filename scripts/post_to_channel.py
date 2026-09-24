import os, json, urllib.request, urllib.parse
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

token = os.getenv("BOT_TOKEN")
channel = os.getenv("CHANNEL_USERNAME", "@toplivo_ykt")

text = "".join([
    chr(128293), " Обстановка на заправках Якутска (28.07.2026)\n\n",
    chr(128693), " Туймаада-Нефть:\n",
    "\u2022 Автоматические АЗС \u2014 только по топливным картам, новые не оформляются\n",
    "\u2022 АЗС с кассиром: АИ-95 и ДТ \u2014 только по топливным картам\n",
    "\u2022 АИ-92, АИ-98 \u2014 лимит 20 л\n",
    "\u2022 Цены: 92=", "93", chr(8381), ", 95=", "96", chr(8381), ", ДТ=", "106", chr(8381), "\n\n",
    chr(128693), " Саханефтегазсбыт:\n",
    "\u2022 Автоматические АЗС (№1,3,4) \u2014 только по топливным картам, новые не оформляются\n",
    "\u2022 АЗС с кассиром: бензин \u2014 лимит 20 л, ДТ \u2014 лимит 50 л\n",
    "\u2022 АЗС №51 (50 лет Советской Армии): бензин \u2014 30 л, ДТ \u2014 200 л\n\n",
    chr(128693), " СибОйл:\n",
    "\u2022 Все АЗС \u2014 по топливным картам или приложению \u00abСибОйл\u00bb, лимит 50 л/день\n",
    "\u2022 Цены: 92=90", chr(8381), ", 95=93", chr(8381), ", ДТ=107", chr(8381), "\n\n",
    chr(128506), " Актуальная карта: https://344988.snk.wtf/fuel-map/"
])

data = urllib.parse.urlencode({"chat_id": channel, "text": text, "parse_mode": "HTML"}).encode("utf-8")
url = "https://api.telegram.org/bot" + token + "/sendMessage"
req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded; charset=utf-8"})
resp = urllib.request.urlopen(req)
print(resp.read().decode())