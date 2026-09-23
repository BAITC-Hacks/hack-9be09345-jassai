import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json

from fastapi.testclient import TestClient
import pytest

from app.config import Settings
from app.db import bump_revision, revision
from app.domain import apply_gains
from app.main import create_app
from tests.conftest import dataset_files, login, sample_dataset, upload


def test_health_and_setup_once(stack):
    app, hr, employee, data, settings = stack
    assert hr.get("/health").json()["application"] == "career-quest"
    ready = hr.get("/ready").json()
    assert ready == {"ready": True, "setup_required": False, "dataset_loaded": True, "ai_configured": False}
    assert hr.post("/api/setup", json={"token": settings.bootstrap_token, "username": "evil", "password": "another-password"}).status_code == 403
    operation = hr.get("/openapi.json").json()["paths"]["/api/me/activities/{event_id}/complete"]["post"]
    assert {p["name"] for p in operation["parameters"]} >= {"x-csrf-token", "idempotency-key"}


def test_effective_skills_and_candidates(stack):
    profile = stack[2].get("/api/me").json()
    assert profile["trajectory"]["effective_skills"] == {"SK_A": 2, "SK_B": 0}
    assert profile["trajectory"]["coverage_pct"] == 40
    ids = {e["event_id"] for e in profile["available_steps"]}
    assert "EV_GOOD" in ids
    assert not ids & {"EV_BEFORE", "EV_AFTER", "EV_CAPPED", "EV_PRE", "EV_MAND"}
    good = next(e for e in profile["available_steps"] if e["event_id"] == "EV_GOOD")
    assert good["expected_gains"][0] == {"skill_id": "SK_A", "before": 2, "after": 4, "gain": 2, "gap_closed": 2, "critical": True}


def test_cap_never_decreases_skill():
    assert apply_gains({"SK_A": 5}, {"develops_skills": [{"skill_id": "SK_A", "gain": 2, "max_level": 3}]}) == {"SK_A": 5}


def test_completion_persistence_and_idempotency(stack):
    app, hr, employee, data, settings = stack
    endpoint = "/api/me/activities/EV_GOOD/complete"
    response = employee.post(endpoint, json={}, headers={"Idempotency-Key": "once"})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["changes"] == [{"skill_id": "SK_A", "before": 2, "after": 4}]
    repeated = employee.post(endpoint, json={}, headers={"Idempotency-Key": "once"})
    assert repeated.json() == result
    assert employee.post(endpoint, json={}, headers={"Idempotency-Key": "another"}).status_code == 409
    assert employee.post("/api/me/activities/EV_036/complete", json={}, headers={"Idempotency-Key": "once"}).status_code == 409
    with TestClient(create_app(settings)) as restarted:
        login(restarted, "one")
        profile = restarted.get("/api/me").json()
        assert profile["trajectory"]["effective_skills"]["SK_A"] == 4
        assert len([r for r in profile["history"] if r["event_id"] == "EV_GOOD"]) == 1


def test_concurrent_completion_only_once(stack):
    client = stack[2]
    def complete(_):
        return client.post("/api/me/activities/EV_GOOD/complete", json={}, headers={"Idempotency-Key": "concurrent"})
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(complete, range(2)))
    assert [r.status_code for r in responses] == [200, 200]
    assert responses[0].json() == responses[1].json()


def test_start_continue_and_future_completion(stack):
    client = stack[2]
    result = client.post("/api/me/activities/EV_GOOD/start", json={})
    assert result.status_code == 200
    again = client.post("/api/me/activities/EV_GOOD/start", json={})
    assert again.json()["already_started"]
    assert again.json()["record"]["record_id"] == result.json()["record"]["record_id"]
    candidate = next(x for x in client.get("/api/me").json()["available_steps"] if x["event_id"] == "EV_GOOD")
    assert candidate["action"] == "continue"
    future = client.post("/api/me/activities/EV_FUTURE/start", json={})
    assert future.status_code == 200
    assert client.post("/api/me/activities/EV_FUTURE/complete", json={}, headers={"Idempotency-Key": "future"}).status_code == 409


def test_repeatable_club_distinct_sessions(stack):
    client = stack[2]
    for day in ["2026-09-30", "2026-10-01"]:
        response = client.post("/api/me/activities/EV_036/complete", json={"session_date": day}, headers={"Idempotency-Key": day})
        assert response.status_code == 200, response.text
    assert client.get("/api/me").json()["trajectory"]["effective_skills"]["SK_B"] == 2
    response = client.post("/api/me/activities/EV_036/complete", json={"session_date": "2026-10-01"}, headers={"Idempotency-Key": "duplicate"})
    assert response.status_code == 409


