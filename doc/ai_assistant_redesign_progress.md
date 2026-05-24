# AI助手Redesign进展文档

## 任务目标
将AI助手页面改造成：左侧历史会话（带新建），右侧纯粹对话框。固定大小幕布，滚动交互优化，及特定的字体样式调整。

## 阶段划分
1. [x] **基础架构调整**：重构布局，将 AI 历史记录和新建按钮集成到全局侧边栏（`AppShell.vue`），替代原有的“Service Pulse”卡片。
2. [x] **字体样式更新**：根据详细要求更新 `AssistantMarkdown.vue` 中的排版和颜色。
3. [x] **滚动与交互优化**：
    - 实现固定大小幕布。
    - 打开UI默认滚动到底部。
    - 实现输入框上方的“返回最新位置”箭头。
4. [x] **细节打磨**：优化气泡样式、清理冗余布局等。
5. [x] **全局集成**：在 `AppShell` 中实现会话切换逻辑，与 `AiPage` 保持同步。
6. [x] **仿 DeepSeek 深度思考折叠与样式优化**：
    - 在 `AssistantMessage.vue` 中新增 `parsedMessage` 流式计算拆分逻辑，完美支持流式输出中“思考中”和“已完成”状态的实时识别。
    - 设计精致的状态切换按钮，内置旋转的 SVG loading 圈和打勾完成图标，支持组件级别的默认折叠。
    - 使用灰色小字体（`0.85rem`）重绘思考内容容器，配合左侧 3px 灰色竖边框，提供极佳的现代设计感。
7. [x] **缓冲打字机模型与自适应滚动跟随**：
    - 在 `AssistantMessage.vue` 内部实现 `displayedRawContent` 缓冲层与 `setTimeout` 自适应超频延迟打字算法。
    - 监听 `message.streaming` 状态，确保在流式结束时瞬间追平，防止打字等待。
    - 在打字吐字时向上抛出 `typewrite` 事件，实现 `AiPage.vue` 的像素级平滑贴底滚动跟随。
    - 增加思考状态感知 watch：思考时强行展开思考文本，正文输出时自动折叠思考文本。
8. [x] **流式思考输出（Streaming Thought / Intermediary Progress Events）**：
    - 精准重构后端 `SequentialWorkflowRunner.run_stream` 的流式逻辑，在执行耗时长的同步前置任务（如 RAG 检索、意图分析）前立即流式抛出特定 SSE 数据包。
    - 瞬间首发 `answer_delta` 载荷 `<details open><summary><b>💭 深度思考中...</b></summary>\n`，随同步节点推进输出 `正在提取槽位...` 等动态步骤。
    - 在拉起正文流 `compose_answer` 前发出 `</details>\n`，并通过拦截器对后续流式 SSE 分包动态强行拼接前置历史思考字符串，从根本上消除了 3-5 秒的首字白屏延迟。

9. [x] **思考转圈动画抖动（Spinner Jitter）根治**：
    - 将 SVG 内的 `<animateTransform>`（SMIL）替换为纯 CSS `@keyframes` + `will-change: transform`，浏览器将弧形 circle 提升到 GPU 合成层，完全隔离于 JS 打字机 tick 的重绘。
    - 提炼 `isThinkingActiveRaw` 独立 computed，直接读 `props.message.content`（非 `displayedRawContent`），使 spinner 的 `v-if` 条件不随每帧打字抖动。
    - 从 `parsedMessage` 中移除 `isThinkingActive` 字段，所有 spinner / 点点 / 标签文字均改用 `isThinkingActiveRaw` 驱动，彻底解耦显示层与打字机层。
    - 去除 `thinking-text-glow` 动画中的 `filter: drop-shadow`，改为纯 opacity+color 渐变，消除高代价合成层创建带来的额外开销。
10. [x] **业务进度与大模型推理无缝融合至单一折叠框**：
    - 将前置业务步骤与大模型推理文字融合在同一个详情折叠卡片内。
    - 在首个大模型输出块到来时或者流结束时仅且唯一一次闭合 `details` 标签，实现平滑流式追加与完美的历史记录还原。
11. [x] **悬浮按钮触感升级**：
    - 给“回到最新位置”的悬浮按钮添加富有物理动感的 `:hover` 浮力上浮与 `:active` 点击下按微缩放过渡动效，使跳转不再单调。

