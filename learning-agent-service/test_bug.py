import asyncio
from learning_agent_service.application.agent import LearningAgent
from learning_agent_service.application.request import AgentExecuteRequest

async def main():
    agent = LearningAgent()
    req = AgentExecuteRequest(
        query="海底捞水晶城店怎么样",
        session_id="test_session_123"
    )
    result = await agent.execute(req)
    print("FINAL ANSWER:", result.answer)

if __name__ == "__main__":
    asyncio.run(main())
