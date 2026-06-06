# 智能路线规划系统

RouteMind 是面向成都本地生活的自然语言出行决策系统，不要求用户按固定模板输入。它可以理解单点推荐、组合需求、夜间场景、出差效率和周边游等不同目标，例如：

- `春熙路附近想吃火锅`
- `太古里附近逛街喝咖啡`
- `九眼桥晚上喝酒，顺便找点夜宵`
- `天府广场附近出差，1小时内找午餐和咖啡`
- `武侯祠附近看景点`

系统会根据意图输出单点候选、候选组合或带时间轴的可执行路线，并为每个推荐点返回结构化推荐依据。

> **当前阶段**：成都武侯+锦江两区本地数据服务（47,045 POI）。后端会拦截广州、重庆、青羊区等超出服务范围的请求并返回 `UNSUPPORTED_SERVICE_AREA`；架构按可替换数据适配器设计，后续接入高德/美团等线上数据源时无需改动规划引擎。

---

## 评审快速入口

- [评委阅读指南](docs/JUDGES_GUIDE.md)：产品能力、可演示场景、实现路径、工程质量和当前边界。
- [产品说明](PRODUCT.md)：接口契约、模型输出、推荐依据、运行方式和部署说明。
- [API 迁移说明](docs/API_MIGRATION.md)：本地数据适配器如何替换为线上 POI、点评和路径服务。
- [生产检查清单](docs/PRODUCTION_CHECKLIST.md)：上线前需要确认的数据、安全、可观测性和回归测试项。
- [部署指南](DEPLOY.md)：本地安全打包、服务器安装、systemd 服务和健康检查。

---

## 核心能力

- **自然语言意图解析**：支持时间预算/出行方式/偏好类型/起始时间（如"下午四点"）
- **三种用户模式**：游客（景点优先）、出差（效率优先）、居民（日常优先）
- **多方案输出**：紧凑高效 / 休闲慢游 / 美食探店
- **路网级路径规划**：Dijkstra真实路网距离 + KNN懒加载缓存（请求内复用，按需开启落盘）
- **营业时间校验**：避免安排已打烊的POI
- **类型推断引擎**：36种POI类型，名称关键词+tag+typecode三级推断
- **结构化推荐依据**：每个 POI 返回 `recommendation_basis`，解释质量分、类型权重、评价热度估计、偏好/语义命中、营业状态、移动成本、路网可达性、类型一致性、数据驱动品牌识别、门店实体可信度等特征
- **约束式 LLM 候选评审**：配置 API Key 后，大模型只在已筛出的真实 POI 候选中做小幅重排和解释，不允许生成不存在的店；不可用时自动降级
- **候选管线诊断**：每次规划返回 `result.model.candidate_pipeline`，追踪空间过滤、名称过滤、类型过滤、候选池截断和类型修正
- **下一代交互理解**：会话/长期记忆、多人对话槽位融合、清淡/约会/亲子/商务等语义需求匹配
- **轻个性化推荐**：会话上下文记忆 + 时间感知 + 天气感知 + 实时人流规避 + 匿名群体信号（全部基于非隐私信息）

---

## 快速开始

```bash
cd demo

# 启动本地服务
python run_server.py --warmup

# 访问 http://127.0.0.1:8000/

# 健康检查 / 就绪检查
# http://127.0.0.1:8000/api/health
# http://127.0.0.1:8000/api/ready

# 本地 smoke test（不依赖外部模型时会走规则 fallback）
python _test_iter.py
python _test_interaction.py
```

**输出示例**：

```
约束: 预算4h | 方式:walk | 偏好:餐饮 | 半径:3000m | 起始:16:00

--- [紧凑高效] 在有限时间内串联最多景点，移动路径最短
   POI:6 | 总时间:238min | 移动:2245.0m/33.5min | 利用率:99%
   1. 海底捞火锅(南纱帽街店) [火锅] 16:00-16:50 (口碑稳定，品牌与门店实体信号较强)
   2. 春熙路周边休闲/茶饮点 16:55-17:25  <- 约300m/5min
   3. ...
   ...
```

---

## 系统架构

### 三层解耦设计

