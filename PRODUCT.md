# 智能路线规划系统 —— 产品文档 v3.3

## 1. 产品概述

基于语义理解 + 路网距离 + 营业时间的智能 POI 路线规划引擎。用户用自然语言描述需求（如"想吃火锅"、"成都半日游"），系统自动生成贴合街道的真实路线。

### 核心差异化
- **意图理解**：短查询先走本地规则快路径，复杂模糊表达再调用 MiMo/MiniMax/GLM，避免"想吃火锅"被过度规划成路线
- **语义检索增强**：复杂路线在配置 `GLM_API_KEY` 后可用本地 POI 向量 + GLM 查询向量做候选增强，未配置或网络异常时自动跳过
- **下一代交互理解**：支持 `session_id/user_id` 记忆、多说话人对话聚合、清淡/约会/亲子/商务等语义需求匹配
- **路网真实路径**：Dijkstra 最短路径，路线折线贴合街道（非直线）
- **营业时间与时长治理**：自动排除已打烊的 POI，根据偏好类型自动调整起始时间；未显式说明时长时按单点、组合、半日/一日、商务/夜间场景推断合理预算
- **类型多样性约束**：餐饮≤2、景点≤2、同类型不重复，避免"火锅→茶馆→火锅"
- **服务范围明确**：当前只支持成都武侯区、锦江区本地数据；外地城市或未覆盖区县会在入口公告和 API 响应中明确提示。

## 2. 技术架构

