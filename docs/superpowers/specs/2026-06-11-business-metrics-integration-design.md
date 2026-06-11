# Design: Integrate BusinessMetricsCollector into builder.py

## Overview
Integrate the BusinessMetricsCollector singleton into the main workflow builder to collect per-query metrics for quantifying system effectiveness.

## Architecture
- Add a lightweight metrics collection helper `_collect_query_metrics()` that extracts fields from GraphState and constructs a QueryMetrics dataclass.
- Hook this helper into `_response_builder_node` after `build_response_bundle` succeeds.
- Export the collector and dataclasses from `local_life.__init__` for external access.

## Components

### 1. Import
Add `business_metrics_collector` and `QueryMetrics` to builder.py imports after line 42:
```python
from learning_agent_service.local_life.business_metrics import business_metrics_collector, QueryMetrics
```

### 2. Helper Function
Create `_collect_query_metrics(state: GraphState, bundle: Any = None) -> None` that extracts:
- Core query fields (raw_query, intent, route, answer_style)
- Shop info (target_shop_id, answer_shop_ids)
- Facets (forbidden, realtime)
- Tool/evidence info
- Degradation/fallback flags
- Clarification flags
- Answer text

### 3. Metrics Recording
Call `business_metrics_collector.record_query(metrics)` wrapped in try/except to avoid affecting main flow.

### 4. Exports
Add to `local_life.__init__`:
- TYPE_CHECKING block: `from .business_metrics import business_metrics_collector, BusinessMetricsCollector, QueryMetrics, MetricsSummary`
- __all__: add the four names

## Data Flow
After response bundle is built:
1. Extract state fields via safe getattr/get with defaults
2. Build QueryMetrics dataclass
3. Record to singleton collector
4. Collector accumulates in memory; summary computed on demand via `get_summary()`

## Error Handling
- Metrics collection wrapped in its own try/except block
- All field extractions use safe getattr/get with defaults
- Main response builder flow unaffected by metrics failures

## Testing
- Run existing tests: `pytest tests/local_life/ -q --tb=short`
- No new unit tests needed (lightweight integration)

## Trade-offs Considered
- **Approach A (chosen)**: Inline helper in builder.py, minimal changes, matches existing patterns
- **Approach B**: Separate metrics module, adds abstraction but unnecessary for this scope
- **Approach C**: Decorator pattern, over-engineered for single call site

**Recommendation**: Approach A is simplest and aligns with the exact specification.

## Acceptance Criteria
- [ ] Import added to builder.py
- [ ] Helper function `_collect_query_metrics` added before `_response_builder_node`
- [ ] Metrics collection hooked into `_response_builder_node` after successful bundle build
- [ ] Exports added to `local_life.__init__`
- [ ] Existing tests pass