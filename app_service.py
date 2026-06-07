"""
应用服务层 - 连接前端与 v3 规划引擎

职责：
1. 接收前端请求参数
2. 通过数据仓库/POI 适配器获取数据
3. 调用 route_planner_v3.build_plan_v3() 生成路线
4. 格式化返回前端
"""
import json
import uuid
import time

from data_repository import RepositoryError, repository
from interaction_intelligence import interaction_manager
from route_planner_v3 import build_plan_v3

SERVICE_AREA = {
    "city": "成都",
    "districts": ["武侯区", "锦江区"],
    "description": "当前数据覆盖成都武侯区、锦江区，暂不支持其他城市或区县。",
    "bounds": {
        "min_lng": 103.985,
        "max_lng": 104.145,
        "min_lat": 30.565,
        "max_lat": 30.705,
    },
}

# 城市坐标映射
CITY_CENTERS = {
    "chengdu": {"lng": 104.06476, "lat": 30.65705, "name": "天府广场"},
    "tianfu": {"lng": 104.06476, "lat": 30.65705, "name": "天府广场"},
    "chunxi":  {"lng": 104.08099, "lat": 30.65732, "name": "春熙路"},
    "taikooli": {"lng": 104.08126, "lat": 30.65335, "name": "太古里"},
    "ifs": {"lng": 104.0799, "lat": 30.6557, "name": "成都 IFS"},
    "jinli": {"lng": 104.0487, "lat": 30.6482, "name": "锦里"},
    "wuhouci": {"lng": 104.0473, "lat": 30.6469, "name": "武侯祠"},
    "jiuyanqiao": {"lng": 104.0832, "lat": 30.6412, "name": "九眼桥"},
    "languifang": {"lng": 104.0846, "lat": 30.6443, "name": "兰桂坊"},
    "wangjiang": {"lng": 104.0803, "lat": 30.6224, "name": "望江路"},
}

LOCAL_LANDMARKS = [
    ("武侯祠", "wuhouci"),
    ("锦里", "jinli"),
    ("太古里", "taikooli"),
    ("IFS", "ifs"),
    ("ifs", "ifs"),
    ("春熙路", "chunxi"),
    ("春熙", "chunxi"),
    ("天府广场", "tianfu"),
    ("九眼桥", "jiuyanqiao"),
    ("兰桂坊", "languifang"),
    ("望江楼", "wangjiang"),
    ("望江", "wangjiang"),
]

UNSUPPORTED_PLACE_TERMS = [
    "广州", "广州塔", "重庆", "解放碑", "洪崖洞", "北京", "上海", "深圳", "杭州", "西安",
    "南京", "武汉", "长沙", "昆明", "贵阳", "大理", "丽江", "峨眉", "乐山", "都江堰",
    "青羊区", "成华区", "金牛区", "高新区", "双流", "龙泉", "郫都", "温江", "新都",
]


def _detect_unsupported_area(goal, city):
    city_key = str(city or "chengdu").lower()
    if city_key not in ("chengdu", "tianfu", "chunxi", "taikooli", "ifs", "jinli", "wuhouci", "jiuyanqiao", "languifang", "wangjiang"):
        return city
    for term in UNSUPPORTED_PLACE_TERMS:
        if term in goal:
            return term
    return None


def _infer_center_key(goal, requested_city):
    city_key = str(requested_city or "chengdu")
    if city_key in CITY_CENTERS and city_key not in ("chengdu",):
        return city_key
    matched = []
    for keyword, center_key in LOCAL_LANDMARKS:
        idx = goal.find(keyword)
        if idx >= 0:
            matched.append((idx, -len(keyword), center_key))
    if matched:
        matched.sort()
        return matched[0][2]
    return "chengdu"


def _coerce_radius(value, default=3000):
    try:
        radius = int(value)
    except (ValueError, TypeError):
        return default
    if radius < 500 or radius > 20000:
        return default
    return radius


def _coerce_location(payload, center):
    try:
        lat = float(payload.get("center_lat", center["lat"]))
        lng = float(payload.get("center_lng", center["lng"]))
    except (ValueError, TypeError):
        return center["lat"], center["lng"]
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return center["lat"], center["lng"]
    return lat, lng


def _location_outside_service_area(lat, lng):
    bounds = SERVICE_AREA["bounds"]
    return (
        lng < bounds["min_lng"]
        or lng > bounds["max_lng"]
        or lat < bounds["min_lat"]
        or lat > bounds["max_lat"]
    )


