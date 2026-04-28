# 文件索引

| 文件 | 状态 | 说明 |
|------|------|------|
| `code_review_graph/migrations.py` | ✅ 完成 | 新增 `_migrate_v10`，注册为 `MIGRATIONS[10]`，版本号升至 v10 |
| `code_review_graph/flows.py` | ✅ 完成 | 新增 `FlowBudget`；改写 `_trace_single_flow`；更新 `store_flows`/`incremental_trace_flows` INSERT；更新 `get_flows`/`get_flow_by_id` 读取新列 |
| `code_review_graph/tools/flows_tools.py` | ✅ 完成 | `list_flows` 加 `completeness_warning`；`get_flow` 暴露 `is_complete`/`truncated_reason` |
| `tests/test_flows.py` | ✅ 完成 | 新增 `TestFlowBudget`、`TestFlowCompletenessMetadata` 两个测试类（约 +110 行） |
| `tests/test_migrations.py` | ✅ 完成 | 新增 `test_v10_adds_completeness_columns`、`test_v10_adds_completeness_indexes`、`test_v10_migration_idempotent` |
| `tests/test_tools.py` | ✅ 完成 | 新增 `test_list_flows_no_completeness_warning_when_all_complete`、`test_get_flow_exposes_is_complete` |
| `docs/FLOW-SCALING-PLAN.md` | ✅ 完成（只读） | PR 1 对应 Phase 0 + Phase 1，已按设计实现 |
| `~/.claude/plans/docs-flow-scaling-plan-md-sequential-lovelace.md` | ✅ 完成 | 三 PR 拆分计划，PR 2 和 PR 3 的 checklist 待执行 |
| `code_review_graph/graph.py` | 🗒️ 未开始 | PR 2 需要新增 `ReverseFlowAdjacency` 和 `load_reverse_call_adjacency()` |
| `code_review_graph/changes.py` | 🗒️ 未开始 | PR 2 需要 `analyze_changes()` 透传 `budget` 和 `flow_discovery_method` |
| `code_review_graph/tools/review.py` | 🗒️ 未开始 | PR 2 需要透传 `discovery_method` |
| `code_review_graph/postprocessing.py` | 🗒️ 未开始 | PR 3 需要重构 `_trace_flows` 为 summary-first |
