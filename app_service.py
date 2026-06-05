"""
应用服务层 - 连接前端与 v3 规划引擎

职责：
1. 接收前端请求参数
2. 通过 MockApiClient 获取数据
3. 调用 route_planner_v3.build_plan_v3() 生成路线
4. 格式化返回前端
"""
import json
import uuid
import time

from data_repository import RepositoryError, repository
from interaction_intelligence import interaction_manager
from route_planner_v3 import build_plan_v3

# 城市坐标映射
CITY_CENTERS = {
    "chengdu": {"lng": 104.047296, "lat": 30.674447, "name": "天府广场"},
    "chunxi":  {"lng": 104.082,    "lat": 30.657,    "name": "春熙路"},
}


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


def _normalize_payload(payload):
    if not isinstance(payload, dict):
        return None, {"ok": False, "error": "请求体必须是 JSON object", "error_code": "INVALID_PAYLOAD"}

    goal = str(payload.get("goal", "")).strip()
    if not goal:
        return None, {"ok": False, "error": "请告诉我想去哪儿或想做什么", "error_code": "EMPTY_GOAL"}
    if len(goal) > 500:
        return None, {"ok": False, "error": "目标描述过长，请控制在500字以内", "error_code": "GOAL_TOO_LONG"}

    city = str(payload.get("city", "chengdu") or "chengdu")
    user_mode = str(payload.get("user_mode", "tourist") or "tourist")
    radius = _coerce_radius(payload.get("radius", 3000))

    center = CITY_CENTERS.get(city, CITY_CENTERS["chengdu"])
    center_lat, center_lng = _coerce_location(payload, center)

    normalized = {
        "goal": goal,
        "city": city,
        "user_mode": user_mode,
        "radius": radius,
        "center_lat": center_lat,
        "center_lng": center_lng,
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


def run_agent(payload, request_id=None):
    """
    主入口：接收前端请求，返回路线规划结果

    Args:
        payload: {
            "goal": "春熙路附近，下午四点想吃火锅",
            "session_id": "demo-session",  # 可选，会话记忆
            "user_id": "demo-user",        # 可选，长期轻画像
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
        effective_goal = interaction_context.get("effective_goal") or goal
        center_lat = normalized["center_lat"]
        center_lng = normalized["center_lng"]

        # 1. 获取 POI 数据
        poi_resp = repository.search_pois(city, center_lng, center_lat, radius=radius, page_size=10000)
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
                "performance": {"load_ms": round(t_load), "plan_ms": round(t_plan), "total_ms": round(t_load + t_plan)},
                "notice": notice,
            }

        return {
            "ok": True,
            "request_id": request_id,
            "result": result,
            "interaction": result.get("constraints", {}).get("interaction", {}),
            "notice": interaction_context.get("clarification"),
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
