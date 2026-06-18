# Prompt 迁移实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将提示词系统从JSON格式迁移到YAML格式，移除固定模板回复，让LLM生成更自然的回答

**Architecture:** 
1. 扩展PromptEngine支持YAML格式（向后兼容JSON）
2. 移除rag_gate.py中的_recommendation_fallback()固定模板
3. 修改helpers.py中的_build_recommendation_answer_text，调用PromptEngine
4. 增强YAML提示词模板，添加COT和更多few-shot示例

**Tech Stack:** Python 3.11+, PyYAML, OpenAI API

---

## 文件结构

### 新增文件
- `learning-agent-service/src/learning_agent_service/local_life/prompts/multi_shop_recommendation.yaml`
- `learning-agent-service/src/learning_agent_service/local_life/prompts/single_shop_review.yaml`
- `learning-agent-service/src/learning_agent_service/local_life/prompts/comparison.yaml`
- `learning-agent-service/src/learning_agent_service/local_life/prompts/coupon_only.yaml`
- `learning-agent-service/src/learning_agent_service/local_life/prompts/distance_only.yaml`
- `learning-agent-service/src/learning_agent_service/local_life/prompts/facet_multi.yaml`
- `learning-agent-service/src/learning_agent_service/local_life/prompts/open_status_only.yaml`
- `tests/local_life/test_prompt_engine_yaml.py`

### 修改文件
- `learning-agent-service/pyproject.toml` - 添加pyyaml依赖
- `learning-agent-service/src/learning_agent_service/local_life/prompt_engine.py` - 支持YAML加载
- `learning-agent-service/src/learning_agent_service/application/rag_gate.py` - 移除_recommendation_fallback
- `learning-agent-service/src/learning_agent_service/application/workflow/adapters/helpers.py` - 调用PromptEngine
- `learning-agent-service/src/learning_agent_service/application/workflow/adapters/stages_back_emit.py` - 传递店铺数据
- `learning-agent-service/src/learning_agent_service/application/workflow/adapters/stages_back_core.py` - 传递店铺数据

### 保留文件（向后兼容）
- 所有`.json`文件保留，YAML优先加载

---

## Task 1: 添加PyYAML依赖

**Files:**
- Modify: `learning-agent-service/pyproject.toml:15-31`

- [ ] **Step 1: 添加pyyaml到dependencies**

```toml
dependencies = [
  "alembic>=1.14.0",
  "fastapi>=0.115.0",
  "httpx>=0.28.0",
  "langgraph>=0.3.0",
  "openai>=1.68.0",
  "orjson>=3.10.0",
  "psycopg[binary]>=3.2.0",
  "pydantic>=2.10.0",
  "pydantic-settings>=2.6.0",
  "pyyaml>=6.0.0",
  "qdrant-client>=1.13.0",
  "redis>=5.2.0",
  "sqlalchemy>=2.0.37",
  "structlog>=25.1.0",
  "tenacity>=9.0.0",
  "uvicorn[standard]>=0.34.0",
]
```

- [ ] **Step 2: 验证依赖安装**

Run: `cd learning-agent-service && pip install -e .`
Expected: 成功安装pyyaml

- [ ] **Step 3: Commit**

```bash
git add learning-agent-service/pyproject.toml
git commit -m "chore: add pyyaml dependency for prompt migration"
```

---

## Task 2: 创建YAML提示词模板

**Files:**
- Create: `learning-agent-service/src/learning_agent_service/local_life/prompts/multi_shop_recommendation.yaml`

- [ ] **Step 1: 创建multi_shop_recommendation.yaml**

