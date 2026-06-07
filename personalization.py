#!/usr/bin/env python3
"""
轻个性化引擎

设计原则：
1. 所有信息为匿名、聚合、会话隔离，不关联个人身份
2. 会话结束后所有上下文自动销毁
3. 每个个性化信号仅作为评分微调（±0.3~1.0分），不决定最终结果

包含模块：
- SessionContext:   会话内上下文记忆（排除/偏好/点击/连贯性）
- TimeAwareScorer:  时间感知路由（早餐/下午茶/夜宵）
- WeatherAwareScorer: 天气感知推荐（雨天/高温/AQI）
- CrowdAwareScorer: 实时人流规避（排队惩罚）
- AggregateSignal:  匿名群体偏好信号
"""
from datetime import datetime


# ==================== 1. 会话上下文记忆 ====================

class SessionContext:
    """
    会话级上下文，仅存在于当前HTTP会话/对话中。
    会话结束即销毁，不写入数据库，不进入长期日志。
    """

    def __init__(self):
        self.queries = []           # 本次会话的所有query文本
        self.excluded_pois = set()  # 用户明确排除的POI ID
        self.excluded_types = set() # 用户明确排除的类型（如"不要火锅"）
        self.clicked_pois = set()   # 用户点击/展开详情的POI ID
        self.preferred_types = []   # 用户多次提及的偏好类型
        self.radius_adjustment = 0  # 用户反馈"太远/太近"后的半径调整（米）
        self.last_route_end = None  # 上一条路线的终点POI（用于连贯性）
        self.last_route_pois = set() # 上一条路线中的所有POI
        self.feedback_scores = {}   # 用户对POI的显式反馈（+1喜欢/-1不喜欢）

    def add_query(self, goal_text):
        """记录用户query，提取排除指令"""
        self.queries.append(goal_text)
        goal_lower = goal_text.lower()

        # 提取排除指令："不要火锅"、"除了火锅"、"不想吃火锅"
        EXCLUDE_PATTERNS = [
            (r"不要(.*?)\b", 1),
            (r"不想吃(.*?)(?:\b|$)", 1),
            (r"除了(.*?)\b", 1),
            (r"排除(.*?)(?:\b|$)", 1),
        ]
        import re
        for pattern, group in EXCLUDE_PATTERNS:
            matches = re.findall(pattern, goal_lower)
            for m in matches:
                m = m.strip()
                if m:
                    self.excluded_types.add(m)

        # 提取偏好类型：重复提及的类型
        TYPE_KEYWORDS = {
            "火锅": "火锅", "烧烤": "烧烤", "小吃": "小吃", "中餐": "中餐",
            "西餐": "外国菜", "日料": "外国菜", "咖啡": "饮品", "奶茶": "饮品",
            "公园": "公园", "景点": "景点", "商场": "商场", "酒吧": "酒吧",
            "茶馆": "茶馆", "甜品": "甜品", "面包": "甜品",
        }
        for kw, typ in TYPE_KEYWORDS.items():
            if kw in goal_lower:
                self.preferred_types.append(typ)

    def exclude_poi(self, poi_id):
        """用户明确排除某个POI"""
        self.excluded_pois.add(poi_id)

    def click_poi(self, poi_id):
        """用户点击/查看了某个POI详情"""
        self.clicked_pois.add(poi_id)

    def feedback(self, poi_id, score):
        """用户显式反馈（+1喜欢，-1不喜欢，0无感）"""
        self.feedback_scores[poi_id] = score

    def adjust_radius(self, delta_meters):
        """用户说"太远了"或"太近了"，调整搜索半径"""
        self.radius_adjustment += delta_meters

    def set_last_route(self, route_pois):
        """记录上一条路线，用于连贯性"""
        if route_pois:
            self.last_route_end = route_pois[-1]
            self.last_route_pois = set(p["poi_id"] for p in route_pois)

    def apply_to_constraints(self, constraints):
        """将会话上下文应用到规划约束中"""
        # 半径调整
        if self.radius_adjustment != 0:
            constraints["radius"] = max(500, constraints.get("radius", 3000) + self.radius_adjustment)

        # 排除类型写入avoid_tags
        if self.excluded_types:
            constraints["avoid_tags"] = list(self.excluded_types)

        return constraints

    def score_adjustment(self, poi, poi_type):
        """返回该POI基于会话上下文的评分调整值"""
        adjustment = 0.0
        pid = poi["poi_id"]

        # 排除的POI：直接排除（返回极大负分）
        if pid in self.excluded_pois or pid in self.last_route_pois:
            return -999

        # 排除的类型
        if poi_type in self.excluded_types:
            return -999

        # 点击过的同类型：+0.5
        if poi_type in self.preferred_types:
            adjustment += 0.5

        # 用户显式反馈
        if pid in self.feedback_scores:
            adjustment += self.feedback_scores[pid] * 1.0

        # 连贯性：以上次终点为起点时，附近POI加分
        if self.last_route_end:
            from math import radians, sin, cos, sqrt, atan2
            R = 6371000
            dlon = radians(poi["longitude"] - self.last_route_end["longitude"])
            dlat = radians(poi["latitude"] - self.last_route_end["latitude"])
            a = sin(dlat/2)**2 + cos(radians(self.last_route_end["latitude"])) * cos(radians(poi["latitude"])) * sin(dlon/2)**2
            dist = 2 * R * atan2(sqrt(a), sqrt(1-a))
            if dist < 500:
                adjustment += 0.3  # 500m内的POI加分

        return adjustment