@pytest.mark.parametrize("endpoint", ["/api/hr/overview", "/api/hr/employees", "/api/hr/employees/E2", "/api/hr/employees/E2/recommendation-context"])
def test_employee_cannot_read_hr_or_colleague(stack, endpoint):
    assert stack[2].get(endpoint).status_code == 403


def test_session_csrf_origin_and_logout(stack):
    client = stack[2]
    csrf = client.headers.pop("X-CSRF-Token")
    assert client.patch("/api/me/goal", json={"career_goal": None}).status_code == 403
    client.headers["X-CSRF-Token"] = csrf
    assert client.patch("/api/me/goal", json={"career_goal": None}, headers={"Origin": "https://attacker.invalid"}).status_code == 403
    assert client.get("/api/auth/session").json()["csrf_token"] == csrf
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/me").status_code == 401


def test_no_auth_no_profiles(stack):
    client = TestClient(stack[0])
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/catalog").status_code == 401
    assert client.get("/ready", headers={"host": "attacker.invalid"}).status_code == 400
    client.close()


def test_default_goal_lead_and_cross_role(stack):
    app, hr, client, data, settings = stack
    result = client.patch("/api/me/goal", json={"career_goal": None})
    assert result.json()["trajectory"]["target"]["source"] == "suggested_next_grade"
    data["employees"][0].update(grade="Lead", career_goal=None)
    report = upload(hr, dataset_files(data, ["employees.json"]), "update").json()
    assert report["valid"], report
    assert hr.post("/api/hr/import/apply", json={"batch_id": report["batch_id"]}).status_code == 200
    view = client.get("/api/me").json()
    assert view["trajectory"]["target"]["goal"] is None
    assert view["available_steps"] == []
    assert client.post("/api/me/recommendations").json()["status"] == "no_candidates"


def test_cross_role_goal_respects_current_event_audience(stack):
    app, hr, client, data, settings = stack
    data["role_profiles"].append({"role": "Analyst", "grade": "Senior", "required_skills": {"SK_B": 4}, "critical_skills": ["SK_B"]})
    analyst_event = deepcopy(data["events"][0])
    analyst_event.update(event_id="EV_ANALYST_ONLY", target_roles=["Analyst"], develops_skills=[{"skill_id": "SK_B", "gain": 4, "max_level": 5}])
    data["events"].append(analyst_event)
    report = upload(hr, dataset_files(data, ["skills.json", "events.json"])).json()
    assert report["valid"], report
    hr.post("/api/hr/import/apply", json={"batch_id": report["batch_id"]})
    response = client.patch("/api/me/goal", json={"career_goal": {"target_role": "Analyst", "target_grade": "Senior"}})
    assert response.status_code == 200
    profile = response.json()
    assert profile["trajectory"]["target"]["goal"]["target_role"] == "Analyst"
    assert "EV_ANALYST_ONLY" not in {e["event_id"] for e in profile["available_steps"]}
    assert profile["trajectory"]["critical_gaps"][0]["skill_id"] == "SK_B"


def test_unknown_target_rejected_without_mutation(stack):
    client = stack[2]
    before = client.get("/api/me").json()["employee"]["career_goal"]
    assert client.patch("/api/me/goal", json={"career_goal": {"target_role": "Unknown", "target_grade": "Senior"}}).status_code == 422
    assert client.get("/api/me").json()["employee"]["career_goal"] == before


def test_jury_profile_and_atomic_invalid_import(stack):
    app, hr, client, data, settings = stack
    new = deepcopy(data["employees"][0])
    new.update(employee_id="JURY_NEW", manager_id="E2")
    data["employees"] = [new]
    report = upload(hr, dataset_files(data, ["employees.json"])).json()
    assert report["valid"]
    # Validation alone must not mutate the dataset.
    assert hr.get("/api/hr/employees/JURY_NEW").status_code == 404
    assert hr.post("/api/hr/import/apply", json={"batch_id": report["batch_id"]}).status_code == 200
    assert hr.get("/api/hr/employees/JURY_NEW").status_code == 200
    assert hr.post("/api/hr/import/apply", json={"batch_id": report["batch_id"]}).json()["already_applied"]
    new["employee_id"] = "INVALID_NEW"
    new["skills"]["UNKNOWN"] = 3
    invalid = upload(hr, dataset_files(data, ["employees.json"])).json()
    assert not invalid["valid"] and "batch_id" not in invalid
    assert hr.get("/api/hr/employees/INVALID_NEW").status_code == 404