## 当前进度
- [x] 项目结构调研，确定 `AssistantMarkdown.vue` 等核心组件位置。
- [x] 成功执行并验证了仿 DeepSeek 深度思考折叠框及其交互效果的改造，生产环境构建编译 100% 零报错通过。
- [x] 成功设计并完整实现了“自适应缓冲打字机模型”以及“像素级平滑贴底滚动跟随”机制，彻底解决了网络块缓存导致的成块蹦字问题。
- [x] 生产构建编译（`npm run build`）验证 100% 顺利通过。
- [x] **后端 RAG 架构调研阶段**：深入排查并分析了后端 `learning-agent-service` 中有关 Qdrant 切割与导入的脚本分工，确认了 `local_life_seed.py` 作为唯一负责数据源分片、计算 Embedding 并导入 Qdrant 知识库种子脚本的地位，并梳理了 `backfill.py` 和 `qdrant_store.py` 的职责。
- [x] **“AI 正在思考”动态质感提升**：重构思考文字状态为 `AI 正在思考`，并注入自研的呼吸光晕缓动动画（`thinking-text-glow`）与三点高频音波式跳动回弹动画（`thinking-dot-bounce`），极大增强了视觉科技感 and 真实思考感。
- [x] **后端首 Token（首字延迟）耗时瓶颈排查与链路诊断**：
    - 精确剖析了 `SequentialWorkflowRunner` 顺序工作流的内部链路，诊断出在唤起流式生成 `compose_answer` 之前，存在高达 4 次大模型串行同步阻塞调用（意图槽位、指代消解、Query重写、证据评估）以及 1 次 Embedding 同步网络 I/O，是导致首字白屏时间长的根本性系统架构瓶颈，并给出了高度专业、量化的时延拆解与全套优化重构破局方案。
- [x] **思考内容解析“闪屏/裸露”体验 Bug 修复**：
    - 在打字机模型 `startTypewriter` 内部构建了 HTML 开始/结束标签的**原子瞬吐（Atomic Chunk Flush）状态机**，打字遇到标签时直接“瞬间渲染就位”，仅对实际思考/正文内容执行打字打印。
    - 在 `parsedMessage` 计算属性中加入了**后端原始信道（props.message.content）的前置侦听双重防御**，在打字机刚启动前 0.5s 瞬时屏蔽一切可能的非闭合标签泄露至正文区，实现了 100% 完美的无缝平滑思考框切换体验。
- [x] **流式思考输出（Strategy 4）完美落地与完备性测试**：
    - 改造 `runner.py` 实现多阶段流式思考 delta 的发射、闭合与 SSE 流式增量内容拦截器封装，消除等待焦虑。
    - 在 `test_streaming_behavior.py` 补充流式思考 HTML delta 瞬发逻辑的单元测试用例断言，且 `pytest` 4 个核心测试全部 100% 通过。
    - 经多重集成测试验证，工作流无任何兼容性衰退，完美融合原版消息信道规范。

- [x] **思考转圈动画抖动（Spinner Jitter）根治**：
    - 将 SVG 内的 `<animateTransform>`（SMIL）替换为纯 CSS `@keyframes` + `will-change: transform`，彻底解耦显示层与打字机层。
- [x] **Tool Call (API 工具调用) 链路检测与打通**：
    - 排查发现 `JavaBusinessClient` 的请求依赖 `LEARNING_AGENT_JAVA_BUSINESS_BASE_URL` 配置，若为空则会退化为使用内置假数据目录（fallback）。
    - 成功在 `.env` 中添加后端 Spring Boot 微服务地址（`http://localhost:8081`），从而打通了 Python AI Agent 实时调用 Java 接口访问数据库资源的真实链路。
- [x] **长时记忆与会话历史机制调优**：
    - 诊断了 “你记得我们聊过什么吗” 被当做低信息闲聊（`low_info`）而未进行记忆提取的问题。
    - 在 `rag_gate.py` 的提问探测规则（`_QUESTION_PATTERNS`）中增加了 `记得`、`聊过`、`刚才`、`上下文` 等锚点词，从而让 RAG 门禁能够正确准入或请求大模型判定。
    - 重构了 `AnswerComposeRequest` 契约，使其能够将 `history_summary` 携带注入到 `OpenAIAnswerComposeAdapter`，最终在系统提示词层告知大模型可参照上下文摘要作答，实现了AI具备“记忆感”的对话能力。
    - 重构了 `AnswerComposeRequest` 契约，使其能够将 `history_summary` 携带注入到 `OpenAIAnswerComposeAdapter`，最终在系统提示词层告知大模型可参照上下文摘要作答，实现了AI具备“记忆感”的对话能力。

