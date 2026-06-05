#!/usr/bin/env python3
"""
POI营业时间生成器

为每个POI生成营业时间，基于真实类型规则 + 随机扰动
"""
import json
import random
from ugc_type_profiles import infer_real_type

random.seed(42)

# 类型 -> (open_hour, open_minute, close_hour, close_minute, 是否跨天)
# 跨天表示 close_time < open_time（如KTV开到凌晨）
BUSINESS_HOURS_RULES = {
    "火锅":      {"open": (10, 30), "close": (2, 0),  "overnight": True,  "peak": (18, 22)},
    "烧烤":      {"open": (17, 0),  "close": (3, 0),  "overnight": True,  "peak": (20, 24)},
    "小吃":      {"open": (6, 0),   "close": (22, 0), "overnight": False, "peak": (12, 14)},
    "甜品":      {"open": (10, 0),  "close": (23, 0), "overnight": False, "peak": (14, 17)},
    "饮品":      {"open": (9, 0),   "close": (23, 30),"overnight": False, "peak": (14, 16)},
    "茶馆":      {"open": (9, 0),   "close": (23, 0), "overnight": False, "peak": (14, 17)},
    "中餐":      {"open": (10, 0),  "close": (22, 0), "overnight": False, "peak": (12, 13)},
    "外国菜":    {"open": (11, 0),  "close": (22, 30),"overnight": False, "peak": (18, 20)},
    "农家乐":    {"open": (9, 0),   "close": (21, 0), "overnight": False, "peak": (12, 14)},
    "KTV":       {"open": (13, 0),  "close": (6, 0),  "overnight": True,  "peak": (20, 24)},
    "酒吧":      {"open": (19, 0),  "close": (4, 0),  "overnight": True,  "peak": (21, 24)},
    "网吧":      {"open": (0, 0),   "close": (24, 0), "overnight": True,  "peak": (14, 18)},
    "电影院":    {"open": (10, 0),  "close": (2, 0),  "overnight": True,  "peak": (19, 22)},
    "健身":      {"open": (7, 0),   "close": (23, 0), "overnight": False, "peak": (18, 21)},
    "按摩SPA":   {"open": (11, 0),  "close": (2, 0),  "overnight": True,  "peak": (19, 22)},
    "景点":      {"open": (8, 0),   "close": (18, 0), "overnight": False, "peak": (10, 15)},
    "公园":      {"open": (6, 0),   "close": (22, 0), "overnight": False, "peak": (7, 9)},
    "游乐园":    {"open": (9, 0),   "close": (21, 0), "overnight": False, "peak": (10, 16)},
    "商场":      {"open": (10, 0),  "close": (22, 0), "overnight": False, "peak": (14, 20)},
    "超市":      {"open": (8, 0),   "close": (22, 0), "overnight": False, "peak": (18, 20)},
    "便利店":    {"open": (0, 0),   "close": (24, 0), "overnight": True,  "peak": (8, 10)},
    "数码":      {"open": (9, 0),   "close": (21, 0), "overnight": False, "peak": (14, 17)},
    "服饰":      {"open": (10, 0),  "close": (22, 0), "overnight": False, "peak": (14, 20)},
    "美妆":      {"open": (10, 0),  "close": (21, 0), "overnight": False, "peak": (14, 19)},
    "家居":      {"open": (9, 0),   "close": (20, 0), "overnight": False, "peak": (10, 16)},
    "住宿":      {"open": (0, 0),   "close": (24, 0), "overnight": True,  "peak": (14, 16)},
    "其他":      {"open": (9, 0),   "close": (21, 0), "overnight": False, "peak": (10, 17)},
}


def generate_hours(poi):
    real_type = infer_real_type(poi)
    rule = BUSINESS_HOURS_RULES.get(real_type, BUSINESS_HOURS_RULES["其他"])

    # 添加随机扰动（±30分钟）
    open_h, open_m = rule["open"]
    close_h, close_m = rule["close"]

    # 随机扰动
    open_m += random.randint(-30, 30)
    close_m += random.randint(-30, 30)

    # 规范化
    open_h += open_m // 60
    open_m = open_m % 60
    close_h += close_m // 60
    close_m = close_m % 60

    # 部分POI有午休（中餐类）
    lunch_break = None
    if real_type in ["中餐", "小吃"] and random.random() < 0.3:
        lunch_break = {"start": "14:00", "end": "17:00"}

    # 部分POI周一休息或特殊营业
    closed_days = []
    if real_type in ["景点", "博物馆"] and random.random() < 0.5:
        closed_days = ["周一"]
    if real_type in ["美容", "美发"] and random.random() < 0.3:
        closed_days = ["周二"]

    def fmt(h, m):
        return f"{h:02d}:{m:02d}"

    result = {
        "open_time": fmt(open_h, open_m),
        "close_time": fmt(close_h, close_m),
        "overnight": rule["overnight"],
        "peak_hours": f"{rule['peak'][0]:02d}:00-{rule['peak'][1]:02d}:00",
        "lunch_break": lunch_break,
        "closed_days": closed_days,
        "real_type": real_type,
    }

    return result


def run(poi_path, out_path):
    with open(poi_path, "r", encoding="utf-8") as f:
        pois = json.load(f)

    hours_map = {}
    for poi in pois:
        hours_map[poi["poi_id"]] = generate_hours(poi)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(hours_map, f, ensure_ascii=False, indent=2)

    print(f"Generated business hours for {len(pois)} POIs")
    print(f"Saved to {out_path}")

    # 统计
    from collections import Counter
    type_counts = Counter()
    overnight_counts = Counter()
    for pid, h in hours_map.items():
        type_counts[h["real_type"]] += 1
        if h["overnight"]:
            overnight_counts[h["real_type"]] += 1

    print("\nOvernight POIs by type:")
    for t, c in sorted(overnight_counts.items(), key=lambda x: -x[1]):
        print(f"  {t}: {c}")

    # 样本
    print("\nSample business hours:")
    for poi in pois[:5]:
        h = hours_map[poi["poi_id"]]
        print(f"  {poi['name']} ({h['real_type']}): {h['open_time']}-{h['close_time']} | peak: {h['peak_hours']}")


if __name__ == "__main__":
    run("wuhou_jinjiang_pois.json", "poi_business_hours.json")
