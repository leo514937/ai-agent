from learning_agent_service.local_life.scene_policy import ScenePolicy


def test_scene_business():
    passed, reason = ScenePolicy.apply("适合商务宴请的餐厅", "环境一般，服务差")
    assert not passed
    assert "商务宴请" in reason
    assert "服务差" in reason


def test_scene_solo():
    passed, reason = ScenePolicy.apply("一个人吃饭推荐", "必须多人，最低消费100")
    assert not passed
    assert "一个人" in reason


def test_scene_late_night():
    passed, reason = ScenePolicy.apply("深夜有什么好吃的", "晚上10点关门")
    assert not passed
    assert "深夜" in reason


def test_get_preferred_facets():
    facets = ScenePolicy.get_preferred_facets("适合约会的餐厅")
    assert "environment" in facets
    assert "atmosphere" in facets


def test_detect_scene():
    assert ScenePolicy.detect_scene("适合约会的餐厅") == "约会"
    assert ScenePolicy.detect_scene("适合带小孩的餐厅") == "带小孩"
    assert ScenePolicy.detect_scene("今天天气怎么样") is None
