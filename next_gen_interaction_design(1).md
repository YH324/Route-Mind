# 智能路线规划系统 — 下一代交互能力方案文档

> 版本：v1.0  
> 日期：2026-05-30  
> 状态：三个需求方案已完成

---

## 文档概述

本文档定义路线规划系统从"工具型查询"升级为"智能旅行助手"所需的三大核心能力：

1. **长期记忆**：让系统记得住用户是谁、喜欢什么、刚才聊了什么
2. **多人对话理解**：从群聊/讨论中融合多方意图、解决冲突
3. **语义需求匹配**：超越关键词字面匹配，理解"清淡""浪漫""亲子"等隐含需求

---

## 一、需求一：和用户交互中的长期记忆

### 1.1 问题背景

当前系统每次对话独立，存在明显断层：

- 用户说"春熙路附近吃火锅"，5分钟后说"那附近有什么商场" → 系统问"哪附近？"
- 用户连续三次搜火锅 → 第四次仍然从0开始推荐，不优先推用户点过的品牌
- 用户说过"不吃辣" → 下次推荐火锅时仍可能推九宫格牛油锅

### 1.2 目标

构建三层记忆体系，实现**连续性**与**个性化**：

| 层级 | 时效 | 作用 |
|-----|------|------|
| 轮次记忆 | 当前请求 | 继承上轮的地点、意图、已推荐列表 |
| 会话记忆 | 2小时内 | 同一次聊天中累加偏好、锁定区域 |
| 长期记忆 | 永久 | 用户画像、历史行为、品牌偏好 |

### 1.3 技术架构

```
User Request
    │
    ▼
┌─────────────────────────────────────────┐
│  Memory Fusion Layer（记忆融合层）        │
│  - 读取长期画像 + 会话上下文 + 上轮状态    │
│  - 注入到 constraints 中                 │
└─────────────────────────────────────────┘
    │
    ▼
build_plan_v3(目标, 约束+记忆, ...)
    │
    ▼
┌─────────────────────────────────────────┐
│  Memory Update Layer（记忆更新层）        │
│  - 记录本轮推荐结果                       │
│  - 记录用户点击/忽略/否定                 │
│  - 持久化高频偏好                         │
└─────────────────────────────────────────┘
```

### 1.4 记忆存储设计

#### 数据结构

```json
{
  "user_id": "uuid",
  "profile": {
    "preferred_tags": {"火锅": 0.85, "茶馆": 0.6},
    "avoid_tags": ["烧烤", "KTV"],
    "dietary": ["不吃辣"],
    "budget_hint": "中等",
    "mobility": "步行偏好"
  },
  "locations": {
    "home": {"lng": 104.05, "lat": 30.65},
    "office": {"lng": 104.08, "lat": 30.67},
    "frequent_areas": [
      {"name": "春熙路", "lng": 104.082, "lat": 30.657, "visits": 12}
    ]
  },
  "session": {
    "center": {"lng": 104.082, "lat": 30.657},
    "locked_radius": 2000,
    "mentioned_types": ["火锅", "商场"],
    "selected_pois": ["poi_123"],
    "negative_pois": ["poi_456"]
  },
  "last_interaction": {
    "intent_type": "single_poi",
    "top_recommendations": ["poi_123", "poi_124"]
  }
}
```

#### 上下文继承规则

| 用户表达 | 记忆触发 | 系统行为 |
|---------|---------|---------|
| "那附近""刚才""还有" | 继承上轮 `center` | 自动锁定同一区域 |
| "像上次那样的" | 读取 `session_history` | 复刻上次路线的类型组合 |
 | "有没有清淡的" | 读取 `dietary` | 已知晓不吃辣，直接过滤 |
| "换个口味" | 读取 `preferred_tags` | 从高频偏好中换子类型 |

### 1.5 关键场景示例

**场景：连续对话**
```
用户：春熙路附近吃火锅
系统：推荐5个火锅店（记录用户点击"无二泰式火锅"）

用户：那附近逛逛
系统：→ 读取 session.center = 春熙路
     → 推荐春熙路商场（WIFC、茂业等）
     
用户：有没有安静点的
系统：→ 读取长期记忆：用户历史评价中多次提到"安静"+
     → 过滤掉评分中"嘈杂"负面标签的店铺
     → 推荐有包间/环境标签的商场内书店、茶馆
```

### 1.6 实现路径

