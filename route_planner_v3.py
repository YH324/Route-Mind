#!/usr/bin/env python3
"""
智能路线规划系统 v3.0

核心改进：
1. 路网距离替代直线距离（Dijkstra最短路径）
2. 营业时间过滤（避免安排已打烊的POI）
3. 类型评分优化（降低购物类权重，提升景点/餐饮）
4. "逛"字语义修复（"逛公园"≠"购物"）
5. 购物类比例硬约束
"""
import json
import os
import re
import random
import urllib.request
import math
from datetime import datetime, timedelta
from collections import Counter, defaultdict

from road_network import get_network
from poi_knn_graph import PoiKnnGraph
from interaction_intelligence import apply_context_to_constraints, poi_matcher

MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CENTER_LNG = 104.06476
DEFAULT_CENTER_LAT = 30.65705
RANKING_MODEL_VERSION = "feature_ranker_v1.5"
PLANNER_VERSION = "route_planner_v3.9"
_REFERENCE_POIS_CACHE = None


def _module_path(path):
    if os.path.isabs(path):
        return path
    return os.path.join(MODULE_DIR, path)


def _load_reference_pois():
    """Load the local POI corpus as a background set for data-driven signals."""
    global _REFERENCE_POIS_CACHE
    if _REFERENCE_POIS_CACHE is None:
        try:
            with open(_module_path("wuhou_jinjiang_pois.json"), "r", encoding="utf-8") as handle:
                _REFERENCE_POIS_CACHE = json.load(handle)
        except (OSError, ValueError):
            _REFERENCE_POIS_CACHE = []
    return _REFERENCE_POIS_CACHE


# LLM API 配置（用于意图分类）
from config import (
    MIMO_API_KEY, MIMO_CHAT_URL, MIMO_MODEL, MIMO_AUTH_TYPE,
    MINIMAX_API_KEY, MINIMAX_CHAT_URL, MINIMAX_MODEL, MINIMAX_AUTH_TYPE,
    GLM_API_KEY, GLM_CHAT_URL, GLM_MODEL, GLM_AUTH_TYPE,
    CATEGORY_QUOTA, CATEGORY_LIMITS, CONCRETE_TYPE_LIMIT,
    SEMANTIC_TOP_K, SEMANTIC_BOOST,
    AUTO_TIME_PERCENTILE, AUTO_TIME_THRESHOLD,
    VARIANT_PARAMS, CANDIDATE_POOL_SIZE,
    PERSIST_KNN_CACHE, ENABLE_LLM_CANDIDATE_REVIEW,
    LLM_REVIEW_CANDIDATE_TOP_N, LLM_REVIEW_BONUS,
)


COMPLEX_ROUTE_SIGNALS = ["半日", "一日", "全天", "路线", "攻略", "行程", "游", "多个", "几个", "逛遍", "打卡", "景点", "规划"]
STRONG_COMPLEX_ROUTE_SIGNALS = ["半日", "一日", "全天", "路线", "攻略", "行程", "多个", "几个", "逛遍", "规划"]
SINGLE_POI_SIGNALS = [
    "逛街", "逛商场", "买东西", "购物", "找个", "找一家", "附近有",
    "附近", "想吃", "想喝", "喝咖啡", "喝茶", "喝酒", "吃饭", "午餐", "午饭", "夜宵", "看电影", "去公园", "情侣约会", "约会",
]
SEQUENCE_SIGNALS = ["然后", "之后", "再去", "顺便", "接着", "先去", "最后去", "吃完", "逛完", "玩完", "看完", "去完"]
MULTI_INTENT_CONNECTORS = ["然后", "之后", "再去", "顺便", "接着", "先去", "最后去", "吃完", "逛完", "玩完", "看完", "去完", "再", "和", "并且", "同时", "也想"]
CONCRETE_GOAL_TERMS = [
    ("火锅", "火锅"), ("烧烤", "烧烤"), ("夜宵", "小吃"), ("小吃", "小吃"),
    ("午餐", "中餐"), ("午饭", "中餐"), ("晚餐", "中餐"), ("正餐", "中餐"), ("吃饭", "中餐"), ("餐厅", "中餐"), ("川菜", "中餐"), ("中餐", "中餐"),
    ("喝咖啡", "饮品"), ("咖啡", "饮品"), ("奶茶", "饮品"), ("饮品", "饮品"),
    ("喝茶", "茶馆"), ("茶馆", "茶馆"), ("茶舍", "茶馆"),
    ("喝酒", "酒吧"), ("小酒馆", "酒吧"), ("酒吧", "酒吧"),
    ("公园", "公园"), ("景点", "景点"), ("商场", "商场"), ("逛街", "商场"), ("购物", "商场"),
    ("买菜", "超市"), ("采购", "超市"), ("超市", "超市"), ("便利店", "便利店"), ("电影", "电影院"), ("影院", "电影院"), ("KTV", "KTV"),
]


def _contains_any(text, signals):
    return any(s in text for s in signals)


def _concrete_goal_types(text):
    lower = (text or "").lower()
    types = []
    for keyword, typ in CONCRETE_GOAL_TERMS:
        if keyword.lower() in lower and typ not in types:
            types.append(typ)
    return types


def _has_multi_concrete_goal(text):
    types = _concrete_goal_types(text)
    return (
        (_contains_any(text, MULTI_INTENT_CONNECTORS) and len(types) >= 2)
        or (("逛街" in text or "购物" in text or "商场" in text) and ("咖啡" in text or "喝咖啡" in text))
    )


def _looks_like_nearby_single_goal(text):
    lower = (text or "").lower()
    if not _contains_any(lower, ("附近", "周边")):
        return False
    return any(term in lower for term in ("景点", "公园", "去哪玩", "玩", "看景点", "散步"))


def _rule_guard_intent(goal_text, intent):
    """用高置信规则约束 LLM 误判，避免短单点需求被扩成完整路线。"""
    text = goal_text.lower()
    if _looks_like_nearby_single_goal(text):
        return "single_poi"
    if _contains_any(text, STRONG_COMPLEX_ROUTE_SIGNALS):
        return intent
    if _contains_any(text, SEQUENCE_SIGNALS) or _has_multi_concrete_goal(text):
        return "simple_route"
    if _contains_any(text, COMPLEX_ROUTE_SIGNALS):
        return intent
    if _contains_any(text, SINGLE_POI_SIGNALS) and intent == "complex_route":
        return "single_poi"
    return intent


def _high_confidence_rule_intent(goal_text):
    """明确关键词直接走规则，避免为简单请求等待外部模型。"""
    text = goal_text.lower()
    if _looks_like_nearby_single_goal(text):
        return {"intent_type": "single_poi", "reason": "规则快速路径：附近单点/短列表需求"}
    if _contains_any(text, STRONG_COMPLEX_ROUTE_SIGNALS):
        return {"intent_type": "complex_route", "reason": "规则快速路径：完整路线信号"}
    if _contains_any(text, SEQUENCE_SIGNALS) or _has_multi_concrete_goal(text):
        return {"intent_type": "simple_route", "reason": "规则快速路径：顺序/连接信号"}
    if _contains_any(text, COMPLEX_ROUTE_SIGNALS):
        return {"intent_type": "complex_route", "reason": "规则快速路径：完整路线信号"}
    if _contains_any(text, SINGLE_POI_SIGNALS):
        return {"intent_type": "single_poi", "reason": "规则快速路径：单点需求信号"}
    return None


def _classify_intent_by_rule(goal_text):
    """基于规则的意图分类（LLM 不可用时作为 fallback）"""
    text = goal_text.lower()
    if _looks_like_nearby_single_goal(text):
        return {"intent_type": "single_poi", "reason": "规则匹配：附近单点/短列表需求"}
    
    # complex_route 的强信号
    for s in STRONG_COMPLEX_ROUTE_SIGNALS:
        if s in text:
            return {"intent_type": "complex_route", "reason": f"规则匹配：包含'{s}'"}

    # 短查询通常是在找一个地点类型，不应在 LLM 不可用时硬扩成半日路线。
    if _contains_any(text, SINGLE_POI_SIGNALS) and not _contains_any(text, SEQUENCE_SIGNALS):
        if not _has_multi_concrete_goal(text):
            return {"intent_type": "single_poi", "reason": "规则匹配：短查询/单点需求"}
    
    # simple_route 的强信号：连接词/顺序词 + 地点
    has_sequence = _contains_any(text, SEQUENCE_SIGNALS) or _has_multi_concrete_goal(text)
    
    # 统计具体类型数量
    type_count = 0
    for types in TYPE_CATEGORIES.values():
        for t in types:
            if t in text:
                type_count += 1
    
    if has_sequence or type_count >= 2:
        return {"intent_type": "simple_route", "reason": "规则匹配：包含顺序词或多个地点"}
    for s in COMPLEX_ROUTE_SIGNALS:
        if s in text:
            return {"intent_type": "complex_route", "reason": f"规则匹配：包含'{s}'"}
    
    # single_poi：只有一个类型词，且没有复杂路线信号
    if type_count == 1 and len(text) <= 15:
        return {"intent_type": "single_poi", "reason": "规则匹配：简短单点需求"}
    
    # 默认
    return {"intent_type": "complex_route", "reason": "规则匹配：默认复杂路线"}


def _auth_headers(api_key, auth_type):
    auth_type = (auth_type or "api-key").lower()
    headers = {"Content-Type": "application/json"}
    if auth_type == "bearer":
        headers["Authorization"] = "Bearer " + api_key
    else:
        headers["api-key"] = api_key
    return headers


def _call_llm_api(url, api_key, model, system_prompt, user_prompt, timeout=15,
                  auth_type="api-key", token_field="max_completion_tokens",
                  include_thinking=True):
    """通用 LLM 调用，支持 MiMo/MiniMax/GLM 等 OpenAI-compatible 接口"""
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.1,
        "stream": False,
    }
    payload[token_field] = 512
    if include_thinking:
        payload["thinking"] = {"type": "disabled"}
    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=_auth_headers(api_key, auth_type),
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
        data = json.loads(raw)
    content = data["choices"][0]["message"]["content"].strip()
    if not content:
        raise ValueError("LLM returned empty content")
    # 提取 JSON（处理可能的 markdown 代码块或额外文字）
    if "```json" in content:
        content = content.split("```json")[1].split("```")[0].strip()
    elif "```" in content:
        content = content.split("```")[1].split("```")[0].strip()
    # 如果还不是纯 JSON，尝试用大括号提取
    try:
        result = json.loads(content)
    except json.JSONDecodeError:
        m = re.search(r'\{[\s\S]*\}', content)
        if m:
            result = json.loads(m.group(0))
        else:
            raise ValueError(f"Cannot parse JSON from LLM response: {content[:200]}")
    return result


def classify_intent_with_llm(goal_text):
    """
    调用大模型判断用户意图类型。
    优先级：MiMo > MiniMax Coding Plan > GLM > 规则 fallback
    
    Returns:
        dict: {"intent_type": "single_poi|simple_route|complex_route", "reason": str, "llm_used": bool}
    """
    fast_rule = _high_confidence_rule_intent(goal_text)
    if fast_rule:
        fast_rule["llm_used"] = False
        print(f"[LLM-Intent] Rule fast path: {fast_rule['intent_type']}")
        return fast_rule

    system_prompt = (
        "你是一个旅游意图分类助手。根据用户的自然语言输入，判断用户的真实意图类型。\n"
        "intent_type 只能是以下三种之一：\n"
        "1. single_poi：用户只想去一个地方，或只想找某个类型的单个地点（如'想吃火锅'、'找个咖啡馆'、'附近有好吃的烧烤吗'）\n"
        "2. simple_route：用户想去 2-3 个地方简单逛逛，有明确的少量地点组合（如'吃完火锅去茶馆'、'想逛街顺便吃个饭'）\n"
        "3. complex_route：用户要求规划完整路线，想串联多个地点，或提到'半日游'、'一日游'、'攻略'等词汇（如'成都半日游'、'想逛多个景点'）\n\n"
        "重要规则：\n"
        "- 必须只输出纯 JSON，不要任何解释、前言、emoji、markdown代码块\n"
        "- 输出格式示例：{\"intent_type\": \"single_poi\", \"reason\": \"用户只想吃火锅\"}\n"
        "- 请直接输出 JSON 文本"
    )
    
    llm_errors = {}

    # 1. 优先尝试 MiMo
    if MIMO_API_KEY:
        try:
            result = _call_llm_api(
                MIMO_CHAT_URL, MIMO_API_KEY, MIMO_MODEL,
                system_prompt, goal_text,
                auth_type=MIMO_AUTH_TYPE,
                token_field="max_completion_tokens",
                include_thinking=True,
            )
            intent = result.get("intent_type", "complex_route")
            if intent not in ("single_poi", "simple_route", "complex_route"):
                intent = "complex_route"
            guarded_intent = _rule_guard_intent(goal_text, intent)
            if guarded_intent != intent:
                print(f"[LLM-Intent] MiMo -> {intent}, guard -> {guarded_intent}: {result.get('reason', '')}")
            else:
                print(f"[LLM-Intent] MiMo -> {intent}: {result.get('reason', '')}")
            return {"intent_type": guarded_intent, "reason": result.get("reason", ""), "llm_used": True, "provider": "mimo"}
        except Exception as e:
            print(f"[LLM-Intent] MiMo failed: {e}")
            llm_errors["MiMo"] = str(e)
    else:
        llm_errors["MiMo"] = "API key not configured"

    # 2. MiMo 失败时回退到 MiniMax Coding Plan
    if MINIMAX_API_KEY:
        try:
            result = _call_llm_api(
                MINIMAX_CHAT_URL, MINIMAX_API_KEY, MINIMAX_MODEL,
                system_prompt, goal_text,
                auth_type=MINIMAX_AUTH_TYPE,
                token_field="max_tokens",
                include_thinking=False,
            )
            intent = result.get("intent_type", "complex_route")
            if intent not in ("single_poi", "simple_route", "complex_route"):
                intent = "complex_route"
            guarded_intent = _rule_guard_intent(goal_text, intent)
            if guarded_intent != intent:
                print(f"[LLM-Intent] MiniMax -> {intent}, guard -> {guarded_intent}: {result.get('reason', '')}")
            else:
                print(f"[LLM-Intent] MiniMax -> {intent}: {result.get('reason', '')}")
            return {"intent_type": guarded_intent, "reason": result.get("reason", ""), "llm_used": True, "provider": "minimax"}
        except Exception as e:
            print(f"[LLM-Intent] MiniMax failed: {e}")
            llm_errors["MiniMax"] = str(e)
    else:
        llm_errors["MiniMax"] = "API key not configured"

    # 3. MiniMax 失败时回退到 GLM
    if GLM_API_KEY:
        try:
            result = _call_llm_api(
                GLM_CHAT_URL, GLM_API_KEY, GLM_MODEL,
                system_prompt, goal_text,
                auth_type=GLM_AUTH_TYPE,
                token_field="max_tokens",
                include_thinking=False,
            )
            intent = result.get("intent_type", "complex_route")
            if intent not in ("single_poi", "simple_route", "complex_route"):
                intent = "complex_route"
            guarded_intent = _rule_guard_intent(goal_text, intent)
            if guarded_intent != intent:
                print(f"[LLM-Intent] GLM -> {intent}, guard -> {guarded_intent}: {result.get('reason', '')}")
            else:
                print(f"[LLM-Intent] GLM -> {intent}: {result.get('reason', '')}")
            return {"intent_type": guarded_intent, "reason": result.get("reason", ""), "llm_used": True, "provider": "glm"}
        except Exception as e:
            print(f"[LLM-Intent] GLM failed: {e}")
            llm_errors["GLM"] = str(e)
    else:
        llm_errors["GLM"] = "API key not configured"
    
    # 4. 所有 LLM 都失败时降级为规则
    result = _classify_intent_by_rule(goal_text)
    result["llm_used"] = False
    result["llm_error"] = "; ".join(f"{name}: {error}" for name, error in llm_errors.items())
    print(f"[LLM-Intent] Rule fallback: {result['intent_type']}")
    return result


def _call_first_available_llm_json(system_prompt, user_prompt, timeout=15):
    errors = {}
    providers = [
        ("mimo", MIMO_API_KEY, MIMO_CHAT_URL, MIMO_MODEL, MIMO_AUTH_TYPE, "max_completion_tokens", True),
        ("minimax", MINIMAX_API_KEY, MINIMAX_CHAT_URL, MINIMAX_MODEL, MINIMAX_AUTH_TYPE, "max_tokens", False),
        ("glm", GLM_API_KEY, GLM_CHAT_URL, GLM_MODEL, GLM_AUTH_TYPE, "max_tokens", False),
    ]
    for name, api_key, url, model, auth_type, token_field, include_thinking in providers:
        if not api_key:
            errors[name] = "API key not configured"
            continue
        try:
            return name, _call_llm_api(
                url, api_key, model, system_prompt, user_prompt,
                timeout=timeout,
                auth_type=auth_type,
                token_field=token_field,
                include_thinking=include_thinking,
            )
        except Exception as exc:
            errors[name] = str(exc)
    raise RuntimeError("; ".join(f"{name}: {error}" for name, error in errors.items()))


