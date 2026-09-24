import json
import os
import re
import sys
import urllib.request
import html as html_mod

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

URL = "https://t.me/s/sakhaday"
STATE_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "sakhaday_state.json")

KEYWORD_PATTERNS = [
    r'сибойл', r'siboyl',
    r'саханефтегазсбыт', r'нефтегазсбыт',
    r'топливн',
    r'\bазс\b',
    r'бензин',
    r'дизель',
    r'\bдт\b',
    r'топливн(?:ые?)? карт',
    r'\bкарт',
]

def fetch_page():
    req = urllib.request.Request(URL, headers={
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'
    })
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read().decode('utf-8')

def parse_messages(html):
    pattern = (
        r'<div class="tgme_widget_message_wrap[^"]*"[^>]*>'
        r'.*?<div class="tgme_widget_message[^"]*"[^>]*data-post="([^"]+)"'
        r'.*?<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>'
        r'.*?<time datetime="([^"]+)"'
    )
    matches = re.findall(pattern, html, re.DOTALL)
    result = []
    for post_id, text_html, timestamp in matches:
        text = re.sub(r'<[^>]+>', ' ', text_html)
        text = html_mod.unescape(text)
        text = re.sub(r'\s+', ' ', text).strip()
        result.append({
            'post_id': post_id,
            'text': text,
            'url': f'https://t.me/{post_id}',
            'timestamp': timestamp,
        })
    return result

def is_relevant(text):
    lower = text.lower()
    for pat in KEYWORD_PATTERNS:
        if re.search(pat, lower):
            return True
    return False

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {'seen': []}

def save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f)

def notify_admin(msg):
    text = (
        f'📰 <b>Новости @sakhaday</b>\n\n'
        f'{msg["text"][:500]}\n\n'
        f'🔗 <a href="{msg["url"]}">Перейти к посту</a>'
    )
    for admin_id in config.ADMIN_IDS:
        url = f'https://api.telegram.org/bot{config.BOT_TOKEN}/sendMessage'
        body = json.dumps({
            'chat_id': admin_id,
            'text': text,
            'parse_mode': 'HTML',
            'disable_web_page_preview': True,
        }).encode()
        req = urllib.request.Request(url, data=body, headers={'Content-Type': 'application/json'})
        urllib.request.urlopen(req, timeout=10)

def main():
    print(f"[{__import__('datetime').datetime.now()}] Fetching {URL}...")
    state = load_state()
    seen = set(state.get('seen', []))

    html = fetch_page()
    messages = parse_messages(html)
    print(f"  Parsed {len(messages)} messages")

    relevant = [m for m in messages if is_relevant(m['text'])]
    print(f"  Relevant: {len(relevant)}")

    new_findings = [m for m in relevant if m['post_id'] not in seen]
    print(f"  New: {len(new_findings)}")

    for msg in new_findings:
        try:
            notify_admin(msg)
            seen.add(msg['post_id'])
            print(f"  Notified: {msg['post_id']}")
        except Exception as e:
            print(f"  Failed to notify {msg['post_id']}: {e}")

    save_state({'seen': list(seen)})

if __name__ == '__main__':
    main()
