# Paper-Copilot 项目文档

基于 LangGraph 自定义 StateGraph 的学术论文智能助理，包含两张图：Research Graph（研究问答）和 Paper Workflow Graph（论文入库流水线）。

---

## 一、图一：Research Graph 节点与流转

ReAct 循环（Reason → Act → Observe → Reason），6 个节点，代码在 `service/graph/nodes.py`，路由在 `service/graph/router.py`。

### 1. `plan_node` — 问题分析
判断用户意图；复杂问题调 LLM 拆成多个搜索角度。

#### 1.1 闲聊
用户说"你好""谢谢"等，返回空搜索角度，跳过所有搜索。
→ `synthesize_node`

#### 1.2 寻找论文（discovery_mode=True）
用户说"帮我找 Mamba 架构的最新论文"等，本地库没有相关内容，跳过本地检索。
→ `arxiv_search_node`

##### 1.2.1 `arxiv_search_node` — arXiv 联网搜索
调用 arXiv API 搜索论文，将返回的标题、作者、摘要格式化为伪文档，补充进搜索结果。标记 `arxiv_searched=True`，只执行一次避免重复调用外部 API。
有两个入口：`plan_node` 的发现意图直接进入，以及 `evaluate_results_node` 的兜底进入。
→ `synthesize_node`

#### 1.3 角度太多 + 中断开启
拆出的搜索角度数量 ≥ 阈值（默认 3），让用户确认后再搜。
→ `human_review_node`

##### 1.3.1 `human_review_node` — 人工审核确认
调用 LangGraph 的 `interrupt()` 暂停图执行，将搜索角度列表通过 SSE 推给前端展示。用户勾选后通过 `POST /api/chat/resume` 恢复。
- 用户选定了角度 → `search_angle_node`（Send API 并行扇出）
- 用户全部拒绝 → `synthesize_node`

#### 1.4 正常学术提问
用户问"Transformer 和 CNN 谁更好？"，LLM 拆出多个搜索角度，通过 LangGraph Send API 并行扇出。第 2 轮起 prompt 中附带已搜过的角度列表和已找到的片段数量，让 LLM 生成**新的**补充搜索角度而不是重复旧角度。
→ `search_angle_node`（N 个实例并行执行）

---

### 2. `search_angle_node` — 知识库检索（并行）
每个搜索角度启动一个独立实例，同时去 Chroma 向量库做相似度检索，返回相关论文段落。所有实例的结果由自定义 Reducer 按（内容前 80 字 + 论文标题）自动合并去重。本节点不调 LLM，纯向量数学运算。
→ `evaluate_results_node`

---

### 3. `evaluate_results_node` — 结果检查
LLM（temperature=0.0）审查所有已检索到的论文片段，判断是否足以回答用户问题。

#### 3.1 搜够了（SUFFICIENT）
→ `synthesize_node`

#### 3.2 内容不够 + 未达最大轮次
→ 回到 `plan_node`（重新拆角度，Reason again）

#### 3.3 本地库完全没结果 + arXiv 未试过
→ `arxiv_search_node`（兜底搜索）

#### 3.4 已达最大搜索轮次
→ `synthesize_node`（强制回答，有多少答多少）

---

### 4. `synthesize_node` — 生成回答
汇总所有搜到的论文片段（可能来自本地 Chroma + arXiv 两路），按内容前 80 字去重，每段截断至 1200 字、总计不超过 8000 字。调用 LLM（streaming=True），逐 token 通过 `get_stream_writer()` 发射 SSE 事件给前端，实现流式输出。最终回答中标注论文来源。
→ END

---

### 5. 核心循环

```
plan_node(思考) → search_angle_node(行动) → evaluate_results_node(观察)
    ↑                                                │
    └────────── 不够，重新拆角度（Reason）←─────────────┘
```

循环上限由 `GRAPH_MAX_SEARCH_ITERATIONS` 控制，默认 3 轮。

### 6. 路由决策表