def _llm_review_candidates(goal, ranked_items, constraints):
    if not ENABLE_LLM_CANDIDATE_REVIEW or not ranked_items:
        return {}, {"enabled": False, "used": False, "reason": "disabled_or_empty"}

    top_items = ranked_items[:max(1, LLM_REVIEW_CANDIDATE_TOP_N)]
    candidates = []
    for rank, item in enumerate(top_items, start=1):
        _score, poi, real_type, cat, features, _reasons, _special_bonus = item
        candidates.append({
            "poi_id": poi["poi_id"],
            "rank": rank,
            "name": poi.get("name"),
            "type": real_type,
            "category": cat,
            "address": poi.get("address"),
            "distance_m": features.get("distance_to_start_m"),
            "quality_score": features.get("quality_score"),
            "matched_brand": features.get("matched_brand"),
            "brand_signal": features.get("brand_signal"),
            "entity_quality_signals": features.get("entity_quality_signals", []),
        })

    system_prompt = (
        "你是出行推荐系统的候选评审器。只能在给定候选 POI 中重排，不能编造新地点。"
        "请根据用户目标、POI 名称、类型、距离、门店实体质量和品牌识别度，判断哪些候选更适合推荐。"
        "必须只输出 JSON，格式为 {\"items\":[{\"poi_id\":\"...\",\"bonus\":0到1之间数字,\"reason\":\"不超过24字\"}]}。"
        "poi_id 必须来自候选列表；不确定时给低 bonus。"
    )
    user_prompt = json.dumps({
        "goal": goal,
        "intent_type": constraints.get("intent_type"),
        "preferred_tags": constraints.get("preferred_tags", []),
        "center": {"lng": constraints.get("center_lng"), "lat": constraints.get("center_lat")},
        "candidates": candidates,
    }, ensure_ascii=False)

    try:
        provider, result = _call_first_available_llm_json(system_prompt, user_prompt, timeout=12)
    except Exception as exc:
        return {}, {"enabled": True, "used": False, "reason": "provider_unavailable", "error": str(exc)[:300]}

    raw_items = result.get("items") if isinstance(result, dict) else None
    if not isinstance(raw_items, list):
        return {}, {"enabled": True, "used": False, "provider": provider, "reason": "invalid_response_shape"}

    valid_ids = {poi["poi_id"] for _, poi, *_ in top_items}
    reviews = {}
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        poi_id = raw.get("poi_id")
        if poi_id not in valid_ids:
            continue
        try:
            bonus = float(raw.get("bonus", 0))
        except (TypeError, ValueError):
            bonus = 0.0
        bonus = max(0.0, min(1.0, bonus)) * LLM_REVIEW_BONUS
        reason = str(raw.get("reason") or "").strip()[:48]
        if bonus > 0:
            reviews[poi_id] = {"bonus": bonus, "reason": reason}

    return reviews, {
        "enabled": True,
        "used": bool(reviews),
        "provider": provider,
        "reviewed_count": len(top_items),
        "accepted_count": len(reviews),
    }

random.seed(42)

# ========== 用户意图解析 ==========

GOAL_PATTERNS = {
    "time_budget": r"(\d+(?:\.\d+)?)\s*(?:个)?小时|([一二三四五六七八九十两俩]+)\s*(?:个)?小时|半小时|半日|一日|一天|全天|半天",
    "mode_walk": r"步行|走路|散步|溜达",
    "mode_bike": r"骑车|骑行|自行车|电动车",
    "mode_drive": r"开车|自驾|驾车|打车",
    "mode_bus": r"公交|地铁|公共交通",
    "food": r"吃|吃饭|午餐|午饭|晚餐|正餐|夜宵|美食|好吃|火锅|烧烤|小吃|餐厅|餐饮|咖啡|喝.*茶|喝.*咖啡|喝.*奶茶|下午茶|甜品|蛋糕",
    "sight": r"景点|公园|游玩|逛公园|游览|打卡|拍照|去哪玩|玩",
    "shopping": r"逛街|买东西|购物|商场|购物中心|超市|便利店|买菜|采购",
    "relax": r"休闲|放松|按摩|SPA|茶馆|茶舍|咖啡|喝酒|小酒馆|酒吧|KTV|电影|影城|影院|下午茶|晚上|夜生活|情侣|约会",
    "start_time": r"(?:现在|起始|开始|从|)(?:是|为|在|大约|大概|)(?:上午|下午|早上|晚上|中午|凌晨)?\s*([\d一二三四五六七八九十两俩]+)\s*(?:点|：|:|\s)\s*(\d{2}|)(?:\s*(?:左右|前后|))?",
    "start_time_ampm": r"(上午|下午|早上|晚上|中午|凌晨)\s*([\d一二三四五六七八九十两俩]+)\s*(?:点|：|:)?\s*(\d{2}|)",
}

TYPE_PRIORITY_V3 = {
    "景点": 1.5, "公园": 1.4, "游乐园": 1.3,
    "火锅": 1.3, "烧烤": 1.2, "中餐": 1.1, "小吃": 1.1, "外国菜": 1.1, "甜品": 1.0, "饮品": 1.0,
    "茶馆": 1.0, "农家乐": 1.0,
    "住宿": 0.7,
    "KTV": 0.8, "酒吧": 0.8, "电影院": 0.9, "健身": 0.7, "按摩SPA": 0.7,
    "商场": 0.6, "超市": 0.4, "便利店": 0.3,
    "数码": 0.4, "服饰": 0.4, "美妆": 0.4, "家居": 0.3,
    "购物": 0.5, "休闲": 0.6,
    "其他": 0.5,
}

# 用户模式配置：当前预研阶段的三种路线策略。
USER_MODES = {
    "tourist": {
        "label": "游客",
        "type_weights": {"景点": 1.5, "公园": 1.4, "游乐园": 1.3, "火锅": 1.3, "烧烤": 1.3, "小吃": 1.1, "茶馆": 1.0},
        "stay_times": {"景点": 50, "公园": 40, "游乐园": 60, "火锅": 50, "烧烤": 45, "小吃": 20, "茶馆": 35},
        "radius_m": 5000,
        "max_travel_min": 30,
        "max_shopping": 1,
        "category_limits": {"餐饮": 2, "景点": 2, "购物": 1, "休闲": 2},
        "exclude_types": {"住宿", "医疗", "汽车", "培训", "宠物", "便利店", "超市"},
    },
    "business": {
        "label": "出差",
        "type_weights": {"中餐": 1.35, "外国菜": 1.15, "茶馆": 1.15, "饮品": 1.0, "按摩SPA": 0.95, "商场": 0.65},
        "stay_times": {"中餐": 35, "外国菜": 35, "小吃": 20, "饮品": 15, "茶馆": 30, "按摩SPA": 45},
        "radius_m": 1000,
        "max_travel_min": 15,
        "max_shopping": 0,
        "category_limits": {"餐饮": 2, "景点": 0, "购物": 0, "休闲": 1},
        "exclude_types": {"景点", "公园", "游乐园", "住宿", "医疗", "汽车", "培训", "宠物", "便利店", "超市", "购物", "商场", "数码", "服饰", "美妆", "家居"},
    },
    "resident": {
        "label": "居民",
        "type_weights": {"火锅": 1.3, "烧烤": 1.2, "茶馆": 1.15, "公园": 1.0, "健身": 0.95, "超市": 0.75, "商场": 0.7},
        "stay_times": {"火锅": 50, "烧烤": 45, "茶馆": 35, "公园": 40, "健身": 60, "超市": 20, "商场": 35},
        "radius_m": 2500,
        "max_travel_min": 25,
        "max_shopping": 2,
        "category_limits": {"餐饮": 2, "景点": 1, "购物": 2, "休闲": 2},
        "exclude_types": {"住宿", "医疗", "汽车", "培训", "宠物"},
    },
}

MODE_ALIASES = {
    "tourist": "tourist", "travel": "tourist", "visitor": "tourist", "游客": "tourist",
    "business": "business", "work": "business", "biz": "business", "出差": "business", "商务": "business",
    "resident": "resident", "local": "resident", "居民": "resident", "本地": "resident",
}


def normalize_user_mode(user_mode):
    return MODE_ALIASES.get(str(user_mode or "tourist").strip().lower(), "tourist")


def _mode_config(constraints):
    return USER_MODES.get(constraints.get("user_mode", "tourist"), USER_MODES["tourist"])


def _type_weight(real_type, constraints):
    weights = _mode_config(constraints).get("type_weights", {})
    return weights.get(real_type, TYPE_PRIORITY_V3.get(real_type, 0.5))


def _stay_minutes(real_type, constraints, variant_name=None, variant=None):
    stay_times = _mode_config(constraints).get("stay_times", {})
    base = stay_times.get(real_type, STAY_TIME.get(real_type, 30))
    if variant is None and variant_name:
        variant = VARIANTS[variant_name]
    stay_mult = variant.get("stay_mult", 1.0) if variant else 1.0
    return int(base * stay_mult)


def _category_limit(cat, constraints):
    limits = dict(CATEGORY_LIMITS)
    limits.update(_mode_config(constraints).get("category_limits", {}))
    return limits.get(cat, 999)


def _is_excluded_by_mode(real_type, constraints):
    if real_type in _mode_config(constraints).get("exclude_types", set()):
        return True
    for tag in constraints.get("avoid_tags", []):
        if _type_matches(real_type, tag):
            return True
    return False


def _type_matches(real_type, expected):
    if not expected:
        return False
    if real_type == expected:
        return True
    if expected in TYPE_CATEGORIES:
        return real_type in TYPE_CATEGORIES[expected]
    expected_cat = _get_category(expected)
    return expected_cat != "其他" and _get_category(real_type) == expected_cat


def _sequence_type_matches(real_type, expected):
    if not expected:
        return False
    if real_type == expected:
        return True
    if expected in TYPE_CATEGORIES:
        return real_type in TYPE_CATEGORIES[expected]
    return False


def _is_shopping_type(real_type):
    return real_type in {"购物", "商场", "超市", "便利店", "数码", "服饰", "美妆", "家居"}


JUNK_NAME_PATTERNS = [
    "小区", "住宅", "楼栋", "单元", "号院", "号门", "公寓", "大厦", "写字楼", "商务楼",
    "东南门", "西南门", "东北门", "西北门", "东南1门", "西南1门", "东北1门", "西北1门",
    "东南2门", "西南2门", "东北2门", "西北2门", "南门", "北门", "东门", "西门",
    "南大门", "北大门", "东大门", "西大门", "出入口", "入口", "出口", "门岗",
    "停车场", "车库", "地下停车场", "地上停车场", "停车位",
    "民宿", "酒店", "旅馆", "客栈", "套一", "套二", "套三", "一居", "两居", "三居", "四居",
    "投影", "地暖", "住宿", "北欧", "欧式", "轻奢", "主卧", "整租",
    "菜鸟驿站", "快递", "速递", "丰巢", "菜鸟", "栋", "收发室", "传达室", "警卫室", "保安室", "岗亭", "值班室",
    "客梯", "扶梯", "楼梯", "电梯", "值班台", "服务台", "收银台", "咨询台", "免费存包区",
    "换电", "充电", "座椅", "咻电", "饮水机", "饮水处", "休息区", "电子储物柜", "会议室", "货梯",
    "街电", "来电", "怪兽充电", "小电", "云充吧", "搜电", "倍电", "共享充电宝",
    "专柜", "服装修改", "巧手改衣", "改衣",
    "售楼处", "售楼部", "营销中心", "接待中心",
]

BAD_STATUS_PATTERNS = ["暂停营业", "装修中", "建设中", "暂未开放", "已关闭", "停业", "歇业"]
MALL_KEYWORDS = ["购物中心", "百货", "商场", "广场", "mall", "MALL", "Mall", "奥特莱斯", "太古里", "IFS", "wifc", "WIFC"]
SMALL_SHOP_KEYWORDS = ["小百货", "日用百货", "五金百货", "烟酒百货", "副食百货", "生活超市", "便利店"]
MALL_ENTITY_PREFIXES = ("茂业", "仁和", "王府井", "新世界", "百盛", "锦官城", "摩尔", "天府红", "WIFC", "IFS", "成都IFS", "远洋太古里", "太古里", "名都")
PARK_KEYWORDS = ["公园", "绿地", "湿地", "园区", "游园"]
PARK_STRICT_KEYWORDS = ["公园", "湿地", "游园", "森林", "生态园", "绿道"]
PARK_FALSE_POSITIVE_TERMS = [
    "超市", "商品", "直销", "购物", "商场", "百货", "来福士", "便利店", "专卖", "经营",
    "公司", "中心", "写字楼", "绿地中心", "绿地全球", "G-Super",
]
LOW_VALUE_ROUTE_TYPES = {"其他", "购物", "服饰", "美妆", "家居", "数码", "家电数码"}
LOW_VALUE_ROUTE_NAME_PATTERNS = [
    "酒业", "专卖", "销售", "经营部", "商贸", "公司", "服务中心", "批发",
    "鲜疏坊", "电器", "五金", "维修", "药房", "门诊", "教育", "培训",
    "置换", "回收", "奢侈品", "交流中心",
]
TEAHOUSE_REAL_TERMS = ["茶馆", "茶楼", "茶舍", "茶坊", "茶室", "茶府", "茶社", "茶艺", "品茗", "茗"]
TEAHOUSE_BEVERAGE_TERMS = ["奶茶", "贡茶", "泰茶", "鲜泡茶", "水果茶", "冷饮", "茶饮", "手标", "喜茶", "奈雪", "CoCo", "coco", "丸摩堂"]
TEAHOUSE_CHESS_TERMS = ["棋牌", "麻将", "娱乐", "桌游"]
COFFEE_TERMS = ["咖啡", "coffee", "cafe", "caffee", "espresso", "latte", "拿铁", "星巴克", "瑞幸"]
COFFEE_WEAK_TERMS = ["网吧", "棋牌", "KTV", "酒馆", "BEER", "beer"]
RESTAURANT_NAME_TERMS = ["餐厅", "餐馆", "菜馆", "川菜", "家常菜", "江湖菜", "酒楼", "食府", "小馆", "饭店", "饭馆", "面馆", "小吃"]
RESTAURANT_BAD_TERMS = ["会展", "博览", "展览", "西博会", "酒店", "宾馆", "住宿", "宴会厅", "会议中心"]
SUPERMARKET_TERMS = ["超市", "卖场", "仓储", "生鲜", "菜市场", "农贸市场", "菜市", "G-Super", "永辉", "沃尔玛", "盒马", "家乐福"]
SUPERMARKET_FALSE_TERMS = ["公园", "景区", "酒店", "住宿", "公司", "批发公司", "服饰", "美妆", "珠宝", "箱包", "专柜", "小商品", "SAINT LAURENT", "PARIS"]
MARKET_TERMS = ["菜市场", "农贸市场", "菜市", "生鲜"]

HOTPOT_FULL_SERVICE_TERMS = ["老火锅", "火锅店", "火锅(", "火锅（", "市井火锅", "传统火锅", "牛肉火锅"]
HOTPOT_LIGHT_MEAL_TERMS = ["麻辣烫", "冒菜", "火锅杯", "火锅菜", "小火锅", "冷锅串串", "串串香", "炸货"]
HOTPOT_NON_RESTAURANT_RAW_TYPES = ["共享设备", "充电宝", "甜品店", "冷饮店", "专卖店", "购物服务", "生活服务"]
HOTPOT_CORE_DISTRICTS = ["春熙", "太古里", "南纱帽", "香槟", "东大街", "三圣街", "晶融汇", "下东大街"]
HOTPOT_FLAGSHIP_TERMS = ["总店", "旗舰", "概念店", "直营", "春熙", "太古里", "南纱帽", "香槟"]
HOTPOT_GENERIC_BRAND_ROOTS = {"火锅", "老火锅", "串串", "串串香", "冒菜", "麻辣烫", "小火锅", "牛肉火锅", "市井火锅"}
HOTPOT_BRAND_SUFFIX_RE = re.compile(r"(老火锅|火锅店|市井火锅|传统火锅|牛肉火锅|火锅|串串香|串串|冒菜|麻辣烫)$")
HOTPOT_LOCATION_PREFIX_RE = re.compile(r"^(成都|重庆|四川|老成都|川渝|蜀都)")


def _has_any_keyword(text, keywords):
    return any(kw in text for kw in keywords)


def _text_contains_any(text, keywords):
    lower = (text or "").lower()
    return any(str(kw).lower() in lower for kw in keywords)


def _is_restaurant_raw_type(raw_type):
    return any(term in (raw_type or "") for term in ("中餐厅", "火锅店", "快餐厅", "外国餐厅", "餐厅", "小吃", "烧烤店"))


def _is_lodging_raw_type(raw_type):
    return any(term in (raw_type or "") for term in ("住宿服务", "宾馆酒店", "旅馆", "酒店"))


def _is_supermarket_raw_type(raw_type):
    return any(term in (raw_type or "") for term in ("超级市场", "超市", "综合市场", "农贸市场"))


def _looks_like_real_park(poi):
    name = poi.get("name", "")
    raw_type = poi.get("type", "")
    if _text_contains_any(name, PARK_FALSE_POSITIVE_TERMS):
        return False
    if _has_any_keyword(name, PARK_STRICT_KEYWORDS):
        return True
    if "游园" in name or "小游园" in name:
        return True
    if "绿地" in name:
        return any(term in raw_type for term in ("公园广场", "公园"))
    if "城市广场" in raw_type or ("广场" in name and "公园" not in name):
        return False
    return any(term in raw_type for term in ("公园广场;公园", "公园", "湿地"))


def _looks_like_teahouse(poi):
    name = poi.get("name", "")
    raw_type = poi.get("type", "")
    if _has_any_keyword(name, TEAHOUSE_CHESS_TERMS):
        return False
    if _text_contains_any(name, TEAHOUSE_BEVERAGE_TERMS) or any(term in raw_type for term in ("冷饮店", "甜品店")):
        return False
    return _has_any_keyword(name, TEAHOUSE_REAL_TERMS) or "茶艺馆" in raw_type or "茶馆" in raw_type


def _looks_like_coffee_place(poi):
    text = poi.get("name", "") + " " + poi.get("type", "")
    return _text_contains_any(text, COFFEE_TERMS)


BAR_POSITIVE_TERMS = ["酒吧", "bar", "pub", "beer", "精酿", "小酒馆", "清吧", "lounge", "club"]
BAR_FALSE_TERMS = ["营养", "健身", "游泳", "棋牌", "茶", "咖啡", "美容", "SPA", "KTV", "培训", "公司"]


