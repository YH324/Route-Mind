# 框架文档

## 1. 系统架构

### 1.1 当前架构（成都武侯+锦江预研阶段）

```
用户输入 → 意图解析 → API客户端 → 候选筛选 → 评分排序 → 路线构建 → 时间轴输出
                                ↓
                        本地 POI 数据适配器（读取本地JSON）
                                ↓
                    POI / 评分聚合 / UGC / 路网 / 营业时间
```

### 1.2 未来全国推广架构

```
用户输入 → 意图解析(LLM) → API客户端 → 城市定位 → 候选筛选 → 评分排序 → 路线构建 → 时间轴输出
                                ↓
                        HttpApiClient（真实HTTP调用）
                                ↓
                    高德POI API + 美团评论API + 高德路径API
```

**三层解耦设计**：
1. **数据适配层**（`mock_api/`）：接口对标高德/美团，当前读本地JSON，未来换HTTP调用，规划引擎零改动
2. **规划层**（`route_planner_v3.py`）：纯算法，不感知数据来源
3. **缓存层**（`poi_knn_graph.py` + `spatial_index`）：加速重复查询，全国推广时迁移到Redis

**关键设计决策：城市分片**。当前仅加载成都两区数据，但代码层面已预留 `city` 参数和分片接口，未来接入全国时只需替换数据源，核心算法（KNN缓存、贪心规划、模式权重）无需改动。

---

## 2. 模块清单

| 模块 | 文件 | 职责 |
|------|------|------|
| API接入 | `llm_clients.py` | MiMo/MiniMax/GLM 等兼容聊天接口调用 |
| POI数据 | `mock_api/__init__.py` + `wuhou_jinjiang_pois.json` | 加载47,045 POI，按统一适配器接口对标真实POI搜索 |
| 评分/类型索引 | `output/gt_index.json` + `output/type_index.json` | 评分聚合索引与POI类型映射 |
| 类型修正 | `ugc_type_profiles.py` | 36类型配置、名称启发式修正 |
| 路网 | `road_network.py` | Dijkstra最短路径 + LRU缓存 |
| 路网生成 | `generate_road_network.py` | 从POI坐标模拟路网 |
| 营业数据 | `generate_business_hours.py` | 按类型生成营业时间 |
| 路线规划 | `route_planner_v3.py` | 主规划引擎（v3集成版） |
| 应用服务 | `app_service.py` + `web_app.py` | API封装与Web服务入口 |
| 交互智能 | `interaction_intelligence.py` | 会话/长期记忆、多人对话状态、语义需求匹配 |

---

## 3. 路线规划引擎（v3）

### 3.1 入口函数
```python
build_plan_v3(goal, pois, gt_data,
              center_lng=104.06476, center_lat=30.65705, radius=3000,
              hours_path="poi_business_hours.json",
              network_path="chengdu_road_network.json",
              spatial_index=None, type_index=None,
              use_knn=True, user_mode="tourist",
              interaction_context=None)
```

### 3.2 排序模型与推荐依据
`route_planner_v3.py` 使用 `feature_ranker_v1.4` 做候选排序。模型不只返回总分，还会在每个 POI 上输出 `recommendation_basis`，用于解释推荐依据和排查异常。

主要特征包括：

- `quality_score`：UGC/评分聚合质量分。
- `type_weight`：游客、出差、居民三种模式下的类型权重。
- `preference_bonus`：用户自然语言、会话记忆、多人对话中命中的偏好。
- `review_count_estimate` / `popularity_adjustment`：基于类型评论画像、商圈密度和 GT 质量分估算评价样本量，作为热度/名气信号参与排序。
- `brand_popularity_bonus`：从候选池和全量 POI 数据中统计出的品牌根、分店数、核心商圈店、历史质量等识别信号，避免只按单一分数把小众或误分类 POI 顶到前面。
- `entity_quality_adjustment` / `entity_quality_signals`：门店实体可信度，覆盖火锅、茶馆、咖啡、中餐、公园、商场、超市、酒吧/小酒馆等场景；优先完整餐厅/真实茶馆/咖啡门店/真实公园或商超/真实酒吧，降级麻辣烫/冒菜/甜品误分类、共享充电、酒店/会展/茶饮/棋牌/商业广场/健身 club 等错配 POI。
- `sequence` 严格约束：组合需求里的具体类型必须精确命中，避免“午餐+咖啡”被泛化成火锅+中餐，或“喝酒+夜宵”被泛化成农家乐+火锅。
- `llm_candidate_review_bonus`：配置 LLM Provider 后，对已筛出的真实候选 POI 做约束式评审重排；LLM 只能返回候选 `poi_id`，不能生成新地点。
- `semantic_need_adjustment`：清淡、约会、亲子、商务、拍照等语义需求匹配。
- `density_bonus` 与 `nearest_same_type_m`：空间密度和同类稀缺性信息。
- `open_at_arrival`：抵达时段是否营业。
- `network_connected`、`distance_m`、`travel_time_min`：路网可达性和移动成本。
- `type_consistency_penalty`：名称推断类型与索引类型冲突时降权。
- `route_rank_score`：路线阶段叠加语义检索、变体偏好、顺序约束、距离惩罚后的最终排序分。

