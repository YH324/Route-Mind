"""
Next-generation interaction intelligence.

Implements the three capabilities defined in docs/next_gen_interaction_design.md:
- session and long-term memory
- multi-speaker dialogue state tracking
- semantic need inference and POI matching
"""
import json
import os
import re
import threading
import time
import uuid


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
PROFILE_PATH = os.path.join(OUTPUT_DIR, "user_memory_profiles.json")
SESSION_TTL_SECONDS = 2 * 60 * 60
MAX_ID_LENGTH = 80
MAX_FEEDBACK_ITEMS = 30
MAX_DIALOGUE_MESSAGES = 30


LOCATION_ALIASES = {
    "春熙路": {"lng": 104.08099, "lat": 30.65732, "name": "春熙路"},
    "太古里": {"lng": 104.08126, "lat": 30.65335, "name": "太古里"},
    "天府广场": {"lng": 104.06476, "lat": 30.65705, "name": "天府广场"},
    "成都IFS": {"lng": 104.0799, "lat": 30.6557, "name": "成都 IFS"},
    "IFS": {"lng": 104.0799, "lat": 30.6557, "name": "成都 IFS"},
    "锦里": {"lng": 104.0487, "lat": 30.6482, "name": "锦里"},
    "武侯祠": {"lng": 104.0473, "lat": 30.6469, "name": "武侯祠"},
    "九眼桥": {"lng": 104.0832, "lat": 30.6412, "name": "九眼桥"},
    "兰桂坊": {"lng": 104.0846, "lat": 30.6443, "name": "兰桂坊"},
    "望江楼": {"lng": 104.0803, "lat": 30.6224, "name": "望江路"},
    "望江": {"lng": 104.0803, "lat": 30.6224, "name": "望江路"},
}

TYPE_KEYWORDS = {
    "火锅": "火锅", "烧烤": "烧烤", "烤肉": "烧烤", "串串": "火锅",
    "茶馆": "茶馆", "喝茶": "茶馆", "咖啡": "饮品", "奶茶": "饮品",
    "甜品": "甜品", "蛋糕": "甜品", "中餐": "中餐", "川菜": "中餐",
    "粤菜": "中餐", "牛肉": "中餐", "商场": "商场", "逛街": "商场",
    "购物": "购物", "超市": "超市", "便利店": "便利店", "小吃": "小吃",
    "买菜": "超市", "采购": "超市", "公园": "公园", "景点": "景点", "博物馆": "景点",
    "游乐园": "游乐园", "电影": "电影院", "影院": "电影院",
    "酒吧": "酒吧", "KTV": "KTV", "健身": "健身", "按摩": "按摩SPA",
}

TYPE_TO_CATEGORY = {
    "火锅": "餐饮", "烧烤": "餐饮", "中餐": "餐饮", "小吃": "餐饮",
    "外国菜": "餐饮", "甜品": "餐饮", "饮品": "餐饮",
    "景点": "景点", "公园": "景点", "游乐园": "景点",
    "商场": "购物", "超市": "购物", "便利店": "购物", "购物": "购物",
    "茶馆": "休闲", "KTV": "休闲", "酒吧": "休闲", "电影院": "休闲",
    "健身": "休闲", "按摩SPA": "休闲",
}

NEED_TYPE_HINTS = {
    "diet:light": ["中餐", "外国菜", "小吃", "饮品", "甜品"],
    "spicy:no": ["中餐", "外国菜", "小吃", "饮品", "甜品", "火锅"],
    "scene:romantic": ["电影院", "甜品", "饮品", "茶馆", "外国菜"],
    "scene:business": ["中餐", "茶馆", "外国菜"],
    "audience:family": ["公园", "景点", "游乐园", "中餐", "甜品"],
    "audience:children": ["公园", "景点", "游乐园", "中餐", "甜品"],
    "comfort:long_stay": ["茶馆", "饮品", "商场"],
    "feature:photogenic": ["景点", "茶馆", "甜品", "商场", "外国菜"],
    "feature:unique": ["景点", "小吃", "茶馆", "火锅"],
}


def _now():
    return time.time()


def _unique(items):
    result = []
    seen = set()
    for item in items:
        if not item:
            continue
        if item not in seen:
            result.append(item)
            seen.add(item)
    return result


