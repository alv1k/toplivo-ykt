import json
import urllib.request
import urllib.parse
import time

CITIES = [
    {"city": "Мирный", "lat": 62.54, "lon": 113.96},
    {"city": "Нерюнгри", "lat": 56.66, "lon": 124.72},
    {"city": "Ленск", "lat": 60.73, "lon": 114.93},
    {"city": "Алдан", "lat": 58.60, "lon": 125.39},
    {"city": "Покровск", "lat": 61.48, "lon": 129.14},
    {"city": "Вилюйск", "lat": 63.75, "lon": 121.63},
    {"city": "Олёкминск", "lat": 60.38, "lon": 120.41},
]

HIGHWAYS = [
    ("Трасса М56", [
        (56.66, 124.72),  # Нерюнгри
        (56.85, 124.90),  # Чульман
        (58.60, 125.39),  # Алдан
        (58.96, 126.28),  # Томмот
        (59.55, 126.00),  # Б.Нимныр
        (59.90, 127.10),  # Чагда
        (60.20, 128.10),  # Унгра
        (61.30, 128.90),  # Покровск р-н
        (61.80, 129.50),  # Ниж.Бестях
    ]),
    ("Трасса Р504", [
        (62.67, 135.55),  # Хандыга
        (63.00, 137.50),  # Тёплый Ключ
        (64.57, 143.23),  # Усть-Нера
    ]),
    ("Трасса Р501", [
        (62.03, 129.73),  # Якутск
        (62.00, 126.00),  # Булгунняхтах
        (62.50, 125.00),  # Хагын
        (63.45, 120.30),  # Верхневилюйск
        (63.75, 121.63),  # Вилюйск
        (63.28, 118.34),  # Нюрба
    ]),
]

def fetch_area(label, lat, lon, radius_km=8):
    radius = radius_km * 1000
    query = f"""
    [out:json];
    node["amenity"="fuel"](around:{radius},{lat},{lon});
    out body;
    """
    url = "https://overpass-api.de/api/interpreter?data=" + urllib.parse.quote(query)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ToplivoYakutsk/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"  Error at {label} ({lat},{lon}): {e}")
        return []
    stations = []
    for el in data.get("elements", []):
        tags = el.get("tags", {})
        name = tags.get("name", "").strip()
        if not name:
            name = f"АЗС"
        brand = tags.get("brand", "")
        addr = tags.get("addr:street", "") or tags.get("addr:full", "") or ""
        if tags.get("addr:housenumber"):
            addr = (addr + ", " + tags["addr:housenumber"]).strip(", ")
        stations.append({
            "name": name, "brand": brand, "lat": el["lat"], "lon": el["lon"],
            "address": addr, "city": label, "card_only": False, "excluded_fuels": [],
        })
    return stations

def main():
    path = "/home/alvik/toplivo-yakutsk/stations.json"
    with open(path, "r", encoding="utf-8") as f:
        existing = json.load(f)
    seen = {(s["lat"], s["lon"]): s for s in existing}
    total_new = 0

    for c in CITIES:
        print(f"Fetching {c['city']}...")
        new_stations = fetch_area(c["city"], c["lat"], c["lon"])
        for s in new_stations:
            key = (s["lat"], s["lon"])
            if key not in seen:
                seen[key] = s
                existing.append(s)
                total_new += 1
        print(f"  +{sum(1 for ns in new_stations if (ns['lat'],ns['lon']) in seen and ns not in existing[:len(existing)-len(new_stations)])} new")
        time.sleep(1)

    for name, points in HIGHWAYS:
        print(f"Fetching {name} ({len(points)} points)...")
        for i, (lat, lon) in enumerate(points):
            new_stations = fetch_area(name, lat, lon, radius_km=8)
            for s in new_stations:
                key = (s["lat"], s["lon"])
                if key not in seen:
                    seen[key] = s
                    existing.append(s)
                    total_new += 1
            time.sleep(1.5)

    for s in existing:
        s.setdefault("card_only", False)
        s.setdefault("excluded_fuels", [])
        s.setdefault("city", "Якутск")

    with open(path, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)

    print(f"Done. Total: {len(existing)} stations (+{total_new} new)")

if __name__ == "__main__":
    main()
