"""Smoke test: can we reach Ollama through Open WebUI?

Needs OPENWEBUI_URL and OPENWEBUI_API_KEY (from .env, loaded by the root conftest.py,
or the environment). Optionally OPENWEBUI_MODEL; otherwise the first listed model is used.
"""

import os

import httpx
import pytest

pytestmark = pytest.mark.llm

BASE_URL = os.environ.get("OPENWEBUI_URL", "http://localhost:3000").rstrip("/")
API_KEY = os.environ.get("OPENWEBUI_API_KEY")


@pytest.fixture(scope="module")
def client():
    if not API_KEY:
        pytest.skip("OPENWEBUI_API_KEY not set")
    with httpx.Client(
        base_url=BASE_URL,
        headers={"Authorization": f"Bearer {API_KEY}"},
        timeout=180,
    ) as c:
        yield c


@pytest.fixture(scope="module")
def models(client):
    response = client.get("/api/models")
    assert response.status_code == 200, (
        f"GET /api/models -> {response.status_code}: {response.text[:200]}"
    )
    return [m["id"] for m in response.json()["data"]]


def test_lists_models(models):
    assert models, "Open WebUI returned no models (is Ollama connected?)"


def test_chat_completion(client, models):
    model = os.environ.get("OPENWEBUI_MODEL", models[0])
    response = client.post(
        "/api/chat/completions",
        json={
            "model": model,
            "messages": [{"role": "user", "content": "Reply with the single word: pong"}],
            "stream": False,
        },
    )
    assert response.status_code == 200, (
        f"chat with {model} -> {response.status_code}: {response.text[:200]}"
    )
    reply = response.json()["choices"][0]["message"]["content"]
    assert reply.strip(), f"{model} returned an empty reply"
