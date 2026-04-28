# Flow Scaling Plan

## Context

This document proposes a concrete redesign of flow detection and storage for large repositories, with a target scale of 200k+ nodes.

The current flow pipeline is centered on these paths:

- `code_review_graph/flows.py::detect_entry_points()`
- `code_review_graph/flows.py::trace_flows()`
- `code_review_graph/flows.py::store_flows()`
- `code_review_graph/flows.py::incremental_trace_flows()`
- `code_review_graph/flows.py::get_affected_flows()`
- `code_review_graph/changes.py::analyze_changes()`
- `code_review_graph/tools/review.py::get_affected_flows_func()`
- `code_review_graph/tools/review.py::detect_changes_func()`

Today the system computes execution flows by:

1. Finding all entry points in the repo.
2. Running a forward BFS from each entry point.
3. Storing every flow in `flows`.
4. Storing every visited node in `flow_memberships`.
5. Using stored memberships later for `list_flows`, `get_flow`, `get_affected_flows`, and `detect_changes`.

This works for small and medium repos, but it couples correctness and latency to a full-repo precomputation step. At 200k+ nodes, the expensive part is not only BFS itself, but also:

- tracing from thousands of roots regardless of the user query
- materializing many overlapping flows
- writing huge `flow_memberships` tables
- rebuilding flows during postprocess even when the active task is code review on a small diff

## Problem Statement

The current shape of the flow subsystem has three scaling issues:

1. Full-graph eager flow generation
   Every entry point is traced whether or not any user workflow needs it.

2. Full membership persistence
   Every traced node is inserted into `flow_memberships`, even though many user workflows need only summaries.

3. Review-path dependence on full stored flows
   `get_affected_flows()` currently answers "what changed?" by checking stored memberships. If stored flows are incomplete, review results become incomplete.

Because of that, hard caps such as "at most 3000 entry points" or "at most 500 nodes per flow" are dangerous unless the system explicitly marks results as partial. Silent truncation turns a performance optimization into an accuracy bug.

## Goals

- Preserve correctness for review workflows.
- Make large repos practical without hard truncation.
- Keep `detect_changes` and `get_affected_flows` fast on small diffs.
- Preserve existing user-facing tool semantics where reasonable.
- Support partial or lazy flow expansion explicitly when full materialization is too expensive.

## Non-Goals

- Replacing the graph store.
- Eliminating the `flows` concept from the product.
- Perfect path enumeration for all possible call graphs.
- Solving all parser imprecision in one change.

## Design Principles

1. Compute flows on demand, not only ahead of time.
2. Store summaries by default; store full memberships selectively.
3. Make degraded results explicit with metadata, never silent.
4. Optimize for review workflows first, because they are the highest-value accuracy-sensitive path.
5. Separate "flow discovery" from "flow expansion".

## Proposed Architecture

The redesign has four major pieces:

1. Reverse reachability index for changed-node to entry-point lookup.
2. Summary-first flow storage.
3. Lazy flow expansion for detail views.
4. Explicit execution budgets and partial-result metadata.

### 1. Reverse Reachability for Review Queries

Instead of relying on precomputed full flow memberships for review, compute affected flows from the changed region outward.

New review path:

1. Resolve changed files to changed graph nodes.
2. Walk the call graph in reverse from changed nodes to discover candidate entry points.
3. Rank candidate entry points.
4. Run forward flow expansion only for the matched entry points.
5. Return summaries immediately and expand details only when needed.

This turns review complexity from:

- "trace all roots in the repository"

into:

- "trace only roots that can reach the changed area"

That is a much better fit for common review scenarios, where the diff is small even if the repo is huge.

### 2. Summary-First Flow Storage

Split flow persistence into two layers:

- `flows`: canonical summary row
- `flow_memberships`: optional detailed expansion rows

Under the proposed design, `flows` remains the primary table for listing and ranking. `flow_memberships` becomes an optional cache for expanded flows, not a required source of truth for every workflow.