def _load_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return default


def _atomic_save_json(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = "{}.{}.tmp".format(path, uuid.uuid4().hex)
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp, path)


def normalize_id(value, default=None):
    text = str(value or "").strip()
    if not text:
        return default
    text = re.sub(r"[^0-9A-Za-z_.:\-\u4e00-\u9fff]", "_", text)
    return text[:MAX_ID_LENGTH] or default


def _clean_text_items(items, limit=MAX_FEEDBACK_ITEMS):
    if not isinstance(items, list):
        return []
    cleaned = []
    for item in items[:limit]:
        text = str(item or "").strip()
        if text:
            cleaned.append(text[:40])
    return _unique(cleaned)


def parse_dialogue_lines(text):
    messages = []
    if not text:
        return messages
    for raw_line in str(text).splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = re.match(r"^([^:：]{1,16})[:：]\s*(.+)$", line)
        if match:
            messages.append({
                "speaker_id": match.group(1).strip()[:16],
                "text": match.group(2).strip()[:200],
            })
    return messages if len(messages) >= 2 else []


def extract_types(text):
    found = []
    for kw, typ in TYPE_KEYWORDS.items():
        if kw in text:
            cat = TYPE_TO_CATEGORY.get(typ)
            if cat:
                found.append(cat)
            found.append(typ)
    return _unique(found)


def extract_location(text):
    for kw, loc in LOCATION_ALIASES.items():
        if kw in text:
            return dict(loc)
    return None


def extract_budget(text):
    match = re.search(r"(?:人均|预算|每人)?\s*(\d{2,4})\s*(?:元|块|以内|以下)?", text)
    if not match:
        if any(k in text for k in ("便宜", "平价", "不要太贵", "性价比")):
            return 100
        if any(k in text for k in ("高档", "体面", "商务宴请")):
            return 300
        return None
    return int(match.group(1))


FOLLOW_UP_TERMS = ("那附近", "刚才", "上次", "附近还有", "还有", "换成", "改成", "换一个", "再来", "再加", "顺便", "别的")
CENTER_FOLLOW_UP_TERMS = ("那附近", "刚才", "上次", "附近还有", "还有", "换成", "改成", "换一个", "再来", "再加", "别的")
AMBIGUOUS_TERMS = ("随便", "都行", "安排一下", "推荐一下", "去哪", "怎么玩", "附近有什么", "不知道", "给个方案")


def _is_follow_up(text):
    return any(k in text for k in FOLLOW_UP_TERMS)


def _uses_previous_center(text):
    return any(k in text for k in CENTER_FOLLOW_UP_TERMS)


def _is_ambiguous_goal(text, has_type_signal, has_location_signal, has_memory):
    clean = re.sub(r"\s+", "", text or "")
    if has_type_signal or has_location_signal:
        return False
    if has_memory and _is_follow_up(clean):
        return False
    return len(clean) <= 12 and any(k in clean for k in AMBIGUOUS_TERMS)


def _clarification_options(normalized):
    return [
        {"label": "找餐厅", "goal": "春熙路附近找一家适合现在去的餐厅"},
        {"label": "逛景点", "goal": "武侯祠附近看景点，安排两小时"},
        {"label": "喝咖啡", "goal": "太古里附近喝咖啡，顺便逛街"},
    ]