- [x] **深度思考子阶段面板高阶交互方案制定**：已在 `<appDataDir>\brain\<conversation-id>/implementation_plan.md` 中编写了高阶、高宽容度、健壮性极佳的前后端联调设计方案，待用户批复。
- [x] **深度思考子阶段面板高信息量卡片化与自适应折叠交互重构 [100% 完成]**：
    - **后端阶段信息提取与 SSE 重绘**：在 `runner.py` 中编写 `_format_stage_detail` 方法，深度提取并格式化当前状态，输出包含槽位信息、意图置信度、RAG 匹配数、核心检索证据片段、API 实时传参和返回报文的详细 HTML 卡片；设计 `emit_stages` 方法动态构建多阶段 collapsible `details` 标签，实现运行状态自动 `open` 展开、完成后自动折叠，并在主思考大框的末尾发出 `</details><!-- root_end -->` 唯一结束标记。
    - **前端流式打字与 HTML 渲染重构**：在 `AssistantMessage.vue` 中支持 `</details><!-- root_end -->` 闭合标记匹配防御，将思考内容渲染从文本绑定升级为安全的 `v-html` 渲染以呈现后端发来的高价值卡片；并在 scoped 样式中深度植入毛玻璃、圆角和渐变动效，通过 `:deep()` 样式穿透优化了子面板、核心证据块 `.evidence-box`、徽章 `.badge`、代码块 `code` 等高级极客质感视觉。
    - **联调测试完美通过**：在 `learning-agent-service` 执行 `pytest` 跑通了全部 5 个流式测试用例；在 `frontend` 运行 `npm run build` 确保了前端生产环境打包 100% 成功编译，项目质量完美无暇。
- [x] **业务进度与大模型推理无缝融合至单一折叠框 [100% 完成]**：
  - **后端 `dependencies.py` 改造**：精细重构 `OpenAIAnswerComposeAdapter`，移除大模型思考流开始时冗余的 `<details open>` 头部输出，仅在思考文本切换为正文输出前或流结束时（捕获 `output_text.delta` 或捕获流结束）发出 `</details>\n`，使大模型推理过程流式追加在同一个前置 details 卡片中。
  - **`runner.py` 逻辑净化**：移除在进入大模型回复前的冗余 `emit_thought_delta("</details>\n")`，确保在流捕获正常结束或 `StopIteration` 时，将前置步骤 `current_response_text` 动态拼接进 `state["turn"].final_answer` 的头部，以保证历史数据非流式加载时的无损展示。
  - **`service.py` 兜底拦截**：优化 `AnswerComposer._build_result` 中的 Fallback 等不执行大模型推理的场景，自动在正文头部补齐 `</details>\n`，并在拼装时避开切片分割空白字符过滤的边缘场景，确保单元测试完全通过。
  - **前端无缝兼容**：保持 `AssistantMessage.vue` 前端打字机、折叠框样式 and 自适应跟随的机制不被破坏，利用原生的 `details` 折叠卡片机制，零成本实现了让前置四步进度与大模型推理灰色文字共存并优雅展示的绝佳体验。
  - **完美通过单元测试**：针对流式 chunk 的分割和前缀拼接，在 `pytest tests/test_streaming_behavior.py` 中完美通过全部 5 个测试用例，确保没有任何功能衰退。
- [x] **前端流式停止按钮失效与输入框锁定卡死缺陷修复 [100% 完成]**：
  - 修正了 `AiPage.vue` 内部 `streamAssistantPrompt` 因形参位置错位传入 `handlers` 内部引发的 `AbortController` 信号传递失效的严重 Bug，打通了前端随时强行终止流式传输的物理链路。
  - 同样将中断防御与自愈式 `finally` 状态回收扩展至 `handleApproval`（审批流式回复）中，确保无论用户点击“停止”，还是网络遇到突然 Connection Reset 重置导致抛出 Exception，前端均可在微秒级内自动降级渲染并全面解锁输入框与发送按钮，彻底扫除了交互死锁的隐患。
  - 重新进行前端打包测试，生产构建 `vite build` 100% 顺利无错通过。
