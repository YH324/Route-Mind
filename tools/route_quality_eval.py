#!/usr/bin/env python3
"""
Offline route quality evaluation for RouteMind.

The suite uses only covered service areas and disables external LLM calls by
default so the backend can be tested predictably in local or CI environments.
"""
import argparse
import json
import os
import statistics
import sys
import time
from contextlib import contextmanager, nullcontext
from unittest.mock import patch


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app_service import CITY_CENTERS, run_agent  # noqa: E402


CENTERS = ["chengdu", "chunxi", "taikooli", "ifs", "jinli", "wuhouci", "jiuyanqiao", "languifang", "wangjiang"]
USER_MODES = ["tourist", "business", "resident"]

GOAL_TEMPLATES = [
    ("single_hotpot", "{place}附近下午四点想吃火锅", "single_poi", ["火锅"]),
    ("single_coffee", "{place}附近找个咖啡馆", "single_poi", ["饮品"]),
    ("single_teahouse", "{place}附近找个安静茶馆", "single_poi", ["茶馆"]),
    ("single_park", "{place}附近去公园散步", "single_poi", ["公园"]),
    ("single_shopping", "{place}附近逛街", "single_poi", ["商场"]),
    ("simple_shop_coffee", "{place}附近逛街喝咖啡", "route", ["商场", "饮品"]),
    ("simple_lunch_coffee", "{place}附近午餐后喝咖啡", "route", ["中餐", "饮品"]),
    ("simple_supermarket_snack", "{place}附近找个超市顺便吃点小吃", "route", ["超市", "小吃"]),
    ("night_drink_snack", "{place}晚上喝酒，顺便找点夜宵", "route", ["酒吧", "小吃"]),
    ("tour_halfday", "{place}附近半日游，想看景点再吃点东西", "route", ["景点", "餐饮"]),
    ("one_day", "{place}一日游，安排景点、美食和休闲", "route", ["景点", "餐饮", "休闲"]),
    ("business_short", "{place}附近出差，1小时内找午餐和咖啡", "route", ["中餐", "饮品"]),
]


BAD_TYPES = {"其他", "住宿", "医疗", "培训", "汽车"}
BAD_NAME_TERMS = [
    "停车", "入口", "出口", "门岗", "充电", "快递", "写字楼", "公寓", "小区", "住宅",
    "销售", "经营部", "维修", "公司", "售楼", "收发室",
]


@contextmanager
def local_only_llm():
    with patch("route_planner_v3.MIMO_API_KEY", ""), \
         patch("route_planner_v3.MINIMAX_API_KEY", ""), \
         patch("route_planner_v3.GLM_API_KEY", ""), \
         patch("route_planner_v3.ENABLE_LLM_CANDIDATE_REVIEW", False), \
         patch("route_planner_v3.ENABLE_LLM_ROUTE_REVIEW", False):
        yield


def _expected_type_hit(item_type, expected):
    if item_type == expected:
        return True
    category_aliases = {
        "餐饮": {"火锅", "烧烤", "中餐", "小吃", "外国菜", "甜品", "饮品", "农家菜"},
        "景点": {"景点", "公园", "游乐园"},
        "休闲": {"茶馆", "饮品", "酒吧", "KTV", "电影院", "按摩SPA", "健身", "休闲", "网吧"},
        "购物": {"商场", "购物", "超市", "便利店"},
        "商场": {"商场"},
        "超市": {"超市"},
    }
    return item_type in category_aliases.get(expected, set())


def _score_response(case, response):
    metrics = {
        "ok": bool(response.get("ok")),
        "has_result": False,
        "has_items": False,
        "route_feasible": True,
        "intent_coverage": 0.0,
        "bad_item_count": 0,
        "polyline_missing": 0,
        "move_time_min": 0.0,
        "latency_ms": (response.get("performance") or {}).get("total_ms"),
        "error_code": response.get("error_code"),
    }
    if not response.get("ok"):
        return metrics
    result = response.get("result") or {}
    metrics["has_result"] = bool(result)
    variants = result.get("variants") or []
    if not variants:
        return metrics
    variant = variants[0]
    items = variant.get("route") or variant.get("recommendations") or []
    metrics["has_items"] = bool(items)
    item_types = [item.get("type") for item in items]
    expected = case["expected_types"]
    if expected:
        hits = 0
        for target in expected:
            if any(_expected_type_hit(t, target) for t in item_types):
                hits += 1
        metrics["intent_coverage"] = hits / max(len(expected), 1)
    else:
        metrics["intent_coverage"] = 1.0
    for item in items:
        if item.get("type") in BAD_TYPES:
            metrics["bad_item_count"] += 1
        name = item.get("name", "")
        if any(term in name for term in BAD_NAME_TERMS):
            metrics["bad_item_count"] += 1
    route = variant.get("route") or []
    if route:
        feasibility = variant.get("route_feasibility") or {}
        metrics["route_feasible"] = bool(feasibility.get("feasible"))
        metrics["move_time_min"] = float(feasibility.get("total_move_time_min") or variant.get("total_move_time") or 0)
        for step in route:
            move = step.get("move_from_start") or step.get("move_from_prev") or {}
            if len(move.get("polyline") or []) < 2:
                metrics["polyline_missing"] += 1
    return metrics