class NeedInferer:
    def infer(self, text, profile=None):
        profile = profile or {}
        text = text or ""
        labels = []
        must_not = []
        type_hints = []
        budget_max = extract_budget(text)

        def add(label):
            labels.append(label)
            type_hints.extend(NEED_TYPE_HINTS.get(label, []))

        if any(k in text for k in ("清淡", "不辣", "少辣", "不吃辣", "别太辣")):
            add("diet:light")
            add("spicy:no")
            must_not.extend(["diet:spicy", "diet:oily"])
        if any(k in text for k in ("不油", "少油", "健康", "轻食")):
            add("diet:light")
            must_not.append("diet:oily")
        if any(k in text for k in ("约会", "情侣", "浪漫", "有氛围")):
            add("scene:romantic")
            add("noise:quiet")
            add("privacy:high")
        if any(k in text for k in ("安静", "清静", "别太吵", "聊天")):
            add("noise:quiet")
            must_not.append("noise:loud")
        if any(k in text for k in ("带孩子", "亲子", "小朋友", "儿童", "带娃")):
            add("audience:family")
            add("audience:children")
            add("safety:high")
        if any(k in text for k in ("有特色", "特色", "老字号", "非遗", "本地特色")):
            add("feature:unique")
            add("feature:heritage")
        if any(k in text for k in ("坐一下午", "久坐", "办公", "有插座", "有wifi", "有 WiFi")):
            add("comfort:long_stay")
            add("facility:wifi")
        if any(k in text for k in ("商务宴请", "客户", "体面", "包间", "商务")):
            add("scene:business")
            add("privacy:high")
        if any(k in text for k in ("拍照", "出片", "打卡", "好看", "网红")):
            add("feature:photogenic")
            add("scene:aesthetic")

        dietary = profile.get("dietary") or []
        if any("不吃辣" in str(item) or "不辣" in str(item) for item in dietary):
            add("spicy:no")
            must_not.append("diet:spicy")

        avoid_tags = profile.get("avoid_tags") or []
        for tag in avoid_tags:
            if tag:
                must_not.append("type:{}".format(tag))

        return {
            "labels": _unique(labels),
            "must_not": _unique(must_not),
            "type_hints": _unique(type_hints),
            "budget_max": budget_max,
        }


class PoiMatcher:
    def infer_poi_semantics(self, poi, real_type, gt=None):
        name = poi.get("name", "")
        tags = set()
        negative = set()
        price = 100

        def add(*items):
            for item in items:
                tags.add(item)

        def avoid(*items):
            for item in items:
                negative.add(item)

        if real_type in ("火锅", "烧烤"):
            add("diet:spicy", "diet:oily", "scene:friends", "feature:local")
            add("noise:loud")
            avoid("diet:light", "noise:quiet", "scene:business")
            price = 120
            if any(k in name for k in ("潮汕", "牛肉", "番茄", "菌汤", "清汤")):
                add("diet:light", "spicy:no")
                negative.discard("diet:light")
        elif real_type in ("中餐", "外国菜", "农家乐"):
            add("scene:business", "audience:family")
            price = 120 if real_type == "中餐" else 160
            if any(k in name for k in ("粤", "牛肉", "汤", "素", "轻食", "沙拉")):
                add("diet:light")
        elif real_type in ("茶馆", "饮品", "甜品"):
            add("noise:quiet", "comfort:long_stay", "facility:wifi", "scene:romantic")
            price = 60
            if real_type == "甜品":
                add("feature:photogenic")
        elif real_type in ("电影院", "酒吧"):
            add("scene:romantic", "privacy:high")
            price = 90 if real_type == "电影院" else 150
            if real_type == "酒吧":
                add("noise:loud")
        elif real_type in ("公园", "景点", "游乐园"):
            add("audience:family", "audience:children", "safety:high", "feature:photogenic")
            price = 50
            if real_type == "景点":
                add("feature:heritage", "feature:unique")
        elif real_type in ("商场", "购物"):
            add("audience:family", "comfort:long_stay", "scene:aesthetic")
            price = 100
        elif real_type in ("健身", "按摩SPA"):
            add("comfort:long_stay", "scene:wellness")
            price = 120

        if any(k in name for k in ("老", "非遗", "博物馆", "传承")):
            add("feature:heritage", "feature:unique")
        if any(k in name for k in ("花园", "江景", "屋顶", "露台", "太古里", "旗舰")):
            add("feature:photogenic", "scene:aesthetic")
        if any(k in name for k in ("快餐", "冒菜", "麻辣烫")):
            add("noise:loud")
            avoid("scene:business", "noise:quiet")
            price = min(price, 60)

        if gt and gt.get("overall", 0) >= 4.5:
            add("quality:high")

        return {
            "labels": sorted(tags),
            "negative": sorted(negative),
            "price_per_person": price,
        }

    def match_score(self, poi, real_type, user_needs, gt=None):
        if not user_needs:
            return 0.0
        semantic = self.infer_poi_semantics(poi, real_type, gt)
        labels = set(semantic["labels"])
        negative = set(semantic["negative"])
        score = 0.0

        for label in user_needs.get("labels", []):
            if label in labels:
                score += 1.8
            elif label in negative:
                score -= 2.5
            else:
                if label.startswith(("scene:", "audience:", "diet:", "noise:", "privacy:")):
                    score -= 0.35

        for label in user_needs.get("must_not", []):
            if label.startswith("type:"):
                if real_type == label.split(":", 1)[1]:
                    score -= 6.0
            elif label in labels:
                score -= 3.0

        budget_max = user_needs.get("budget_max")
        if budget_max:
            price = semantic.get("price_per_person", 100)
            if price <= budget_max:
                score += 1.0
            elif price <= budget_max * 1.25:
                score += 0.2
            elif price > budget_max * 1.5:
                score -= 2.0

        return max(-8.0, min(8.0, score))


