# Frontdoor And Intent 路径分析

> 目标：说明一个 `query` 刚进入服务后，如何经过入口门禁、顶层意图路由，最后分到“直接回答 / 本地生活 / 安全拦截 / 澄清”这些大分支。

> 实测提示：当前环境里，`ChatStreamTestClient` 对中文闲聊/超范围句子有时会在最前面就落到澄清分支，所以本页更适合用“路由结果”而不是“自然语言外观”来判断是否真的命中门禁。

## 适用节点与代码直达链接

以下是本流程涉及的所有核心节点，点击链接可直接跳转到代码实现处：

- `load_context`: [stages_front_a.py:L33](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/application/workflow/adapters/stages_front_a.py#L33) (加载历史上下文与初始状态)
- `request_legality`: [stages_main_graph.py:L503](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/application/workflow/adapters/stages_main_graph.py#L503) (业务合法性阻断)
- `illegal_request_response`: [stages_main_graph.py:L718](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/application/workflow/adapters/stages_main_graph.py#L718) (生成非法请求的阻断回复)
- `hard_guard`: [stages_main_graph.py:L481](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/application/workflow/adapters/stages_main_graph.py#L481) (强规则干预与兜底策略)
- `clarification_or_reject`: [stages_main_graph.py:L356](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/application/workflow/adapters/stages_main_graph.py#L356) (根据状态判断执行澄清追问或直接拒绝)
- `query_safety`: [stages_main_graph.py:L515](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/application/workflow/adapters/stages_main_graph.py#L515) (用户输入的安全性与敏感词检测)
- `safety_reject_response`: [stages_main_graph.py:L727](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/application/workflow/adapters/stages_main_graph.py#L727) (生成安全原因导致的拒绝回复)
- `understand_turn`: [builder.py:L1774](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/application/workflow/builder.py#L1774) (核心意图解析子图入口)
- `top_level_intent_router`: [stages_main_graph.py:L586](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/application/workflow/adapters/stages_main_graph.py#L586) (顶层流量分发路由器)
- `identity_answer`: [stages_main_graph.py:L682](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/application/workflow/adapters/stages_main_graph.py#L682) (我是谁/身份认知类回复)
- `capability_answer`: [stages_main_graph.py:L691](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/application/workflow/adapters/stages_main_graph.py#L691) (能力介绍类回复)
- `direct_chat_answer`: [stages_main_graph.py:L700](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/application/workflow/adapters/stages_main_graph.py#L700) (闲聊类短平快直答)
- `out_of_scope_response`: [stages_main_graph.py:L709](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/application/workflow/adapters/stages_main_graph.py#L709) (超纲问题拒绝回复)
- `final_answer`: [stages_main_graph.py:L833](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/application/workflow/adapters/stages_main_graph.py#L833) (组装最终的流式/非流式输出)
- `query_merge_for_local_life`: [stages_main_graph.py:L526](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/application/workflow/adapters/stages_main_graph.py#L526) (进入本地生活域的衔接入口)

## 主流程

```text
query
  -> load_context
  -> request_legality
       -> illegal_request_response
       -> hard_guard
            -> clarification_or_reject
            -> query_safety
                 -> safety_reject_response
                 -> understand_turn
                      -> top_level_intent_router
                           -> identity_answer
                           -> capability_answer
                           -> direct_chat_answer
                           -> out_of_scope_response
                           -> safety_reject_response
                           -> final_answer
                           -> query_merge_for_local_life
```

## 每个节点做什么

### `load_context` ([查看代码](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/application/workflow/adapters/stages_front_a.py#L33))

- **功能**: 加载会话上下文。
- **作用域**: 补齐 persistent session（长期记忆）、短期记忆、历史状态。如果之前问了澄清问题（pending clarification），这一层负责解析用户的新回答并恢复话题。这一层也会执行初步的 RAG Gate 预检。

### `request_legality` ([查看代码](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/application/workflow/adapters/stages_main_graph.py#L503))

- **功能**: 做请求的业务合法性检查。
- **作用域**: 拦截业务层不允许的情况，如果被判定为阻断类请求，会直接走向 `illegal_request_response`。这是最靠前的一层业务安全门禁。

### `hard_guard` ([查看代码](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/application/workflow/adapters/stages_main_graph.py#L481))

- **功能**: 做硬规则匹配检查。
- **作用域**: 通过正则表达式、强匹配词库拦截恶劣输入。如果 `blocked = true`，进入 `clarification_or_reject` 节点；否则走向 `query_safety`。

### `query_safety` ([查看代码](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/application/workflow/adapters/stages_main_graph.py#L515))

- **功能**: 基于模型或外部服务的综合安全检查。
- **作用域**: 检查黄赌毒等涉政敏感信息。如果 unsafe 直接去 `safety_reject_response` 生成标准拒绝文案，否则才会进入 `understand_turn` 做自然语言意图理解。

### `understand_turn` ([查看代码](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/application/workflow/builder.py#L1774))

- **功能**: 自然语言理解子图（SubGraph）。
- **作用域**: 执行分类（`parse_intent_slots`）、指代消解（`resolve_reference`）和歧义检查（`ambiguity_check`），把结构化的意图、槽位（比如城市、餐厅名）、以及是否需要走 RAG 检索（`needs_rag`）和工具调用的标识全都写进 State。

### `top_level_intent_router` ([查看代码](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/application/workflow/adapters/stages_main_graph.py#L586))

- **功能**: 顶层意图分发。
- **作用域**: 第一个真正决定**回答类别**的分叉点。通过读取 `understand_turn` 中写入的 `routing.required_action` 等信息，将流程派发给各个专用处理器（如闲聊、能力认知、本地生活域等）。

常见路由分支：

- `identity_answer`：用户在问“你是谁 / 你能做什么”
- `capability_answer`：用户在问能力介绍
- `direct_chat_answer`：闲聊类，无需查库直接回复
- `out_of_scope_response`：超出业务范围（不在本地生活、闲聊范畴内）
- `safety_reject_response`：再次命中安全拒绝
- `final_answer`：已有完整直答，不需要继续往本地生活链路走
- `query_merge_for_local_life`：判定用户在问美食、找店等核心业务，准备进入本地生活域进行复杂的检索。

## 典型 case 分析

### Case 1: 纯身份/能力问题

```text
query -> load_context -> request_legality -> hard_guard -> query_safety
     -> understand_turn -> top_level_intent_router
     -> identity_answer / capability_answer / direct_chat_answer
     -> final_answer -> final_answer_safety -> response_builder -> persist_session -> emit_final
```

适合问题：
- `你是谁`
- `你能干什么`
- `聊聊天`

### Case 2: 明显违规或拒绝类

```text
query -> load_context -> request_legality
     -> illegal_request_response
     -> final_answer -> final_answer_safety -> response_builder -> persist_session -> emit_final
```
或者：
```text
query -> load_context -> request_legality -> hard_guard
     -> clarification_or_reject
     -> final_answer
```

### Case 3: 安全拒绝

```text
query -> load_context -> request_legality -> hard_guard -> query_safety
     -> safety_reject_response
     -> final_answer
```

### Case 4: 本地生活大类 (核心业务场景)

```text
query -> load_context -> request_legality -> hard_guard -> query_safety
     -> understand_turn
     -> top_level_intent_router
     -> query_merge_for_local_life
```

走向 `query_merge_for_local_life` 后，意味着流量成功穿透基础层，将进入本地生活专属链路，执行 RAG、工具调用和多步推荐引擎，详见 `03_local_life_standard_workflow.md`。

## 你应该重点看哪里

- 如果你想知道“为什么有些 query 直接答了，有些却进了本地生活链路”，看 [`top_level_intent_router`](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/application/workflow/adapters/stages_main_graph.py#L586)
- 如果你想知道“为什么一上来就被拒绝”，看 [`request_legality`](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/application/workflow/adapters/stages_main_graph.py#L503) / [`hard_guard`](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/application/workflow/adapters/stages_main_graph.py#L481) / [`query_safety`](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/application/workflow/adapters/stages_main_graph.py#L515)
- 如果你想知道“为什么要先加载记忆或识别追问”，看 [`load_context`](file:///d:/javacode/hm-dianping/learning-agent-service/src/learning_agent_service/application/workflow/adapters/stages_front_a.py#L33)

## 实测 case

### `D11-2` 缺少店名的券查询

输入：
```text
有券吗？
```

实际观察到：
- `route_gate.branch = clarify`
- `route_gate.required_action = clarify`
- 最终输出是澄清式回复（触发了缺少核心参数的追问逻辑）。

### `D5-1` 附近推荐

输入：
```text
附近有没有推荐的餐厅？
```

实际观察到：
- `top_level_intent_router` 判断意图后，进入了本地生活推荐方向。
- `route_gate.branch = recommendation`
- 后续顺利通过 `query_merge_for_local_life` 进入本地生活核心检索链路，不会在外部阻断。
