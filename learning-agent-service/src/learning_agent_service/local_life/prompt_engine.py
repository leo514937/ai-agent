"""LLM-based answer generation using few-shot prompting."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

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
        """启动时加载所有 JSON 配置文件"""
        if not _PROMPTS_DIR.exists():
            return
        for json_file in _PROMPTS_DIR.glob("*.json"):
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
                scene = data.get("scene", json_file.stem)
                config = PromptSceneConfig(
                    scene=scene,
                    description=data.get("description", ""),
                    system=data.get("system", ""),
                    few_shots=data.get("few_shots", []),
                )
                self._configs[scene] = config
                logger.info("loaded_prompt_config scene=%s", scene)
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
