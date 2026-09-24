import sys
import os
import math
import json
import urllib.request
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db

def dist_meters(lat1, lon1, lat2, lon2):
    dlat = (lat2 - lat1) * 111139
    dlon = (lon2 - lon1) * 111139 * math.cos(math.radians((lat1 + lat2) * 0.5))
    return math.hypot(dlat, dlon)

def main():
    stations = db.load_stations()
    print(f"Loaded {len(stations)} stations from DB.")
    
    # 1. Fetch Yakutsk bbox
    print("Fetching Yakutsk roads from OSM Overpass...")
    query_ykt = """
[out:json][timeout:45];
way(61.8, 129.4, 62.4, 130.1)[highway~'^(primary|secondary|tertiary|residential|trunk|unclassified|service)$'];
(._;>;);
out body;
"""
    overpass_url = 'https://overpass-api.de/api/interpreter'
    req = urllib.request.Request(overpass_url, data=query_ykt.encode('utf-8'), headers={'User-Agent': 'ToplivoYakutskBot/1.0'})
    resp = urllib.request.urlopen(req, timeout=45)
    data = json.loads(resp.read().decode('utf-8'))
    
    nodes = {el['id']: (el['lat'], el['lon']) for el in data.get('elements', []) if el['type'] == 'node'}
    ways = [el for el in data.get('elements', []) if el['type'] == 'way']
    print(f"Retrieved {len(ways)} ways, {len(nodes)} nodes.")
    
    station_roads = {}
    missing_stations = []
    
    for s in stations:
        sid = str(s['id'])
        slat = s['lat']
        slon = s['lon']
        
        # Find nearest road way and node
        best_way = None
        best_node_idx = -1
        min_dist = 999999
        
        for w in ways:
            w_node_ids = w.get('nodes', [])
            for idx, nid in enumerate(w_node_ids):
                if nid in nodes:
                    nlat, nlon = nodes[nid]
                    d = dist_meters(slat, slon, nlat, nlon)
                    if d < min_dist and d <= 120:  # within 120 meters
                        min_dist = d
                        best_way = w
                        best_node_idx = idx
                        
        if best_way and best_node_idx >= 0:
            w_node_ids = best_way.get('nodes', [])
            all_pts = [nodes[nid] for nid in w_node_ids if nid in nodes]
            
            pts_before = []
            pts_after = []
            
            cur_d = 0
            for i in range(best_node_idx, len(all_pts) - 1):
                cur_d += dist_meters(all_pts[i][0], all_pts[i][1], all_pts[i+1][0], all_pts[i+1][1])
                pts_after.append(all_pts[i+1])
                if cur_d >= 350:
                    break
                    
            cur_d = 0
            for i in range(best_node_idx, 0, -1):
                cur_d += dist_meters(all_pts[i][0], all_pts[i][1], all_pts[i-1][0], all_pts[i-1][1])
                pts_before.insert(0, all_pts[i-1])
                if cur_d >= 350:
                    break
                    
            road_pts = pts_before + [all_pts[best_node_idx]] + pts_after
            station_roads[sid] = {
                'name': best_way.get('tags', {}).get('name', ''),
                'center_idx': len(pts_before),
                'coords': [[round(p[0], 6), round(p[1], 6)] for p in road_pts]
            }
        else:
            missing_stations.append(s)
            
    print(f"Matched {len(station_roads)} stations in Yakutsk. Missing (outside bbox / remote): {len(missing_stations)}")
    
    # Process remaining stations via around query if needed (batch 10 at a time or query)
    for s in missing_stations:
        sid = str(s['id'])
        slat = s['lat']
        slon = s['lon']
        try:
            q = f"""
[out:json][timeout:15];
way(around:150, {slat}, {slon})[highway~'^(primary|secondary|tertiary|residential|trunk|unclassified|service)$'];
(._;>;);
out body;
"""
            r = urllib.request.Request(overpass_url, data=q.encode('utf-8'), headers={'User-Agent': 'ToplivoYakutskBot/1.0'})
            res_data = json.loads(urllib.request.urlopen(r, timeout=15).read().decode('utf-8'))
            rem_nodes = {el['id']: (el['lat'], el['lon']) for el in res_data.get('elements', []) if el['type'] == 'node'}
            rem_ways = [el for el in res_data.get('elements', []) if el['type'] == 'way']
            
            best_way = None
            best_idx = -1
            min_d = 999999
            for w in rem_ways:
                for idx, nid in enumerate(w.get('nodes', [])):
                    if nid in rem_nodes:
                        nlat, nlon = rem_nodes[nid]
                        d = dist_meters(slat, slon, nlat, nlon)
                        if d < min_d:
                            min_d = d
                            best_way = w
                            best_idx = idx
            if best_way and best_idx >= 0:
                all_pts = [rem_nodes[nid] for nid in best_way.get('nodes', []) if nid in rem_nodes]
                station_roads[sid] = {
                    'name': best_way.get('tags', {}).get('name', ''),
                    'center_idx': best_idx,
                    'coords': [[round(p[0], 6), round(p[1], 6)] for p in all_pts]
                }
                print(f"  + Resolved remote station {sid} ({s['name']}) -> {len(all_pts)} pts")
            time.sleep(0.15)
        except Exception as e:
            print(f"  Failed for {sid}: {e}")
            
    out_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'map', 'station_roads.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(station_roads, f, ensure_ascii=False, indent=2)
    print(f"Saved road geometries for {len(station_roads)} stations to {out_path}")

if __name__ == '__main__':
    main()
