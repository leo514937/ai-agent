#!/usr/bin/env python3
"""
generate_and_import_mock_data.py

Generate 100 shops (×10 local-life categories) + 300 vouchers (3 per shop)
+ users + blogs + blog comments + follow relationships.
All data is realistic Chinese local-life content targeting Hangzhou/Beijing/Shanghai/Shenzhen.

Usage:
    python scripts/generate_and_import_mock_data.py

Environment:
    Uses mysql.connector to connect to localhost:3306/hmdp
    (credentials from application.yaml: root / 123456)
"""

from __future__ import annotations

import json
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import mysql.connector

# ── DB config (matches application.yaml) ──────────────────────
DB_CONFIG = {
    "host": "localhost",
    "port": 3306,
    "database": "hmdp",
    "user": "root",
    "password": "123456",
}

# ── Seed for reproducibility ──────────────────────────────────
RNG = random.Random(42)

# ── Shop type definitions (from tb_shop_type) ─────────────────
SHOP_TYPES: list[dict[str, Any]] = [
    {"id": 1, "name": "美食", "icon": "/types/ms.png", "sort": 1},
    {"id": 2, "name": "KTV", "icon": "/types/KTV.png", "sort": 2},
    {"id": 3, "name": "丽人·美发", "icon": "/types/lrmf.png", "sort": 3},
    {"id": 4, "name": "健身运动", "icon": "/types/jsyd.png", "sort": 10},
    {"id": 5, "name": "按摩·足疗", "icon": "/types/amzl.png", "sort": 5},
    {"id": 6, "name": "美容SPA", "icon": "/types/spa.png", "sort": 6},
    {"id": 7, "name": "亲子游乐", "icon": "/types/qzyl.png", "sort": 7},
    {"id": 8, "name": "酒吧", "icon": "/types/jiuba.png", "sort": 8},
    {"id": 9, "name": "轰趴馆", "icon": "/types/hpg.png", "sort": 9},
    {"id": 10, "name": "美睫·美甲", "icon": "/types/mjmj.png", "sort": 4},
]

