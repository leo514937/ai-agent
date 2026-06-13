"""混合路由器监控指标"""

from prometheus_client import Counter, Histogram

# 路由请求计数
ROUTING_REQUESTS = Counter(
    "routing_requests_total",
    "Total routing requests",
    ["intent", "route", "fallback_used"]
)

# 路由延迟
ROUTING_LATENCY = Histogram(
    "routing_latency_seconds",
    "Routing latency in seconds",
    ["fallback_used"]
)

# 路由置信度
ROUTING_CONFIDENCE = Histogram(
    "routing_confidence",
    "Routing confidence score",
    ["intent"]
)

# LLM错误计数
LLM_ERRORS = Counter(
    "llm_errors_total",
    "LLM routing errors",
    ["error_type"]
)

# LLM Token使用量
LLM_TOKENS = Counter(
    "llm_tokens_total",
    "Total LLM tokens used",
    ["model", "token_type"]
)

# LLM成本（美元）
LLM_COST = Counter(
    "llm_cost_usd_total",
    "Total LLM cost in USD",
    ["model"]
)


def record_routing_request(intent: str, route: str, fallback_used: bool) -> None:
    """记录路由请求"""
    ROUTING_REQUESTS.labels(
        intent=intent,
        route=route,
        fallback_used=str(fallback_used).lower()
    ).inc()


def record_routing_latency(latency_seconds: float, fallback_used: bool) -> None:
    """记录路由延迟"""
    ROUTING_LATENCY.labels(
        fallback_used=str(fallback_used).lower()
    ).observe(latency_seconds)


def record_routing_confidence(intent: str, confidence: float) -> None:
    """记录路由置信度"""
    ROUTING_CONFIDENCE.labels(intent=intent).observe(confidence)


def record_llm_error(error_type: str) -> None:
    """记录LLM错误"""
    LLM_ERRORS.labels(error_type=error_type).inc()


def record_llm_tokens(model: str, prompt_tokens: int, completion_tokens: int) -> None:
    """记录LLM Token使用量"""
    LLM_TOKENS.labels(model=model, token_type="prompt").inc(prompt_tokens)
    LLM_TOKENS.labels(model=model, token_type="completion").inc(completion_tokens)


def record_llm_cost(model: str, cost_usd: float) -> None:
    """记录LLM成本（美元）"""
    LLM_COST.labels(model=model).inc(cost_usd)


def calculate_llm_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """计算LLM调用成本（美元）
    
    基于2024年OpenAI定价：
    - gpt-4o-mini: $0.15/1M prompt tokens, $0.60/1M completion tokens
    - gpt-4o: $2.50/1M prompt tokens, $10.00/1M completion tokens
    """
    pricing = {
        "gpt-4o-mini": {"prompt": 0.15, "completion": 0.60},
        "gpt-4o": {"prompt": 2.50, "completion": 10.00},
        "gpt-3.5-turbo": {"prompt": 0.50, "completion": 1.50},
    }
    
    model_pricing = pricing.get(model, pricing["gpt-4o-mini"])
    cost = (prompt_tokens * model_pricing["prompt"] + 
            completion_tokens * model_pricing["completion"]) / 1_000_000
    return cost
