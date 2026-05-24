# toolcall 的实现

这份文档总结当前 Python 服务里的 toolcall 机制。它的定位不是“随便让模型调函数”，而是先由路由和计划器判断，再由执行器和归一化器完成真正的工具链路。

## 一、toolcall 在哪里起作用

toolcall 主要在这些场景发挥作用：

- 本地生活推荐
- 商家详情查询
- 分类列表查询
- 优惠券查询
- 探店笔记查询
- 距离和 ETA 估算
- 营业状态查询
- 预约 / 下单 / 取消 / 退款 / 订单状态查询

它通常和路由决策绑定，只有当前请求确实需要外部业务动作或最新状态时才会进入 tool 链路。

## 二、当前能调用哪些 API

### 1. 只读类

| 工具名 | 功能 |
| --- | --- |
| `search_restaurants` | 搜索餐厅候选，按地点、价格、品类、场景推荐 |
| `get_shop_detail` | 获取单个商家详情 |
| `get_shop_type_list` | 获取商家类型列表 |
| `get_coupon_list` | 获取优惠券列表 |
| `get_blog_list` | 获取探店笔记 |
| `get_distance_eta` | 估算距离和到达时间 |
| `check_open_status` | 查询营业 / 关店状态 |
| `get_order_status` | 查询订单状态 |

### 2. 写入 / 高风险类

| 工具名 | 功能 | 备注 |
| --- | --- | --- |
| `create_booking` | 创建预约 | 需要审批 |
| `create_order` | 创建订单 | 需要审批 |
| `cancel_order` | 取消订单 | 需要审批，风险更高 |
| `refund_order` | 发起退款 | 需要审批，风险更高 |

## 三、toolcall 的实现链路

```text
用户请求
  |
  v
[Routing Decision]
  |
  +--> tool_call / rag_plus_tool
  |
  v
[ToolPlanner]
  |
  +--> 选工具名
  +--> 组装工具输入
  +--> 判断是否需要审批
  |
  v
[ToolExecutor]
  |
  +--> 调 JavaBusinessClient
  +--> 或走本地 / catalog fallback
  |
  v
[ToolResultNormalizer]
  |
  v
[Compose Answer]
```

## 四、Planner、Executor、Normalizer 分别做什么

### 1. ToolPlanner

它负责把“意图”映射成“具体工具”。

例如：

- `restaurant_recommendation` -> `search_restaurants`
- `restaurant_detail` -> `get_shop_detail`
- `restaurant_coupon` -> `get_coupon_list`
- `restaurant_blog` -> `get_blog_list`
- `restaurant_shop_type` -> `get_shop_type_list`
- `restaurant_distance_eta` -> `get_distance_eta`
- `restaurant_open_status` -> `check_open_status`
- booking / order intent -> 对应写工具

它还会根据路由决策和风险判断，决定这一步是直接执行还是先走审批。

### 2. ToolExecutor

执行器真正去调用后端能力，优先级大致是：

- JavaBusinessClient
- 交易存储 / 事务存储
- catalog fallback

这样即使上游某个依赖不可用，系统也能尽量降级返回。

### 3. ToolResultNormalizer

归一化器把不同 API 的返回结果整理成统一的用户输出格式，比如：

- 推荐列表
- 商家详情卡片
- 优惠券摘要
- 订单状态
- 距离 / ETA
- 营业状态

这样对话层不需要关心底层工具返回结构有多杂。

## 五、什么时候应该走 toolcall

适合 toolcall 的请求通常满足下面至少一种：

- 需要最新业务状态
- 需要真实的订单 / 预约结果
- 需要查询一个明确对象的详情
- 需要执行有副作用的业务动作
- 需要算距离、ETA、营业状态这种即时信息

## 六、什么时候不应该硬走 toolcall

- 只是泛泛问推荐思路
- 明显可以靠知识库回答
- 用户还没把关键参数说清楚
- 需要先确认城市、商家、时间、人数等 slot

## 七、写工具为什么要审批

`create_booking`、`create_order`、`cancel_order`、`refund_order` 都属于有副作用的操作，所以默认需要更严格的控制：

- 先确认参数
- 再确认用户意图
- 再进入审批或执行

这避免了“模型理解错一句话就真的下单了”的风险。

## 八、toolcall 和 RAG 的关系

两者不是冲突关系，而是互补关系：

- RAG 负责回答“知识是什么”
- toolcall 负责回答“当前状态是什么”或“帮我执行动作”

如果是“这家店怎么样，顺便帮我看有没有券”，通常会先走 RAG 拿知识，再走 toolcall 拿实时信息。