```
┌─────────────────────────────────────────────────────────────┐
│  数据适配层（mock_api/，本地 POI 适配器实现）                 │
│  当前: LocalApiClient 读取本地JSON                            │
│  未来: HttpApiClient 调用高德/美团真实API                     │
│                                                             │
│  ├── search_pois()       → 高德POI周边搜索                   │
│  ├── get_poi_detail()    → 高德POI详情                       │
│  ├── get_comment_summary() → 美团评分聚合                     │
│  ├── get_walking_route() → 高德路径规划（或本地Dijkstra）      │
│  └── get_business_hours() → 美团营业信息                      │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  个性化层（personalization.py）                              │
│  匿名、聚合、会话隔离的轻个性化信号                           │
│                                                             │
│  ├── SessionContext       会话内上下文记忆（排除/偏好/点击）   │
│  ├── TimeAwareScorer      时间感知路由（早餐/下午茶/夜宵）     │
│  ├── WeatherAwareScorer   天气感知推荐（雨天推荐室内）         │
│  ├── CrowdAwareScorer     实时人流规避（排队惩罚）             │
│  └── AggregateSignal      匿名群体偏好信号                   │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  规划层（route_planner_v3.py）                               │
│  纯算法，不感知数据来源，支持三种用户模式                     │
│                                                             │
│  ├── parse_goal()         自然语言意图解析                   │
│  ├── build_plan_v3()      主规划入口                         │
│  └── build_route_v3()     贪心路线构建 + 营业时间过滤         │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  缓存层                                                      │
│  ├── poi_knn_graph.py     路网距离懒加载缓存（本地JSON）       │
│  ├── spatial_index.json   500m网格空间索引                   │
│  ├── type_index.json      预计算POI类型                      │
│  └── gt_index.json        评分/评论聚合索引                  │
└─────────────────────────────────────────────────────────────┘
```

### 关键设计决策

| 决策 | 当前实现 | 未来扩展 |
|------|---------|---------|
| **数据源** | 本地模拟数据 | 高德/美团/百度API |
| **路网** | k近邻模拟图 + Dijkstra | 高德路径规划API |
| **UGC评论** | 规则生成775万条 | 平台真实评论API |
| **缓存** | 读取本地JSON缓存，请求内懒加载；可用 `PERSIST_KNN_CACHE=1` 开启落盘 | Redis Cluster按城市分片 |
| **部署** | 单机 | K8s城市分片Pod |

---

## 文件结构

```
demo/
├── mock_api/                    # 本地/线上 POI 数据适配器
│   └── __init__.py              # 本地/线上 POI 数据适配器
│
├── output/                      # 生成数据和缓存
│   ├── gt_index.json            # 评分/评论聚合索引
│   ├── spatial_index.json       # 500m网格空间索引
│   ├── type_index.json          # 预计算POI类型
│   ├── poi_knn_cache.json       # KNN路网距离缓存（默认只读，可配置落盘）
│   └── user_memory_profiles.json # 运行时长期轻画像（自动生成）
│
├── web/                         # Web前端
│   ├── index.html
│   ├── styles.css
│   └── app.js
│
├── route_planner_v3.py          # 路线规划引擎（核心算法）
├── poi_knn_graph.py             # KNN懒加载缓存图
├── personalization.py           # 轻个性化引擎（隐私优先）
├── road_network.py              # Dijkstra路径计算
├── semantic_search.py           # 语义向量检索
├── interaction_intelligence.py  # 记忆/多人对话/语义需求匹配
├── config.py                    # 配置与.env加载
├── generate_road_network.py     # 路网模拟生成（数据工具）
├── generate_business_hours.py   # 营业时间生成（数据工具）
├── ugc_type_profiles.py         # 类型配置与评分特征
├── llm_clients.py               # LLM API客户端
├── app_service.py               # 应用服务入口
├── web_app.py                   # Web服务入口
├── _test_iter.py                # 核心场景smoke test
├── _test_multi.py               # 多场景意图/结果检查
│
├── wuhou_jinjiang_pois.json     # POI本体数据（47,045个）
├── chengdu_road_network.json    # 模拟路网（291,460边）
├── poi_business_hours.json      # 营业时间数据
├── ugc_groundtruth_v4_xl.json   # UGC评论数据（775万条，1.97GB）
│
├── README.md                    # 本文件（入口速览）
├── AGENTS.md                    # 框架文档（架构/决策/实现）
├── DATA.md                      # 数据文档（规模/质量/规则）
├── REQUIREMENTS.md              # 需求文档（三种用户模式）
├── PRIVACY.md                   # 隐私设计白皮书
│
├── .env                         # 环境变量
├── .env.example                 # 环境变量模板
└── requirements.txt             # Python依赖
```

---

## 性能指标

| 场景 | 数据加载 | 规划耗时 | 总响应 | KNN缓存命中 |
|------|---------|---------|--------|------------|
| 第1次查询（冷） | 0.55s | 5.6s | 6.1s | 57% |
| 第2次查询（热） | 0.55s | **2.4s** | **3.0s** | **100%** |