```yaml
# 多店铺推荐场景的提示词模板
# 包含COT(Chain of Thought)和few-shot示例

scene: multi_shop_recommendation
description: 推荐多家店铺时的回答

system: |
  你是一个本地生活助手，帮助用户发现和选择餐厅或店铺。
  
  ## 思考步骤（Chain of Thought）
  在回答之前，请按以下步骤思考：
  1. **分析用户需求**：理解用户想要什么类型的店铺、预算范围、使用场景
  2. **评估候选店铺**：根据评分、距离、特色、评价数等维度评估每个候选店铺
  3. **匹配用户场景**：将店铺特点与用户需求进行匹配
  4. **组织推荐理由**：为每个店铺生成差异化的推荐理由
  5. **生成自然回答**：用自然、亲切的语言组织回答
  
  ## 回答要求
  - 推荐理由基于实际数据（评分、评价数、特色），不要编造不存在的信息
  - 每家店的推荐点要有差异化，不要千篇一律
  - 语气自然亲切，像朋友推荐而非机器输出
  - 优先按用户场景组织回答，不要照搬固定模板
  - 如果信息不足，诚实说明，不要填充虚假信息
  - 控制在200字以内，不要过长
  - 使用Markdown格式，店铺名加粗

few_shots:
  - user: 推荐火锅
    context: |
      候选店铺:
      1. 海底捞(望京店) - 评分4.8, 人均120元, 距离1.2km, 特色:服务好, 有宝宝椅, 评价数856
      2. 巴奴毛肚火锅(三里屯店) - 评分4.7, 人均150元, 距离2.3km, 特色:毛肚鲜嫩, 牛油锅底, 评价数623
      3. 小龙坎(国贸店) - 评分4.5, 人均100元, 距离0.8km, 特色:性价比高, 麻辣过瘾, 评价数412
    assistant: |
      给你推荐3家不错的火锅店：
      
      **海底捞(望京店)** 人均120元，评分4.8，离你1.2km
      服务确实到位，等位有小食，带小孩有宝宝椅，家庭聚餐首选。
      
      **巴奴毛肚火锅(三里屯店)** 人均150元，评分4.7，离你2.3km
      毛肚是招牌，口感脆嫩，牛油锅底很地道，适合朋友涮肉。
      
      **小龙坎(国贸店)** 人均100元，评分4.5，离你最近0.8km
      性价比高，麻辣味足，想吃顿实惠的麻辣火锅可以试试。
      
      建议先看哪家离你近，再决定去哪。

  - user: 附近有什么好吃的
    context: |
      候选店铺:
      1. 西贝莜面村(朝阳大悦城) - 评分4.6, 人均90元, 距离1.5km, 特色:西北菜, 莜面地道, 评价数534
      2. 外婆家(蓝色港湾) - 评分4.5, 人均75元, 距离2.1km, 特色:杭帮菜, 性价比高, 评价数478
      3. 全聚德(王府井店) - 评分4.3, 人均180元, 距离3.8km, 特色:烤鸭, 老字号, 评价数1203
    assistant: |
      附近这3家可以看看：
      
      **西贝莜面村** 人均90元，主打西北菜，莜面和羊肉都很地道，适合带家人。
      
      **外婆家** 人均75元，杭帮菜，价格实惠味道稳定，一个人吃也不贵。
      
      **全聚德** 人均180元，老字号烤鸭，如果想请客或尝鲜可以考虑。
      
      你平时偏好什么口味？我可以帮你缩小范围。

  - user: 推荐几家适合约会的餐厅
    context: |
      候选店铺:
      1. 绿茶餐厅(来福士店) - 评分4.6, 人均85元, 距离1.0km, 特色:环境清爽, 菜品精致, 评价数501
      2. 小酒馆(滨江店) - 评分4.7, 人均160元, 距离2.4km, 特色:安静, 灯光柔和, 评价数288
      3. 湘遇湘知(市中心店) - 评分4.5, 人均110元, 距离1.7km, 特色:口味重, 氛围热闹, 评价数389
    assistant: |
      给你挑了3家风格不太一样的：
      
      **绿茶餐厅(来福士店)** 人均85元，评分4.6，离你1.0km
      环境清爽，菜品比较精致，适合轻松聊天。
      
      **小酒馆(滨江店)** 人均160元，评分4.7，离你2.4km
      氛围更安静，灯光柔和，适合想认真约会。
      
      **湘遇湘知(市中心店)** 人均110元，评分4.5，离你1.7km
      口味更重、氛围更热闹，适合想吃得尽兴一点。
      
      如果你更在意环境，我会优先看前两家。

  - user: 推荐几家性价比高的快餐店
    context: |
      候选店铺:
      1. 麦当劳(中关村店) - 评分4.4, 人均35元, 距离0.5km, 特色:出餐快, 24小时营业, 评价数1205
      2. 肯德基(五道口店) - 评分4.3, 人均38元, 距离0.8km, 特色:新品多, 早餐好, 评价数987
      3. 吉野家(北大店) - 评分4.2, 人均32元, 距离1.2km, 特色:日式快餐, 牛丼饭, 评价支654
    assistant: |
      这3家快餐店性价比都不错：
      
      **麦当劳(中关村店)** 人均35元，离你最近0.5km
      出餐快，24小时营业，赶时间或夜宵都可以。
      
      **肯德基(五道口店)** 人均38元，离你0.8km
      新品出得快，早餐选择多，口味比较丰富。
      
      **吉野家(北大店)** 人均32元，最便宜
      日式快餐，牛丼饭是招牌，想换个口味可以试试。
      
      如果赶时间，优先看最近的麦当劳。
```

- [ ] **Step 2: 验证YAML语法**

