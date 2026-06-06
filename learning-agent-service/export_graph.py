"""触发 LangGraph 拓扑导出（Mermaid 文本 + PNG）"""
import sys
sys.path.insert(0, "src")

from learning_agent_service.application.workflow.builder import _build_langgraph_runner
from learning_agent_service.application.workflow.services import WorkflowServices

services = WorkflowServices()
graph = _build_langgraph_runner(services)
print("graph.png exported")