def _normalize_payload(payload):
    if not isinstance(payload, dict):
        return None, {"ok": False, "error": "请求体必须是 JSON object", "error_code": "INVALID_PAYLOAD"}

    goal = str(payload.get("goal", "")).strip()
    if not goal:
        return None, {"ok": False, "error": "请告诉我想去哪儿或想做什么", "error_code": "EMPTY_GOAL"}
    if len(goal) > 500:
        return None, {"ok": False, "error": "目标描述过长，请控制在500字以内", "error_code": "GOAL_TOO_LONG"}

    city = str(payload.get("city", "chengdu") or "chengdu")
    unsupported_area = _detect_unsupported_area(goal, city)
    if unsupported_area:
        return None, {
            "ok": False,
            "error": "{}暂不在服务范围内。{}".format(unsupported_area, SERVICE_AREA["description"]),
            "error_code": "UNSUPPORTED_SERVICE_AREA",
            "service_area": SERVICE_AREA,
        }
    user_mode = str(payload.get("user_mode", "tourist") or "tourist")
    radius = _coerce_radius(payload.get("radius", 3000))

    center_key = _infer_center_key(goal, city)
    center = CITY_CENTERS.get(center_key, CITY_CENTERS["chengdu"])
    has_explicit_center = payload.get("center_lat") is not None or payload.get("center_lng") is not None
    center_lat, center_lng = _coerce_location(payload, center)
    if has_explicit_center and _location_outside_service_area(center_lat, center_lng):
        return None, {
            "ok": False,
            "error": "当前位置暂不在服务范围内。{}".format(SERVICE_AREA["description"]),
            "error_code": "UNSUPPORTED_SERVICE_AREA",
            "service_area": SERVICE_AREA,
        }

    normalized = {
        "goal": goal,
        "city": "chengdu",
        "requested_city": city,
        "user_mode": user_mode,
        "radius": radius,
        "center_lat": center_lat,
        "center_lng": center_lng,
        "center_name": center["name"] if not has_explicit_center else payload.get("center_name", center["name"]),
        "center_key": center_key,
        "service_area": SERVICE_AREA,
    }
    return normalized, None


def _pois_from_api_response(poi_resp):
    pois = []
    for p in poi_resp.get("pois", []):
        lng, lat = p["location"].split(",")
        pois.append({
            "poi_id": p["id"],
            "name": p["name"],
            "type": p["type"],
            "typecode": p["typecode"],
            "address": p["address"],
            "longitude": float(lng),
            "latitude": float(lat),
            "cityname": p["cityname"],
            "adname": p["adname"],
            "tags": p["tag"].split(",") if p["tag"] else [],
            "tel": p.get("tel", ""),
            "grid_density": p.get("grid_density", 0),
            "nearest_same_type_m": p.get("nearest_same_type_m", 0),
        })
    return pois


def _clarification_response(request_id, normalized, interaction_context, t0):
    result = {
        "user_goal": normalized["goal"],
        "constraints": {
            "raw_goal": normalized["goal"],
            "intent_type": "clarification",
            "time_budget_hours": None,
            "time_budget_source": "pending",
            "preferred_tags": [],
            "sequence": [],
            "interaction": {
                "session_id": interaction_context.get("session_id"),
                "user_id": interaction_context.get("user_id"),
                "effective_goal": interaction_context.get("effective_goal"),
                "memory_applied": interaction_context.get("memory_applied", []),
                "user_needs": interaction_context.get("user_needs") or {},
                "conflicts": interaction_context.get("conflicts", []),
                "clarification": interaction_context.get("clarification"),
                "needs_clarification": True,
                "clarification_options": interaction_context.get("clarification_options", []),
            },
        },
        "center": {
            "lng": normalized["center_lng"],
            "lat": normalized["center_lat"],
            "radius_m": normalized["radius"],
            "name": normalized.get("center_name"),
            "center_key": normalized.get("center_key"),
            "requested_city": normalized.get("requested_city"),
        },
        "service_area": SERVICE_AREA,
        "model": {
            "planner_version": "clarification_gate",
            "strategy": "interactive_intent_completion",
        },
        "variants": [],
    }
    elapsed = round((time.time() - t0) * 1000)
    return {
        "ok": True,
        "request_id": request_id,
        "result": result,
        "interaction": result["constraints"]["interaction"],
        "persistence": interaction_manager.memory.persistence_status(),
        "notice": interaction_context.get("clarification"),
        "clarification_options": interaction_context.get("clarification_options", []),
        "performance": {"load_ms": 0, "plan_ms": 0, "total_ms": elapsed},
    }


