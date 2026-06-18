"""ClarificationAgent — 自然追问。"""

from __future__ import annotations

from typing import Any


class ClarificationAgent:
    """自然追问。

    根据缺失信息生成自然的追问文本。
    """

    def generate_clarification(
        self,
        query: str,
        missing_info: list[str],
        context: dict[str, Any] | None = None,
    ) -> str:
        """生成自然的追问。"""
        if not missing_info:
            return "请问您想了解什么？"

        # 根据缺失信息生成追问
        questions: list[str] = []

        for info in missing_info:
            if info == "shop_id" or info == "shop_name":
                questions.append("请问您想了解哪家店？")
            elif info == "price_range":
                questions.append("您的预算大概是多少？")
            elif info == "location":
                questions.append("您在哪个区域？")
            elif info == "time":
                questions.append("您想什么时候去？")
            else:
                questions.append(f"请问{info}是什么？")

        # 组合追问（最多问两个）
        if len(questions) > 2:
            questions = questions[:2]

        return "另外，".join(questions)