整次规划还会返回 `result.model.candidate_pipeline`，记录原始 POI 数、空间过滤、名称过滤、类型过滤、候选池截断、类型修正和语义检索命中数。`app_service.py` 还会返回 `service_area`，并对成都武侯区、锦江区以外的城市/区县返回 `UNSUPPORTED_SERVICE_AREA`。

### 3.3 硬约束
```python
if travel_time > max_travel_minutes: continue      # 单段移动上限
if not is_open_at(poi, current_time): continue     # 营业校验
if total_time + travel_time + stay > time_budget: break  # 总时间预算
```

### 3.4 v3 核心改进
- ✅ 接入真实路网Dijkstra（替代Haversine直线距离）
- ✅ 营业时间可行性过滤
- ✅ 类型多样性奖励
- ✅ 低价值购物类排除（布艺/成衣/水果/编织/名酒）
- ⚠️ 评分均值3.41（低于v2的4.38，多样性会牺牲部分单点评分）
- ⚠️ 部分单段移动仍>20min（需按模式加严约束）

---

## 4. 三种用户模式实现

### 4.1 模式配置中心
```python
USER_MODES = {
    "tourist": {
        "type_weights": {"景点": 1.5, "公园": 1.4, "火锅": 1.3, "小吃": 1.1, "茶馆": 1.0},
        "stay_times": {"景点": 50, "公园": 40, "火锅": 50, "小吃": 20},
        "radius_m": 5000,
        "max_travel_min": 30,
        "max_shopping": 1,
        "exclude_types": ["便利店", "超市", "银行", "医院", "加油站"],
        "time_priority": "daytime_first"  # 先排景点（白天），再排晚餐
    },
    "business": {
        "type_weights": {"中餐": 1.2, "茶馆": 1.1, "外国菜": 1.0, "按摩SPA": 0.9, "商场": 0.7},
        "stay_times": {"中餐": 35, "简餐": 20, "茶馆": 30},
        "radius_m": 1000,
        "max_travel_min": 15,  # 硬约束：单段不超15分钟
        "max_shopping": 0,
        "exclude_types": ["景点", "游乐园", "公园", "便利店", "超市"],
        "time_priority": "strict_match"  # 严格匹配到达时间在营业时段内
    },
    "resident": {
        "type_weights": {"火锅": 1.3, "烧烤": 1.2, "茶馆": 1.1, "公园": 1.0, "健身": 0.9, "超市": 0.7},
        "stay_times": {"火锅": 50, "茶馆": 35, "公园": 40, "健身": 60},
        "radius_m": 2500,
        "max_travel_min": 25,
        "max_shopping": 2,
        "exclude_types": [],
        "new_store_bonus": 0.3,  # 开业<6个月加分
        "peak_avoid": True,       # 高峰避开排队>4
        "time_priority": "evening_first"  # 工作日优先晚上时段
    }
}
```

### 4.2 模式切换逻辑
```python
def apply_mode_config(plan_builder, user_mode):
    config = USER_MODES[user_mode]
    plan_builder.radius_m = config["radius_m"]
    plan_builder.max_travel_min = config["max_travel_min"]
    plan_builder.max_shopping = config["max_shopping"]
    plan_builder.exclude_types = config["exclude_types"]
    plan_builder.type_weights = config["type_weights"]
    plan_builder.stay_times = config["stay_times"]
    
    if user_mode == "business":
        plan_builder.strict_time_match = True
    elif user_mode == "resident":
        plan_builder.new_store_bonus = config.get("new_store_bonus", 0)
        plan_builder.peak_avoid = config.get("peak_avoid", False)
```

