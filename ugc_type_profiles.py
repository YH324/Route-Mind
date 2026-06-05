#!/usr/bin/env python3
"""
POI类型画像系统 v4.0

核心设计：为每种POI类型定义专属的评论维度、词汇库、模板句式、数量/长度规则。
类型推断优先级：name关键词 > tag > typecode前缀
"""
import re

# ============================================================
# 1. 类型关键词映射（用于从POI名称推断真实类型）
# ============================================================
NAME_KEYWORDS = {
    # 餐饮大类
    "火锅": ["火锅", "串串", "麻辣烫", "冒菜", "涮", "老灶", "九宫格", "牛油"],
    "烧烤": ["烧烤", "烤串", "烤肉", "烤鱼", "铁板烧", "炭烤", "烤吧"],
    "小吃": ["小吃", "面", "粉", "馄饨", "饺子", "包子", "锅盔", "凉粉", "冰粉", "蛋烘糕", "肥肠", "兔头", "钵钵鸡", "凉皮", "肉夹馍", "炸鸡", "汉堡"],
    "甜品": ["蛋糕", "甜品", "面包", "烘焙", "糕点", "酥", "糖果", "糖葫芦", "糖画", "糖油果子", "冰品", "冰淇淋", "绵绵冰", "布丁", "蛋挞", "泡芙", "五芳斋", "月饼", "粽子"],
    "饮品": ["奶茶", "咖啡", "茶饮", "果汁", "酸奶", "奶昔", " lemonade", "柠檬茶", "coco", "喜茶", "奈雪", "星巴克", "瑞幸", "一点点", "茶百道", "蜜雪"],
    "茶馆": ["茶", "茶楼", "茶府", "茶舍", "茶坊", "茶室", "茶园", "茶艺"],
    "中餐": ["川菜", "湘菜", "粤菜", "鲁菜", "江浙菜", "家常菜", "江湖菜", "土菜", "酒楼", "饭店", "食府", "餐厅", "私房菜", "菜馆"],
    "外国菜": ["日料", "寿司", "韩国", "泰国", "越南", "印度", "西餐", "意大利菜", "法餐", "法国菜", "墨西哥", "土耳其", "东南亚"],
    "农家乐": ["农家", "农庄", "柴火", "土鸡", "土鸭", "有机", "采摘", "生态园"],

    # 休闲娱乐
    "KTV": ["KTV", "量贩", "歌城", "唱吧", "卡拉OK"],
    "酒吧": ["酒吧", "酒馆", "夜店", "club", "livehouse", "live house", "清吧", "精酿", "啤酒屋"],
    "网吧": ["网吧", "网咖", "电竞"],
    "电影院": ["电影", "影院", "影城", "IMAX", "杜比"],
    "健身": ["健身", "瑜伽", "舞蹈", "普拉提", "搏击", "拳馆", "跆拳道", "游泳馆"],
    "按摩SPA": ["按摩", "足疗", "SPA", "养生", "推拿", "洗浴", "汗蒸", "采耳"],

    # 景点/公园
    "景点": ["景区", "景点", "古迹", "寺庙", "寺院", "禅寺", "古寺", "博物馆", "纪念馆", "观景点", "观景台", "宝塔", "雷峰塔", "观光塔", "电视塔"],
    "公园": ["公园", "绿地", "湿地", "陵园"],  # 移除"广场""花园"，避免酒店分店名/小区名误判
    "游乐园": ["游乐园", "游乐场", "乐园", "嘉年华", "摩天轮", "过山车"],

    # 购物
    "商场": ["商场", "购物中心", "百货", "奥特莱斯", "outlets", "mall", "商业街"],
    "超市": ["超市", "卖场", "仓储", "生鲜", "永辉", "沃尔玛", "家乐福", "盒马", "山姆", "鲜疏坊", "菜市场", "农贸市场", "菜市"],
    "便利店": ["便利店", "小卖部", "杂货", "24小时", "7-11", "全家", "罗森", "红旗连锁"],
    "数码": ["手机", "电脑", "数码", "电子", "家电", "华为", "苹果", "小米", "OPPO", "vivo"],
    "服饰": ["服装", "服饰", "鞋店", "鞋城", "皮鞋", "运动鞋", "女鞋", "男鞋", "童鞋", "高跟鞋", "包包", "皮包", "背包", "旅行包", "手提包", "钱包", "女装", "男装", "童装", "内衣", "帽子", "配饰", "首饰", "珠宝"],
    "美妆": ["美妆", "化妆品", "护肤", "美容", "美甲", "美发", "理发", "造型", "纹绣", "希思黎", "娇韵诗", "香奈儿", "兰蔻", "迪奥", "雅诗兰黛", "资生堂", "欧莱雅", "SK-II", "MAC", "悦木之源"],
    "家居": ["家具", "家居", "建材", "装饰", "灯饰", "地板", "瓷砖", "卫浴", "橱柜"],

    # 住宿
    "住宿": ["酒店", "宾馆", "客栈", "民宿", "公寓", "旅馆", "招待所", "度假村", "别墅"],

    # 生活服务
    "培训": ["培训", "学校", "教育", "辅导", "补习班", "琴行", "画室", "驾校"],
    "医疗": ["医院", "诊所", "药店", "口腔", "眼科", "体检", "中医馆", "整形", "医美", "美容医院", "植发", "牙科"],
    "宠物": ["宠物", "猫", "狗", "宠", "兽医", "宠物医院"],
    "汽车": ["汽修", "保养", "洗车", "4S店", "轮胎", "美容", "改装"],
}


# 需要过滤的名称前缀（共享充电宝、前置广告等）
NOISE_PREFIXES = ["街电(", "怪兽充电(", "来电(", "小电(", "云充吧(", "速绿(", "搜电("]

def clean_name(name):
    """清理POI名称中的共享充电宝等前缀"""
    for prefix in NOISE_PREFIXES:
        if prefix in name:
            # 提取括号内的真实店名
            idx = name.find(prefix)
            if idx >= 0:
                start = idx + len(prefix)
                end = name.find(")", start)
                if end > start:
                    return name[start:end]
    return name

def infer_real_type(poi):
    """从POI名称、tag、typecode推断真实类型"""
    raw_name = poi.get("name", "")
    name = clean_name(raw_name)
    name_lower = name.lower()
    tags = poi.get("tags", [])
    typecode = poi.get("typecode", "")

    # 1. 名称关键词匹配（最高优先级，按优先级顺序遍历）
    # 优先级：住宿 > 餐饮 > 休闲娱乐 > 景点/公园 > 购物 > 生活服务
    priority_order = [
        "住宿", "火锅", "烧烤", "小吃", "甜品", "饮品", "茶馆", "中餐", "外国菜", "农家乐",
        "KTV", "酒吧", "网吧", "电影院", "健身", "按摩SPA",
        "景点", "公园", "游乐园",
        "商场", "超市", "便利店", "数码", "服饰", "美妆", "家居",
        "培训", "医疗", "宠物", "汽车",
    ]
    for typ in priority_order:
        keywords = NAME_KEYWORDS.get(typ, [])
        for kw in keywords:
            if kw.lower() in name_lower or kw in name:
                return typ

    # 2. Tag匹配（辅助）
    tag_priority = ["火锅", "烧烤", "小吃", "甜品", "饮品", "茶馆", "中餐", "外国菜", "农家菜",
                    "KTV", "酒吧", "网吧", "电影院", "健身", "休闲",
                    "景点", "公园", "游乐园", "度假村",
                    "购物", "家电数码", "便利店",
                    "住宿", "酒店",
                    "教育", "医疗", "宠物", "汽车"]
    for t in tag_priority:
        if t in tags:
            return t

    # 3. Typecode前缀兜底
    tc_map = {
        "0501": "中餐", "0502": "外国菜", "0503": "小吃", "0504": "甜品",
        "0505": "饮品", "0506": "茶馆", "0507": "饮品", "0508": "烧烤", "0509": "火锅",
        "0602": "便利店", "0604": "超市", "0611": "服饰", "0612": "美妆", "0711": "便利店",
        "0712": "数码", "0713": "家居", "0714": "服饰", "0801": "健身", "0802": "休闲",
        "0803": "酒吧", "0804": "度假村", "1001": "住宿", "1101": "公园", "1102": "景点",
    }
    for prefix, typ in tc_map.items():
        if typecode.startswith(prefix):
            return typ

    # 4. 默认
    if "餐饮" in tags or "050" in typecode:
        return "中餐"
    if "购物" in tags or "06" in typecode or "07" in typecode:
        return "购物"
    if "休闲" in tags or "08" in typecode:
        return "休闲"
    if "住宿" in tags or "10" in typecode:
        return "住宿"

    return "其他"