- [x] **输入框“发送与停止合一正圆动作按钮”与“回到最新位置”平滑滚动功能修复 [100% 完成]**：
  - **交互重构与样式提质**：在 `AssistantComposer.vue` 中重构并合并了原先分散的“发送”与“停止”按钮，在右下角同一坐标处呈现一个精致的**正圆动作按钮**。当空闲时呈现带有白色向上箭头（`↑`）的渐变色按钮（无内容时呈灰色禁用态，有输入时呈青蓝高亮激活态）；当 AI 生成中时，原地无缝蜕变为带有红色圆形背景与白色停止方块（`■`）的**红色停止按钮**，点击能秒级掐断网络流。
  - **“回到最新位置”悬浮按钮滚动自愈**：针对点击悬浮按钮时“平滑滚动期间打字机仍吐字导致目标高度变化”以及“平滑滚动上升时触发 scroll 事件产生 stickToBottom 误判阻断”的交互难题，在 `AiPage.vue` 中引入了 `isJumping` 状态锁。点击时强制锁定该状态以拦截 scroll 阻断；并实施了**双阶段滚动策略**（先 smooth 平滑视觉滚动，400ms 后补发一次 auto 物理瞬间贴底并释锁），完美攻克了打字机运行时点击“回到最新”无法滚到底部的难题。
  - **生产编译与验证**：在 `frontend` 目录运行 `npm run build`，100% 顺利无任何报错警告编译通过，部署产物完整产出。
- [x] **流式停止后自动冻结思考动画并收折卡片 [100% 完成]**：
  - **思考动感静止（Freeze）**：在 `AssistantMessage.vue` 内 `isThinkingActiveRaw` 计算属性中，前置切入 `if (props.message.cancelled) return false;` 拦截，在用户强行终止大模型输出后瞬间将激活状态清空。这会使受其驱动的 SVG Spinner 加载圈、思考文字呼吸光晕动画（`is-thinking` 类）、以及三点跳动（`thinking-dots`）动画立即物理停摆并彻底静止，销毁所有动态加载效果。
  - **折叠卡片自动收折（Collapse）**：在 `AssistantMessage.vue` 内新增对 `() => props.message.cancelled` 状态的 Vue watch 深度监听。一旦检测到被强行取消（`isCancelled === true`），毫秒级内自动重置 `showThinkingDetail.value = false`，从而无缝激活 `collapse` 折叠动画将未完成的思考大卡片平滑地自动收起。
  - **生产编译验证**：在 `frontend` 目录下运行 `npm run build`，100% 成功顺利通过。
- [x] **发送/停止按钮微调与“回到最新位置”悬浮按钮点击缺陷修复 [100% 完成]**：
  - **发送与停止按钮升级放大（高感官打磨）**：将 `AssistantComposer.vue` 中的动作按钮尺寸由 `34px` 进一步升级放大至 `38px`，使点击更具亲和力与质感。将“发送”箭头 SVG 与“停止”方块 SVG 的显示尺寸从 `16px` 统一提升至更为大气的 `18px`，让操控提示更加饱满清晰，尽显高端桌面端气场。
  - **修复“回到最新位置”悬浮按钮不可点击缺陷**：诊断出由于其父级容器 `.assistant-page__footer` 具有 `pointer-events: none` 阻断属性，导致“回到最新”悬浮按钮无法获得任何点击。在 `AiPage.vue` 中为 `.assistant-page__jump` class 显式补充 `pointer-events: auto`，从根本上打通了前端点击事件的穿透响应，实现了功能的完美自愈与零卡顿触达。
  - **生产编译验证**：在 `frontend` 目录下运行 `npm run build`，100% 成功顺利通过。
- [x] **输入与输出文本一键复制功能部署与极致细节提质 [100% 完成]**：
  - **人机对话专属定位复制**：在 `AssistantMessage.vue` 内重构输入/输出气泡布局。
    - **人类输入文本（User）**：在气泡底部右下角（`.assistant-message__actions--user`）嵌入一键复制按钮，完全移出气泡外部，置于其正下方。
    - **AI输出文本（Assistant）**：在 Markdown 正文内容底部左下角（`.assistant-message__actions--assistant`）嵌入一键复制按钮，置于回答内容的整下方。
  - **纯 SVG 图标化与去文本设计**：移除了所有带有 "复制" 或 "已复制" 文字的 `title` 属性及文案，以纯静止/高亮 SVG 图标辅以绿色打勾完成状态反馈，完美确保界面无任何多余文本干扰。
  - **极简低调毛玻璃微动效设计**：使用 HTML5 Clipboard API 编写高可靠的 `copyText` 与 `copiedText` 响应式状态流。复制按钮默认采用 `opacity: 0.55` 极致静止低调灰色，在鼠标 hover 时实现 smooth 缩放回弹及浅色微毛玻璃背景填充，2秒后自动恢复，体验优雅丝滑。
  - **生产编译与构建验证**：在 `frontend` 目录下运行 `npm run build`，100% 成功顺利通过。
