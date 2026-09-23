"""Actual authenticated A -> B -> A requests; only B's HTTP transport is mocked."""

import asyncio
import json

import httpx
import pytest

from app.ai import provider


def attach_provider(app, monkeypatch, handler):
    original_client = httpx.AsyncClient
    transport = httpx.MockTransport(handler)

    def client_with_mock_transport(*args, **kwargs):
        return original_client(*args, transport=transport, **kwargs)

    monkeypatch.setattr(provider.httpx, "AsyncClient", client_with_mock_transport)
    monkeypatch.setenv("OPENAI_API_KEY", "integration-test-not-a-real-key")
    monkeypatch.setenv("OPENAI_MODEL", "integration-test-model")
    app.state.recommender = provider.recommend


def model_response(context):
    facts = context["candidate_facts"]
    candidates = list(facts)
    chosen = "EV_GOOD" if "EV_GOOD" in candidates else candidates[0]
    selection = {
        "recommendations": [{
            "event_id": chosen,
            "factor_types": ["goal", "skill_gap", "history"],
            "alternative_event_id": next((event for event in candidates if event != chosen), None),
            "comparison_factor": "duration",
        }],
    }
    return {
        "status": "completed",
        "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(selection)}]}],
    }


def test_recommendation_route_calls_b_caches_and_refreshes_after_completion(stack, monkeypatch):
    app, _, client, _, _ = stack
    requests = []

    def handler(request):
        assert str(request.url) == "https://api.openai.com/v1/responses"
        payload = json.loads(request.content)
        context = json.loads(payload["input"])
        requests.append((payload, context))
        return httpx.Response(200, json=model_response(context))

    attach_provider(app, monkeypatch, handler)
    before = client.get("/api/me").json()
    expected = next(event for event in before["available_steps"] if event["event_id"] == "EV_GOOD")
    response = client.post("/api/me/recommendations")
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "ok" and result["mode"] == "ai"
    assert result["cached"] is False and len(result["recommendations"]) == 1
    row = result["recommendations"][0]
    assert row["event_id"] == "EV_GOOD"
    assert {factor["type"] for factor in row["factors"]} == {"goal", "skill_gap", "history"}
    assert all(factor["text"] for factor in row["factors"])
    assert row["event"] == expected
    assert row["event"]["expected_gains"][0]["before"] == 2
    assert row["event"]["expected_gains"][0]["after"] == 4

    payload, context = requests[0]
    assert payload["model"] == "integration-test-model"
    assert payload["store"] is False
    assert payload["text"]["format"]["strict"] is True
    allowed_ids = payload["text"]["format"]["schema"]["properties"]["recommendations"]["items"]["properties"]["event_id"]["enum"]
    assert set(allowed_ids) == {event["event_id"] for event in before["available_steps"]}
    assert "employee_id" not in context["employee"] and "full_name" not in context["employee"]

    cached = client.post("/api/me/recommendations")
    assert cached.status_code == 200 and cached.json()["cached"] is True
    assert cached.json()["recommendations"] == result["recommendations"]
    assert len(requests) == 1

    completed = client.post(
        "/api/me/activities/EV_GOOD/complete", json={},
        headers={"Idempotency-Key": "b-integration-complete"},
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["changes"] == [{"skill_id": "SK_A", "before": 2, "after": 4}]

    refreshed = client.post("/api/me/recommendations")
    assert refreshed.status_code == 200, refreshed.text
    fresh = refreshed.json()
    assert fresh["cached"] is False and fresh["data_revision"] > result["data_revision"]
    assert len(requests) == 2
    assert "EV_GOOD" not in requests[1][1]["candidate_facts"]
    assert requests[1][1]["history_summary"]["total_records"] == context["history_summary"]["total_records"] + 1
    available_now = {event["event_id"]: event for event in client.get("/api/me").json()["available_steps"]}
    for recommendation in fresh["recommendations"]:
        assert recommendation["event"] == available_now[recommendation["event_id"]]


@pytest.mark.parametrize("failure", ["http_error", "invalid_selection"])
def test_provider_failures_are_explicit_502_and_never_cached_as_ai(stack, monkeypatch, failure):
    app, _, client, _, _ = stack
    requests = []

    def handler(request):
        requests.append(request)
        if failure == "http_error":
            return httpx.Response(401, text="integration-test-not-a-real-key private-provider-body")
        return httpx.Response(200, json={
            "status": "completed",
            "output": [{"type": "message", "content": [{"type": "output_text", "text": '{"recommendations":[]}'}]}],
        })

    attach_provider(app, monkeypatch, handler)
    for _ in range(2):
        response = client.post("/api/me/recommendations")
        assert response.status_code == 502, response.text
        assert response.json() == {"detail": {"code": "ai_provider_failed"}}
        assert "integration-test-not-a-real-key" not in response.text
        assert "private-provider-body" not in response.text
        assert "recommendations" not in response.json()
    assert len(requests) == 2


def test_b_deadline_reaches_a_as_504_without_fabricated_recommendations(stack, monkeypatch):
    app, _, client, _, _ = stack

    async def handler(request):
        await asyncio.sleep(1)
        return httpx.Response(200, json=model_response(json.loads(json.loads(request.content)["input"])))

    attach_provider(app, monkeypatch, handler)
    monkeypatch.setattr(provider, "REQUEST_BUDGET", 0.02)
    response = client.post("/api/me/recommendations")
    assert response.status_code == 504, response.text
    assert response.json() == {"detail": {"code": "ai_timeout"}}
    with app.state.db.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM recommendation_cache").fetchone()[0] == 0

