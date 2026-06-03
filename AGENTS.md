# 框架文档

## 1. 系统架构

### 1.1 当前架构（成都武侯+锦江预研阶段）

```
用户输入 → 意图解析 → API客户端 → 候选筛选 → 评分排序 → 路线构建 → 时间轴输出
                                ↓
                        MockApiClient（读取本地JSON）
                                ↓
                    POI / GT评分 / UGC / 路网 / 营业时间
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
1. **API层**（`mock_api/`）：接口对标高德/美团，当前读本地JSON，未来换HTTP调用，规划引擎零改动
2. **规划层**（`route_planner_v3.py`）：纯算法，不感知数据来源
3. **缓存层**（`poi_knn_graph.py` + `spatial_index`）：加速重复查询，全国推广时迁移到Redis

**关键设计决策：城市分片**。当前仅加载成都两区数据，但代码层面已预留 `city` 参数和分片接口，未来接入全国时只需替换数据源，核心算法（KNN缓存、贪心规划、模式权重）无需改动。

---

## 2. 模块清单

| 模块 | 文件 | 职责 |
|------|------|------|
| API接入 | `llm_clients.py` | 女娲平台多模型调用（OpenAI/Anthropic协议） |
| POI数据 | `poi_loader.py` | 加载47,045 POI，名称清洗，类型推断 |
| UGC引擎 | `ugc_v4_xl_fast.py` | 775万评论生成，36类型差异化配置 |
| GT评分 | `ugc_type_profiles.py` | 类型维度定义、评分计算 |
| 路网 | `road_network.py` | Dijkstra最短路径 + LRU缓存 |
| 路网生成 | `generate_road_network.py` | 从POI坐标模拟路网 |
| 营业数据 | `generate_business_hours.py` | 按类型生成营业时间 |
| 路线规划 | `route_planner_v3.py` | 主规划引擎（v3集成版） |
| 应用服务 | `app_service.py` | 主应用入口 |

---

## 3. 路线规划引擎（v3）

### 3.1 入口函数
```python
build_plan_v3(center_lat, center_lng, radius_m=3000, time_budget=240,
              mode="compact", travel_mode="walk", user_tags=None,
              user_mode="tourist",  # 三种模式: tourist/business/resident
              poi_data=None, gt_data=None, road_network=None, bh_data=None)
```

### 3.2 评分公式
```python
score = base_score + diversity_bonus - distance_penalty

base_score = gt_overall + tag_match_bonus
tag_match_bonus = 5.0 if POI类型 in user_tags else 0.0
diversity_bonus = 20.0 if 该类型尚未在路线中出现 else 0.0
distance_penalty = min(travel_time_min / 10, 20)  # 强化距离惩罚
```

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
- ⚠️ GT均值3.41（低于v2的4.38，多样性牺牲部分评分）
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

**绝对禁区**：手机号、用户ID、跨会话历史、位置轨迹、消费记录、社交关系。详见 `PRIVACY.md`。

### 5.1 模拟数据 vs 真实数据：预研策略

当前处于**预研阶段**，所有数据为模拟生成，目的是验证算法架构。未来全国推广时逐项替换为真实API：

| 数据层 | 当前（预研） | 未来（全国推广） | 替换成本 |
|--------|------------|----------------|---------|
| POI本体 | 高德Excel清洗（47k） | 高德/百度POI Search API | 低 |
| UGC评论 | 规则生成7.75M条 | 美团/点评/小红书真实评论 | 中（需商务合作） |
| GT评分 | 规则生成overall | 平台真实评分 | 低 |
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
├── output/                      # 生成数据
│   ├── wuhou_jinjiang_pois.json          # 47,045 POI
│   ├── ugc_groundtruth_v4_xl.json        # 775万评论（1.97GB）
│   ├── chengdu_road_network.json         # 291,460边
│   └── poi_business_hours.json           # 营业时间
├── web/                         # Web前端（待建）
├── tests/                       # 单元测试
├── llm_clients.py               # API客户端
├── poi_loader.py                # POI加载与类型推断
├── ugc_type_profiles.py         # 类型配置与GT评分
├── ugc_v4_xl_fast.py            # UGC评论生成器
├── generate_road_network.py     # 路网模拟生成
├── road_network.py              # Dijkstra路径计算
├── generate_business_hours.py   # 营业时间生成
├── route_planner_v3.py          # 路线规划引擎
├── app_service.py               # 应用服务入口
├── main.py                      # CLI入口
├── .env.example                 # 环境变量模板
├── REQUIREMENTS.md              # 需求文档（三种模式定义）
├── DATA.md                      # 数据文档（规模/质量/规则）
└── AGENTS.md                    # 本文件（架构/决策/实现）
```

---

## 7. 环境要求

### 7.1 当前预研环境
```
Python 3.10+
依赖：pandas, numpy, openpyxl, python-dotenv
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
NWV_API_KEY=ak-a441b4719add46ae930f0246782c22d0
NWV_BASE_URL=https://api.example.com/v1  # 女娲平台地址
NWV_MODEL=qwen3.6-plus                    # 默认模型
```

支持协议：
- OpenAI: `/chat/completions`
- Anthropic: `/messages`（`x-api-key`头，thinking+text blocks）

---

## 9. 下一步迭代

1. **模式引擎**：在 `route_planner_v3.py` 中接入 `user_mode` 参数
2. **单段约束**：按模式动态设置 `max_travel_min`（出差15min/游客30min/居民25min）
3. **新店发现**：接入POI开业时间字段，实现居民模式新店加成
4. **高峰规避**：接入排队数据，实现居民模式高峰降权
5. **前端展示**：Web界面支持三种模式切换
6. **A/B测试**：三种模式生成路线对比，收集用户偏好反馈
