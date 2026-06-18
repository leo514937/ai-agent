from __future__ import annotations
import hashlib
import json
import re
import random
import time
import uuid
from dataclasses import dataclass, field, replace
from typing import Any
from datetime import datetime
from collections.abc import Mapping

from ..config.settings_impl import get_settings
from ..infrastructure.db.openai_client import OpenAIRuntime
from ..domain.contracts import (
    IntentRoutingDecision,
    PersistentSessionContext,
    RoutingDecision,
)
from .hybrid_router_metrics import (
    record_routing_request,
    record_routing_latency,
    record_routing_confidence,
    record_llm_error,
    record_llm_tokens,
    record_llm_cost,
    calculate_llm_cost,
)

# 常见店铺名称模式
_SHOP_NAME_PATTERNS = (
    r'海底捞', r'巴奴', r'呷哺呷哺', r'西贝', r'奈雪', r'喜茶', r'瑞幸', r'星巴克',
    r'麦当劳', r'肯德基', r'必胜客', r'汉堡王', r'德克士', r'真功夫', r'永和大王',
    r'全聚德', r'便宜坊', r'大鸭梨', r'金百万', r'湘鄂情', r'俏江南', r'外婆家',
    r'绿茶餐厅', r'新白鹿', r'弄堂里', r'楼外楼', r'知味观', r'狗不理',
)

_REALTIME_FACET_TOOL_MAP: dict[str, str] = {
    "coupon": "get_coupon_list",
    "open_status": "check_open_status",
    "distance_eta": "get_distance_eta",
}

_REALTIME_FACET_KEYWORDS: dict[str, tuple[str, ...]] = {
    "coupon": ("券", "优惠券", "优惠", "团购", "套餐", "代金券", "有券", "有什么券"),
    "open_status": ("营业", "开门", "开业", "关门", "歇业", "现在营业", "今天营业", "营业吗", "开门吗"),
    "distance_eta": ("离我多远", "多远", "距离", "导航", "路线", "怎么去", "怎么走", "到店", "路程"),
}


def _infer_realtime_facets(
    raw_query: str,
    *,
    route_type: str,
    intent_name: str,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    normalized = re.sub(r"\s+", "", str(raw_query or "")).lower()
    facet_names: list[str] = []

    def _append_facet(name: str) -> None:
        if name and name not in facet_names:
            facet_names.append(name)

    for facet_name, keywords in _REALTIME_FACET_KEYWORDS.items():
        if any(keyword in normalized for keyword in keywords):
            _append_facet(facet_name)

    if intent_name == "coupon":
        _append_facet("coupon")
    if intent_name == "open_status":
        _append_facet("open_status")
    if intent_name == "navigation":
        _append_facet("distance_eta")
    if intent_name == "realtime" and route_type == "realtime_tool":
        # realtime 是一个宽泛标签，保底把已经识别到的实时面保留下来。
        for facet_name in ("open_status", "distance_eta", "coupon"):
            if facet_name in normalized:
                _append_facet(facet_name)

    required_facets = [{"name": facet_name} for facet_name in facet_names]
    source_constraints = {
        facet_name: {"source": "tool", "tool_name": _REALTIME_FACET_TOOL_MAP[facet_name]}
        for facet_name in facet_names
        if facet_name in _REALTIME_FACET_TOOL_MAP
    }
    tool_candidates = [tool_name for tool_name in (_REALTIME_FACET_TOOL_MAP.get(name) for name in facet_names) if tool_name]
    if facet_names and any(name in {"open_status", "distance_eta"} for name in facet_names):
        tool_candidates.append("get_shop_detail")
    tool_candidates = list(dict.fromkeys(tool_candidates))
    return required_facets, source_constraints, tool_candidates


@dataclass(frozen=True)
class LLMRouteDecision:
    """LLM路由决策结果"""
    intent: str           # 意图: greeting, detail, recommend, compare, coupon, open_status, navigation, booking, refund, clarification, out_of_scope
    domain: str           # 领域: local_life, general, unsafe
    confidence: float     # 置信度: 0.0-1.0
    route: str            # 路由: realtime_tool, compare_multi_parent, structured_first, merchant_reasoning, guide_rule_rag, general_chat
    slots: dict[str, Any] = field(default_factory=dict)  # 提取的槽位
    reasoning: str = ""   # 推理过程（可选，用于调试）
    fallback_reason: str | None = None
    rollout_stage: str | None = None
    rollout_key: str | None = None
    rollout_bucket: int | None = None
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "domain": self.domain,
            "confidence": self.confidence,
            "route": self.route,
            "slots": self.slots,
            "reasoning": self.reasoning,
            "fallback_reason": self.fallback_reason,
            "rollout_stage": self.rollout_stage,
            "rollout_key": self.rollout_key,
            "rollout_bucket": self.rollout_bucket,
        }