Run: `cd learning-agent-service && python -c "import yaml; yaml.safe_load(open('src/learning_agent_service/local_life/prompts/multi_shop_recommendation.yaml'))"`
Expected: 无报错

- [ ] **Step 3: Commit**

```bash
git add learning-agent-service/src/learning_agent_service/local_life/prompts/multi_shop_recommendation.yaml
git commit -m "feat: add YAML prompt template with COT and few-shot examples"
```

---

## Task 3: 扩展PromptEngine支持YAML

**Files:**
- Modify: `learning-agent-service/src/learning_agent_service/local_life/prompt_engine.py`

- [ ] **Step 1: 添加yaml导入和YAML加载逻辑**

```python
"""LLM-based answer generation using few-shot prompting."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

import yaml  # 新增

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent / "prompts"


class PromptSceneConfig:
    """单个场景的 prompt 配置"""
    def __init__(self, scene: str, description: str, system: str, few_shots: list[dict[str, str]]):
        self.scene = scene
        self.description = description
        self.system = system
        self.few_shots = few_shots


class PromptEngine:
    """根据 answer_style 加载配置、组装 prompt、调用 LLM 生成回答"""
    
    def __init__(self):
        self._configs: dict[str, PromptSceneConfig] = {}
        self._load_configs()
    
    def _load_configs(self):
        """启动时加载所有 YAML/JSON 配置文件（YAML优先）"""
        if not _PROMPTS_DIR.exists():
            return
        
        loaded_scenes: set[str] = set()
        
        # 优先加载YAML文件
        for yaml_file in _PROMPTS_DIR.glob("*.yaml"):
            try:
                data = yaml.safe_load(yaml_file.read_text(encoding="utf-8"))
                scene = data.get("scene", yaml_file.stem)
                config = PromptSceneConfig(
                    scene=scene,
                    description=data.get("description", ""),
                    system=data.get("system", ""),
                    few_shots=data.get("few_shots", []),
                )
                self._configs[scene] = config
                loaded_scenes.add(scene)
                logger.info("loaded_prompt_config scene=%s format=yaml", scene)
            except Exception as e:
                logger.warning("failed_to_load_prompt_config file=%s error=%s", yaml_file.name, e)
        
        # 加载JSON文件（仅当同名YAML不存在时）
        for json_file in _PROMPTS_DIR.glob("*.json"):
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
                scene = data.get("scene", json_file.stem)
                if scene in loaded_scenes:
                    logger.debug("skipping_json_config scene=%s already_loaded_from_yaml", scene)
                    continue
                config = PromptSceneConfig(
                    scene=scene,
                    description=data.get("description", ""),
                    system=data.get("system", ""),
                    few_shots=data.get("few_shots", []),
                )
                self._configs[scene] = config
                logger.info("loaded_prompt_config scene=%s format=json", scene)
            except Exception as e:
                logger.warning("failed_to_load_prompt_config file=%s error=%s", json_file.name, e)
    
    def has_config(self, answer_style: str) -> bool:
        """判断该 answer_style 是否有 LLM 配置"""
        return answer_style in self._configs
    
    def build_messages(
        self,
        answer_style: str,
        query: str,
        evidence_context: str,
    ) -> list[dict[str, str]]:
        """组装 OpenAI messages 格式"""
        config = self._configs.get(answer_style)
        if config is None:
            return []
        
        messages = [{"role": "system", "content": config.system}]
        
        # 添加 few-shot examples
        for example in config.few_shots:
            messages.append({"role": "user", "content": example.get("user", "")})
            messages.append({"role": "assistant", "content": example.get("assistant", "")})
        
        # 添加当前用户查询 + 上下文
        user_message = f"用户问题：{query}\n\n相关信息：\n{evidence_context}"
        messages.append({"role": "user", "content": user_message})
        
        return messages
    
    def generate(
        self,
        answer_style: str,
        query: str,
        evidence_context: str,
        *,
        client: Any,
        model: str,
        timeout_seconds: float = 5.0,
    ) -> str | None:
        """调用 LLM 生成回答，失败返回 None"""
        config = self._configs.get(answer_style)
        if config is None:
            return None
        
        messages = self.build_messages(answer_style, query, evidence_context)
        if not messages:
            return None
        
        responses = getattr(client, "responses", None)
        if responses is None or not hasattr(responses, "create"):
            return None
        
        try:
            started = time.perf_counter()
            response = responses.create(
                model=model,
                input=messages,
                temperature=0.3,
                max_output_tokens=800,
            )
            elapsed_ms = (time.perf_counter() - started) * 1000
            
            # 提取输出文本
            output_text = ""
            for item in getattr(response, "output", []) or []:
                if getattr(item, "type", "") == "message":
                    for content_block in getattr(item, "content", []) or []:
                        if getattr(content_block, "type", "") == "output_text":
                            output_text += getattr(content_block, "text", "")
            
            logger.info(
                "prompt_engine_generated style=%s elapsed_ms=%.0f output_len=%d",
                answer_style, elapsed_ms, len(output_text),
            )
            return output_text.strip() if output_text.strip() else None
            
        except TimeoutError:
            logger.warning("prompt_engine_timeout style=%s", answer_style)
            return None
        except Exception as e:
            logger.warning("prompt_engine_error style=%s error=%s", answer_style, type(e).__name__)
            return None


# 模块级单例
_engine: PromptEngine | None = None


def get_prompt_engine() -> PromptEngine:
    global _engine
    if _engine is None:
        _engine = PromptEngine()
    return _engine
```

