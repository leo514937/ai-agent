# ADR: P0 Single-Owner Workflow, No Workflow-Level Map-Reduce

## Status

Frozen for P0 fact calibration.

## Context

The current local-life agent uses a top-level router plus a workflow runner. The current codebase already has multiple registered workflows, but the dispatch contract must stay single-owner: one turn chooses one active workflow, and that workflow owns the final response for that turn.

This ADR freezes the intended boundary for the current phase so we do not accidentally grow a workflow-level fan-out / merge system while stabilizing the architecture.

## Decision

We adopt a single-owner workflow model:

- Each turn may select exactly one active `workflow_name`.
- `workflow_runner` must dispatch exactly one workflow handler per turn.
- A workflow name must never become `List[str]`.
- Multiple workflows must not compete to produce or merge `final_response`.
- Multiple workflows must not compete to produce or merge `state_update_plan`.
- Workflow-level Map-Reduce is forbidden.

If future parallelism is needed, it must stay inside a single workflow's tool/evidence layer, and then reduce back into one `EvidencePack` for that workflow.

## Non-Goals

- No new workflow is introduced in P0.
- No workflow graph rewrite is performed in P0.
- No workflow-level fan-out is added in P0.
- No RAG, transaction, reservation, or payment flow is added in P0.

## Current Interpretation

The current repository already keeps workflow dispatch single-owner at the runner level, but some subgraphs still perform internal batching or aggregation. That internal batching is acceptable only when it remains inside one workflow and collapses into a single workflow-owned result object.

## Consequences

- Router and runner logic must remain singular and deterministic.
- Any future batching must be contained inside a workflow and must not create multiple active workflow owners.
- Any new multi-result structure must be explicitly reviewed to ensure it is not a hidden workflow merge.