# ==================== 2. 时间感知路由 ====================

class TimeAwareScorer:
    """
    基于当前时间的POI推荐调整。
    信息来源：系统时间（公开信息），零隐私风险。
    """

    TIME_PROFILES = {
        "morning":    {"hours": (6, 10),  "name": "早晨",
                       "boost": {"早餐": 2.0, "饮品": 1.5, "咖啡": 1.5, "公园": 1.0, "茶馆": 0.5},
                       "avoid": {"酒吧": -999, "烧烤": -999, "KTV": -999, "夜宵": -999}},
        "lunch":      {"hours": (11, 14), "name": "午餐",
                       "boost": {"中餐": 1.5, "快餐": 1.5, "小吃": 1.5, "外国菜": 1.0, "火锅": 0.5},
                       "avoid": {"酒吧": -999, "早餐": -2.0}},
        "afternoon":  {"hours": (14, 17), "name": "下午",
                       "boost": {"甜品": 2.0, "饮品": 1.5, "茶馆": 1.5, "咖啡": 1.5, "商场": 1.0, "公园": 0.5},
                       "avoid": {"早餐": -999}},
        "dinner":     {"hours": (18, 21), "name": "晚餐",
                       "boost": {"火锅": 2.0, "烧烤": 1.5, "中餐": 1.5, "外国菜": 1.0, "小吃": 0.5},
                       "avoid": {"早餐": -999, "咖啡": -1.0}},
        "night":      {"hours": (21, 24), "name": "夜间",
                       "boost": {"烧烤": 2.0, "酒吧": 2.0, "夜宵": 2.0, "KTV": 1.5, "便利店": 0.5},
                       "avoid": {"景点": -999, "公园": -999, "早餐": -999}},
        "late_night": {"hours": (0, 6),   "name": "深夜",
                       "boost": {"便利店": 2.0, "酒吧": 1.5, "夜宵": 1.5},
                       "avoid": {"景点": -999, "公园": -999, "商场": -999, "早餐": -999}},
    }

    def __init__(self, now=None):
        self.now = now or datetime.now()
        self.hour = self.now.hour
        self.profile = self._get_profile()

    def _get_profile(self):
        for name, prof in self.TIME_PROFILES.items():
            start, end = prof["hours"]
            if start <= self.hour < end:
                return prof
        return self.TIME_PROFILES["afternoon"]  # fallback

    def get_time_label(self):
        return self.profile["name"]

    def score_adjustment(self, poi_type):
        """返回该类型在当前时段的评分调整"""
        boost = self.profile.get("boost", {})
        avoid = self.profile.get("avoid", {})
        return boost.get(poi_type, 0) + avoid.get(poi_type, 0)

    def get_recommendation_hint(self):
        """给用户的时段提示语"""
        hints = {
            "morning": "早上好，推荐早餐和晨练场所",
            "lunch": "午餐时间，推荐各类正餐",
            "afternoon": "下午时光，推荐下午茶和休闲",
            "dinner": "晚餐时间，推荐火锅和烧烤",
            "night": "夜生活开始，推荐夜宵和酒吧",
            "late_night": "深夜了，推荐24小时营业的场所",
        }
        return hints.get(self.get_time_label(), "")