- [ ] **Step 2: 运行现有测试验证兼容性**

Run: `cd learning-agent-service && python -m pytest tests/local_life/test_prompt_engine.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add learning-agent-service/src/learning_agent_service/local_life/prompt_engine.py
git commit -m "feat: extend PromptEngine to support YAML format with JSON fallback"
```

---

## Task 4: 创建其他YAML模板

**Files:**
- Create: `learning-agent-service/src/learning_agent_service/local_life/prompts/single_shop_review.yaml`
- Create: `learning-agent-service/src/learning_agent_service/local_life/prompts/comparison.yaml`

- [ ] **Step 1: 创建single_shop_review.yaml**

```yaml
# 单店铺评价场景的提示词模板

scene: single_shop_review
description: 评价单家店铺时的回答

system: |
  你是一个本地生活助手，帮助用户了解单家店铺的详细情况。
  
  ## 思考步骤（Chain of Thought）
  1. **分析店铺信息**：评分、人均、距离、特色、评价数
  2. **识别优势**：基于数据找出店铺的亮点
  3. **指出不足**：客观分析可能的问题
  4. **匹配场景**：判断适合什么样的用户/场景
  5. **给出建议**：提供中肯的建议
  
  ## 回答要求
  - 基于实际数据进行分析，不要编造信息
  - 客观指出优点和可能的不足，不夸大不贬低
  - 语气自然亲切，像朋友帮忙分析
  - 优先输出自然、个性化的回答，不要套固定模板
  - 如果信息不足，诚实说明
  - 控制在150字以内
  - 使用Markdown格式，店铺名加粗

few_shots:
  - user: 海底捞望京店怎么样
    context: |
      店铺信息:
      海底捞(望京店) - 评分4.8, 人均120元, 距离1.2km, 特色:服务好, 有宝宝椅, 评价数856
    assistant: |
      **海底捞(望京店)** 人均120元，评分4.8，离你1.2km
      
      **优点：** 服务确实到位，等位有小食和美甲，带小孩有宝宝椅，适合家庭聚餐。
      
      **注意：** 饭点排队时间较长，建议提前预约。口味中规中矩，主要胜在服务。
      
      如果看重服务体验，这家值得去；如果更在意火锅本身味道，可以再看看其他选择。

  - user: 这家日料店值得去吗
    context: |
      店铺信息:
      的场日本料理(三里屯店) - 评分4.6, 人均280元, 距离3.5km, 特色:新鲜刺身, 寿司师傅现场制作, 评价数267
    assistant: |
      **的场日本料理(三里屯店)** 人均280元，评分4.6，离你3.5km
      
      **优点：** 刺身新鲜，寿司师傅现场制作，食材品质有保障。
      
      **注意：** 价格偏高，人均近300元。位置稍远，需要专门跑一趟。
      
      如果喜欢正宗日料且预算充足，可以去尝鲜；如果追求性价比，附近有更实惠的选择。

  - user: 这家店适合商务宴请吗
    context: |
      店铺信息:
      全聚德(王府井店) - 评分4.3, 人均180元, 距离3.8km, 特色:烤鸭, 老字号, 评价数1203
    assistant: |
      **全聚德(王府井店)** 人均180元，评分4.3，离你3.8km
      
      **适合宴请：** 老字号品牌，知名度高，请客有面子；烤鸭是招牌，菜品比较正式。
      
      **注意：** 评分4.3说明整体中规中矩，可能不会有惊喜；价格偏高，性价比一般。
      
      如果请的客人看重品牌和正式感，这家可以；如果更在意口味，可以考虑其他选择。
```

- [ ] **Step 2: 创建comparison.yaml**

