"""
问题类型-失败类型映射表

定义本地生活服务中常见的问题类型和对应的失败模式，
用于系统性地检测、分类和修复问题。
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class FailureSeverity(str, Enum):
    """失败严重程度"""
    P0 = "p0"  # 导致错答、串店、事实错误
    P1 = "p1"  # 影响体验、稳定性
    P2 = "p2"  # 工程质量、技术债


class FailureCategory(str, Enum):
    """失败类别"""
    ROUTING = "routing"           # 路由错误
    ENTITY = "entity"             # 实体解析错误
    EVIDENCE = "evidence"         # 证据错误
    ANSWER = "answer"             # 答案生成错误
    TOOL = "tool"                 # 工具调用错误
    CONTEXT = "context"           # 上下文错误
    CLARIFICATION = "clarification"  # 追问错误


class FailureMode(BaseModel):
    """失败模式定义"""
    mode_id: str
    name: str
    description: str
    category: FailureCategory
    severity: FailureSeverity
    typical_cause: str
    affected_module: str
    detection_rule: str
    suggested_test: str
    example_query: str | None = None
    example_failure: str | None = None


class ProblemType(BaseModel):
    """问题类型定义"""
    type_id: str
    name: str
    description: str
    typical_symptoms: list[str]
    related_failure_modes: list[str]
    affected_intents: list[str]


FAILURE_MODES: dict[str, FailureMode] = {
    # ==================== 路由错误 ====================
    "wrong_route": FailureMode(
        mode_id="wrong_route",
        name="路由错误",
        description="查询被路由到错误的处理路径",
        category=FailureCategory.ROUTING,
        severity=FailureSeverity.P0,
        typical_cause="intent 识别错误或路由规则冲突",
        affected_module="top_level_intent_router, phase1_intent",
        detection_rule="route_branch 不匹配预期",
        suggested_test="验证各类查询的路由分支",
        example_query="海底捞有券吗",
        example_failure="被路由到 out_of_scope 而非 local_life",
    ),
    "missing_clarification": FailureMode(
        mode_id="missing_clarification",
        name="缺少追问",
        description="需要追问时直接回答",
        category=FailureCategory.CLARIFICATION,
        severity=FailureSeverity.P0,
        typical_cause="location slot 缺失未检测或 current_shop 继承错误",
        affected_module="user_need_parser, target_shop_policy",
        detection_rule="无位置时推荐、无 current_shop 时回答 follow-up",
        suggested_test="验证各种缺失信息场景的追问行为",
        example_query="附近有什么好吃的",
        example_failure="直接推荐而没有追问位置",
    ),
    "over_clarification": FailureMode(
        mode_id="over_clarification",
        name="过度追问",
        description="上下文足够时仍追问",
        category=FailureCategory.CLARIFICATION,
        severity=FailureSeverity.P1,
        typical_cause="追问策略未考虑 session 上下文",
        affected_module="target_shop_policy, phase3_review",
        detection_rule="连续多轮追问相同信息",
        suggested_test="验证多轮对话中追问行为",
        example_query="海底捞怎么样",
        example_failure="已有 current_shop 仍追问是哪家店",
    ),

    # ==================== 实体解析错误 ====================
    "cross_shop": FailureMode(
        mode_id="cross_shop",
        name="串店",
        description="问 A 店答 B 店",
        category=FailureCategory.ENTITY,
        severity=FailureSeverity.P0,
        typical_cause="target_shop 解析失败或 evidence_scope_guard 过滤失败",
        affected_module="target_shop_policy, evidence_scope_guard",
        detection_rule="答案中出现非目标店名",
        suggested_test="验证单店模式不出现其他店名",
        example_query="海底捞水晶城店怎么样",
        example_failure="答案中提到巴奴的信息",
    ),
    "wrong_entity": FailureMode(
        mode_id="wrong_entity",
        name="实体错误",
        description="解析到错误的店铺",
        category=FailureCategory.ENTITY,
        severity=FailureSeverity.P0,
        typical_cause="代词消解失败或 alias 匹配错误",
        affected_module="target_shop_policy, entity_resolver",
        detection_rule="target_shop_id 与预期不符",
        suggested_test="验证各种代词和 alias 的解析准确性",
        example_query="这家怎么样",
        example_failure="解析到错误的店铺",
    ),
    "pronoun_resolution_failure": FailureMode(
        mode_id="pronoun_resolution_failure",
        name="代词消解失败",
        description="代词无法正确解析到具体店铺",
        category=FailureCategory.ENTITY,
        severity=FailureSeverity.P1,
        typical_cause="session 中无 current_shop 或 last_candidates",
        affected_module="target_shop_policy",
        detection_rule="代词查询返回 clarification 但上下文有店铺",
        suggested_test="验证代词在各种上下文中的解析",
        example_query="它怎么样",
        example_failure="返回 clarification 而非继承 current_shop",
    ),

    # ==================== 证据错误 ====================
    "forbidden_facet_leak": FailureMode(
        mode_id="forbidden_facet_leak",
        name="禁止维度泄露",
        description="答案中出现禁止的 facet 内容",
        category=FailureCategory.EVIDENCE,
        severity=FailureSeverity.P0,
        typical_cause="answer_contract.forbidden_facets 未生效或 answer_linter 拦截失败",
        affected_module="answer_contract, answer_linter",
        detection_rule="答案包含 forbidden_facet 内容",
        suggested_test="验证各 answer_style 的 forbidden_facet 约束",
        example_query="海底捞有券吗",
        example_failure="答案中提到环境评价（coupon_only 禁止 environment）",
    ),
    "realtime_facet_from_rag": FailureMode(
        mode_id="realtime_facet_from_rag",
        name="实时维度从 RAG 获取",
        description="实时信息（券/营业/距离）从 RAG 而非工具获取",
        category=FailureCategory.EVIDENCE,
        severity=FailureSeverity.P0,
        typical_cause="realtime_facets 未正确隔离或 tool 未被调用",
        affected_module="answer_contract, route_gate, tool_planner",
        detection_rule="实时 facet 无 tool 调用记录",
        suggested_test="验证实时 facet 必须调用对应 tool",
        example_query="海底捞现在开门吗",
        example_failure="使用 RAG 中的历史营业时间而非调用 check_open_status",
    ),
    "insufficient_evidence": FailureMode(
        mode_id="insufficient_evidence",
        name="证据不足",
        description="evidence 不足但仍硬答",
        category=FailureCategory.EVIDENCE,
        severity=FailureSeverity.P0,
        typical_cause="grounded_verifier 阈值过宽或未触发",
        affected_module="grounded_verifier, rag_guardrail",
        detection_rule="evidence_used <= 1 但答案未降级",
        suggested_test="验证证据不足时的降级行为",
        example_query="某某小店怎么样",
        example_failure="无证据但仍生成完整评价",
    ),
    "cross_shop_evidence": FailureMode(
        mode_id="cross_shop_evidence",
        name="跨店证据污染",
        description="单店模式下混入其他店的证据",
        category=FailureCategory.EVIDENCE,
        severity=FailureSeverity.P0,
        typical_cause="evidence_scope_guard 过滤失败",
        affected_module="evidence_scope_guard, rag_guardrail",
        detection_rule="单店模式下 evidence 包含其他 shop_id",
        suggested_test="验证单店模式 evidence 严格过滤",
        example_query="海底捞水晶城店怎么样",
        example_failure="evidence 中包含巴奴的评价",
    ),
    "irrelevant_evidence": FailureMode(
        mode_id="irrelevant_evidence",
        name="不相关证据",
        description="检索到的证据与查询不相关",
        category=FailureCategory.EVIDENCE,
        severity=FailureSeverity.P1,
        typical_cause="query_router 路由错误或 retrieval 质量差",
        affected_module="query_router, local_life_retrieval",
        detection_rule="facet_hit_rate 低",
        suggested_test="验证各类查询的证据相关性",
        example_query="适合约会的餐厅",
        example_failure="返回的证据都是关于排队的",
    ),

    # ==================== 答案生成错误 ====================
    "single_shop_to_recommendation": FailureMode(
        mode_id="single_shop_to_recommendation",
        name="单店答成推荐",
        description="问单店却输出推荐列表",
        category=FailureCategory.ANSWER,
        severity=FailureSeverity.P0,
        typical_cause="target_shop 解析失败导致 answer_style 从 single_shop_review 变为 multi_shop_recommendation",
        affected_module="target_shop_policy, answer_contract",
        detection_rule="single_shop_mode=True 但答案含推荐语言",
        suggested_test="验证单店查询不输出推荐",
        example_query="海底捞水晶城店怎么样",
        example_failure="答案推荐了多家店",
    ),
    "comparison_only_single_shop": FailureMode(
        mode_id="comparison_only_single_shop",
        name="比较只答单店",
        description="比较查询只输出一家店的信息",
        category=FailureCategory.ANSWER,
        severity=FailureSeverity.P0,
        typical_cause="comparison 无模板，LLM 只输出单店评价",
        affected_module="answer_structure_composer",
        detection_rule="answer_style=comparison 但答案只提到一家店",
        suggested_test="验证比较查询输出两家店信息",
        example_query="海底捞和巴奴哪个好",
        example_failure="答案只评价了海底捞",
    ),
    "unsupported_realtime_claim": FailureMode(
        mode_id="unsupported_realtime_claim",
        name="无依据的实时声明",
        description="答案中有实时关键词但无 tool 调用",
        category=FailureCategory.ANSWER,
        severity=FailureSeverity.P1,
        typical_cause="answer_linter 拦截失败",
        affected_module="answer_linter",
        detection_rule="答案含'实时/刚查/最新'但无 tool 调用",
        suggested_test="验证实时声明必须有 tool 支持",
        example_query="海底捞有券吗",
        example_failure="答案说'刚查到有券'但未调用 get_coupon_list",
    ),
    "unsolicited_recommendation": FailureMode(
        mode_id="unsolicited_recommendation",
        name="未经请求的推荐",
        description="非推荐查询中出现推荐语言",
        category=FailureCategory.ANSWER,
        severity=FailureSeverity.P1,
        typical_cause="answer_linter 拦截失败",
        affected_module="answer_linter",
        detection_rule="单店合同下答案含'推荐'语言",
        suggested_test="验证单店查询不推荐其他店",
        example_query="海底捞怎么样",
        example_failure="答案推荐了其他餐厅",
    ),
    "hallucinated_facts": FailureMode(
        mode_id="hallucinated_facts",
        name="编造事实",
        description="无证据支撑的事实性陈述",
        category=FailureCategory.ANSWER,
        severity=FailureSeverity.P0,
        typical_cause="LLM 推断无证据约束",
        affected_module="grounded_verifier, answer_linter",
        detection_rule="答案含绝对语气词但 evidence <= 1",
        suggested_test="验证无证据时禁止绝对语气",
        example_query="某某小店怎么样",
        example_failure="答案说'这家店一定很好'但无证据",
    ),

    # ==================== 工具调用错误 ====================
    "tool_not_called": FailureMode(
        mode_id="tool_not_called",
        name="工具未调用",
        description="应该调用工具但未调用",
        category=FailureCategory.TOOL,
        severity=FailureSeverity.P0,
        typical_cause="route_gate 或 tool_planner 逻辑错误",
        affected_module="route_gate, tool_planner",
        detection_rule="realtime facet 无对应 tool 调用",
        suggested_test="验证各 realtime facet 必须调用 tool",
        example_query="海底捞有券吗",
        example_failure="未调用 get_coupon_list",
    ),
    "tool_result_ignored": FailureMode(
        mode_id="tool_result_ignored",
        name="工具结果被忽略",
        description="有 tool 结果但答案中未体现",
        category=FailureCategory.TOOL,
        severity=FailureSeverity.P1,
        typical_cause="compose_answer 未整合 tool 结果",
        affected_module="compose_answer, phase7_compose",
        detection_rule="tool_called=True 但答案无相关内容",
        suggested_test="验证 tool 结果在答案中体现",
        example_query="海底捞有券吗",
        example_failure="调用了 get_coupon_list 但答案未提及券信息",
    ),
    "tool_call_failed": FailureMode(
        mode_id="tool_call_failed",
        name="工具调用失败",
        description="工具调用返回错误",
        category=FailureCategory.TOOL,
        severity=FailureSeverity.P1,
        typical_cause="外部 API 不可用或参数错误",
        affected_module="tool_executor, composer",
        detection_rule="tool 返回 error/degraded 状态",
        suggested_test="验证工具失败时的降级行为",
        example_query="海底捞有券吗",
        example_failure="get_coupon_list 返回 timeout",
    ),

    # ==================== 上下文错误 ====================
    "context_pollution": FailureMode(
        mode_id="context_pollution",
        name="上下文污染",
        description="session 上下文影响了不该影响的查询",
        category=FailureCategory.CONTEXT,
        severity=FailureSeverity.P1,
        typical_cause="current_shop 或 last_candidates 未正确隔离",
        affected_module="target_shop_policy, persistent_session",
        detection_rule="capability/identity 查询被路由到 local_life",
        suggested_test="验证元查询不受上下文影响",
        example_query="你有什么作用",
        example_failure="因为有 current_shop 而被路由到 local_life",
    ),
    "wrong_context_inheritance": FailureMode(
        mode_id="wrong_context_inheritance",
        name="上下文错误继承",
        description="继承了错误的 current_shop 或 last_candidates",
        category=FailureCategory.CONTEXT,
        severity=FailureSeverity.P0,
        typical_cause="session 状态管理错误",
        affected_module="persistent_session, target_shop_policy",
        detection_rule="多轮对话中店铺继承错误",
        suggested_test="验证多轮对话的上下文继承",
        example_query="第二家怎么样",
        example_failure="继承了第一家店而非第二家",
    ),
    "stale_context": FailureMode(
        mode_id="stale_context",
        name="过期上下文",
        description="使用了过期的 session 信息",
        category=FailureCategory.CONTEXT,
        severity=FailureSeverity.P1,
        typical_cause="session 未正确更新或过期",
        affected_module="persistent_session",
        detection_rule="使用已过期的 current_shop",
        suggested_test="验证 session 过期行为",
        example_query="那家店怎么样",
        example_failure="使用了已切换的旧店铺信息",
    ),
    # ==================== P0 深化 ====================
    "realtime_facet_rag_source": FailureMode(
        mode_id="realtime_facet_rag_source",
        name="实时信息从RAG获取",
        description="实时维度（券/营业/距离）从RAG获取而非工具",
        category=FailureCategory.EVIDENCE,
        severity=FailureSeverity.P0,
        typical_cause="realtime_facets未触发tool调用",
        affected_module="route_gate, tool_planner",
        detection_rule="realtime facet 无 tool 调用",
        suggested_test="验证实时维度必须调用工具",
        example_query="海底捞有券吗",
        example_failure="从RAG返回券信息而非调用get_coupon_list",
    ),
    "comparison_single_shop": FailureMode(
        mode_id="comparison_single_shop",
        name="对比只输出单店",
        description="对比查询只输出一家店的信息",
        category=FailureCategory.ANSWER,
        severity=FailureSeverity.P0,
        typical_cause="comparison模板缺失或LLM未遵循",
        affected_module="answer_structure_composer",
        detection_rule="comparison style 但答案只有一家店",
        suggested_test="验证对比查询输出两家店",
        example_query="海底捞和呷哺呷哺哪个好",
        example_failure="只介绍了海底捞，未提及呷哺呷哺",
    ),
    "clarification_loop": FailureMode(
        mode_id="clarification_loop",
        name="追问循环",
        description="连续多轮追问相同信息",
        category=FailureCategory.CLARIFICATION,
        severity=FailureSeverity.P1,
        typical_cause="追问策略未考虑历史追问",
        affected_module="clarification_strategy",
        detection_rule="连续2+轮追问相同slot",
        suggested_test="验证多轮对话不重复追问",
        example_query="（连续3轮被问位置）",
        example_failure="每次都追问位置，未记住已追问",
    ),
    "stale_evidence_used": FailureMode(
        mode_id="stale_evidence_used",
        name="使用过时证据",
        description="使用明显过时的证据生成答案",
        category=FailureCategory.EVIDENCE,
        severity=FailureSeverity.P1,
        typical_cause="未检测证据新鲜度",
        affected_module="rag_guardrail, evidence_pack",
        detection_rule="evidence metadata 有 stale/deprecated 标记",
        suggested_test="验证过时证据被过滤或提示",
        example_query="这家店还在营业吗",
        example_failure="使用2年前的RAG数据回答",
    ),
    "scene_violation_not_caught": FailureMode(
        mode_id="scene_violation_not_caught",
        name="场景违禁词未过滤",
        description="答案包含场景违禁词",
        category=FailureCategory.ANSWER,
        severity=FailureSeverity.P1,
        typical_cause="scene_policy未生效",
        affected_module="scene_policy, rag_guardrail",
        detection_rule="答案包含场景违禁词",
        suggested_test="验证场景过滤生效",
        example_query="约会适合去哪家",
        example_failure="推荐了'吵闹'的餐厅",
    ),
}


PROBLEM_TYPES: dict[str, ProblemType] = {
    "coupon_query_wrong_facet": ProblemType(
        type_id="coupon_query_wrong_facet",
        name="问券却答环境",
        description="优惠券查询却返回环境评价",
        typical_symptoms=["答案含'环境'/'氛围'等词", "无券信息"],
        related_failure_modes=["forbidden_facet_leak"],
        affected_intents=["coupon_query"],
    ),
    "open_status_use_history": ProblemType(
        type_id="open_status_use_history",
        name="问当前营业却用了历史信息",
        description="营业状态查询使用 RAG 历史数据而非实时工具",
        typical_symptoms=["无 tool 调用", "答案含历史时间"],
        related_failure_modes=["realtime_facet_from_rag", "tool_not_called"],
        affected_intents=["open_status"],
    ),
    "nearby_no_clarify_location": ProblemType(
        type_id="nearby_no_clarify_location",
        name="问附近却没追问位置",
        description="附近推荐查询未追问位置信息",
        typical_symptoms=["直接推荐", "无位置确认"],
        related_failure_modes=["missing_clarification"],
        affected_intents=["nearby_recommendation"],
    ),
    "comparison_only_single": ProblemType(
        type_id="comparison_only_single",
        name="问比较却只答单店",
        description="比较查询只输出一家店的信息",
        typical_symptoms=["答案只提到一家店", "无对比维度"],
        related_failure_modes=["comparison_only_single_shop"],
        affected_intents=["comparison"],
    ),
    "single_shop_recommend": ProblemType(
        type_id="single_shop_recommend",
        name="问单店却答成推荐",
        description="单店查询却输出推荐列表",
        typical_symptoms=["答案推荐多家店", "无目标店聚焦"],
        related_failure_modes=["single_shop_to_recommendation", "cross_shop"],
        affected_intents=["merchant_detail"],
    ),
    "wrong_shop_answer": ProblemType(
        type_id="wrong_shop_answer",
        name="问 A 店答 B 店",
        description="查询 A 店却返回 B 店信息",
        typical_symptoms=["答案含非目标店名", "串店"],
        related_failure_modes=["cross_shop", "wrong_entity"],
        affected_intents=["merchant_detail", "coupon_query", "open_status"],
    ),
    "no_evidence_answer": ProblemType(
        type_id="no_evidence_answer",
        name="无证据硬答",
        description="无证据支撑但仍生成完整答案",
        typical_symptoms=["无 evidence 引用", "编造事实"],
        related_failure_modes=["insufficient_evidence", "hallucinated_facts"],
        affected_intents=["merchant_detail", "recommendation"],
    ),
    "rag_irrelevant": ProblemType(
        type_id="rag_irrelevant",
        name="RAG 召回不相关",
        description="检索到的证据与查询不相关",
        typical_symptoms=["facet_hit_rate 低", "证据不匹配"],
        related_failure_modes=["irrelevant_evidence"],
        affected_intents=["merchant_detail", "recommendation"],
    ),
    "tool_result_ignored": ProblemType(
        type_id="tool_result_ignored",
        name="工具结果被忽略",
        description="有 tool 结果但答案中未体现",
        typical_symptoms=["tool_called 但答案无相关内容"],
        related_failure_modes=["tool_result_ignored"],
        affected_intents=["coupon_query", "open_status", "distance"],
    ),
    "context_inherit_wrong": ProblemType(
        type_id="context_inherit_wrong",
        name="上下文错误继承",
        description="多轮对话中继承了错误的店铺信息",
        typical_symptoms=["代词解析错误", "current_shop 错误"],
        related_failure_modes=["wrong_context_inheritance", "pronoun_resolution_failure"],
        affected_intents=["follow_up"],
    ),
}


class FailureModeDetector:
    """失败模式检测器"""

    def __init__(self) -> None:
        self._modes = FAILURE_MODES
        self._problems = PROBLEM_TYPES

    def get_mode(self, mode_id: str) -> FailureMode | None:
        return self._modes.get(mode_id)

    def get_problem(self, type_id: str) -> ProblemType | None:
        return self._problems.get(type_id)

    def detect_failure_modes(
        self,
        query: str,
        answer: str,
        route: str,
        tool_called: bool,
        evidence_count: int,
        target_shop_id: int | None,
        answer_shop_ids: list[int],
        allowed_facets: list[str],
        forbidden_facets: list[str],
        realtime_facets: list[str],
    ) -> list[FailureMode]:
        """检测可能的失败模式"""
        detected: list[FailureMode] = []

        # 检测禁止维度泄露
        for facet in forbidden_facets:
            if facet in answer:
                detected.append(self._modes["forbidden_facet_leak"])

        # 检测实时维度从 RAG 获取
        for facet in realtime_facets:
            if facet in answer and not tool_called:
                detected.append(self._modes["realtime_facet_from_rag"])

        # 检测证据不足
        if evidence_count <= 1 and any(
            word in answer for word in ("一定", "肯定", "绝对", "百分百")
        ):
            detected.append(self._modes["insufficient_evidence"])

        # 检测串店
        if target_shop_id and answer_shop_ids:
            if target_shop_id not in answer_shop_ids and len(answer_shop_ids) > 0:
                detected.append(self._modes["cross_shop"])

        # 检测无依据的实时声明
        realtime_keywords = ("实时", "刚查", "最新", "当前", "现在")
        if any(kw in answer for kw in realtime_keywords) and not tool_called:
            detected.append(self._modes["unsupported_realtime_claim"])

        return detected

    def detect_realtime_facet_issues(
        self,
        answer_text: str,
        realtime_facets: list[str],
        tools_called: list[str],
    ) -> list[str]:
        """检测实时维度问题"""
        detected = []
        
        realtime_tool_map = {
            "coupon": "get_coupon_list",
            "open_status": "check_open_status",
            "distance_eta": "get_distance_eta",
        }
        
        for facet in realtime_facets:
            if facet in realtime_tool_map:
                required_tool = realtime_tool_map[facet]
                if required_tool not in tools_called:
                    detected.append("realtime_facet_rag_source")
        
        return detected

    def detect_comparison_issues(
        self,
        answer_style: str,
        answer_text: str,
        shop_count: int,
    ) -> list[str]:
        """检测对比问题"""
        detected = []
        
        if answer_style == "comparison" and shop_count < 2:
            detected.append("comparison_single_shop")
        
        return detected

    def detect_staleness_issues(
        self,
        evidence_metadata_list: list[dict],
    ) -> list[str]:
        """检测过时证据问题"""
        detected = []
        
        for metadata in evidence_metadata_list:
            if metadata.get("deprecated") or metadata.get("stale"):
                detected.append("stale_evidence_used")
                break
        
        return detected

    def get_modes_by_category(self, category: FailureCategory) -> list[FailureMode]:
        return [m for m in self._modes.values() if m.category == category]

    def get_modes_by_severity(self, severity: FailureSeverity) -> list[FailureMode]:
        return [m for m in self._modes.values() if m.severity == severity]

    def get_problems_by_intent(self, intent: str) -> list[ProblemType]:
        return [p for p in self._problems.values() if intent in p.affected_intents]

    def summarize(self) -> dict[str, Any]:
        """返回失败模式摘要"""
        return {
            "total_modes": len(self._modes),
            "total_problems": len(self._problems),
            "by_category": {
                cat.value: len(self.get_modes_by_category(cat))
                for cat in FailureCategory
            },
            "by_severity": {
                sev.value: len(self.get_modes_by_severity(sev))
                for sev in FailureSeverity
            },
        }


failure_mode_detector = FailureModeDetector()