```
前端 (web/)
  └── index.html + app.js + styles.css
        ↓ POST /api/plan
web_app.py (ThreadingHTTPServer)
  └── app_service.py
        ├── interaction_intelligence.py (记忆/多人对话/需求匹配)
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
| `output/user_memory_profiles.json` | 运行时生成 | `user_id` 对应的轻量偏好/避让/饮食画像 |
| `chengdu_road_network.json` | 61MB | 291,460 条路网边 |
| `poi_business_hours.json` | 10MB | 营业时间数据 |

## 3. API 接口

### POST /api/plan —— 路线规划

**请求体：**
```json
{
  "goal": "想吃火锅",
  "session_id": "default-session",
  "user_id": "sample-user",
  "center_lat": 30.65705,
  "center_lng": 104.06476,
  "radius": 3000,
  "city": "chengdu"
}
```

**响应体：**
```json
{
  "ok": true,
  "request_id": "sample-request-id",
  "result": {
    "user_goal": "想吃火锅",
    "constraints": {
      "preferred_tags": ["餐饮", "火锅"],
      "start_time": "11:00",
      "intent_type": "single_poi",
      "interaction": {
        "session_id": "default-session",
        "user_id": "sample-user",
        "memory_applied": [],
        "user_needs": [],
        "conflicts": []
      }
    },
    "variants": [
      {
        "variant_id": "single_poi",
        "name": "单点推荐",
        "poi_count": 5,
        "recommendations": [
          {
            "name": "海底捞火锅(南纱帽街店)",
            "type": "火锅",
            "category": "餐饮",
            "score": 4.6,
            "business_hours": {"open_time": "10:30", "close_time": "02:00"},
            "location": {"lat": 30.65, "lng": 104.08},
            "recommendation_basis": {
              "model": "feature_ranker_v1.5",
              "score": 25.0,
              "top_reasons": [
                "质量评分 4.6，游客 对 火锅 权重 1.30",
                "命中用户偏好：餐饮、火锅",
                "同品牌在本地数据中有多家可识别门店：海底捞",
                "更像正餐火锅门店，适合到店推荐"
              ],
              "features": {
                "quality_score": 4.6,
                "type_weight": 1.3,
                "preference_bonus": 4.5,
                "semantic_need_adjustment": 0,
                "density_bonus": 0.3,
                "review_count_estimate": 157,
                "popularity_adjustment": 1.07,
                "brand_popularity_bonus": 2.0,
                "entity_quality_adjustment": 3.2,
                "entity_quality_signals": ["restaurant_raw_type", "full_service_hotpot"],
                "distance_to_start_m": 537,
                "nearest_same_type_m": 180,
                "open_at_arrival": true
              }
            }
          }
        ]
      }
    ],
    "model": {
      "planner_version": "route_planner_v3.9",
      "ranking_model": "feature_ranker_v1.5",
      "strategy": "feature-weighted constraint planner",
      "candidate_pipeline": {
        "raw_poi_count": 47045,
        "spatial_candidates": 8000,
        "name_filter_removed": 1200,
        "type_filter_removed": 500,
        "candidate_pool_after_cap": 300,
        "hotpot_brand_roots": 552,
        "entity_type_corrections": 1795,
        "llm_candidate_review": {"enabled": true, "used": false, "reason": "provider_unavailable"}
      }
    }
  },
  "interaction": {
    "session_id": "default-session",
    "user_id": "sample-user",
    "memory_applied": [],
    "user_needs": [],
    "conflicts": []
  },
  "notice": null,
  "performance": {
    "load_ms": 120,
    "plan_ms": 850,
    "total_ms": 970
  }
}
```

**多人对话请求示例：**
```json
{
  "session_id": "group-session",
  "user_id": "sample-user",
  "goal": "小明：春熙路附近吃火锅\n小红：吃完想逛街\n小明：不要太贵",
  "dialogue": [
    {"speaker_id": "小明", "text": "春熙路附近吃火锅"},
    {"speaker_id": "小红", "text": "吃完想逛街"},
    {"speaker_id": "小明", "text": "不要太贵"}
  ]
}
```

### GET /api/health —— 健康检查

**响应：**
```json
{
  "ok": true,
  "version": "3.3.0",
  "features": ["semantic_search", "road_network", "llm_intent", "business_hours", "type_diversity", "session_memory", "dialogue_state", "need_matching"]
}
```

### GET /api/session —— 会话与画像查看

`/api/session?session_id=default-session&user_id=sample-user` 返回当前会话记忆和长期轻画像。

### POST /api/session/clear —— 清除会话记忆

```json
{"session_id": "default-session"}
```

### POST /api/profile/clear —— 清除长期画像

```json
{"user_id": "sample-user"}
```

### POST /api/feedback —— 写入长期偏好

```json
{
  "user_id": "sample-user",
  "feedback": {
    "preferred_tags": ["茶馆"],
    "avoid_tags": ["KTV"],
    "dietary": ["不吃辣"]
  }
}
```

## 4. 配置说明

所有配置通过 `config.py` 管理，支持环境变量覆盖；旧版带前缀变量仍可兼容读取。

### 环境变量示例（.env）
```bash
# LLM API Key（任选其一；无 key 时使用规则 fallback）
MIMO_API_KEY=
MINIMAX_API_KEY=
GLM_API_KEY=

# 服务监听
HOST=127.0.0.1
PORT=8000