class DialogueStateTracker:
    def __init__(self):
        self.slots = {}
        self.conflicts = []
        self.messages = []
        self.speaker_bias = {}

    def update(self, speaker, text):
        speaker = speaker or "user"
        text = text or ""
        self.messages.append({"speaker_id": speaker, "text": text})
        self.speaker_bias.setdefault(speaker, 1.0 if not self.speaker_bias else 0.7)

        slots = self.extract_slots(text)
        for name, value in slots.items():
            if value in (None, [], ""):
                continue
            if name in self.slots:
                old = self.slots[name]
                if self._is_conflict(name, old["value"], value):
                    self.conflicts.append({
                        "slot": name,
                        "a": old,
                        "b": {"speaker_id": speaker, "value": value},
                    })
                else:
                    old["value"] = self._merge(name, old["value"], value)
                    old["weight"] += self.speaker_bias.get(speaker, 0.7)
                    old["speakers"] = _unique(old.get("speakers", []) + [speaker])
            else:
                self.slots[name] = {
                    "speaker_id": speaker,
                    "speakers": [speaker],
                    "value": value,
                    "weight": self.speaker_bias.get(speaker, 0.7),
                }

    def extract_slots(self, text):
        slots = {}
        types = extract_types(text)
        if types:
            food_types = [t for t in types if TYPE_TO_CATEGORY.get(t) == "餐饮" or t == "餐饮"]
            activity_types = [t for t in types if TYPE_TO_CATEGORY.get(t) in ("购物", "景点", "休闲")]
            if food_types:
                slots["food"] = food_types
            if activity_types:
                slots["activity"] = activity_types
        loc = extract_location(text)
        if loc:
            slots["location"] = loc
        budget = extract_budget(text)
        if budget:
            slots["budget"] = budget
        if any(k in text for k in ("不吃辣", "不辣", "清淡", "少辣")):
            slots["dietary"] = ["不吃辣", "清淡"]
        if any(k in text for k in ("吃完", "先吃", "然后", "再去", "逛街")):
            sequence = []
            food_types = [t for t in types if TYPE_TO_CATEGORY.get(t) == "餐饮"]
            if any(k in text for k in ("火锅", "吃", "餐")):
                sequence.append(food_types[0] if food_types else "餐饮")
            if any(k in text for k in ("逛街", "购物", "商场")):
                sequence.append("商场")
            if sequence:
                slots["sequence"] = sequence
        return slots

    def _is_conflict(self, name, old, new):
        if name == "budget":
            return abs(int(old) - int(new)) >= 200
        if name == "location":
            return old.get("name") != new.get("name")
        if name == "sequence":
            return old and new and old != new and list(reversed(old)) == new
        return False

    def _merge(self, name, old, new):
        if name in ("food", "activity", "dietary", "sequence"):
            return _unique(list(old) + list(new))
        return new

    def combined_goal(self):
        parts = []
        loc = self.slots.get("location", {}).get("value")
        if loc:
            parts.append(loc.get("name", ""))
        for key in ("food", "activity", "dietary"):
            value = self.slots.get(key, {}).get("value")
            if value:
                parts.extend(value)
        budget = self.slots.get("budget", {}).get("value")
        if budget:
            parts.append("人均{}以内".format(budget))
        if not parts:
            parts = [m["text"] for m in self.messages]
        return " ".join(_unique(parts))

    def to_dict(self):
        return {
            "slots": self.slots,
            "conflicts": self.conflicts,
            "messages": self.messages,
        }