# ── Shop names per type (10-20 names each, realistic) ─────────
SHOP_NAMES_BY_TYPE: dict[int, list[str]] = {
    1: [  # 美食
        "老北京炸酱面馆", "川味观·麻辣火锅", "粤港茶餐厅", "西北人家·羊肉泡馍",
        "湘辣人家", "东北铁锅炖", "日式拉面道场", "泰味小馆",
        "海底捞火锅(湖滨店)", "西堤牛排(万象城店)", "外婆家(西湖店)", "楼外楼·经典杭帮菜",
        "鼎泰丰(国贸店)", "大董烤鸭(三里屯店)", "陈麻花·重庆老火锅", "小龙坎火锅(春熙路店)",
        "太二酸菜鱼(天河城店)", "点都德(北京路店)", "穗香酒家·广式早茶", "味千拉面(中山路店)",
    ],
    2: [  # KTV
        "纯K量贩KTV(湖滨店)", "星聚会KTV(万达店)", "魅KTV(远洋乐堤港店)", "唱吧麦颂KTV",
        "温莎KTV(国贸店)", "酷秀KTV(解放碑店)", "V·SHOW KTV(新天地店)", "agogo KTV(华强北店)",
    ],
    3: [  # 丽人·美发
        "永琪美容美发(朝晖店)", "文峰美容美发(古墩路店)", "东瀛造型(恒隆广场店)", "椰岛造型(来福士店)",
        "梵创形象设计(湖滨银泰店)", "乔治发型(万象天地店)", "InStyle造型(三里屯店)", "TONI&GUY(国金店)",
        "沙宣美发学院(KKMALL店)", "秀·美容美发(龙湖天街店)",
    ],
    4: [  # 健身运动
        "乐刻健身(运河上街店)", "超级猩猩(来福士店)", "威尔仕健身(万象城店)", "一兆韦德(恒隆店)",
        "Keep Fit健身工作室(钱江新城店)", "中田健身(水晶城店)", "古德菲力(COCO Park店)", "金吉鸟健身(万达店)",
    ],
    5: [  # 按摩·足疗
        "郑远元专业修脚房(文二路店)", "足本记·足道养生(湖滨店)", "金色印象·影院式足体养生(解放碑店)", "金泰元·SPA足道(体育场店)",
        "华夏良子(朝外大街店)", "常乐足道(五一广场店)", "合和大唐(光谷店)", "大班SPA·足道(华侨城店)",
        "上品足道(西湖文化广场店)", "康悦故事·足道(武林店)",
    ],
    6: [  # 美容SPA
        "美丽田园·SPA(万象城店)", "思妍丽(恒隆店)", "克丽缇娜(龙湖天街店)", "自然美·SPA(湖滨道店)",
        "iSpa(东方广场店)", "悦椿SPA(南山区店)", "水之梦·SPA(中南路店)", "兰诺·轻奢SPA(国金店)",
    ],
    7: [  # 亲子游乐
        "莫莉幻想·亲子乐园(万达店)", "汤姆熊欢乐世界(万象城店)", "奇乐儿主题公园(宝龙店)", "Meland儿童成长中心(龙湖天街店)",
        "卡通尼乐园(印象城店)", "粒粒堡亲子餐厅(钱江新城店)", "宝燕乐园(虹桥店)", "奈尔宝家庭中心(黄龙店)",
    ],
    8: [  # 酒吧
        "Helens海伦司小酒馆(河坊街店)", "贰麻酒馆(九眼桥店)", "Perrys(滨江店)", "SPACE PLUS(太古里店)",
        "MUSE CLUB(南山店)", "MOKIHOUSE(新天地店)", "SOS CLUB(龙湖店)", "17 Party House(黄兴路店)",
        "86 CLUB(嘉里中心店)", "MAGO CLUB(春熙路店)",
    ],
    9: [  # 轰趴馆
        "乌托邦轰趴馆(下沙店)", "拉勾勾轰趴馆(滨江店)", "小目标·别墅轰趴(湘湖店)", "趣轰趴(未来科技城店)",
        "66号轰趴馆(五角场店)", "大玩家·潮玩轰趴(夫子庙店)", "WOOHOO轰趴馆(思明区店)", "派对工场·别墅轰趴(华侨城店)",
    ],
    10: [  # 美睫·美甲
        "InNail(万象城店)", "Lily Nail(湖滨银泰店)", "刘娟美甲(国金中心店)", "爱睫物语(恒隆店)",
        "樱美·美甲美睫(来福士店)", "MISS NAIL(龙湖天街店)", "悦指间·美甲美睫(万达店)", "漫漫美甲(三里屯店)",
        "D·NAIL美甲(武林店)", "MEET NAIL·美甲美睫(钱江新城店)",
    ],
}

# ── Address / Area / Coordinates per city ─────────────────────
CITY_CONFIGS: list[dict[str, Any]] = [
    {
        "city": "杭州",
        "areas": ["西湖区", "拱墅区", "上城区", "滨江区", "余杭区", "萧山区", "钱塘区", "西湖风景名胜区"],
        "x_range": (120.05, 120.35),
        "y_range": (30.20, 30.40),
        "streets": ["延安路", "凤起路", "庆春路", "体育场路", "解放路", "文三路",
                     "学院路", "古墩路", "余杭塘路", "江南大道", "市心路", "钱江路"],
    },
    {
        "city": "北京",
        "areas": ["朝阳区", "海淀区", "东城区", "西城区", "丰台区", "大兴区", "通州区"],
        "x_range": (116.20, 116.60),
        "y_range": (39.75, 40.05),
        "streets": ["建国路", "三里屯路", "望京街", "中关村大街", "五道口", "西单北大街",
                     "王府井大街", "长安街", "朝阳北路", "亮马桥路"],
    },
    {
        "city": "上海",
        "areas": ["黄浦区", "静安区", "徐汇区", "长宁区", "浦东新区", "虹口区", "杨浦区", "闵行区"],
        "x_range": (121.35, 121.60),
        "y_range": (31.15, 31.35),
        "streets": ["南京东路", "淮海中路", "静安寺路", "徐家汇路", "陆家嘴环路",
                     "世纪大道", "五角场", "虹桥路", "长寿路", "西藏中路"],
    },
    {
        "city": "深圳",
        "areas": ["南山区", "福田区", "罗湖区", "宝安区", "龙华区", "龙岗区"],
        "x_range": (113.90, 114.20),
        "y_range": (22.45, 22.70),
        "streets": ["深南大道", "科技南路", "华强北路", "益田路", "福华路",
                     "建设路", "龙岗大道", "民治大道", "后海滨路", "海岸城"],
    },
]

