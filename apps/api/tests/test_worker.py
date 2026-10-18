from byop.worker import celery_app, ping


def test_ping_task_is_registered_under_its_public_name() -> None:
    assert "byop.ping" in celery_app.tasks


def test_ping_returns_pong() -> None:
    assert ping.apply().get() == "pong"


def test_celery_uses_redis_and_json() -> None:
    assert celery_app.conf.broker_url.startswith("redis://")
    assert celery_app.conf.task_serializer == "json"