class MemoryStore:
    def __init__(self, profile_path=PROFILE_PATH):
        self.profile_path = profile_path
        self._lock = threading.RLock()
        self._profiles = _load_json(profile_path, {"users": {}})
        self._sessions = {}
        self.profile_persist_error = None

    def get_profile(self, user_id, create=True):
        if not user_id:
            return {}
        with self._lock:
            users = self._profiles.setdefault("users", {})
            if not create and str(user_id) not in users:
                return {}
            profile = users.setdefault(str(user_id), {
                "preferred_tags": {},
                "avoid_tags": [],
                "dietary": [],
                "locations": {"frequent_areas": []},
                "updated_at": int(_now()),
            })
            return profile

    def save_profiles(self):
        with self._lock:
            try:
                _atomic_save_json(self.profile_path, self._profiles)
                self.profile_persist_error = None
                return True
            except OSError as exc:
                # Route planning must continue even when the runtime directory is
                # read-only. Profiles remain available in memory for this process.
                self.profile_persist_error = str(exc)
                return False

    def get_session(self, session_id, create=True):
        session_id = session_id or "anonymous"
        with self._lock:
            self._purge_expired()
            if not create and session_id not in self._sessions:
                return {}
            session = self._sessions.setdefault(session_id, {
                "session_id": session_id,
                "created_at": _now(),
                "updated_at": _now(),
                "queries": [],
                "center": None,
                "locked_radius": None,
                "mentioned_types": [],
                "selected_pois": [],
                "negative_pois": [],
                "last_interaction": {},
            })
            session["updated_at"] = _now()
            return session

    def clear_session(self, session_id):
        with self._lock:
            return self._sessions.pop(session_id, None) is not None

    def clear_profile(self, user_id):
        if not user_id:
            return False
        with self._lock:
            users = self._profiles.setdefault("users", {})
            cleared = users.pop(str(user_id), None) is not None
            if cleared:
                self.save_profiles()
            return cleared

    def persistence_status(self):
        return {
            "profile_path": self.profile_path,
            "profile_persisted": self.profile_persist_error is None,
            "profile_persist_error": self.profile_persist_error,
        }

    def _purge_expired(self):
        cutoff = _now() - SESSION_TTL_SECONDS
        expired = [sid for sid, s in self._sessions.items() if s.get("updated_at", 0) < cutoff]
        for sid in expired:
            self._sessions.pop(sid, None)


