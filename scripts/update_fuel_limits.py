import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db

ADMIN_TG_ID = 364224373

def set_price(sid, fc, price):
    db.set_price(sid, fc, price)
    print(f"    price {fc} -> {price}")

def add_mark(sid, fc, status):
    db.add_mark(sid, fc, status, ADMIN_TG_ID, 'admin')
    print(f"    mark {fc} -> {status}")

def get_stations(brand, city=None):
    conn = db.get_conn()
    if city:
        rows = conn.execute("SELECT id, name, address, automatic FROM stations WHERE brand = ? AND city = ? ORDER BY name", (brand, city)).fetchall()
    else:
        rows = conn.execute("SELECT id, name FROM stations WHERE brand = ? ORDER BY name", (brand,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def update_tuneft_prices():
    print("\n=== ТУЙМААДА-НЕФТЬ: обновление цен ===")
    stations = get_stations('Туймаада-Нефть', 'Якутск')
    for s in stations:
        print(f"  {s['name']}")
        for fc, pr in [('92',93),('95',96),('dt',106)]:
            set_price(s['id'], fc, pr)

def add_tuneft_marks():
    print("\n=== ТУЙМААДА-НЕФТЬ: marks ===")
    stations = get_stations('Туймаада-Нефть', 'Якутск')
    for s in stations:
        print(f"  {s['name']} aut={s['automatic']}")
        if s['automatic']:
            print("    -> automatic: все виды no")
            for fc in ['92','95','98','100','dt','gas']:
                add_mark(s['id'], fc, 'no')
        else:
            print("    -> staffed: 92,95,98 yes; dt no")
            add_mark(s['id'], '92', 'yes')
            add_mark(s['id'], '95', 'yes')
            add_mark(s['id'], '98', 'yes')
            add_mark(s['id'], 'dt', 'no')

def add_sngs_marks():
    print("\n=== САХАНЕФТЕГАЗСБЫТ ЯКУТСК: marks ===")
    stations = get_stations('Саханефтегазсбыт', 'Якутск')
    for s in stations:
        print(f"  {s['name']} ({s['address']}) aut={s['automatic']}")
        if s['automatic']:
            print("    -> automatic: все виды no")
            for fc in ['92','95','98','100','dt','gas','ts1']:
                add_mark(s['id'], fc, 'no')
        else:
            print("    -> staffed: бензин yes, ДТ yes")
            for fc in ['92','95','98','100','dt']:
                add_mark(s['id'], fc, 'yes')

def add_siboil_marks():
    print("\n=== СИБОЙЛ: marks ===")
    stations = get_stations('СибОйл')
    for s in stations:
        print(f"  {s['name']}")
        print("    -> все виды: yes")
        for fc in ['92','95','98','dt','ts1','gas']:
            add_mark(s['id'], fc, 'yes')

def update_tuneft_base_prices_in_script():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'parse_tuneft.py')
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    content = content.replace("BASE_PRICES = {'92': 77.5, '95': 81.0, '98': 87.0, 'dt': 94.5}", "BASE_PRICES = {'92': 93.0, '95': 96.0, '98': 87.0, 'dt': 106.0}")
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    print("\n== parse_tuneft.py BASE_PRICES обновлены ==")

if __name__ == '__main__':
    update_tuneft_base_prices_in_script()
    update_tuneft_prices()
    add_tuneft_marks()
    add_sngs_marks()
    add_siboil_marks()
    print("\n=== ГОТОВО ===")