def _looks_like_bar_place(poi):
    text = poi.get("name", "") + " " + poi.get("type", "")
    if _text_contains_any(text, BAR_FALSE_TERMS):
        return False
    return _text_contains_any(text, BAR_POSITIVE_TERMS)


def _looks_like_restaurant_entity(poi, real_type=None):
    name = poi.get("name", "")
    raw_type = poi.get("type", "")
    if _has_any_keyword(name, RESTAURANT_BAD_TERMS) or _is_lodging_raw_type(raw_type):
        return False
    if _is_restaurant_raw_type(raw_type):
        return True
    return _has_any_keyword(name, RESTAURANT_NAME_TERMS)


def _looks_like_supermarket(poi):
    name = poi.get("name", "")
    raw_type = poi.get("type", "")
    if _has_any_keyword(name, SUPERMARKET_FALSE_TERMS):
        return False
    return _has_any_keyword(name, SUPERMARKET_TERMS) or _is_supermarket_raw_type(raw_type)


def _looks_like_market_for_grocery(poi):
    text = poi.get("name", "") + " " + poi.get("type", "")
    return _has_any_keyword(text, MARKET_TERMS)


def _correct_candidate_type(poi, real_type):
    name = poi.get("name", "")
    raw_type = poi.get("type", "")
    if real_type in ("景点", "其他") and _looks_like_real_park(poi):
        return "公园"
    if real_type == "公园" and not _looks_like_real_park(poi):
        if _looks_like_supermarket(poi):
            return "超市"
        if _looks_like_real_mall(name):
            return "商场"
        if _is_supermarket_raw_type(raw_type):
            return "超市"
    if real_type == "中餐" and not _looks_like_restaurant_entity(poi, real_type):
        if _is_lodging_raw_type(raw_type):
            return "住宿"
        if _has_any_keyword(name, ["会展", "博览", "西博会"]):
            return "其他"
    if real_type == "茶馆":
        if _text_contains_any(name, TEAHOUSE_BEVERAGE_TERMS) or any(term in raw_type for term in ("冷饮店", "甜品店")):
            return "饮品"
        if _has_any_keyword(name, TEAHOUSE_CHESS_TERMS):
            return "休闲"
    if real_type == "饮品" and _has_any_keyword(name, TEAHOUSE_CHESS_TERMS):
        return "休闲"
    if real_type in ("中餐", "饮品", "休闲", "购物", "其他") and _looks_like_bar_place(poi):
        return "酒吧"
    if real_type == "酒吧" and not _looks_like_bar_place(poi):
        return "休闲"
    if real_type == "购物" and _looks_like_supermarket(poi):
        return "超市"
    if real_type == "购物" and _looks_like_real_mall(name):
        return "商场"
    return real_type


def _hotpot_brand_root(name):
    base = re.split(r"[（(]", name or "")[0].strip()
    if not base:
        return ""
    base = HOTPOT_LOCATION_PREFIX_RE.sub("", base).strip()
    if base.endswith("火锅") and len(base) <= 4 and base not in HOTPOT_GENERIC_BRAND_ROOTS:
        return base
    if base.endswith("串串") and len(base) <= 4 and base not in HOTPOT_GENERIC_BRAND_ROOTS:
        return base
    previous = None
    while previous != base:
        previous = base
        base = HOTPOT_BRAND_SUFFIX_RE.sub("", base).strip()
    return base


def _looks_like_full_service_hotpot(poi):
    name = poi.get("name", "")
    raw_type = poi.get("type", "")
    if _has_any_keyword(name, HOTPOT_LIGHT_MEAL_TERMS):
        return False
    return (
        _has_any_keyword(name, HOTPOT_FULL_SERVICE_TERMS)
        or name.endswith("火锅")
        or "火锅店" in raw_type
    )


def _is_valid_hotpot_brand_observation(poi):
    name = poi.get("name", "")
    raw_type = poi.get("type", "")
    if _has_any_keyword(name, BAD_STATUS_PATTERNS):
        return False
    if _has_any_keyword(raw_type, HOTPOT_NON_RESTAURANT_RAW_TYPES):
        return False
    if _has_any_keyword(name, HOTPOT_LIGHT_MEAL_TERMS):
        return False
    return _is_restaurant_raw_type(raw_type) or _looks_like_full_service_hotpot(poi)


def _build_hotpot_brand_stats(all_pois, local_candidates, gt_data, type_index, center_lng, center_lat):
    stats = defaultdict(lambda: {
        "global_count": 0,
        "local_count": 0,
        "quality_sum": 0.0,
        "quality_count": 0,
        "best_quality": 0.0,
        "core_count": 0,
        "flagship_count": 0,
        "quality_ids": set(),
        "flagship_ids": set(),
    })

    def observe(poi, is_local=False):
        if type_index and type_index.get(poi["poi_id"], "其他") != "火锅":
            return
        if not _is_valid_hotpot_brand_observation(poi):
            return
        root = _hotpot_brand_root(poi.get("name", ""))
        if not root or len(root) < 2 or root in HOTPOT_GENERIC_BRAND_ROOTS:
            return
        entry = stats[root]
        if is_local:
            entry["local_count"] += 1
            if _has_any_keyword(poi.get("name", "") + poi.get("address", ""), HOTPOT_CORE_DISTRICTS):
                entry["core_count"] += 1
        else:
            entry["global_count"] += 1
        pid = poi["poi_id"]
        quality = float((gt_data.get(pid, {}) or {}).get("overall", 0) or 0)
        if quality > 0 and pid not in entry["quality_ids"]:
            entry["quality_ids"].add(pid)
            entry["quality_sum"] += quality
            entry["quality_count"] += 1
            entry["best_quality"] = max(entry["best_quality"], quality)
        if _has_any_keyword(poi.get("name", ""), HOTPOT_FLAGSHIP_TERMS) and pid not in entry["flagship_ids"]:
            entry["flagship_ids"].add(pid)
            entry["flagship_count"] += 1

    for p in all_pois:
        observe(p, is_local=False)
    for p in local_candidates:
        observe(p, is_local=True)

    result = {}
    for root, entry in stats.items():
        global_count = entry["global_count"]
        local_count = entry["local_count"]
        if global_count <= 0 and local_count <= 0:
            continue
        avg_quality = entry["quality_sum"] / max(entry["quality_count"], 1)
        branch_signal = 0.0
        if global_count >= 2:
            branch_signal += min(2.6, math.log1p(global_count) * 1.15)
        if local_count >= 2:
            branch_signal += min(0.8, math.log1p(local_count) * 0.35)
        if entry["best_quality"] >= 4.0 and (global_count >= 2 or entry["flagship_count"] > 0):
            branch_signal += min(0.6, (entry["best_quality"] - 3.8) * 0.6)
        if entry["core_count"] > 0:
            branch_signal += min(0.5, entry["core_count"] * 0.2)
        result[root] = {
            "global_count": global_count,
            "local_count": local_count,
            "avg_quality": round(avg_quality, 3),
            "best_quality": round(entry["best_quality"], 3),
            "core_count": entry["core_count"],
            "flagship_count": entry["flagship_count"],
            "recognition_score": round(min(3.2, branch_signal), 3),
        }
    return result


def _hotpot_brand_signal(poi, constraints=None):
    root = _hotpot_brand_root(poi.get("name", ""))
    stats = (constraints or {}).get("_hotpot_brand_stats", {}).get(root)
    if not stats:
        return root, 0.0, None
    return root, float(stats.get("recognition_score", 0) or 0), stats


def _hotpot_entity_adjustment(poi):
    name = poi.get("name", "")
    raw_type = poi.get("type", "")
    adjustment = 0.0
    signals = []

    if _has_any_keyword(raw_type, HOTPOT_NON_RESTAURANT_RAW_TYPES):
        adjustment -= 5.0
        signals.append("non_restaurant_raw_type")
    if _is_restaurant_raw_type(raw_type):
        adjustment += 0.3
        signals.append("restaurant_raw_type")
    if _looks_like_full_service_hotpot(poi):
        adjustment += 1.4
        signals.append("full_service_hotpot")
    if _has_any_keyword(name, HOTPOT_LIGHT_MEAL_TERMS):
        adjustment -= 1.6
        signals.append("light_meal_or_snack")
    if _has_any_keyword(name + poi.get("address", ""), HOTPOT_CORE_DISTRICTS):
        adjustment += 0.8
        signals.append("core_chunxi_taikooli_area")
    if _has_any_keyword(name, HOTPOT_FLAGSHIP_TERMS) and not _has_any_keyword(name, HOTPOT_LIGHT_MEAL_TERMS):
        adjustment += 0.7
        signals.append("flagship_or_anchor_store")
    if "装修中" in name or "暂停营业" in name:
        adjustment -= 8.0
        signals.append("bad_business_status")
    return adjustment, signals


def _estimated_review_signal(poi, real_type, quality_score):
    try:
        from ugc_type_profiles import get_profile
        profile = get_profile(real_type)
    except Exception:
        profile = {}
    low, high = profile.get("comment_count_range", (15, 40))
    base_count = (float(low) + float(high)) / 2.0
    density = max(1.0, float(poi.get("grid_density", 1) or 1))
    density_factor = 0.5 + min(1.0, math.log1p(density) / math.log1p(360)) * 1.5
    quality_norm = max(0.0, min(1.0, (float(quality_score or 3.0) - 2.5) / 2.0))
    quality_factor = 0.7 + quality_norm * 0.6
    estimated = max(1, int(round(base_count * density_factor * quality_factor)))
    popularity_adjustment = min(1.4, math.log1p(estimated) / math.log1p(180) * 1.1)
    return estimated, popularity_adjustment, {
        "type_base_count": _round_feature(base_count, 1),
        "density_factor": _round_feature(density_factor),
        "quality_factor": _round_feature(quality_factor),
    }


def _generic_entity_adjustment(poi, real_type, constraints=None):
    constraints = constraints or {}
    name = poi.get("name", "")
    raw_type = poi.get("type", "")
    raw_goal = constraints.get("raw_goal", "")
    adjustment = 0.0
    signals = []
    reason = None

    if real_type == "公园":
        if _looks_like_real_park(poi):
            adjustment += 1.2
            signals.append("real_park_entity")
            reason = "名称和原始类型更像真实公园/绿地空间"
        else:
            adjustment -= 7.0
            signals.append("park_false_positive")
            reason = "名称或原始类型更像商超/商业设施，降低公园候选优先级"
    elif real_type == "茶馆":
        if _looks_like_teahouse(poi):
            adjustment += 1.4
            signals.append("real_teahouse_entity")
            reason = "更像可坐下品茶的茶馆/茶楼"
        elif _text_contains_any(name, TEAHOUSE_BEVERAGE_TERMS) or any(term in raw_type for term in ("冷饮店", "甜品店")):
            penalty = -2.6 if "茶馆" in raw_goal else -0.9
            adjustment += penalty
            signals.append("tea_beverage_not_teahouse")
            reason = "更像茶饮/冷饮门店，不完全匹配茶馆需求"
        elif _has_any_keyword(name, TEAHOUSE_CHESS_TERMS):
            adjustment -= 2.4
            signals.append("chess_room_not_teahouse")
            reason = "更像棋牌室，降低茶馆推荐优先级"
    elif real_type == "饮品":
        if "咖啡" in raw_goal:
            if _looks_like_coffee_place(poi):
                adjustment += 1.8
                signals.append("coffee_name_match")
                reason = "名称/类型明确匹配咖啡需求"
            else:
                adjustment -= 1.0
                signals.append("generic_beverage_for_coffee_query")
                reason = "当前需求是咖啡，普通饮品门店降权"
            if _text_contains_any(name + raw_type, COFFEE_WEAK_TERMS):
                adjustment -= 0.5
                signals.append("coffee_context_noise")
    elif real_type == "酒吧":
        if _looks_like_bar_place(poi):
            adjustment += 1.6
            signals.append("bar_entity")
            reason = "名称或原始类型更像酒吧/小酒馆，适合夜间喝酒需求"
        else:
            adjustment -= 4.0
            signals.append("not_bar_entity")
            reason = "名称或原始类型不像酒吧，降低喝酒场景优先级"
    elif real_type == "超市":
        if "买菜" in raw_goal or "采购" in raw_goal:
            if _looks_like_market_for_grocery(poi):
                adjustment += 1.2
                signals.append("grocery_market_entity")
                reason = "更像菜市场/生鲜超市，适合买菜需求"
            else:
                adjustment -= 0.8
                signals.append("generic_supermarket_for_grocery")
    elif real_type == "中餐":
        if _looks_like_restaurant_entity(poi, real_type):
            adjustment += 0.9
            signals.append("restaurant_entity")
            reason = "原始类型和名称更像可就餐的中餐门店"
        else:
            adjustment -= 5.5
            signals.append("not_restaurant_entity")
            reason = "名称或原始类型不像中餐厅，降低候选优先级"
        if "安静" in raw_goal and _has_any_keyword(name, ["茶", "楼", "轩", "苑"]):
            adjustment += 0.3
            signals.append("quiet_name_hint")
    elif real_type == "商场":
        if _looks_like_real_mall(name):
            adjustment += 1.8
            signals.append("real_mall_entity")
            reason = "名称更像商场本体而不是内部店铺"
        else:
            adjustment -= 3.5
            signals.append("mall_inner_shop")
            reason = "名称更像商场内普通店铺，降低商场候选优先级"
    elif real_type == "超市":
        if _looks_like_supermarket(poi):
            adjustment += 1.2
            signals.append("supermarket_entity")
            reason = "名称/原始类型匹配超市或生鲜采购场景"
        else:
            adjustment -= 2.5
            signals.append("weak_supermarket_entity")
            reason = "超市实体特征较弱"

    return adjustment, signals, reason


def _is_junk_candidate(poi, real_type=None):
    real_type = _correct_candidate_type(poi, real_type or "其他")
    name = poi.get("name", "")
    if _has_any_keyword(name, BAD_STATUS_PATTERNS):
        return True
    if _has_any_keyword(name, JUNK_NAME_PATTERNS):
        return True
    if real_type == "火锅" and _has_any_keyword(poi.get("type", ""), HOTPOT_NON_RESTAURANT_RAW_TYPES):
        return True
    if real_type == "商场" and not _looks_like_real_mall(name):
        return True
    if real_type == "公园" and not _looks_like_real_park(poi):
        return True
    if real_type == "中餐" and not _looks_like_restaurant_entity(poi, real_type):
        return True
    if real_type == "茶馆" and not _looks_like_teahouse(poi):
        return True
    if real_type == "酒吧" and not _looks_like_bar_place(poi):
        return True
    if real_type == "超市" and not _looks_like_supermarket(poi):
        return True
    return False


def _looks_like_real_mall(name):
    if not name or _has_any_keyword(name, SMALL_SHOP_KEYWORDS):
        return False
    base_name = re.split(r"[（(]", name)[0].strip()
    if any(base_name.startswith(prefix) for prefix in MALL_ENTITY_PREFIXES):
        return True
    if _has_any_keyword(base_name, ["购物中心", "商场", "奥特莱斯", "太古里", "IFS", "WIFC"]):
        return True
    if re.search(r"(?i)(^|[^a-z])mall($|[^a-z])", base_name):
        return True
    return False


def _strict_single_type_match(real_type, cat, target_types, exact_types):
    if exact_types:
        return real_type in exact_types
    return any(_type_matches(real_type, target) for target in target_types) or cat in target_types


def _is_route_low_value(poi, real_type, constraints):
    real_type = _correct_candidate_type(poi, real_type)
    name = poi.get("name", "")
    if _has_any_keyword(name, LOW_VALUE_ROUTE_NAME_PATTERNS) and not (
        real_type == "超市" and _looks_like_supermarket(poi)
    ):
        return True
    if any(_type_matches(real_type, tag) for tag in constraints.get("preferred_tags", [])):
        return False
    if real_type == "购物" and not _looks_like_real_mall(name):
        return True
    if real_type in LOW_VALUE_ROUTE_TYPES:
        return True
    if _has_any_keyword(name, LOW_VALUE_ROUTE_NAME_PATTERNS):
        return True
    return False


