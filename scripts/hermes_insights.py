#!/usr/bin/env python3
"""
Hermes AI Product & Feature Advisor for Toplivo Yakutsk.
Analyzes driver chatter, comments, and queues to propose UX/feature improvements and sends reports to Admin.
"""
import os
import sys
import json
import time
import urllib.request
import urllib.parse
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import config
import db

INSIGHTS_FILE = os.path.join(BASE_DIR, "data", "hermes_insights.json")
GEMINI_MODELS = [
    "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent",
    "https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent"
]

def get_recent_driver_feedback(limit=60):
    conn = db.get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT c.comment, s.brand, s.name, s.address, c.created_at
        FROM comments c
        LEFT JOIN stations s ON c.station_id = s.id
        WHERE c.comment IS NOT NULL AND length(c.comment) > 8
        ORDER BY c.id DESC
        LIMIT ?
    """, (limit,))
    rows = cur.fetchall()
    conn.close()
    return [
        f"[{r['created_at']}] {r['brand']} {r['name']} ({r['address']}): {r['comment']}"
        for r in rows
    ]

def generate_insights_and_suggestions():
    feedback_list = get_recent_driver_feedback(60)
    if not feedback_list:
        print("[Hermes Insights] No recent feedback found.")
        return None

    feedback_text = "\n".join(feedback_list)

    prompt = f"""Ты — Senior Product Manager и Data Analyst картографического сервиса 'Топливо Якутия' (интерактивная карта наличия бензина/газа на АЗС г. Якутска и пригородов).

Вот свежие 60 сообщений и отзывов реальных водителей из чатов и комментариев:
---
{feedback_text}
---

Сделай глубокий анализ болей пользователей (Pain Points) и предложи конкретные фичи для улучшения бота и интерактивной карты Leaflet.

ВЕРНИ ТОЛЬКО ВАЛИДНЫЙ JSON:
{{
  "summary": "<Краткая сводка текущей обстановки с топливом в городе>",
  "top_user_pains": [
    "<Боль 1 (например: непонятно, с какой улицы вставать в хвост очереди на АЗС Х)>",
    "<Боль 2 (например: жалобы на зависающие терминалы безналичной оплаты)>"
  ],
  "suggested_features": [
    {{
      "feature_name": "<Название фичи>",
      "target_component": "Карта" | "Бот" | "Парсер",
      "rationale": "<Почему это нужно водителям на основе их сообщений>",
      "implementation_hint": "<Как кратко реализовать (например: добавить поле в карточку станции, добавить фильтр)>"
    }}
  ],
  "anomalies_or_trends": "<Замеченные тренды (например: дефицит 95-го на конкретном тракте, рост очередей к вечеру)>"
}}
"""

    # 1. Сначала пробуем локальный Zero-Trust шлюз AGY Inference
    try:
        req_agy = urllib.request.Request(
            "http://127.0.0.1:8799/v1/chat/completions",
            data=json.dumps({
                "model": "gemini-3.7-flash",
                "messages": [
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.2
            }).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-Internal-Key": "c1f2119335fb922ccb4fd2e898901448ab1b587eb849106b"
            },
            method="POST"
        )
        with urllib.request.urlopen(req_agy, timeout=35) as resp:
            res_data = json.loads(resp.read().decode("utf-8"))
            content = res_data["choices"][0]["message"]["content"].strip()
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:].strip()
            insights = json.loads(content)

            os.makedirs(os.path.dirname(INSIGHTS_FILE), exist_ok=True)
            insights["generated_at"] = datetime.now().isoformat()

            with open(INSIGHTS_FILE, "w", encoding="utf-8") as f:
                json.dump(insights, f, ensure_ascii=False, indent=2)

            return insights
    except Exception as e:
        print(f"[Hermes Insights] AGY local gateway fail/bypass ({e}), falling back to Gemini API", file=sys.stderr)

    api_key = config.GEMINI_API_KEY
    if not api_key:
        print("[Hermes Insights] GEMINI_API_KEY is not set.", file=sys.stderr)
        return None

    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": prompt}]
            }
        ],
        "generationConfig": {
            "temperature": 0.2,
            "responseMimeType": "application/json"
        }
    }

    req_data = json.dumps(payload).encode("utf-8")

    for endpoint in GEMINI_MODELS:
        url = f"{endpoint}?key={api_key}"
        for attempt in range(1, 4):
            try:
                req = urllib.request.Request(
                    url,
                    data=req_data,
                    headers={"Content-Type": "application/json"},
                    method="POST"
                )
                with urllib.request.urlopen(req, timeout=30) as resp:
                    res_data = json.loads(resp.read().decode("utf-8"))
                    content = res_data["candidates"][0]["content"]["parts"][0]["text"]
                    insights = json.loads(content)
                    
                    os.makedirs(os.path.dirname(INSIGHTS_FILE), exist_ok=True)
                    insights["generated_at"] = datetime.now().isoformat()
                    
                    with open(INSIGHTS_FILE, "w", encoding="utf-8") as f:
                        json.dump(insights, f, ensure_ascii=False, indent=2)
                        
                    return insights
            except Exception as e:
                time.sleep(attempt * 4)

    return None

def send_telegram_digest(insights):
    if not insights or not config.BOT_TOKEN or not config.ADMIN_IDS:
        return

    features_text = ""
    for idx, feat in enumerate(insights.get("suggested_features", [])[:4], 1):
        features_text += (
            f"\n💡 <b>{idx}. {feat.get('feature_name')}</b> [{feat.get('target_component')}]\n"
            f"   • <i>Зачем:</i> {feat.get('rationale')}\n"
            f"   • <i>Как:</i> {feat.get('implementation_hint')}\n"
        )

    pains_text = "\n".join([f"• {p}" for p in insights.get("top_user_pains", [])[:3]])

    tg_message = (
        f"🧠 <b>AI Product Digest — Топливо Якутия</b>\n\n"
        f"📊 <b>Обстановка:</b>\n{insights.get('summary', '')}\n\n"
        f"⚠️ <b>Главные боли водителей:</b>\n{pains_text}\n\n"
        f"🚀 <b>Предложения по новым фичам:</b>"
        f"{features_text}\n"
        f"📈 <b>Тренды:</b>\n{insights.get('anomalies_or_trends', '')}"
    )

    for admin_id in config.ADMIN_IDS:
        try:
            url = f"https://api.telegram.org/bot{config.BOT_TOKEN}/sendMessage"
            body = json.dumps({
                "chat_id": admin_id,
                "text": tg_message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            }).encode("utf-8")
            req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=10)
            print(f"[Hermes Digest] Sent to admin {admin_id}")
        except Exception as e:
            print(f"[Hermes Digest Error] {e}", file=sys.stderr)

if __name__ == "__main__":
    send_tg = "--send" in sys.argv
    print("Генерация продуктовых инсайтов на основе отзывов водителей...")
    res = generate_insights_and_suggestions()
    if res:
        print(json.dumps(res, ensure_ascii=False, indent=2))
        if send_tg:
            send_telegram_digest(res)