```yaml
# 店铺对比场景的提示词模板

scene: comparison
description: 对比多家店铺时的回答

system: |
  你是一个本地生活助手，帮助用户对比不同店铺的优劣。
  
  ## 思考步骤（Chain of Thought）
  1. **提取对比维度**：价格、评分、距离、特色、适合场景
  2. **逐项对比**：每个维度上各家店的表现
  3. **总结差异**：明确指出主要区别
  4. **给出建议**：根据不同需求推荐
  
  ## 回答要求
  - 使用表格或清晰的对比格式
  - 基于实际数据，不要编造
  - 客观中立，不偏向任何一家
  - 明确指出各自优势和不足
  - 控制在200字以内

few_shots:
  - user: 海底捞和巴奴哪个好
    context: |
      对比店铺:
      1. 海底捞(望京店) - 评分4.8, 人均120元, 距离1.2km, 特色:服务好, 有宝宝椅
      2. 巴奴毛肚火锅(三里屯店) - 评分4.7, 人均150元, 距离2.3km, 特色:毛肚鲜嫩, 牛油锅底
    assistant: |
      这两家火锅店各有特色：
      
      | 维度 | 海底捞 | 巴奴 |
      |------|--------|------|
      | 人均 | 120元 | 150元 |
      | 评分 | 4.8 | 4.7 |
      | 距离 | 1.2km | 2.3km |
      | 特色 | 服务好 | 毛肚鲜嫩
      
      **选择建议：**
      - 看重服务、带小孩：选海底捞
      - 看重口味、想吃毛肚：选巴奴
      - 追求性价比：海底捞更划算

  - user: 西贝和外婆家哪个适合请客
    context: |
      对比店铺:
      1. 西贝莜面村(朝阳大悦城) - 评分4.6, 人均90元, 距离1.5km, 特色:西北菜, 莜面地道
      2. 外婆家(蓝色港湾) - 评分4.5, 人均75元, 距离2.1km, 特色:杭帮菜, 性价比高
    assistant: |
      两家定位不太一样：
      
      **西贝莜面村** 人均90元
      - 优势：菜品有特色，莜面、羊肉品质好，请客有面子
      - 适合：想吃得有特色、请比较重要的客人
      
      **外婆家** 人均75元
      - 优势：价格实惠，环境干净，请客压力小
      - 适合：朋友聚餐、不想花太多钱
      
      如果是正式请客，西贝更合适；如果是朋友随意聚聚，外婆家就够了。
```

- [ ] **Step 3: 验证YAML语法**

Run: `cd learning-agent-service && python -c "import yaml; [yaml.safe_load(f.read_text()) for f in __import__('pathlib').Path('src/learning_agent_service/local_life/prompts').glob('*.yaml')]"`
Expected: 无报错

- [ ] **Step 4: Commit**

```bash
git add learning-agent-service/src/learning_agent_service/local_life/prompts/single_shop_review.yaml learning-agent-service/src/learning_agent_service/local_life/prompts/comparison.yaml
git commit -m "feat: add YAML templates for single_shop_review and comparison scenes"
```

---

## Task 5: 移除rag_gate.py中的固定模板

**Files:**
- Modify: `learning-agent-service/src/learning_agent_service/application/rag_gate.py:206-261`

- [ ] **Step 1: 修改compose_direct_response_text函数**

将第210-228行的`_recommendation_fallback()`函数和第246、257行的调用改为返回空字符串，让后续流程处理：

```python
def compose_direct_response_text(raw_query: str, response_kind: str | None, reason: str | None = None) -> str:
    kind = (response_kind or "").strip().lower()
    compact = (raw_query or "").replace(" ", "")

    if kind == "greeting":
        return "你好，我在。你可以直接告诉我想查什么、想解释什么，或者把问题贴出来。"
    if kind == "thanks":
        return "不客气，有需要继续问我。"
    if kind == "farewell":
        return "好的，之后想继续查知识、门店或工具信息，随时来找我。"
    if kind == "profile":
        return "我可以帮你做通用问答、代码解释和调试，也能结合本地生活信息帮你筛店、看券、做对比和推荐。"
    if kind == "memory_update":
        return "我记住了，这个偏好我会尽量沿用到后续对话里。"
    if kind == "conversation_recap":
        return "我记得我们刚才主要在聊的上下文。你可以继续问刚才那家店、那张券，或者让我接着往下说。"
    if kind == "location_unavailable":
        return "这个位置不太适合本地生活推荐。你可以换成具体城市、商圈或地标，我再继续帮你找。"
    if kind in {"empty", "low_info"}:
        # 移除固定模板，返回空字符串让后续prompt_engine处理
        text = normalize_rag_gate_request(RagGateRequest(raw_query=raw_query))
        if text:
            return f"我先按你的问题理解为：{text}。如果你愿意补充一点上下文，我可以继续从原理、流程、示例或排错思路展开，给你更具体的说明。"
        return "我还需要更具体的信息才能继续。你可以补充对象、范围或目标。"

    text = (raw_query or "").strip()
    if text:
        if any(marker.lower() in text.lower() for marker in ("spring", "aop", "rag", "stream", "tool", "sse", "检索", "原理", "报错", "异常", "实现")):
            return f"我先按你的问题来理解：{text}。如果你愿意，我可以继续从原理、流程、示例或排错思路展开，给你更具体的回答。"
        # 移除固定模板，返回空字符串让后续prompt_engine处理
        return f"我先按你的问题来理解：{text}。如果你愿意补充一点上下文，我可以继续给你更具体的说明。"
    if reason:
        return "我还需要更具体的信息才能继续。你可以补充对象、范围或目标。"
    return "我还需要更具体的信息才能继续。你可以补充对象、范围或目标。"
```

