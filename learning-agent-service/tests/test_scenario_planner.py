import pytest
from learning_agent_service.application.scenario_planner import ScenarioPlanner

def test_scenario_planner_basic():
    planner = ScenarioPlanner()
    result = planner.plan(
        query="我想找一家适合约会的火锅店，要有包间，人均不超过200",
        context={"domain": "local_life"},
    )
    assert len(result) > 0
    assert all(hasattr(step, 'action') for step in result)

def test_scenario_planner_simple_query():
    planner = ScenarioPlanner()
    result = planner.plan(
        query="附近有什么火锅店",
        context={"domain": "local_life"},
    )
    assert len(result) > 0