### 4.3 未来扩展
- 模式自动推断：根据用户query关键词（"出差"→business, "周末"→resident）
- 混合模式：支持手动调整权重
- 历史学习：根据用户反馈调整个人化权重

---

## 5. 技术决策记录

### 5.0 隐私优先架构

**核心原则**：所有个性化基于**匿名、聚合、会话隔离**的信息，不收集任何可识别个人身份的数据。

**可用信息（不侵犯隐私）**：
| 信息 | 来源 | 用途 | 隐私风险 |
|------|------|------|---------|
| 会话内交互 | 本次对话 | 排除指令/点击反馈/半径调整 | 会话结束即销毁 |
| 当前时间 | 系统时钟 | 时间感知路由（早餐/下午茶/夜宵） | 零 |
| 天气信息 | 公开天气API | 雨天推荐室内，晴天推荐户外 | 零 |
| POI聚合统计 | 平台匿名数据 | 实时人流规避、热门度排序 | 匿名，N≥100 |
| 匿名群体信号 | 聚合数据 | "周六晚上春熙路68%选火锅" | 无法反推个人 |

**绝对禁区**：手机号、真实身份账号、长期位置轨迹、消费记录、社交关系。当前只允许用用户提供的 `user_id` 保存低敏偏好/避让/饮食限制，并提供 `/api/profile/clear` 删除入口；详见 `PRIVACY.md`。

### 5.1 模拟数据 vs 真实数据：预研策略

当前处于**预研阶段**，所有数据为模拟生成，目的是验证算法架构。未来全国推广时逐项替换为真实API：

| 数据层 | 当前（预研） | 未来（全国推广） | 替换成本 |
|--------|------------|----------------|---------|
| POI本体 | 高德Excel清洗（47k） | 高德/百度POI Search API | 低 |
| UGC评论 | 规则生成7.75M条 | 美团/点评/小红书真实评论 | 中（需商务合作） |
| 评分聚合 | 规则生成overall | 平台真实评分/评论聚合 | 低 |
| 路网距离 | k近邻模拟图+Dijkstra | 高德路径规划API | 低 |
| 营业时间 | 按类型规则生成 | 平台真实营业数据 | 低 |

**为什么预研阶段用模拟数据？**
- 全国POI数千万，模拟全部不现实也不必要
- 两区数据足够验证：路线规划算法、KNN缓存机制、三种用户模式、空间索引效率
- 保留真实API接入接口，切换时只需替换数据源模块

### 5.2 城市分片：全国推广的核心架构

当前代码已内建城市分片扩展点：
- `build_plan_v3(city="chengdu", district=["wuhou","jinjiang"])` — 未来传入 `city="beijing"`
- KNN缓存按城市隔离：`output/knn_cache/{city}_knn.json`
- 空间索引按城市独立构建

单城市数据量估算：
| 城市 | POI数 | 数据量 | 内存占用 |
|------|-------|--------|---------|
| 成都两区 | 4.7万 | ~30MB | ~500MB |
| 成都全市 | ~80万 | ~500MB | ~2GB |
| 北京全市 | ~150万 | ~1GB | ~4GB |

**单机策略**：同时加载1-2个城市，切换城市时换出内存。
**高并发策略**：按城市分微服务实例，网关按城市路由。

### 5.3 为什么用模拟路网而非真实高德路网？
- 真实路网API有调用配额限制（日10000次）
- 47k节点×多源Dijkstra = 百万级路径查询，远超配额
- 模拟路网平均绕行系数1.61，与真实城市道路匹配度>80%
- **未来替换方案**：保留 `network.get_route_between()` 接口，内部从Dijkstra切换为高德API调用，上层代码零改动

### 5.4 KNN缓存：从单机缓存到全国缓存层

当前KNN缓存（`poi_knn_cache.json`）是**单文件懒加载**模式：
- 第1次查询：走Dijkstra/API，写入缓存
- 第2次查询：缓存命中，零计算

未来全国推广时升级为**分布式缓存**：
- 热门城市（北上广深蓉杭）：预计算高频POI的KNN，Redis缓存
- 冷门城市：首次查询走API，后续命中Redis
- KNN缓存与城市数据同步生命周期