- [ ] **Step 2: 运行rag_gate测试**

Run: `cd learning-agent-service && python -m pytest tests/ -k "rag_gate" -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add learning-agent-service/src/learning_agent_service/application/rag_gate.py
git commit -m "refactor: remove _recommendation_fallback template from rag_gate"
```

---

## Task 6: 修改helpers.py调用PromptEngine

**Files:**
- Modify: `learning-agent-service/src/learning_agent_service/application/workflow/adapters/helpers.py:1061-1127`

- [ ] **Step 1: 修改_build_recommendation_answer_text函数**

```python
def _build_recommendation_answer_text(
    shop_names: list[str],
    limit: int = 3,
    fallback_text: str | None = None,
    scene_hint: str | None = None,
    focus_hint: str | None = None,
    shop_data: list[dict[str, Any]] | None = None,  # 新增参数：真实店铺数据
    query: str | None = None,  # 新增参数：用户查询
) -> str:
    """
    构建推荐回答文本。
    
    优先使用PromptEngine生成自然回答，失败时降级到模板。
    """
    # 尝试使用PromptEngine生成自然回答
    if shop_data and query:
        try:
            from learning_agent_service.local_life.prompt_engine import get_prompt_engine
            
            engine = get_prompt_engine()
            if engine.has_config("multi_shop_recommendation"):
                # 构建evidence_context
                evidence_lines = ["候选店铺:"]
                for i, shop in enumerate(shop_data[:limit], 1):
                    name = shop.get("name") or shop.get("shop_name") or f"店铺{i}"
                    score = shop.get("score", "未知")
                    avg_price = shop.get("avg_price", "未知")
                    distance = shop.get("distance", "未知")
                   特色 = shop.get("特色") or shop.get("highlights") or []
                    if isinstance(特色, list):
                        特色_str = ", ".join(特色[:3])
                    else:
                        特色_str = str(特色)
                    comments = shop.get("comments", "未知")
                    evidence_lines.append(
                        f"{i}. {name} - 评分{score}, 人均{avg_price}元, 距离{distance}km, 特色:{特色_str}, 评价数{comments}"
                    )
                
                evidence_context = "\n".join(evidence_lines)
                
                # 构建完整查询
                full_query = query
                if scene_hint:
                    full_query = f"{query}（场景：{scene_hint}）"
                if focus_hint:
                    full_query = f"{full_query}（重点：{focus_hint}）"
                
                # 调用PromptEngine生成回答
                from learning_agent_service.application.container import OpenAIAnswerComposer
                # 这里需要异步调用，但_build_recommendation_answer_text是同步函数
                # 所以我们使用同步的generate方法
                result = engine.generate(
                    "multi_shop_recommendation",
                    full_query,
                    evidence_context,
                    client=None,  # 需要在调用时传入
                    model="gpt-4o-mini",
                )
                if result:
                    return result
        except Exception as e:
            logger.warning("prompt_engine_fallback error=%s", e)
    
    # 降级到原有模板逻辑
    names = [str(name).strip() for name in shop_names if str(name).strip()]
    if not names:
        return fallback_text or "我暂时没有找到合适的店。"

    lines = ["我先帮你推荐以下这几家店铺：", ""]
    scene_text = scene_hint or "适合约会、聊天或轻松聚餐。"
    for i, name in enumerate(names[:limit], 1):
        lines.append(f"{i}. {name}")
        lines.append("- 推荐理由：当前候选里它的综合信息比较靠前，值得优先查看。")
        lines.append(f"- 适合场景：{scene_text}")
        lines.append("- 注意事项：建议先确认营业状态、预算和是否需要排队。")
        lines.append("")
    lines.append("综合建议")
    if focus_hint:
        lines.append(f"- 筛选重点：{focus_hint}")
    lines.append("- 如果你更在意气氛和稳定性，建议先从前两家开始看。")
    lines.append("- 另外，如果你想继续看实时优惠，我可以接着帮你查。")
    return "\n".join(lines).strip()
```