*测试条件：春熙路3km范围，9227候选POI，3种方案*

---

## 数据说明

当前为**预研阶段**，所有数据为模拟生成，用于验证算法架构：

| 数据 | 规模 | 生成方式 | 未来替换 |
|------|------|---------|---------|
| POI本体 | 47,045个 | 高德Excel清洗 | 高德POI Search API |
| UGC评论 | 775万条 | 规则生成 | 美团/点评真实评论 |
| 评分聚合索引 | 47,045条 | 规则生成 | 平台真实评分/评论聚合 |
| 路网 | 291,460边 | k近邻模拟 | 高德路径规划API |
| 营业时间 | 47,045条 | 按类型规则 | 平台真实数据 |
| 用户轻画像 | 按 `user_id` 增长 | 本地反馈与会话沉淀 | 授权后的用户偏好服务/Redis |

全国推广时**不预加载全国全量**，按城市分片按需加载，单城市约200-500MB。

---

## 轻个性化引擎

五个匿名信号协同优化推荐，全部不侵犯隐私：

| 信号 | 信息来源 | 隐私风险 | 效果示例 |
|------|---------|---------|---------|
| **会话上下文** | 本次对话 | 零（会话结束销毁） | "不要烧烤"→自动排除所有烧烤 |
| **时间感知** | 系统时钟 | 零 | 下午3点→优先下午茶，晚上9点→优先夜宵 |
| **天气感知** | 公开天气API | 零 | 雨天→公园-999分（排除），商场+2分 |
| **实时人流** | 平台匿名聚合数据 | 匿名，无法反推个人 | 排队30分钟→-1.5分，推荐替代店 |
| **群体信号** | 聚合统计(N≥100) | 无法反推个人 | "周六春熙路68%选火锅"→火锅+0.3分 |

**用户控制**：一键清除会话、一键清除长期轻画像、关闭位置授权、关闭个性化开关。

详细设计见 `PRIVACY.md`。

## 下一代交互能力

`docs/next_gen_interaction_design.md` 中的三项能力已接入本地服务：

| 能力 | 当前实现 |
|------|----------|
| 长期/会话记忆 | `session_id` 继承上轮中心点、提到过的类型、推荐过的POI；`user_id` 写入可删除的轻量长期画像 `output/user_memory_profiles.json` |
| 多人对话理解 | 请求可传 `dialogue/messages` 数组；也可只在 `goal` 中输入 `小明：...` 多行对话，后端会自动解析并聚合地点、食物、活动、预算、顺序 |
| 语义需求匹配 | `NeedInferer` 推断 `diet:light`、`scene:romantic`、`audience:family` 等标签；`PoiMatcher` 把这些标签融入 POI 排序；画像 `avoid_tags` 会作为硬过滤 |

多人对话推断出的顺序会通过 `interaction.intent_hint` 覆盖基础意图分类，避免“吃饭再逛街”这类短输入被当成单点推荐。

相关接口：
- `POST /api/plan`：支持 `session_id`、`user_id`、`dialogue`、`feedback`
- `GET /api/session?session_id=...&user_id=...`：查看会话与用户画像
- `POST /api/session/clear`：清除当前会话记忆
- `POST /api/profile/clear`：清除指定 `user_id` 的长期轻画像
- `POST /api/feedback`：写入长期偏好/避让/饮食反馈

交互层回归测试：
```bash
python _test_interaction.py
```

典型输入：
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

---

## 安装

```bash
pip install -r requirements.txt
```

运行依赖：`numpy`。当前项目用内置 `.env` 读取器，不需要 `python-dotenv`。

Windows终端需设置UTF-8编码：
```bash
chcp 65001
```

---

## 服务化能力

后端按服务化方式组织本地数据，接口层与外部数据源解耦：

- `data_repository.py` 统一管理本地 POI、索引和资产检查，进程内复用数据源。
- `/api/health` 返回服务版本、Python版本和功能开关。
- `/api/ready` 检查必需数据文件是否存在，并展示核心索引/客户端加载状态。
- `/api/plan` 响应带 `request_id`，错误带 `error_code`，便于排查线上请求。
- `run_server.py --warmup` 可在接收请求前预加载核心数据，降低首个请求抖动。

---

## 后端模型契约

规划结果现在包含两层可审计信息：

