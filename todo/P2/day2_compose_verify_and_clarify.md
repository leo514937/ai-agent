# P2-Day2：收敛 compose_answer 与澄清回路

源文档： [../P2_graph_topology_refactor_plan.md](../P2_graph_topology_refactor_plan.md)

## 本日目标

- 把校验从 `compose_answer` 拆出来
- 显式化澄清回路与记忆更新层

## 必须避免的架构冗余

- 不要把生成、验证、兜底、修正继续堆在同一个节点
- 不要把澄清逻辑隐藏在若干 helper 里

## 完成标准

- `compose_answer` 更薄
- 有清晰的澄清回路
- 记忆更新与会话保存边界更清楚