# ==================== 3. 天气感知推荐 ====================

class WeatherAwareScorer:
    """
    基于天气状况的POI推荐调整。
    信息来源：公开天气API（如和风天气），零隐私风险。
    未接入外部天气信号时不参与评分，避免用推测天气影响推荐。
    """

    WEATHER_PROFILES = {
        "sunny":       {"boost": {"景点": 1.5, "公园": 1.5, "饮品": 0.5, "冰品": 1.0},
                        "avoid": {},
                        "hint": "天气晴朗，适合户外活动"},
        "sunny_hot":   {"boost": {"商场": 1.5, "饮品": 2.0, "冰品": 2.0, "茶馆": 1.0, "电影院": 1.0},
                        "avoid": {"景点": -1.0, "公园": -1.0},
                        "hint": "天气炎热，推荐有空调的场所"},
        "cloudy":      {"boost": {"公园": 1.0, "景点": 1.0, "商场": 0.5},
                        "avoid": {},
                        "hint": "多云天气，活动不受限"},
        "rain":        {"boost": {"商场": 2.0, "火锅": 1.5, "茶馆": 1.5, "电影院": 1.5, "甜品": 1.0},
                        "avoid": {"景点": -2.0, "公园": -999},
                        "hint": "下雨了，推荐室内活动"},
        "heavy_rain":  {"boost": {"商场": 2.0, "火锅": 2.0, "电影院": 2.0},
                        "avoid": {"景点": -999, "公园": -999, "步行": -999},
                        "hint": "大雨天，建议地铁直达的室内场所"},
        "snow":        {"boost": {"火锅": 2.0, "商场": 1.5, "温泉": 2.0},
                        "avoid": {"景点": -999, "公园": -999},
                        "hint": "下雪了，推荐温暖的室内"},
        "extreme_hot": {"boost": {"商场": 2.0, "茶馆": 1.5, "饮品": 2.0, "电影院": 1.5},
                        "avoid": {"景点": -999, "公园": -999, "户外": -999},
                        "hint": "高温预警，建议室内活动"},
        "aqi_bad":     {"boost": {"室内": 2.0, "电影院": 1.5, "商场": 1.5, "茶馆": 1.0},
                        "avoid": {"景点": -999, "公园": -999, "户外": -999},
                        "hint": "空气质量较差，建议室内活动"},
    }

    def __init__(self, weather_code=None):
        """
        Args:
            weather_code: 天气代码。None 表示当前请求没有可用天气信号。
        """
        self.weather_code = weather_code
        self.profile = self.WEATHER_PROFILES.get(weather_code, {}) if weather_code else {}

    def score_adjustment(self, poi_type):
        boost = self.profile.get("boost", {})
        avoid = self.profile.get("avoid", {})
        return boost.get(poi_type, 0) + avoid.get(poi_type, 0)

    def get_hint(self):
        return self.profile.get("hint", "")


# ==================== 4. 实时人流规避 ====================