Recommended summary fields:

- `id`
- `name`
- `entry_point_id`
- `depth`
- `node_count`
- `file_count`
- `criticality`
- `path_json`
  Keep this as a small representative path or top-K spine, not necessarily the full expansion.
- `is_complete`
- `is_expanded`
- `truncated_reason`
- `analysis_version`
- `updated_at`

Recommended `flow_memberships` semantics:

- only present for expanded flows
- may be missing for summary-only flows
- never interpreted as "complete" unless `flows.is_complete = 1`

### 3. Lazy Expansion

Add a distinction between:

- flow summary
- expanded flow

Summary is enough for:

- `list_flows`
- top critical-flow displays
- wiki and overview pages
- token-efficient prompts

Expanded flow is needed for:

- detailed `get_flow`
- deep debugging
- exact membership inspection
- high-confidence impact display when the user explicitly drills in

The main rule is:

- full expansion happens on demand, not during every postprocess run

### 4. Explicit Budgets with Partial Metadata

Budget controls are still useful, but they must be visible in the data model.

Every flow computation should carry a budget object such as:

```python
FlowBudget(
    max_nodes=20000,
    max_edges=100000,
    max_depth=25,
    max_frontier=5000,
    max_ms=1500,
)
```

When a budget is exceeded:

- stop expansion
- mark `is_complete = False`
- record `truncated_reason`
- record counters such as `explored_nodes`, `explored_edges`, `frontier_size`

This allows downstream tools to say:

- "2 affected flows found"
- "1 flow is partial because traversal budget was exhausted"

instead of incorrectly saying:

- "no affected flows"

## Concrete Changes by Module

### `code_review_graph/graph.py`

Add reverse adjacency loading for flow review queries.

New helper:

```python
def load_reverse_call_adjacency(self) -> ReverseFlowAdjacency:
    ...
```

Recommended shape:

```python
@dataclass
class ReverseFlowAdjacency:
    callers_of: dict[str, list[str]]
    nodes_by_qn: dict[str, GraphNode]
    nodes_by_id: dict[int, GraphNode]
```

This can be loaded from the same `edges` table used by `load_flow_adjacency()`.

### `code_review_graph/flows.py`

Refactor responsibilities into explicit layers:

- `detect_entry_points()`
  Keep full results by default. No silent root cap.

- `find_candidate_entry_points_for_nodes()`
  New reverse traversal helper for review-driven flow discovery.

- `trace_flow_summary()`
  New function that computes summary data without requiring full membership persistence.

- `expand_flow()`
  New function that returns detailed node memberships for one entry point under a supplied budget.

- `trace_flows()`
  Reposition as a batch helper for postprocess, built on top of summary tracing.

- `store_flows()`
  Store summary rows first, memberships optionally.

- `get_affected_flows()`
  Change source of truth:
  - first try review-time reverse reachability from changed files
  - optionally enrich from stored expanded memberships
  - never require global precomputed completeness to answer correctly

### `code_review_graph/changes.py`

Change `analyze_changes()` to use the new review-first flow path:

1. resolve changed functions
2. compute candidate entry points via reverse reachability
3. summarize affected flows
4. expand only top-N when needed for richer review output

This makes `detect_changes()` accurate even when the repo has not recently run a full flow expansion job.

### `code_review_graph/tools/review.py`

Keep tool APIs stable, but expose partial-result metadata in responses:

- `is_complete`
- `is_expanded`
- `truncated_reason`
- `analysis_mode`
  Values such as `summary_only`, `on_demand_expanded`, `precomputed_expanded`

This is important both for UI clarity and for LLM consumers.

### `code_review_graph/postprocessing.py`

Change full postprocess behavior from:

- eagerly expand and store all flows

to:

- compute and store flow summaries
- optionally expand only the top critical flows
- optionally skip expansion entirely in very large repos

Recommended default:

- store summaries for all detected entry points
- expand only top 100 to 500 high-criticality flows

### `code_review_graph/tools/flows_tools.py`