@dataclass
class RoutingTraceLog:
    """路由追踪日志"""
    trace_id: str
    query: str
    session_id: str | None
    llm_decision: LLMRouteDecision | None
    fallback_used: bool
    final_decision: LLMRouteDecision
    latency_ms: float
    timestamp: float
    llm_error_type: str | None = None
    fallback_reason: str | None = None
    rollout_stage: str | None = None
    rollout_key: str | None = None
    rollout_bucket: int | None = None
    
    def to_log_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "query": self.query[:100],  # 截断长查询
            "session_id": self.session_id,
            "llm_decision": self.llm_decision.to_dict() if self.llm_decision else None,
            "fallback_used": self.fallback_used,
            "llm_error_type": self.llm_error_type,
            "fallback_reason": self.fallback_reason,
            "rollout_stage": self.rollout_stage,
            "rollout_key": self.rollout_key,
            "rollout_bucket": self.rollout_bucket,
            "final_intent": self.final_decision.intent,
            "final_route": self.final_decision.route,
            "final_confidence": self.final_decision.confidence,
            "latency_ms": round(self.latency_ms, 2),
            "timestamp": self.timestamp,
        }


class HybridRouter:
    """混合路由器：LLM主导，规则兜底"""

    def __init__(self, runtime: OpenAIRuntime | None = None):
        self.runtime = runtime
        self._cache: dict[str, LLMRouteDecision] = {}
        self._cache_timestamps: dict[str, float] = {}
        cfg = get_settings()
        self._cache_ttl = cfg.hybrid_router.hybrid_router_cache_ttl
        self._llm_timeout = cfg.hybrid_router.hybrid_router_llm_timeout
        self._llm_max_retries = cfg.hybrid_router.hybrid_router_llm_max_retries

    def _route_with_keywords(
        self,
        query: str,
        session_context: dict[str, Any] | None = None,
        client_context: dict[str, Any] | None = None,
    ) -> LLMRouteDecision:
        """关键词降级路由：LLM 不可用或置信度低时的兜底。"""
        compact = query.replace(" ", "").lower()
        has_session_shop_context = bool(
            session_context
            and (
                session_context.get("current_shop")
                or session_context.get("current_topic")
                or session_context.get("selected_shop_name")
                or session_context.get("selected_shop_id")
            )
        )

        # 1. 安全检查
        if any(kw in compact for kw in ("忽略之前的指令", "system prompt", "jailbreak")):
            return LLMRouteDecision(intent="unsafe", domain="unsafe", confidence=0.99, route="reject", reasoning="检测到不安全输入")

        # 2. 问候/告别
        if any(kw in compact for kw in ("你好", "hello", "hi", "谢谢", "再见", "拜拜")):
            return LLMRouteDecision(intent="greeting", domain="general", confidence=0.95, route="general_chat", reasoning="问候语")

        # 3. 身份查询
        if any(kw in compact for kw in ("你是谁", "你叫什么", "介绍一下你自己")):
            return LLMRouteDecision(intent="identity", domain="general", confidence=0.95, route="general_chat", reasoning="身份查询")

        # 4. 能力查询
        if any(kw in compact for kw in ("你能做什么", "有什么功能", "有什么能力")):
            return LLMRouteDecision(intent="capability", domain="general", confidence=0.90, route="general_chat", reasoning="能力查询")

        # 5. 本地生活
        local_life_keywords = ("附近", "推荐", "好吃的", "火锅", "餐厅", "饭店", "优惠", "优惠券", "券", "团购", "营业", "海底捞", "巴奴", "地址", "位置", "排队", "带小孩", "朋友聚餐", "深夜", "商务宴请", "家庭聚餐", "约会", "一个人")
        local_life_hint = any(kw in compact for kw in local_life_keywords)
        if not local_life_hint:
            suitability_keywords = ("适合", "合适", "怎么样", "好不好", "行不行")
            person_scene_keywords = ("带父母", "带家人", "带小孩", "约会", "家庭聚餐", "朋友聚餐", "商务宴请")
            local_life_hint = any(kw in compact for kw in suitability_keywords) and (
                has_session_shop_context or any(kw in compact for kw in person_scene_keywords)
            )
        if not local_life_hint and has_session_shop_context:
            follow_up_tokens = ("怎么样", "好吃吗", "评价", "口碑", "人均", "价格", "电话", "地址", "怎么去", "营业时间", "有包间吗", "可以带小孩吗")
            local_life_hint = any(kw in compact for kw in follow_up_tokens)

        if local_life_hint:
            realtime_kw = ("营业", "开门", "关门", "几点", "离我多远", "怎么去", "有券", "团购", "预约", "订座", "退款", "取消")
            if any(kw in compact for kw in realtime_kw):
                return LLMRouteDecision(intent="realtime", domain="local_life", confidence=0.85, route="realtime_tool", reasoning="实时查询")
            address_kw = ("地址在哪", "位置在哪", "在哪", "怎么走", "在哪里", "位置")
            if any(kw in compact for kw in address_kw):
                return LLMRouteDecision(intent="navigation", domain="local_life", confidence=0.85, route="realtime_tool", reasoning="地址/导航查询")
            compare_kw = ("哪个好", "哪家更好", "对比", "比较", "区别")
            if any(kw in compact for kw in compare_kw):
                return LLMRouteDecision(intent="compare", domain="local_life", confidence=0.80, route="compare_multi_parent", reasoning="比较查询")
            if any(token in compact for token in ("推荐", "附近", "好吃")) or any(kw in compact for kw in ("约会", "家庭聚餐", "商务宴请", "带小孩", "带父母", "朋友聚餐")):
                return LLMRouteDecision(intent="recommend", domain="local_life", confidence=0.75, route="structured_first", reasoning="推荐查询")
            return LLMRouteDecision(intent="detail", domain="local_life", confidence=0.60, route="merchant_reasoning", reasoning="店铺详情查询")

        # 6. 兜底
        return LLMRouteDecision(intent="out_of_scope", domain="general", confidence=0.50, route="general_chat", reasoning="非本地生活查询")

    def route(
        self,
        query: str,
        *,
        session_context: dict[str, Any] | None = None,
        client_context: dict[str, Any] | None = None,
        use_llm: bool = True,
    ) -> tuple[LLMRouteDecision, RoutingTraceLog]:
        """路由查询，返回决策和追踪信息"""
        start_time = time.time()
        llm_decision = None
        fallback_used = False
        trace_id = str(uuid.uuid4())
        llm_error_type = None
        fallback_reason = None
        rollout_stage = None
        rollout_key = None
        rollout_bucket = None

        # 1. 尝试LLM路由
        cfg = get_settings()
        if use_llm and cfg.hybrid_router.enable_hybrid_router_llm:
            # 流量控制：根据配置的百分比决定是否使用LLM
            traffic_percentage = cfg.hybrid_router.hybrid_router_traffic_percentage
            rollout_stage = cfg.hybrid_router.hybrid_router_rollout_stage
            
            # 根据灰度阶段判断是否使用LLM
            rollout_key = self._build_rollout_stable_key(query, session_context, client_context)
            should_use_llm, rollout_bucket = self._should_use_llm_by_rollout(
                rollout_stage, traffic_percentage, rollout_key
            )
            
            if should_use_llm:
                try:
                    llm_decision = self._route_with_llm(query, session_context, client_context)
                    if (
                        llm_decision.intent == "unknown"
                        and llm_decision.confidence <= 0.0
                        and str(llm_decision.reasoning).startswith("LLM响应解析失败")
                    ):
                        fallback_reason = "parse_error"
                        final_decision = replace(
                            self._route_with_keywords(query, session_context, client_context),
                            fallback_reason=fallback_reason,
                        )
                        fallback_used = True
                        llm_error_type = "parse_error"
                    elif llm_decision.confidence >= cfg.hybrid_router.hybrid_router_fallback_confidence_threshold:
                        final_decision = llm_decision
                    else:
                        # LLM置信度低，降级到规则
                        fallback_reason = "low_confidence"
                        final_decision = replace(
                            self._route_with_keywords(query, session_context, client_context),
                            fallback_reason=fallback_reason,
                        )
                        fallback_used = True
                        llm_error_type = "low_confidence"
                except TimeoutError:
                    # LLM超时，降级到规则
                    fallback_reason = "timeout"
                    final_decision = replace(
                        self._route_with_keywords(query, session_context, client_context),
                        fallback_reason=fallback_reason,
                    )
                    fallback_used = True
                    llm_error_type = "timeout"
                except Exception as e:
                    # LLM调用失败，降级到规则
                    fallback_reason = type(e).__name__
                    final_decision = replace(
                        self._route_with_keywords(query, session_context, client_context),
                        fallback_reason=fallback_reason,
                    )
                    fallback_used = True
                    llm_error_type = type(e).__name__
            else:
                # 流量控制：未命中的流量使用规则引擎
                fallback_reason = "rollout_excluded"
                final_decision = replace(
                    self._route_with_keywords(query, session_context, client_context),
                    fallback_reason=fallback_reason,
                    rollout_stage=rollout_stage,
                    rollout_key=rollout_key,
                    rollout_bucket=rollout_bucket,
                )
                fallback_used = True
        else:
            # 禁用LLM，直接使用规则
            fallback_reason = "llm_disabled" if not use_llm or not cfg.hybrid_router.enable_hybrid_router_llm else "fallback_only"
            final_decision = replace(
                self._route_with_keywords(query, session_context, client_context),
                fallback_reason=fallback_reason,
            )
            fallback_used = True

        latency_ms = (time.time() - start_time) * 1000

        # 记录监控指标
        record_routing_request(final_decision.intent, final_decision.route, fallback_used)
        record_routing_latency(latency_ms / 1000, fallback_used)
        record_routing_confidence(final_decision.intent, final_decision.confidence)
        if llm_error_type:
            record_llm_error(llm_error_type)

        trace = RoutingTraceLog(
            trace_id=trace_id,
            query=query,
            session_id=session_context.get("session_id") if session_context else None,
            llm_decision=llm_decision,
            fallback_used=fallback_used,
            final_decision=final_decision,
            latency_ms=latency_ms,
            timestamp=time.time(),
            llm_error_type=llm_error_type,
            fallback_reason=fallback_reason or getattr(final_decision, "fallback_reason", None),
            rollout_stage=rollout_stage,
            rollout_key=rollout_key,
            rollout_bucket=rollout_bucket,
        )

        return final_decision, trace

    def _build_rollout_stable_key(
        self,
        query: str,
        session_context: dict[str, Any] | None,
        client_context: dict[str, Any] | None,
    ) -> str:
        normalized_query = re.sub(r"\s+", " ", str(query or "")).strip()
        stable_session = {
            "session_id": (session_context or {}).get("session_id"),
            "current_shop": (session_context or {}).get("current_shop"),
            "current_topic": (session_context or {}).get("current_topic"),
            "selected_shop_name": (session_context or {}).get("selected_shop_name"),
            "selected_shop_id": (session_context or {}).get("selected_shop_id"),
            "last_intent": (session_context or {}).get("last_intent"),
        }
        stable_client = {
            "city": (client_context or {}).get("city"),
            "shopId": (client_context or {}).get("shopId"),
            "shopName": (client_context or {}).get("shopName"),
            "page": (client_context or {}).get("page"),
            "location": (client_context or {}).get("location"),
        }
        content = json.dumps(
            {
                "query": normalized_query,
                "session": stable_session,
                "client": stable_client,
            },
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        return hashlib.md5(content.encode("utf-8")).hexdigest()

    def _should_use_llm_by_rollout(
        self,
        rollout_stage: str,
        traffic_percentage: float,
        rollout_key: str,
    ) -> tuple[bool, int | None]:
        """根据灰度阶段和流量百分比决定是否使用LLM
        
        Args:
            rollout_stage: 灰度阶段 (disabled/testing/canary/progressive/full)
            traffic_percentage: LLM路由流量百分比 (0-100)
            rollout_key: 稳定哈希键，用于一致性路由
            
        Returns:
            (是否使用LLM, 归一化桶位)
        """
        # 完全禁用LLM
        if rollout_stage == "disabled":
            return False, None
        
        # 测试阶段：仅开发环境使用
        if rollout_stage == "testing":
            cfg = get_settings()
            return cfg.environment == "development", None
        
        # 全量阶段：100%使用LLM
        if rollout_stage == "full":
            return True, 100
        
        # 金丝雀/渐进阶段：根据流量百分比决定
        # 使用稳定键的一致性哈希，确保相同请求总是走相同路径
        hash_value = int(hashlib.md5(rollout_key.encode()).hexdigest()[:8], 16)
        percentage_hash = (hash_value % 100) + 1  # 1-100
        
        return percentage_hash <= traffic_percentage, percentage_hash

    def _route_with_llm(
        self,
        query: str,
        session_context: dict[str, Any] | None,
        client_context: dict[str, Any] | None,
    ) -> LLMRouteDecision:
        """使用LLM进行路由"""
        # 1. 检查缓存
        cache_key = self._make_cache_key(query, session_context, client_context)
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            return cached

        # 2. 构建prompt
        user_message = self._build_user_message(query, session_context, client_context)

        # 3. 调用LLM（模拟实现，后续集成实际LLM客户端）
        # TODO: 集成实际的LLM客户端
        response = self._call_llm(user_message)

        # 4. 解析响应
        decision = self._parse_response(response)

        # 5. 缓存结果
        self._put_to_cache(cache_key, decision)

        return decision

    # DEPRECATED: 完整路由将被 application/router/facet_planner.py 替代。
    # 当前保留用作兼容层，新功能请直接使用 facet_planner。
    SYSTEM_PROMPT = """You are a routing assistant for a local-life Q&A system. Output route decision as JSON.

Intent: greeting, detail, recommend, compare, coupon, open_status, navigation, booking, refund, clarification, out_of_scope
Route: realtime_tool, compare_multi_parent, structured_first, merchant_reasoning, guide_rule_rag, general_chat

Route mapping:
- greeting/clarification/out_of_scope -> general_chat
- coupon/open_status/navigation/booking/refund -> realtime_tool
- compare -> compare_multi_parent
- recommend -> structured_first
- detail -> merchant_reasoning

Extract slots if present: city, district, shop_name, shop_id, category, scene, price_range

Output strict JSON:
{"intent": "coupon", "domain": "local_life", "confidence": 0.95, "route": "realtime_tool", "slots": {}, "reasoning": "brief analysis"}
"""

    def _call_llm(self, user_message: str) -> str:
        """调用LLM，支持超时和重试"""
        if self.runtime is None:
            raise RuntimeError("OpenAI runtime not available")

        cfg = get_settings()
        model = cfg.hybrid_router.hybrid_router_llm_model or self.runtime.default_model
        responses = self.runtime.client.responses

        last_error = None
        for attempt in range(self._llm_max_retries):
            try:
                response = responses.create(
                    model=model,
                    input=[
                        {"role": "system", "content": [{"type": "input_text", "text": self.SYSTEM_PROMPT}]},
                        {"role": "user", "content": [{"type": "input_text", "text": user_message}]}
                    ],
                    temperature=0.1,
                    max_output_tokens=500,
                    timeout=self._llm_timeout,
                )

                output = getattr(response, "output", [])
                for item in output:
                    if hasattr(item, "content"):
                        for content in item.content:
                            if hasattr(content, "text"):
                                # 记录token使用量和成本
                                usage = getattr(response, "usage", None)
                                if usage:
                                    prompt_tokens = getattr(usage, "prompt_tokens", 0)
                                    completion_tokens = getattr(usage, "completion_tokens", 0)
                                    record_llm_tokens(model, prompt_tokens, completion_tokens)
                                    cost = calculate_llm_cost(model, prompt_tokens, completion_tokens)
                                    record_llm_cost(model, cost)
                                return content.text

                raise RuntimeError("No text content in LLM response")
            
            except Exception as e:
                last_error = e
                if attempt < self._llm_max_retries - 1:
                    # 指数退避重试
                    time.sleep(0.1 * (2 ** attempt))
                    continue
                raise

        raise last_error or RuntimeError("LLM call failed after max retries")

    def _build_user_message(
        self,
        query: str,
        session_context: dict[str, Any] | None,
        client_context: dict[str, Any] | None,
    ) -> str:
        """构建用户消息"""
        parts = [f"用户: {query}"]

        if session_context:
            context_parts = []
            if "current_shop" in session_context:
                context_parts.append(f"当前店铺: {session_context['current_shop']}")
            if "current_topic" in session_context:
                context_parts.append(f"当前话题: {session_context['current_topic']}")
            if "selected_shop_name" in session_context:
                context_parts.append(f"已选店铺: {session_context['selected_shop_name']}")
            if "recent_shops" in session_context:
                context_parts.append(f"最近店铺: {', '.join(session_context['recent_shops'][:3])}")
            if "last_intent" in session_context:
                context_parts.append(f"上轮意图: {session_context['last_intent']}")
            if context_parts:
                parts.append("会话上下文: " + "; ".join(context_parts))

        if client_context:
            context_parts = []
            if "city" in client_context:
                context_parts.append(f"城市: {client_context['city']}")
            if "shopId" in client_context:
                context_parts.append(f"店铺ID: {client_context['shopId']}")
            if "shopName" in client_context:
                context_parts.append(f"店铺名: {client_context['shopName']}")
            if "location" in client_context:
                loc = client_context["location"]
                if isinstance(loc, dict) and loc.get("type") == "near_user":
                    context_parts.append("用户位置: 附近")
            if context_parts:
                parts.append("客户端上下文: " + "; ".join(context_parts))

        return "\\n".join(parts)

    def _parse_response(self, response: str) -> LLMRouteDecision:
        """解析LLM响应"""
        try:
            json_str = response.strip()
            if json_str.startswith("```"):
                json_str = json_str.split("\\n", 1)[1]
                if json_str.endswith("```"):
                    json_str = json_str[:-3]

            data = json.loads(json_str)

            required_fields = ["intent", "domain", "confidence", "route"]
            for field_name in required_fields:
                if field_name not in data:
                    raise ValueError(f"Missing required field: {field_name}")

            return LLMRouteDecision(
                intent=data["intent"],
                domain=data["domain"],
                confidence=float(data["confidence"]),
                route=data["route"],
                slots=data.get("slots", {}),
                reasoning=data.get("reasoning", ""),
            )
        except Exception as e:
            return LLMRouteDecision(
                intent="unknown",
                domain="general",
                confidence=0.0,
                route="general_chat",
                slots={},
                reasoning=f"LLM响应解析失败: {e}",
            )

    def _make_cache_key(
        self,
        query: str,
        session_context: dict[str, Any] | None,
        client_context: dict[str, Any] | None,
    ) -> str:
        """生成缓存键"""
        content = f"{query}:{json.dumps(session_context, sort_keys=True)}:{json.dumps(client_context, sort_keys=True)}"
        return hashlib.md5(content.encode()).hexdigest()

    def _get_from_cache(self, key: str) -> LLMRouteDecision | None:
        """从缓存获取"""
        if key not in self._cache:
            return None

        timestamp = self._cache_timestamps.get(key, 0)
        if time.time() - timestamp > self._cache_ttl:
            del self._cache[key]
            del self._cache_timestamps[key]
            return None

        return self._cache[key]

    def _put_to_cache(self, key: str, decision: LLMRouteDecision) -> None:
        """放入缓存"""
        cfg = get_settings()
        if len(self._cache) >= cfg.hybrid_router.hybrid_router_cache_size:
            if self._cache_timestamps:
                oldest_key = min(self._cache_timestamps, key=lambda k: self._cache_timestamps.get(k, 0))
                del self._cache[oldest_key]
                del self._cache_timestamps[oldest_key]

        self._cache[key] = decision
        self._cache_timestamps[key] = time.time()



# 全局 HybridRouter 实例
_global_hybrid_router: HybridRouter | None = None


def get_hybrid_router() -> HybridRouter:
    """获取全局 HybridRouter 实例"""
    global _global_hybrid_router
    if _global_hybrid_router is None:
        _global_hybrid_router = HybridRouter()
    return _global_hybrid_router