# ── Voucher templates (3 per shop) ────────────────────────────
VOUCHER_TEMPLATES: list[dict[str, Any]] = [
    {
        "title": "超值代金券",
        "pay_rate": (0.80, 0.95),   # pay = actual * random in this range
        "type": 0,
        "subtitle_tmpl": "日常消费通用代金券",
    },
    {
        "title": "特惠套餐券",
        "pay_rate": (0.65, 0.80),
        "type": 1,  # seckill
        "subtitle_tmpl": "限时特惠套餐，超值享受",
    },
    {
        "title": "VIP尊享券",
        "pay_rate": (0.50, 0.70),
        "type": 0,
        "subtitle_tmpl": "VIP客户专享优惠",
    },
]

# ── Blog template words ───────────────────────────────────────
BLOG_TITLES = [
    "周末探店｜发现一家宝藏店铺",
    "闺蜜聚会好去处，太适合拍照了",
    "打卡这家网红店，果然名不虚传",
    "本地人强烈推荐，好吃不贵",
    "环境超赞，服务贴心，五星推荐",
    "性价比超高，值得N刷的好店",
    "隐藏在小巷里的美味，终于找到了",
    "这家店我可以吃一年，太绝了",
    "氛围感拉满，约会首选",
    "排队两小时也值得的美味",
]


# ── Generation helpers ────────────────────────────────────────


def pick_city_for_type(type_id: int) -> dict[str, Any]:
    """Pick a city config, weighted by type for diversity."""
    return RNG.choice(CITY_CONFIGS)


def gen_address(city_cfg: dict[str, Any]) -> tuple[str, str]:
    """Generate a realistic Chinese address. Returns (address, area)."""
    area = RNG.choice(city_cfg["areas"])
    street = RNG.choice(city_cfg["streets"])
    num = RNG.randint(1, 999)
    return f"{city_cfg['city']}{area}{street}{num}号", area


def gen_coords(city_cfg: dict[str, Any]) -> tuple[float, float]:
    x = RNG.uniform(*city_cfg["x_range"])
    y = RNG.uniform(*city_cfg["y_range"])
    return round(x, 6), round(y, 6)


def gen_phone() -> str:
    prefixes = ["138", "139", "150", "151", "152", "186", "187", "188"]
    suffix = "".join(str(RNG.randint(0, 9)) for _ in range(8))
    return RNG.choice(prefixes) + suffix


def gen_shop_image() -> str:
    idx = RNG.randint(1, 20)
    return f"https://qcloud.dpfile.com/pc/shop_{idx}.jpg"


def gen_blog_content(shop_name: str) -> str:
    """Generate a short realistic blog review."""
    adjectives = ["超棒", "很赞", "绝了", "无敌", "惊艳", "满分推荐", "太可了", "绝绝子"]
    foods = ["招牌菜", "特色菜", "推荐菜", "必点菜", "经典款"]
    return (
        f"今天打卡了{shop_name}，真的太{RNG.choice(adjectives)}了！\n\n"
        f"点了他们家的{RNG.choice(foods)}，味道非常正宗，"
        f"环境也特别棒，很适合{RNG.choice(['朋友聚会', '约会', '家庭聚餐', '一个人来'])}。\n\n"
        f"服务态度也很好，下次还会再来！💯"
    )


def now_ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ── Main generation ───────────────────────────────────────────