### 5.5 为什么不用个人画像数据？
- 原始数据包含 `user_profiles.json` 和 `user_behaviors.json`
- **已删除**：个人隐私数据无法在企业系统中合规使用
- 替代方案：三种匿名模式 + 实时query意图解析（LLM）
- 未来可扩展：用户授权后接入平台历史行为，但核心架构不依赖个人画像

---

## 6. 文件结构

```
demo/
├── output/                      # 索引数据和缓存
│   ├── gt_index.json                     # 评分/评论聚合索引
│   ├── type_index.json                   # POI类型索引
│   ├── spatial_index.json                # 500m网格空间索引
│   ├── poi_embeddings.npy                # 语义向量
│   ├── poi_embedding_ids.json            # 向量ID映射
│   ├── poi_knn_cache.json                # KNN距离缓存（默认只读）
│   └── user_memory_profiles.json         # 运行时长期轻画像（自动生成）
├── web/                         # Web前端
│   ├── index.html
│   ├── styles.css
│   └── app.js
├── llm_clients.py               # API客户端
├── config.py                    # 配置与.env加载
├── semantic_search.py           # 语义检索
├── ugc_type_profiles.py         # 类型配置与评分特征
├── generate_road_network.py     # 路网模拟生成
├── road_network.py              # Dijkstra路径计算
├── generate_business_hours.py   # 营业时间生成
├── route_planner_v3.py          # 路线规划引擎
├── interaction_intelligence.py  # 记忆/多人对话/语义需求匹配
├── app_service.py               # 应用服务入口
├── web_app.py                   # Web服务入口
├── _test_iter.py                # smoke test
├── _test_multi.py               # 多场景测试
├── wuhou_jinjiang_pois.json     # 47,045 POI
├── ugc_groundtruth_v4_xl.json   # 775万评论（1.97GB）
├── chengdu_road_network.json    # 291,460边
├── poi_business_hours.json      # 营业时间
├── .env.example                 # 环境变量模板
├── REQUIREMENTS.md              # 需求文档（三种模式定义）
├── DATA.md                      # 数据文档（规模/质量/规则）
└── AGENTS.md                    # 本文件（架构/决策/实现）
```

---

## 7. 环境要求

### 7.1 当前预研环境
```
Python 3.7+
依赖：numpy
编码：UTF-8（Windows终端需 chcp 65001）
内存：4GB+（加载UGC数据时峰值500MB，已优化）
磁盘：3GB+（生成数据2GB + 原始Excel 1.5GB）
```

### 7.2 未来全国生产环境
```
Python 3.10+ / Go（高并发路径计算）
依赖：+ redis, + kafka（异步队列）
内存：16GB+（单城市2-4GB，支持多城市并发）
磁盘：SSD 100GB+（多城市KNN缓存）
网络：高德/百度API密钥，美团/点评商务接口
部署：K8s + 城市分片Pod + Redis Cluster
```

---

## 8. API配置

```bash
# .env 文件
HOST=127.0.0.1
PORT=8000
SERVER_VERSION=3.3.0
MAX_REQUEST_BYTES=65536
ENABLE_CORS=1
WARMUP_ON_START=0
MIMO_API_KEY=
MINIMAX_API_KEY=
GLM_API_KEY=
ENABLE_LLM_CANDIDATE_REVIEW=1
LLM_REVIEW_CANDIDATE_TOP_N=12
LLM_REVIEW_BONUS=1.2
PERSIST_KNN_CACHE=0
```

`config.py` 支持无前缀变量，并兼容旧版带前缀变量；LLM 客户端当前使用 `/chat/completions` 兼容协议。

本地服务入口为 `run_server.py`。推荐用 `python run_server.py --warmup` 启动；`/api/health` 检查进程状态，`/api/ready` 检查本地数据资产和仓库加载状态。

---

## 9. 下一步迭代

1. **新店发现**：接入POI开业时间字段，实现居民模式新店加成
2. **高峰规避**：接入排队数据，实现居民模式高峰降权
3. **交互智能校准**：抽样校验 `NeedInferer` / `PoiMatcher` 的标签准确率，补充更多UGC关键词规则
4. **A/B测试**：三种模式生成路线对比，收集用户偏好反馈
5. **真实API替换**：按统一 POI 适配器接口实现 `HttpApiClient`