def build_cases(limit=None, offset=0):
    cases = []
    for center_key in CENTERS:
        center = CITY_CENTERS[center_key]
        for mode in USER_MODES:
            for template_id, template, expectation, expected_types in GOAL_TEMPLATES:
                goal = template.format(place=center["name"])
                cases.append({
                    "id": "{}:{}:{}".format(center_key, mode, template_id),
                    "goal": goal,
                    "city": "chengdu",
                    "center_lng": center["lng"],
                    "center_lat": center["lat"],
                    "radius": 3000,
                    "user_mode": mode,
                    "expectation": expectation,
                    "expected_types": expected_types,
                })
    if offset:
        cases = cases[offset:]
    if limit:
        return cases[:limit]
    return cases


def run_suite(limit=None, offset=0, output_path=None, use_external_llm=False):
    cases = build_cases(limit, offset=offset)
    results = []
    context = local_only_llm() if not use_external_llm else nullcontext()
    with context:
        for idx, case in enumerate(cases, start=1):
            started = time.time()
            response = run_agent({
                "goal": case["goal"],
                "city": case["city"],
                "center_lng": case["center_lng"],
                "center_lat": case["center_lat"],
                "radius": case["radius"],
                "user_mode": case["user_mode"],
            }, request_id="offline-eval-{}".format(offset + idx))
            metrics = _score_response(case, response)
            metrics["wall_ms"] = round((time.time() - started) * 1000)
            results.append({"case": case, "metrics": metrics})
            print("[{}/{}] {} ok={} coverage={:.2f} feasible={} bad={} wall_ms={}".format(
                idx,
                len(cases),
                case["id"],
                metrics["ok"],
                metrics["intent_coverage"],
                metrics["route_feasible"],
                metrics["bad_item_count"],
                metrics["wall_ms"],
            ))

    summary = summarize(results)
    artifact = {"summary": summary, "results": results}
    if output_path:
        try:
            output_dir = os.path.dirname(os.path.abspath(output_path))
            if output_dir and not os.path.exists(output_dir):
                os.makedirs(output_dir, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as handle:
                json.dump(artifact, handle, ensure_ascii=False, indent=2)
        except OSError as exc:
            print("[Eval] Report write skipped: {}".format(exc))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return artifact


def summarize(results):
    total = len(results)
    ok = sum(1 for row in results if row["metrics"]["ok"])
    has_items = sum(1 for row in results if row["metrics"]["has_items"])
    feasible_routes = sum(1 for row in results if row["metrics"]["route_feasible"])
    zero_bad = sum(1 for row in results if row["metrics"]["bad_item_count"] == 0)
    no_polyline_missing = sum(1 for row in results if row["metrics"]["polyline_missing"] == 0)
    coverages = [row["metrics"]["intent_coverage"] for row in results]
    latencies = [row["metrics"]["wall_ms"] for row in results]
    failures = [
        {
            "id": row["case"]["id"],
            "goal": row["case"]["goal"],
            "metrics": row["metrics"],
        }
        for row in results
        if (
            not row["metrics"]["ok"]
            or not row["metrics"]["has_items"]
            or row["metrics"]["intent_coverage"] < 0.75
            or not row["metrics"]["route_feasible"]
            or row["metrics"]["bad_item_count"] > 0
            or row["metrics"]["polyline_missing"] > 0
        )
    ]
    return {
        "case_count": total,
        "ok_rate": round(ok / max(total, 1), 4),
        "has_items_rate": round(has_items / max(total, 1), 4),
        "route_feasible_rate": round(feasible_routes / max(total, 1), 4),
        "zero_bad_item_rate": round(zero_bad / max(total, 1), 4),
        "polyline_complete_rate": round(no_polyline_missing / max(total, 1), 4),
        "intent_coverage_avg": round(sum(coverages) / max(total, 1), 4),
        "intent_coverage_p50": round(statistics.median(coverages), 4) if coverages else 0,
        "latency_ms_p50": round(statistics.median(latencies), 1) if latencies else 0,
        "latency_ms_p95": round(sorted(latencies)[int(0.95 * (len(latencies) - 1))], 1) if latencies else 0,
        "failure_count": len(failures),
        "sample_failures": failures[:20],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--output", default=os.path.join(ROOT, "eval_reports", "route_quality_eval.json"))
    parser.add_argument("--use-external-llm", action="store_true")
    args = parser.parse_args()
    run_suite(limit=args.limit, offset=args.offset, output_path=args.output, use_external_llm=args.use_external_llm)


if __name__ == "__main__":
    main()