Adjust tools to understand the new lifecycle:

- `list_flows`
  Reads summary rows only.

- `get_flow`
  If the flow is not expanded, expand it on demand.

The tool response should clearly tell the caller whether expansion was cached or newly computed.

## Data Model Changes

### Schema Changes

Add columns to `flows`:

```sql
ALTER TABLE flows ADD COLUMN is_complete INTEGER NOT NULL DEFAULT 1;
ALTER TABLE flows ADD COLUMN is_expanded INTEGER NOT NULL DEFAULT 1;
ALTER TABLE flows ADD COLUMN truncated_reason TEXT;
ALTER TABLE flows ADD COLUMN analysis_version TEXT;
ALTER TABLE flows ADD COLUMN explored_nodes INTEGER;
ALTER TABLE flows ADD COLUMN explored_edges INTEGER;
ALTER TABLE flows ADD COLUMN frontier_size INTEGER;
```

Optional new table for cached expansion metadata:

```sql
CREATE TABLE IF NOT EXISTS flow_expansions (
    flow_id INTEGER PRIMARY KEY,
    expanded_at TEXT NOT NULL DEFAULT (datetime('now')),
    budget_json TEXT NOT NULL,
    source TEXT NOT NULL
);
```

This is optional, but useful if the project wants to track whether a flow was expanded during postprocess, review, or explicit lookup.

### Storage Semantics

Under the new contract:

- `flows` always exists for discovered summaries
- `flow_memberships` may be absent or partial
- completeness is determined from `flows.is_complete`, not inferred from membership count

## Algorithm Details

### A. Review-Time Candidate Entry Point Discovery

Pseudo-flow:

```text
changed_files
  -> changed_nodes
  -> reverse CALLS BFS / DFS
  -> reachable roots and decorated handlers
  -> rank entry points
  -> forward summary trace from ranked roots
```

Ranking factors:

- shortest reverse distance to changed node
- explicit framework entry point
- criticality hints
- file spread
- security-sensitive naming

This makes large repos manageable because only a small subgraph near the diff is explored.

### B. Summary Trace

A summary trace should compute:

- representative path
- unique file count
- approximate node count
- depth
- criticality
- completeness metadata

It does not need to store every node ID by default.

Recommended representative path policy:

- keep the shortest or highest-signal spine
- include cross-file transitions
- include security-sensitive nodes
- cap the serialized path for token efficiency

### C. Expansion

Flow expansion should be a separate operation that:

- takes one entry point
- takes a budget
- returns memberships and stats
- can reuse cached expansions

This is where the expensive traversal belongs.

## Migration Plan

### Phase 0: Safety Fix

Immediate actions:

- remove silent caps in `detect_entry_points()` and `_trace_single_flow()`
- if any temporary limits remain, expose `is_complete=False` and `truncated_reason`

This restores correctness before larger refactors land.

### Phase 1: Summary Contract

Implement:

- new `flows` columns
- summary-vs-expanded semantics
- tool response metadata

Keep existing `flow_memberships` behavior for compatibility during this phase.

### Phase 2: Review-First Affected Flow Discovery

Implement:

- reverse adjacency loader
- candidate entry point discovery from changed files
- new `get_affected_flows()` path that does not depend on globally expanded memberships

This phase delivers the biggest product win for code review.

### Phase 3: Lazy Expansion

Implement:

- `expand_flow()`
- on-demand expansion from `get_flow`
- optional expansion cache

### Phase 4: Postprocess Optimization

Implement:

- summary-only or summary-mostly postprocess
- top-K expansion policy
- repo-size-aware defaults

### Phase 5: Cleanup

After adoption:

- remove assumptions that every stored flow has full memberships
- simplify incremental flow refresh semantics around summary rows and selective expansion

## Compatibility Notes

The current codebase assumes:

- `store_flows()` clears and rewrites all flows
- `get_affected_flows()` can answer from `flow_memberships`
- `get_flows()` returns complete-looking flows