**Phase 1（1周）**：Session级上下文
- `build_plan_v3` 增加 `session_id` 参数
- Redis 存储 `last_center`、`mentioned_types`
- 实现指代词解析（"那附近/刚才"）

**Phase 2（2周）**：用户画像持久化
- SQLite 表：`user_profiles`、`user_sessions`、`user_feedback`
- 偏好自动提取（点击=+0.1，忽略=-0.05，否定=-0.2）
- `score_poi_v3` 接入个性化权重

**Phase 3（1周）**：记忆遗忘与更新
- 低频偏好衰减（30天未提及×0.9）
- 负面反馈强过滤（否定类型60天内权重归零）
- 地理位置漂移自动检测

---

## 二、需求二：从用户多人对话中推断用户需求

### 2.1 问题背景

真实场景中用户常以群聊/讨论形式表达需求：

```
小明：我想吃火锅
小红：吃完想去逛街
小明：春熙路附近吧
小红：不要太贵，人均100以内
```

当前系统只解析最后一句话（"人均100以内"），丢失前序信息。

### 2.2 目标

- **意图聚合**：将多方碎片化输入合并为完整约束
- **冲突检测**：识别矛盾需求（如"吃火锅"vs"不吃辣"）
- **智能澄清**：无法推断时主动追问，而非盲目执行

### 2.3 核心模块：DialogueStateTracker

#### 状态机设计

```python
class DialogueStateTracker:
    def __init__(self):
        self.slots = {}       # 已确认槽位
        self.pending = []     # 待澄清槽位
        self.conflicts = []   # 冲突列表
        self.speaker_bias = {}  # 说话人权重（发起者权重高）
    
    def update(self, speaker, text, intent):
        # 提取本轮槽位
        new_slots = extract_slots(text, intent)
        
        for k, v in new_slots.items():
            if k in self.slots:
                old = self.slots[k]
                if is_conflict(old["value"], v):
                    self.conflicts.append({
                        "slot": k,
                        "a": old, "b": {"speaker": speaker, "value": v}
                    })
                else:
                    # 同意图强化
                    self.slots[k]["value"] = merge(old["value"], v)
                    self.slots[k]["weight"] += 1
            else:
                self.slots[k] = {"speaker": speaker, "value": v, "weight": 1}
        
        self._infer_missing()
```

#### 槽位与冲突定义

| 槽位 | 示例 | 冲突规则 | 合并策略 |
|-----|------|---------|---------|
| food | 火锅 | 与"不吃辣"冲突 | 推清淡锅型 |
| activity | 逛街 | 不冲突 | 追加到 sequence |
| location | 春熙路 | 多地点冲突 | 取中间点/多数决 |
| budget | 便宜 | 与"高档"冲突 | 推性价比/澄清 |
| time | 下午 | 不冲突 | 取后提及 |
| sequence | 先吃后逛 | 与"先逛后吃"冲突 | 需澄清 |

### 2.4 冲突澄清示例

```
对话：
  A：想吃火锅
  B：我不吃辣

系统推断：
  slots: {food: "火锅", dietary: "不吃辣"}
  conflicts: [{slot: "food", reason: "火锅通常辣"}]

系统回应（不直接执行）：
  "有人想吃火锅，有人不吃辣。推荐菌汤锅/番茄锅/潮汕牛肉火锅可以吗？"
```

### 2.5 多人意图聚合输出

```
输入对话：
  小明：春熙路附近吃火锅
  小红：吃完想逛街
  小明：不要太贵

聚合后约束：
{
  "intent_type": "simple_route",
  "preferred_tags": ["餐饮", "火锅", "购物"],
  "sequence": ["火锅", "商场"],
  "location": "春熙路",
  "budget": "经济",
  "center_lng": 104.082,
  "center_lat": 30.657
}

生成路线：火锅(平价) → 商场
```

### 2.6 实现路径

**Phase 1（2周）**：多轮槽位提取
- 前端传入 `speaker_id`
- LLM prompt 改造为对话数组格式
- 槽位提取规则库

**Phase 2（2周）**：冲突检测与澄清
- 冲突规则库建设
- 澄清话术模板
- 状态机持久化（Redis）

**Phase 3（1周）**：对接路线引擎
- `DialogueStateTracker.get_combined_goal()` → `parse_goal()`
- 多人偏好权重融合（发起者权重1.0，附和者0.7）

