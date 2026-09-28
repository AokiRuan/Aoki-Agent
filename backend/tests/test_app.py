"""FastAPI 应用冒烟测试。讲解见 docs/02-project-setup.md。"""
from fastapi.testclient import TestClient

from backend.app.main import app


def test_health():
    with TestClient(app) as client:
        r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
