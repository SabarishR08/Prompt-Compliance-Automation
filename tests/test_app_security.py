import importlib
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
import sys

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture()
def app_module(monkeypatch):
    monkeypatch.setenv("ADMIN_API_KEY", "test-admin-key")
    monkeypatch.setenv("RATE_LIMIT_MAX_REQUESTS", "1")
    monkeypatch.setenv("RATE_LIMIT_WINDOW_SECONDS", "60")
    monkeypatch.setenv("TRUSTED_HOSTS", "testserver,127.0.0.1,localhost")

    module = importlib.import_module("app")
    module = importlib.reload(module)

    class FakeAnalyzer:
        def analyze(self, text, language="en"):
            return []

    class FakeDetoxify:
        def predict(self, prompt):
            return {
                "toxicity": 0.0,
                "severe_toxicity": 0.0,
                "obscene": 0.0,
                "threat": 0.0,
                "insult": 0.0,
                "identity_attack": 0.0,
            }

    monkeypatch.setattr(module, "analyzer", FakeAnalyzer())
    monkeypatch.setattr(module, "detoxify_model", FakeDetoxify())
    monkeypatch.setattr(module, "nlp_engine_loaded", True)
    monkeypatch.setattr(module, "get_gemini_response", lambda *_args, **_kwargs: None)
    module.request_buckets.clear()
    return module


@pytest.fixture()
def client(app_module):
    return TestClient(app_module.app)


def test_admin_routes_require_key(client):
    assert client.get("/get_logs").status_code == 401
    assert client.post("/clear_logs").status_code == 401
    assert client.post("/update_mode", json={"mode": "Default"}).status_code == 401
    assert client.get("/get_settings").status_code == 401


def test_admin_routes_accept_key(client):
    headers = {"X-Admin-Key": "test-admin-key"}
    assert client.get("/get_settings", headers=headers).status_code == 200
    assert client.get("/get_logs", headers=headers).status_code == 200
    assert client.post("/update_mode", json={"mode": "Custom"}, headers=headers).status_code == 200


def test_prompt_rate_limit(client):
    first = client.post("/check_prompt", json={"text": "hello world"})
    second = client.post("/check_prompt", json={"text": "hello world again"})

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["detail"] == "Rate limit exceeded. Please try again later."
