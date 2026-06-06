# RouteMind API 迁移指南

> 目标：将当前基于本地 POI 适配器的系统，平滑迁移到真实高德/美团/百度 API。

---

## 1. 架构替换策略

当前架构已预留替换点，迁移时**无需改动规划引擎** (`route_planner_v3.py`)：

```
┌─────────────────┐      ┌─────────────────────┐      ┌─────────────────┐
│   前端 (web/)   │ ──→  │   web_app.py        │ ──→  │  app_service.py │
└─────────────────┘      └─────────────────────┘      └─────────────────┘
                                                        │
                              替换点：只需修改这一层      ↓
                                                        │
                              ┌─────────────────┐   ┌─────────────────┐
                              │ LocalApiClient  │ → │ HttpApiClient   │
                              │ (本地 JSON)     │   │ (真实 HTTP API) │
                              └─────────────────┘   └─────────────────┘
```

### 替换步骤

1. **申请 API 密钥**
   - 高德开放平台：https://lbs.amap.com → 申请 Web 服务 Key
   - 美团开放平台（或自建聚合服务）

2. **配置环境变量**
   ```bash
   export AMAP_KEY=your_amap_key
   export MEITUAN_KEY=your_meituan_key
   ```

3. **实现 HttpApiClient**
   在 `mock_api/__init__.py` 中已有骨架类 `HttpApiClient`，补全各方法即可：
   - `search_pois()` → 高德 `/v3/place/around`
   - `get_poi_detail()` → 高德 `/v3/place/detail`
   - `get_walking_route()` → 高德 `/v3/direction/walking`
   - `get_comment_summary()` → 美团商家详情评分
   - `get_business_hours()` → 美团营业信息

4. **切换 Client**
   在 `data_repository.py` 的 `get_client()` 中：
   ```python
   from mock_api import HttpApiClient as ApiClient
   client = ApiClient(city=city_key, api_key=os.environ["AMAP_KEY"])
   ```

---

## 2. 数据字段映射表

### 2.1 POI 基础信息

| 本系统字段 | 类型 | 高德 API 字段 | 美团 API 字段 | 解析/转换说明 |
|-----------|------|-------------|-------------|-------------|
| `poi_id` | string | `id` | `wm_poi_id` | 主键映射 |
| `name` | string | `name` | `name` | 直接透传 |
| `type` | string | `type` | `category_name` | 高德为分号分隔的层级类型，需取最后一级 |
| `typecode` | string | `typecode` | - | 高德类型编码，用于类型推断 |
| `address` | string | `address` | `address` | 直接透传 |
| `location` | object `{lat, lng}` | `location` (string "lng,lat") | `lat` / `lng` (number) | 高德需 split 解析 |
| `tel` | string | `tel` | `phone` | 直接透传 |
| `cityname` | string | `cityname` | `city` | 直接透传 |
| `adname` | string | `adname` | `district` | 直接透传 |
| `tags` | string[] | `tag` (comma-separated) | `tags` | 需 split |
| `rating` | number | - | `wm_poi_score` | 美团评分映射 |

### 2.2 评分/评论

| 本系统字段 | 高德 | 美团 | 说明 |
|-----------|------|------|------|
| `ground_truth.overall` | - | `wm_poi_score` | 总评分 |
| `ground_truth.taste` | - | 需自建或从评论挖掘 | 口味评分 |
| `ground_truth.env` | - | 需自建或从评论挖掘 | 环境评分 |
| `ground_truth.service` | - | 需自建或从评论挖掘 | 服务评分 |
| `ground_truth.best_for` | - | 需 NLP 提取 | 最佳标签 |

> **迁移建议**：初期可先用美团总评分填充 `overall`，其余维度后续通过评论 NLP 补充。

### 2.3 营业时间