# ============================================================
# 2. 类型评论画像
# ============================================================
# 每个画像包含：
# - dimensions: {dim_name: weight} 该类型关注的核心维度及权重
# - dim_vocab: {dim_name: {star: [words]}} 各维度各星级的描述词汇
# - templates: {sentiment: {length: [templates]}} 按情感和长度分类的模板
# - details: {star: [detail_phrases]} 细节描述短语
# - scenes: [scene_list] 适用场景
# - comment_count_range: (min, max) 该类型评论数量范围
# - length_weights: {short: w1, medium: w2, long: w3} 长度分布权重
# - aspect_names: 该类型特有的评价方面名称

TYPE_PROFILES = {
    # ========== 餐饮类 ==========
    "火锅": {
        "aspect_name": "火锅",
        "dimensions": {"taste": 0.35, "env": 0.15, "service": 0.15, "value": 0.20, "queue": 0.15},
        "dim_labels": {"taste": "锅底口味", "env": "环境氛围", "service": "服务态度", "value": "性价比", "queue": "等位时间"},
        "vocab_good": ["锅底正宗", "牛油香浓", "食材新鲜", "毛肚脆嫩", "鸭血嫩滑", "辣得过瘾", "鸳鸯锅贴心", "自助小料丰富"],
        "vocab_bad": ["锅底寡淡", "食材不新鲜", "毛肚发柴", "越吃越咸", "排队太久", "空调不给力", "油烟大"],
        "details_good": ["招牌毛肚七上八下正好", "鸭血入口即化", "嫩牛肉纹理清晰", "酥肉外酥里嫩", "小料台种类超多"],
        "details_bad": ["锅底越煮越苦", "肉品解冻痕迹明显", "蔬菜叶子发黄", "小料台补给不及时"],
        "templates": {
            "good": {
                "short": ["{name}的锅底太绝了，{highlight}，下次还来！", "{name}人气爆棚，{highlight}，推荐！"],
                "medium": ["{name}算是成都火锅里比较正宗的，{highlight}。{detail}，人均{price}左右，性价比不错。{scene}很合适。"],
                "long": ["{name}在{adname}算是老牌子了，{highlight}。{detail}，环境{env_desc}。{queue_desc}。{scene}推荐来，{people}应该都喜欢。"],
            },
            "neutral": {
                "short": ["{name}中规中矩，{highlight}一般。"],
                "medium": ["{name}整体还行，{highlight}过得去，{issue}。"],
            },
            "bad": {
                "short": ["{name}踩雷，{highlight}不行。"],
                "medium": ["{name}让人失望，{highlight}差劲，{issue}。"],
                "long": ["{name}的体验很差，{highlight}简直不能忍。{issue}，{queue_desc}。环境{env_desc}，不会再来了。"],
            },
        },
        "scenes": ["朋友聚餐", "冬天聚餐", "深夜食堂", "家庭聚会", "同学聚餐"],
        "people": ["重口味爱好者", "吃货", "成都土著", "外地游客", "大学生"],
        "comment_count_range": (40, 90),
        "length_weights": {"short": 0.15, "medium": 0.45, "long": 0.40},
    },

    "烧烤": {
        "aspect_name": "烧烤",
        "dimensions": {"taste": 0.40, "env": 0.10, "service": 0.10, "value": 0.25, "queue": 0.15},
        "dim_labels": {"taste": "烤串味道", "env": "烟火氛围", "service": "上菜速度", "value": "性价比", "queue": "等位时间"},
        "vocab_good": ["炭火香", "肉质鲜嫩", "腌制入味", "外焦里嫩", "撒料地道", "火候到位", "啤酒配烤串绝配"],
        "vocab_bad": ["烤焦了", "肉不新鲜", "调料太咸", "上菜慢", "炭火味呛人", "油烟大"],
        "details_good": ["羊肉串肥瘦相间", "鸡翅表皮酥脆", "茄子上蒜蓉超香", "烤韭菜很入味"],
        "details_bad": ["羊肉串膻味重", "生蚝不新鲜", "烤馒头片糊了", "上菜等了一小时"],
        "templates": {
            "good": {
                "short": ["{name}的烤串味道很正，{highlight}！", "{name}夜宵首选，{highlight}。"],
                "medium": ["{name}算是附近比较火的烧烤店，{highlight}。{detail}，{scene}很合适。"],
                "long": ["晚上和朋友来{name}吃夜宵，{highlight}。{detail}，氛围{env_desc}。{queue_desc}，人均{price}，{people}推荐来。"],
            },
            "neutral": {"short": ["{name}一般，{highlight}中规中矩。"], "medium": ["{name}还行吧，{highlight}一般，{issue}。"]},
            "bad": {"short": ["{name}踩雷，{highlight}太差。"], "medium": ["{name}不推荐，{highlight}不行，{issue}。"]},
        },
        "scenes": ["夜宵", "朋友聚会", "看球赛", "夏天露天", "周末放松"],
        "people": ["夜猫子", "啤酒爱好者", "年轻人", "男生聚会"],
        "comment_count_range": (30, 70),
        "length_weights": {"short": 0.20, "medium": 0.50, "long": 0.30},
    },

    "小吃": {
        "aspect_name": "小吃",
        "dimensions": {"taste": 0.45, "env": 0.05, "service": 0.10, "value": 0.30, "queue": 0.10},
        "dim_labels": {"taste": "味道口感", "env": "卫生环境", "service": "出餐速度", "value": "性价比", "queue": "排队时间"},
        "vocab_good": ["地道", "正宗", "鲜香", "麻辣过瘾", "皮薄馅大", "汤头浓郁", "料足"],
        "vocab_bad": ["油腻", "偏咸", "料少", "皮厚", "汤淡", "不新鲜"],
        "details_good": ["担担面调料很香", "抄手皮薄肉嫩", "锅盔又酥又脆", "冰粉配料丰富"],
        "details_bad": ["面条煮太软", "饺子馅有异味", "凉皮酱料太咸", "分量越来越少"],
        "templates": {
            "good": {
                "short": ["{name}的{food}很正宗，{highlight}！", "{name}好吃不贵，{highlight}。"],
                "medium": ["{name}是附近比较出名的小吃店，{highlight}。{detail}，{scene}来一份正好。"],
                "long": ["{name}在{adname}开了不少年了，{highlight}。{detail}，{queue_desc}。价格实惠，{people}经常来。"],
            },
            "neutral": {"short": ["{name}还行，{highlight}一般。"], "medium": ["{name}中规中矩，{highlight}一般，{issue}。"]},
            "bad": {"short": ["{name}不推荐，{highlight}差。"], "medium": ["{name}让人失望，{highlight}不行，{issue}。"]},
        },
        "scenes": ["一人食", "快速解决", "下午茶", "逛吃", "早餐"],
        "people": ["上班族", "学生党", "游客", "本地人"],
        "comment_count_range": (25, 60),
        "length_weights": {"short": 0.25, "medium": 0.50, "long": 0.25},
    },

    "甜品": {
        "aspect_name": "甜品",
        "dimensions": {"taste": 0.40, "env": 0.25, "service": 0.15, "value": 0.15, "queue": 0.05},
        "dim_labels": {"taste": "甜品口感", "env": "店面氛围", "service": "服务态度", "value": "性价比", "queue": "等位时间"},
        "vocab_good": ["甜而不腻", "入口即化", "层次丰富", "用料讲究", "颜值超高", "拍照好看", "新鲜现做"],
        "vocab_bad": ["太甜腻", "奶油不新鲜", "干巴巴", "颜值一般", "性价比低"],
        "details_good": ["提拉米苏酒味刚好", "千层皮很薄", "芒果班戟果肉超多", "泡芙爆浆超满足"],
        "details_bad": ["蛋糕体发干", "奶油有植物奶油味", "慕斯 gelatin 感重", "甜度太高吃不完"],
        "templates": {
            "good": {
                "short": ["{name}的甜品{highlight}，超满足！", "{name}颜值味道都在线，{highlight}。"],
                "medium": ["{name}是附近比较受欢迎的甜品店，{highlight}。{detail}，环境{env_desc}，{scene}很合适。"],
                "long": ["{name}在{adname}算是网红店了，{highlight}。{detail}，环境{env_desc}，拍照很出片。{queue_desc}，{people}推荐来。"],
            },
            "neutral": {"short": ["{name}还行，{highlight}一般。"], "medium": ["{name}中规中矩，{highlight}一般，{issue}。"]},
            "bad": {"short": ["{name}踩雷，{highlight}不行。"], "medium": ["{name}让人失望，{highlight}差，{issue}。"]},
        },
        "scenes": ["闺蜜下午茶", "约会", "一人食", "拍照打卡", "生日庆祝"],
        "people": ["女生", "甜食爱好者", "年轻人", "情侣"],
        "comment_count_range": (30, 75),
        "length_weights": {"short": 0.20, "medium": 0.45, "long": 0.35},
    },

    "饮品": {
        "aspect_name": "饮品",
        "dimensions": {"taste": 0.40, "env": 0.20, "service": 0.20, "value": 0.15, "queue": 0.05},
        "dim_labels": {"taste": "饮品口味", "env": "店面环境", "service": "出杯速度", "value": "性价比", "queue": "排队时间"},
        "vocab_good": ["茶香浓郁", "奶盖绵密", "甜度刚好", "清爽解渴", "用料新鲜", "创意十足", "颜值在线"],
        "vocab_bad": ["太甜", "茶味淡", "奶盖稀", "用料廉价", "排队久", "性价比低"],
        "details_good": ["珍珠Q弹有嚼劲", "芋泥很细腻", "水果茶果肉超多", "拿铁拉花漂亮"],
        "details_bad": ["珍珠煮太烂", "水果不新鲜", "冰块太多稀释了", "杯子小还贵"],
        "templates": {
            "good": {
                "short": ["{name}的{drink}超好喝，{highlight}！", "{name}种草了，{highlight}。"],
                "medium": ["{name}在{adname}挺火的，{highlight}。{detail}，{scene}来一杯很惬意。"],
                "long": ["{name}算是最近比较喜欢的饮品店，{highlight}。{detail}，环境{env_desc}。{queue_desc}，{people}应该都会喜欢。"],
            },
            "neutral": {"short": ["{name}一般，{highlight}普通。"], "medium": ["{name}中规中矩，{highlight}一般，{issue}。"]},
            "bad": {"short": ["{name}不推荐，{highlight}差。"], "medium": ["{name}踩雷，{highlight}不行，{issue}。"]},
        },
        "scenes": ["下午茶", "逛街解渴", "工作提神", "约会", "闺蜜聚会"],
        "people": ["年轻人", "女生", "学生党", "上班族", "奶茶控"],
        "comment_count_range": (25, 70),
        "length_weights": {"short": 0.25, "medium": 0.50, "long": 0.25},
    },

    "茶馆": {
        "aspect_name": "茶馆",
        "dimensions": {"taste": 0.25, "env": 0.35, "service": 0.25, "value": 0.10, "queue": 0.05},
        "dim_labels": {"taste": "茶叶品质", "env": "环境氛围", "service": "服务体验", "value": "性价比", "queue": "等位情况"},
        "vocab_good": ["茶香清雅", "环境幽静", "装修有格调", "包间私密", "茶艺专业", "适合久坐"],
        "vocab_bad": ["茶质一般", "环境嘈杂", "包间加收费用高", "服务员推销", "停车不便"],
        "details_good": ["普洱陈香浓郁", "铁观音回甘持久", "包间隔音很好", "窗外景色不错"],
        "details_bad": ["茶叶泡两泡就没味了", "大厅太吵", "包间最低消费太高", "茶艺表演敷衍"],
        "templates": {
            "good": {
                "short": ["{name}环境很好，{highlight}，适合喝茶聊天。", "{name}茶叶不错，{highlight}。"],
                "medium": ["{name}在{adname}算是比较有格调的茶馆，{highlight}。{detail}，{scene}很合适。"],
                "long": ["{name}算是{adname}比较安静的茶馆了，{highlight}。{detail}，环境{env_desc}。{queue_desc}，{people}推荐来。"],
            },
            "neutral": {"short": ["{name}一般，{highlight}普通。"], "medium": ["{name}中规中矩，{highlight}一般，{issue}。"]},
            "bad": {"short": ["{name}不推荐，{highlight}差。"], "medium": ["{name}让人失望，{highlight}不行，{issue}。"]},
        },
        "scenes": ["商务洽谈", "老友聚会", "独自品茗", "下午茶", "休闲放松"],
        "people": ["商务人士", "中老年人", "茶文化爱好者", "本地居民"],
        "comment_count_range": (20, 50),
        "length_weights": {"short": 0.20, "medium": 0.55, "long": 0.25},
    },

    "中餐": {
        "aspect_name": "中餐",
        "dimensions": {"taste": 0.35, "env": 0.15, "service": 0.20, "value": 0.20, "queue": 0.10},
        "dim_labels": {"taste": "菜品口味", "env": "就餐环境", "service": "服务态度", "value": "性价比", "queue": "等位时间"},
        "vocab_good": ["菜品精致", "火候到位", "色香味俱全", "用料新鲜", "分量足", "摆盘讲究", "传统味道"],
        "vocab_bad": ["口味一般", "偏油偏咸", "分量少", "上菜慢", "服务冷淡", "性价比低"],
        "details_good": ["宫保鸡丁酸甜适口", "回锅肉肥而不腻", "麻婆豆腐麻辣鲜香", "水煮鱼鱼肉嫩滑"],
        "details_bad": ["菜品温温吞吞", "回锅肉太肥", "麻婆豆腐不够麻", "米饭太硬"],
        "templates": {
            "good": {
                "short": ["{name}的菜品{highlight}，推荐！", "{name}味道正宗，{highlight}。"],
                "medium": ["{name}算是附近比较不错的中餐馆，{highlight}。{detail}，{scene}很合适。"],
                "long": ["{name}在{adname}开了挺久了，{highlight}。{detail}，环境{env_desc}。{queue_desc}，{people}推荐来。"],
            },
            "neutral": {"short": ["{name}一般，{highlight}中规中矩。"], "medium": ["{name}还行，{highlight}一般，{issue}。"]},
            "bad": {"short": ["{name}不推荐，{highlight}差。"], "medium": ["{name}让人失望，{highlight}不行，{issue}。"]},
        },
        "scenes": ["家庭聚餐", "朋友聚会", "商务宴请", "日常吃饭", "节日聚餐"],
        "people": ["本地人", "家庭", "商务人士", "游客", "聚餐人群"],
        "comment_count_range": (30, 70),
        "length_weights": {"short": 0.18, "medium": 0.50, "long": 0.32},
    },

    "外国菜": {
        "aspect_name": "外国菜",
        "dimensions": {"taste": 0.35, "env": 0.25, "service": 0.20, "value": 0.15, "queue": 0.05},
        "dim_labels": {"taste": "菜品口味", "env": "异国氛围", "service": "服务体验", "value": "性价比", "queue": "等位情况"},
        "vocab_good": ["口味正宗", "食材新鲜", "氛围感强", "服务专业", "摆盘精致", "约会首选"],
        "vocab_bad": ["不正宗", "分量少", "价格贵", "服务一般", "环境吵闹"],
        "details_good": ["牛排熟度刚好", "寿司米温度合适", "冬阴功汤底浓郁", "提拉米苏很地道"],
        "details_bad": ["牛排煎老了", "刺身不够新鲜", "意面煮太软", "价格虚高"],
        "templates": {
            "good": {
                "short": ["{name}的菜品很正宗，{highlight}！", "{name}氛围很棒，{highlight}。"],
                "medium": ["{name}算是{adname}比较受欢迎的{foreign_type}餐厅，{highlight}。{detail}，{scene}很合适。"],
                "long": ["{name}环境很有{foreign_type}风情，{highlight}。{detail}，氛围{env_desc}。{queue_desc}，{people}推荐来。"],
            },
            "neutral": {"short": ["{name}一般，{highlight}中规中矩。"], "medium": ["{name}还行，{highlight}一般，{issue}。"]},
            "bad": {"short": ["{name}不推荐，{highlight}差。"], "medium": ["{name}让人失望，{highlight}不行，{issue}。"]},
        },
        "scenes": ["约会", "纪念日", "闺蜜聚餐", "尝鲜", "拍照打卡"],
        "people": ["情侣", "年轻人", "尝鲜者", "海归", "白领"],
        "comment_count_range": (25, 60),
        "length_weights": {"short": 0.20, "medium": 0.50, "long": 0.30},
    },

    "农家乐": {
        "aspect_name": "农家乐",
        "dimensions": {"taste": 0.30, "env": 0.25, "service": 0.15, "value": 0.25, "queue": 0.05},
        "dim_labels": {"taste": "农家风味", "env": "乡村环境", "service": "接待服务", "value": "性价比", "queue": "等位情况"},
        "vocab_good": ["土菜正宗", "食材新鲜", "环境自然", "空气清新", "分量足", "价格实惠", "适合带孩子"],
        "vocab_bad": ["口味一般", "环境简陋", "蚊虫多", "服务态度差", "交通不便"],
        "details_good": ["土鸡炖得很烂", "野菜很新鲜", "鱼塘可以钓鱼", "院子里有秋千"],
        "details_bad": ["菜太咸", "桌椅不干净", "厕所有异味", "停车不方便"],
        "templates": {
            "good": {
                "short": ["{name}的农家菜{highlight}，推荐！", "{name}环境很好，{highlight}。"],
                "medium": ["{name}算是附近比较不错的农家乐，{highlight}。{detail}，{scene}很合适。"],
                "long": ["周末带家人来{name}，{highlight}。{detail}，环境{env_desc}。{queue_desc}，{people}推荐来。"],
            },
            "neutral": {"short": ["{name}一般，{highlight}中规中矩。"], "medium": ["{name}还行，{highlight}一般，{issue}。"]},
            "bad": {"short": ["{name}不推荐，{highlight}差。"], "medium": ["{name}让人失望，{highlight}不行，{issue}。"]},
        },
        "scenes": ["周末亲子", "家庭聚餐", "团建", "亲近自然", "采摘体验"],
        "people": ["家庭", "亲子", "团建人群", "老年人", "城市人"],
        "comment_count_range": (20, 50),
        "length_weights": {"short": 0.20, "medium": 0.55, "long": 0.25},
    },

    # ========== 休闲娱乐 ==========
    "KTV": {
        "aspect_name": "KTV",
        "dimensions": {"taste": 0, "env": 0.35, "service": 0.30, "value": 0.25, "queue": 0.10},
        "dim_labels": {"taste": "音质效果", "env": "包厢环境", "service": "服务态度", "value": "性价比", "queue": "等位时间"},
        "vocab_good": ["音响效果好", "曲库全", "包厢干净", "服务态度好", "价格划算", "酒水种类多"],
        "vocab_bad": ["音响杂音", "曲库老", "包厢有异味", "服务冷淡", "强制消费", "麦克风有问题"],
        "details_good": ["低音炮效果震撼", "新歌更新快", "包间空间大", "服务员响应快"],
        "details_bad": ["音响有电流声", "想唱的歌没有", "包厢空调坏了", "结账时加收服务费"],
        "templates": {
            "good": {
                "short": ["{name}音响{highlight}，唱得很爽！", "{name}环境不错，{highlight}。"],
                "medium": ["{name}算是附近比较不错的KTV，{highlight}。{detail}，{scene}很合适。"],
                "long": ["{name}在{adname}算是老牌KTV了，{highlight}。{detail}，环境{env_desc}。{queue_desc}，{people}推荐来。"],
            },
            "neutral": {"short": ["{name}一般，{highlight}中规中矩。"], "medium": ["{name}还行，{highlight}一般，{issue}。"]},
            "bad": {"short": ["{name}不推荐，{highlight}差。"], "medium": ["{name}让人失望，{highlight}不行，{issue}。"]},
        },
        "scenes": ["朋友聚会", "生日派对", "公司团建", "周末放松", "解压"],
        "people": ["年轻人", "麦霸", "学生党", "上班族"],
        "comment_count_range": (25, 60),
        "length_weights": {"short": 0.20, "medium": 0.50, "long": 0.30},
    },

    "酒吧": {
        "aspect_name": "酒吧",
        "dimensions": {"taste": 0.25, "env": 0.40, "service": 0.20, "value": 0.10, "queue": 0.05},
        "dim_labels": {"taste": "酒水品质", "env": "氛围环境", "service": "服务体验", "value": "性价比", "queue": "等位情况"},
        "vocab_good": ["调酒专业", "氛围超棒", "音乐好听", "DJ水平高", "环境私密", "拍照出片"],
        "vocab_bad": ["酒水贵", "环境吵闹", "服务冷淡", "音乐太吵", "二手烟重", "安全性差"],
        "details_good": ["鸡尾酒颜值很高", "威士忌选择丰富", "live演出很精彩", "露台视野很好"],
        "details_bad": ["酒水单价格虚高", "音乐声太大没法说话", "服务生爱搭不理", "厕所很脏"],
        "templates": {
            "good": {
                "short": ["{name}氛围{highlight}，超赞！", "{name}酒水不错，{highlight}。"],
                "medium": ["{name}算是{adname}比较火的酒吧，{highlight}。{detail}，{scene}很合适。"],
                "long": ["{name}氛围{env_desc}，{highlight}。{detail}，音乐很棒。{queue_desc}，{people}推荐来。"],
            },
            "neutral": {"short": ["{name}一般，{highlight}中规中矩。"], "medium": ["{name}还行，{highlight}一般，{issue}。"]},
            "bad": {"short": ["{name}不推荐，{highlight}差。"], "medium": ["{name}让人失望，{highlight}不行，{issue}。"]},
        },
        "scenes": ["约会", "朋友聚会", "周末放松", "生日庆祝", "解压"],
        "people": ["年轻人", "潮人", "白领", "夜猫子", "情侣"],
        "comment_count_range": (25, 70),
        "length_weights": {"short": 0.20, "medium": 0.45, "long": 0.35},
    },

    "网吧": {
        "aspect_name": "网吧",
        "dimensions": {"taste": 0, "env": 0.30, "service": 0.20, "value": 0.35, "queue": 0.15},
        "dim_labels": {"taste": "电脑配置", "env": "环境氛围", "service": "服务态度", "value": "性价比", "queue": "等位情况"},
        "vocab_good": ["配置高", "网速快", "环境干净", "座椅舒适", "价格实惠", "零食饮料多"],
        "vocab_bad": ["电脑卡顿", "网速慢", "环境闷", "键盘油腻", "烟味重", "收费高"],
        "details_good": ["RTX 4080显卡", "240Hz显示器", "机械键盘手感好", "包间隔音不错"],
        "details_bad": ["电脑经常死机", "网速延迟高", "耳机有异味", "空调不够冷"],
        "templates": {
            "good": {
                "short": ["{name}配置{highlight}，打游戏很爽！", "{name}环境不错，{highlight}。"],
                "medium": ["{name}算是附近比较不错的网吧，{highlight}。{detail}，{scene}很合适。"],
                "long": ["{name}在{adname}算是高端网咖了，{highlight}。{detail}，环境{env_desc}。{queue_desc}，{people}推荐来。"],
            },
            "neutral": {"short": ["{name}一般，{highlight}中规中矩。"], "medium": ["{name}还行，{highlight}一般，{issue}。"]},
            "bad": {"short": ["{name}不推荐，{highlight}差。"], "medium": ["{name}让人失望，{highlight}不行，{issue}。"]},
        },
        "scenes": ["打游戏", "开黑", "通宵", "休闲", "电竞比赛"],
        "people": ["游戏玩家", "学生党", "年轻人", "电竞爱好者"],
        "comment_count_range": (20, 50),
        "length_weights": {"short": 0.25, "medium": 0.50, "long": 0.25},
    },

    "电影院": {
        "aspect_name": "电影院",
        "dimensions": {"taste": 0, "env": 0.40, "service": 0.25, "value": 0.25, "queue": 0.10},
        "dim_labels": {"taste": "观影效果", "env": "影厅环境", "service": "服务态度", "value": "性价比", "queue": "购票体验"},
        "vocab_good": ["IMAX效果震撼", "座椅舒适", "音响效果好", "屏幕清晰", "检票效率高", "爆米花好吃"],
        "vocab_bad": ["屏幕暗", "音响杂音", "座椅不舒服", "空调太冷", "排队久", "票价贵"],
        "details_good": ["杜比全景声效果超棒", "座椅可以调节角度", "4K屏幕很清晰", "爆米花现爆的很香"],
        "details_bad": ["3D眼镜很脏", "前排座位太挤", "放映时有人进进出出", "空调太冷没毯子"],
        "templates": {
            "good": {
                "short": ["{name}观影{highlight}，体验很棒！", "{name}环境不错，{highlight}。"],
                "medium": ["{name}算是附近比较不错的影院，{highlight}。{detail}，{scene}很合适。"],
                "long": ["{name}在{adname}算是比较新的影院了，{highlight}。{detail}，环境{env_desc}。{queue_desc}，{people}推荐来。"],
            },
            "neutral": {"short": ["{name}一般，{highlight}中规中矩。"], "medium": ["{name}还行，{highlight}一般，{issue}。"]},
            "bad": {"short": ["{name}不推荐，{highlight}差。"], "medium": ["{name}让人失望，{highlight}不行，{issue}。"]},
        },
        "scenes": ["约会", "周末放松", "大片首映", "亲子观影", "独自观影"],
        "people": ["影迷", "情侣", "家庭", "学生党", "年轻人"],
        "comment_count_range": (25, 60),
        "length_weights": {"short": 0.20, "medium": 0.50, "long": 0.30},
    },

    "健身": {
        "aspect_name": "健身",
        "dimensions": {"taste": 0, "env": 0.35, "service": 0.30, "value": 0.25, "queue": 0.10},
        "dim_labels": {"taste": "器械质量", "env": "场馆环境", "service": "教练水平", "value": "性价比", "queue": "高峰拥挤"},
        "vocab_good": ["器械齐全", "环境干净", "教练专业", "课程丰富", "性价比高", "淋浴设施好"],
        "vocab_bad": ["器械老旧", "环境拥挤", "教练推销", "课程少", "收费高", "卫生一般"],
        "details_good": ["自由重量区很大", "跑步机带电视", "瑜伽课老师很专业", "更衣室有密码柜"],
        "details_bad": ["器械维护不好", "高峰期没位置", "私教一直推销", "淋浴水忽冷忽热"],
        "templates": {
            "good": {
                "short": ["{name}器械{highlight}，练得很爽！", "{name}环境不错，{highlight}。"],
                "medium": ["{name}算是附近比较专业的健身房，{highlight}。{detail}，{scene}很合适。"],
                "long": ["{name}在{adname}算是比较新的健身房了，{highlight}。{detail}，环境{env_desc}。{queue_desc}，{people}推荐来。"],
            },
            "neutral": {"short": ["{name}一般，{highlight}中规中矩。"], "medium": ["{name}还行，{highlight}一般，{issue}。"]},
            "bad": {"short": ["{name}不推荐，{highlight}差。"], "medium": ["{name}让人失望，{highlight}不行，{issue}。"]},
        },
        "scenes": ["日常锻炼", "减脂塑形", "增肌", "瑜伽", "团课"],
        "people": ["健身爱好者", "上班族", "学生党", "减脂人群", "瑜伽爱好者"],
        "comment_count_range": (20, 50),
        "length_weights": {"short": 0.20, "medium": 0.55, "long": 0.25},
    },

    "按摩SPA": {
        "aspect_name": "按摩SPA",
        "dimensions": {"taste": 0, "env": 0.30, "service": 0.40, "value": 0.20, "queue": 0.10},
        "dim_labels": {"taste": "技师手法", "env": "环境私密", "service": "服务态度", "value": "性价比", "queue": "预约难度"},
        "vocab_good": ["技师手法专业", "环境私密", "服务贴心", "性价比高", "放松效果好", "精油品质好"],
        "vocab_bad": ["技师手法一般", "环境嘈杂", "推销办卡", "价格虚高", "卫生堪忧", "预约难"],
        "details_good": ["肩颈按摩力度刚好", "足疗穴位准", "房间香薰很好闻", "结束后有养生茶"],
        "details_bad": ["技师按得太轻", "房间隔音差", "一直推销办卡", "毛巾有异味"],
        "templates": {
            "good": {
                "short": ["{name}技师{highlight}，超放松！", "{name}环境很好，{highlight}。"],
                "medium": ["{name}算是附近比较不错的按摩店，{highlight}。{detail}，{scene}很合适。"],
                "long": ["{name}在{adname}算是比较高端的SPA了，{highlight}。{detail}，环境{env_desc}。{queue_desc}，{people}推荐来。"],
            },
            "neutral": {"short": ["{name}一般，{highlight}中规中矩。"], "medium": ["{name}还行，{highlight}一般，{issue}。"]},
            "bad": {"short": ["{name}不推荐，{highlight}差。"], "medium": ["{name}让人失望，{highlight}不行，{issue}。"]},
        },
        "scenes": ["放松解压", "周末犒劳", "运动后恢复", "闺蜜聚会", "商务接待"],
        "people": ["上班族", "运动爱好者", "养生人群", "商务人士", "女性"],
        "comment_count_range": (20, 50),
        "length_weights": {"short": 0.20, "medium": 0.55, "long": 0.25},
    },

    # ========== 景点/公园 ==========
    "景点": {
        "aspect_name": "景点",
        "dimensions": {"taste": 0, "env": 0.45, "service": 0.15, "value": 0.25, "queue": 0.15},
        "dim_labels": {"taste": "景色质量", "env": "游览环境", "service": "服务质量", "value": "门票性价比", "queue": "人流拥挤"},
        "vocab_good": ["景色优美", "历史文化", "拍照出片", "设施完善", "导游专业", "值得再来"],
        "vocab_bad": ["商业化严重", "人多拥挤", "门票贵", "设施老旧", "导游敷衍", "没啥可看"],
        "details_good": ["古建筑保存完好", "山顶视野开阔", "讲解很详细", "文创产品精致"],
        "details_bad": ["到处都是卖东西的", "厕所很脏", "指示牌不清楚", "门票贵不值"],
        "templates": {
            "good": {
                "short": ["{name}景色{highlight}，值得一去！", "{name}很有特色，{highlight}。"],
                "medium": ["{name}算是{adname}比较有代表性的景点，{highlight}。{detail}，{scene}很合适。"],
                "long": ["{name}在{adname}算是必打卡的景点了，{highlight}。{detail}，环境{env_desc}。{queue_desc}，{people}推荐来。"],
            },
            "neutral": {"short": ["{name}一般，{highlight}中规中矩。"], "medium": ["{name}还行，{highlight}一般，{issue}。"]},
            "bad": {"short": ["{name}不推荐，{highlight}差。"], "medium": ["{name}让人失望，{highlight}不行，{issue}。"]},
        },
        "scenes": ["周末出游", "亲子游", "拍照打卡", "文化体验", "情侣约会"],
        "people": ["游客", "本地人", "摄影爱好者", "文化爱好者", "家庭"],
        "comment_count_range": (30, 90),
        "length_weights": {"short": 0.15, "medium": 0.40, "long": 0.45},
    },

    "公园": {
        "aspect_name": "公园",
        "dimensions": {"taste": 0, "env": 0.50, "service": 0.10, "value": 0.30, "queue": 0.10},
        "dim_labels": {"taste": "绿化景观", "env": "休闲环境", "service": "管理维护", "value": "免费开放", "queue": "人流密度"},
        "vocab_good": ["绿树成荫", "空气清新", "设施完善", "适合散步", "免费开放", "环境优美"],
        "vocab_bad": ["绿化一般", "设施损坏", "人多嘈杂", "卫生差", "管理不善", "蚊子多"],
        "details_good": ["湖边的柳树很美", "步道很适合跑步", "儿童游乐区很安全", "有专门的遛狗区"],
        "details_bad": ["草坪被踩秃了", "健身器材生锈", "湖里水质不好", "晚上灯光太暗"],
        "templates": {
            "good": {
                "short": ["{name}环境{highlight}，适合散步！", "{name}绿化很好，{highlight}。"],
                "medium": ["{name}算是{adname}比较不错的公园，{highlight}。{detail}，{scene}很合适。"],
                "long": ["{name}在{adname}算是居民休闲的好去处，{highlight}。{detail}，环境{env_desc}。{queue_desc}，{people}推荐来。"],
            },
            "neutral": {"short": ["{name}一般，{highlight}中规中矩。"], "medium": ["{name}还行，{highlight}一般，{issue}。"]},
            "bad": {"short": ["{name}不推荐，{highlight}差。"], "medium": ["{name}让人失望，{highlight}不行，{issue}。"]},
        },
        "scenes": ["晨练", "散步", "亲子活动", "遛狗", "周末野餐", "跑步"],
        "people": ["老年人", "亲子家庭", "跑步爱好者", "遛弯居民", "情侣"],
        "comment_count_range": (25, 70),
        "length_weights": {"short": 0.15, "medium": 0.50, "long": 0.35},
    },

    "游乐园": {
        "aspect_name": "游乐园",
        "dimensions": {"taste": 0, "env": 0.40, "service": 0.20, "value": 0.25, "queue": 0.15},
        "dim_labels": {"taste": "游乐设施", "env": "园区环境", "service": "服务态度", "value": "性价比", "queue": "排队时间"},
        "vocab_good": ["设施刺激", "项目丰富", "安全措施到位", "工作人员热情", "适合全家", "值回票价"],
        "vocab_bad": ["设施老旧", "项目少", "排队太久", "服务态度差", "票价贵", "安全隐患"],
        "details_good": ["过山车超刺激", "旋转木马很漂亮", "4D影院效果很好", "花车巡游很精彩"],
        "details_bad": ["过山车维修中", "排队两小时玩五分钟", "工作人员态度恶劣", "餐饮贵得离谱"],
        "templates": {
            "good": {
                "short": ["{name}设施{highlight}，玩得很开心！", "{name}适合带孩子，{highlight}。"],
                "medium": ["{name}算是{adname}比较受欢迎的游乐园，{highlight}。{detail}，{scene}很合适。"],
                "long": ["{name}在{adname}算是比较大的游乐园了，{highlight}。{detail}，环境{env_desc}。{queue_desc}，{people}推荐来。"],
            },
            "neutral": {"short": ["{name}一般，{highlight}中规中矩。"], "medium": ["{name}还行，{highlight}一般，{issue}。"]},
            "bad": {"short": ["{name}不推荐，{highlight}差。"], "medium": ["{name}让人失望，{highlight}不行，{issue}。"]},
        },
        "scenes": ["亲子游", "朋友聚会", "情侣约会", "生日庆祝", "周末放松"],
        "people": ["亲子家庭", "年轻人", "学生", "情侣", "胆大的"],
        "comment_count_range": (30, 80),
        "length_weights": {"short": 0.18, "medium": 0.45, "long": 0.37},
    },

    # ========== 购物类 ==========
    "商场": {
        "aspect_name": "商场",
        "dimensions": {"taste": 0, "env": 0.35, "service": 0.25, "value": 0.25, "queue": 0.15},
        "dim_labels": {"taste": "品牌丰富度", "env": "购物环境", "service": "服务体验", "value": "活动优惠", "queue": "停车难易"},
        "vocab_good": ["品牌齐全", "环境舒适", "活动多", "餐饮丰富", "停车方便", "适合逛街"],
        "vocab_bad": ["品牌少", "环境拥挤", "服务态度差", "活动少", "停车难", "吃饭排队"],
        "details_good": ["国际大牌很多", "空调温度合适", "经常有打折活动", "顶楼餐饮选择多"],
        "details_bad": ["很多品牌撤柜了", "空调不给力", "停车位难找", "吃饭每一家都排队"],
        "templates": {
            "good": {
                "short": ["{name}品牌{highlight}，很好逛！", "{name}环境不错，{highlight}。"],
                "medium": ["{name}算是{adname}比较受欢迎的商场，{highlight}。{detail}，{scene}很合适。"],
                "long": ["{name}在{adname}算是地标商场了，{highlight}。{detail}，环境{env_desc}。{queue_desc}，{people}推荐来。"],
            },
            "neutral": {"short": ["{name}一般，{highlight}中规中矩。"], "medium": ["{name}还行，{highlight}一般，{issue}。"]},
            "bad": {"short": ["{name}不推荐，{highlight}差。"], "medium": ["{name}让人失望，{highlight}不行，{issue}。"]},
        },
        "scenes": ["周末逛街", "约会", "亲子购物", "吃饭聚餐", "看电影"],
        "people": ["年轻人", "家庭", "白领", "游客", "购物狂"],
        "comment_count_range": (25, 60),
        "length_weights": {"short": 0.20, "medium": 0.50, "long": 0.30},
    },

    "超市": {
        "aspect_name": "超市",
        "dimensions": {"taste": 0, "env": 0.25, "service": 0.20, "value": 0.40, "queue": 0.15},
        "dim_labels": {"taste": "商品品质", "env": "购物环境", "service": "收银效率", "value": "性价比", "queue": "排队长短"},
        "vocab_good": ["商品齐全", "新鲜度高", "价格划算", "环境整洁", "收银快", "会员优惠多"],
        "vocab_bad": ["商品不全", "生鲜不新鲜", "价格贵", "环境拥挤", "收银慢", "服务差"],
        "details_good": ["蔬菜水果很新鲜", "进口商品种类多", "自有品牌性价比高", "自助结账很方便"],
        "details_bad": ["很多商品缺货", "肉类不新鲜", "标价和结算价不一致", "收银排队太久"],
        "templates": {
            "good": {
                "short": ["{name}商品{highlight}，常来采购！", "{name}价格实惠，{highlight}。"],
                "medium": ["{name}算是附近比较方便的超市，{highlight}。{detail}，{scene}很合适。"],
                "long": ["{name}在{adname}算是比较大的超市了，{highlight}。{detail}，环境{env_desc}。{queue_desc}，{people}推荐来。"],
            },
            "neutral": {"short": ["{name}一般，{highlight}中规中矩。"], "medium": ["{name}还行，{highlight}一般，{issue}。"]},
            "bad": {"short": ["{name}不推荐，{highlight}差。"], "medium": ["{name}让人失望，{highlight}不行，{issue}。"]},
        },
        "scenes": ["日常采购", "囤货", "买生鲜", "周末大采购", "应急购物"],
        "people": ["家庭主妇", "上班族", "老年人", "附近居民"],
        "comment_count_range": (15, 40),
        "length_weights": {"short": 0.30, "medium": 0.55, "long": 0.15},
    },

    "便利店": {
        "aspect_name": "便利店",
        "dimensions": {"taste": 0, "env": 0.15, "service": 0.20, "value": 0.45, "queue": 0.20},
        "dim_labels": {"taste": "鲜食品质", "env": "店面整洁", "service": "服务效率", "value": "性价比", "queue": "结账快慢"},
        "vocab_good": ["24小时营业", "关东煮好吃", "位置方便", "结账快", "商品更新快", "促销活动多"],
        "vocab_bad": ["商品不新鲜", "价格贵", "店面小", "服务差", "经常缺货", "卫生一般"],
        "details_good": ["热食区经常有新品", "早餐选择多", "位置就在地铁口", "员工态度很好"],
        "details_bad": ["便当过期了还在卖", "比超市贵很多", "店面太小转不开身", "冰柜温度不够"],
        "templates": {
            "good": {
                "short": ["{name}很方便，{highlight}！", "{name}位置好，{highlight}。"],
                "medium": ["{name}算是附近比较方便的便利店，{highlight}。{detail}，{scene}很合适。"],
                "long": ["{name}在{adname}算是比较正规的便利店了，{highlight}。{detail}，环境{env_desc}。{queue_desc}，{people}推荐来。"],
            },
            "neutral": {"short": ["{name}一般，{highlight}中规中矩。"], "medium": ["{name}还行，{highlight}一般，{issue}。"]},
            "bad": {"short": ["{name}不推荐，{highlight}差。"], "medium": ["{name}让人失望，{highlight}不行，{issue}。"]},
        },
        "scenes": ["应急购物", "买早餐", "深夜觅食", "买水", "快速结账"],
        "people": ["上班族", "夜猫子", "附近居民", "学生党"],
        "comment_count_range": (10, 30),
        "length_weights": {"short": 0.40, "medium": 0.50, "long": 0.10},
    },

    "数码": {
        "aspect_name": "数码",
        "dimensions": {"taste": 0, "env": 0.20, "service": 0.35, "value": 0.30, "queue": 0.15},
        "dim_labels": {"taste": "产品质量", "env": "店面环境", "service": "售后维修", "value": "性价比", "queue": "排队等待"},
        "vocab_good": ["正品保障", "维修专业", "价格合理", "配件齐全", "服务态度好", "技术过硬"],
        "vocab_bad": ["假货", "维修乱收费", "态度差", "配件贵", "技术一般", "等太久"],
        "details_good": ["换屏速度很快", "原装配件", "维修过程透明", "保修期长"],
        "details_bad": ["换的配件不是原装", "收费比官方贵", "修完还有问题", "服务态度恶劣"],
        "templates": {
            "good": {
                "short": ["{name}维修{highlight}，靠谱！", "{name}服务好，{highlight}。"],
                "medium": ["{name}算是附近比较专业的数码店，{highlight}。{detail}，{scene}很合适。"],
                "long": ["{name}在{adname}算是比较正规的数码维修店了，{highlight}。{detail}，环境{env_desc}。{queue_desc}，{people}推荐来。"],
            },
            "neutral": {"short": ["{name}一般，{highlight}中规中矩。"], "medium": ["{name}还行，{highlight}一般，{issue}。"]},
            "bad": {"short": ["{name}不推荐，{highlight}差。"], "medium": ["{name}让人失望，{highlight}不行，{issue}。"]},
        },
        "scenes": ["修手机", "买配件", "电脑维修", "数据恢复", "贴膜"],
        "people": ["数码爱好者", "上班族", "学生", "手机党"],
        "comment_count_range": (15, 40),
        "length_weights": {"short": 0.25, "medium": 0.55, "long": 0.20},
    },

    "服饰": {
        "aspect_name": "服饰",
        "dimensions": {"taste": 0, "env": 0.30, "service": 0.30, "value": 0.30, "queue": 0.10},
        "dim_labels": {"taste": "款式质量", "env": "试衣环境", "service": "导购服务", "value": "性价比", "queue": "排队试衣"},
        "vocab_good": ["款式新颖", "质量过硬", "价格合理", "试衣间干净", "导购专业", "退换方便"],
        "vocab_bad": ["款式老气", "质量差", "价格虚高", "试衣间少", "导购跟着", "不让试穿"],
        "details_good": ["新款上架很快", "面料摸起来很舒服", "尺码很全", "导购搭配建议很实用"],
        "details_bad": ["线头很多", "洗完缩水", "尺码偏小", "导购态度冷淡"],
        "templates": {
            "good": {
                "short": ["{name}款式{highlight}，满意！", "{name}质量不错，{highlight}。"],
                "medium": ["{name}算是附近比较受欢迎的服饰店，{highlight}。{detail}，{scene}很合适。"],
                "long": ["{name}在{adname}算是比较有名的服装店了，{highlight}。{detail}，环境{env_desc}。{queue_desc}，{people}推荐来。"],
            },
            "neutral": {"short": ["{name}一般，{highlight}中规中矩。"], "medium": ["{name}还行，{highlight}一般，{issue}。"]},
            "bad": {"short": ["{name}不推荐，{highlight}差。"], "medium": ["{name}让人失望，{highlight}不行，{issue}。"]},
        },
        "scenes": ["日常购物", "换季采购", "约会前打扮", "逛街", "送礼"],
        "people": ["年轻人", "上班族", "学生", "时尚爱好者", "女性"],
        "comment_count_range": (20, 50),
        "length_weights": {"short": 0.25, "medium": 0.50, "long": 0.25},
    },

    "美妆": {
        "aspect_name": "美妆",
        "dimensions": {"taste": 0, "env": 0.25, "service": 0.35, "value": 0.25, "queue": 0.15},
        "dim_labels": {"taste": "产品品质", "env": "店面环境", "service": "服务体验", "value": "性价比", "queue": "预约难度"},
        "vocab_good": ["产品正品", "手法专业", "环境舒适", "效果明显", "价格透明", "不推销"],
        "vocab_bad": ["产品可疑", "手法一般", "环境一般", "效果不明显", "乱收费", "一直推销"],
        "details_good": ["护肤品都是大牌", "美容师手法很轻柔", "做完脸皮肤很亮", "没有任何推销"],
        "details_bad": ["产品闻着不对", "做完脸过敏了", "一直让办卡", "价格不透明"],
        "templates": {
            "good": {
                "short": ["{name}服务{highlight}，效果好！", "{name}环境很好，{highlight}。"],
                "medium": ["{name}算是附近比较专业的美妆店，{highlight}。{detail}，{scene}很合适。"],
                "long": ["{name}在{adname}算是比较高端的美妆店了，{highlight}。{detail}，环境{env_desc}。{queue_desc}，{people}推荐来。"],
            },
            "neutral": {"short": ["{name}一般，{highlight}中规中矩。"], "medium": ["{name}还行，{highlight}一般，{issue}。"]},
            "bad": {"short": ["{name}不推荐，{highlight}差。"], "medium": ["{name}让人失望，{highlight}不行，{issue}。"]},
        },
        "scenes": ["护肤", "美甲", "美发", "化妆", "约会前准备"],
        "people": ["女性", "爱美人士", "上班族", "学生", "新娘"],
        "comment_count_range": (20, 50),
        "length_weights": {"short": 0.20, "medium": 0.50, "long": 0.30},
    },

    "家居": {
        "aspect_name": "家居",
        "dimensions": {"taste": 0, "env": 0.20, "service": 0.30, "value": 0.35, "queue": 0.15},
        "dim_labels": {"taste": "产品质量", "env": "展厅环境", "service": "设计安装", "value": "性价比", "queue": "工期长短"},
        "vocab_good": ["质量不错", "设计专业", "价格合理", "安装到位", "售后及时", "材料环保"],
        "vocab_bad": ["质量一般", "设计老套", "价格虚高", "安装粗糙", "售后差", "材料有异味"],
        "details_good": ["板材没有异味", "设计师沟通很耐心", "安装师傅手艺好", "售后响应很快"],
        "details_bad": ["柜子门板不平", "设计图和实际差很多", "安装完有缝隙", "售后电话打不通"],
        "templates": {
            "good": {
                "short": ["{name}质量{highlight}，满意！", "{name}服务到位，{highlight}。"],
                "medium": ["{name}算是附近比较靠谱的家居店，{highlight}。{detail}，{scene}很合适。"],
                "long": ["{name}在{adname}算是比较有名的家居店了，{highlight}。{detail}，环境{env_desc}。{queue_desc}，{people}推荐来。"],
            },
            "neutral": {"short": ["{name}一般，{highlight}中规中矩。"], "medium": ["{name}还行，{highlight}一般，{issue}。"]},
            "bad": {"short": ["{name}不推荐，{highlight}差。"], "medium": ["{name}让人失望，{highlight}不行，{issue}。"]},
        },
        "scenes": ["装修", "买家具", "软装搭配", "旧房改造", "新房布置"],
        "people": ["装修业主", "新婚夫妇", "家庭主妇", "设计师"],
        "comment_count_range": (15, 40),
        "length_weights": {"short": 0.25, "medium": 0.55, "long": 0.20},
    },

    # ========== 住宿 ==========
    "住宿": {
        "aspect_name": "住宿",
        "dimensions": {"taste": 0.15, "env": 0.35, "service": 0.30, "value": 0.15, "queue": 0.05},
        "dim_labels": {"taste": "早餐品质", "env": "房间卫生", "service": "前台服务", "value": "性价比", "queue": "入住退房"},
        "vocab_good": ["房间干净", "床品舒适", "服务热情", "位置方便", "早餐丰富", "隔音好"],
        "vocab_bad": ["房间脏", "床品有异味", "服务冷淡", "位置偏", "早餐差", "隔音差"],
        "details_good": ["床垫软硬适中", "卫生间干湿分离", "前台24小时有人", "离地铁站很近"],
        "details_bad": ["床单上有头发", "卫生间有异味", "空调噪音大", "周边吃饭不方便"],
        "templates": {
            "good": {
                "short": ["{name}房间{highlight}，住得舒服！", "{name}服务很好，{highlight}。"],
                "medium": ["{name}算是{adname}比较不错的住宿，{highlight}。{detail}，{scene}很合适。"],
                "long": ["{name}在{adname}算是比较受欢迎的酒店了，{highlight}。{detail}，环境{env_desc}。{queue_desc}，{people}推荐来。"],
            },
            "neutral": {"short": ["{name}一般，{highlight}中规中矩。"], "medium": ["{name}还行，{highlight}一般，{issue}。"]},
            "bad": {"short": ["{name}不推荐，{highlight}差。"], "medium": ["{name}让人失望，{highlight}不行，{issue}。"]},
        },
        "scenes": ["商务出差", "旅游住宿", "情侣约会", "家庭出游", "临时休息"],
        "people": ["商务人士", "游客", "情侣", "家庭", "出差党"],
        "comment_count_range": (25, 70),
        "length_weights": {"short": 0.20, "medium": 0.50, "long": 0.30},
    },

    # ========== 其他 ==========
    "其他": {
        "aspect_name": "店铺",
        "dimensions": {"taste": 0.20, "env": 0.25, "service": 0.25, "value": 0.20, "queue": 0.10},
        "dim_labels": {"taste": "产品质量", "env": "店面环境", "service": "服务态度", "value": "性价比", "queue": "等待时间"},
        "vocab_good": ["质量不错", "环境整洁", "服务好", "价格合理", "位置方便", "值得推荐"],
        "vocab_bad": ["质量一般", "环境差", "服务冷淡", "价格贵", "位置偏", "不推荐"],
        "details_good": ["产品用起来很满意", "店面收拾得很干净", "老板态度很好", "性价比超出预期"],
        "details_bad": ["产品质量不如预期", "店面有点乱", "工作人员爱答不理", "价格比其他店贵"],
        "templates": {
            "good": {
                "short": ["{name}整体{highlight}，满意！", "{name}不错，{highlight}。"],
                "medium": ["{name}算是附近比较不错的店，{highlight}。{detail}，{scene}很合适。"],
                "long": ["{name}在{adname}算是比较有名的店了，{highlight}。{detail}，环境{env_desc}。{queue_desc}，{people}推荐来。"],
            },
            "neutral": {"short": ["{name}一般，{highlight}中规中矩。"], "medium": ["{name}还行，{highlight}一般，{issue}。"]},
            "bad": {"short": ["{name}不推荐，{highlight}差。"], "medium": ["{name}让人失望，{highlight}不行，{issue}。"]},
        },
        "scenes": ["日常消费", "临时需要", "朋友推荐", "随便逛逛"],
        "people": ["附近居民", "上班族", "学生", "路人"],
        "comment_count_range": (15, 40),
        "length_weights": {"short": 0.30, "medium": 0.50, "long": 0.20},
    },
}


