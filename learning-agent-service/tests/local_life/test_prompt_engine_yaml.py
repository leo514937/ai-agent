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