| 本系统字段 | 高德 | 美团 | 说明 |
|-----------|------|------|------|
| `business_hours.open_time` | - | `open_time` / `shipping_time` | 美团营业时间 |
| `business_hours.close_time` | - | `close_time` | 美团关店时间 |
| `business_hours.overnight` | - | 需推断 | 是否跨午夜 |

> **注意**：高德 API 不直接返回营业时间，需通过美团或百度获取。

### 2.4 路径规划（路网）

| 本系统字段 | 高德 | 说明 |
|-----------|------|------|
| `move_from_prev.polyline` | `paths[0].polyline` ( encoded ) | 高德返回加密 polyline，需用官方 SDK 解码 |
| `move_from_prev.distance_m` | `paths[0].distance` | 直接透传 |
| `move_from_prev.time_min` | `paths[0].duration` / 60 | 秒转分钟 |

> **迁移建议**：建议接入高德路径规划 SDK（支持步行/公交/驾车），比纯 REST API 更稳定。

---

## 3. 前端适配

前端已内置 API 适配层概念（`app.js` 中封装了所有 `fetch` 调用）。迁移时只需：

1. **切换 baseURL**（如有独立后端）
2. **添加请求签名/Token**（在 `fetch` 中统一添加 `Authorization` header）
3. **响应格式兼容**：当前后端同时支持 v1 (`ok` 字段) 和 v2 (`code` 字段)，前端自动识别

---

## 4. 性能基准与优化

| 场景 | 本地适配器 | 真实 API | 优化手段 |
|------|----------|----------|---------|
| POI 搜索 | ~50ms | 200-500ms | 本地缓存 24h |
| POI 详情（批量） | ~5ms | 50-100ms/个 | 并发批量请求 |
| 评分查询（批量） | ~1ms | 30-50ms/个 | Redis 缓存 1h |
| 路径规划 | ~10ms（KNN 缓存） | 150-300ms/次 | 结果缓存 + KNN 预加载 |
| 营业时间 | ~1ms | 30-50ms/个 | 本地缓存 24h |

### 推荐缓存策略

```python
# 伪代码：接入 Redis 缓存层
import redis
import hashlib

cache = redis.Redis(host='localhost', port=6379, db=0)

def cached_search_pois(center_lng, center_lat, radius):
    key = f"pois:{center_lng}:{center_lat}:{radius}"
    cached = cache.get(key)
    if cached:
        return json.loads(cached)
    result = api.search_pois(center_lng, center_lat, radius)
    cache.setex(key, 86400, json.dumps(result))  # TTL 24h
    return result
```

---

## 5. 城市扩展

当前预研数据仅覆盖**成都武侯+锦江两区**（47,045 POI）。全国推广时：

1. **数据准备**：通过高德 POI 下载服务批量获取各城市 POI
2. **路网构建**：使用 OSM (OpenStreetMap) 数据构建各城市道路网络
3. **评分补充**：与美团/点评合作获取评分数据，或通过爬虫合规获取
4. **营业时间**：与美团/百度合作获取，或通过众包方式补充

---

## 6. 合规与授权

| 数据源 | 授权方式 | 合规要求 |
|--------|---------|---------|
| 高德地图 | 企业 Key + 日配额 | 需显示高德 Logo，遵守使用条款 |
| 美团 | 开放平台合作 | 需签署数据使用协议 |
| OpenStreetMap | ODbL 开源协议 | 需标注数据来源 |

---

## 7. 迁移检查清单

- [ ] 已申请高德/美团 API Key
- [ ] 已实现 `HttpApiClient` 所有方法
- [ ] 已配置 Redis 缓存
- [ ] 已添加 API 请求限流（避免触发平台配额）
- [ ] 已测试各城市 POI 搜索返回字段完整性
- [ ] 已验证路径规划 polyline 解码正确
- [ ] 已确认评分字段映射无误
- [ ] 已添加错误降级（API 失败时回退到本地缓存）
- [ ] 已更新前端 baseURL
- [ ] 已通过压测验证性能达标
