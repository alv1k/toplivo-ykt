#!/usr/bin/env python3
"""
Hermes Historical Learning Script (Batch Mode).
Scans past comments in fuel.db, extracts vernacular landmarks in batches,
and populates hermes_synonyms.json using minimal Gemini API requests.
"""
import os
import sys
import time
import json
import urllib.request
import urllib.error
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import db
import config
from scripts.hermes_parser import (
    load_synonyms,
    save_learned_synonym,
    get_stations_context,
    SYNONYMS_FILE,
    GEMINI_API_URL,
    GEMINI_MODELS
)

# Ключевые слова-маркеры топонимов и локаций
LOCATION_KEYWORDS = {
    "ул", "ул.", "улица", "шоссе", "тракт", "перекресток", "круг", "кольцо",
    "район", "возле", "около", "напротив", "рядом", "поворот", "остановка",
    "жатай", "грэс", "прометей", "красильникова", "даркылах", "ураса", "цой",
    "хатынка", "хатын", "юрях", "покровский", "намцы", "сергелях", "автострада",
    "дзержинского", "лермонтова", "кальвица", "вилюйский", "марха", "маган",
    "кирова", "кулаковского", "чернышевского", "октябрьская", "богдана", "чиряева"
}

def is_candidate_for_learning(text: str) -> bool:
    """Локально отсекает сообщения без топонимов перед отправкой в LLM (экономия токенов)."""
    clean = text.lower().strip()
    if len(clean) < 6:
        return False
    # Игнорируем типовые короткие отчеты без упоминания ориентиров
    words = set(clean.replace(",", " ").replace(".", " ").replace(":", " ").split())
    if not words:
        return False
    # Проверяем пересечение с маркерами локаций
    if any(kw in clean for kw in LOCATION_KEYWORDS):
        return True
    # Если в тексте 4+ слова и есть упоминание брендов
    brands = {"снгс", "сибойл", "туймаада", "паритет", "саханефтегазсбыт", "энергаз", "энерготрейд"}
    if len(words) >= 4 and any(b in clean for b in brands):
        return True
    return False

def analyze_batch_with_gemini(items: list, max_retries: int = 3):
    """
    Отправляет отфильтрованную пачку сообщений в LLM (локальный AGY шлюз или Gemini API).
    """
    # Компактный справочник станций (сжатие токенов на ~75%)
    stations = get_stations_context()
    compact_stations = [f"{s['id']}|{s.get('brand','')}|{s.get('address','')}" for s in stations if s.get('address')]

    synonyms_data = load_synonyms()
    known_keys = list(synonyms_data.get("synonyms", {}).keys())[-100:]  # последние 100 синонимов

    system_prompt = f"""Ты — аналитик народных названий АЗС Якутии.
Извлеки из сообщений новые народные названия ориентиров/топонимов и сопоставь с АЗС.

ТОПОНИМЫ: жатай->СНГС Жатай; прометей/красильникова->СНГС №1 (Красильникова 19/1А); грэс/даркылах->50 лет Сов.Армии; ураса->Туймаада (Автострада 14з); цой->СибОйл (Покровский 7км); хатынка->СНГС (Хатын-Юряхское 4км).

СПРАВОЧНИК [id|бренд|адрес]:
{'; '.join(compact_stations)}

УЖЕ ИЗВЕСТНЫЕ: {', '.join(known_keys)}

Верни JSON массив объектов:
[{{"message_id": <int>, "phrase": "<народное название>", "matched_address": "<адрес>", "brand": "<бренд>", "station_id": <int|null>}}]
Если новых полезных ориентиров нет, верни [].
"""

    user_payload = []
    for it in items:
        user_payload.append({
            "message_id": it["id"],
            "text": it["text"],
            "actual_station": f"{it['brand'] or ''} ({it['address'] or ''})"
        })

    # 1. Сначала пробуем локальный Zero-Trust шлюз AGY Inference
    try:
        req_agy = urllib.request.Request(
            "http://127.0.0.1:8799/v1/chat/completions",
            data=json.dumps({
                "model": "gemini-3.7-flash",
                "messages": [
                    {"role": "user", "content": f"{system_prompt}\n\nСообщения для анализа:\n{json.dumps(user_payload, ensure_ascii=False)}"}
                ],
                "temperature": 0.1
            }).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-Internal-Key": "c1f2119335fb922ccb4fd2e898901448ab1b587eb849106b"
            },
            method="POST"
        )
        with urllib.request.urlopen(req_agy, timeout=30) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            content = res_data["choices"][0]["message"]["content"].strip()
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:].strip()
            parsed = json.loads(content)
            return parsed if isinstance(parsed, list) else []
    except Exception as e:
        print(f"[Hermes Batch] AGY local gateway fail/bypass ({e}), falling back to Gemini API", file=sys.stderr)

    api_key = config.GEMINI_API_KEY
    if not api_key:
        print("[Error] GEMINI_API_KEY is not configured.", file=sys.stderr)
        return []

    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": system_prompt},
                    {"text": f"Сообщения для анализа:\n{json.dumps(user_payload, ensure_ascii=False)}"}
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "application/json"
        }
    }

    req_data = json.dumps(payload).encode("utf-8")

    for model_name in GEMINI_MODELS:
        url = f"{GEMINI_API_URL.format(model=model_name)}?key={api_key}"
        for attempt in range(1, max_retries + 1):
            try:
                req = urllib.request.Request(
                    url,
                    data=req_data,
                    headers={"Content-Type": "application/json"},
                    method="POST"
                )
                with urllib.request.urlopen(req, timeout=25) as response:
                    res_data = json.loads(response.read().decode("utf-8"))
                    content = res_data["candidates"][0]["content"]["parts"][0]["text"].strip()
                    if content.startswith("```"):
                        content = content.split("```")[1]
                        if content.startswith("json"):
                            content = content[4:].strip()
                    parsed = json.loads(content)
                    return parsed if isinstance(parsed, list) else []
            except Exception as e:
                if attempt < max_retries:
                    time.sleep(attempt * 2)
                else:
                    print(f"[Hermes Batch Error] Model {model_name} failed: {e}", file=sys.stderr)
                    break

    return []

