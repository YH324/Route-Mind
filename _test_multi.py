#!/usr/bin/env python3
import json
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from route_planner_v3 import build_plan_v3
from mock_api import MockApiClient

DATA_DIR = os.path.join(SCRIPT_DIR, "output")

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

api = MockApiClient(city="chengdu", simulate_latency_ms=0, simulate_quota=False)
poi_resp = api.search_pois(104.082, 30.657, radius=3000, page=1, page_size=10000)
pois = []
for p in poi_resp.get("pois", []):
    lng_p, lat_p = p["location"].split(",")
    pois.append({
        "poi_id": p["id"], "name": p["name"],
        "type": p["type"], "typecode": p["typecode"],
        "address": p["address"],
        "longitude": float(lng_p), "latitude": float(lat_p),
        "cityname": p["cityname"], "adname": p["adname"],
        "tags": p["tag"].split(",") if p["tag"] else [],
        "tel": p.get("tel", ""),
    })

gt_index = load_json(os.path.join(DATA_DIR, "gt_index.json"))
type_index = load_json(os.path.join(DATA_DIR, "type_index.json"))
spatial_index = load_json(os.path.join(DATA_DIR, "spatial_index.json"))

test_queries = [
    ("春熙路附近逛街", "single_poi"),
    ("想吃火锅", "single_poi"),
    ("早上9点去公园", "single_poi"),
    ("成都一日游", "complex_route"),
    ("吃完火锅去茶馆", "simple_route"),
    ("情侣约会", "single_poi"),
]

for goal, expected_intent in test_queries:
    print(f"\n{'='*60}")
    print(f"Query: {goal}")
    print(f"{'='*60}")
    result = build_plan_v3(
        goal=goal,
        pois=pois, gt_data=gt_index,
        center_lng=104.082, center_lat=30.657, radius=3000,
        spatial_index=spatial_index, type_index=type_index,
    )
    actual_intent = result.get("constraints", {}).get("intent_type", "?")
    status = "OK" if actual_intent == expected_intent else "MISMATCH"
    print(f"Intent: {actual_intent} | expected={expected_intent} [{status}]")
    if result["variants"]:
        variant = result["variants"][0]
        print(f"Variant: {variant['variant_id']}")
        recs = variant.get("recommendations", [])
        route = variant.get("route", [])
        if recs:
            print(f"Recommendations ({len(recs)}):")
            for rec in recs[:10]:
                print(f"  {rec['name']} ({rec['type']}) score={rec['score']}")
        elif route:
            print(f"Route ({len(route)} stops):")
            for step in route[:10]:
                print(f"  {step['name']} ({step['type']}) arr={step['arrival_time']} stay={step['stay_minutes']}min")
        else:
            print("No recommendations or route.")
    else:
        print("No variants returned.")