---

## 三、需求三：从推断需求中尝试匹配相关的店铺

### 3.1 问题背景

当前系统基于**字面类型匹配**（如用户说"火锅"→匹配 rt="火锅"），无法理解隐含需求：

| 用户真实需求 | 当前系统行为 | 期望行为 |
|------------|-----------|---------|
| "想吃清淡的" | 无法理解，fallback到默认 | 推荐菌汤火锅、粤菜、轻食 |
| "适合约会" | 可能推荐任意类型 | 推荐景观餐厅、rooftop bar、私房菜 |
| "带孩子玩" | 只匹配 rt="游乐园" | 推荐亲子餐厅、科普馆、有儿童区的公园 |
| "有特色的" | 无差别推荐 | 推荐老字号、网红店、非遗体验 |
| "能坐一下午" | 无法理解 | 推荐有插座/WiFi/舒适的咖啡馆、茶馆 |
| "商务宴请" | 可能推路边摊 | 推荐有包间、档次中上、服务专业的餐厅 |
| "拍照好看" | 无法理解 | 推荐装修独特、有打卡点、光线好的店铺 |

问题在于：用户表达的是**场景/感受/约束**，而非**具体类型**。

### 3.2 目标

构建**语义需求推断 + 多维度店铺匹配**能力：

1. **需求语义层**：将自然语言转化为结构化需求标签（非类型标签）
2. **店铺属性层**：为每个POI打上语义属性标签（环境、氛围、适合人群等）
3. **匹配引擎**：计算需求标签与店铺属性的匹配度

### 3.3 架构设计

```
用户输入
  │
  ▼
┌─────────────────────────────┐
│ 需求语义推断层 (NeedInferer)  │
│ - 提取显式类型（火锅/茶馆）   │
│ - 推断隐式需求（浪漫/亲子/安静）│
│ - 输出：结构化需求向量        │
└─────────────────────────────┘
  │
  ▼
┌─────────────────────────────┐
│ 店铺属性匹配层 (PoiMatcher)   │
│ - 读取POI语义属性标签         │
│ - 计算需求-属性匹配分         │
│ - 结合原始GT质量分重排序      │
└─────────────────────────────┘
  │
  ▼
推荐结果（类型可能不字面匹配，但场景高度契合）
```

### 3.4 需求语义标签体系

#### 隐式需求标签（从用户表达推断）

| 用户表达 | 推断需求标签 | 匹配店铺属性 |
|---------|-----------|-----------|
| "清淡的" | `diet:light`, `spicy:no` | 菜系=粤菜/江浙菜/菌汤锅 |
| "适合约会" | `scene:romantic`, `noise:quiet` | 景观位、烛光、评分高环境 |
| "带孩子" | `audience:family`, `safety:high` | 儿童椅、无台阶、有亲子设施 |
| "有特色的" | `feature:unique`, `feature:heritage` | 老字号、非遗、网红设计 |
| "能坐一下午" | `comfort:long_stay`, `facility:wifi` | 座位宽敞、有插座、不赶客 |
| "商务宴请" | `scene:business`, `privacy:high` | 包间、档次中上、服务专业 |
| "拍照好看" | `feature:photogenic`, `scene:aesthetic` | 装修独特、有打卡点、光线好 |
| "人均100" | `budget:100` | 人均消费区间匹配 |

#### 店铺语义属性（为每个POI打标）

```json
{
  "poi_id": "poi_123",
  "name": "某火锅店",
  "type": "火锅",
  "semantic_tags": {
    "scene": ["朋友聚餐", "夜宵"],
    "scene_not": ["商务宴请", "约会"],
    "noise_level": "loud",
    "diet_feature": ["重辣", "油重"],
    "diet_not": ["清淡", "素食"],
    "audience": ["年轻人", "朋友"],
    "audience_not": ["老人", "婴幼儿"],
    "comfort": ["快速翻台"],
    "comfort_not": ["久坐", "办公"],
    "price_per_person": 120,
    "feature": ["网红", "排队长"],
    "environment": ["工业风", "热闹"]
  }
}
```

### 3.5 匹配算法

#### 需求向量 → 属性向量匹配