| 路由函数 | 条件 | 去向 |
|---|---|---|
| `route_after_plan` | discovery_mode=True | `arxiv_search_node` |
| `route_after_plan` | search_angles 为空 | `synthesize_node` |
| `route_after_plan` | 角度 ≥ 阈值 + 中断开启 | `human_review_node` |
| `route_after_plan` | 正常 | `search_angle_node`（Send 并行扇出） |
| `route_after_human_review` | 用户选了角度 | `search_angle_node`（Send 并行扇出） |
| `route_after_human_review` | 全拒绝 | `synthesize_node` |
| `route_after_evaluate` | SUFFICIENT | `synthesize_node` |
| `route_after_evaluate` | NEEDS_MORE + iter < max | `plan_node` |
| `route_after_evaluate` | 本地空 + arXiv 未试 | `arxiv_search_node` |
| `route_after_evaluate` | iter ≥ max | `synthesize_node` |

---

## 二、图二：Paper Workflow Graph 节点与流转

纯线性流水线，无循环，4 个节点。代码在 `service/graph/paper_workflow_nodes.py`。

### 1. `discover_node` — 论文发现
LLM 把中文研究主题转为英文搜索词，调 arXiv API 搜索论文；结果少就换关键词重搜。
- 找到论文 → `screen_node`
- 没找到 → END

### 2. `screen_node` — 质量筛选
LLM 逐篇评估质量分和相关度分（0-10），自动打标签，低于阈值（默认 5.0）的丢弃。
- 有论文通过 → `analyze_node`
- 全部被过滤 → `store_node`（仅存元数据）

### 3. `analyze_node` — 深度分析
LLM 逐篇做六维结构化提取：背景、方法、实验、贡献、局限、关键词。
→ `store_node`

### 4. `store_node` — 入库存储
论文元数据和分析结果写入 SQLite。后续上传 PDF 全文、分词向量化后进入 Chroma 向量库，可被图一检索。
→ END

---

## 三、两图关系

```
图二（Paper Workflow Graph）
    │  产出：论文元数据 + 分析结果 → SQLite
    │  上传 PDF → 分词向量化 → Chroma 向量库
    ▼
图一（Research Graph）
    │  从 Chroma 向量库检索论文片段
    │  兜底时从 arXiv 在线搜索
    │  最终生成带引用的流式回答
    ▼
  用户
```

图一是用户的日常交互入口（提问→回答），图二是批量入库工具（研究方向→论文入库）。两者通过 Chroma 向量库连接。

---

## 四、关键文件索引

| 文件 | 内容 |
|---|---|
| `app.py` | Flask 主入口，所有 API 路由 |
| `service/graph/nodes.py` | 图一 6 个节点函数 |
| `service/graph/router.py` | 图一 3 个条件路由函数 |
| `service/graph/state.py` | 图一 State TypedDict + Reducer |
| `service/graph/research_graph.py` | 图一 StateGraph 构建与编译 |
| `service/graph/paper_workflow_nodes.py` | 图二 4 个节点函数 |
| `service/graph/paper_workflow_state.py` | 图二 State TypedDict |
| `service/graph/paper_workflow_graph.py` | 图二 StateGraph 构建与编译 |
| `service/graph/checkpoint.py` | 检查点工厂（Memory/SQLite） |
| `service/graph/streaming.py` | SSE 流式适配器 |
| `service/vector_service.py` | Chroma 向量库管理 |
| `service/pdf_service.py` | PDF 解析 + 学术章节识别 + 语义分块 |
| `service/storage_service.py` | 本地文件存储（论文 PDF + 向量库备份） |
| `service/paper_library.py` | SQLite 论文元数据库 |
| `service/paper_discovery_service.py` | arXiv 论文搜索 |
| `service/paper_screening_service.py` | LLM 论文质量筛选 |
| `service/deep_analysis_service.py` | LLM 六维结构化提取 |
| `service/contradiction_service.py` | 跨论文矛盾检测 |
| `service/summarize_service.py` | 结构化文献综述 |
| `service/agent_service.py` | Research Graph 调用封装 |
| `prompts/templates.py` | 所有 LLM 提示词模板 |
| `config/settings.py` | 全局配置项 |