def test_duplicate_import_and_explicit_update(stack):
    app, hr, client, data, settings = stack
    duplicate = upload(hr, dataset_files(data)).json()
    assert duplicate["valid"]
    assert duplicate["counts"]["history"] == {"added": 0, "updated": 0, "skipped": 2}
    data["employees"][0]["full_name"] = "Updated Name"
    conflict = upload(hr, dataset_files(data, ["employees.json"])).json()
    assert not conflict["valid"]
    update = upload(hr, dataset_files(data, ["employees.json"]), "update").json()
    assert update["valid"]
    hr.post("/api/hr/import/apply", json={"batch_id": update["batch_id"]})
    assert client.get("/api/me").json()["employee"]["full_name"] == "Updated Name"


@pytest.mark.parametrize("fault", ["unknown_employee", "invalid_level", "duplicate_id", "wrong_date", "bad_csv"])
def test_import_schema_and_reference_errors(stack, fault):
    app, hr, client, data, settings = stack
    if fault == "unknown_employee": data["history"][0]["employee_id"] = "ABSENT"
    if fault == "invalid_level": data["employees"][0]["skills"]["SK_A"] = True
    if fault == "duplicate_id": data["employees"].append(deepcopy(data["employees"][0]))
    files = dataset_files(data)
    if fault == "wrong_date":
        document = json.loads(files["events.json"])
        document["meta"]["as_of_date"] = "2026-10-02"
        files["events.json"] = json.dumps(document).encode()
    if fault == "bad_csv": files["activity_history.csv"] = b"wrong,columns\n1,2\n"
    report = upload(hr, files, "update").json()
    assert not report["valid"]
    assert "batch_id" not in report
    assert client.get("/api/me").json()["trajectory"]["effective_skills"]["SK_A"] == 2


def test_employee_cannot_import_or_create_accounts(stack):
    client = stack[2]
    assert upload(client, dataset_files(stack[3])).status_code == 403
    assert client.post("/api/hr/users", json={"username": "other", "password": "test-password-123", "role": "hr"}).status_code == 403


def test_same_day_application_completion_counts_after_assessment(stack):
    app, hr, client, data, settings = stack
    data["employees"][0]["last_review_date"] = "2026-10-01"
    report = upload(hr, dataset_files(data, ["employees.json"]), "update").json()
    assert report["valid"]
    hr.post("/api/hr/import/apply", json={"batch_id": report["batch_id"]})
    assert client.get("/api/me").json()["trajectory"]["effective_skills"]["SK_A"] == 1
    result = client.post("/api/me/activities/EV_GOOD/complete", json={}, headers={"Idempotency-Key": "same-day"})
    assert result.status_code == 200, result.text
    assert result.json()["changes"] == [{"skill_id": "SK_A", "before": 1, "after": 3}]


def test_stale_import_cannot_overwrite_completion(stack):
    app, hr, client, data, settings = stack
    report = upload(hr, dataset_files(data)).json()
    client.post("/api/me/activities/EV_GOOD/complete", json={}, headers={"Idempotency-Key": "changed"})
    response = hr.post("/api/hr/import/apply", json={"batch_id": report["batch_id"]})
    assert response.status_code == 409


def test_hr_metrics_and_period(stack):
    result = stack[1].get("/api/hr/overview").json()
    assert result["employee_count"] == 2
    skill = next(x for x in result["skill_deficits"] if x["skill_id"] == "SK_A")
    assert skill["target_population"] == 2 and skill["employees_with_gap"] == 2
    assert skill["gap_pct"] == 100
    assert sum(x["records"] for x in result["participation"]) == 2
    filtered = stack[1].get("/api/hr/overview?date_from=2026-09-15").json()
    assert sum(x["records"] for x in filtered["participation"]) == 1
    assert stack[1].get("/api/hr/overview?date_from=2026-10-01&date_to=2026-09-01").status_code == 422


def ai_result(context):
    return {"recommendations": [{
        "event_id": context["candidates"][0]["event_id"], "reason": "Test response; no live model involved",
        "factors": [{"type": kind, "text": f"Test factor {kind}"} for kind in ["goal", "skill_gap", "history"]],
    }]}


