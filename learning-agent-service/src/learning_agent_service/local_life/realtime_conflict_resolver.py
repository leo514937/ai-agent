"""Realtime information conflict resolver.

This module provides priority resolution logic for conflicts between
RAG (historical) data and tool (realtime) data for realtime facets.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class DataSourcePriority(Enum):
    """Priority levels for different data sources (lower number = higher priority)."""
    TOOL_REALTIME = 1      # Real-time tool results (highest priority)
    CLIENT_CONTEXT = 2     # Client-provided context
    SESSION_CONTEXT = 3    # Session-persisted context
    RAG_HISTORICAL = 4     # RAG historical data (lowest priority)


@dataclass(frozen=True)
class ConflictResolution:
    """Result of conflict resolution."""
    facet: str
    chosen_source: str
    chosen_value: Any
    rejected_sources: list[str]
    resolution_reason: str


# Realtime facets that should ALWAYS use tool results over RAG
REALTIME_FACETS = {"coupon", "open_status", "distance_eta"}

# Facets where RAG data might be acceptable if tool fails
FALLBACK_TO_RAG_FACETS = {"open_status"}  # Business hours from RAG can supplement

# Maximum staleness for RAG data to be considered (in seconds)
RAG_STALENESS_THRESHOLD = 86400  # 24 hours


def resolve_realtime_conflict(
    facet: str,
    tool_result: Any | None = None,
    rag_result: Any | None = None,
    client_context: Any | None = None,
    session_context: Any | None = None,
) -> ConflictResolution | None:
    """Resolve conflict between different data sources for a realtime facet.
    
    Priority order:
    1. Tool real-time results
    2. Client context
    3. Session context
    4. RAG historical data
    
    For realtime facets (coupon, open_status, distance_eta), tool results
    are always preferred when available.
    
    Args:
        facet: The facet name (e.g., "open_status", "coupon", "distance_eta")
        tool_result: Result from realtime tool (e.g., check_open_status)
        rag_result: Result from RAG historical data
        client_context: Client-provided context
        session_context: Session-persisted context
        
    Returns:
        ConflictResolution if there's a conflict to resolve, None if no conflict
    """
    if facet not in REALTIME_FACETS:
        return None
    
    # Collect available sources
    sources = []
    if tool_result is not None:
        sources.append(("tool", DataSourcePriority.TOOL_REALTIME, tool_result))
    if client_context is not None:
        sources.append(("client_context", DataSourcePriority.CLIENT_CONTEXT, client_context))
    if session_context is not None:
        sources.append(("session_context", DataSourcePriority.SESSION_CONTEXT, session_context))
    if rag_result is not None:
        sources.append(("rag", DataSourcePriority.RAG_HISTORICAL, rag_result))
    
    if len(sources) < 2:
        # No conflict if only one source
        return None
    
    # Sort by priority (lower number = higher priority)
    sources.sort(key=lambda x: x[1].value)
    
    chosen_source, chosen_priority, chosen_value = sources[0]
    rejected_sources = [source for source, _, _ in sources[1:]]
    
    # Determine resolution reason
    if chosen_priority == DataSourcePriority.TOOL_REALTIME:
        resolution_reason = f"Tool real-time data has highest priority for {facet}"
    elif facet in REALTIME_FACETS:
        resolution_reason = f"Realtime facet {facet}: tool data unavailable, using {chosen_source}"
    else:
        resolution_reason = f"Using {chosen_source} data based on priority"
    
    return ConflictResolution(
        facet=facet,
        chosen_source=chosen_source,
        chosen_value=chosen_value,
        rejected_sources=rejected_sources,
        resolution_reason=resolution_reason,
    )


def should_use_tool_result_for_facet(
    facet: str,
    tool_result: Any | None = None,
    rag_result: Any | None = None,
) -> bool:
    """Determine if tool result should be used over RAG for a facet.
    
    Args:
        facet: The facet name
        tool_result: Result from realtime tool
        rag_result: Result from RAG historical data
        
    Returns:
        True if tool result should be used, False otherwise
    """
    if facet not in REALTIME_FACETS:
        return False
    
    if tool_result is None:
        return False
    
    # For realtime facets, always prefer tool when available
    return True


def get_freshness_status(
    facet: str,
    tool_result: Any | None = None,
    rag_result: Any | None = None,
) -> str:
    """Get freshness status of data for a facet.
    
    Args:
        facet: The facet name
        tool_result: Result from realtime tool
        rag_result: Result from RAG historical data
        
    Returns:
        Status string: "realtime", "historical", "mixed", or "unavailable"
    """
    has_tool = tool_result is not None
    has_rag = rag_result is not None
    
    if facet in REALTIME_FACETS:
        if has_tool:
            return "realtime"
        elif has_rag:
            return "historical"
        else:
            return "unavailable"
    else:
        if has_tool and has_rag:
            return "mixed"
        elif has_tool:
            return "realtime"
        elif has_rag:
            return "historical"
        else:
            return "unavailable"


def detect_staleness(evidence_metadata: dict[str, Any]) -> tuple[bool, str]:
    """检测证据是否过时
    
    Args:
        evidence_metadata: 证据元数据
        
    Returns:
        (is_stale, reason) 元组
    """
    # 检查显式过时标记
    if evidence_metadata.get("deprecated") or evidence_metadata.get("is_deprecated"):
        return True, "deprecated"
    
    if evidence_metadata.get("stale"):
        return True, "stale"
    
    # 检查时间戳
    import_time = evidence_metadata.get("import_time") or evidence_metadata.get("created_at")
    if import_time:
        try:
            from datetime import datetime
            if isinstance(import_time, str):
                import_time = datetime.fromisoformat(import_time.replace("Z", "+00:00"))
            age_seconds = (datetime.now() - import_time).total_seconds()
            if age_seconds > RAG_STALENESS_THRESHOLD:
                return True, f"age_{int(age_seconds)}"
        except (ValueError, TypeError):
            pass
    
    return False, ""


def get_staleness_warning(staleness_reason: str, shop_name: str | None = None) -> str | None:
    """获取过时警告消息
    
    Args:
        staleness_reason: 过时原因
        shop_name: 商家名称
        
    Returns:
        警告消息或None
    """
    from learning_agent_service.local_life.boundary_prompts import get_boundary_prompt
    
    if staleness_reason == "deprecated":
        return get_boundary_prompt("outdated_info", shop_name)
    elif staleness_reason == "stale":
        return get_boundary_prompt("stale_evidence", shop_name)
    elif staleness_reason.startswith("age_"):
        return get_boundary_prompt("outdated_info", shop_name)
    
    return None


__all__ = [
    "DataSourcePriority",
    "ConflictResolution",
    "REALTIME_FACETS",
    "resolve_realtime_conflict",
    "should_use_tool_result_for_facet",
    "get_freshness_status",
    "detect_staleness",
    "get_staleness_warning",
]