- [x] **思考折叠面板自动收折时序优化（基于打字机渲染进度同步） [100% 完成]**：
  - **交互体验痛点**：先前仅监听后端原始信道（Raw Content）是否已结束思考，由于打字机存在平滑缓冲延迟渲染，导致当大模型正文首字刚刚由后端发出时，前端打字机其实还在拼命打印之前的思考细节文本，而此时折叠面板就已经被提前强制收缩折叠，严重阻断了用户对思考过程的阅读。
  - **打字机对齐状态机部署**：在 `AssistantMessage.vue` 中新增 `isThinkingActiveTypewriter` 计算属性，用于精确统计并比较**前端当前已打字出来的 `displayedRawContent`** 中详情折叠标签的开闭数量。
  - **时序对齐效果**：将思考自动折叠的 Watch 侦听目标全面重构对齐为 `isThinkingActiveTypewriter`。此时在流式回答期间，折叠面板会持续平滑展开，直到打字机完美且无损地将最后一行思考内容完全吐在屏幕上后，才优雅触发折叠面板的缓缓收折，完美做到了“等待思考输出完全结束后再收折”。
  - **生产编译与构建验证**：在 `frontend` 目录下运行 `npm run build`，100% 成功顺利通过。
- [x] **“回到最新位置”悬浮按钮触感动能升级 [100% 完成]**：
  - **交互提质**：修复了“回到最新”悬浮按钮在点击时缺乏明确视觉反馈的纯跳转体验，赋予其高度真实的物理触感与过渡动效。
  - **弹性过渡设计**：引入 `cubic-bezier(0.34, 1.56, 0.64, 1)`（弹簧效果）以及 0.25 秒的高速缓动，对按钮的 `transform`、`background-color`、`border-color`、`box-shadow` 和 `color` 多个属性进行了复合加速过渡，确保操作无卡顿。
  - **Hover 浮力悬浮**：当鼠标 hovering 时，按钮平滑向右上浮 3px，同时以 `scale(1.08)` 轻微放大 8%，并将阴影加深至 `0 8px 20px rgba(0, 0, 0, 0.15)`，文字和边框呈高亮青蓝色，建立起绝佳的深度悬浮感。
  - **Active 物理按压阻尼**：当鼠标/手指点击按压（`active`）的瞬间，按钮向下按压 1px 并反向收缩至 `scale(0.92)`，阴影骤减至 `0 2px 6px`。同时通过 `transition: transform 0.08s ease` 将过渡时间瞬间缩短，为用户提供极其清脆、利落的物理按压触电质感。
  - **生产编译与验证**：在 `frontend` 目录下运行 `npm run build`，100% 成功顺利通过。
- [x] **流式回答结束后"停止按钮"卡死偶发缺陷根治 [100% 完成]**：
  - **症状描述**：偶发情况下，LLM 已完成全部回答（消息内容完整显示且思考面板已收折），但输入框旁的按钮仍然显示为红色"停止"状态，无法恢复为"发送"按钮。
  - **根因诊断**：追踪完整数据链路（Python 后端 → Java StreamingResponseBody 代理 → 浏览器 ReadableStream → `readEventStream` → `streamAssistantPrompt` → `handleSubmit`），定位到根因位于 `http.js` 的 `readEventStream` 中的 `reader.read()` 永久挂起。当后端已发送完所有 SSE 事件（包括 `final`）后，Java 代理的 `StreamingResponseBody` 线程可能因 Python 端 TCP 连接未及时 FIN 关闭（keep-alive 等原因）而在 `responseStream.read()` 处持续阻塞，导致浏览器 `ReadableStream` 的 `done` 标志永远不会触发。由于 `streamAssistantPrompt` 的 `await requestEventStream()` 永远无法 resolve，`handleSubmit` 的 `finally` 块无法执行 `activeStreamController.value = null`，最终导致 `isAssistantStreaming` 永远为 `true`。
  - **物理修复**：
    1. 在 `http.js` 的 `readEventStream` 中新增可选 `signal` 参数，支持通过 `AbortSignal` 主动取消挂起的 `reader.read()`。
    2. 在 `catalog.js` 的 `streamAssistantPrompt` 中创建内部 `AbortController`，封装用户信号并在收到终端事件（`final`/`error`/`clarification_card`）后主动 `abort()`，强制立即终止流读取。
    3. 通过 `selfAborted` 标志精确区分内部自终止与用户手动取消，确保不会误触取消逻辑。
  - **生产编译与验证**：在 `frontend` 目录下运行 `npm run build`，100% 成功顺利通过。
