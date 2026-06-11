from __future__ import annotations

class ScenePolicy:
    """规则引擎场景策略，识别高频场景并接入硬规则过滤校验。"""
    
    SCENE_RULES = {
        "约会": {
            "forbidden_keywords": ["吵闹", "太吵", "环境差", "脏乱", "拥挤", "服务差", "灯光暗", "位置偏僻"],
            "required_keywords": ["环境", "氛围", "安静"],
            "preferred_facets": ["environment", "atmosphere"],
        },
        "家庭聚餐": {
            "forbidden_keywords": ["不适合老人", "不适合小孩", "太辣", "没宝宝椅", "位置偏僻", "停车不便"],
            "required_keywords": ["适合家庭", "包间"],
            "preferred_facets": ["family_friendly", "parking"],
        },
        "带父母": {
            "forbidden_keywords": ["不适合老人", "太吵", "太辣", "环境差", "只能站着", "排队久"],
            "required_keywords": ["适合老人", "座位舒适"],
            "preferred_facets": ["elderly_friendly", "comfortable"],
        },
        "带小孩": {
            "forbidden_keywords": ["不适合小孩", "没宝宝椅", "太辣", "环境嘈杂", "危险"],
            "required_keywords": ["宝宝椅", "儿童餐"],
            "preferred_facets": ["child_friendly", "safety"],
        },
        "商务宴请": {
            "forbidden_keywords": ["环境差", "服务差", "太吵", "位置偏僻", "档次低"],
            "required_keywords": ["包间", "服务好", "环境好"],
            "preferred_facets": ["private_room", "service", "environment"],
        },
        "朋友聚餐": {
            "forbidden_keywords": ["太安静", "不适合多人", "位置偏僻"],
            "required_keywords": ["适合多人", "氛围好"],
            "preferred_facets": ["group_friendly", "atmosphere"],
        },
        "一个人": {
            "forbidden_keywords": ["不适合一人食", "必须多人", "最低消费"],
            "required_keywords": ["一人食", "小份"],
            "preferred_facets": ["solo_friendly", "portion_size"],
        },
        "深夜": {
            "forbidden_keywords": ["打烊早", "晚上不开", "10点关门"],
            "required_keywords": ["营业到很晚", "夜宵"],
            "preferred_facets": ["late_night", "hours"],
        },
    }

    @classmethod
    def detect_scene(cls, query: str) -> str | None:
        compact = str(query or "").strip()
        for scene in cls.SCENE_RULES:
            if scene in compact:
                return scene
        return None

    @classmethod
    def get_preferred_facets(cls, query: str) -> list[str]:
        preferred: list[str] = []
        compact = str(query or "").strip()
        for scene, rules in cls.SCENE_RULES.items():
            if scene not in compact:
                continue
            for facet in rules.get("preferred_facets", []):
                if facet not in preferred:
                    preferred.append(facet)
        return preferred

    @classmethod
    def apply(cls, query: str, claim_text: str) -> tuple[bool, str]:
        """
        检查查询中是否包含特定场景，并校验单条证据（或评论）是否符合硬规则。
        返回: (是否通过校验, 拒绝理由)
        """
        if not claim_text:
            return True, ""

        compact_query = str(query or "").strip()
        detected_scenes = [scene for scene in cls.SCENE_RULES if scene in compact_query]
        if not detected_scenes:
            return True, ""

        for scene in detected_scenes:
            rules = cls.SCENE_RULES[scene]
            for forbidden in rules["forbidden_keywords"]:
                if forbidden in claim_text:
                    return False, f"场景[{scene}]违禁词[{forbidden}]"

        return True, ""
