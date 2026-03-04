from worker.main import build_worker_config


def test_build_worker_config_defaults(monkeypatch) -> None:
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("WORKER_POLL_INTERVAL_SECONDS", raising=False)
    cfg = build_worker_config()
    assert cfg.redis_url == "redis://redis:6379/0"
    assert cfg.poll_interval_seconds == 5


def test_build_worker_config_overrides(monkeypatch) -> None:
    monkeypatch.setenv("REDIS_URL", "redis://custom:6379/1")
    monkeypatch.setenv("WORKER_POLL_INTERVAL_SECONDS", "9")
    cfg = build_worker_config()
    assert cfg.redis_url == "redis://custom:6379/1"
    assert cfg.poll_interval_seconds == 9