def test_ai_hook_validation_cache_invalidation(stack):
    app, hr, client, data, settings = stack
    captured = []
    async def provider(context):
        captured.append(deepcopy(context))
        return ai_result(context)
    app.state.recommender = provider
    first = client.post("/api/me/recommendations")
    assert first.status_code == 200, first.text
    assert first.json()["mode"] == "ai" and not first.json()["cached"]
    assert "full_name" not in captured[0]["employee"]
    assert "expected_gains" in first.json()["recommendations"][0]["event"]
    assert client.post("/api/me/recommendations").json()["cached"]
    assert len(captured) == 1
    client.patch("/api/me/goal", json={"career_goal": None})
    assert not client.post("/api/me/recommendations").json()["cached"]
    assert len(captured) == 2


@pytest.mark.parametrize("bad", ["unknown_event", "duplicate_event", "few_factors", "duplicate_factors", "exception"])
def test_ai_bad_output_rejected(stack, bad):
    app, hr, client, data, settings = stack
    def provider(context):
        if bad == "exception":
            raise RuntimeError("secret-provider-token")
        result = ai_result(context)
        choice = result["recommendations"][0]
        if bad == "unknown_event": choice["event_id"] = "EV_UNKNOWN"
        if bad == "duplicate_event": result["recommendations"].append(deepcopy(choice))
        if bad == "few_factors": choice["factors"] = choice["factors"][:1]
        if bad == "duplicate_factors": choice["factors"][1]["type"] = "goal"
        return result
    app.state.recommender = provider
    result = client.post("/api/me/recommendations")
    assert result.status_code == 502
    assert "secret-provider-token" not in result.text


def test_ai_missing_and_stale_context(stack):
    app, hr, client, data, settings = stack
    assert client.post("/api/me/recommendations").status_code == 503
    def provider(context):
        with app.state.db.connection(write=True) as conn: bump_revision(conn)
        return ai_result(context)
    app.state.recommender = provider
    assert client.post("/api/me/recommendations").status_code == 409


def test_bootstrap_token_and_secrets_not_echoed(tmp_path):
    settings = Settings(tmp_path, testing=True)
    with TestClient(create_app(settings)) as client:
        token = (tmp_path / "setup-token.txt").read_text()
        assert token not in client.get("/ready").text
        assert client.post("/api/setup", json={"token": "bad", "username": "hr", "password": "strong-enough"}).status_code == 403
        secret = "s" * 300
        result = client.post("/api/setup", json={"token": token, "username": "hr", "password": secret})
        assert result.status_code == 422 and secret not in result.text
        assert client.post("/api/setup", json={"token": token, "username": "hr", "password": "strong-enough"}).status_code == 201
        assert not (tmp_path / "setup-token.txt").exists()


def test_login_rate_limit(stack):
    with TestClient(stack[0]) as client:
        for _ in range(10):
            assert client.post("/api/auth/login", json={"username": "hr", "password": "wrong"}).status_code == 401
        assert client.post("/api/auth/login", json={"username": "hr", "password": "wrong"}).status_code == 429


def test_mandatory_recurring_history_allowed(stack):
    app, hr, client, data, settings = stack
    for index, day in enumerate(["2025-09-01", "2026-09-01"]):
        record = deepcopy(data["history"][0])
        record.update(record_id=f"MAND_{index}", event_id="EV_MAND", date=day)
        data["history"].append(record)
    result = upload(hr, dataset_files(data, ["activity_history.csv"])).json()
    assert result["valid"], result


def test_ai_timeout_is_bounded(tmp_path):
    async def slow_provider(context):
        await asyncio.sleep(1)
        return ai_result(context)
    settings = Settings(tmp_path, bootstrap_token="token", ai_timeout=0.02, testing=True)
    app = create_app(settings, slow_provider)
    with TestClient(app) as client:
        client.post("/api/setup", json={"username": "hr", "password": "test-password-123", "token": "token"})
        login(client)
        report = upload(client, dataset_files(sample_dataset())).json()
        client.post("/api/hr/import/apply", json={"batch_id": report["batch_id"]})
        client.post("/api/hr/users", json={"username": "one", "password": "test-password-123", "employee_id": "E1"})
        login(client, "one")
        assert client.post("/api/me/recommendations").status_code == 504
