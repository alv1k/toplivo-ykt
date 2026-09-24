#!/usr/bin/env python3
"""
Hermes AI Parser for Toplivo Yakutsk.
Uses Gemini API to parse complex/vernacular fuel status messages and learn local landmarks.
"""
import os
import sys
import json
import re
import time
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import config
import db

SYNONYMS_FILE = os.path.join(BASE_DIR, "data", "hermes_synonyms.json")
GEMINI_MODELS = [
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-flash-latest"
]
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

def load_synonyms():
    if os.path.exists(SYNONYMS_FILE):
        try:
            with open(SYNONYMS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"synonyms": {}, "history": []}

def save_learned_synonym(phrase, matched_address, brand, station_id=None):
    if not phrase or not matched_address:
        return
    phrase_clean = phrase.lower().strip()
    # Игнорируем слишком общие слова, которые могут быть в десятке мест
    AMBIGUOUS_WORDS = {"круговая", "кольцо", "круг", "заправка", "азс", "город", "центр", "трасса"}
    if phrase_clean in AMBIGUOUS_WORDS:
        return

    data = load_synonyms()
    data["synonyms"][phrase_clean] = {
        "target_address": matched_address,
        "brand": brand,
        "station_id": station_id,
        "learned_at": datetime.now().isoformat()
    }
    data["history"].append({
        "phrase": phrase,
        "matched_address": matched_address,
        "station_id": station_id,
        "timestamp": datetime.now().isoformat()
    })
    data["history"] = data["history"][-1000:]
    try:
        with open(SYNONYMS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[Hermes Memory Error] {e}", file=sys.stderr)

def get_stations_context():
    """Загружает список станций для контекста модели."""
    conn = db.get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, name, brand, address FROM stations WHERE address != '' OR name != ''")
        rows = cur.fetchall()
        return [{"id": r["id"], "name": r["name"], "brand": r["brand"], "address": r["address"]} for r in rows]
    finally:
        conn.close()

def parse_with_hermes(text: str, reply_text: str = None, max_retries: int = 3):
    """
    Отправляет текст в Gemini API и возвращает структурированный результат с автоповторами.
    Поддерживает контекст диалога (reply_text/цитирование).
    """
    api_key = config.GEMINI_API_KEY
    if not api_key:
        print("[Hermes] GEMINI_API_KEY is not configured.", file=sys.stderr)
        return None

    stations = get_stations_context()
    compact_stations = [f"{s['id']}|{s.get('brand','')}|{s.get('address','')}" for s in stations if s.get('address') or s.get('name')]
    stations_str = "; ".join(compact_stations)

    synonyms_data = load_synonyms()
    known_synonyms = synonyms_data.get("synonyms", {})
    compact_synonyms = [f"{k}->{v.get('matched_address','')}" for k, v in list(known_synonyms.items())[-80:]]
    synonyms_str = "; ".join(compact_synonyms)

    system_prompt = f"""Ты — интеллектуальный диспетчер мониторинга топлива на АЗС Якутии (Якутск и улусы).
Твоя задача — извлечь из сообщения водителя информацию о наличии топлива, очередях, лимитах и сопоставить с конкретной АЗС.
Если указан контекст вопроса/цитаты (reply_text), извлеки АЗС или топливо из вопроса, а статус/очередь из ответа.

ТОПОНИМИЧЕСКИЕ ПРАВИЛА ЯКУТСКА:
1. 'перед жатаем' / 'жатайский перекресток' / 'жатайский круг' -> СНГС АЗС №6 (Жатайский перекресток, 1). Если явно указан только газ -> АГЗС Газ (Жатай).
2. 'круговая' / 'кольцо' — НЕОДНОЗНАЧНО, так как колец много (Покровский 7 км, Вилюйский 3 км, Дзержинского, ГИБДД, Жатай). Привязывай ТОЛЬКО если в тексте есть название шоссе или района.
3. 'прометей' / 'красильникова' -> СНГС АЗС №1 (ул. Красильникова / пр. Михаила Николаева, 19/1А).
4. 'грэс' / 'даркылах' -> ул. 50 лет Советской Армии. НЕОДНОЗНАЧНО: на улице находятся АЗС Саханефтегазсбыт (№51), СибОйл (№8, №14), Туймаада-Нефть (№617) и АГЗС Энерготрейд. Требуется уточнение по бренду/номеру дома/ориентиру.
5. 'столичка' -> НЕОДНОЗНАЧНО (в зависимости от контекста: начало пробки к СНГС ул. Труда, либо АЗС/АГЗС на Хатын-Юряхском шоссе).
6. 'ураса' -> Туймаада-Нефть (ул. Автострада 50 лет Октября, 14з).
7. 'птичка' / 'птицефабрика' -> мкр. Птицефабрика. В микрорайоне нет АЗС/АГЗС, не сопоставлять со станцией без прямого указания тракта/шоссе.
8. 'цой' -> СибОйл (Покровский тракт 7 км, 1а).
9. 'хатынка' -> МАЗС Саханефтегазсбыт №62 (Хатын-Юряхское шоссе 4 км, 8а).

ПРАВИЛА ОБРАБОТКИ ВОПРОСОВ И ОТВЕТОВ (КРИТИЧЕСКИ ВАЖНО):
1. Если текущее сообщение водителя является ВОПРОСОМ (содержит знаки '?', '⁇' или вопросительные обороты вроде "где продают?", "где есть 95?", "есть ли?", "отпускают ли?", "кто знает?", "на 51 есть 95?", "где свободно?"):
   - НЕЛЬЗЯ отмечать наличие/лимит/отсутствие топлива как факт! Вопрос — это запрос, а не отчёт.
   - fuels ОБЯЗАНЫ быть ВСЕ null!
   - "is_question": true
   - Если в вопросе упомянута конкретная АЗС (например "на 51 есть 95?"), можно определить station_id (для сохранения вопроса в буфер ожидания ответа), но fuels ВСЕ null!
2. Если указан контекст вопроса/цитаты (reply_text):
   - Только при наличии ответа факт фиксируется: АЗС или марка берутся из вопроса (reply_text), а подтверждение/статус/лимит — из ответа (text).

СПРАВОЧНИК СТАНЦИЙ [id|бренд|адрес]:
{stations_str}

ИЗВЕСТНЫЕ НАРОДНЫЕ СИНОНИМЫ И ТОПОНИМЫ:
{synonyms_str}

ТРЕБОВАНИЯ К ФОРМАТУ ОТВЕТА:
Верни ТОЛЬКО валидный JSON со следующей структурой:
{{
  "is_question": <true если сообщение является вопросом, иначе false>,
  "station_id": <int или null>,
  "brand": "<название бренда или ''>",
  "matched_address": "<адрес из справочника или ''>",
  "fuels": {{
    "92": "yes" | "no" | "limit" | "queue" | null,
    "95": "yes" | "no" | "limit" | "queue" | null,
    "98": "yes" | "no" | "limit" | "queue" | null,
    "100": "yes" | "no" | "limit" | "queue" | null,
    "dt": "yes" | "no" | "limit" | "queue" | null,
    "gas": "yes" | "no" | "limit" | "queue" | null
  }},
  "details": {{
    "limit_liters": <int или null>,
    "queue_level": "low" | "medium" | "high" | null,
    "note": "<краткий комментарий о ситуации или текст вопроса>"
  }},
  "new_learned_landmark": {{
    "phrase": "<новое народное название ориентира из текста, кроме общих слов вроде 'кольцо'>",
    "matched_address": "<к какому адресу это относится>"
  }},
  "confidence": <float от 0.0 до 1.0>
}}
"""

    user_msg = f"Сообщение водителя:\n{text}"
    if reply_text:
        user_msg = f"Контекст (вопрос / цитируемое сообщение):\n{reply_text}\n\nОтвет / текущее сообщение:\n{text}"

    # 1. Сначала пробуем локальный Zero-Trust шлюз AGY Inference
    try:
        req_agy = urllib.request.Request(
            "http://127.0.0.1:8799/v1/chat/completions",
            data=json.dumps({
                "model": "gemini-3.7-flash",
                "messages": [
                    {"role": "user", "content": f"{system_prompt}\n\n{user_msg}"}
                ],
                "temperature": 0.1
            }).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-Internal-Key": "c1f2119335fb922ccb4fd2e898901448ab1b587eb849106b"
            },
            method="POST"
        )
        with urllib.request.urlopen(req_agy, timeout=25) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            content = res_data["choices"][0]["message"]["content"].strip()
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                parsed = json.loads(json_match.group(0))
            else:
                parsed = json.loads(content)
            
            new_landmark = parsed.get("new_learned_landmark")
            if new_landmark and new_landmark.get("phrase") and new_landmark.get("matched_address"):
                save_learned_synonym(
                    phrase=new_landmark["phrase"],
                    matched_address=new_landmark["matched_address"],
                    brand=parsed.get("brand", ""),
                    station_id=parsed.get("station_id")
                )
            return parsed
    except Exception as e:
        print(f"[Hermes Parser] AGY local gateway bypass/fail ({e}), falling back to external Gemini API", file=sys.stderr)

    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": system_prompt},
                    {"text": user_msg}
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
                    
                    new_landmark = parsed.get("new_learned_landmark")
                    if new_landmark and new_landmark.get("phrase") and new_landmark.get("matched_address"):
                        save_learned_synonym(
                            phrase=new_landmark["phrase"],
                            matched_address=new_landmark["matched_address"],
                            brand=parsed.get("brand", ""),
                            station_id=parsed.get("station_id")
                        )
                        
                    return parsed
            except Exception as e:
                if attempt < max_retries:
                    time.sleep(attempt * 2)
                else:
                    print(f"[Hermes Parser] Model {model_name} failed: {e}", file=sys.stderr)
                    break

    print(f"[Hermes Parser Error] All models failed after retries.", file=sys.stderr)
    return None

if __name__ == "__main__":
    test_msg = "На снгс возле урасы 92 есть, но 95 только по талонам до 20 литров, очередь средняя"
    if len(sys.argv) > 1:
        test_msg = " ".join(sys.argv[1:])
    print(f"Тестирование сообщения: '{test_msg}'\n")
    res = parse_with_hermes(test_msg)
    print(json.dumps(res, ensure_ascii=False, indent=2))
