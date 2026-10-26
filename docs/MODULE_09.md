# 模块 9：Adaptive Workspace UI

## 结构与职责

前端是写作工作区，不是聊天窗口。`frontend/src/layout.ts` 是确定性 Layout Policy：输入后端 `SessionView.stage` 与 `mode`，输出 `main`、`side`、`bottom` 三个区域的组件键。`frontend/src/components.tsx` 的固定 Component Registry 将键映射到预先实现的 React 组件；模型没有生成 React/HTML 的入口。

Registry 含作文编辑器、审题卡、教学对话区、语法错误卡、语法知识图谱、微课卡、练习题、段落结构图、内容展开卡、Revision Checklist、学习状态面板共 11 个组件。语法、结构、内容、语言、二次重写等阶段有各自的组件组合。独立模式仅配置写作编辑器，隐藏所有教学辅助组件及侧边阶段栏。二次重写阶段只展示学生原稿编辑器和修改清单，不渲染上一轮的完整教学文本或 AI 修改稿。

`frontend/src/App.tsx` 使用后端会话状态决定当前阶段和模式，不允许前端自行推进阶段。提交后重新读取 `SessionView`。浏览器 `localStorage` 只保存 Session/Student UUID，刷新时通过 `GET /sessions/{id}` 从数据库恢复题目、草稿、Stage、Mode 和 Student State。编辑器内容在成功提交后持久化；提交失败时本地草稿保留。同一份失败提交重试时复用请求 UUID，后端去重语义仍然有效。空状态、Loading、接口失败与重试都有明确视图。

## 接口与安全边界

- `POST /students`、`POST /tasks`、`POST /sessions`：创建工作区所需记录。
- `POST /sessions/{id}/turn`：提交当前阶段的学生输入；请求 ID 使用 UUID 以便后端去重。
- `GET /sessions/{id}?student_id=...`：恢复后端真实状态。语法阶段按需返回 `grammar_hints` 和 `knowledge_paths`。`grammar_hints` 不含 `corrected_expression` 或建议改写字段；知识图谱路径来自 Grammar Knowledge Graph，不由 RAG 生成。独立模式的 `last_result`、语法提示和知识路径为空。
- `VITE_API_BASE_URL` 可覆盖前端 API 地址；开发时 Vite 将相关路径代理到 8000 端口。DeepSeek Key 仅在后端私有 `.env` 中。

当前 HTTP 会话归属依赖调用方提供学生 UUID；尚无账号登录和生产身份认证。`localStorage` 仅用于记住会话标识，不承担身份认证。工作区不自动保存未提交文本，浏览器在提交前关闭会丢失本地编辑内容。能力面板显示 Student State 的实际值；没有证据时明确标注初始估计。语法提示只覆盖现有 Analyzer 能识别的保守规则。

最终评估完成后，工作区将两稿比较显示为“学习反馈”，隐藏无法再提交的导师问题输入，按钮不可再次执行。浏览器刷新后从数据库恢复已完成状态与第二稿。

## 验证与截图

`frontend/src/layout.test.tsx`、`api.test.ts`、`App.test.tsx` 覆盖 28 项前端检查，包括各 Stage 组合、独立模式、知识图谱、结构/内容组件、二次重写、状态驱动、刷新恢复、空/加载/错误状态、提交失败保留草稿、失败重试去重和注册表。`tests/test_module9_workspace_api.py` 使用真实 PostgreSQL 与 FastAPI 检查会话流进入语法阶段后的 UI 数据合同及独立模式权限；教学模型在该集成测试中使用可控 Provider，模型真实调用已在模块 7、8 验收。

真实浏览器检查使用 `scripts/verify_workspace_browser.mjs`：先通过本地 HTTP 创建 Student/Task/Session，再在 Chrome 中写入会话 ID 并刷新两次，确认审题组件及 Student State 从数据库恢复。加 `--advance` 后调用真实 DeepSeek 工作流，浏览器刷新进入初稿。该次实测返回 Evaluator `pass`；PostgreSQL 中 Stage 为 `first_draft`，有 2 个完成事件、4 条 Tool Trace、1 条学习证据。执行时需启动后端、Vite 和本地 Chrome DevTools 9222 端口。截图：[空状态](assets/module9-empty.png)、[审题工作区](assets/module9-workspace.png)、[真实回合后的初稿工作区](assets/module9-first-draft.png)。

前端使用 React、Vite、TypeScript、Vitest、Testing Library 和 Lucide 图标。示例工作区题目是脚本生成的项目演示数据，不属于公开 Benchmark；语法知识点和例句数据来源仍见模块 3、4 文档。评估指标与基准数据在模块 10 才实施。
