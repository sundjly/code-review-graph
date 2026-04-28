# 知识图谱当索引：code-review-graph 是怎么让 Claude 少读 90% 代码的

想象一个场景：你的代码库有 50 万行，刚改了三个函数，找 Claude 帮你 review 一下影响范围。

它怎么做？

最朴素的做法是让它读文件。改了 `auth.py`？读 `auth.py`。有没有地方调用了 `authenticate()`？逐目录 grep，再把相关文件一起喂进去。顺便把依赖文件也带上，万一有用。一圈下来，几千行代码进了上下文窗口，大半是没用的，但你不知道该扔哪些。

这不叫 code review，这叫把 Claude 当搜索引擎用，还是那种每次都得重新建索引的搜索引擎。

---

## 问题的本质：每次读文件是在重复"理解代码结构"这件事

说实话，我搭这个工具之前也没想清楚问题在哪。以为 token 贵是贵在"代码太长"，所以想着截断、压缩、精简。

后来发现截错了方向。

真正贵的不是代码长度，而是**每次 review 都要从头重新解析代码结构**。函数调用谁、谁调用它、改一行会影响哪条执行路径——这些关系是固定的，代码不变它就不变。但每次对话，Claude 都得重新从文件内容里把这些关系"推导"出来，用的是它自己的注意力，折算下来就是 token。

这就像你每次进图书馆找书，不看目录，直接从第一排书架开始翻。每次都这样，浪费的不是体力，是时间。

code-review-graph 干的事情很简单：**把代码的结构关系提前算好，存成一张图，放在 SQLite 里。review 的时候查图，不读文件。**

---

## 把代码库变成一张可以查询的地图

工具链是这样的：Tree-sitter 解析源码，提取 AST；AST walker 识别函数、类、调用关系、继承、导入；然后把这些节点和边写进 SQLite。

![构建流程：从源码到可查询的知识图谱](code-review-graph-token-saving-fig1-flow.html)

支持 23 种语言，Python、TypeScript、Go、Rust、Java、Kotlin、Vue、Solidity 都在里面，还有 Jupyter notebook 和 Databricks notebook。解析完之后，一个函数在图里是一个 node，它调用谁是一条 `CALLS` 边，谁继承了它是一条 `INHERITS` 边。

建图是一次性的。增量更新靠 `git diff`——哪些文件改了，只重解析那些文件，顺带更新依赖它们的节点。大仓库第一次全量 build 大约 30-60 秒，之后每次增量 < 2 秒。

图建好之后，Claude Code 通过 MCP 协议查图，拿到的是结构化的精准答案，而不是原始文件内容。

---

## 问图，不问文件：30 个工具，每个都比直接读文件便宜得多

这套系统暴露了 24 个 MCP tool。大部分使用场景用不到一半。

最重要的入口是 `get_minimal_context`：

```
get_minimal_context_tool(task="review auth changes")
```

返回大约 100 tokens。包含风险等级、受影响的模块、执行流路径、建议的下一步工具。就这些，100 tokens，Claude 已经知道这次改动大概在干什么、有没有高危路径。

然后是 `get_impact_radius`——改了哪个函数，往外扩 2 跳，受影响的节点全列出来，带风险评分：

```
get_impact_radius_tool(node_id=42, max_depth=2)
```

比手动 grep 准，比读文件省。普通场景整个 review 上下文控制在 800 tokens 以内。

![token 用量对比：传统方式 vs 知识图谱](code-review-graph-token-saving-fig2-info-cards.html)

还有 `detect_changes`，它把 git diff 的行号范围映射到具体的函数节点，再关联到执行流和社区（模块簇），最后给出风险排序的 review 列表。不是"哪些文件变了"，而是"哪条调用链受到影响，测试覆盖缺口在哪"。

`query_graph` 支持直接查关系：谁调用了这个函数（`callers_of`），这个类继承了什么（`inherits`），哪些测试覆盖了这个节点（`tests_for`）。精确到节点，没有废话。

---

## 增量更新：不重建，只修正

坑就在这里。很多人建图的时候觉得挺好，用了一段时间图就"过期"了，和代码对不上，反而更糟。

code-review-graph 的增量更新是这样设计的：

每个文件存一个 hash。文件没变，hash 没变，跳过解析。文件变了，重解析这个文件，同时通过图里的边关系找出依赖这个文件的其他文件，一起更新。不是简单 diff，是图感知的级联更新。

执行流（flows）也是增量的。哪条调用链里的节点被改了，只重新 trace 那条链，其他链不动。

钩子可以挂在 Claude Code 的 PostToolUse 事件上——每次写文件之后自动触发增量更新，不用手动跑命令。这样图永远跟当前代码状态同步。

---

## Opus 4.7 的工作方式，和这套系统配合得很好

说到这里可以聊 Opus 4.7 了。

这个模型有个变化我觉得很关键：它从"指挥官"变成了"匠人"。默认不再自动调度并发 agent，推理更深，但单线程走。同时 Anthropic 也明确说，它适合批量式交互——一开始把任务说清楚，让它跑，别在中途插话改方向。

这和知识图谱的价值方向完全对齐。

图给的不是文件内容，是结构化的结论：这里有风险，这条链受影响，测试覆盖这里缺口。Claude 拿到这些，不需要自己再去"探索"代码，直接在精准的上下文里深度推理。批量式的、高质量的输入，得到批量式的、高质量的输出。

还有一个点：Opus 4.7 换了新 tokenizer，长会话后半段推理量会增加，成本比 4.6 更依赖上下文质量。你喂的上下文越精准，它浪费的注意力越少。

传统 review 流程是往上下文里塞文件，祈祷 Claude 自己找到重点。现在的做法是把重点提前算好，只把重点喂给它。

![review 工作流对比：传统方式 vs code-review-graph](code-review-graph-token-saving-fig3-comparison.html)

---

## 上下文不是仓库，是工作台

这里有一个更底层的东西值得说一下。

Opus 4.7 的文章里有个词我反复在想：context rot（上下文腐烂）。随着会话越来越长，模型注意力分散到越来越多的内容上，早期的无关信息开始干扰当前推理。工作台堆满了，效率反而下降。

知识图谱解决的正是这个问题，但在另一个维度。

它不是把代码放进上下文，而是**把代码结构提取成外脑**，需要的时候精准查询，不需要的时候完全不占上下文空间。这相当于把"理解代码库结构"这件事从每次对话里永久移出去，放进一个独立的、可以按需访问的索引层。

每次 review，Claude 的上下文里只有 5 个 tool call，800 tokens 的结构化结论，加上真正需要看的代码片段。工作台永远是干净的。

这不只是省 token。这是让 Claude 的推理始终聚焦在真正有价值的问题上——这个改动安不安全，这条路径有没有测试盲区，这个 PR 值不值得 approve。

> 让 AI 变聪明有两条路：一条是换更强的模型，另一条是减少它需要处理的噪音。图谱做的是第二件事，而且这件事可以一直做。

---

## References

1. Anthropic, ["Best practices for using Claude Opus 4.7 with Claude Code"](https://claude.com/blog/best-practices-for-using-claude-opus-4-7-with-claude-code), 2026-04-20.
2. Anthropic, ["Using Claude Code: Session management and 1M context"](https://claude.com/blog/using-claude-code-session-management-and-1m-context), 2026-04-20.
3. sandy, [code-review-graph](https://github.com/ai-is-fun/code-review-graph), 2026-04-20.