```python
def match_score(poi_semantic, user_needs):
    """
    计算POI与用户需求的匹配度
    """
    score = 0.0
    
    # 正向匹配（需求标签在POI属性中）
    for need in user_needs["must_have"]:
        if need in poi_semantic.get("scene", []) or \
           need in poi_semantic.get("feature", []) or \
           need in poi_semantic.get("diet_feature", []):
            score += 2.0
        else:
            score -= 1.0  # 硬性需求未满足，大幅扣分
    
    # 负向过滤（需求与POI排斥属性冲突）
    for avoid in user_needs["must_not"]:
        if avoid in poi_semantic.get("scene_not", []) or \
           avoid in poi_semantic.get("diet_not", []) or \
           avoid in poi_semantic.get("audience_not", []):
            score -= 3.0  # 硬性排斥，直接排除
    
    # 预算匹配
    if "budget" in user_needs:
        target = user_needs["budget"]
        actual = poi_semantic.get("price_per_person", 100)
        if actual <= target * 1.2:
            score += 1.0
        elif actual > target * 1.5:
            score -= 2.0
    
    # 人群匹配
    for audience in user_needs.get("audience", []):
        if audience in poi_semantic.get("audience", []):
            score += 1.5
        elif audience in poi_semantic.get("audience_not", []):
            score -= 2.0
    
    return score
```

#### 与现有评分体系融合

```python
def score_poi_v3(poi, gt, constraints, route_types, network, type_index, semantic_tags=None):
    base_score = gt.get("overall", 3.0)
    
    # 原有逻辑：类型匹配、距离、多样性...
    ...
    
    # 新增：语义需求匹配
    if semantic_tags and constraints.get("user_needs"):
        semantic_score = match_score(semantic_tags, constraints["user_needs"])
        base_score += semantic_score
    
    return base_score
```

### 3.6 典型场景：语义匹配实战

#### 场景A："想吃清淡的"

```
用户输入："春熙路附近想吃清淡的"

推断过程：
  → 地点：春熙路
  → 需求标签：{diet_feature: "清淡", diet_not: "辣", diet_not: "油腻"}
  
候选池：
  1. 无二泰式火锅 (rt=火锅) 
     → semantic: {diet_feature: ["酸辣"], diet_not: ["清淡"]} → score=-3 ❌
  2. 潮汕牛肉火锅 (rt=火锅)
     → semantic: {diet_feature: ["清淡", "鲜甜"], scene: ["家庭聚餐"]} → score=+3 ✅
  3. 粤菜馆 (rt=中餐)
     → semantic: {diet_feature: ["清淡", "精致"], scene: ["商务宴请"]} → score=+2 ✅
  4. 轻食沙拉店 (rt=小吃)
     → semantic: {diet_feature: ["清淡", "健康"], audience: ["健身"]} → score=+2 ✅

输出：潮汕牛肉火锅、粤菜馆、轻食沙拉店
（注意：不字面匹配"火锅"关键词，但匹配"清淡"语义）
```

#### 场景B："适合约会的地方"

```
用户输入："适合约会的地方"

推断过程：
  → 需求标签：{
      scene: ["浪漫", "安静"],
      noise_level: "quiet",
      privacy: "high",
      feature: ["景观", "氛围"]
    }

候选池：
  1. 班花麻辣烫 (rt=火锅, 评分高)
     → semantic: {scene_not: ["约会"], noise_level: "loud"} → score=-5 ❌
  2. 屋顶花园餐厅 (rt=外国菜)
     → semantic: {scene: ["约会", "浪漫"], feature: ["景观", "夜景"]} → score=+6 ✅
  3. 私人影院 (rt=电影院)
     → semantic: {scene: ["约会", "私密"], privacy: "high"} → score=+5 ✅
  4. 江景茶馆 (rt=茶馆)
     → semantic: {scene: ["约会", "安静"], feature: ["景观"]} → score=+5 ✅

输出：屋顶花园餐厅、私人影院、江景茶馆
（注意：跨类型推荐，不局限于某一具体类型）
```

#### 场景C："带孩子玩一天"

```
用户输入："带孩子玩一天，春熙路附近"

推断过程：
  → 需求标签：{
      audience: ["家庭", "儿童"],
      safety: "high",
      comfort: ["休息区", "卫生间便利"],
      scene: ["亲子", "教育", "互动"]
    }

路线规划：
  上午：成都博物馆/四川科技馆 (景点，有儿童互动区)
  中午：亲子餐厅 (中餐，有儿童餐椅、游乐角)
  下午：有儿童区的公园/室内乐园
  
（注意：不硬推"游乐园"，而是推"适合儿童的科普场馆+亲子餐厅"组合）
```