# 统一问题库（各类型通用）
MINOR_ISSUES = [
    "位置不太好找", "停车位紧张", "高峰期要等", "座位有点挤",
    "价格略贵", "装修有点旧", "服务员不够热情", "菜单选择不多",
    "卫生一般", "空调不够冷", "灯光太暗", "wifi信号差",
]

MAJOR_ISSUES = [
    "排队时间太长", "服务态度恶劣", "价格和描述不符", "环境脏乱差",
    "强制消费", "上错菜", "餐具不干净", "音响太吵",
    "温度不适宜", "安全隐患", "虚假宣传", "不退不换",
]


def get_profile(real_type):
    """获取类型画像，若不存在则返回'其他'"""
    return TYPE_PROFILES.get(real_type, TYPE_PROFILES["其他"])


# ========== 类型修正（ workaround：修正 type_index 中的明显错误 ）==========

# 基于名称的强制类型映射（覆盖 type_index 中的错误标注）
_NAME_OVERRIDE_PATTERNS = {
    "住宿": ["酒店", "宾馆", "客栈", "民宿", "公寓", "旅馆", "招待所", "度假村", "别墅", "快捷酒店", "连锁酒店", "商务酒店", "青年旅舍", "锦江之星", "如家", "汉庭", "7天", "布丁酒店", "全季", "亚朵", "桔子水晶", "维也纳", "速8", "莫泰", "格林豪泰", "假日酒店", "喜来登", "希尔顿", "香格里拉", "凯悦", "万豪", "洲际"],
    "火锅": ["火锅", "串串", "麻辣烫", "冒菜", "九宫格", "老灶", "牛油锅"],
    "小吃": ["小吃", "包子", "饺子", "馄饨", "锅盔", "凉粉", "冰粉", "钵钵鸡", "兔头", "肥肠", "肉夹馍", "炸鸡", "汉堡", "烤苕皮", "烤豆腐", "包浆豆腐"],
    "茶馆": ["茶馆", "茶楼", "茶舍", "茶坊", "茶室", "茶园", "茶艺馆"],
    "中餐": ["川菜馆", "家常菜", "私房菜", "江湖菜", "酒楼", "食府", "餐厅", "菜馆", "土菜馆"],
    "烧烤": ["烧烤", "烤串", "烤肉", "烤鱼", "炭烤"],
    "饮品": ["奶茶", "咖啡", "茶饮", "果汁", "酸奶", "奶昔", "coffee", "cafe", "espresso", "latte", "cappuccino", "mocha", "星巴克", "瑞幸", "starbucks", "luckin"],
    "甜品": ["蛋糕", "甜品", "面包", "烘焙", "糕点", "冰淇淋", "绵绵冰", "布丁", "蛋挞", "五芳斋", "月饼", "粽子", "酥", "糖"],
    "KTV": ["KTV", "量贩", "歌城", "唱吧", "卡拉OK"],
    "酒吧": ["酒吧", "酒馆", "夜店", "清吧", "精酿", "啤酒屋"],
    "电影院": ["电影", "影院", "影城", "IMAX"],
    "健身": ["健身", "瑜伽", "舞蹈", "普拉提", "游泳馆"],
    "按摩SPA": ["按摩", "足疗", "SPA", "养生", "推拿", "洗浴", "汗蒸", "采耳"],
    "公园": ["公园", "绿地", "湿地"],
    "景点": ["景区", "古迹", "寺庙", "博物馆", "纪念馆", "观景台", "塔"],
    "游乐园": ["游乐园", "游乐场", "乐园", "摩天轮"],
    "商场": ["商场", "购物中心", "百货", "奥特莱斯", "商业街"],
    "超市": ["超市", "卖场", "仓储", "生鲜", "鲜疏坊", "菜市场", "农贸市场", "菜市"],
    "便利店": ["便利店", "小卖部", "杂货", "24小时", "红旗连锁"],
    "数码": ["手机", "电脑", "数码", "电子", "家电"],
    "服饰": ["服装", "服饰", "女装", "男装", "童装", "鞋店", "鞋城", "皮鞋", "运动鞋", "女鞋", "男鞋", "童鞋", "高跟鞋", "包包", "皮包", "背包", "旅行包", "手提包", "钱包"],
    "美妆": ["美妆", "化妆品", "护肤", "美容", "美甲", "美发", "理发", "面膜", "樊文花", "希思黎", "娇韵诗", "香奈儿", "兰蔻", "迪奥", "雅诗兰黛", "资生堂", "欧莱雅", "sk-ii", "mac"],
    "家居": ["家具", "家居", "建材", "装饰", "灯饰", "地板", "瓷砖"],
    "其他": ["小区", "住宅", "楼栋", "单元", "号院", "号门", "公寓", "大厦", "写字楼", "商务楼", "菜鸟驿站", "快递", "速递", "丰巢", "菜鸟"],
    "医疗": ["医院", "诊所", "药店", "口腔", "眼科", "体检", "中医馆", "整形", "医美", "美容医院", "植发", "牙科"],
    "培训": ["培训", "辅导", "补习班", "琴行", "画室", "驾校"],
    "宠物": ["宠物", "兽医", "宠物医院"],
    "汽车": ["汽修", "保养", "洗车", "4S店", "轮胎"],
}