def run_history_learning(limit=60, batch_size=20, delay=5.0):
    """
    Анализирует последние комментарии пачками (батчами) по batch_size за один вызов API.
    """

    conn = db.get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT c.id, c.station_id, c.comment, s.brand, s.name, s.address 
        FROM comments c
        LEFT JOIN stations s ON c.station_id = s.id
        WHERE c.comment IS NOT NULL AND length(c.comment) > 7
        ORDER BY c.id DESC
        LIMIT ?
    """, (limit,))
    rows = cur.fetchall()
    conn.close()

    items = []
    for r in rows:
        comment_text = r["comment"]
        # Чистим префиксы
        clean_text = comment_text.split("📍")[0].replace("💬:", "").strip()
        if not is_candidate_for_learning(clean_text):
            continue
        items.append({
            "id": r["id"],
            "station_id": r["station_id"],
            "text": clean_text,
            "brand": r["brand"],
            "name": r["name"],
            "address": r["address"]
        })

    print(f"=== Hermes Batch History Learning: {len(items)} релевантных сообщений из {len(rows)} (батчи по {batch_size}) ===")
    total_learned = 0

    for i in range(0, len(items), batch_size):
        batch = items[i:i + batch_size]
        batch_num = (i // batch_size) + 1
        total_batches = (len(items) + batch_size - 1) // batch_size
        print(f"\n[Батч {batch_num}/{total_batches}] Отправка {len(batch)} сообщений в Gemini...")

        results = analyze_batch_with_gemini(batch)
        print(f"-> Получено {len(results)} потенциальных ориентиров.")

        for res in results:
            phrase = res.get("phrase")
            matched_addr = res.get("matched_address")
            brand = res.get("brand", "")
            station_id = res.get("station_id")

            if phrase and matched_addr:
                save_learned_synonym(phrase, matched_addr, brand, station_id)
                print(f"   ✨ Сохранён ориентир: '{phrase}' -> {brand} ({matched_addr})")
                total_learned += 1

        if i + batch_size < len(items):
            time.sleep(delay)

    print(f"\n✅ Обучение завершено! Добавлено ориентиров: {total_learned}")
    print(f"База сохранена в: {SYNONYMS_FILE}")
    return {
        "status": "ok",
        "items_total": len(rows),
        "items_filtered": len(items),
        "total_learned": total_learned,
        "synonyms_file": SYNONYMS_FILE
    }

if __name__ == "__main__":
    count = 50
    if len(sys.argv) > 1:
        count = int(sys.argv[1])
    run_history_learning(limit=count)