- `result.model`：记录 `planner_version`、`ranking_model`、意图来源、特征来源、语义检索状态和 `candidate_pipeline`。
- `recommendation_basis`：每个路线点或单点推荐都会返回总分、`top_reasons` 和特征明细。

候选质量治理会过滤停业/装修、门岗/入口、停车/快递/充电设施、民宿房源、普通销售经营点等低价值 POI；逛街+咖啡、喝酒+夜宵、午餐+咖啡、超市+小吃等组合需求会生成严格顺序约束，避免同大类泛化候选挤掉用户明确说出的类型。路网起点过严导致无起点时，路线构建会降级到直线距离起点选择，并在 `recommendation_basis.features.start_fallback` 中标注；若严格时间/步行约束下无法构成路线，会返回“候选组合”而不是硬凑路线。

`feature_ranker_v1.4` / `route_planner_v3.8` 在 v1.3 的品牌识别基础上增加了更严格的服务范围、组合意图和实体适配治理：

- `review_count_estimate` / `popularity_adjustment`：根据类型评论画像、商圈 POI 密度和 GT 质量分估算评价样本量，让“名气/热度”与评分一起参与排序。
- `entity_quality_adjustment` / `entity_quality_signals`：覆盖火锅、茶馆、咖啡、中餐、公园、商场、超市、酒吧/小酒馆等常见场景，纠正“绿地超市=公园”“酒店=中餐”“茶饮=茶馆”“营养 club=酒吧”等误分类。
- `sequence` 严格匹配：具体类型顺序只接受精确类型命中，例如“酒吧→小吃”不会被“农家乐→火锅”这种同大类候选替代。
- `service_area`：规划结果和错误响应都带服务范围说明。当前数据只覆盖成都武侯区、锦江区；武侯祠/锦里周边真实景点数据不足时，系统会返回可用的公园/周边候选，不会编造不存在的景点。
- `result.model.candidate_pipeline.entity_type_corrections`：记录候选阶段按实体证据修正的类型数量，便于排查数据索引质量。

后端模型回归测试：
```bash
python -m unittest tests.test_backend_model_contract
python _test_multi.py
```

---

## Web 工作台

当前 `web/` 是 RouteMind 三栏工作台，并与 `ui/` 下的桌面 V2 原型保持一致：

- 左栏：自然语言/多人对话输入、常用目标 chip、上次目标、本轮清空、三种用户模式、中心点、半径、定位、会话与画像清除。
- 中栏：Leaflet 地图画布、缩放/归中/起点定位、路线/POI 图层开关、marker tooltip、地图不可用降级。
- 右栏：方案对比卡、只看差异、时间轴/单点推荐列表、推荐理由、复制路线文本、复制 POI 名单、toast、无结果修正入口。
- 产品能力：中英文 UI 切换、清爽/暖橙/夜游主题、生成中四步进度、移动端堆叠布局。

`ui/route_planner_desktop_v1.html` 和 `ui/route_planner_desktop_v2.html` 仍保留为静态高保真原型；真实后端联调用 `python run_server.py --warmup` 后访问 `http://127.0.0.1:8000/`。

---

## 三种用户模式

| 模式 | 优先级类型 | 半径 | 单段上限 | 购物上限 |
|------|-----------|------|---------|---------|
| **游客** | 景点>公园>火锅>小吃 | 5000m | 30min | ≤1个 |
| **出差** | 中餐>茶馆>外国菜 | 1000m | **15min** | 0个 |
| **居民** | 火锅>烧烤>茶馆>公园 | 2500m | 25min | ≤2个 |

模式切换方式：
```python
build_plan_v3(..., user_mode="tourist")  # 或 "business" / "resident"
```

Web 前端也支持在“用户模式”下拉框中切换游客、出差、居民。

前端地图依赖 Leaflet CDN 和高德瓦片服务；外网不可用时页面会显示地图降级提示，路线列表仍可查看。

---

## 未来全国推广路径

1. **替换数据适配器**：本地 POI 适配器 → `HttpApiClient`，接口不变
2. **接入真实路网**：`road_network.py` 内部从Dijkstra切换为高德API
3. **城市分片加载**：按城市隔离数据，内存只保留当前城市
4. **分布式缓存**：KNN缓存从本地JSON迁移到Redis Cluster
5. **LLM意图解析**：保留短查询规则快路径，使用 MiMo/MiniMax/GLM 处理模糊表达（如"想吃点辣的"→火锅/烧烤）

详细架构决策见 `AGENTS.md`，数据规格见 `DATA.md`，需求定义见 `REQUIREMENTS.md`，隐私设计见 `PRIVACY.md`。