class InteractionManager:
    def __init__(self):
        self.memory = MemoryStore()
        self.need_inferer = NeedInferer()

    def prepare(self, payload, normalized):
        payload = payload or {}
        session_id = normalize_id(payload.get("session_id"), "default-session")
        user_id = normalize_id(payload.get("user_id"))
        session = self.memory.get_session(session_id)
        profile = self.memory.get_profile(user_id)

        dialogue = payload.get("dialogue") or payload.get("messages") or []
        if not dialogue:
            dialogue = parse_dialogue_lines(normalized.get("goal", ""))
        tracker = DialogueStateTracker()
        if isinstance(dialogue, list):
            for msg in dialogue[:MAX_DIALOGUE_MESSAGES]:
                if isinstance(msg, dict):
                    speaker = normalize_id(msg.get("speaker_id") or msg.get("speaker"), "user")
                    tracker.update(speaker, str(msg.get("text", ""))[:200])

        goal = normalized["goal"]
        if tracker.messages:
            goal = tracker.combined_goal()

        memory_applied = []
        is_follow_up = _is_follow_up(goal)
        goal_location = extract_location(goal)
        if _uses_previous_center(goal) and session.get("center") and not goal_location:
            normalized["center_lng"] = session["center"]["lng"]
            normalized["center_lat"] = session["center"]["lat"]
            if session["center"].get("name"):
                normalized["center_name"] = session["center"]["name"]
            if session["center"].get("center_key"):
                normalized["center_key"] = session["center"]["center_key"]
            memory_applied.append("last_center")
        if (
            any(k in goal for k in ("像上次", "照上次", "类似上次", "还有", "附近还有", "别的", "换一个"))
            and session.get("mentioned_types")
        ):
            memory_applied.append("mentioned_types")

        combined_text = " ".join([goal] + [m.get("text", "") for m in tracker.messages])
        needs = self.need_inferer.infer(combined_text, profile)
        type_hints = needs.get("type_hints", [])
        if tracker.slots.get("food"):
            type_hints.extend(tracker.slots["food"]["value"])
        if tracker.slots.get("activity"):
            type_hints.extend(tracker.slots["activity"]["value"])
        if session.get("mentioned_types") and "mentioned_types" in memory_applied:
            type_hints.extend(session["mentioned_types"])

        loc = tracker.slots.get("location", {}).get("value") or goal_location
        if loc:
            normalized["center_lng"] = loc["lng"]
            normalized["center_lat"] = loc["lat"]
            normalized["center_name"] = loc.get("name", normalized.get("center_name"))
            memory_applied.append("dialogue_location")

        sequence = tracker.slots.get("sequence", {}).get("value")
        avoid_tags = list(profile.get("avoid_tags") or [])
        dietary = tracker.slots.get("dietary", {}).get("value")
        if dietary:
            profile.setdefault("dietary", [])
            profile["dietary"] = _unique(profile.get("dietary", []) + dietary)

        clarification = None
        clarification_options = []
        needs_clarification = False
        conflicts = list(tracker.conflicts)
        intent_hint = None
        if sequence and len(sequence) >= 2:
            intent_hint = "simple_route"
        elif tracker.slots.get("food") and not tracker.slots.get("activity"):
            intent_hint = "single_poi"
        elif is_follow_up and type_hints and not sequence:
            intent_hint = "single_poi"
        if sequence and tracker.slots.get("food"):
            foods = [t for t in tracker.slots["food"]["value"] if TYPE_TO_CATEGORY.get(t) == "餐饮"]
            if foods and sequence[0] == "餐饮":
                sequence[0] = foods[0]
        if tracker.slots.get("food") and tracker.slots.get("dietary"):
            foods = tracker.slots["food"]["value"]
            if "火锅" in foods and "不吃辣" in tracker.slots["dietary"]["value"]:
                intent_hint = intent_hint or "single_poi"
                conflicts.append({
                    "slot": "food_dietary",
                    "reason": "火锅与不吃辣存在口味冲突，已转为清淡/不辣锅型偏好",
                })
                clarification = "有人想吃火锅，也有人不吃辣；已优先匹配番茄锅、菌汤锅、潮汕牛肉火锅等清淡方案。"
        has_type_signal = bool(type_hints or sequence or tracker.slots.get("food") or tracker.slots.get("activity") or extract_types(goal))
        has_location_signal = bool(loc or goal_location)
        if _is_ambiguous_goal(goal, has_type_signal, has_location_signal, bool(session.get("center") or session.get("mentioned_types"))):
            needs_clarification = True
            clarification = "我还需要一个方向：您更想找餐饮、景点/公园、咖啡茶馆，还是夜间活动？"
            clarification_options = _clarification_options(normalized)
        elif is_follow_up and session.get("center") and not has_type_signal and not session.get("mentioned_types"):
            needs_clarification = True
            clarification = "我已沿用上一次的位置，但还需要知道这次想找餐饮、景点、咖啡茶馆还是夜间活动。"
            clarification_options = _clarification_options(normalized)

        return {
            "session_id": session_id,
            "user_id": user_id,
            "effective_goal": goal,
            "preferred_tags_append": _unique(type_hints),
            "avoid_tags_append": _unique(avoid_tags),
            "sequence": sequence,
            "user_needs": needs,
            "intent_hint": intent_hint,
            "dialogue_state": tracker.to_dict() if tracker.messages else None,
            "conflicts": conflicts,
            "clarification": clarification,
            "needs_clarification": needs_clarification,
            "clarification_options": clarification_options,
            "memory_applied": _unique(memory_applied),
        }

    def record_result(self, normalized, result, context):
        session = self.memory.get_session(context["session_id"])
        constraints = result.get("constraints", {}) if result else {}
        variants = result.get("variants", []) if result else []
        first = variants[0] if variants else {}
        items = first.get("recommendations") or first.get("route") or []
        top_ids = [item.get("poi_id") for item in items[:5] if item.get("poi_id")]
        center = {
            "lng": normalized["center_lng"],
            "lat": normalized["center_lat"],
            "name": normalized.get("center_name"),
            "center_key": normalized.get("center_key"),
        }

        session["queries"].append({
            "goal": normalized["goal"],
            "effective_goal": context.get("effective_goal"),
            "ts": int(_now()),
        })
        session["queries"] = session["queries"][-20:]
        session["center"] = center
        session["locked_radius"] = normalized.get("radius")
        session["mentioned_types"] = _unique(session.get("mentioned_types", []) + constraints.get("preferred_tags", []))[-20:]
        session["selected_pois"] = _unique(session.get("selected_pois", []) + top_ids)[-30:]
        session["last_interaction"] = {
            "intent_type": constraints.get("intent_type"),
            "top_recommendations": top_ids,
        }

        user_id = context.get("user_id")
        if user_id:
            profile = self.memory.get_profile(user_id)
            prefs = profile.setdefault("preferred_tags", {})
            for tag in constraints.get("preferred_tags", []):
                prefs[tag] = round(min(1.0, float(prefs.get(tag, 0)) + 0.05), 3)
            locs = profile.setdefault("locations", {}).setdefault("frequent_areas", [])
            locs.append({"name": "current", "lng": center["lng"], "lat": center["lat"], "visits": 1})
            profile["locations"]["frequent_areas"] = locs[-20:]
            profile["updated_at"] = int(_now())
            self.memory.save_profiles()

    def apply_feedback(self, payload):
        feedback = payload.get("feedback")
        user_id = normalize_id(payload.get("user_id"))
        if not isinstance(feedback, dict) or not user_id:
            return False
        preferred_tags = _clean_text_items(feedback.get("preferred_tags", []))
        avoid_tags = _clean_text_items(feedback.get("avoid_tags", []))
        dietary = _clean_text_items(feedback.get("dietary", []))
        if not (preferred_tags or avoid_tags or dietary):
            return False
        profile = self.memory.get_profile(user_id)
        prefs = profile.setdefault("preferred_tags", {})
        for tag in preferred_tags:
            prefs[tag] = round(min(1.0, float(prefs.get(tag, 0)) + 0.1), 3)
        profile["avoid_tags"] = _unique(profile.get("avoid_tags", []) + avoid_tags)
        profile["dietary"] = _unique(profile.get("dietary", []) + dietary)
        profile["updated_at"] = int(_now())
        self.memory.save_profiles()
        return True

    def profile_status(self, user_id):
        user_id = normalize_id(user_id)
        if not user_id:
            return {}
        return dict(self.memory.get_profile(user_id, create=False))

    def clear_session(self, session_id):
        return self.memory.clear_session(normalize_id(session_id, "default-session"))

    def clear_profile(self, user_id):
        return self.memory.clear_profile(normalize_id(user_id))

    def session_status(self, session_id):
        return dict(self.memory.get_session(normalize_id(session_id, "default-session"), create=False))


