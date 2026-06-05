#!/usr/bin/env python3
"""
模拟API客户端层

================================================================================
设计目标
================================================================================
1. 接口格式 1:1 对标真实平台API（高德/美团/百度），未来替换时只换实现类
2. 当前底层读取本地预研数据，全国推广时切换为真实HTTP调用
3. 支持模拟延迟、配额限制、错误率等真实场景，便于压测和容错演练

================================================================================
真实API映射表
================================================================================
| 本系统方法                  | 对标真实API                                  | 平台     |
|---------------------------|--------------------------------------------|---------|
| search_pois()             | 高德POI周边搜索 /v3/place/around             | 高德     |
| get_poi_detail()          | 高德POI详情   /v3/place/detail               | 高德     |
| get_comments()            | 美团商家评论  /waimai/v1/poi/detail          | 美团     |
| get_comment_summary()     | 美团评分聚合  /waimai/v1/poi/detail          | 美团     |
| get_walking_route()       | 高德步行路径  /v3/direction/walking          | 高德     |
| get_driving_route()       | 高德驾车路径  /v3/direction/driving          | 高德     |
| get_business_hours()      | 美团营业信息  /waimai/v1/poi/detail          | 美团     |
| batch_get_ratings()       | 批量评分（需自建聚合服务或并发调用）           | 自建     |

================================================================================
使用方式
================================================================================

【当前预研阶段】
    from mock_api import MockApiClient
    api = MockApiClient(city="chengdu", district=["wuhou","jinjiang"])
    resp = api.search_pois(center_lng=104.082, center_lat=30.657, radius=3000)

【未来全国推广】
    方案A：直接替换类名（接口不变）
        from mock_api import HttpApiClient as ApiClient
        api = ApiClient(city="beijing", api_key="ak-xxx")

    方案B：通过配置文件切换（推荐）
        api = create_api_client(config)  # 根据环境变量自动选择Mock/Http

================================================================================
数据流向
================================================================================

    用户Query
        ↓
    意图解析(LLM)
        ↓
    API Client (本文件)
        ├── search_pois()     → 获取候选POI列表
        ├── get_poi_detail()  → 获取POI详细信息
        ├── get_comment_summary() → 获取评分/标签
        ├── get_walking_route()   → 获取路网距离
        └── get_business_hours()  → 获取营业时间
        ↓
    规划引擎 (route_planner_v3.py)
        ↓
    路线输出

================================================================================
性能基准
================================================================================
| 指标              | Mock模式（本地JSON） | Http模式（真实API） | 优化手段     |
|-------------------|-------------------|-------------------|------------|
| POI搜索           | ~0.5s             | ~200-500ms        | 本地缓存24h  |
| POI详情（批量）    | ~0.05s            | ~50-100ms/个      | 并发批量请求  |
| 评分查询（批量）   | ~0.01s            | ~30-50ms/个       | Redis缓存    |
| 路径规划           | ~0.01s（KNN缓存）  | ~150-300ms/次     | KNN懒加载缓存 |
| 营业时间           | ~0.01s            | ~30-50ms/个       | 本地缓存24h  |

================================================================================
"""
import json
import os
import time

# 数据根目录（当前指向项目根目录，未来可配置为远程API base_url）
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output")
SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


