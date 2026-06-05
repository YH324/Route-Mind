#!/usr/bin/env python3
"""快速测试迭代脚本"""
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from app_service import run_agent

def test(goal, lat=30.657, lng=104.082, radius=3000):
    print(f"\n{'='*60}")
    print(f"测试: {goal}")
    print(f"{'='*60}")
    r = run_agent({"goal": goal, "center_lat": lat, "center_lng": lng, "radius": radius})
    if not r["ok"]:
        print("失败:", r.get("error", r.get("notice", "unknown")))
        return
    result = r.get("result", {})
    variants = result.get("variants", [])
    constraints = result.get("constraints", {})
    print(f"意图: {constraints.get('intent_type', '?')} | 偏好: {constraints.get('preferred_tags', [])}")
    print(f"起始时间: {constraints.get('start_time', '?')} | 预算: {constraints.get('time_budget_hours', '?')}h")
    print(f"顺序约束: {constraints.get('sequence', [])}")
    if not variants:
        print("无变体结果")
        print("notice:", r.get("notice", ""))
        return
    for route in variants:
        name = route.get("variant_id", "?")
        steps = route.get("route", [])
        recs = route.get("recommendations", [])
        print(f"\n  [{name}] {route.get('name', '')}")
        if recs:
            print(f"    推荐列表 ({len(recs)} 个):")
            for rec in recs:
                h = rec.get("business_hours", {})
                hours_str = f"{h.get('open_time','?')}-{h.get('close_time','?')}" if h else "?"
                print(f"    - {rec['name']} ({rec['type']}) 评分:{rec['score']} 营业:{hours_str}")
        if steps:
            print(f"    路线 ({len(steps)} 个POI):")
            for s in steps:
                move = ""
                if "move_from_prev" in s:
                    m = s["move_from_prev"]
                    move = f" 移动{m['distance_m']:.0f}m/{m['time_min']:.0f}min"
                elif "move_from_start" in s:
                    m = s["move_from_start"]
                    move = f" 起点{m['distance_m']:.0f}m/{m['time_min']:.0f}min"
                print(f"      {s['order']}. {s['name']} ({s['type']}) {s['arrival_time']}-{s['departure_time']}{move}")
            total = route.get("total_time_minutes", 0)
            move_total = route.get("total_move_time", 0)
            print(f"      总耗时: {total}min 移动: {move_total}min")

# 典型场景
test("想吃火锅")
test("成都一日游")
test("吃完火锅去茶馆")
test("情侣约会")
test("春熙路附近逛街")
test("早上9点去公园")