def generate_all() -> dict[str, Any]:
    """Generate all mock data. Returns dict of table_name -> list of row dicts."""
    data: dict[str, list[dict[str, Any]]] = {
        "tb_shop": [],
        "tb_voucher": [],
        "tb_seckill_voucher": [],
        "tb_user": [],
        "tb_user_info": [],
        "tb_blog": [],
        "tb_blog_comments": [],
        "tb_follow": [],
    }

    shop_id = 1
    voucher_id = 1
    user_id = 1
    blog_id = 1

    # ── Users ─────────────────────────────────────────────────
    # Create 50 users (enough for blogs and follows)
    nicknames = [
        "小食客", "美食猎人", "城市漫游者", "吃货日记", "生活家小明",
        "周末去哪儿", "探店达人", "吃货小丸子", "碳水教父", "甜食爱好者",
        "阿肥的日常", "吃不胖的秘密", "深夜食堂主", "咖啡成瘾者", "火锅英雄",
        "边走边吃", "小巷美食家", "日料控", "烤肉达人", "素食主义",
        "杭州味道", "北京吃货", "上海小资", "深圳美食家", "美食地图",
        "饭团君", "料理小白", "美食摄影师", "味觉旅行者", "甜品艺术家",
        "辣味挑战者", "茶饮爱好者", "烘焙达人", "海鲜猎人", "路边摊女王",
        "厨房小白", "外卖点评家", "早茶爱好者", "深夜放毒", "轻食主义",
        "美食品鉴官", "吃货不打烊", "舌尖上的旅行", "美食发现者", "味蕾探险家",
        "吃遍天下", "美食评论家", "小吃货成长记", "饮食男女", "饕餮客",
    ]
    for i, nn in enumerate(nicknames, 1):
        data["tb_user"].append({
            "id": i,
            "phone": gen_phone(),
            "password": "",
            "nick_name": nn,
            "icon": f"/imgs/icons/user{i}.jpg" if i <= 10 else "",
            "create_time": now_ts(),
            "update_time": now_ts(),
        })
        data["tb_user_info"].append({
            "user_id": i,
            "city": RNG.choice(["杭州", "北京", "上海", "深圳", "广州", "成都", "武汉", "重庆"]),
            "introduce": f"热爱生活，热爱美食的第{i}天~",
            "fans": RNG.randint(0, 5000),
            "followee": RNG.randint(0, 200),
            "gender": RNG.choice([0, 1]),
            "birthday": f"{RNG.randint(1985, 2003)}-{RNG.randint(1, 12):02d}-{RNG.randint(1, 28):02d}",
            "credits": RNG.randint(0, 9999),
            "level": RNG.choice([0, 0, 0, 1, 1, 2]),
            "create_time": now_ts(),
            "update_time": now_ts(),
        })

    # ── Shops ─────────────────────────────────────────────────
    all_shop_names: list[tuple[int, str]] = []
    for st in SHOP_TYPES:
        type_id = st["id"]
        names = SHOP_NAMES_BY_TYPE[type_id]
        for name in names:
            city_cfg = pick_city_for_type(type_id)
            address, area = gen_address(city_cfg)
            x, y = gen_coords(city_cfg)
            avg_price = RNG.choice([29, 39, 49, 59, 68, 78, 88, 98, 108, 128, 158, 188, 228, 288, 388])
            score = RNG.randint(30, 50)
            open_hours = RNG.choice([
                "10:00-22:00", "09:00-21:00", "11:00-23:00", "10:00-24:00",
                "08:00-20:00", "11:00-02:00", "全天24小时", "09:30-21:30",
            ])
            data["tb_shop"].append({
                "id": shop_id,
                "name": name,
                "type_id": type_id,
                "images": ",".join(gen_shop_image() for _ in range(RNG.randint(2, 4))),
                "area": area,
                "address": address,
                "x": x,
                "y": y,
                "avg_price": avg_price,
                "sold": RNG.randint(100, 99999),
                "comments": RNG.randint(50, 50000),
                "score": score,
                "open_hours": open_hours,
                "create_time": now_ts(),
                "update_time": now_ts(),
            })
            all_shop_names.append((shop_id, name))
            shop_id += 1

    # ── Vouchers (3 per shop) ─────────────────────────────────
    for sid, sname in all_shop_names:
        shop_avg_price = None
        for s in data["tb_shop"]:
            if s["id"] == sid:
                shop_avg_price = s["avg_price"]
                break

        for tmpl in VOUCHER_TEMPLATES:
            actual_value = shop_avg_price * RNG.choice([50, 80, 100, 120, 150, 200, 300]) // 100
            if actual_value < 10:
                actual_value = 10
            pay_rate = RNG.uniform(*tmpl["pay_rate"])
            pay_value = max(1, int(actual_value * pay_rate))

            vtype = tmpl["type"]
            v = {
                "id": voucher_id,
                "shop_id": sid,
                "title": tmpl["title"],
                "sub_title": f"{sname} - {tmpl['subtitle_tmpl']}",
                "rules": f"全场通用\n无需预约\n有效期至{RNG.choice(['2026-12-31', '2027-03-31', '2027-06-30'])}",
                "pay_value": pay_value,
                "actual_value": actual_value,
                "type": vtype,
                "status": 1,
                "create_time": now_ts(),
                "update_time": now_ts(),
            }
            data["tb_voucher"].append(v)

            if vtype == 1:  # seckill
                stock = RNG.randint(50, 500)
                now = datetime.now()
                begin = now - timedelta(days=RNG.randint(0, 5))
                end = now + timedelta(days=RNG.randint(15, 60))
                data["tb_seckill_voucher"].append({
                    "voucher_id": voucher_id,
                    "stock": stock,
                    "begin_time": begin.strftime("%Y-%m-%d %H:%M:%S"),
                    "end_time": end.strftime("%Y-%m-%d %H:%M:%S"),
                    "create_time": now_ts(),
                    "update_time": now_ts(),
                })

            voucher_id += 1

    # ── Blogs (around 50 blogs from users about shops) ────────
    num_blogs = min(50, len(all_shop_names))
    sampled_shops = RNG.sample(all_shop_names, num_blogs)
    for bidx, (sid, sname) in enumerate(sampled_shops, 1):
        uid = RNG.randint(1, min(30, len(data["tb_user"])))
        title = RNG.choice(BLOG_TITLES)
        images = ",".join(f"/imgs/blogs/blog{RNG.randint(1,30)}.jpg" for _ in range(RNG.randint(2, 6)))
        data["tb_blog"].append({
            "id": blog_id,
            "shop_id": sid,
            "user_id": uid,
            "title": title,
            "images": images,
            "content": gen_blog_content(sname),
            "liked": RNG.randint(0, 999),
            "comments": RNG.randint(0, 199),
            "create_time": now_ts(),
            "update_time": now_ts(),
        })

        # Add 0-3 comments per blog
        num_comments = RNG.randint(0, 3)
        for _ in range(num_comments):
            cuid = RNG.randint(1, min(20, len(data["tb_user"])))
            comment_texts = [
                "看起来不错，改天去试试！",
                "已经去过了，确实很好吃~",
                "求地址！求地址！",
                "价格怎么样？人均多少？",
                "种草了，周末就去打卡！",
                "环境真的这么好吗？",
                "楼主拍的照片好好看！",
                "这家我也去过，确实值得推荐",
            ]
            data["tb_blog_comments"].append({
                "id": None,  # auto increment
                "user_id": cuid,
                "blog_id": blog_id,
                "parent_id": 0,
                "answer_id": 0,
                "content": RNG.choice(comment_texts),
                "liked": RNG.randint(0, 50),
                "status": 0,
                "create_time": now_ts(),
                "update_time": now_ts(),
            })

        blog_id += 1

    # ── Follows (random follow relationships) ─────────────────
    follow_pairs: set[tuple[int, int]] = set()
    for uid in range(1, min(31, len(data["tb_user"]) + 1)):
        num_follow = RNG.randint(1, 10)
        targets = RNG.sample(
            [t for t in range(1, min(31, len(data["tb_user"]) + 1)) if t != uid],
            min(num_follow, 29),
        )
        for t in targets:
            pair = (uid, t)
            if pair not in follow_pairs:
                follow_pairs.add(pair)
                data["tb_follow"].append({
                    "id": None,
                    "user_id": uid,
                    "follow_user_id": t,
                    "create_time": now_ts(),
                })

    return data


