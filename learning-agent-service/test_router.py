import sys
import os

sys.path.insert(0, os.path.abspath('src'))

from learning_agent_service.local_life.query_router import LocalLifeQueryRouter
from learning_agent_service.local_life.schemas import LocalLifeSlots

router = LocalLifeQueryRouter()
slots = LocalLifeSlots()
decision = router.route("你记得我们聊过什么吗", slots=slots)
print("Route:", decision.route)
print("Reason:", decision.route_reason)
print("Use Qdrant:", decision.use_qdrant)
