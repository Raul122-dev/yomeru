"""Shared fixtures."""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """App with every data path in a temp dir and one dummy connection + model."""
    import yomeru.core.paths as paths
    import yomeru.core.runs as runs
    import yomeru.core.settings as settings

    monkeypatch.setattr(paths, "DATA_DIR", tmp_path)
    monkeypatch.setattr(runs, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(settings, "CONFIG_FILE", tmp_path / "config.json")
    (tmp_path / "runs").mkdir()
    from yomeru.app import app
    c = TestClient(app)
    c.post("/api/config/connections", json={"name": "Local", "protocol": "openai",
                                            "base_url": "http://127.0.0.1:9/v1"})
    c.patch("/api/config/settings", json={"analysis_model": {"model": "test-model"}})
    return c