# 规划引擎参数
CANDIDATE_POOL_SIZE=300
LIMIT_FOOD=2
LIMIT_SIGHT=2
LIMIT_SHOPPING=1
LIMIT_LEISURE=2
SEMANTIC_TOP_K=80
SEMANTIC_BOOST=2.5
ENABLE_LLM_CANDIDATE_REVIEW=1
LLM_REVIEW_CANDIDATE_TOP_N=12
LLM_REVIEW_BONUS=1.2
PERSIST_KNN_CACHE=0
```

### 关键配置项
| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `CANDIDATE_POOL_SIZE` | 300 | 候选池大小 |
| `CATEGORY_QUOTA` | 景点50/休闲40/购物25/餐饮80/其他20 | 候选池类型配额 |
| `CATEGORY_LIMITS` | 餐饮2/景点2/购物1/休闲2 | 路线中各大类上限 |
| `CONCRETE_TYPE_LIMIT` | 1 | 同一具体类型上限 |
| `SEMANTIC_TOP_K` | 80 | 复杂路线语义增强候选数 |
| `SEMANTIC_BOOST` | 2.5 | 语义命中加分 |
| `ENABLE_LLM_CANDIDATE_REVIEW` | 1 | 是否允许大模型在已筛出的 POI 候选中评审重排 |
| `LLM_REVIEW_CANDIDATE_TOP_N` | 12 | 送入候选评审的大模型候选数 |
| `LLM_REVIEW_BONUS` | 1.2 | 大模型候选评审最大加分 |
| `AUTO_TIME_PERCENTILE` | 60 | 自动调整起始时间的百分位 |
| `AUTO_TIME_THRESHOLD` | 0.05 | 营业率低于此值时触发时间调整 |
| `PERSIST_KNN_CACHE` | 0 | 是否把新计算的KNN距离写回本地缓存 |

## 5. 下一代交互策略

| 能力 | 模块 | 说明 |
|------|------|------|
| 会话记忆 | `InteractionManager` / `MemoryStore` | `session_id` 继承上轮中心点、半径、提过的类型和推荐过的POI |
| 长期画像 | `output/user_memory_profiles.json` | `user_id` 记录轻量偏好、避让、饮食限制；可通过 `/api/feedback` 更新，通过 `/api/profile/clear` 删除；`avoid_tags` 进入候选硬过滤 |
| 多人对话 | `DialogueStateTracker` | 从 `dialogue/messages` 或 `goal` 中的 `说话人：内容` 多行文本提取 food/activity/location/budget/sequence，并检测火锅+不辣等冲突 |
| 语义需求 | `NeedInferer` | 将“清淡”“适合约会”“带孩子”“商务宴请”“拍照好看”映射为结构化需求标签 |
| POI匹配 | `PoiMatcher` | 根据POI类型、名称和评分聚合信号推断属性，并把语义匹配分融入排序 |

当多人对话推断出明确顺序时，交互层会通过 `interaction.intent_hint` 覆盖基础意图分类，例如短文本先被规则识别为 `single_poi`，但 `sequence=["中餐","商场"]` 会提升为 `simple_route`。

交互智能回归测试：
```bash
python _test_interaction.py
```

## 6. 意图分类与推荐策略

系统先用本地规则识别高置信短查询；规则不确定时按 MiMo → MiniMax → GLM 的顺序调用 LLM，失败后回落到规则分类：

| 意图类型 | 触发条件 | 变体数 | POI 数 | 示例 |
|---------|---------|--------|--------|------|
| `single_poi` | 只想去一个地方 | 1 | 1-5 个推荐 | "想吃火锅" |
| `simple_route` | 想去 2-3 个地方 | 1 | 2-3 | "吃完火锅去茶馆" |
| `complex_route` | 规划完整路线 | 3 | 3-6 | "成都半日游" |

### 推荐依据与质量治理

- 每个 POI 返回 `recommendation_basis`，解释质量分、类型权重、评价热度估计、偏好/语义命中、营业状态、移动成本、路网可达性、类型一致性、数据驱动品牌识别和门店实体可信度；同时返回 `review_summary`，把本地评分/热度/场景信号转为前端可展示的精选口碑摘要。
- 每次规划返回 `result.model.candidate_pipeline`，记录空间过滤、类型修正、低价值名称过滤、类型过滤、候选池截断、语义检索命中和 LLM 候选评审状态。
- 低价值 POI 治理覆盖停业/装修、入口/门岗、停车/快递/充电设施、民宿房源、普通销售经营点；火锅推荐会降级麻辣烫/冒菜/甜品误分类和共享充电等附属设施，优先完整正餐火锅门店，并按候选池/全量 POI 中的品牌根、分店数、核心商圈店和正餐实体信号排序。
- `feature_ranker_v1.5` 增加类型评论画像驱动的 `review_count_estimate` 与 `popularity_adjustment`，同时把公园、茶馆、咖啡、中餐、商场、超市、酒吧/小酒馆的实体适配纳入 `entity_quality_signals`，避免仅按文本相似或单一评分推荐误分类 POI。
- 大模型只参与“已存在候选”的评审重排：系统向 LLM 提供候选 POI ID、名称、类型、距离和排序特征，LLM 返回 POI ID 级加分与理由；任何不存在的 POI ID 都会被丢弃，网络或 API 异常时本地排序继续生效。
- 单点“逛街/购物”优先真实商场本体；完整路线不再用普通购物或 `其他` 类型凑点。
- “逛街+咖啡”“喝酒+夜宵”“午餐+咖啡”“超市+小吃”等组合意图会生成严格 `sequence`，具体类型顺序不再被同大类候选替代。严格步行/时间约束下无法构成主路线时，返回带时间轴、移动距离和 `polyline` 的“顺序候选路线”，前端仍能绘制路线。
- `time_budget_source` 标记时长来自用户显式输入还是系统推断；“春熙路附近想吃火锅”会按单点用餐估算为短时段，“太古里逛街喝咖啡”会按两点组合估算为约 2.5 小时，“半日/一日”仍分别保留 4/8 小时。
- 短句模糊意图会进入澄清门控：服务返回 `clarification_options`，前端展示可点击选项；同一 `session_id` 下支持“那附近换成茶馆”“还有别的吗”等多轮承接。
- 路网起点候选过严时，会降级为直线距离起点选择，并在 `recommendation_basis.features.start_fallback` 中标记。

## 7. 部署指南

### 环境要求
- Python 3.7+
- 依赖：`numpy`

### 启动服务
```bash
python run_server.py --warmup
```
服务默认监听 `http://127.0.0.1:8000`。

