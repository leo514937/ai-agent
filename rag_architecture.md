# RAG 的实现架构

这份文档总结 Python 服务里当前的 RAG 实现。它不是单纯的“向量检索 + 生成”，而是把 `query 重写`、`chunk 切分`、`Qdrant 入库`、`混合检索`、`rerank`、`RRF 融合` 和 `引用构建` 串成了一条完整链路。

## 一、RAG 在哪里接入

在工作流里，RAG 不是每次都跑，而是先经过路由判断：

`load_context -> understand_turn -> rag_subgraph -> compose_answer`

只有当当前请求属于“需要检索知识”的路径时，才会进入 RAG 子图。典型场景包括：

- 商家详情
- 商家推荐
- 套餐 / 优惠券查询
- 探店笔记 / 评价摘要
- 本地攻略 / 避坑提示
- 平台规则 / 业务规则问答

如果用户只是寒暄、确认上下文、直接回答就够了，RAG 不会被强行触发。

## 二、RAG 的整体流程

```text
用户问题
  |
  v
[Understand Turn]
  |
  +--> 直接回答 / 澄清 / 拒答
  |
  +--> 进入 RAG
            |
            v
      [Query Rewrite]
            |
            +--> semantic_query
            +--> keyword_query
            +--> step_back_query
            +--> rewritten_queries
            +--> supplemental_queries
            +--> HyDE passage
            |
            v
      [Hybrid Retrieve]
        /      |       \
       /       |        \
      v        v         v
 [Dense]   [Sparse]   [Metadata]
      \       |        /
       \      |       /
        v     v      v
            [RRF]
              |
              v
            [Rerank]
              |
              v
        [Evidence / Citation]
              |
              v
         [Compose Answer]
```

## 三、Query 重写是怎么做的

`QueryRewriteService` 会先根据当前问题和上下文生成检索计划，再决定是否做更激进的重写。

它通常会产出这些字段：

- `semantic_query`：偏语义的检索表达
- `keyword_query`：偏关键词的检索表达
- `step_back_query`：向上抽象一层的查询
- `rewritten_queries`：改写后的多个查询版本
- `supplemental_queries`：补充检索问题
- `hyde_passage`：HyDE 生成的假设答案片段

它的意义是把“用户原话”变成更适合召回的检索表达。比如：

- 用户问法很口语，但知识库内容更偏正式
- 用户问题信息太少，需要补一个上位表达
- 用户问题里同时包含场景、约束、偏好，需要拆成多个检索角度

## 四、切 chunk 的方式

RAG 的知识不是直接把整段文本塞进库里，而是分成 parent / child 两级。

### 1. 长文本切分

对长文本会先做语义化切分：

- 先归一化文本
- 如果长度还不够长，直接保留整段
- 如果超过阈值，就按语义单元拆分
- 单段过长时再继续拆
- 拼接时保留一定 overlap，避免语义断层

代码里可以看到：

- `split_long_text_by_semantic_units`
- `max_chars = 760`
- `overlap_chars = 72`
- `min_split_chars = 850`

### 2. parent / child 结构

每个实体通常都会有：

- `parent chunk`：整体摘要
- `child chunk`：细粒度证据

比如商家维度会拆出：

- 商家介绍
- 评价摘要
- 适合场景
- 避坑提示
- 套餐说明
- 探店笔记

平台规则则会拆成多条 child，再聚合成一个 parent 摘要。

```text
一个商家
  |
  +--> parent summary
  |
  +--> child: 商家介绍
  +--> child: 评价摘要
  +--> child: 套餐说明
  +--> child: 探店笔记
```

## 五、怎么入 Qdrant

当前 RAG 主要使用两个集合：

- `local_life_hybrid_chunks`
- `local_life_parent_child_chunks`

关键参数：

- 向量名：`embedding`
- 向量维度：`4096`

入库时不是只写文本，还会一起写 payload 和索引字段，例如：

- `chunk_level`
- `parent_id`
- `parent_chunk_id`
- `child_chunk_ids`
- `child_roles`
- `entity_id`
- `chunk_role`
- `shop_id`
- `shop_type_id`
- `voucher_id`
- `blog_id`
- `rule_id`
- `city`
- `area`

这意味着它既能做向量召回，也能做元数据过滤和实体级定位。

### 入库流程

```text
业务数据
  |
  v
[构造 KnowledgeChunk]
  |
  v
[生成 embedding]
  |
  v
[封装 PointStruct / payload]
  |
  v
[Upsert 到 Qdrant]
  |
  v
[建立 payload index]
```

## 六、混合检索怎么做

检索阶段不是单一路径，而是并行做三类召回：

- Dense 检索：更偏语义
- Sparse 检索：更偏关键词 / 词面命中
- Metadata 检索：更偏结构字段和过滤条件

然后用 `Reciprocal Rank Fusion` 做融合，再把融合后的候选交给 rerank。

### 1. Dense

通常使用 `semantic_query`，有时也会叠加：

- `step_back_query`
- `rewritten_queries`
- `supplemental_queries`

### 2. Sparse

通常使用 `keyword_query`，并允许把 `HyDE passage`、改写查询一起纳入。

### 3. Metadata

会结合一些结构化条件，比如：

- 类目
- 子类目
- source_type
- chunk_type
- 标签
- entity_id
- city / area

### 4. RRF

RRF 不是简单加分，而是把多个检索路由的排序结果做稳健融合。这样可以避免：

- 语义检索命中但关键词缺失
- 关键词命中但语义相关性不足
- 元数据召回过窄导致漏召回

## 七、rerank 做什么

RRF 之后还会 rerank，重新排序最值得看的候选。

它的作用是：

- 压掉噪声候选
- 把更贴近问题意图的证据排到前面
- 让最终引用更集中

典型做法是只对 top `rerank_top_k` 做 rerank，再输出更少但质量更高的 evidence。

## 八、什么时候特别有用

RAG 最适合这些场景：

- 用户问的是平台已有知识，不需要实时工具调用
- 用户要比较多个商家、套餐、攻略
- 用户想看“为什么推荐 / 为什么不推荐”
- 用户问题里带有场景约束，比如“适合家庭”“适合停车”“适合约会”
- 用户问的是规则类问题，需要有依据地回答

## 九、什么时候不该强行用

- 纯寒暄
- 明显要调用工具才能得到最新状态的内容
- 信息太少，需要先澄清
- 风险很高、必须走审批或业务工具链

## 十、当前实现的一个特点

如果 Qdrant 里没有足够内容，系统会退回到 bundled 的默认 chunks，保证链路不会直接断掉。也就是说，RAG 不是“有库才工作”，而是“有库更准，没库也能降级运行”。