class CrowdAwareScorer:
    """
    基于POI实时人流/排队数据的评分调整。
    信息来源：平台匿名聚合数据（美团排队、高德人流指数）。
    未接入外部人流信号时不参与评分。
    """

    def __init__(self, crowd_data=None):
        """
        Args:
            crowd_data: {poi_id: {"wait_min": 30, "crowd_level": "high"}}
                       None 表示当前请求没有可用人流信号
        """
        self.crowd_data = crowd_data or {}

    def score_adjustment(self, poi_id):
        """排队时间越长的POI扣分越多"""
        crowd = self.crowd_data.get(poi_id)
        if not crowd:
            return 0
        wait = crowd.get("wait_min", 0)
        if wait > 60:
            return -3.0
        elif wait > 30:
            return -1.5
        elif wait > 15:
            return -0.5
        return 0

    def get_wait_time(self, poi_id):
        """获取POI预计排队时间"""
        return self.crowd_data.get(poi_id, {}).get("wait_min", 0)


# ==================== 5. 匿名群体信号 ====================

class AggregateSignal:
    """
    基于大规模匿名统计的偏好信号。
    没有传入聚合统计时不参与评分。
    """

    def __init__(self, area="chunxi", signals=None, is_holiday=False):
        self.area = area
        self.hour = datetime.now().hour
        self.is_weekend = datetime.now().weekday() >= 5
        self.is_holiday = bool(is_holiday)
        self.signals = signals or {}

    def get_signal(self, poi_type):
        """获取该类型在当前场景的群体偏好信号（0~1之间）"""
        signals = []

        # 时段+区域信号
        if self.hour >= 18:
            signals.append(self.signals.get(("weekend" if self.is_weekend else "weekday", "evening", self.area), {}))
        elif self.hour >= 12:
            signals.append(self.signals.get(("weekend" if self.is_weekend else "weekday", "lunch", "any"), {}))
        else:
            signals.append(self.signals.get(("weekend" if self.is_weekend else "weekday", "afternoon", self.area), {}))

        # 节假日信号
        if self.is_holiday:
            signals.append(self.signals.get(("holiday", "any", "any"), {}))

        # 取平均
        if not signals:
            return 0
        total = sum(s.get(poi_type, 0) for s in signals)
        avg = total / len(signals)
        # 映射到评分调整：0.5~0.7 → +0.2, 0.3~0.5 → +0.1, <0.3 → 0
        if avg > 0.6:
            return 0.3
        elif avg > 0.4:
            return 0.15
        return 0


# ==================== 6. 个性化评分聚合器 ====================

class PersonalizationEngine:
    """
    聚合所有轻个性化信号，输出最终评分调整。
    """

    def __init__(self, session=None, weather_code=None, crowd_data=None, area="chunxi",
                 aggregate_signals=None, is_holiday=False):
        self.session = session or SessionContext()
        self.time_scorer = TimeAwareScorer()
        self.weather_scorer = WeatherAwareScorer(weather_code)
        self.crowd_scorer = CrowdAwareScorer(crowd_data)
        self.aggregate = AggregateSignal(area, signals=aggregate_signals, is_holiday=is_holiday)

    def get_context_hints(self):
        """返回给用户的上下午/天气提示"""
        hints = []
        time_hint = self.time_scorer.get_recommendation_hint()
        if time_hint:
            hints.append(time_hint)
        weather_hint = self.weather_scorer.get_hint()
        if weather_hint:
            hints.append(weather_hint)
        return hints

    def score_poi(self, poi, poi_type):
        """
        计算该POI的综合个性化评分调整。
        返回：调整值（可正可负，-999表示排除）
        """
        total = 0.0
        pid = poi["poi_id"]

        # 1. 会话上下文
        s = self.session.score_adjustment(poi, poi_type)
        if s <= -900:
            return -999  # 被明确排除
        total += s

        # 2. 时间感知
        total += self.time_scorer.score_adjustment(poi_type)

        # 3. 天气感知
        total += self.weather_scorer.score_adjustment(poi_type)

        # 4. 人流规避
        total += self.crowd_scorer.score_adjustment(pid)

        # 5. 群体信号
        total += self.aggregate.get_signal(poi_type)

        return total
