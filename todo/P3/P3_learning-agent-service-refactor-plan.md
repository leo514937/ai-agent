# learning-agent-service 深度重构与代码拆分方案 (V4)

> 更新日期：2026-06-05 下午
> 分析基准：237 个 Python 文件 / 2.65 MB 源码
> 前期重构回顾：V3 阶段的 P0 目标大获全胜！原先最大的 `seed_parent_child.py` 被成功拆分为 `rag/seed` 包，且 `retrieval_components.py` 按照 Dense/Sparse/Metadata 策略模式进行了教科书级别的解耦拆分。**项目最大文件的上限已被彻底压低至 68.8 KB。**

---

## 一、现状：后重构时代的系统瓶颈

随着业务主流程（Stream）、RAG 检索分发模块等历史遗留的"大泥球"被相继打碎，我们现在的痛点转移到了**特化业务逻辑**和**基础设施模板代码**上。目前的 Top 5 臃肿文件如下：

1. **`rag/local_life_retrieval.py` (68.8 KB)**：新晋全项目第一大文件。包含了过于特化的本地生活查询、召回合并逻辑。
2. **`config/settings_impl.py` (63.1 KB)**：高达 1400 行，大量使用 `data.pop("key", _env(...))` 的手写解析模式。
3. **`application/dependencies_impl.py` (57.5 KB)**：50+ 个 `_build_xxx()` 手写装配工厂，缺乏自动化。
4. **`rag/seed/context_builder.py` (56.1 KB)**：刚刚被拆出来，依然承载了较重的上下文拼接逻辑。
5. **`application/routing_signals.py` (56.1 KB)**：路由信号的定义与解析集中在单一文件。

---

## 二、进一步改进规划（按优先级排序）

### 阶段一：P0 基础设施现代化（消除配置与注入的纯模板代码）

**目标**：消除纯手写的配置加载和依赖注入工厂，这部分虽然不涉及深层业务逻辑，但极大地增加了代码量和接入门槛，收益比极高。

**1. 现代化配置加载 `settings_impl.py` (63.1 KB)**
- **行动**：删除长达 800 行手写的 `__init__` 解析逻辑。
- **重构方式**：利用 `pydantic-settings` 的 `BaseSettings` 特性（`env_prefix` 等）自动从环境变量加载并校验，按功能域定义 `OpenAISettings`, `QdrantSettings`, `ObservabilitySettings` 等子模型进行组合。

**2. 引入轻量级 DI 容器 `dependencies_impl.py` (57.5 KB)**
- **行动**：消灭大量重复的 `_build_xxx()` 工厂函数模式。
- **重构方式**：引入基于类的声明式 DI（如 `lagom`、`dependency-injector` 或简单的 Registry 模式），自动管理对象的依赖树、单例生命周期和回退（Fallback）逻辑。

---

### 阶段二：P1 拆解最后的业务巨石 (`local_life_retrieval.py`)

**目标**：解决新晋第一大文件 `rag/local_life_retrieval.py` 的过度臃肿问题。

**重构方向**：
将 `local_life_retrieval.py` (68.8 KB) 转换为包：
```text
rag/local_life/
├── __init__.py
├── orchestrator.py      # 本地生活检索的主调度流程
├── strategies/          # 具体的领域检索策略
│   ├── hybrid.py        # 图文混合检索
│   ├── location.py      # LBS 基于位置检索
│   └── intent.py        # 强意图精准检索
└── post_processing/     # 召回结果合并与打分逻辑
```

---

### 阶段三：P2 路由规则库解耦 (`routing_signals.py`)

**目标**：分散 56.1 KB 的集中式路由信号管理，防止它继续膨胀。

**重构方向**：
提取出具体意图的识别与打分策略：
```text
application/routing_signals/
├── __init__.py
├── base.py              # 信号接口与基类
├── intent_signals.py    # 意图相关的启发式规则
├── geo_signals.py       # 空间位置相关的验证
└── quality_signals.py   # 输入质量相关的信号
```

---

### 阶段四：P3 扫尾与去噪（Stub 全面大扫除）

**目标**：消除经过多次平滑过渡而产生的代码库重导出（Stub）噪音。

**行动列表**：
1. 全局搜索并替换旧的 Import 路径：
   - 将 `from tools.service import` 替换为正确的内部路径。
   - 将 `from config.settings import` 和 `settings_parts` 替换为 `settings_impl`（或最终名）。
   - 将 `dependencies` 和 `dependencies_core` 替换。
2. **安全删除**以下只包含 1-3 行 `from .xxx import *` 的残留存根文件：
   - `local_life/subgraph/stream.py`
   - `local_life/subgraph/stream_stages.py` (已缩至1KB)
   - `rag/retrieval.py` 
   - `config/settings.py` / `settings_core.py`
   - `application/dependencies.py` / `dependencies_core.py` / `dependency_runtime.py`
3. 重新运行测试，确保没有丢失的依赖关系。

---

## 三、实施规范与验证兜底

1. **先基建，后业务**：强烈建议先实施 P0（Settings/DI 重构）。因为配置和依赖是全局的，先稳定它们的装配方式，再动业务逻辑会安全得多。
2. **测试优先**：
   - 配置改动必须补充配置初始化的单元测试。
   - 业务逻辑拆分（P1/P2）必须在 `pytest --record-mode=none` 模式下跑通全部黄金链路用例。