def apply_context_to_constraints(constraints, context):
    if not context:
        return constraints
    constraints["raw_goal"] = context.get("effective_goal") or constraints.get("raw_goal")
    constraints["preferred_tags"] = _unique(
        constraints.get("preferred_tags", []) + context.get("preferred_tags_append", [])
    )
    constraints["avoid_tags"] = _unique(
        constraints.get("avoid_tags", []) + context.get("avoid_tags_append", [])
    )
    if context.get("sequence"):
        constraints["sequence"] = context["sequence"]
    if context.get("intent_hint"):
        constraints["intent_hint"] = context["intent_hint"]
    constraints["user_needs"] = context.get("user_needs") or {}
    constraints["interaction"] = {
        "session_id": context.get("session_id"),
        "user_id": context.get("user_id"),
        "effective_goal": context.get("effective_goal"),
        "intent_hint": context.get("intent_hint"),
        "memory_applied": context.get("memory_applied", []),
        "user_needs": context.get("user_needs") or {},
        "conflicts": context.get("conflicts", []),
        "clarification": context.get("clarification"),
        "needs_clarification": context.get("needs_clarification", False),
        "clarification_options": context.get("clarification_options", []),
        "dialogue_state": context.get("dialogue_state"),
    }
    return constraints


poi_matcher = PoiMatcher()
interaction_manager = InteractionManager()