def _straight_distance_m(lng1, lat1, lng2, lat2):
    from math import radians, sin, cos, sqrt, atan2
    R = 6371000
    dlon = radians(lng2 - lng1)
    dlat = radians(lat2 - lat1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    return 2 * R * atan2(sqrt(a), sqrt(1-a))


def _travel_time_from_distance(dist_m, mode):
    return dist_m / 80 if mode == "walk" else dist_m / 200


def _route_from_location_to_poi(network, from_lng, from_lat, poi, mode):
    to_lng = poi["longitude"]
    to_lat = poi["latitude"]
    if network and network.is_connected(poi["poi_id"]):
        best_node = None
        best_dist = float("inf")
        for nid, node in network.nodes.items():
            dx = node["lng"] - from_lng
            dy = node["lat"] - from_lat
            d2 = dx*dx + dy*dy
            if d2 < best_dist:
                best_dist = d2
                best_node = nid
        if best_node:
            dist_m, time_min, path = network.get_route_between(best_node, poi["poi_id"], mode)
            if dist_m is not None:
                node = network.nodes.get(best_node)
                if node:
                    start_gap = _straight_distance_m(from_lng, from_lat, node["lng"], node["lat"])
                    dist_m += start_gap
                    time_min += _travel_time_from_distance(start_gap, mode)
                coords = [[from_lat, from_lng]]
                if path:
                    coords.extend(network.get_path_coords(path))
                return dist_m, time_min, path, coords
    dist_m = _straight_distance_m(from_lng, from_lat, to_lng, to_lat)
    time_min = _travel_time_from_distance(dist_m, mode)
    return dist_m, time_min, [], [[from_lat, from_lng], [to_lat, to_lng]]

# 停留时间（分钟）
STAY_TIME = {
    "景点": 50, "公园": 40, "游乐园": 60,
    "火锅": 50, "烧烤": 45, "中餐": 40, "小吃": 20, "外国菜": 45, "甜品": 25, "饮品": 20,
    "茶馆": 35, "农家乐": 45,
    "KTV": 60, "酒吧": 50, "电影院": 120, "健身": 60, "按摩SPA": 60,
    "商场": 40, "超市": 20, "便利店": 10,
    "数码": 25, "服饰": 30, "美妆": 40, "家居": 30,
    "住宿": 0,
    "购物": 25, "休闲": 35,
    "其他": 20,
}

# 方案参数（从 config.py 读取，支持环境变量覆盖）
VARIANTS = VARIANT_PARAMS

# 低价值类型：路线规划中直接排除（住宿/医疗/汽车/培训等）
EXCLUDED_ROUTE_TYPES = {"住宿", "医疗", "汽车", "培训", "宠物"}

# ========== 类型大类与约束 ==========
TYPE_CATEGORIES = {
    "景点": {"景点", "公园", "游乐园"},
    "餐饮": {"火锅", "烧烤", "中餐", "小吃", "外国菜", "甜品", "饮品", "农家菜"},
    "购物": {"商场", "超市", "便利店", "数码", "家电数码", "服饰", "美妆", "家居", "购物"},
    "休闲": {"茶馆", "KTV", "酒吧", "电影院", "健身", "按摩SPA", "休闲", "农家乐", "网吧"},
}

# 大类上限约束（从 config.py 读取）
CATEGORY_LIMITS = CATEGORY_LIMITS

# 具体类型上限（从 config.py 读取）
CONCRETE_TYPE_LIMIT = CONCRETE_TYPE_LIMIT

# 路线节奏：同一具体类型只去一次（火锅→茶馆→火锅 是不允许的）
# 大类本身允许最多 2 个不同类型（火锅+小吃 是可以的）
CATEGORY_ONE_WAY = set()  # 不限制大类单向，只限制具体类型

# 变体差异化：每个变体对各类型大类的额外评分
def _get_category(real_type):
    for cat, types in TYPE_CATEGORIES.items():
        if real_type in types:
            return cat
    return "其他"


CN_NUM = {
    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
    "十一": 11, "十二": 12, "两": 2, "俩": 2, "廿": 20, "卅": 30,
}


def _parse_cn_number(s):
    s = str(s or "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        pass
    if s in CN_NUM:
        return CN_NUM[s]
    if s.startswith("十") and len(s) > 1:
        tail = CN_NUM.get(s[1:])
        if tail is not None:
            return 10 + tail
    if "十" in s:
        head, tail = s.split("十", 1)
        head_num = CN_NUM.get(head, 1)
        tail_num = CN_NUM.get(tail, 0) if tail else 0
        return head_num * 10 + tail_num
    return None


def _format_budget_hours(hours):
    try:
        value = float(hours)
    except (TypeError, ValueError):
        return hours
    if value.is_integer():
        return int(value)
    return round(value, 1)


def _explicit_time_budget(goal_text, goal_lower):
    time_match = re.search(GOAL_PATTERNS["time_budget"], goal_lower)
    if not time_match:
        return None, "inferred"
    if "半小时" in goal_text:
        return 0.5, "explicit"
    num = time_match.group(1)
    cn_num = time_match.group(2)
    if num:
        return _format_budget_hours(float(num)), "explicit"
    parsed_cn = _parse_cn_number(cn_num)
    if parsed_cn is not None:
        return _format_budget_hours(parsed_cn), "explicit"
    if "半日" in goal_text or "半天" in goal_text:
        return 4, "explicit"
    if "一日" in goal_text or "一天" in goal_text or "全天" in goal_text:
        return 8, "explicit"
    return None, "inferred"


def _infer_time_budget_hours(goal_text, preferred, sequence):
    """Infer a practical time budget when the user did not state one."""
    text = goal_text or ""
    if any(k in text for k in ("半日", "半天")):
        return 4
    if any(k in text for k in ("一日", "一天", "全天")):
        return 8
    if any(k in text for k in ("出差", "赶时间", "快速", "就近", "路过")):
        return 1.5
    if sequence:
        if len(sequence) >= 3:
            return 3.5
        if any(t in sequence for t in ("酒吧", "KTV", "电影院", "按摩SPA")):
            return 3
        if any(t in sequence for t in ("商场", "景点", "公园")):
            return 2.5
        return 2
    concrete = [t for t in preferred if t not in TYPE_CATEGORIES]
    if len(concrete) >= 2:
        return 2.5
    if any(t in preferred for t in ("酒吧", "KTV", "电影院", "按摩SPA")):
        return 2.5
    if any(t in preferred for t in ("景点", "公园", "游乐园", "购物", "商场")):
        return 2
    if any(t in preferred for t in ("火锅", "烧烤", "中餐", "外国菜", "农家菜", "餐饮")):
        return 1.5
    if any(t in preferred for t in ("饮品", "甜品", "茶馆", "小吃", "超市", "便利店")):
        return 1
    return 3



VARIANT_BONUS = {
    "efficient": {"景点": 0.6, "餐饮": 0.4, "休闲": 0.4, "购物": 0.0, "其他": 0.2},
    "relaxed":   {"景点": 1.5, "餐饮": 0.3, "休闲": 1.2, "购物": 0.0, "其他": 0.3},
    "food_first":{"景点": 0.3, "餐饮": 2.2, "休闲": 0.5, "购物": -0.8, "其他": 0.1},
}


def parse_goal(goal_text):
    """解析用户自然语言意图"""
    goal_lower = goal_text.lower()
    
    # 时间预算：显式时间优先；未说明时按意图形态推断，避免所有请求都落到固定 4 小时。
    hours, time_budget_source = _explicit_time_budget(goal_text, goal_lower)

    # 出行方式
    if re.search(GOAL_PATTERNS["mode_walk"], goal_lower):
        mode = "walk"
    elif re.search(GOAL_PATTERNS["mode_bike"], goal_lower):
        mode = "bike"
    elif re.search(GOAL_PATTERNS["mode_drive"], goal_lower):
        mode = "drive"
    elif re.search(GOAL_PATTERNS["mode_bus"], goal_lower):
        mode = "bus"
    else:
        mode = "walk"

    # 偏好标签（v3修复："逛公园"优先解析为公园而不是购物）
    preferred = []
    
    # 先检查明确的非购物意图
    if re.search(r"逛公园|逛景区|逛景点|逛动物园|游乐园", goal_lower):
        preferred.append("公园")
        preferred.append("景点")
    elif re.search(r"逛街|逛商场|逛超市|买东西|购物", goal_lower):
        preferred.append("购物")
    
    if re.search(GOAL_PATTERNS["sight"], goal_lower):
        preferred.append("景点")
        preferred.append("公园")
        # 检测具体景点类型
        if "公园" in goal_text:
            preferred.append("公园")
        if "游乐园" in goal_text:
            preferred.append("游乐园")
        # "晚上去哪玩"等表达 → 也加入休闲
        if "晚上" in goal_text or "去哪玩" in goal_text or "夜生活" in goal_text:
            preferred.append("休闲")
    if re.search(GOAL_PATTERNS["food"], goal_lower):
        preferred.append("餐饮")
        # 检测具体餐饮类型
        if "火锅" in goal_text:
            preferred.append("火锅")
        if "烧烤" in goal_text:
            preferred.append("烧烤")
        if "小吃" in goal_text or "夜宵" in goal_text:
            preferred.append("小吃")
        if "夜宵" in goal_text and "烧烤" not in preferred:
            preferred.append("烧烤")
        if any(term in goal_text for term in ("中餐", "炒菜", "午餐", "午饭", "晚餐", "正餐", "吃饭", "餐厅")):
            preferred.append("中餐")
        if "甜品" in goal_text or "蛋糕" in goal_text or "下午茶" in goal_text:
            preferred.append("甜品")
        if "饮品" in goal_text or "咖啡" in goal_text or "奶茶" in goal_text:
            preferred.append("饮品")
        if "外国菜" in goal_text or "西餐" in goal_text:
            preferred.append("外国菜")
        if "农家菜" in goal_text or "农家" in goal_text:
            preferred.append("农家菜")
        # 喝茶/茶饮 → 饮品或茶馆
        if "喝茶" in goal_text or "茶饮" in goal_text or "下午茶" in goal_text:
            preferred.append("饮品")
            if "茶馆" not in preferred:
                preferred.append("茶馆")
    if re.search(GOAL_PATTERNS["relax"], goal_lower):
        preferred.append("休闲")
        # 检测具体休闲类型
        if "酒吧" in goal_text or "喝酒" in goal_text or "小酒馆" in goal_text:
            preferred.append("酒吧")
        if "KTV" in goal_text or "ktv" in goal_text:
            preferred.append("KTV")
        if "茶馆" in goal_text or "茶舍" in goal_text or "喝茶" in goal_text:
            preferred.append("茶馆")
        if "电影院" in goal_text or "看电影" in goal_text or "电影" in goal_text:
            preferred.append("电影院")
        if "按摩" in goal_text or "SPA" in goal_text:
            preferred.append("按摩SPA")
        if "下午茶" in goal_text:
            preferred.append("甜品")
        if "情侣" in goal_text or "约会" in goal_text:
            preferred.extend(["电影院", "甜品", "饮品", "茶馆"])
    if re.search(GOAL_PATTERNS["shopping"], goal_lower):
        preferred.append("购物")
        # 检测具体购物类型
        if "商场" in goal_text:
            preferred.append("商场")
        if "超市" in goal_text:
            preferred.append("超市")
        if "便利店" in goal_text:
            preferred.append("便利店")
        if "买菜" in goal_text or "采购" in goal_text:
            preferred.append("超市")
    
    if not preferred:
        preferred = ["景点", "餐饮"]

    # 去重保持顺序
    seen = set()
    preferred = [p for p in preferred if not (p in seen or seen.add(p))]

    # 顺序约束解析："先吃火锅再去茶馆"、"吃完火锅去茶馆"
    sequence = []
    # 模式1: 先...再/然后/接着/之后/去...
    seq_match = re.search(r"先(.*?(?:火锅|烧烤|小吃|茶馆|咖啡|公园|景点|商场|超市|电影院|酒吧|KTV|按摩|SPA|餐厅|川菜|西餐))(?:再|然后|接着|之后|去)(.*?(?:火锅|烧烤|小吃|茶馆|咖啡|公园|景点|商场|超市|电影院|酒吧|KTV|按摩|SPA|餐厅|川菜|西餐))", goal_lower)
    if seq_match:
        sequence = [seq_match.group(1).strip(), seq_match.group(2).strip()]
    else:
        # 模式2: 吃完...去...、逛完...去...
        seq_match2 = re.search(r"(?:吃完|逛完|去完|玩完|看完)(.*?)(?:去|再到|再去|顺便|接着)(.*)", goal_lower)
        if seq_match2:
            sequence = [seq_match2.group(1).strip(), seq_match2.group(2).strip()]
    # 把顺序关键词映射到类型
    def _seq_to_type(text):
        if "火锅" in text: return "火锅"
        if "烧烤" in text: return "烧烤"
        if "小吃" in text or "夜宵" in text: return "小吃"
        if "茶馆" in text or "茶" in text: return "茶馆"
        if "咖啡" in text: return "饮品"
        if "公园" in text: return "公园"
        if "景点" in text: return "景点"
        if "商场" in text: return "商场"
        if "超市" in text: return "超市"
        if "电影" in text: return "电影院"
        if "酒吧" in text or "喝酒" in text or "小酒馆" in text: return "酒吧"
        if "ktv" in text: return "KTV"
        if "按摩" in text or "spa" in text: return "按摩SPA"
        if any(term in text for term in ("餐厅", "川菜", "中餐", "午餐", "午饭", "晚餐", "正餐", "吃饭")): return "中餐"
        if "西餐" in text or "外国菜" in text: return "外国菜"
        return None
    sequence = [_seq_to_type(s) for s in sequence if _seq_to_type(s)]
    if not sequence and (_contains_any(goal_text, MULTI_INTENT_CONNECTORS) or _has_multi_concrete_goal(goal_text)):
        ordered_mentions = []
        for kw, typ in CONCRETE_GOAL_TERMS:
            idx = goal_text.find(kw)
            if idx >= 0:
                ordered_mentions.append((idx, typ))
        ordered_mentions.sort()
        for _, typ in ordered_mentions:
            if typ not in sequence:
                sequence.append(typ)

    if hours is None:
        hours = _infer_time_budget_hours(goal_text, preferred, sequence)
        time_budget_source = "inferred"

    # 起始时间解析（支持中文数字和阿拉伯数字）
    def _parse_hour(s):
        s = s.strip()
        if s.isdigit():
            return int(s)
        parsed = _parse_cn_number(s)
        return int(parsed) if parsed is not None else None

    start_time = "09:00"
    ampm_match = re.search(GOAL_PATTERNS["start_time_ampm"], goal_text)
    if ampm_match:
        ampm = ampm_match.group(1)
        h = _parse_hour(ampm_match.group(2))
        m = ampm_match.group(3)
        if h is not None:
            minute = int(m) if m and m.isdigit() else 0
            hour = h
            if ampm in ("下午", "晚上") and hour < 12:
                hour += 12
            if ampm == "中午" and hour < 10:
                hour += 12
            if ampm == "凌晨" and hour >= 12:
                hour -= 12
            start_time = "{:02d}:{:02d}".format(hour, minute)
    else:
        time_match2 = re.search(GOAL_PATTERNS["start_time"], goal_text)
        if time_match2:
            h = _parse_hour(time_match2.group(1))
            m = time_match2.group(2)
            if h is not None:
                minute = int(m) if m and m.isdigit() else 0
                # 无AM/PM时，简单规则：<=6 视为晚上（18-23），>6 且 <12 视为上午
                if h <= 6:
                    h += 12
                start_time = "{:02d}:{:02d}".format(h, minute)

    return {
        "raw_goal": goal_text,
        "time_budget_hours": hours,
        "time_budget_source": time_budget_source,
        "mode": mode,
        "preferred_tags": preferred,
        "must_visit": [],
        "avoid_tags": [],
        "start_time": start_time,
        "sequence": sequence,
    }


def load_hours(hours_path):
    with open(hours_path, "r", encoding="utf-8") as f:
        return json.load(f)


def is_open_at(poi_id, arrival_time_str, hours_map):
    """检查POI在到达时间是否营业"""
    h = hours_map.get(poi_id)
    if not h:
        return True  # 没有数据默认营业

    # 解析时间
    try:
        arr = datetime.strptime(arrival_time_str, "%H:%M")
        open_t = datetime.strptime(h["open_time"], "%H:%M")
        close_t = datetime.strptime(h["close_time"], "%H:%M")
    except:
        return True

    if h["overnight"]:
        # 跨天营业（如19:00-04:00）
        if close_t <= open_t:
            return arr >= open_t or arr <= close_t
        else:
            return open_t <= arr <= close_t
    else:
        return open_t <= arr <= close_t


def _round_feature(value, digits=3):
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return value


def _public_constraints(constraints):
    return {k: v for k, v in constraints.items() if not str(k).startswith("_")}


def _resolve_real_type(poi, type_index=None):
    if type_index:
        return type_index.get(poi["poi_id"], "其他")
    from ugc_type_profiles import infer_real_type
    return infer_real_type(poi)


def _score_poi_features(poi, gt, constraints, route_types_so_far, network, type_index=None):
    """Return ranking score plus auditable feature contributions."""
    real_type = _resolve_real_type(poi, type_index)
    if real_type == "购物" and _looks_like_real_mall(poi.get("name", "")):
        real_type = "商场"
    real_type = _correct_candidate_type(poi, real_type)
    cat = _get_category(real_type)
    base = gt.get("overall", 3.0)
    type_weight = _type_weight(real_type, constraints)
    score = base * type_weight
    review_count, popularity_adjustment, popularity_components = _estimated_review_signal(poi, real_type, base)
    features = {
        "quality_score": _round_feature(base),
        "type_weight": _round_feature(type_weight),
        "quality_type_contribution": _round_feature(base * type_weight),
        "matched_preferences": [],
        "preference_bonus": 0.0,
        "diversity_bonus": 0.0,
        "density": poi.get("grid_density", 1),
        "density_bonus": 0.0,
        "review_count_estimate": review_count,
        "popularity_adjustment": 0.0,
        "popularity_components": popularity_components,
        "network_connected": True if not network else bool(network.is_connected(poi["poi_id"])),
        "connectivity_penalty": 0.0,
        "semantic_need_adjustment": 0.0,
        "type_consistency_penalty": 0.0,
        "excluded_mode_penalty": 0.0,
        "nearest_same_type_m": poi.get("nearest_same_type_m", 0),
        "brand_popularity_bonus": 0.0,
        "matched_brand": None,
        "entity_quality_adjustment": 0.0,
        "entity_quality_signals": [],
        "distance_to_start_m": None,
        "proximity_adjustment": 0.0,
    }
    reasons = [
        f"质量评分 {base:.1f}，{constraints.get('user_mode_label', '当前模式')} 对 {real_type} 权重 {type_weight:.2f}",
    ]

    if _is_excluded_by_mode(real_type, constraints):
        features["excluded_mode_penalty"] = -8.0
        score += features["excluded_mode_penalty"]
        reasons.append("当前用户模式或避让画像降低该类型优先级")

    pref_bonus = 0
    for tag in constraints.get("preferred_tags", []):
        if tag in [real_type] or tag in poi.get("tags", []):
            pref_bonus += 3.0
            features["matched_preferences"].append(tag)
        elif _type_matches(real_type, tag):
            pref_bonus += 1.5
            features["matched_preferences"].append(tag)
    score += pref_bonus
    features["preference_bonus"] = _round_feature(pref_bonus)
    if features["matched_preferences"]:
        reasons.append("命中用户偏好：" + "、".join(features["matched_preferences"][:4]))

    if real_type not in route_types_so_far:
        features["diversity_bonus"] = 0.6
        score += features["diversity_bonus"]
        reasons.append("路线中尚未出现该具体类型，提升多样性")

    density = poi.get("grid_density", 1)
    features["density_bonus"] = _round_feature(min(0.3, density / 50))
    score += features["density_bonus"]
    if features["density_bonus"] > 0:
        reasons.append("所在网格有一定 POI 密度，位置数据可信度较高")

    score += popularity_adjustment
    features["popularity_adjustment"] = _round_feature(popularity_adjustment)
    if popularity_adjustment >= 0.75:
        reasons.append(f"评价热度估计约 {review_count} 条，口碑样本相对更充分")

    generic_adjustment, generic_signals, generic_reason = _generic_entity_adjustment(poi, real_type, constraints)
    if generic_adjustment:
        score += generic_adjustment
        features["entity_quality_adjustment"] = _round_feature(
            features.get("entity_quality_adjustment", 0.0) + generic_adjustment
        )
        features["entity_quality_signals"] = list(features.get("entity_quality_signals", [])) + generic_signals
        if generic_reason:
            reasons.append(generic_reason)

    center_lng = constraints.get("center_lng")
    center_lat = constraints.get("center_lat")
    if center_lng is not None and center_lat is not None:
        dist_to_start = _straight_distance_m(center_lng, center_lat, poi["longitude"], poi["latitude"])
        features["distance_to_start_m"] = _round_feature(dist_to_start, 1)
        if constraints.get("intent_type") == "single_poi":
            if dist_to_start <= 500:
                proximity_adjustment = 1.0
            elif dist_to_start <= 900:
                proximity_adjustment = 0.7
            elif dist_to_start <= 1500:
                proximity_adjustment = 0.4
            elif dist_to_start >= 2600:
                proximity_adjustment = -0.4
            else:
                proximity_adjustment = 0.0
            if proximity_adjustment:
                score += proximity_adjustment
                features["proximity_adjustment"] = _round_feature(proximity_adjustment)
                if proximity_adjustment > 0:
                    reasons.append("离起点更近，适合附近即时推荐")
                else:
                    reasons.append("距离起点较远，降低附近推荐优先级")

    if real_type == "火锅":
        brand_name, brand_bonus, brand_stats = _hotpot_brand_signal(poi, constraints)
        entity_adjustment, entity_signals = _hotpot_entity_adjustment(poi)
        if brand_bonus:
            score += brand_bonus
            features["brand_popularity_bonus"] = _round_feature(brand_bonus)
            features["matched_brand"] = brand_name
            features["brand_signal"] = {
                "global_branch_count": brand_stats.get("global_count", 0),
                "local_branch_count": brand_stats.get("local_count", 0),
                "best_quality": brand_stats.get("best_quality", 0),
                "anchor_store_count": brand_stats.get("flagship_count", 0),
            }
            reasons.append(f"同品牌在本地数据中有多家可识别门店：{brand_name}")
        if entity_adjustment:
            score += entity_adjustment
            features["entity_quality_adjustment"] = _round_feature(
                features.get("entity_quality_adjustment", 0.0) + entity_adjustment
            )
            features["entity_quality_signals"] = list(features.get("entity_quality_signals", [])) + entity_signals
            if entity_adjustment > 0:
                reasons.append("更像正餐火锅门店，适合到店推荐")
            else:
                reasons.append("轻餐/附属服务属性较强，降低正餐火锅优先级")

    if network and not network.is_connected(poi["poi_id"]):
        features["connectivity_penalty"] = -1.0
        score += features["connectivity_penalty"]
        reasons.append("路网连通性弱，降低推荐优先级")

    user_needs = constraints.get("user_needs") or {}
    if user_needs.get("labels") or user_needs.get("must_not") or user_needs.get("budget_max"):
        semantic_adjustment = poi_matcher.match_score(poi, real_type, user_needs, gt)
        features["semantic_need_adjustment"] = _round_feature(semantic_adjustment)
        score += semantic_adjustment
        if semantic_adjustment > 0:
            reasons.append("匹配画像/语义需求：" + "、".join((user_needs.get("labels") or [])[:4]))
        elif semantic_adjustment < 0:
            reasons.append("与部分语义约束或避让条件冲突")

    from ugc_type_profiles import infer_real_type
    inferred = infer_real_type(poi)
    features["name_inferred_type"] = inferred
    features["resolved_type"] = real_type
    features["category"] = cat
    if inferred != real_type and _get_category(inferred) != _get_category(real_type):
        if real_type in ("景点", "服饰", "购物", "数码", "美妆", "家居"):
            penalty = -3.0
        elif inferred in ("住宿", "医疗", "培训", "宠物", "汽车"):
            penalty = -2.0
        else:
            penalty = -1.0
        features["type_consistency_penalty"] = penalty
        score += penalty
        reasons.append(f"名称推断为 {inferred}，与索引类型不完全一致")

    return score, features, reasons, real_type


def score_poi_v3(poi, gt, constraints, route_types_so_far, network, type_index=None):
    """v3评分：类型优先级 + GT质量 + 多样性奖励 + 路网可达性 + 类型一致性惩罚"""
    score, _, _, _ = _score_poi_features(poi, gt, constraints, route_types_so_far, network, type_index)
    return score


def _build_recommendation_basis(score, features, reasons, arrival_time=None, open_at_arrival=True,
                                distance_m=None, travel_time_min=None, variant_name=None,
                                semantic_boost=0.0, sequence_boost=0.0, distance_penalty=0.0,
                                special_bonus=0.0, variant_bonus=0.0, start_selection_bonus=0.0,
                                start_fallback=False, llm_review_bonus=0.0, llm_review_reason=None):
    full_features = dict(features)
    if arrival_time is not None:
        full_features["arrival_time"] = arrival_time
    full_features["open_at_arrival"] = bool(open_at_arrival)
    if distance_m is not None:
        full_features["distance_m"] = _round_feature(distance_m, 1)
    if travel_time_min is not None:
        full_features["travel_time_min"] = _round_feature(travel_time_min, 1)
    if variant_name:
        full_features["variant"] = variant_name
    if semantic_boost:
        full_features["semantic_search_boost"] = _round_feature(semantic_boost)
    if sequence_boost:
        full_features["sequence_boost"] = _round_feature(sequence_boost)
    if distance_penalty:
        full_features["route_distance_penalty"] = _round_feature(distance_penalty)
    if special_bonus:
        full_features["single_poi_special_bonus"] = _round_feature(special_bonus)
    if variant_bonus:
        full_features["variant_bonus"] = _round_feature(variant_bonus)
    if start_selection_bonus:
        full_features["start_selection_bonus"] = _round_feature(start_selection_bonus)
    if start_fallback:
        full_features["start_fallback"] = True
    if llm_review_bonus:
        full_features["llm_candidate_review_bonus"] = _round_feature(llm_review_bonus)
    if llm_review_reason:
        full_features["llm_candidate_review_reason"] = llm_review_reason

    top_reasons = list(reasons)
    if open_at_arrival:
        top_reasons.append("抵达时段可营业或无关闭数据")
    else:
        top_reasons.append("抵达时段营业风险较高")
    if travel_time_min is not None:
        top_reasons.append(f"移动约 {travel_time_min:.1f} 分钟")
    if semantic_boost:
        top_reasons.append("语义检索命中当前目标")
    if sequence_boost:
        top_reasons.append("符合用户指定的访问顺序")
    if distance_penalty:
        top_reasons.append("因移动成本进行距离惩罚")
    if special_bonus:
        top_reasons.append("单点场景下命中强偏好特征")
    if variant_bonus:
        top_reasons.append("符合当前路线变体的偏好方向")
    if start_selection_bonus:
        top_reasons.append("适合作为当前路线起点")
    if start_fallback:
        top_reasons.append("路网起点候选不足，已使用直线距离降级")
    if llm_review_bonus:
        top_reasons.append(llm_review_reason or "大模型候选评审认为更符合当前需求")

    return {
        "model": RANKING_MODEL_VERSION,
        "score": round(score, 3),
        "top_reasons": top_reasons[:8],
        "features": full_features,
    }


def _build_review_summary(poi, real_type, gt, basis=None):
    """Create user-facing review notes from local aggregate signals."""
    gt = gt or {}
    basis = basis or {}
    features = basis.get("features", {})
    review_count = features.get("review_count_estimate")
    rating = float(gt.get("overall", 0) or 0)
    highlights = []
    dim_labels = {"taste": "口味", "env": "环境", "service": "服务", "value": "性价比", "queue": "等位"}
    dims = []
    for key, label in dim_labels.items():
        try:
            value = float(gt.get(key, 0) or 0)
        except (TypeError, ValueError):
            value = 0
        if value > 0:
            dims.append((value, label))
    dims.sort(reverse=True)

    if rating >= 4.5:
        highlights.append("综合口碑突出")
    elif rating >= 4.0:
        highlights.append("评价稳定")
    elif rating >= 3.5:
        highlights.append("口碑表现中上")
    if review_count:
        try:
            count = int(review_count)
            if count >= 250:
                highlights.append("热度较高")
            elif count >= 120:
                highlights.append("评价样本较充分")
        except (TypeError, ValueError):
            pass
    for _, label in dims[:2]:
        if label not in "".join(highlights):
            highlights.append(f"{label}反馈较好")
    for scene in gt.get("best_for", [])[:2]:
        if isinstance(scene, str) and not any(ch in scene for ch in ("�", "Ã", "Â", "å", "æ", "é")):
            highlights.append(f"适合{scene}")
    if real_type in ("火锅", "烧烤", "中餐", "小吃", "外国菜"):
        template = "多数反馈集中在口味、出餐和聚餐体验，适合作为本次用餐候选。"
    elif real_type in ("饮品", "甜品", "茶馆"):
        template = "多数反馈集中在环境、停留舒适度和聊天体验，适合放慢节奏。"
    elif real_type in ("景点", "公园", "游乐园"):
        template = "多数反馈集中在可逛性、拍照和亲友同行体验，适合串联行程。"
    elif real_type in ("商场", "购物"):
        template = "多数反馈集中在动线、品牌丰富度和顺路程度，适合和餐饮组合。"
    else:
        template = "多数反馈显示它和当前目标匹配度较高，可作为备选点位。"

    return {
        "rating_label": "口碑{}".format("突出" if rating >= 4.5 else "稳定" if rating >= 4.0 else "尚可"),
        "review_count_estimate": review_count,
        "highlights": list(dict.fromkeys(highlights))[:4],
        "selected_comment": template,
        "crowd_type": gt.get("crowd_type") if isinstance(gt.get("crowd_type"), str) and not any(ch in gt.get("crowd_type", "") for ch in ("�", "Ã", "Â", "å", "æ", "é")) else None,
        "best_for": [x for x in gt.get("best_for", [])[:3] if isinstance(x, str) and not any(ch in x for ch in ("�", "Ã", "Â", "å", "æ", "é"))],
    }


def _model_metadata(intent_result, constraints, trace, semantic_poi_ids=None):
    return {
        "planner_version": PLANNER_VERSION,
        "ranking_model": RANKING_MODEL_VERSION,
        "strategy": "feature-weighted constraint planner",
        "intent": {
            "type": constraints.get("intent_type"),
            "provider": constraints.get("intent_provider", "fallback"),
            "llm_used": bool(constraints.get("llm_used", False)),
            "reason": constraints.get("intent_reason"),
            "error": constraints.get("llm_error"),
        },
        "feature_sources": [
            "ground_truth_quality",
            "ugc_type_index_and_name_correction",
            "business_hours",
            "road_network_or_distance",
            "spatial_density",
            "estimated_review_volume",
            "nearest_same_type_distance",
            "data_driven_brand_recognition",
            "entity_fit_quality",
            "semantic_needs",
            "session_and_user_profile",
            "route_diversity_constraints",
        ],
        "candidate_pipeline": trace,
        "semantic": {
            "enabled": bool(semantic_poi_ids),
            "matched_count": len(semantic_poi_ids or []),
            "top_k": SEMANTIC_TOP_K,
        },
        "constraints_applied": {
            "user_mode": constraints.get("user_mode"),
            "user_mode_label": constraints.get("user_mode_label"),
            "radius_m": constraints.get("radius"),
            "requested_radius_m": constraints.get("requested_radius"),
            "time_budget_hours": constraints.get("time_budget_hours"),
            "time_budget_source": constraints.get("time_budget_source"),
            "start_time": constraints.get("start_time"),
            "preferred_tags": constraints.get("preferred_tags", []),
            "avoid_tags": constraints.get("avoid_tags", []),
            "sequence": constraints.get("sequence", []),
        },
    }


def _filter_candidates_spatial(poi_dict, spatial_index, center_lng, center_lat, radius, network):
    """使用空间索引快速筛选3km范围内的候选POI（poi_dict版本，O(1)查找）"""
    if not spatial_index:
        # fallback: 全量扫描
        candidates = []
        for p in poi_dict.values():
            from math import radians, sin, cos, sqrt, atan2
            R = 6371000
            dlon = radians(p["longitude"] - center_lng)
            dlat = radians(p["latitude"] - center_lat)
            a = sin(dlat/2)**2 + cos(radians(center_lat)) * cos(radians(p["latitude"])) * sin(dlon/2)**2
            dist = 2 * R * atan2(sqrt(a), sqrt(1-a))
            if dist <= radius:
                if not network or network.is_connected(p["poi_id"]):
                    candidates.append(p)
        return candidates

    grid_size = spatial_index["grid_size"]
    poi_map = spatial_index["poi_map"]
    index = spatial_index["index"]

    center_gx = int(center_lng / grid_size)
    center_gy = int(center_lat / grid_size)
    span = int(radius / 500) + 2

    from math import radians, sin, cos, sqrt, atan2
    R = 6371000

    candidates = []
    seen_ids = set()
    for dx in range(-span, span + 1):
        for dy in range(-span, span + 1):
            key = "{},{}".format(center_gx + dx, center_gy + dy)
            if key not in index:
                continue
            for poi_id in index[key]:
                if poi_id in seen_ids:
                    continue
                seen_ids.add(poi_id)
                info = poi_map.get(poi_id)
                if not info:
                    continue
                dlon = radians(info["lng"] - center_lng)
                dlat = radians(info["lat"] - center_lat)
                a = sin(dlat/2)**2 + cos(radians(center_lat)) * cos(radians(info["lat"])) * sin(dlon/2)**2
                dist = 2 * R * atan2(sqrt(a), sqrt(1-a))
                if dist > radius:
                    continue
                if network and not network.is_connected(poi_id):
                    continue
                p = poi_dict.get(poi_id)
                if p:
                    candidates.append(p)
    return candidates


def build_route_v3(pois_or_candidates, gt_data, constraints, hours_map, network, variant_name,
                   spatial_index=None, type_index=None, candidates=None, knn_graph=None,
                   semantic_poi_ids=None, route_limits=None):
    """构建单条路线。支持外部传入预筛选的candidates和KNN图，避免重复Dijkstra"""
    variant = dict(VARIANTS[variant_name])  # 复制一份，避免修改全局
    if route_limits:
        variant.update(route_limits)  # 用外部传入的限制覆盖默认值
    budget_min = constraints["time_budget_hours"] * 60
    mode = constraints["mode"]
    start_time = datetime.strptime(constraints["start_time"], "%H:%M")

    # 如果外部已传入candidates（预筛选+类型过滤+TopN），直接使用
    if candidates is None:
        center_lng = constraints.get("center_lng", DEFAULT_CENTER_LNG)
        center_lat = constraints.get("center_lat", DEFAULT_CENTER_LAT)
        radius = constraints.get("radius", 3000)
        candidates = _filter_candidates_spatial(pois_or_candidates, spatial_index, center_lng, center_lat, radius, network)

        # 按类型过滤低价值POI
        filtered = []
        for p in candidates:
            rt = type_index.get(p["poi_id"], "其他") if type_index else "其他"
            if rt in EXCLUDED_ROUTE_TYPES or _is_excluded_by_mode(rt, constraints):
                continue
            filtered.append(p)
        candidates = filtered

        # 限制候选数量
        if len(candidates) > 150:
            scored = []
            for p in candidates:
                gt = gt_data.get(p["poi_id"], {})
                s = gt.get("overall", 3.0)
                rt = type_index.get(p["poi_id"], "其他") if type_index else "其他"
                for tag in constraints["preferred_tags"]:
                    if tag in [rt] or tag in p.get("tags", []):
                        s += 1.0
                scored.append((s, p))
            scored.sort(key=lambda x: -x[0])
            candidates = [p for _, p in scored[:150]]

    print(f"[RouteBuild] variant={variant_name}, route_limits={route_limits}, candidates={len(candidates)}")
    if not candidates:
        print(f"[RouteFail] No candidates")
        return []

    # 按评分排序，取top N作为起点候选
    scored = []
    for p in candidates:
        gt = gt_data.get(p["poi_id"], {})
        s = score_poi_v3(p, gt, constraints, set(), network, type_index)
        scored.append((s, p))
    scored.sort(key=lambda x: -x[0])

    # 贪心构建路线
    route = []
    current_time = start_time
    current_poi = None
    route_types = set()          # 已选过的具体类型
    total_time = 0
    shopping_count = 0
    mode_cfg = _mode_config(constraints)
    max_shopping = mode_cfg.get("max_shopping", 2 if variant_name == "efficient" else 3)
    max_travel_min = mode_cfg.get("max_travel_min", 30)
    category_counts = {}         # 大类计数
    concrete_type_counts = {}    # 具体类型计数（避免火锅+火锅）
    visited_categories = set()   # 已经"离开过"的大类（单向约束）

    # 选择起点：从Top-N营业候选中，根据变体偏好选择最匹配的
    open_candidates = []
    for s, p in scored:
        rt = type_index.get(p["poi_id"], "其他") if type_index else "其他"
        if _is_excluded_by_mode(rt, constraints):
            continue
        open_candidates.append((s, p))
        if len(open_candidates) >= 120:
            break

    # 按变体偏好排序起点：优先选择变体偏好类型的POI
    # 获取用户起点坐标（用于距离惩罚）
    center_lng = constraints.get("center_lng", DEFAULT_CENTER_LNG)
    center_lat = constraints.get("center_lat", DEFAULT_CENTER_LAT)
    
    def _start_score(item):
        s, p = item
        rt = type_index.get(p["poi_id"], "其他") if type_index else "其他"
        cat = _get_category(rt)
        bonus = 0
        # food_first 优先餐饮起点
        if variant_name == "food_first" and cat == "餐饮":
            bonus = 5
        # relaxed 优先景点/休闲起点
        elif variant_name == "relaxed" and cat in ("景点", "休闲"):
            bonus = 5
        # efficient 优先高分+距离中心近的
        elif variant_name == "efficient":
            bonus = 0
        # 用户偏好匹配：明确提到的具体类型（如火锅）最高优先级
        for tag in constraints["preferred_tags"]:
            if tag in [rt]:
                bonus += 20  # 用户明确提到的类型最高优先级
            elif _get_category(rt) == tag:
                bonus += 3
        # 顺序约束：sequence[0] 类型的POI作为起点获得最高优先级
        sequence = constraints.get("sequence", [])
        if sequence and _sequence_type_matches(rt, sequence[0]):
            bonus += 100
        
        # 距离惩罚：距离起点越远，扣分越多（避免起点选在3公里外的高分POI）
        dist_m = _straight_distance_m(center_lng, center_lat, p["longitude"], p["latitude"])
        # 超过500m开始惩罚，每500m扣1分
        if dist_m > 500:
            bonus -= dist_m / 500
        
        return s + bonus

    # 用户明确偏好的具体类型（直接从输入提取，如"火锅"）
    user_concrete_prefs = set()
    for tag in constraints["preferred_tags"]:
        for types in TYPE_CATEGORIES.values():
            if tag in types:
                user_concrete_prefs.add(tag)
    # 也加入大类对应的子类型（用于兼容性）
    preferred_concrete_types = set(user_concrete_prefs)
    for tag in constraints["preferred_tags"]:
        if tag in TYPE_CATEGORIES:
            preferred_concrete_types.update(TYPE_CATEGORIES[tag])

    # 排序：优先包含偏好类型的POI
    filtered_open_candidates = []
    start_travel = {}
    start_fallback_used = False
    for s, p in open_candidates:
        start_dist_m, start_time_min, _, _ = _route_from_location_to_poi(network, center_lng, center_lat, p, mode)
        arrival_str = (current_time + timedelta(minutes=start_time_min)).strftime("%H:%M")
        if start_time_min <= max_travel_min and is_open_at(p["poi_id"], arrival_str, hours_map):
            start_travel[p["poi_id"]] = (start_dist_m, start_time_min)
            filtered_open_candidates.append((s, p))
    open_candidates = filtered_open_candidates
    open_candidates.sort(key=_start_score, reverse=True)
    if not open_candidates:
        fallback_open_candidates = []
        for s, p in scored[:200]:
            rt = type_index.get(p["poi_id"], "其他") if type_index else "其他"
            if _is_excluded_by_mode(rt, constraints) or _is_route_low_value(p, rt, constraints):
                continue
            start_dist_m = _straight_distance_m(center_lng, center_lat, p["longitude"], p["latitude"])
            start_time_min = _travel_time_from_distance(start_dist_m, mode)
            arrival_str = (current_time + timedelta(minutes=start_time_min)).strftime("%H:%M")
            if start_time_min <= max_travel_min and is_open_at(p["poi_id"], arrival_str, hours_map):
                start_travel[p["poi_id"]] = (start_dist_m, start_time_min)
                fallback_open_candidates.append((s - 1.0, p))
        open_candidates = fallback_open_candidates
        open_candidates.sort(key=_start_score, reverse=True)
        if open_candidates:
            start_fallback_used = True
            print(f"[RouteBuild] variant={variant_name} using straight-distance start fallback")
    
    # 顺序约束强制执行：如果sequence[0]存在，确保起点是它
    sequence = constraints.get("sequence", [])
    if sequence and open_candidates:
        first_type = sequence[0]
        # 检查Top1是否已经是sequence[0]类型
        top_rt = type_index.get(open_candidates[0][1]["poi_id"], "其他") if type_index else "其他"
        if not _sequence_type_matches(top_rt, first_type):
            # 在open_candidates中查找sequence[0]类型的POI并移到最前面
            for i, (s, p) in enumerate(open_candidates):
                rt = type_index.get(p["poi_id"], "其他") if type_index else "其他"
                if _sequence_type_matches(rt, first_type):
                    open_candidates.insert(0, open_candidates.pop(i))
                    print(f"[Sequence] Force start with {first_type}: {p['name']}")
                    break
    
    # 如果Top1不是用户明确偏好的具体类型（如火锅），尝试把明确偏好类型提到前面
    elif user_concrete_prefs and open_candidates:
        top_rt = type_index.get(open_candidates[0][1]["poi_id"], "其他") if type_index else "其他"
        if top_rt not in user_concrete_prefs:
            for i, (s, p) in enumerate(open_candidates):
                rt = type_index.get(p["poi_id"], "其他") if type_index else "其他"
                if rt in user_concrete_prefs:
                    # 把这个候选移到第一位
                    open_candidates.insert(0, open_candidates.pop(i))
                    break

    if open_candidates:
        s, p = open_candidates[0]
        start_rank_score = _start_score((s, p))
        route.append(p)
        p["_route_rank_context"] = {
            "variant": variant_name,
            "rank_score": round(start_rank_score, 3),
            "semantic_boost": SEMANTIC_BOOST if semantic_poi_ids and p["poi_id"] in semantic_poi_ids else 0.0,
            "variant_bonus": 0.0,
            "sequence_boost": 0.0,
            "distance_penalty": 0.0,
            "start_selection_bonus": round(start_rank_score - s, 3),
            "start_fallback": start_fallback_used,
        }
        current_poi = p
        rt = type_index.get(p["poi_id"], "其他") if type_index else "其他"
        route_types.add(rt)
        cat = _get_category(rt)
        category_counts[cat] = category_counts.get(cat, 0) + 1
        concrete_type_counts[rt] = concrete_type_counts.get(rt, 0) + 1
        if _is_shopping_type(rt):
            shopping_count += 1
        stay = _stay_minutes(rt, constraints, variant_name=variant_name)
        _, start_time_min = start_travel.get(p["poi_id"], (0, 0))
        current_time += timedelta(minutes=start_time_min + stay)
        total_time += start_time_min + stay

    if not route:
        print(f"[RouteFail] No starting POI found. open_candidates={len(open_candidates)}, scored={len(scored)}")
        return []

    # 贪心添加后续POI
    used = {route[0]["poi_id"]}
    max_iter = variant["max_pois"] * 3

    for _ in range(max_iter):
        if len(route) >= variant["max_pois"]:
            break
        if total_time >= budget_min * 0.95:
            break

        best_score = -999
        best_poi = None
        best_dist = None
        best_time = None
        best_path = None

        for p in candidates:
            pid = p["poi_id"]
            if pid in used:
                continue

            if type_index:
                rt = type_index.get(pid, "其他")
            else:
                from ugc_type_profiles import infer_real_type
                rt = infer_real_type(p)
            # 大类上限约束
            cat = _get_category(rt)
            if _is_excluded_by_mode(rt, constraints):
                continue

            if category_counts.get(cat, 0) >= _category_limit(cat, constraints):
                continue

            # 同一具体类型最多 1 个（谁要吃两家火锅？）
            if concrete_type_counts.get(rt, 0) >= CONCRETE_TYPE_LIMIT:
                continue

            # 大类单向约束：一旦离开过某大类，不再回去（避免火锅→茶馆→火锅）
            if cat in visited_categories and cat in CATEGORY_ONE_WAY:
                continue

            # 相邻类型约束：同类不能连续（餐饮/景点）
            if route:
                last_rt = type_index.get(route[-1]["poi_id"], "其他") if type_index else "其他"
                last_cat = _get_category(last_rt)
                if cat == last_cat and cat in ("餐饮", "景点"):
                    continue

            # 购物类硬约束
            if _is_shopping_type(rt):
                if shopping_count >= max_shopping:
                    continue

            # 路网距离（优先用KNN缓存图）
            if knn_graph:
                dist_m, time_min = knn_graph.get_distance(current_poi["poi_id"], pid, mode)
                if dist_m is None:
                    continue
                path = []
            elif network:
                dist_m, time_min, path = network.get_route_between(current_poi["poi_id"], pid, mode)
                if dist_m is None:
                    continue
            else:
                #  fallback直线距离
                from math import radians, sin, cos, sqrt, atan2
                R = 6371000
                dlon = radians(p["longitude"] - current_poi["longitude"])
                dlat = radians(p["latitude"] - current_poi["latitude"])
                a = sin(dlat/2)**2 + cos(radians(current_poi["latitude"])) * cos(radians(p["latitude"])) * sin(dlon/2)**2
                dist_m = 2 * R * atan2(sqrt(a), sqrt(1-a))
                time_min = dist_m / 80 if mode == "walk" else dist_m / 200
                path = []

            if time_min > max_travel_min:
                continue

            # 营业时间检查：必须按抵达时间判断，而不是离开上一站的时间。
            arr_str = (current_time + timedelta(minutes=time_min)).strftime("%H:%M")
            if not is_open_at(pid, arr_str, hours_map):
                continue

            # 时间预算检查
            stay = _stay_minutes(rt, constraints, variant=variant)
            if total_time + time_min + stay > budget_min * 1.05:
                continue

            # 评分
            gt = gt_data.get(pid, {})
            s = score_poi_v3(p, gt, constraints, route_types, network, type_index)
            # 语义搜索加分
            semantic_boost = 0.0
            if semantic_poi_ids and pid in semantic_poi_ids:
                semantic_boost = SEMANTIC_BOOST
                s += semantic_boost
            # 变体差异化加分
            cat = _get_category(rt)
            variant_bonus = VARIANT_BONUS.get(variant_name, {}).get(cat, 0)
            s += variant_bonus
            # 顺序约束加分：如果当前应该选sequence中的下一个类型，大幅加分
            sequence = constraints.get("sequence", [])
            sequence_boost = 0.0
            if sequence and len(route) < len(sequence):
                expected_type = sequence[len(route)]
                if _sequence_type_matches(rt, expected_type):
                    sequence_boost = 50.0  # 强制优先选择顺序中的下一个类型
                    s += sequence_boost
            # 距离惩罚（v3加强：超过15min的移动大幅扣分）
            distance_penalty = -((time_min / 15) * 0.8)
            s += distance_penalty
            if time_min > 30:
                distance_penalty -= 2.0  # 超过30分钟的移动额外惩罚
                s -= 2.0
            if time_min > 45:
                distance_penalty -= 3.0  # 超过45分钟的移动严重惩罚
                s -= 3.0

            if s > best_score:
                best_score = s
                best_poi = p
                best_dist = dist_m
                best_time = time_min
                best_path = path
                best_rank_context = {
                    "variant": variant_name,
                    "rank_score": round(s, 3),
                    "semantic_boost": semantic_boost,
                    "variant_bonus": variant_bonus,
                    "sequence_boost": sequence_boost,
                    "distance_penalty": distance_penalty,
                }

        if best_poi is None:
            break

        route.append(best_poi)
        best_poi["_route_rank_context"] = best_rank_context
        used.add(best_poi["poi_id"])
        current_poi = best_poi
        if type_index:
            rt = type_index.get(best_poi["poi_id"], "其他")
        else:
            from ugc_type_profiles import infer_real_type
            rt = infer_real_type(best_poi)
        route_types.add(rt)
        cat = _get_category(rt)
        category_counts[cat] = category_counts.get(cat, 0) + 1
        concrete_type_counts[rt] = concrete_type_counts.get(rt, 0) + 1
        if _is_shopping_type(rt):
            shopping_count += 1

        # 更新"已离开"的大类：如果当前大类和上一个不同，标记上一个为已离开
        if len(route) >= 2:
            prev_rt = type_index.get(route[-2]["poi_id"], "其他") if type_index else "其他"
            prev_cat = _get_category(prev_rt)
            if prev_cat != cat and prev_cat in CATEGORY_ONE_WAY:
                visited_categories.add(prev_cat)

        stay = _stay_minutes(rt, constraints, variant=variant)
        current_time += timedelta(minutes=best_time + stay)
        total_time += best_time + stay

    if len(route) < variant["min_pois"]:
        print(f"[RouteFail] Route has {len(route)} POIs, but min_pois={variant['min_pois']}. Returning empty.")
        for i, r in enumerate(route):
            rt = type_index.get(r["poi_id"], "其他") if type_index else "其他"
            print(f"  Route POI {i}: {r['name']} ({rt})")
        return []
    
    print(f"[RouteSuccess] Built route with {len(route)} POIs for variant={variant_name}")

    # 强制包含偏好类型：明确顺序优先，避免推导出的泛化偏好挤掉用户说出的 A -> B。
    sequence = constraints.get("sequence") or []
    if preferred_concrete_types or sequence:
        required_types = set(sequence) if sequence else set(user_concrete_prefs)
        if not required_types:
            has_any_preferred = any(
                (type_index.get(poi["poi_id"], "其他") if type_index else "其他") in preferred_concrete_types
                for poi in route
            )
            if not has_any_preferred:
                required_types = set(preferred_concrete_types)
        present_types = set()
        for poi in route:
            rt = type_index.get(poi["poi_id"], "其他") if type_index else "其他"
            if rt in required_types:
                present_types.add(rt)

        for missing_type in [rt for rt in required_types if rt not in present_types]:
            best_preferred = None
            best_preferred_score = -999
            best_context = None
            for p in candidates:
                pid = p["poi_id"]
                if pid in used:
                    continue
                rt = type_index.get(pid, "其他") if type_index else "其他"
                if _sequence_type_matches(rt, missing_type):
                    gt = gt_data.get(pid, {})
                    score, features, reasons, _ = _score_poi_features(p, gt, constraints, route_types, network, type_index)
                    if score > best_preferred_score:
                        best_preferred_score = score
                        best_preferred = p
                        best_context = (features, reasons)
            
            if best_preferred:
                # 替换路线中最后一个非关键POI（优先替换"其他"或低优先级类型）
                replace_idx = -1
                for i in range(len(route) - 1, -1, -1):
                    rt = type_index.get(route[i]["poi_id"], "其他") if type_index else "其他"
                    if not any(_sequence_type_matches(rt, required) for required in required_types) and _get_category(rt) not in ("餐饮", "景点"):
                        replace_idx = i
                        break
                if replace_idx < 0 and len(route) > 1:
                    for i in range(len(route) - 1, -1, -1):
                        rt = type_index.get(route[i]["poi_id"], "其他") if type_index else "其他"
                        if not any(_sequence_type_matches(rt, required) for required in required_types):
                            replace_idx = i
                            break
                
                if replace_idx >= 0:
                    used.remove(route[replace_idx]["poi_id"])
                    used.add(best_preferred["poi_id"])
                    best_preferred["_route_rank_context"] = {
                        "variant": variant_name,
                        "rank_score": round(best_preferred_score, 3),
                        "semantic_boost": SEMANTIC_BOOST if semantic_poi_ids and best_preferred["poi_id"] in semantic_poi_ids else 0.0,
                        "variant_bonus": 0.0,
                        "sequence_boost": 0.0,
                        "distance_penalty": 0.0,
                        "forced_preference_replacement": True,
                    }
                    if best_context:
                        best_preferred["_route_rank_context"]["forced_preference_features"] = best_context[0]
                        best_preferred["_route_rank_context"]["forced_preference_reasons"] = best_context[1]
                    route[replace_idx] = best_preferred
                    present_types.add(missing_type)
        if sequence:
            ordered = []
            used_ids = set()
            for expected in sequence:
                match = None
                for poi in route:
                    if poi["poi_id"] in used_ids:
                        continue
                    rt = type_index.get(poi["poi_id"], "其他") if type_index else "其他"
                    if _sequence_type_matches(rt, expected):
                        match = poi
                        break
                if match:
                    ordered.append(match)
                    used_ids.add(match["poi_id"])
            for poi in route:
                if poi["poi_id"] not in used_ids:
                    ordered.append(poi)
            route = ordered[:len(route)]

    return route


def format_route_v3(route, constraints, gt_data, hours_map, network, variant_name, type_index=None, knn_graph=None):
    """格式化路线为时间轴"""
    mode = constraints["mode"]
    start_time = datetime.strptime(constraints["start_time"], "%H:%M")
    current_time = start_time

    steps = []
    total_move = 0
    total_move_time = 0
    route_types_so_far = set()

    for i, poi in enumerate(route):
        if type_index:
            rt = type_index.get(poi["poi_id"], "其他")
        else:
            from ugc_type_profiles import infer_real_type
            rt = infer_real_type(poi)
        rt = _correct_candidate_type(poi, rt)
        stay = _stay_minutes(rt, constraints, variant_name=variant_name)
        dist_m = 0
        time_min = 0
        path = []
        coords = []

        if i == 0:
            from_lng = constraints.get("center_lng", DEFAULT_CENTER_LNG)
            from_lat = constraints.get("center_lat", DEFAULT_CENTER_LAT)
            dist_m, time_min, path, coords = _route_from_location_to_poi(network, from_lng, from_lat, poi, mode)
        else:
            prev = route[i - 1]
            if network:
                dist_m, time_min, path = network.get_route_between(prev["poi_id"], poi["poi_id"], mode)
            else:
                from math import radians, sin, cos, sqrt, atan2
                R = 6371000
                dlon = radians(poi["longitude"] - prev["longitude"])
                dlat = radians(poi["latitude"] - prev["latitude"])
                a = sin(dlat/2)**2 + cos(radians(prev["latitude"])) * cos(radians(poi["latitude"])) * sin(dlon/2)**2
                dist_m = 2 * R * atan2(sqrt(a), sqrt(1-a))
                time_min = dist_m / 80 if mode == "walk" else dist_m / 200
                path = []
            if dist_m is None:
                dist_m = 0
                time_min = 0
                path = []

        if i == 0:
            total_move += dist_m
            total_move_time += time_min
        elif i > 0:
            total_move += dist_m
            total_move_time += time_min

        arr_time = current_time + timedelta(minutes=time_min)
        dep_time = arr_time + timedelta(minutes=stay)
        gt = gt_data.get(poi["poi_id"], {})
        score, features, reasons, _ = _score_poi_features(poi, gt, constraints, route_types_so_far, network, type_index)
        rank_context = poi.get("_route_rank_context") or {}
        rank_score = rank_context.get("rank_score")
        if rank_score is not None:
            score = rank_score
            features["base_feature_score"] = _round_feature(features.get("quality_type_contribution", 0))
            features["route_rank_score"] = _round_feature(rank_score)
        if rank_context.get("forced_preference_replacement"):
            reasons.append("路线后处理阶段为满足明确偏好强制替换进入方案")
        open_at_arrival = is_open_at(poi["poi_id"], arr_time.strftime("%H:%M"), hours_map)
        category = _get_category(rt)
        recommendation_basis = _build_recommendation_basis(
            score,
            features,
            reasons,
            arrival_time=arr_time.strftime("%H:%M"),
            open_at_arrival=open_at_arrival,
            distance_m=dist_m,
            travel_time_min=time_min,
            variant_name=variant_name,
            semantic_boost=rank_context.get("semantic_boost", 0.0),
            sequence_boost=rank_context.get("sequence_boost", 0.0),
            distance_penalty=rank_context.get("distance_penalty", 0.0),
            variant_bonus=rank_context.get("variant_bonus", 0.0),
            start_selection_bonus=rank_context.get("start_selection_bonus", 0.0),
            start_fallback=rank_context.get("start_fallback", False),
        )

        step = {
            "order": i + 1,
            "poi_id": poi["poi_id"],
            "name": poi["name"],
            "type": rt,
            "category": category,
            "tags": poi.get("tags", []),
            "score": round(score, 2),
            "location": {"lng": poi["longitude"], "lat": poi["latitude"]},
            "arrival_time": arr_time.strftime("%H:%M"),
            "departure_time": dep_time.strftime("%H:%M"),
            "stay_minutes": stay,
            "ground_truth": gt,
            "business_hours": hours_map.get(poi["poi_id"], {}),
            "recommendation_basis": recommendation_basis,
            "review_summary": _build_review_summary(poi, rt, gt, recommendation_basis),
        }

        # 从起点到第一个 POI
        if i == 0:
            from_lng = constraints.get("center_lng", DEFAULT_CENTER_LNG)
            from_lat = constraints.get("center_lat", DEFAULT_CENTER_LAT)
            to_lng = poi["longitude"]
            to_lat = poi["latitude"]
            step["move_from_start"] = {
                "from_location": {"lng": from_lng, "lat": from_lat},
                "to_location": {"lng": to_lng, "lat": to_lat},
                "travel_mode": mode,
            }
            step["move_from_start"]["distance_m"] = round(dist_m, 1)
            step["move_from_start"]["time_min"] = round(time_min, 1)
            step["move_from_start"]["polyline"] = coords

        if i > 0:
            prev = route[i - 1]
            step["move_from_prev"] = {
                "distance_m": round(dist_m, 1),
                "time_min": round(time_min, 1),
                "travel_mode": mode,
                "path_nodes": len(path) if path else 0,
            }
            if network:
                if path:
                    step["move_from_prev"]["polyline"] = network.get_path_coords(path)
                else:
                    prev_node = network.nodes.get(prev["poi_id"])
                    cur_node = network.nodes.get(poi["poi_id"])
                    if prev_node and cur_node:
                        step["move_from_prev"]["polyline"] = [
                            [prev_node["lat"], prev_node["lng"]],
                            [cur_node["lat"], cur_node["lng"]],
                        ]
            if "polyline" not in step["move_from_prev"]:
                step["move_from_prev"]["polyline"] = [
                    [prev["latitude"], prev["longitude"]],
                    [poi["latitude"], poi["longitude"]],
                ]

        current_time = dep_time
        route_types_so_far.add(rt)

        steps.append(step)

    total_time = (current_time - start_time).total_seconds() / 60
    return {
        "variant_id": variant_name,
        "name": {"efficient": "紧凑高效", "relaxed": "休闲慢游", "food_first": "美食探店"}[variant_name],
        "description": VARIANTS[variant_name]["desc"],
        "poi_count": len(route),
        "total_time_minutes": round(total_time),
        "total_move_time": round(total_move_time, 1),
        "total_move_distance": round(total_move, 1),
        "time_utilization": round(total_time / (constraints["time_budget_hours"] * 60), 2),
        "start_location": {"lng": constraints.get("center_lng", DEFAULT_CENTER_LNG), "lat": constraints.get("center_lat", DEFAULT_CENTER_LAT)},
        "route": steps,
    }


def build_plan_v3(goal, pois, gt_data, center_lng=DEFAULT_CENTER_LNG, center_lat=DEFAULT_CENTER_LAT, radius=3000,
                  hours_path="poi_business_hours.json", network_path="chengdu_road_network.json",
                  spatial_index=None, type_index=None, use_knn=True, user_mode="tourist",
                  interaction_context=None):
    """主入口"""
    trace = {
        "raw_poi_count": len(pois),
        "effective_radius_m": None,
        "spatial_candidates": 0,
        "type_corrections": 0,
        "name_filter_removed": 0,
        "after_name_filter": 0,
        "type_filter_removed": 0,
        "after_type_filter": 0,
        "candidate_pool_before_cap": 0,
        "candidate_pool_after_cap": 0,
        "category_quota_counts": {},
        "auto_time_adjustment": None,
    }
    hours_path = _module_path(hours_path)
    network_path = _module_path(network_path)
    user_mode = normalize_user_mode(user_mode)
    mode_cfg = USER_MODES[user_mode]
    effective_radius = min(int(radius), mode_cfg["radius_m"])
    trace["effective_radius_m"] = effective_radius
    constraints = parse_goal(goal)
    constraints = apply_context_to_constraints(constraints, interaction_context)
    constraints["center_lng"] = center_lng
    constraints["center_lat"] = center_lat
    constraints["radius"] = effective_radius
    constraints["requested_radius"] = radius
    constraints["user_mode"] = user_mode
    constraints["user_mode_label"] = mode_cfg["label"]
    constraints["max_travel_min"] = mode_cfg["max_travel_min"]
    constraints["max_shopping"] = mode_cfg["max_shopping"]

    # 调用大模型判断用户意图复杂度
    intent_result = classify_intent_with_llm(goal)
    intent_type = intent_result["intent_type"]
    if constraints.get("intent_hint") in ("single_poi", "simple_route", "complex_route"):
        intent_type = constraints["intent_hint"]
        intent_result["intent_type"] = intent_type
        intent_result["reason"] = "interaction context intent hint"
    if len(constraints.get("sequence") or []) >= 2 and intent_type == "single_poi":
        intent_type = "simple_route"
        intent_result["intent_type"] = intent_type
        intent_result["reason"] = "interaction sequence requires route planning"
    constraints["intent_type"] = intent_type
    constraints["llm_used"] = intent_result.get("llm_used", False)
    constraints["intent_reason"] = intent_result.get("reason")
    constraints["intent_provider"] = intent_result.get("provider", "llm" if intent_result.get("llm_used") else "fallback")
    if "llm_error" in intent_result:
        constraints["llm_error"] = intent_result["llm_error"]

    # 根据意图类型决定推荐策略（变体数量、POI 数量）
    if intent_type == "single_poi":
        # 单点推荐：后续直接返回推荐列表，不构建路线变体
        variant_names = ["food_first"]  # 优先美食类变体
        route_limits = {"min_pois": 1, "max_pois": 2}
    elif intent_type == "simple_route":
        # 简单路线：只生成 1 个变体
        variant_names = ["relaxed"]
        # 如果用户明确提到了具体类型（如"火锅"和"茶馆"），限制POI数量为2
        # 避免硬凑无关POI（如用户说吃火锅和茶馆，路线中却混入游乐园）
        all_concrete_values = set()
        for types in TYPE_CATEGORIES.values():
            all_concrete_values.update(types)
        category_keys = set(TYPE_CATEGORIES.keys())
        pure_concrete_count = len([t for t in constraints["preferred_tags"] 
                                   if t in all_concrete_values and t not in category_keys])
        # 也检查用户是否提到了两个不同大类（如餐饮+休闲）
        user_categories = [t for t in constraints["preferred_tags"] if t in TYPE_CATEGORIES]
        if pure_concrete_count >= 2 or len(user_categories) >= 2:
            # 用户明确说了多个具体类型或大类，只生成2个POI（simple_route = 简单两点路线）
            route_limits = {"min_pois": 2, "max_pois": 2}
        else:
            route_limits = {"min_pois": 2, "max_pois": 3}
    else:
        # 完整路线规划：生成 3 个变体，3-6 个 POI
        variant_names = list(VARIANTS.keys())
        route_limits = {}

    hours_map = load_hours(hours_path)
    network = None
    knn_graph = None
    if intent_type != "single_poi":
        network = get_network(network_path)
        # 初始化 KNN 缓存图
        knn_graph = PoiKnnGraph(network, persist=PERSIST_KNN_CACHE) if (use_knn and network) else None

    # 预构建 poi_dict（O(1)查找）
    poi_dict = {p["poi_id"]: p for p in pois}

    # 自动调整起始时间：只检查用户明确提到的具体类型（而非整个大类）
    # 例如"想吃火锅"只检查火锅的营业率，不因甜品未开门而推迟
    user_concrete_types = set()
    for tag in constraints["preferred_tags"]:
        for types in TYPE_CATEGORIES.values():
            if tag in types:
                user_concrete_types.add(tag)
    
    if user_concrete_types:
        open_counts = {}
        total_counts = {}
        for p in pois:
            rt = type_index.get(p["poi_id"], "其他") if type_index else "其他"
            if rt in user_concrete_types:
                total_counts[rt] = total_counts.get(rt, 0) + 1
                start_str = constraints["start_time"]
                if is_open_at(p["poi_id"], start_str, hours_map):
                    open_counts[rt] = open_counts.get(rt, 0) + 1
        
        worst_rt = None
        worst_ratio = 1.0
        for rt in user_concrete_types:
            ratio = open_counts.get(rt, 0) / max(total_counts.get(rt, 1), 1)
            if total_counts.get(rt, 0) > 0 and ratio < worst_ratio:
                worst_ratio = ratio
                worst_rt = rt
        
        if worst_rt and worst_ratio < AUTO_TIME_THRESHOLD:
            open_times = []
            for p in pois:
                if type_index.get(p["poi_id"], "其他") == worst_rt:
                    hours = hours_map.get(p["poi_id"], {})
                    ot = hours.get("open_time")
                    if ot:
                        open_times.append(ot)
            if open_times:
                open_times.sort()
                suggested = open_times[max(0, int(len(open_times) * AUTO_TIME_PERCENTILE / 100))]
                h, m = int(suggested[:2]), int(suggested[3:])
                if m >= 30:
                    h += 1
                    m = 0
                elif m >= 5:
                    m = 30
                else:
                    m = 0
                suggested_rounded = f"{h:02d}:{m:02d}"
                old_start = constraints["start_time"]
                if suggested_rounded > old_start:
                    constraints["start_time"] = suggested_rounded
                    trace["auto_time_adjustment"] = {
                        "type": worst_rt,
                        "open_ratio": round(worst_ratio, 4),
                        "from": old_start,
                        "to": suggested_rounded,
                    }
                    print(f"[AutoTime] '{worst_rt}' 在 {old_start} 营业率仅 {worst_ratio:.1%}，自动调整起始时间为 {suggested_rounded}")

    # 只做一次候选筛选，3个变体复用
    candidates = _filter_candidates_spatial(poi_dict, spatial_index, center_lng, center_lat, effective_radius, network)
    trace["spatial_candidates"] = len(candidates)

    # 类型修正：基于 POI 名称修正 type_index 中的明显错误
    # （如"锦江之星"被标为"其他"、"包浆豆腐"被标为"服饰"）
    if type_index:
        from ugc_type_profiles import correct_type
        corrected_count = 0
        for p in candidates:
            pid = p["poi_id"]
            rt = type_index.get(pid, "其他")
            corrected = correct_type(p, rt)
            if corrected != rt:
                type_index[pid] = corrected
                corrected_count += 1
        trace["type_corrections"] = corrected_count
        if corrected_count > 0:
            print(f"[TypeFix] Corrected {corrected_count} POI types by name")
        entity_corrected_count = 0
        for p in candidates:
            pid = p["poi_id"]
            rt = type_index.get(pid, "其他")
            corrected = _correct_candidate_type(p, rt)
            if corrected != rt:
                type_index[pid] = corrected
                entity_corrected_count += 1
        trace["entity_type_corrections"] = entity_corrected_count
        if entity_corrected_count > 0:
            print(f"[EntityTypeFix] Corrected {entity_corrected_count} POI types by entity evidence")

    # 名称过滤：排除小区门、住宅、楼栋、商场内部设施、暂停/装修等低价值POI
    before_count = len(candidates)
    filtered = []
    for p in candidates:
        rt = type_index.get(p["poi_id"], "其他") if type_index else "其他"
        if _is_junk_candidate(p, rt):
            continue
        filtered.append(p)
    candidates = filtered
    trace["name_filter_removed"] = before_count - len(candidates)
    trace["after_name_filter"] = len(candidates)
    if before_count > len(candidates):
        print(f"[NameFilter] Excluded {before_count - len(candidates)} junk POIs")

    # 类型过滤
    before_type_filter = len(candidates)
    filtered = []
    for p in candidates:
        rt = type_index.get(p["poi_id"], "其他") if type_index else "其他"
        if rt == "购物" and _looks_like_real_mall(p.get("name", "")):
            rt = "商场"
        if rt in EXCLUDED_ROUTE_TYPES or _is_excluded_by_mode(rt, constraints):
            continue
        if intent_type != "single_poi" and _is_route_low_value(p, rt, constraints):
            continue
        filtered.append(p)
    candidates = filtered
    trace["type_filter_removed"] = before_type_filter - len(candidates)
    trace["after_type_filter"] = len(candidates)

    constraints["_hotpot_brand_stats"] = _build_hotpot_brand_stats(
        _load_reference_pois() or pois, candidates, gt_data, type_index, center_lng, center_lat
    )
    trace["hotpot_brand_roots"] = len(constraints["_hotpot_brand_stats"])

    # 限制数量：扩大候选池，并优先保留偏好类型，同时保证类型多样性
    trace["candidate_pool_before_cap"] = len(candidates)
    if len(candidates) > CANDIDATE_POOL_SIZE:
        scored = []
        for p in candidates:
            gt = gt_data.get(p["poi_id"], {})
            rt = type_index.get(p["poi_id"], "其他") if type_index else "其他"
            if _is_excluded_by_mode(rt, constraints):
                continue
            s, _, _, rt = _score_poi_features(p, gt, constraints, set(), network, type_index)
            # 真正的商场/公园在候选池截断时优先保留
            name = p.get("name", "")
            if rt == "商场" and _has_any_keyword(name, MALL_KEYWORDS):
                # 区分真正的商场（名称以商场名开头）vs 商场内品牌店（名称以品牌名开头）
                if name.startswith("茂业") or name.startswith("仁和") or name.startswith("王府井") or name.startswith("新世界") or name.startswith("百盛") or name.startswith("锦官城") or name.startswith("摩尔") or name.startswith("天府红") or name.startswith("红旗") or "购物中心" in name or "太古里" in name or "IFS" in name:
                    s += 5.0  # 真正的商场大幅优先
                else:
                    s += 1.0
            elif rt == "公园" and _looks_like_real_park(p):
                s += 3.0
            elif rt == "超市" and _looks_like_supermarket(p):
                s += 2.5
            scored.append((s, p))
        scored.sort(key=lambda x: -x[0])
        
        # 多样性保障：强制保留各类型的候选，避免单一类型垄断候选池
        # 否则"想吃火锅"时候选全是火锅，导致后续无法穿插其他类型
        final_candidates = []
        category_sel_counts = {}
        selected_ids = set()
        
        # 第一轮：按配额选取（优先高分）
        for s, p in scored:
            rt = type_index.get(p["poi_id"], "其他") if type_index else "其他"
            cat = _get_category(rt)
            quota = CATEGORY_QUOTA.get(cat, 20)
            if category_sel_counts.get(cat, 0) < quota and p["poi_id"] not in selected_ids:
                final_candidates.append(p)
                selected_ids.add(p["poi_id"])
                category_sel_counts[cat] = category_sel_counts.get(cat, 0) + 1
        
        # 第二轮：填充到候选池上限（从剩余高分候选中补充）
        for s, p in scored:
            if p["poi_id"] not in selected_ids and len(final_candidates) < CANDIDATE_POOL_SIZE:
                final_candidates.append(p)
                selected_ids.add(p["poi_id"])
        
        candidates = final_candidates
        trace["category_quota_counts"] = dict(category_sel_counts)
        print(f"[CandidatePool] Diversity quotas: {category_sel_counts}")
    trace["candidate_pool_after_cap"] = len(candidates)

    # 语义搜索增强：获取与用户查询语义相关的 Top-K POI
    semantic_poi_ids = set()
    if intent_type != "single_poi" and GLM_API_KEY:
        try:
            from semantic_search import SemanticIndex
            idx = SemanticIndex()
            candidate_ids = [p["poi_id"] for p in candidates]
            ranked = idx.rerank_candidates(goal, candidate_ids, top_k=SEMANTIC_TOP_K)
            semantic_poi_ids = {pid for pid, _ in ranked}
            print(f"[Semantic] Top semantic match: {len(semantic_poi_ids)} POIs")
        except Exception as e:
            print(f"[Semantic] Skip: {e}")
    elif intent_type != "single_poi":
        print("[Semantic] Skip: GLM_API_KEY not configured")

    # ========== single_poi: 直接返回同类 Top-N 推荐，不走路线构建 ==========
    if intent_type == "single_poi":
        # 筛选用户偏好类型的POI
        # 区分：
        #   - 纯具体类型（如"火锅"、"商场"、"公园"）：用户明确说了某个具体子类型
        #   - 大类键型"具体类型"（如"购物"、"景点"、"休闲"）：在TYPE_CATEGORIES值集中存在，
        #     但同时也是大类键；这类词本质上是聚合标签，用户说"购物"时应匹配整个购物大类
        #   - 大类键（如"餐饮"）：只在TYPE_CATEGORIES键中
        all_concrete_values = set()
        for types in TYPE_CATEGORIES.values():
            all_concrete_values.update(types)
        
        # 大类键本身不是"纯具体类型"（如"购物"不是某个POI的真实子类型，而是聚合标签）
        category_keys = set(TYPE_CATEGORIES.keys())
        
        # 纯具体类型：在大类值集中但不在大类键中（如"火锅"、"商场"、"公园"）
        pure_concrete = [t for t in constraints["preferred_tags"] if t in all_concrete_values and t not in category_keys]
        # 大类键型值（如"购物"）：用户说了这个词，应视为大类偏好
        category_as_value = [t for t in constraints["preferred_tags"] if t in all_concrete_values and t in category_keys]
        # 大类键（如"餐饮"）：用户直接说了大类
        user_categories = [t for t in constraints["preferred_tags"] if t in TYPE_CATEGORIES]
        
        target_types = set()
        if pure_concrete:
            # 用户明确说了纯具体类型（如"火锅"、"商场"），只匹配这些
            target_types.update(pure_concrete)
        elif category_as_value:
            # 用户说了"购物"、"景点"等聚合词，视为大类偏好，匹配整个大类
            for tag in category_as_value:
                target_types.update(TYPE_CATEGORIES[tag])
        elif user_categories:
            # 用户只说了大类（如"餐饮"），匹配整个大类
            for tag in user_categories:
                target_types.update(TYPE_CATEGORIES[tag])
        else:
            # fallback：匹配所有偏好标签
            for tag in constraints["preferred_tags"]:
                target_types.add(tag)
                if tag in TYPE_CATEGORIES:
                    target_types.update(TYPE_CATEGORIES[tag])
        
        # 特殊偏好映射："逛街"优先商场，"公园"优先真实公园
        preferred_concrete = set()
        for tag in constraints["preferred_tags"]:
            if tag == "购物":
                preferred_concrete.add("商场")
            elif tag == "公园":
                preferred_concrete.add("公园")
            elif tag in TYPE_CATEGORIES:
                preferred_concrete.update(TYPE_CATEGORIES[tag])
        
        # 单一明确类型（如"火锅"）可以多给同类；多类型偏好优先保证多样性。
        max_per_type = 5 if len(pure_concrete) == 1 else 2
        strict_exact_types = set(pure_concrete)
        single_poi_fallback = False
        if not strict_exact_types and ("购物" in category_as_value or "购物" in user_categories):
            strict_exact_types.add("商场")
            max_per_type = 5
        
        def _single_poi_matches(active_target_types, exact_types=None):
            matches = []
            exact_types = set(exact_types or [])
            for p in candidates:
                rt = type_index.get(p["poi_id"], "其他") if type_index else "其他"
                if rt == "购物" and _looks_like_real_mall(p.get("name", "")):
                    rt = "商场"
                rt = _correct_candidate_type(p, rt)
                cat = _get_category(rt)
                if _is_excluded_by_mode(rt, constraints):
                    continue
                if _is_junk_candidate(p, rt):
                    continue
                if exact_types and rt not in exact_types:
                    continue
                if not exact_types and intent_type == "single_poi" and _is_route_low_value(p, rt, constraints):
                    continue
                if _strict_single_type_match(rt, cat, active_target_types, exact_types):
                    gt = gt_data.get(p["poi_id"], {})
                    score, features, reasons, _ = _score_poi_features(p, gt, constraints, set(), None, type_index)
                    special_bonus = 0.0
                    # 用户明确提到的具体类型
                    if rt in constraints["preferred_tags"]:
                        special_bonus += 5.0
                    elif cat in constraints["preferred_tags"]:
                        special_bonus += 1.0
                    # 特殊偏好映射："逛街"优先真正的商场，"公园"优先真实公园
                    if rt in preferred_concrete:
                        name = p.get("name", "")
                        if rt == "商场":
                            has_mall_kw = any(kw in name for kw in ["百货", "购物中心", "商场", "奥特莱斯"])
                            if not has_mall_kw:
                                import re
                                has_mall_kw = re.search(r'(?i)\bmall\b', name) is not None
                            if has_mall_kw:
                                # 真正的商场获得最高优先级
                                special_bonus += 10.0
                        elif rt == "公园" and any(kw in name for kw in ["公园", "绿地", "湿地"]):
                            special_bonus += 6.0
                        elif rt == "火锅":
                            _, brand_bonus, _ = _hotpot_brand_signal(p, constraints)
                            entity_adjustment, _ = _hotpot_entity_adjustment(p)
                            if brand_bonus:
                                special_bonus += min(1.2, brand_bonus * 0.3)
                            if entity_adjustment > 0:
                                special_bonus += min(1.0, entity_adjustment * 0.3)
                        elif rt == "茶馆" and _looks_like_teahouse(p):
                            special_bonus += 5.0
                        elif rt == "饮品" and "咖啡" in constraints.get("raw_goal", "") and _looks_like_coffee_place(p):
                            special_bonus += 5.0
                        elif rt == "中餐" and _looks_like_restaurant_entity(p, rt):
                            special_bonus += 4.0
                        elif rt == "超市" and _looks_like_supermarket(p):
                            special_bonus += 4.0
                        else:
                            special_bonus += 2.0
                    score += special_bonus
                    matches.append((score, p, rt, cat, features, reasons, special_bonus))
            matches.sort(key=lambda x: -x[0])
            llm_reviews, llm_trace = _llm_review_candidates(goal, matches, constraints)
            trace["llm_candidate_review"] = llm_trace
            if llm_reviews:
                reviewed = []
                for score, p, rt, cat, features, reasons, special_bonus in matches:
                    review = llm_reviews.get(p["poi_id"])
                    if review:
                        bonus = review["bonus"]
                        score += bonus
                        features = dict(features)
                        reasons = list(reasons)
                        features["llm_candidate_review_bonus"] = _round_feature(bonus)
                        features["llm_candidate_review_reason"] = review.get("reason", "")
                        reasons.append(review.get("reason") or "大模型候选评审认为更符合当前需求")
                    reviewed.append((score, p, rt, cat, features, reasons, special_bonus))
                reviewed.sort(key=lambda x: -x[0])
                return reviewed
            return matches

        matches = _single_poi_matches(target_types, strict_exact_types)
        if not matches and strict_exact_types:
            fallback_types = set(target_types)
            for tag in pure_concrete:
                cat = _get_category(tag)
                if cat in TYPE_CATEGORIES:
                    fallback_types.update(TYPE_CATEGORIES[cat])
            for tag in category_as_value + user_categories:
                if tag in TYPE_CATEGORIES:
                    fallback_types.update(TYPE_CATEGORIES[tag])
            if fallback_types != target_types:
                print(f"[SinglePOI] Fallback target types: {sorted(fallback_types)}")
                target_types = fallback_types
                matches = _single_poi_matches(target_types)
                single_poi_fallback = True
        
        # 按类型配额选取，确保多样性
        recs = []
        seen_names = set()
        type_counts = {}
        user_concrete_set = set(strict_exact_types)

        def _append_recommendation(score, p, rt, cat, features=None, reasons=None, special_bonus=0.0):
            base_name = p["name"].split("(")[0].split("（")[0].strip()
            dedupe_key = base_name
            if rt == "火锅":
                brand_root = _hotpot_brand_root(p.get("name", ""))
                if brand_root and brand_root not in HOTPOT_GENERIC_BRAND_ROOTS:
                    dedupe_key = "火锅品牌:" + brand_root
            if dedupe_key in seen_names:
                return False
            seen_names.add(dedupe_key)
            type_counts[rt] = type_counts.get(rt, 0) + 1
            hours = hours_map.get(p["poi_id"], {})
            if features is None or reasons is None:
                score, features, reasons, _ = _score_poi_features(
                    p, gt_data.get(p["poi_id"], {}), constraints, set(), None, type_index
                )
            open_at_start = is_open_at(p["poi_id"], constraints.get("start_time", "09:00"), hours_map)
            gt = gt_data.get(p["poi_id"], {})
            recommendation_basis = _build_recommendation_basis(
                score,
                features,
                reasons,
                arrival_time=constraints.get("start_time"),
                open_at_arrival=open_at_start,
                special_bonus=special_bonus,
            )
            recs.append({
                "poi_id": p["poi_id"],
                "name": p["name"],
                "type": rt,
                "category": cat,
                "score": round(score, 2),
                "location": {"lng": p["longitude"], "lat": p["latitude"]},
                "business_hours": hours,
                "ground_truth": gt,
                "recommendation_basis": recommendation_basis,
                "review_summary": _build_review_summary(p, rt, gt, recommendation_basis),
            })
            if single_poi_fallback:
                recs[-1]["recommendation_basis"]["features"]["single_poi_fallback"] = True
                recs[-1]["recommendation_basis"]["top_reasons"].append("精确类型候选不足，已降级到同大类候选")
            return True

        # 第一轮：多个明确类型时，每类先保底一个。
        ordered_user_types = []
        for tag in constraints["preferred_tags"]:
            if tag in user_concrete_set and tag not in ordered_user_types:
                ordered_user_types.append(tag)
        if len(ordered_user_types) > 1:
            for target_rt in ordered_user_types:
                for score, p, rt, cat, features, reasons, special_bonus in matches:
                    if rt == target_rt and _append_recommendation(score, p, rt, cat, features, reasons, special_bonus):
                        break
                if len(recs) >= 5:
                    break

        # 单一明确类型仍优先补满同类推荐。
        for score, p, rt, cat, features, reasons, special_bonus in matches:
            if not user_concrete_set or len(recs) >= 5:
                break
            if rt not in user_concrete_set:
                continue
            if type_counts.get(rt, 0) >= max_per_type:
                continue
            _append_recommendation(score, p, rt, cat, features, reasons, special_bonus)
        
        # 第二轮：补充其他匹配类型，填充到5个
        for score, p, rt, cat, features, reasons, special_bonus in matches:
            if len(recs) >= 5:
                break
            if type_counts.get(rt, 0) >= max_per_type:
                continue
            _append_recommendation(score, p, rt, cat, features, reasons, special_bonus)
        
        print(f"[SinglePOI] Found {len(recs)} recommendations for {constraints['preferred_tags']}, types: {type_counts}")
        
        # 包装为兼容的 variant 格式
        variant = {
            "variant_id": "single_poi",
            "name": "精选推荐",
            "description": f"为您精选的{'/'.join(constraints['preferred_tags'][:2])}推荐",
            "poi_count": len(recs),
            "total_time_minutes": 0,
            "total_move_time": 0,
            "total_move_distance": 0,
            "time_utilization": 0,
            "start_location": {"lng": center_lng, "lat": center_lat},
            "route": [],
            "recommendations": recs,
        }
        
        return {
            "user_goal": goal,
            "constraints": _public_constraints(constraints),
            "center": {"lng": center_lng, "lat": center_lat, "radius_m": effective_radius},
            "model": _model_metadata(intent_result, constraints, trace, semantic_poi_ids),
            "variants": [variant],
        }

    variants = {}
    for vname in variant_names:
        route = build_route_v3(poi_dict, gt_data, constraints, hours_map, network, vname,
                               spatial_index=spatial_index, type_index=type_index,
                               candidates=candidates, knn_graph=knn_graph,
                               semantic_poi_ids=semantic_poi_ids,
                               route_limits=route_limits)
        if route:
            variants[vname] = format_route_v3(route, constraints, gt_data, hours_map, network, vname,
                                              type_index=type_index, knn_graph=knn_graph)

    if not variants and intent_type == "simple_route":
        fallback = _build_sequence_recommendation_variant(
            candidates, gt_data, constraints, hours_map, type_index, center_lng, center_lat
        )
        if fallback:
            variants["sequence_fallback"] = fallback

    # 保存 KNN 缓存（懒加载：本次计算的距离下次复用）
    if knn_graph:
        try:
            knn_graph.save()
        except OSError as e:
            print(f"[KNN] Cache save skipped: {e}")
        print("[KNN] " + knn_graph.stats())

    return {
        "user_goal": goal,
        "constraints": _public_constraints(constraints),
        "center": {"lng": center_lng, "lat": center_lat, "radius_m": effective_radius},
        "model": _model_metadata(intent_result, constraints, trace, semantic_poi_ids),
        "variants": list(variants.values()),
    }


def _build_sequence_recommendation_variant(candidates, gt_data, constraints, hours_map, type_index, center_lng, center_lat):
    sequence = constraints.get("sequence") or []
    if not sequence:
        return None
    recs = []
    used = set()
    for expected in sequence:
        scored = []
        expected_cat = _get_category(expected)
        for p in candidates:
            pid = p["poi_id"]
            if pid in used:
                continue
            rt = type_index.get(pid, "其他") if type_index else "其他"
            cat = _get_category(rt)
            if not _sequence_type_matches(rt, expected):
                continue
            if _is_excluded_by_mode(rt, constraints):
                continue
            if not is_open_at(pid, constraints.get("start_time", "09:00"), hours_map):
                continue
            gt = gt_data.get(pid, {})
            score, features, reasons, _ = _score_poi_features(p, gt, constraints, set(), None, type_index)
            sequence_boost = 5.0
            score += sequence_boost
            scored.append((score, p, rt, cat, features, reasons, sequence_boost))
        scored.sort(key=lambda x: -x[0])
        if scored:
            score, p, rt, cat, features, reasons, sequence_boost = scored[0]
            used.add(p["poi_id"])
            recommendation_basis = _build_recommendation_basis(
                score,
                features,
                reasons,
                arrival_time=constraints.get("start_time", "09:00"),
                open_at_arrival=True,
                sequence_boost=sequence_boost,
            )
            recs.append({
                "poi_id": p["poi_id"],
                "name": p["name"],
                "type": rt,
                "category": cat,
                "score": round(score, 2),
                "location": {"lng": p["longitude"], "lat": p["latitude"]},
                "business_hours": hours_map.get(p["poi_id"], {}),
                "ground_truth": gt_data.get(p["poi_id"], {}),
                "recommendation_basis": recommendation_basis,
                "review_summary": _build_review_summary(p, rt, gt_data.get(p["poi_id"], {}), recommendation_basis),
            })
    if not recs:
        return None
    route_steps = []
    mode = constraints.get("mode", "walk")
    current_time = datetime.strptime(constraints.get("start_time", "09:00"), "%H:%M")
    prev_lng, prev_lat = center_lng, center_lat
    total_move = 0.0
    total_move_time = 0.0
    for i, rec in enumerate(recs):
        loc = rec["location"]
        dist_m = _straight_distance_m(prev_lng, prev_lat, loc["lng"], loc["lat"])
        time_min = _travel_time_from_distance(dist_m, mode)
        stay = _stay_minutes(rec["type"], constraints, variant_name="relaxed")
        arr_time = current_time + timedelta(minutes=time_min)
        dep_time = arr_time + timedelta(minutes=stay)
        step = dict(rec)
        step.update({
            "order": i + 1,
            "arrival_time": arr_time.strftime("%H:%M"),
            "departure_time": dep_time.strftime("%H:%M"),
            "stay_minutes": stay,
        })
        move = {
            "distance_m": round(dist_m, 1),
            "time_min": round(time_min, 1),
            "travel_mode": mode,
            "polyline": [[prev_lat, prev_lng], [loc["lat"], loc["lng"]]],
        }
        if i == 0:
            step["move_from_start"] = {
                "from_location": {"lng": center_lng, "lat": center_lat},
                "to_location": {"lng": loc["lng"], "lat": loc["lat"]},
                **move,
            }
        else:
            step["move_from_prev"] = move
        route_steps.append(step)
        total_move += dist_m
        total_move_time += time_min
        current_time = dep_time
        prev_lng, prev_lat = loc["lng"], loc["lat"]
    total_time = (current_time - datetime.strptime(constraints.get("start_time", "09:00"), "%H:%M")).total_seconds() / 60
    return {
        "variant_id": "sequence_fallback",
        "name": "顺序候选路线",
        "description": "按您的访问顺序生成的可执行候选路线",
        "poi_count": len(recs),
        "total_time_minutes": round(total_time),
        "total_move_time": round(total_move_time, 1),
        "total_move_distance": round(total_move, 1),
        "time_utilization": round(total_time / max(constraints["time_budget_hours"] * 60, 1), 2),
        "start_location": {"lng": center_lng, "lat": center_lat},
        "route": route_steps,
        "recommendations": recs,
    }
