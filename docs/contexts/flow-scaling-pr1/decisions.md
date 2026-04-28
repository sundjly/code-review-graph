# 关键决策

## D1: FlowBudget 作为 dataclass 而非函数参数

- **选择**: 新增 `FlowBudget` dataclass，统一封装所有 BFS 限制参数
- **原因**: 三个 PR 都需要传递 budget 信息，dataclass 可以在 `_trace_single_flow`、`detect_entry_points`、`trace_flows`、`get_affected_flows` 之间一致传递，避免参数爆炸
- **放弃**: 继续用 `max_depth`/`max_nodes` 散参数 —— 放弃原因：PR 2/3 还需要更多 budget 字段，散参数会导致函数签名越来越长

## D2: 深度截断检测改为 depth_truncated 布尔标记

- **选择**: 在 BFS 循环内当 `depth >= budget.max_depth` 时，检查是否有未访问的有效 callees，若有则设 `depth_truncated = True`
- **原因**: BFS 结束时 queue 为空，无法用 `frontier_size > 0` 判断是否因深度截断
- **放弃**: `frontier_size > 0` 判断 —— 放弃原因：BFS while loop 结束时 queue 已耗尽，frontier_size 恒为 0，无法区分"正常结束"和"深度截断"

## D3: get_flows / get_flow_by_id 用列名检测兼容旧 schema

- **选择**: 读取新列前先检查 `col_names` 是否包含 `is_complete`，兼容未跑 migration v10 的旧数据库
- **原因**: 迁移是增量的，老数据库打开后不一定立即跑 migration（测试环境会跑，但要保证代码健壮）
- **放弃**: 直接访问 `row["is_complete"]` —— 放弃原因：对旧 schema 会抛 KeyError

## D4: store_flows 对 summary-only flow 也写 flow_memberships

- **选择**: PR 1 中 `store_flows` 仍然为所有 flow 写 memberships（`is_expanded=True`），不改变现有行为
- **原因**: PR 3 才引入 summary-only 存储；PR 1 只加元数据列，不改存储语义，降低回归风险
- **放弃**: PR 1 就引入 `is_expanded=False` 的 summary-only 路径 —— 放弃原因：会破坏现有 `get_affected_flows` 的 membership_lookup 快速路径
