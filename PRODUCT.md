# 智能路线规划系统 —— 产品文档 v3.3

## 1. 产品概述

基于语义理解 + 路网距离 + 营业时间的智能 POI 路线规划引擎。用户用自然语言描述需求（如"想吃火锅"、"成都半日游"），系统自动生成贴合街道的真实路线。

### 核心差异化
- **意图理解**：短查询先走本地规则快路径，复杂模糊表达再调用 MiMo/MiniMax/GLM，避免"想吃火锅"被过度规划成路线
- **语义检索增强**：复杂路线在配置 `GLM_API_KEY` 后可用本地 POI 向量 + GLM 查询向量做候选增强，未配置或网络异常时自动跳过
- **下一代交互理解**：支持 `session_id/user_id` 记忆、多说话人对话聚合、清淡/约会/亲子/商务等语义需求匹配
- **路网真实路径**：Dijkstra 最短路径，路线折线贴合街道（非直线）
- **营业时间过滤**：自动排除已打烊的 POI，根据偏好类型自动调整起始时间
- **类型多样性约束**：餐饮≤2、景点≤2、同类型不重复，避免"火锅→茶馆→火锅"

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
  "session_id": "demo-session",
  "user_id": "demo-user",
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
  "request_id": "demo-request-id",
  "result": {
    "user_goal": "想吃火锅",
    "constraints": {
      "preferred_tags": ["餐饮", "火锅"],
      "start_time": "11:00",
      "intent_type": "single_poi",
      "interaction": {
        "session_id": "demo-session",
        "user_id": "demo-user",
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
            "name": "宽板凳火锅鱼(大石东路店)",
            "type": "火锅",
            "category": "餐饮",
            "score": 4.6,
            "business_hours": {"open_time": "10:30", "close_time": "02:00"},
            "location": {"lat": 30.65, "lng": 104.08}
          }
        ]
      }
    ]
  },
  "interaction": {
    "session_id": "demo-session",
    "user_id": "demo-user",
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
  "session_id": "group-demo",
  "user_id": "demo-user",
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

`/api/session?session_id=demo-session&user_id=demo-user` 返回当前会话记忆和长期轻画像。

### POST /api/session/clear —— 清除会话记忆

```json
{"session_id": "demo-session"}
```

### POST /api/profile/clear —— 清除长期画像

```json
{"user_id": "demo-user"}
```

### POST /api/feedback —— 写入长期偏好

```json
{
  "user_id": "demo-user",
  "feedback": {
    "preferred_tags": ["茶馆"],
    "avoid_tags": ["KTV"],
    "dietary": ["不吃辣"]
  }
}
```

## 4. 配置说明

所有配置通过 `config.py` 管理，支持环境变量覆盖（前缀 `HACKATHON_`）。

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
| POI匹配 | `PoiMatcher` | 根据POI类型、名称和GT评分推断属性，并把语义匹配分融入排序 |

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
- 意图分类优先使用 MiMo/MiniMax/GLM，网络异常时会降级到本地规则；语义搜索需要 `GLM_API_KEY`，未配置或网络异常时会跳过增强
- 建议在生产环境配置 API Key 并监控调用成功率

### 性能
- 首次查询需加载 184MB 语义向量，约 3-5 秒
- 后续查询复用内存缓存，响应时间 < 1 秒（不含 LLM 调用）
- 路网 Dijkstra 计算已做懒加载并读取本地缓存（`poi_knn_cache.json`）；默认不强制落盘，设置 `PERSIST_KNN_CACHE=1` 可开启缓存持久化

### 覆盖范围
- 当前数据仅覆盖成都武侯/锦江区域（天府广场为中心，默认 3km 半径）
- 扩展其他城市需重新生成：POI 数据、路网、语义向量、营业时间

### 前端地图
- Web 前端使用 Leaflet CDN 和高德瓦片服务；外网不可用时地图可能不显示，但结果列表、时间轴和推荐仍可正常展示