# ── SQL execution ─────────────────────────────────────────────


def clear_existing_data(cursor: Any) -> None:
    """Clear old data in correct order (respect FK constraints)."""
    tables_in_order = [
        "tb_seckill_voucher",
        "tb_voucher_order",
        "tb_voucher",
        "tb_blog_comments",
        "tb_blog",
        "tb_follow",
        "tb_shop",
        "tb_user_info",
        "tb_user",
    ]
    for tbl in tables_in_order:
        cursor.execute(f"DELETE FROM {tbl}")
    print("  [clear] All old data cleared.")


def insert_shop_types(cursor: Any) -> None:
    """Ensure shop types exist."""
    cursor.execute("DELETE FROM tb_shop_type")
    for st in SHOP_TYPES:
        cursor.execute(
            "INSERT INTO tb_shop_type (id, name, icon, sort, create_time, update_time) "
            "VALUES (%s, %s, %s, %s, NOW(), NOW())",
            (st["id"], st["name"], st["icon"], st["sort"]),
        )
    print(f"  [insert] {len(SHOP_TYPES)} shop types.")


def insert_data(cursor: Any, table: str, rows: list[dict[str, Any]]) -> int:
    """Insert list of row dicts into table. Returns count."""
    if not rows:
        return 0

    # Build column list (exclude None-keyed auto-increment columns)
    cols = [k for k in rows[0].keys() if k is not None]
    placeholders = ", ".join(["%s"] * len(cols))
    col_names = ", ".join(cols)
    sql = f"INSERT INTO {table} ({col_names}) VALUES ({placeholders})"

    count = 0
    for row in rows:
        vals = [row[k] for k in cols]
        try:
            cursor.execute(sql, vals)
            count += 1
        except mysql.connector.Error as e:
            print(f"  [WARN] {table} insert failed: {e}")
            print(f"         row: {row}")
    return count


