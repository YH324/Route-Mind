# 智能路线规划系统 —— 产品文档 v3.1

## 1. 产品概述

基于语义理解 + 路网距离 + 营业时间的智能 POI 路线规划引擎。用户用自然语言描述需求（如"想吃火锅"、"成都半日游"），系统自动生成贴合街道的真实路线。

### 核心差异化
- **语义理解**：GLM embedding-2 本地向量检索，理解"想吃辣的"="火锅/烧烤"
- **路网真实路径**：Dijkstra 最短路径，路线折线贴合街道（非直线）
- **营业时间过滤**：自动排除已打烊的 POI，根据偏好类型自动调整起始时间
- **LLM 意图分类**：调用大模型判断用户是"单点推荐"还是"路线规划"，避免过度推荐
- **类型多样性约束**：餐饮≤2、景点≤2、同类型不重复，避免"火锅→茶馆→火锅"

## 2. 技术架构

```
前端 (web/)
  └── index.html + app.js + styles.css
        ↓ POST /api/plan
web_app.py (ThreadingHTTPServer)
  └── app_service.py
        └── route_planner_v3.py (核心引擎)
              ├── semantic_search.py (语义检索)
              ├── road_network.py (Dijkstra 路网)
              ├── poi_knn_graph.py (距离缓存)
              └── ugc_type_profiles.py (类型推断 + 修正)
```

### 数据层
| 文件 | 大小 | 说明 |
|------|------|------|
| `wuhou_jinjiang_pois.json` | 21MB | 47,045 POI 基础信息 |
| `output/gt_index.json` | 2MB | POI 评分/评论聚合索引 |
| `output/type_index.json` | 1MB | POI 类型映射 |
| `output/spatial_index.json` | 4.4MB | 空间网格索引 |
| `output/poi_embeddings.npy` | 184MB | 47,045×1024 语义向量 |
| `output/poi_embedding_ids.json` | 0.6MB | 向量到 POI ID 映射 |
| `chengdu_road_network.json` | 61MB | 291,460 条路网边 |
| `poi_business_hours.json` | 10MB | 营业时间数据 |

## 3. API 接口

### POST /api/plan —— 路线规划

**请求体：**
```json
{
  "goal": "想吃火锅",
  "center_lat": 30.674447,
  "center_lng": 104.047296,
  "radius": 3000,
  "city": "chengdu"
}
```

**响应体：**
```json
{
  "ok": true,
  "result": {
    "user_goal": "想吃火锅",
    "constraints": {
      "preferred_tags": ["餐饮", "火锅"],
      "start_time": "11:00",
      "intent_type": "single_poi"
    },
    "variants": [
      {
        "variant_id": "food_first",
        "name": "美食探店",
        "poi_count": 2,
        "route": [
          {
            "order": 1,
            "name": "宽板凳火锅鱼(大石东路店)",
            "type": "火锅",
            "arrival_time": "11:00",
            "departure_time": "11:45",
            "stay_minutes": 45,
            "move_from_start": {
              "distance_m": 2570.2,
              "time_min": 32.1,
              "polyline": [[30.674, 104.047], ...]
            }
          }
        ]
      }
    ]
  },
  "performance": {
    "load_ms": 120,
    "plan_ms": 850,
    "total_ms": 970
  }
}
```

### GET /api/health —— 健康检查

**响应：**
```json
{
  "ok": true,
  "version": "3.1.0",
  "features": ["semantic_search", "road_network", "llm_intent", "business_hours", "type_diversity"]
}
```

## 4. 配置说明

所有配置通过 `config.py` 管理，支持环境变量覆盖（前缀 `HACKATHON_`）。

### 环境变量示例（.env）
```bash
# GLM API Key（用于意图分类和 embedding）
HACKATHON_GLM_API_KEY=your_key_here

# 服务端口
HACKATHON_PORT=8000

# 规划引擎参数
HACKATHON_CANDIDATE_POOL_SIZE=300
HACKATHON_LIMIT_FOOD=2
HACKATHON_LIMIT_SIGHT=2
HACKATHON_LIMIT_SHOPPING=1
HACKATHON_LIMIT_LEISURE=2
HACKATHON_SEMANTIC_TOP_K=80
HACKATHON_SEMANTIC_BOOST=2.5
```

### 关键配置项
| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `CANDIDATE_POOL_SIZE` | 300 | 候选池大小 |
| `CATEGORY_QUOTA` | 景点50/休闲40/购物25/餐饮80/其他20 | 候选池类型配额 |
| `CATEGORY_LIMITS` | 餐饮2/景点2/购物1/休闲2 | 路线中各大类上限 |
| `CONCRETE_TYPE_LIMIT` | 1 | 同一具体类型上限 |
| `AUTO_TIME_PERCENTILE` | 60 | 自动调整起始时间的百分位 |
| `AUTO_TIME_THRESHOLD` | 0.05 | 营业率低于此值时触发时间调整 |

## 5. 意图分类与推荐策略

系统调用 GLM-4-flash 对用户输入做意图分类，动态调整推荐策略：

| 意图类型 | 触发条件 | 变体数 | POI 数 | 示例 |
|---------|---------|--------|--------|------|
| `single_poi` | 只想去一个地方 | 1 | 1-2 | "想吃火锅" |
| `simple_route` | 想去 2-3 个地方 | 1 | 2-3 | "吃完火锅去茶馆" |
| `complex_route` | 规划完整路线 | 3 | 3-6 | "成都半日游" |

## 6. 部署指南

### 环境要求
- Python 3.7+
- 依赖：`numpy`, `urllib3`

### 启动服务
```bash
python web_app.py
```
服务默认监听 `http://127.0.0.1:8000`。

### 前端访问
浏览器打开 `http://127.0.0.1:8000/`，输入自然语言需求即可获取路线。

## 7. 已知问题与限制

### 数据质量
- `type_index.json` 中存在少量类型标注错误（如"锦江之星"标为"其他"、"包浆豆腐烤豆腐"标为"服饰"）
- ** workaround**：`ugc_type_profiles.correct_type()` 基于 POI 名称做启发式修正，已集成到路线规划流程
- **根治方案**：需重新处理 2GB 原始评论数据（`ugc_groundtruth_v4_xl.json`）生成更准确的类型映射

### LLM 依赖
- 意图分类和语义搜索均依赖 GLM API，网络异常时会降级为 `complex_route` 或跳过语义增强
- 建议在生产环境配置 API Key 并监控调用成功率

### 性能
- 首次查询需加载 184MB 语义向量，约 3-5 秒
- 后续查询复用内存缓存，响应时间 < 1 秒（不含 LLM 调用）
- 路网 Dijkstra 计算已做懒加载 + 本地缓存（`poi_knn_cache.json`）

### 覆盖范围
- 当前数据仅覆盖成都武侯/锦江区域（天府广场为中心，默认 3km 半径）
- 扩展其他城市需重新生成：POI 数据、路网、语义向量、营业时间
