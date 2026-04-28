# Session: flow-scaling-pr1

**Date:** 2026-04-20
**Project:** code-review-graph
**Topic:** 实现 Flow Scaling Plan 的 PR 1 —— Safety Fix + Summary Contract

## 做了什么

本会话完整实现了 `docs/FLOW-SCALING-PLAN.md` 的 Phase 0 + Phase 1，即 PR 1 的全部内容。

从阅读现有代码开始，确认了两处静默截断（`_MAX_ENTRY_POINTS=3000` 和 `_MAX_FLOW_NODES=500`），以及 `flows` 表缺少完整性元数据列的问题。随后制定了三 PR 拆分计划（已批准），并完整实现了 PR 1。

主要变更：
1. **migrations.py**：新增 `_migrate_v10`，给 `flows` 表添加 7 列 + 2 索引
2. **flows.py**：新增 `FlowBudget` dataclass；`_trace_single_flow` 改为接受 `budget`，超限时设 `is_complete=False` + `truncated_reason`；`store_flows`/`incremental_trace_flows` 写入新列；`get_flows`/`get_flow_by_id` 读取新字段
3. **tools/flows_tools.py**：`list_flows` 加 `completeness_warning`，`get_flow` 透传 `is_complete`/`truncated_reason`
4. **测试**：新增 `TestFlowBudget`、`TestFlowCompletenessMetadata`，以及 migrations/tools 验证测试

## 当前状态

- ✅ 完成: PR 1 全部代码变更（129 个目标测试通过，ruff lint 通过）
- ✅ 完成: 三 PR 拆分计划已写入 `~/.claude/plans/docs-flow-scaling-plan-md-sequential-lovelace.md`
- 🗒️ 未开始: PR 2 — Review-First Affected Flow Discovery
- 🗒️ 未开始: PR 3 — Lazy Expansion + Postprocess Optimization

## 失败的方案（不要重试）

- 深度截断检测用 `frontier_size > 0` 判断 — 原因：BFS 结束时 queue 已清空，frontier_size 恒为 0。改为在循环内追踪 `depth_truncated` 布尔值

## 下一步

开始实现 PR 2。入口：

1. 在 `code_review_graph/graph.py` 的 `FlowAdjacency` 定义之后新增 `ReverseFlowAdjacency` dataclass
2. 新增 `GraphStore.load_reverse_call_adjacency()` 方法（只加载 Function/Test 节点 + CALLS 边）
3. 在 `flows.py` 新增 `find_candidate_entry_points_for_nodes()`
4. 重构 `get_affected_flows()` 为双路径策略

详细 checklist 见 `~/.claude/plans/docs-flow-scaling-plan-md-sequential-lovelace.md` 的「PR 2」章节。

## 环境备注

```bash
# 运行目标测试
uv run pytest tests/test_flows.py tests/test_migrations.py tests/test_tools.py -q

# lint 检查
uv run ruff check code_review_graph/

# 全套测试（注意 test_parser.py / test_refactor.py 有预存失败，不是本 PR 引入的）
uv run pytest tests/ --tb=short -q
```