### 3.7 语义标签数据来源

| 来源 | 方式 | 可信度 |
|-----|------|-------|
| UGC评论分析 | NLP提取关键词（"环境安静""适合拍照"） | 高 |
| 商家自填标签 | 高德/美团POI的 tag 字段 | 中 |
| 图片识别 | 门店外观/内景识别（网红风/老字号等） | 中 |
| 运营人工标注 | 对头部POI人工打标 | 极高 |
| 用户行为反推 | 点击"约会"query的用户最终去了哪些店 | 高 |

### 3.8 实现路径

**Phase 1（2周）**：语义标签体系建立
- 定义需求标签字典（50+标签）
- 定义店铺属性Schema
- 从现有UGC评论中批量提取标签（NLP规则+关键词匹配）

**Phase 2（2周）**：推断引擎开发
- `NeedInferer`：从用户输入提取/推断需求标签
- `PoiMatcher`：需求标签与POI属性的匹配计算
- 与 `build_plan_v3` 集成（在 `score_poi_v3` 中融入语义分）

**Phase 3（2周）**：数据建设与冷启动
- UGC评论批量打标（可用LLM辅助：输入评论→输出标签列表）
- 人工抽检校准（抽样100条验证准确率）
- A/B测试：语义匹配 vs 字面匹配的转化率对比

---

## 四、三个需求的协同关系

```
┌──────────────────────────────────────────────┐
│              用户输入（单轮/多轮/多人）           │
└──────────────────────────────────────────────┘
                    │
    ┌───────────────┼───────────────┐
    ▼               ▼               ▼
┌─────────┐   ┌─────────────┐   ┌───────────┐
│ 长期记忆 │   │ 多人对话理解 │   │ 语义推断   │
│ (需求一) │   │  (需求二)   │   │ (需求三)   │
└─────────┘   └─────────────┘   └───────────┘
    │               │               │
    └───────────────┼───────────────┘
                    ▼
        ┌─────────────────────┐
        │   融合后的约束向量    │
        │ {location, type,     │
        │  scene, budget,      │
        │  audience, ...}      │
        └─────────────────────┘
                    │
                    ▼
        ┌─────────────────────┐
        │   build_plan_v3     │
        │   (语义匹配+路线规划) │
        └─────────────────────┘
                    │
                    ▼
              个性化推荐结果
```

**协同示例**：
```
对话：
  [长期记忆] 用户：不吃辣、常去春熙路、上周刚去过武侯祠
  [多人对话] 小明：想吃火锅；小红：我要清淡的；小明：春熙路吧
  [语义推断] "清淡的火锅"→菌汤/番茄/潮汕牛肉；"约会"隐含（对话双方为情侣账号）

融合约束：
  location: 春熙路
  type: 火锅
  diet: 清淡、不辣
  scene: 约会（隐含）
  avoid: 用户上周去过的不推

输出：春熙路附近的潮汕牛肉火锅（环境好、不辣、适合约会）
```

---

## 五、排期与里程碑

| 阶段 | 周期 | 交付物 | 优先级 |
|-----|------|-------|-------|
| **需求一 Phase 1** | 1周 | Session上下文继承 | P0 |
| **需求一 Phase 2** | 2周 | 用户画像持久化 | P0 |
| **需求三 Phase 1** | 2周 | 语义标签体系+UGC批量打标 | P0 |
| **需求三 Phase 2** | 2周 | NeedInferer + PoiMatcher 上线 | P0 |
| **需求一 Phase 3** | 1周 | 记忆遗忘与更新机制 | P1 |
| **需求二 Phase 1** | 2周 | 多轮槽位提取 | P1 |
| **需求二 Phase 2** | 2周 | 冲突检测与澄清 | P1 |
| **需求二 Phase 3** | 1周 | 对接路线引擎 | P1 |
| **需求三 Phase 3** | 2周 | 数据校准+A/B测试 | P2 |

**建议启动顺序**：需求一（记忆）→ 需求三（语义匹配）→ 需求二（多人对话）

原因：语义匹配可直接提升单用户体验；记忆是多人对话的基础；多人对话复杂度最高。

---

*文档完成。如需补充接口定义、数据表设计、LLM Prompt模板等细节，请告知。*