def correct_type(poi, current_type):
    """
    基于 POI 名称修正 type_index 中的明显错误类型。
    """
    name = clean_name(poi.get("name", ""))
    name_lower = name.lower()
    
    # 基于名称推断真实类型（先计算，供后续修正逻辑使用）
    inferred = None
    for typ, keywords in _NAME_OVERRIDE_PATTERNS.items():
        for kw in keywords:
            if kw.lower() in name_lower or kw in name:
                inferred = typ
                break
        if inferred:
            break
    
    # fallback：如果 _NAME_OVERRIDE_PATTERNS 没匹配到，使用 infer_real_type
    if not inferred:
        inferred = infer_real_type(poi)
    
    # 先处理特殊格式：商场品牌店（如"鄂尔多斯(仁和春天百货店)"被标为"商场"）
    # 商场内部的品牌专柜/店铺被错标为"商场"，应修正为"购物"
    # 扩展：不仅限于"品牌(商场名)"格式，任何不含真正商场关键词的"商场"类型POI都可能是误判
    if current_type == "商场":
        # 检查是否含真正的商场关键词（"mall"需为独立单词，避免匹配"SmallCompanyCoffee"）
        has_mall_keyword = any(kw in name for kw in ["百货", "购物中心", "商场", "奥特莱斯"])
        if not has_mall_keyword:
            import re
            has_mall_keyword = re.search(r'(?i)\bmall\b', name) is not None
        if not has_mall_keyword:
            # 名称不含商场关键词，说明是商场内店铺（如咖啡店、服装店等）
            # 如果有推断类型且不是"商场"，返回推断类型；否则降级为"购物"
            return inferred if inferred and inferred != "商场" else "购物"
    
    # 如果当前类型是"其他"，直接返回推断类型
    if current_type == "其他":
        return inferred
    
    # 如果推断类型与当前类型属于同一大类，保留当前类型（更细粒度，避免过度修正）
    # 但商场品牌店例外：即使infer_real_type也返回"商场"（因名称含"百货"），仍需修正
    from route_planner_v3 import _get_category
    if _get_category(inferred) == _get_category(current_type):
        # 再次检查商场品牌店（防止infer_real_type误判）
        if current_type == "商场" and "(" in name:
            brand_part = name.split("(")[0].strip()
            mall_kws = ["百货", "购物中心", "商场", "奥特莱斯"]
            has_mall_kw = any(kw in brand_part for kw in mall_kws)
            if not has_mall_kw:
                import re
                has_mall_kw = re.search(r'(?i)\bmall\b', brand_part) is not None
            if brand_part and not has_mall_kw:
                return "购物"
        return current_type
    
    # 如果当前类型是住宿/医疗/培训/宠物/汽车，但名称明显指向其他类型，修正
    if current_type in ("住宿", "医疗", "培训", "宠物", "汽车"):
        return inferred
    
    # 如果推断类型是住宿/医疗/培训/宠物/汽车（高确定性类型），且当前类型不是这些，修正
    if inferred in ("住宿", "医疗", "培训", "宠物", "汽车"):
        return inferred
    
    # 核心修正：名称推断的类型与当前类型不同大类，优先名称推断
    # 这能修正大量 type_index 错误（如"五芳斋"被标为"景点"、"coffee"被标为"商场"）
    if current_type in ("其他", "购物", "数码", "服饰", "美妆", "家居", "景点", "休闲", "公园", "游乐园"):
        return inferred
    
    # 兜底：如果推断类型是"其他"但当前类型是景点/公园/游乐园（名称无特征却被标为景点），降级
    if inferred == "其他" and current_type in ("景点", "公园", "游乐园"):
        return inferred
    
    return current_type