class MockApiClient:
    """
    模拟平台API客户端（高德POI + 美团评论 + 高德路径规划）

    全国推广时的替换策略：
    1. 保留本类的接口签名不变
    2. 新建 HttpApiClient 类实现同样的方法，内部走 requests HTTP 调用
    3. 通过工厂函数或配置切换实现类
    """

    def __init__(self, city="chengdu", district=None, simulate_latency_ms=0, simulate_quota=True):
        """
        Args:
            city: 城市编码，如 "chengdu", "beijing"
            district: 行政区列表，如 ["wuhou", "jinjiang"]
            simulate_latency_ms: 模拟API延迟（毫秒），0表示无延迟
            simulate_quota: 是否模拟日配额限制
        """
        self.city = city
        self.district = district or []
        self.simulate_latency_ms = simulate_latency_ms
        self.simulate_quota = simulate_quota
        self._quota_counter = 0
        self._quota_limit = 10000  # 模拟日配额1万次

        # 预加载索引数据（实际生产环境这些数据会走缓存/Redis）
        self._pois = None
        self._pois_by_id = {}  # poi_id -> poi 字典索引，避免O(n)查找
        self._gt_index = None
        self._type_index = None
        self._spatial_index = None
        self._hours = None
        self._network = None

    def _delay(self):
        """模拟网络延迟"""
        if self.simulate_latency_ms > 0:
            time.sleep(self.simulate_latency_ms / 1000.0)

    def _check_quota(self):
        """模拟API配额检查"""
        if self.simulate_quota:
            self._quota_counter += 1
            if self._quota_counter > self._quota_limit:
                raise MockApiQuotaError("Daily quota exceeded (limit: {})".format(self._quota_limit))

    # ==================== 数据加载（内部方法） ====================

    def _load_pois(self):
        """模拟高德POI数据加载。返回POI列表，同时构建poi_id索引。"""
        if self._pois is None:
            path = os.path.join(SRC_DIR, "wuhou_jinjiang_pois.json")
            self._pois = _load_json(path)
            self._pois_by_id = {p["poi_id"]: p for p in self._pois}
        return self._pois

    def _load_gt_index(self):
        """模拟平台评分数据加载"""
        if self._gt_index is None:
            path = os.path.join(DATA_DIR, "gt_index.json")
            self._gt_index = _load_json(path)
        return self._gt_index

    def _load_type_index(self):
        """模拟平台类型数据加载"""
        if self._type_index is None:
            path = os.path.join(DATA_DIR, "type_index.json")
            self._type_index = _load_json(path)
        return self._type_index

    def _load_spatial_index(self):
        """模拟平台空间索引加载"""
        if self._spatial_index is None:
            path = os.path.join(DATA_DIR, "spatial_index.json")
            self._spatial_index = _load_json(path)
        return self._spatial_index

    def _load_business_hours(self):
        """模拟平台营业时间数据加载"""
        if self._hours is None:
            path = os.path.join(SRC_DIR, "poi_business_hours.json")
            self._hours = _load_json(path)
        return self._hours

    # ==================== POI Search API ====================

    def search_pois(self, center_lng, center_lat, radius=3000,
                    keywords=None, types=None, page=1, page_size=20):
        """
        模拟高德POI周边搜索API

        真实API:
            GET https://restapi.amap.com/v3/place/around
            Params: key, location, radius, keywords, types, page, offset

        Returns:
            {
                "status": "1",
                "info": "OK",
                "count": "166",
                "page": "1",
                "page_size": "20",
                "pois": [
                    {
                        "id": "B0FFGCTJKR",
                        "name": "健道健身",
                        "type": "运动健身;健身中心",
                        "typecode": "080111",
                        "address": "会展路198号",
                        "location": "104.078289,30.557503",
                        "tel": "028-83227393",
                        "cityname": "成都市",
                        "adname": "武侯区",
                        "distance": "1200",
                        "rating": "4.2",
                        "tag": "KTV,休闲"
                    }
                ]
            }
        """
        self._check_quota()
        self._delay()

        pois = self._load_pois()
        gt_index = self._load_gt_index()
        type_index = self._load_type_index()

        from math import radians, sin, cos, sqrt, atan2
        R = 6371000

        results = []
        for p in pois:
            dlon = radians(p["longitude"] - center_lng)
            dlat = radians(p["latitude"] - center_lat)
            a = sin(dlat/2)**2 + cos(radians(center_lat)) * cos(radians(p["latitude"])) * sin(dlon/2)**2
            dist = 2 * R * atan2(sqrt(a), sqrt(1-a))
            if dist > radius:
                continue

            # 关键词过滤（名称或tag包含关键词）
            if keywords:
                kw_list = keywords.split()
                name_match = any(k in p.get("name", "") for k in kw_list)
                tag_match = any(k in str(p.get("tags", [])) for k in kw_list)
                if not name_match and not tag_match:
                    continue

            # 类型过滤
            if types:
                rt = type_index.get(p["poi_id"], "其他")
                if rt not in types:
                    continue

            gt = gt_index.get(p["poi_id"], {})
            results.append({
                "id": p["poi_id"],
                "name": p["name"],
                "type": p.get("type", ""),
                "typecode": p.get("typecode", ""),
                "address": p.get("address", ""),
                "location": "{},{}".format(p["longitude"], p["latitude"]),
                "tel": p.get("tel", ""),
                "cityname": p.get("cityname", "成都市"),
                "adname": p.get("adname", ""),
                "distance": str(int(dist)),
                "rating": str(gt.get("overall", 3.0)),
                "tag": ",".join(p.get("tags", [])),
                "grid_density": p.get("grid_density", 0),
                "nearest_same_type_m": p.get("nearest_same_type_m", 0),
            })

        # 分页
        total = len(results)
        start = (page - 1) * page_size
        end = start + page_size
        page_data = results[start:end]

        return {
            "status": "1",
            "info": "OK",
            "count": str(total),
            "page": str(page),
            "page_size": str(page_size),
            "pois": page_data,
        }

    def get_poi_detail(self, poi_id):
        """
        模拟高德POI详情API

        真实API:
            GET https://restapi.amap.com/v3/place/detail
            Params: key, id

        Returns:
            {
                "status": "1",
                "info": "OK",
                "poi": {
                    "id": "B0FFGCTJKR",
                    "name": "健道健身",
                    "type": "运动健身;健身中心",
                    "typecode": "080111",
                    ...
                }
            }
        """
        self._check_quota()
        self._delay()

        self._load_pois()
        gt_index = self._load_gt_index()
        type_index = self._load_type_index()

        p = self._pois_by_id.get(poi_id)
        if p:
            gt = gt_index.get(poi_id, {})
            return {
                "status": "1",
                "info": "OK",
                "poi": {
                    "id": p["poi_id"],
                    "name": p["name"],
                    "type": p.get("type", ""),
                    "typecode": p.get("typecode", ""),
                    "address": p.get("address", ""),
                    "location": "{},{}".format(p["longitude"], p["latitude"]),
                    "tel": p.get("tel", ""),
                    "cityname": p.get("cityname", ""),
                    "adname": p.get("adname", ""),
                    "rating": gt.get("overall", 3.0),
                    "inferred_type": type_index.get(poi_id, "其他"),
                    "tags": p.get("tags", []),
                }
            }
        return {"status": "0", "info": "POI_NOT_FOUND"}

    # ==================== 评论/评分 API ====================

    def get_comments(self, poi_id, page=1, page_size=10):
        """
        模拟美团/点评商家评论API

        真实API:
            GET https://waimai.meituan.com/.../poi/detail
            Params: wm_poi_id

        Returns:
            {
                "status": 0,
                "data": {
                    "total": 164,
                    "page": 1,
                    "page_size": 10,
                    "comments": [
                        {
                            "user_name": "匿名用户",
                            "comment_score": 5.0,
                            "comment": "锅底香得遭不住...",
                            "comment_time": "2024-03-15 18:30",
                            "pics": []
                        }
                    ]
                }
            }
        """
        self._check_quota()
        self._delay()

        # 当前预研阶段：从UGC大文件中按需读取
        ugc_path = os.path.join(SRC_DIR, "ugc_groundtruth_v4_xl.json")
        if not os.path.exists(ugc_path):
            return {
                "status": 0,
                "data": {"total": 0, "page": page, "page_size": page_size, "comments": []}
            }

        comments = []
        with open(ugc_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            poi_comments = data.get("comments", {}).get(poi_id, [])
            total = len(poi_comments)
            start = (page - 1) * page_size
            end = start + page_size
            for c in poi_comments[start:end]:
                comments.append({
                    "user_name": c.get("user", "匿名用户"),
                    "comment_score": c.get("s", 5),
                    "comment": c.get("t", ""),
                    "comment_time": c.get("time", ""),
                    "pics": c.get("pics", []),
                })

        return {
            "status": 0,
            "data": {
                "total": total,
                "page": page,
                "page_size": page_size,
                "comments": comments,
            }
        }

    def get_comment_summary(self, poi_id):
        """
        模拟美团/点评评论摘要API（聚合评分和标签）

        真实场景：平台侧已聚合好的评分维度，不需要逐条拉评论再计算。

        Returns:
            {
                "status": 0,
                "data": {
                    "overall": 4.5,
                    "taste": 4.6,
                    "env": 4.2,
                    "service": 4.3,
                    "value": 4.0,
                    "tag_list": ["口味好", "服务热情", "环境不错"]
                }
            }
        """
        self._check_quota()
        self._delay()

        gt_index = self._load_gt_index()
        gt = gt_index.get(poi_id, {})
        return {
            "status": 0,
            "data": {
                "overall": gt.get("overall", 3.0),
                "taste": gt.get("taste", 3.0),
                "env": gt.get("env", 3.0),
                "service": gt.get("service", 3.0),
                "value": gt.get("value", 3.0),
                "tag_list": gt.get("best_for", []),
            }
        }

    # ==================== 路径规划 API ====================

    def get_walking_route(self, origin_lng, origin_lat, destination_lng, destination_lat):
        """
        模拟高德步行路径规划API

        真实API:
            GET https://restapi.amap.com/v3/direction/walking
            Params: origin, destination, key

        Returns:
            {
                "status": "1",
                "info": "OK",
                "route": {
                    "origin": "104.082,30.657",
                    "destination": "104.070,30.660",
                    "paths": [
                        {
                            "distance": "2345",
                            "duration": "1800",
                            "steps": [...]
                        }
                    ]
                }
            }
        """
        self._check_quota()
        self._delay()

        from road_network import get_network
        network = get_network(os.path.join(SRC_DIR, "chengdu_road_network.json"))

        origin_poi = self._find_nearest_poi(origin_lng, origin_lat)
        dest_poi = self._find_nearest_poi(destination_lng, destination_lat)

        if origin_poi and dest_poi:
            dist_m, time_min, path = network.get_route_between(
                origin_poi["poi_id"], dest_poi["poi_id"], "walk")
        else:
            from math import radians, sin, cos, sqrt, atan2
            R = 6371000
            dlon = radians(destination_lng - origin_lng)
            dlat = radians(destination_lat - origin_lat)
            a = sin(dlat/2)**2 + cos(radians(origin_lat)) * cos(radians(destination_lat)) * sin(dlon/2)**2
            dist_m = 2 * R * atan2(sqrt(a), sqrt(1-a))
            time_min = dist_m / 80
            path = []

        if dist_m is None:
            return {"status": "0", "info": "ROUTE_NOT_FOUND"}

        return {
            "status": "1",
            "info": "OK",
            "route": {
                "origin": "{},{}".format(origin_lng, origin_lat),
                "destination": "{},{}".format(destination_lng, destination_lat),
                "paths": [{
                    "distance": str(int(dist_m)),
                    "duration": str(int(time_min * 60)),
                    "steps": [{"instruction": "step_{}".format(i), "road": ""} for i in range(len(path))],
                }]
            }
        }

    def _find_nearest_poi(self, lng, lat):
        """找到最近的POI作为路网节点（模拟高德API的坐标吸附到道路）"""
        self._load_pois()
        best = None
        best_dist = float("inf")
        from math import radians, sin, cos, sqrt, atan2
        R = 6371000
        for p in self._pois:
            dlon = radians(p["longitude"] - lng)
            dlat = radians(p["latitude"] - lat)
            a = sin(dlat/2)**2 + cos(radians(lat)) * cos(radians(p["latitude"])) * sin(dlon/2)**2
            dist = 2 * R * atan2(sqrt(a), sqrt(1-a))
            if dist < best_dist:
                best_dist = dist
                best = p
        return best

    # ==================== 营业时间 API ====================

    def get_business_hours(self, poi_id):
        """
        模拟平台营业时间API

        真实场景：美团/大众点评商家详情页中的营业时间字段。

        Returns:
            {
                "status": 0,
                "data": {
                    "poi_id": "xxx",
                    "open_time": "10:30",
                    "close_time": "02:00",
                    "overnight": true,
                    "peak_hours": "18:00-21:00",
                    "rest_days": ["无"]
                }
            }
        """
        self._check_quota()
        self._delay()

        hours_map = self._load_business_hours()
        h = hours_map.get(poi_id, {})
        return {
            "status": 0,
            "data": {
                "poi_id": poi_id,
                "open_time": h.get("open", "09:00"),
                "close_time": h.get("close", "22:00"),
                "overnight": h.get("overnight", False),
                "peak_hours": h.get("peak", ""),
                "rest_days": [h.get("rest_day", "无")],
            }
        }

    # ==================== 批量查询接口（高性能场景） ====================

    def batch_get_poi_details(self, poi_ids):
        """
        批量获取POI详情，减少API调用次数

        真实场景：自建聚合服务并发调用，或利用平台的批量接口（如有）。
        """
        results = {}
        for pid in poi_ids:
            results[pid] = self.get_poi_detail(pid).get("poi")
        return {"status": "1", "data": results}

    def batch_get_ratings(self, poi_ids):
        """
        批量获取评分摘要

        真实场景：自建聚合服务并发调用，减少RTT。
        """
        results = {}
        for pid in poi_ids:
            results[pid] = self.get_comment_summary(pid).get("data")
        return {"status": "1", "data": results}


class MockApiQuotaError(Exception):
    """模拟API配额超限异常"""
    pass


class MockApiNetworkError(Exception):
    """模拟API网络异常"""
    pass


# ================================================================================
# 未来HttpApiClient骨架（接入真实高德/美团API时参考）
# ================================================================================

class HttpApiClient:
    """
    真实平台API客户端骨架（未实现，供未来参考）

    接入时只需实现与 MockApiClient 同样的接口，规划引擎无需改动。
    """

    def __init__(self, city, api_key, base_url="https://restapi.amap.com/v3"):
        self.city = city
        self.api_key = api_key
        self.base_url = base_url
        self._session = None  # requests.Session

    def search_pois(self, center_lng, center_lat, radius=3000,
                    keywords=None, types=None, page=1, page_size=20):
        """
        TODO: 接入高德POI周边搜索API
        GET /place/around?key={api_key}&location={lng},{lat}&radius={radius}&keywords={keywords}
        """
        raise NotImplementedError("待接入高德POI Search API")

    def get_poi_detail(self, poi_id):
        """TODO: 接入高德POI详情API"""
        raise NotImplementedError("待接入高德POI Detail API")

    def get_comments(self, poi_id, page=1, page_size=10):
        """TODO: 接入美团/点评评论API"""
        raise NotImplementedError("待接入美团评论API")

    def get_comment_summary(self, poi_id):
        """TODO: 接入美团评分聚合API"""
        raise NotImplementedError("待接入美团评分API")

    def get_walking_route(self, origin_lng, origin_lat, destination_lng, destination_lat):
        """TODO: 接入高德步行路径规划API"""
        raise NotImplementedError("待接入高德路径规划API")

    def get_business_hours(self, poi_id):
        """TODO: 接入美团营业信息API"""
        raise NotImplementedError("待接入美团营业API")

    def batch_get_poi_details(self, poi_ids):
        """TODO: 并发批量调用"""
        raise NotImplementedError("待实现并发批量接口")

    def batch_get_ratings(self, poi_ids):
        """TODO: 并发批量调用"""
        raise NotImplementedError("待实现并发批量接口")