These assumptions should be changed gradually.

Recommended compatibility strategy:

1. Add new metadata fields first.
2. Teach readers to respect `is_complete`.
3. Introduce summary-only rows.
4. Shift review logic away from full-membership dependence.
5. Finally reduce eager expansion.

## Testing Plan

Add new tests in `tests/test_flows.py`, `tests/test_changes.py`, and `tests/test_tools.py`.

Required coverage:

- large repo with more than 3000 candidate entry points
- large flow with more than 500 nodes
- partial flow returns `is_complete=False`
- `get_affected_flows()` still finds changed files beyond old traversal caps
- `detect_changes()` remains accurate when only summaries are stored
- `get_flow()` expands a summary-only flow on demand
- repeated `get_flow()` calls reuse cached expansion when available
- postprocess stores summaries without requiring full memberships

Recommended benchmark coverage:

- build time on 50k, 100k, and 200k node synthetic graphs
- review latency for small diffs in large repos
- DB size before and after summary-first storage
- false-negative rate for affected flow detection

## Rollout Risks

### Risk: Reverse traversal returns too many candidate roots

Mitigation:

- rank roots
- stop only with explicit partial metadata
- bias toward framework/decorated roots and nearest roots first

### Risk: Tool consumers expect memberships to always exist

Mitigation:

- add `is_expanded`
- preserve old shape where possible
- lazily expand inside `get_flow`

### Risk: Criticality changes when moving from full path to representative path

Mitigation:

- compute criticality from traversal stats, not only serialized path
- compare old and new scoring in benchmarks

### Risk: Incremental updates become harder to reason about

Mitigation:

- track summary rows separately from expansion cache
- invalidate cached expansions by entry point or touched files

## Recommended Default Policy for 200k+ Node Repos

- No hard cap on discovered entry points.
- No silent per-flow node cap.
- Postprocess stores summaries for all entry points.
- Postprocess expands only top 250 critical flows by default.
- Review workflows use reverse reachability from changed files.
- `get_flow` expands on demand with explicit budget metadata.

## Why This Plan Is Better Than Hard Truncation

Hard truncation answers the wrong question:

- "How do we stop the system from doing too much work?"

The better question is:

- "Which work must be exact, which work can be deferred, and how do we expose partial results honestly?"

This proposal keeps exactness where it matters most:

- code review
- impact analysis
- detailed flow inspection

while making expensive work lazy, cacheable, and explicit.

## Suggested Implementation Order

If this work is split into small PRs, use this sequence:

1. Add flow completeness metadata and stop silent truncation.
2. Add reverse call adjacency loader.
3. Introduce review-time candidate entry point discovery.
4. Refactor `get_affected_flows()` to use review-time discovery.
5. Add summary-only storage semantics.
6. Add on-demand expansion for `get_flow`.
7. Optimize postprocess defaults for large repos.

## Affected Files

The first implementation wave will likely touch:

- `code_review_graph/flows.py`
- `code_review_graph/graph.py`
- `code_review_graph/changes.py`
- `code_review_graph/postprocessing.py`
- `code_review_graph/tools/review.py`
- `code_review_graph/tools/flows_tools.py`
- `code_review_graph/migrations.py`
- `docs/architecture.md`
- `docs/schema.md`
- `tests/test_flows.py`
- `tests/test_changes.py`
- `tests/test_tools.py`

## Open Questions

Before implementation, confirm:

1. Should `path_json` stay as a literal node-id path, or become a representative path?
2. Should postprocess expand top-K flows globally, or expand none by default and leave expansion entirely on demand?
3. Should `get_affected_flows()` return summary-only results by default, with an opt-in for expansion?
4. Should cache invalidation be entry-point-based, file-based, or graph-version-based?

## Recommendation

For this repository, the best first milestone is:

- fix correctness first
- make review workflows independent from globally expanded memberships
- store summaries by default
- add lazy expansion later

That sequence gives the highest value with the least migration risk.