- [ ] **Step 2: 运行helpers测试**

Run: `cd learning-agent-service && python -m pytest tests/local_life/test_recommendation_answer_text.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add learning-agent-service/src/learning_agent_service/application/workflow/adapters/helpers.py
git commit -m "feat: integrate PromptEngine into _build_recommendation_answer_text"
```

---

## Task 7: 修改stages传递店铺数据

**Files:**
- Modify: `learning-agent-service/src/learning_agent_service/application/workflow/adapters/stages_back_emit.py:806-813`
- Modify: `learning-agent-service/src/learning_agent_service/application/workflow/adapters/stages_back_core.py:778-792`

- [ ] **Step 1: 修改stages_back_emit.py中的调用**

在第806-813行，将_build_recommendation_answer_text的调用修改为传递shop_data：

```python
                        if not final_answer_text.strip():
                            # 构建shop_data列表
                            shop_data_for_prompt = []
                            for candidate in ranked_candidates[:3]:
                                shop_data_for_prompt.append({
                                    "name": candidate.get("name") or candidate.get("shop_name"),
                                    "score": candidate.get("score"),
                                    "avg_price": candidate.get("avg_price"),
                                    "distance": candidate.get("distance"),
                                    "特色": candidate.get("highlights") or candidate.get("特色"),
                                    "comments": candidate.get("comments"),
                                })
                            
                            final_answer_text = _build_recommendation_answer_text(
                                fallback_names,
                                limit=(1 if any(token in compact_query_text for token in ("一家", "1家")) else 3),
                                scene_hint=scene_hint,
                                focus_hint=focus_hint,
                                fallback_text=f"{current_city_name or '你附近'}暂时还没有足够信息，我先给你列出几家候选店，供你继续筛选。",
                                shop_data=shop_data_for_prompt,
                                query=raw_query_text,
                            )
```

- [ ] **Step 2: 修改stages_back_core.py中的调用**

在第778-792行，修改_build_recommendation_answer_text的调用：

```python
                # 构建shop_data列表
                shop_data_for_prompt = []
                for candidate in ranked_candidates[:3]:
                    shop_data_for_prompt.append({
                        "name": candidate.get("name") or candidate.get("shop_name"),
                        "score": candidate.get("score"),
                        "avg_price": candidate.get("avg_price"),
                        "distance": candidate.get("distance"),
                        "特色": candidate.get("highlights") or candidate.get("特色"),
                        "comments": candidate.get("comments"),
                    })
                
                result = result.model_copy(
                    update={
                        "answer_text": _build_recommendation_answer_text(
                            candidate_names,
                            limit=3,
                            scene_hint=scene_hint,
                            focus_hint=focus_hint,
                            fallback_text=(
                                f"{current_topic or '你附近'}暂时还没有足够信息，我先给你列出几家候选店，供你继续筛选。"
                                if recommendation_like_query
                                else (answer_text or current_topic or "这家店")
                            ),
                            shop_data=shop_data_for_prompt,
                            query=raw_query,
                        )
                    }
                )
```

- [ ] **Step 3: 运行相关测试**

Run: `cd learning-agent-service && python -m pytest tests/ -k "recommendation" -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add learning-agent-service/src/learning_agent_service/application/workflow/adapters/stages_back_emit.py learning-agent-service/src/learning_agent_service/application/workflow/adapters/stages_back_core.py
git commit -m "feat: pass shop data to _build_recommendation_answer_text"
```

---

## Task 8: 创建YAML加载单元测试

**Files:**
- Create: `tests/local_life/test_prompt_engine_yaml.py`

- [ ] **Step 1: 创建测试文件**