也可以指定监听地址和端口：
```bash
python run_server.py --host 127.0.0.1 --port 8001 --warmup
```

### 前端访问
浏览器打开 `http://127.0.0.1:8000/`，输入自然语言需求即可获取路线。

### 服务检查
```bash
curl http://127.0.0.1:8000/api/health
curl http://127.0.0.1:8000/api/ready
```

`/api/ready` 会检查本地数据资产、索引加载状态和进程级数据仓库状态；`/api/plan` 返回 `request_id` 和结构化错误码。

## 8. 已知问题与限制

### 数据质量
- `type_index.json` 中存在少量类型标注错误（如"锦江之星"标为"其他"、"包浆豆腐烤豆腐"标为"服饰"）
- **Workaround**：`ugc_type_profiles.correct_type()` 基于 POI 名称做启发式修正，已集成到路线规划流程
- **根治方案**：需重新处理 2GB 原始评论数据（`ugc_groundtruth_v4_xl.json`）生成更准确的类型映射

### LLM 依赖
- 意图分类优先使用 MiMo/MiniMax/GLM，网络异常时会降级到本地规则；语义搜索需要 `GLM_API_KEY`，未配置或网络异常时会跳过增强；候选评审可使用同一组 LLM Provider，但只重排真实候选
- 建议在生产环境配置 API Key 并监控调用成功率

### 性能
- 首次查询需加载 184MB 语义向量，约 3-5 秒
- 后续查询复用内存缓存，响应时间 < 1 秒（不含 LLM 调用）
- 路网 Dijkstra 计算已做懒加载并读取本地缓存（`poi_knn_cache.json`）；默认不强制落盘，设置 `PERSIST_KNN_CACHE=1` 可开启缓存持久化

### 覆盖范围
- 当前数据仅覆盖成都武侯/锦江区域（默认中心为天府广场，坐标 `104.06476,30.65705`，默认 3km 半径）
- 支持的本地中心包括春熙路、太古里、成都 IFS、锦里、武侯祠、九眼桥、兰桂坊、望江路。后端会根据用户文本中最早出现的本地地标自动重设中心。
- 外地城市或未覆盖区县返回 `UNSUPPORTED_SERVICE_AREA`，响应中包含 `service_area`；前端首次进入也会展示服务范围公告。
- 当前 POI 语料在武侯祠/锦里周边真实景点条目较少，系统会诚实返回可用的公园/周边候选，不编造本地数据中不存在的景点。
- 扩展其他城市需重新生成：POI 数据、路网、语义向量、营业时间

### 前端地图
- Web 前端使用 Leaflet CDN 和高德瓦片服务；外网不可用时地图可能不显示，但结果列表、时间轴和推荐仍可正常展示
