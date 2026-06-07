"""
全局配置管理

所有可配置参数集中在此，支持环境变量覆盖。
支持无前缀环境变量；历史 HACKATHON_ 前缀仍兼容。
"""
import os


def _load_dotenv():
    """Load simple KEY=VALUE pairs from local .env without adding a dependency."""
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(env_path):
        return
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
    except OSError:
        pass


_load_dotenv()


def _env(key, default=""):
    """读取环境变量，兼容历史 HACKATHON_ 前缀。"""
    return os.environ.get(f"HACKATHON_{key}", os.environ.get(key, default))


def _env_int(key, default=0):
    try:
        return int(_env(key, str(default)))
    except ValueError:
        return default


def _env_float(key, default=0.0):
    try:
        return float(_env(key, str(default)))
    except ValueError:
        return default


def _env_bool(key, default=False):
    value = _env(key, "1" if default else "0").strip().lower()
    return value in ("1", "true", "yes", "on")


def _chat_url(key, base_key, default):
    url = _env(key, "")
    if not url:
        url = _env(base_key, default)
    if url.endswith("/chat/completions"):
        return url
    return url.rstrip("/") + "/chat/completions"


# ========== API Keys ==========
# 优先级：DeepSeek -> MiMo -> MiniMax Coding Plan -> GLM -> 本地语义兜底
DEEPSEEK_API_KEY = _env("DEEPSEEK_API_KEY", "")
DEEPSEEK_CHAT_URL = _chat_url("DEEPSEEK_CHAT_URL", "DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = _env("DEEPSEEK_MODEL", "deepseek-chat")
DEEPSEEK_AUTH_TYPE = _env("DEEPSEEK_AUTH_TYPE", "bearer")
MIMO_API_KEY = _env("MIMO_API_KEY", "")
MIMO_CHAT_URL = _chat_url("MIMO_CHAT_URL", "MIMO_BASE_URL", "https://token-plan-cn.xiaomimimo.com/v1")
MIMO_MODEL = _env("MIMO_MODEL", "mimo-v2.5-pro")
MIMO_AUTH_TYPE = _env("MIMO_AUTH_TYPE", "api-key")
MINIMAX_API_KEY = _env("MINIMAX_API_KEY", "")
MINIMAX_CHAT_URL = _chat_url("MINIMAX_CHAT_URL", "MINIMAX_BASE_URL", "https://api.minimax.io/v1")
MINIMAX_MODEL = _env("MINIMAX_MODEL", "MiniMax-M3")
MINIMAX_AUTH_TYPE = _env("MINIMAX_AUTH_TYPE", "bearer")
GLM_API_KEY = _env("GLM_API_KEY", "")
GLM_CHAT_URL = _chat_url("GLM_CHAT_URL", "GLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4")
GLM_MODEL = _env("GLM_MODEL", "glm-4-flash")
GLM_AUTH_TYPE = _env("GLM_AUTH_TYPE", "bearer")
INTENT_LLM_FAILURE_COOLDOWN_SECONDS = _env_int("INTENT_LLM_FAILURE_COOLDOWN_SECONDS", 120)

# ========== 服务配置 ==========
SERVER_HOST = _env("HOST", "127.0.0.1")
SERVER_PORT = _env_int("PORT", 8000)
SERVER_VERSION = _env("SERVER_VERSION", "3.3.0")
REQUEST_TIMEOUT_SECONDS = _env_int("REQUEST_TIMEOUT_SECONDS", 90)
MAX_REQUEST_BYTES = _env_int("MAX_REQUEST_BYTES", 64 * 1024)
ENABLE_CORS = _env_bool("ENABLE_CORS", True)
WARMUP_ON_START = _env_bool("WARMUP_ON_START", False)
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")

# ========== 规划引擎参数 ==========
DEFAULT_CENTER_LNG = _env_float("CENTER_LNG", 104.06476)
DEFAULT_CENTER_LAT = _env_float("CENTER_LAT", 30.65705)
DEFAULT_RADIUS = _env_int("RADIUS", 3000)
# 兼容历史环境变量；当前规划器会按用户意图推断未明说的时间预算，不再全局套用固定 4 小时。
DEFAULT_TIME_BUDGET_HOURS = _env_int("TIME_BUDGET", 4)

# 候选池
CANDIDATE_POOL_SIZE = _env_int("CANDIDATE_POOL_SIZE", 300)
PERSIST_KNN_CACHE = _env_bool("PERSIST_KNN_CACHE", False)
CATEGORY_QUOTA = {
    "景点": _env_int("QUOTA_SIGHT", 50),
    "休闲": _env_int("QUOTA_LEISURE", 40),
    "购物": _env_int("QUOTA_SHOPPING", 25),
    "餐饮": _env_int("QUOTA_FOOD", 80),
    "其他": _env_int("QUOTA_OTHER", 20),
}

# 类型约束
CATEGORY_LIMITS = {
    "餐饮": _env_int("LIMIT_FOOD", 2),
    "景点": _env_int("LIMIT_SIGHT", 2),
    "购物": _env_int("LIMIT_SHOPPING", 1),
    "休闲": _env_int("LIMIT_LEISURE", 2),
}
CONCRETE_TYPE_LIMIT = _env_int("CONCRETE_TYPE_LIMIT", 1)

# 语义搜索
SEMANTIC_TOP_K = _env_int("SEMANTIC_TOP_K", 80)
SEMANTIC_BOOST = _env_float("SEMANTIC_BOOST", 2.5)

# 候选集大模型评审：只重排已存在的 POI，不允许生成新地点。
ENABLE_LLM_CANDIDATE_REVIEW = _env_bool("ENABLE_LLM_CANDIDATE_REVIEW", True)
LLM_REVIEW_CANDIDATE_TOP_N = _env_int("LLM_REVIEW_CANDIDATE_TOP_N", 12)
LLM_REVIEW_BONUS = _env_float("LLM_REVIEW_BONUS", 1.2)

# 路线级候选方案评审：只在已生成的路线候选之间重排，资源可按场景调度。
ENABLE_LLM_ROUTE_REVIEW = _env_bool("ENABLE_LLM_ROUTE_REVIEW", True)
LLM_ROUTE_REVIEW_TOP_N = _env_int("LLM_ROUTE_REVIEW_TOP_N", 5)
LLM_ROUTE_REVIEW_BONUS = _env_float("LLM_ROUTE_REVIEW_BONUS", 1.5)
ROUTE_SLATE_MAX_CANDIDATES = _env_int("ROUTE_SLATE_MAX_CANDIDATES", 28)
ROUTE_SLATE_REPLACEMENT_TOP_N = _env_int("ROUTE_SLATE_REPLACEMENT_TOP_N", 8)

# 营业时间自动调整
AUTO_TIME_PERCENTILE = _env_int("AUTO_TIME_PERCENTILE", 60)
AUTO_TIME_THRESHOLD = _env_float("AUTO_TIME_THRESHOLD", 0.05)

# 路线变体参数
VARIANT_PARAMS = {
    "efficient": {
        "stay_mult": 0.8,
        "min_pois": 4,
        "max_pois": 8,
        "desc": "在有限时间内串联最多景点，移动路径最短",
    },
    "relaxed": {
        "stay_mult": 1.3,
        "min_pois": 3,
        "max_pois": 6,
        "desc": "节奏更舒缓，每个地点留有充足体验时间",
    },
    "food_first": {
        "stay_mult": 0.9,
        "min_pois": 4,
        "max_pois": 7,
        "desc": "优先串联特色美食与热门景点",
    },
}

# 日志
LOG_LEVEL = _env("LOG_LEVEL", "INFO")
LOG_FORMAT = _env("LOG_FORMAT", "text")  # text | json
