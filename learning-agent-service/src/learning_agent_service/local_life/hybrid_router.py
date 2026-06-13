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
        self.fallback_engine = FallbackRuleEngine()
        self._cache: dict[str, LLMRouteDecision] = {}
        self._cache_timestamps: dict[str, float] = {}
        cfg = get_settings()
        self._cache_ttl = cfg.hybrid_router.hybrid_router_cache_ttl
        self._llm_timeout = cfg.hybrid_router.hybrid_router_llm_timeout
        self._llm_max_retries = cfg.hybrid_router.hybrid_router_llm_max_retries

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
                            self.fallback_engine.route(query, session_context, client_context),
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
                            self.fallback_engine.route(query, session_context, client_context),
                            fallback_reason=fallback_reason,
                        )
                        fallback_used = True
                        llm_error_type = "low_confidence"
                except TimeoutError:
                    # LLM超时，降级到规则
                    fallback_reason = "timeout"
                    final_decision = replace(
                        self.fallback_engine.route(query, session_context, client_context),
                        fallback_reason=fallback_reason,
                    )
                    fallback_used = True
                    llm_error_type = "timeout"
                except Exception as e:
                    # LLM调用失败，降级到规则
                    fallback_reason = type(e).__name__
                    final_decision = replace(
                        self.fallback_engine.route(query, session_context, client_context),
                        fallback_reason=fallback_reason,
                    )
                    fallback_used = True
                    llm_error_type = type(e).__name__
            else:
                # 流量控制：未命中的流量使用规则引擎
                fallback_reason = "rollout_excluded"
                final_decision = replace(
                    self.fallback_engine.route(query, session_context, client_context),
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
                self.fallback_engine.route(query, session_context, client_context),
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

    SYSTEM_PROMPT = """你是一个本地生活服务的路由助手。根据用户查询和上下文，判断意图并输出JSON格式的路由决策。

## 意图类型（intent）

| 意图 | 说明 | 示例 |
|------|------|------|
| greeting | 问候/告别/感谢/闲聊 | "你好"、"谢谢"、"再见" |
| detail | 单店详情查询 | "海底捞怎么样"、"这家店好吃吗" |
| recommend | 多店推荐/场景推荐 | "附近有什么火锅"、"适合约会的餐厅" |
| compare | 比较两家或多家店 | "海底捞和巴奴哪个好" |
| coupon | 优惠券/团购查询 | "有券吗"、"有什么优惠" |
| open_status | 营业状态/时间查询 | "现在开门吗"、"几点关门" |
| navigation | 距离/导航查询 | "离我多远"、"怎么去" |
| booking | 预约/订座 | "帮我订个位"、"能预约吗" |
| refund | 退款/取消/订单问题 | "我想退款"、"订单取消" |
| clarification | 信息不足需要追问 | "哪家店"、"你在哪个城市" |
| out_of_scope | 非本地生活查询 | "今天天气"、"帮我写代码" |

## 路由类型（route）

| 路由 | 说明 | 触发条件 |
|------|------|---------|
| realtime_tool | 调用实时工具 | 营业状态/距离/券/预约/退款 |
| compare_multi_parent | 多店比较检索 | 比较查询 |
| structured_first | 结构化筛选优先 | 推荐/场景/附近 |
| merchant_reasoning | 单店详情推理 | 单店评价/详情 |
| guide_rule_rag | 攻略规则检索 | 攻略/避坑/流程 |
| general_chat | 直接回答 | 问候/闲聊/非本地生活 |

## 槽位提取（slots）

提取以下结构化信息（如有）：
- city: 城市名
- district: 区域名（如"朝阳区"）
- shop_name: 店铺名（如"海底捞"）
- shop_id: 店铺ID（如有）
- category: 品类（如"火锅"、"烧烤"）
- scene: 场景（如"约会"、"家庭聚餐"、"商务宴请"）
- price_range: 价格范围（如"人均100"）
- preferences: 用户偏好（如"安静"、"有包间"）

## 输出格式

严格输出JSON，不要输出其他内容：
{
  "intent": "意图类型",
  "domain": "local_life 或 general",
  "confidence": 0.0-1.0之间的浮点数,
  "route": "路由类型",
  "slots": {"city": "北京", "shop_name": "海底捞"},
  "reasoning": "一句话说明判断依据"
}
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


class FallbackRuleEngine:
    """降级规则引擎：LLM不可用时使用"""

    # 确定性100%的关键词
    _UNSAFE_KEYWORDS = ("忽略之前的指令", "system prompt", "jailbreak")
    _GREETING_KEYWORDS = ("你好", "hello", "hi", "谢谢", "再见", "拜拜")
    _IDENTITY_KEYWORDS = ("你是谁", "你叫什么", "介绍一下你自己")
    _CAPABILITY_KEYWORDS = ("你能做什么", "有什么功能", "有什么能力")

    # 本地生活领域关键词（精简版）
    _LOCAL_LIFE_KEYWORDS = ("附近", "推荐", "好吃的", "火锅", "餐厅", "饭店", "优惠", "优惠券", "券", "团购", "营业", "海底捞", "巴奴", "地址", "位置", "排队", "带小孩", "朋友聚餐", "深夜", "商务宴请", "家庭聚餐", "约会", "一个人")

    # 适配/场景类追问关键词
    _SUITABILITY_KEYWORDS = ("适合", "合适", "怎么样", "好不好", "行不行")
    _PERSON_SCENE_KEYWORDS = ("带父母", "带家人", "带小孩", "约会", "家庭聚餐", "朋友聚餐", "商务宴请")

    # 实时工具关键词
    _REALTIME_KEYWORDS = ("营业", "开门", "关门", "几点", "离我多远", "怎么去", "有券", "团购", "预约", "订座", "退款", "取消")

    # 比较关键词
    _COMPARE_KEYWORDS = ("哪个好", "哪家更好", "对比", "比较", "区别")

    # 场景关键词
    _SCENE_KEYWORDS = ("约会", "家庭聚餐", "商务宴请", "带小孩", "带父母", "朋友聚餐")

    # 地址关键词
    _ADDRESS_KEYWORDS = ("地址在哪", "位置在哪", "在哪", "怎么走", "在哪里", "位置")

    def _extract_shop_names(self, query: str) -> list[str]:
        """从查询中提取店铺名称"""
        found = []
        for pattern in _SHOP_NAME_PATTERNS:
            match = re.search(pattern, query)
            if match:
                found.append(match.group())
        return found

    def _has_session_shop_context(self, session_context: dict[str, Any] | None) -> bool:
        if not session_context:
            return False
        return bool(
            session_context.get("current_shop")
            or session_context.get("current_topic")
            or session_context.get("selected_shop_name")
            or session_context.get("selected_shop_id")
        )

    def route(
        self,
        query: str,
        session_context: dict[str, Any] | None = None,
        client_context: dict[str, Any] | None = None,
    ) -> LLMRouteDecision:
        """使用规则进行路由"""
        compact = query.replace(" ", "").lower()
        has_session_shop_context = self._has_session_shop_context(session_context)

        # 1. 安全检查
        if any(kw in compact for kw in self._UNSAFE_KEYWORDS):
            return LLMRouteDecision(
                intent="unsafe",
                domain="unsafe",
                confidence=0.99,
                route="reject",
                reasoning="检测到不安全输入",
            )

        # 2. 问候/告别
        if any(kw in compact for kw in self._GREETING_KEYWORDS):
            return LLMRouteDecision(
                intent="greeting",
                domain="general",
                confidence=0.95,
                route="general_chat",
                reasoning="问候语",
            )

        # 3. 身份查询
        if any(kw in compact for kw in self._IDENTITY_KEYWORDS):
            return LLMRouteDecision(
                intent="identity",
                domain="general",
                confidence=0.95,
                route="general_chat",
                reasoning="身份查询",
            )

        # 4. 能力查询
        if any(kw in compact for kw in self._CAPABILITY_KEYWORDS):
            return LLMRouteDecision(
                intent="capability",
                domain="general",
                confidence=0.90,
                route="general_chat",
                reasoning="能力查询",
            )

        # 5. ????????
        local_life_hint = any(kw in compact for kw in self._LOCAL_LIFE_KEYWORDS)
        if not local_life_hint:
            local_life_hint = any(kw in compact for kw in self._SUITABILITY_KEYWORDS) and (
                has_session_shop_context or any(kw in compact for kw in self._PERSON_SCENE_KEYWORDS)
            )
        if not local_life_hint and has_session_shop_context:
            local_life_hint = any(
                kw in compact
                for kw in (
                    "??",
                    "??",
                    "???",
                    "???",
                    "???",
                    "???",
                    "???",
                    "??",
                    "????",
                    "????",
                    "????",
                    "??",
                    "??",
                    "?",
                )
            )

        if local_life_hint:
            # 5.1 ????
            if any(kw in compact for kw in self._REALTIME_KEYWORDS):
                shop_names = self._extract_shop_names(query)
                return LLMRouteDecision(
                    intent="realtime",
                    domain="local_life",
                    confidence=0.85,
                    route="realtime_tool",
                    slots={"shop_name": ",".join(shop_names)} if shop_names else {},
                    reasoning="??????",
                )

            # 5.1.1 ??????????
            if any(kw in compact for kw in self._ADDRESS_KEYWORDS):
                shop_names = self._extract_shop_names(query)
                return LLMRouteDecision(
                    intent="navigation",
                    domain="local_life",
                    confidence=0.85,
                    route="realtime_tool",
                    slots={"shop_name": ",".join(shop_names)} if shop_names else {},
                    reasoning="??/????",
                )

            # 5.2 ????
            if any(kw in compact for kw in self._COMPARE_KEYWORDS):
                shop_names = self._extract_shop_names(query)
                return LLMRouteDecision(
                    intent="compare",
                    domain="local_life",
                    confidence=0.80,
                    route="compare_multi_parent",
                    slots={"shop_name": ",".join(shop_names)} if shop_names else {},
                    reasoning="????",
                )

            # 5.3 ????
            if any(token in compact for token in ("推荐", "附近", "好吃")) or any(kw in compact for kw in self._SCENE_KEYWORDS):
                return LLMRouteDecision(
                    intent="recommend",
                    domain="local_life",
                    confidence=0.75,
                    route="structured_first",
                    reasoning="????",
                )

            # 5.4 ???merchant_reasoning
            return LLMRouteDecision(
                intent="detail",
                domain="local_life",
                confidence=0.60,
                route="merchant_reasoning",
                reasoning="????????????",
            )

        # 6. 兜底：out_of_scope
        return LLMRouteDecision(
            intent="out_of_scope",
            domain="general",
            confidence=0.50,
            route="general_chat",
            reasoning="非本地生活查询",
        )


# 全局 HybridRouter 实例
_global_hybrid_router: HybridRouter | None = None


def get_hybrid_router() -> HybridRouter:
    """获取全局 HybridRouter 实例"""
    global _global_hybrid_router
    if _global_hybrid_router is None:
        _global_hybrid_router = HybridRouter()
    return _global_hybrid_router


def build_routing_decision_from_hybrid_router(
    raw_query: str,
    persistent: PersistentSessionContext,
    *,
    client_context: Mapping[str, Any] | None = None,
) -> RoutingDecision:
    """新的路由入口：直接使用 HybridRouter 创建 RoutingDecision
    
    这是新的单一入口点，替代旧的 route_top_level_intent() 和 build_initial_routing_decision()
    """
    from ..application.routing_primitives import (
        _context_has_anchor,
        _context_has_candidate_anchor,
        build_input_quality,
        normalize_query,
    )
    
    normalized_query = normalize_query(raw_query)
    input_quality = build_input_quality(raw_query)
    
    # 直接使用 HybridRouter
    router = get_hybrid_router()
    session_context = None
    if persistent is not None:
        session_context = {
            "session_id": getattr(persistent, "session_id", None),
            "current_shop": getattr(persistent, "current_shop", None),
            "recent_shops": getattr(persistent, "recent_entities", []) or [],
            "last_intent": getattr(persistent, "last_intent", None),
        }
    
    decision, trace = router.route(
        raw_query,
        session_context=session_context,
        client_context=dict(client_context or {}),
    )
    
    # 映射到 RoutingDecision 格式
    route_type = decision.route
    intent_name = decision.intent
    confidence = decision.confidence
    reason = decision.reasoning
    slots = decision.slots
    low_info_clarify = input_quality.kind in {"empty_input", "pure_punctuation", "low_information"} and intent_name == "out_of_scope"
    if low_info_clarify:
        route_type = "general_chat"
        intent_name = "clarification"
        confidence = max(confidence, 0.6)
        reason = input_quality.reason or "low_information"
        slots = {}
    
    # 根据 route_type 决定路由行为
    route_mapping = {
        "realtime_tool": ("tool_call", True, False),
        "compare_multi_parent": ("rag_retrieval", True, False),
        "structured_first": ("rag_retrieval", True, False),
        "merchant_reasoning": ("rag_retrieval", True, False),
        "guide_rule_rag": ("rag_retrieval", True, False),
        "general_chat": ("direct_answer", False, False),
        "reject": ("reject", False, False),
    }
    
    required_action, should_retrieve, should_call_tool = route_mapping.get(
        route_type, ("rag_retrieval", True, False)
    )
    
    # 判断是否需要澄清
    missing_slots = []
    clarification_question = None
    if low_info_clarify:
        missing_slots = ["shop_name"]
        clarification_question = "请补充一下店名或你想问的具体信息。"
        required_action = "clarify"
        should_retrieve = False
        should_call_tool = False

    # 对于 realtime_tool 类型的查询，如果没有 shop_name 且没有 current_shop，需要澄清
    if (
        route_type == "realtime_tool"
        and not slots.get("shop_name")
        and not persistent.current_shop
        and not persistent.selected_shop_id
    ):
        missing_slots = ["shop_name"]
        clarification_question = "你想查哪家店？请告诉我具体店名。"
        required_action = "clarify"
    
    # 构建 allowed_routes / forbidden_routes
    allowed_routes = []
    forbidden_routes = []
    if required_action in {"rag_retrieval", "tool_call"}:
        allowed_routes = [required_action]
    elif required_action == "rag_plus_tool":
        allowed_routes = ["rag_retrieval", "tool_call", "rag_plus_tool"]
    elif required_action == "clarify":
        allowed_routes = ["clarify"]
        forbidden_routes = ["rag_retrieval", "tool_call"]
    elif required_action == "direct_answer":
        allowed_routes = ["direct_answer"]
        forbidden_routes = ["rag_retrieval", "tool_call"]
    
    # 处理 intent 映射
    intent_mapping = {
        "greeting": "greeting",
        "detail": "local_life",
        "recommend": "local_life",
        "compare": "local_life",
        "coupon": "package_or_coupon",
        "open_status": "local_life",
        "navigation": "local_life",
        "booking": "local_life",
        "refund": "local_life",
        "clarification": "local_life",
        "out_of_scope": "out_of_scope",
        "unsafe": "unsafe",
        "identity": "identity",
        "capability": "capability",
        "realtime": "local_life",
    }
    
    mapped_intent = intent_mapping.get(intent_name, "local_life")
    compact_query = normalized_query.replace(" ", "")
    if (
        required_action == "clarify"
        and mapped_intent == "local_life"
        and any(token in compact_query for token in ("券", "优惠", "团购", "套餐"))
    ):
        mapped_intent = "package_or_coupon"
    route_candidate = "local_life.package_or_coupon" if mapped_intent == "package_or_coupon" else mapped_intent
    
    # 创建 RoutingDecision
    route = RoutingDecision(
        raw_query=str(raw_query or ""),
        normalized_query=normalized_query,
        domain=decision.domain,
        confidence=confidence,
        input_quality=input_quality,
        intent=IntentRoutingDecision(
            name=mapped_intent,
            confidence=confidence,
            required_slots=list(slots.keys()) + missing_slots,
            missing_slots=missing_slots,
            allowed_routes=allowed_routes,
            forbidden_routes=forbidden_routes,
        ),
        required_action=required_action,
        blocked=False,
        should_rewrite_query=should_retrieve or should_call_tool,
        should_retrieve=should_retrieve,
        should_call_tool=should_call_tool,
        should_use_memory=required_action not in {"clarify", "reject", "no_op"},
        should_persist_memory=required_action not in {"clarify", "reject", "no_op"},
        should_vectorize_memory=required_action not in {"clarify", "reject", "no_op"},
        should_emit_retrieval_events=should_retrieve,
        missing_slots=missing_slots,
        resolved_references=[],
        route_reason=reason or f"hybrid_router:{route_type}",
        safeguards_triggered=[],
        route_candidate=route_candidate,
        preferred_chunk_roles=[],
        tool_candidates=[],
        clarification_question=clarification_question,
        extra={
            "client_context": dict(client_context or {}),
            "context_has_anchor": _context_has_anchor(persistent),
            "context_has_candidate_anchor": _context_has_candidate_anchor(persistent),
            "top_level_intent": mapped_intent,
            "top_level_intent_reason": reason,
            "hybrid_router_route": route_type,
        "hybrid_router_slots": slots,
        "trace_id": trace.trace_id,
        "fallback_used": trace.fallback_used,
        "hybrid_router_llm_error_type": trace.llm_error_type,
    },
)
    
    return route