def main() -> None:
    print("=" * 60)
    print("  hm-dianping Mock Data Generator")
    print("=" * 60)

    # Generate
    print("\n[1/3] Generating mock data ...")
    data = generate_all()

    shop_count = len(data["tb_shop"])
    voucher_count = len(data["tb_voucher"])
    seckill_count = len(data["tb_seckill_voucher"])
    user_count = len(data["tb_user"])
    blog_count = len(data["tb_blog"])
    comment_count = len(data["tb_blog_comments"])
    follow_count = len(data["tb_follow"])

    print(f"       Shops  : {shop_count}")
    print(f"       Vouchers: {voucher_count} (seckill: {seckill_count})")
    print(f"       Users  : {user_count}")
    print(f"       Blogs  : {blog_count}")
    print(f"       Comments: {comment_count}")
    print(f"       Follows: {follow_count}")

    # Connect
    print(f"\n[2/3] Connecting to MySQL {DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['database']} ...")
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor()
        print("       Connected.")
    except mysql.connector.Error as e:
        print(f"  [ERROR] Cannot connect to MySQL: {e}")
        print("  Make sure MySQL is running on localhost:3306")
        sys.exit(1)

    try:
        # Clear old data
        print("\n[3/3] Clearing old data and inserting new data ...")
        clear_existing_data(cursor)

        # Insert shop types
        insert_shop_types(cursor)

        # Insert users
        n = insert_data(cursor, "tb_user", data["tb_user"])
        print(f"       [insert] tb_user: {n} rows")

        # Insert user info
        n = insert_data(cursor, "tb_user_info", data["tb_user_info"])
        print(f"       [insert] tb_user_info: {n} rows")

        # Insert shops
        n = insert_data(cursor, "tb_shop", data["tb_shop"])
        print(f"       [insert] tb_shop: {n} rows")

        # Insert vouchers
        n = insert_data(cursor, "tb_voucher", data["tb_voucher"])
        print(f"       [insert] tb_voucher: {n} rows")

        # Insert seckill vouchers
        n = insert_data(cursor, "tb_seckill_voucher", data["tb_seckill_voucher"])
        print(f"       [insert] tb_seckill_voucher: {n} rows")

        # Insert blogs
        n = insert_data(cursor, "tb_blog", data["tb_blog"])
        print(f"       [insert] tb_blog: {n} rows")

        # Insert blog comments (auto-increment id)
        for row in data["tb_blog_comments"]:
            cursor.execute(
                "INSERT INTO tb_blog_comments (user_id, blog_id, parent_id, answer_id, content, liked, status, create_time, update_time) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (row["user_id"], row["blog_id"], row["parent_id"], row["answer_id"],
                 row["content"], row["liked"], row["status"], row["create_time"], row["update_time"]),
            )
        print(f"       [insert] tb_blog_comments: {len(data['tb_blog_comments'])} rows")

        # Insert follows (auto-increment id)
        for row in data["tb_follow"]:
            cursor.execute(
                "INSERT INTO tb_follow (user_id, follow_user_id, create_time) VALUES (%s, %s, %s)",
                (row["user_id"], row["follow_user_id"], row["create_time"]),
            )
        print(f"       [insert] tb_follow: {len(data['tb_follow'])} rows")

        conn.commit()
        print("\n       ✓ All data committed successfully!")

        # ── Verification ──────────────────────────────────────
        print("\n" + "=" * 60)
        print("  Verification")
        print("=" * 60)
        cursor.execute("SELECT COUNT(*) FROM tb_shop_type")
        print(f"  tb_shop_type    : {cursor.fetchone()[0]} rows")
        cursor.execute("SELECT COUNT(*) FROM tb_shop")
        st = cursor.fetchone()[0]
        print(f"  tb_shop         : {st} rows")
        cursor.execute("SELECT COUNT(*) FROM tb_voucher")
        vt = cursor.fetchone()[0]
        print(f"  tb_voucher      : {vt} rows")
        cursor.execute("SELECT COUNT(*) FROM tb_seckill_voucher")
        svt = cursor.fetchone()[0]
        print(f"  tb_seckill_voucher: {svt} rows")
        cursor.execute("SELECT COUNT(*) FROM tb_user")
        ut = cursor.fetchone()[0]
        print(f"  tb_user         : {ut} rows")
        cursor.execute("SELECT COUNT(*) FROM tb_blog")
        print(f"  tb_blog         : {cursor.fetchone()[0]} rows")
        cursor.execute("SELECT COUNT(*) FROM tb_blog_comments")
        print(f"  tb_blog_comments : {cursor.fetchone()[0]} rows")
        cursor.execute("SELECT COUNT(*) FROM tb_follow")
        print(f"  tb_follow       : {cursor.fetchone()[0]} rows")

        # Per-type distribution
        cursor.execute(
            "SELECT t.name, COUNT(*) FROM tb_shop s JOIN tb_shop_type t ON s.type_id = t.id GROUP BY t.name ORDER BY t.sort"
        )
        print("\n  Shop distribution by type:")
        for row in cursor.fetchall():
            print(f"    {row[0]:12s}: {row[1]}")

        # Voucher per shop verification
        cursor.execute(
            "SELECT COUNT(*) FROM (SELECT shop_id FROM tb_voucher GROUP BY shop_id HAVING COUNT(*) = 3) AS v"
        )
        shops_with_3 = cursor.fetchone()[0]
        print(f"\n  Shops with exactly 3 vouchers: {shops_with_3} / {st}")

        if st == 100 and vt == 300:
            print("\n  ✓ GOAL ACHIEVED: 100 shops × 3 vouchers = 300 total!")
        else:
            print(f"\n  ⚠ Expected 100 shops / 300 vouchers, got {st} / {vt}")

    except mysql.connector.Error as e:
        conn.rollback()
        print(f"  [ERROR] {e}")
        sys.exit(1)
    finally:
        cursor.close()
        conn.close()

    print("\n" + "=" * 60)
    print("  Done. You can now start the Spring Boot application.")
    print("=" * 60)


if __name__ == "__main__":
    main()