def run_agent(payload, request_id=None):
    """
    主入口：接收前端请求，返回路线规划结果

    Args:
        payload: {
            "goal": "春熙路附近，下午四点想吃火锅",
            "session_id": "default-session",  # 可选，会话记忆
            "user_id": "sample-user",         # 可选，长期轻画像
            "dialogue": [{"speaker_id": "小明", "text": "想吃火锅"}],  # 可选，多人对话
            "feedback": {"avoid_tags": ["KTV"]},  # 可选，写入长期轻画像
            "center_lat": 30.657,       # 可选，默认天府广场
            "center_lng": 104.082,      # 可选
            "radius": 3000,             # 可选，默认3000
            "user_mode": "tourist",     # 可选：tourist/business/resident
            "city": "chengdu"           # 可选
        }

    Returns:
        {
            "ok": True,
            "result": build_plan_v3 的输出,
            "performance": {"load_ms": 550, "plan_ms": 2400, "total_ms": 2950}
        }
    """
    request_id = request_id or uuid.uuid4().hex
    normalized, error = _normalize_payload(payload)
    if error:
        error["request_id"] = request_id
        return error

    goal = normalized["goal"]
    city = normalized["city"]
    user_mode = normalized["user_mode"]
    radius = normalized["radius"]

    t0 = time.time()

    try:
        repository.assert_ready()
        interaction_manager.apply_feedback(payload)
        interaction_context = interaction_manager.prepare(payload, normalized)
        if interaction_context.get("needs_clarification"):
            return _clarification_response(request_id, normalized, interaction_context, t0)
        effective_goal = interaction_context.get("effective_goal") or goal
        center_lat = normalized["center_lat"]
        center_lng = normalized["center_lng"]

        # 1. 获取 POI 数据。取数半径保留适度冗余，规划层仍会按用户目标和模式收紧有效半径；
        #    这样显式多目标路线不会因为上游召回过窄而找不到可行组合。
        retrieval_radius = radius
        if any(term in effective_goal for term in ("超市", "买菜", "采购")):
            retrieval_radius = max(retrieval_radius, 5000)
        elif any(term in effective_goal for term in ("逛街", "购物", "商场", "购物中心")):
            retrieval_radius = max(retrieval_radius, 3500)
        poi_resp = repository.search_pois(city, center_lng, center_lat, radius=retrieval_radius, page_size=10000)
        pois = _pois_from_api_response(poi_resp)

        if not pois:
            return {
                "ok": False,
                "request_id": request_id,
                "error": "在指定范围内未找到任何 POI，请尝试扩大搜索半径或更换位置",
                "error_code": "NO_POI",
            }

        # 2. 获取进程级缓存索引
        gt_index = repository.gt_index
        type_index = repository.type_index
        spatial_index = repository.spatial_index

        t_load = (time.time() - t0) * 1000

        # 3. 调用规划引擎
        t0 = time.time()
        result = build_plan_v3(
            goal=effective_goal,
            pois=pois,
            gt_data=gt_index,
            type_index=type_index,
            spatial_index=spatial_index,
            center_lng=center_lng,
            center_lat=center_lat,
            radius=radius,
            user_mode=user_mode,
            interaction_context=interaction_context,
        )
        result["service_area"] = SERVICE_AREA
        result["center"]["name"] = normalized.get("center_name")
        result["center"]["center_key"] = normalized.get("center_key")
        result["center"]["requested_city"] = normalized.get("requested_city")
        t_plan = (time.time() - t0) * 1000
        interaction_manager.record_result(normalized, result, interaction_context)

        # 如果规划结果为空，给出友好提示
        if not result.get("variants"):
            notice = interaction_context.get("clarification") or "未找到符合要求的路线，可能是当前时间该类型店铺尚未营业，或搜索范围太小。"
            return {
                "ok": True,
                "request_id": request_id,
                "result": result,
                "interaction": result.get("constraints", {}).get("interaction", {}),
                "persistence": interaction_manager.memory.persistence_status(),
                "performance": {"load_ms": round(t_load), "plan_ms": round(t_plan), "total_ms": round(t_load + t_plan)},
                "notice": notice,
                "clarification_options": interaction_context.get("clarification_options", []),
            }

        return {
            "ok": True,
            "request_id": request_id,
            "result": result,
            "interaction": result.get("constraints", {}).get("interaction", {}),
            "persistence": interaction_manager.memory.persistence_status(),
            "notice": interaction_context.get("clarification"),
            "clarification_options": interaction_context.get("clarification_options", []),
            "performance": {
                "load_ms": round(t_load),
                "plan_ms": round(t_plan),
                "total_ms": round(t_load + t_plan),
            }
        }
    except RepositoryError as e:
        return {"ok": False, "request_id": request_id, "error": str(e), "error_code": "DATA_NOT_READY"}
    except FileNotFoundError as e:
        return {"ok": False, "request_id": request_id, "error": f"数据文件缺失: {e}", "error_code": "DATA_FILE_MISSING"}
    except json.JSONDecodeError as e:
        return {"ok": False, "request_id": request_id, "error": f"数据文件损坏: {e}", "error_code": "DATA_FILE_INVALID"}
    except Exception as e:
        return {"ok": False, "request_id": request_id, "error": f"服务内部错误: {e}", "error_code": "INTERNAL_ERROR"}