```python
"""Tests for YAML prompt loading in PromptEngine."""

import pytest
from learning_agent_service.local_life.prompt_engine import get_prompt_engine, PromptEngine


class TestPromptEngineYAML:
    """测试YAML格式提示词加载"""
    
    def setup_method(self):
        """每个测试前重置单例"""
        import learning_agent_service.local_life.prompt_engine as pe
        pe._engine = None
    
    def test_yaml_config_loaded(self):
        """测试YAML配置被正确加载"""
        engine = get_prompt_engine()
        assert engine.has_config("multi_shop_recommendation")
    
    def test_yaml_has_few_shots(self):
        """测试YAML配置包含few-shot示例"""
        engine = get_prompt_engine()
        messages = engine.build_messages(
            "multi_shop_recommendation",
            "推荐火锅",
            "候选店铺: 海底捞"
        )
        # system + 3*2 few-shot + 1 user = 8条消息
        assert len(messages) >= 4
        assert messages[0]["role"] == "system"
    
    def test_yaml_system_contains_cot(self):
        """测试YAML的system prompt包含COT"""
        engine = get_prompt_engine()
        messages = engine.build_messages(
            "multi_shop_recommendation",
            "推荐火锅",
            "候选店铺: 海底捞"
        )
        system_content = messages[0]["content"]
        assert "思考步骤" in system_content or "Chain of Thought" in system_content
    
    def test_json_fallback(self):
        """测试JSON格式仍然可用"""
        engine = get_prompt_engine()
        # coupon_only只有JSON格式
        assert engine.has_config("coupon_only")
    
    def test_yaml_priority_over_json(self):
        """测试YAML优先于JSON"""
        engine = get_prompt_engine()
        # multi_shop_recommendation同时有YAML和JSON，应该加载YAML
        messages = engine.build_messages(
            "multi_shop_recommendation",
            "推荐火锅",
            "候选店铺: 海底捞"
        )
        # YAML版本的system prompt更长，包含COT
        system_content = messages[0]["content"]
        assert len(system_content) > 200  # YAML版本有详细的COT说明
```

- [ ] **Step 2: 运行测试**

Run: `cd learning-agent-service && python -m pytest tests/local_life/test_prompt_engine_yaml.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/local_life/test_prompt_engine_yaml.py
git commit -m "test: add unit tests for YAML prompt loading"
```

---

## Task 9: 端到端验证

**Files:**
- No new files

- [ ] **Step 1: 运行完整测试套件**

Run: `cd learning-agent-service && python -m pytest tests/ -v --tb=short`
Expected: 所有测试通过

- [ ] **Step 2: 手动测试推荐场景**

创建测试脚本验证推荐功能：

```python
# test_e2e_recommendation.py
from learning_agent_service.local_life.prompt_engine import get_prompt_engine

engine = get_prompt_engine()

# 模拟店铺数据
shop_data = [
    {"name": "海底捞(望京店)", "score": 4.8, "avg_price": 120, "distance": 1.2, "特色": ["服务好", "有宝宝椅"], "comments": 856},
    {"name": "巴奴毛肚火锅(三里屯店)", "score": 4.7, "avg_price": 150, "distance": 2.3, "特色": ["毛肚鲜嫩", "牛油锅底"], "comments": 623},
    {"name": "小龙坎(国贸店)", "score": 4.5, "avg_price": 100, "distance": 0.8, "特色": ["性价比高", "麻辣过瘾"], "comments": 412},
]

evidence_lines = ["候选店铺:"]
for i, shop in enumerate(shop_data, 1):
    evidence_lines.append(f"{i}. {shop['name']} - 评分{shop['score']}, 人均{shop['avg_price']}元, 距离{shop['distance']}km, 特色:{', '.join(shop['特色'])}, 评价数{shop['comments']}")

evidence_context = "\n".join(evidence_lines)

messages = engine.build_messages("multi_shop_recommendation", "推荐火锅", evidence_context)
print("Messages count:", len(messages))
print("System prompt preview:", messages[0]["content"][:200])
```

Run: `cd learning-agent-service && python test_e2e_recommendation.py`
Expected: 输出消息数量和system prompt预览

- [ ] **Step 3: 清理测试文件并最终提交**

```bash
rm test_e2e_recommendation.py
git add -A
git commit -m "feat: complete prompt migration from JSON to YAML with COT support"
```

---

## 回滚计划

如果迁移出现问题，可以快速回滚：

1. **删除YAML文件**：`rm learning-agent-service/src/learning_agent_service/local_life/prompts/*.yaml`
2. **恢复rag_gate.py**：`git checkout HEAD~5 -- learning-agent-service/src/learning_agent_service/application/rag_gate.py`
3. **恢复helpers.py**：`git checkout HEAD~5 -- learning-agent-service/src/learning_agent_service/application/workflow/adapters/helpers.py`

由于保留了JSON文件，PromptEngine会自动降级到JSON格式。

---

## 验证清单

- [ ] 所有YAML文件语法正确
- [ ] PromptEngine正确加载YAML（优先于JSON）
- [ ] few-shot示例被正确组装到messages中
- [ ] COT（Chain of Thought）指令在system prompt中
- [ ] rag_gate.py不再返回固定模板
- [ ] helpers.py调用PromptEngine生成回答
- [ ] stages正确传递店铺数据
- [ ] 所有现有测试通过
- [ ] 新增YAML相关测试通过
- [ ] 端到端推荐场景测试通过
