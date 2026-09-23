"""Gamification is private, optional and rewards only real application progress."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

from fastapi.testclient import TestClient
import pytest

from app.main import create_app
from tests.conftest import dataset_files, login, upload


GAME = "/api/me/gamification"
QUEST = GAME + "/quest"


def state(client):
    response = client.get(GAME)
    assert response.status_code == 200, response.text
    return response.json()


def enable(client, value=True):
    response = client.patch(GAME, json={"enabled": value})
    assert response.status_code == 200, response.text
    return response.json()


def complete(client, event_id="EV_GOOD", key="gamification-once", body=None):
    return client.post(
        f"/api/me/activities/{event_id}/complete",
        json=body or {}, headers={"Idempotency-Key": key},
    )


def apply_import(hr, data, names, mode="add"):
    validation = upload(hr, dataset_files(data, names), mode)
    assert validation.status_code == 200, validation.text
    report = validation.json()
    assert report["valid"], report
    response = hr.post("/api/hr/import/apply", json={"batch_id": report["batch_id"]})
    assert response.status_code == 200, response.text
    return report["batch_id"]


def earned_badges(value):
    return {badge["id"] for badge in value["badges"] if badge["earned"]}


def test_default_disabled_and_imported_history_has_no_rewards(stack):
    client = stack[2]
    assert len(client.get("/api/me").json()["history"]) == 2
    initial = state(client)
    assert initial["enabled"] is False
    assert initial["xp"] == 0 and initial["level"] == 1
    assert initial["completed_count"] == 0
    assert initial["skill_levels_gained"] == 0
    assert initial["recent_rewards"] == [] and initial["quest"] is None
    assert earned_badges(initial) == set()
    assert client.post(QUEST, json={"event_id": "EV_GOOD"}).status_code == 409
    assert state(client) == initial
    enabled = enable(client)
    assert enabled["enabled"] is True and enabled["xp"] == 0
    assert enabled["recent_rewards"] == []


@pytest.mark.parametrize("method,path,body", [
    ("GET", GAME, None),
    ("PATCH", GAME, {"enabled": True}),
    ("POST", QUEST, {"event_id": "EV_GOOD"}),
    ("DELETE", QUEST, None),
])
def test_gamification_requires_employee_session(stack, method, path, body):
    app, hr, _, _, _ = stack
    options = {"json": body} if body is not None else {}
    assert hr.request(method, path, **options).status_code == 403
    with TestClient(app) as anonymous:
        assert anonymous.request(method, path, **options).status_code == 401


@pytest.mark.parametrize("method,path,body", [
    ("PATCH", GAME, {"enabled": True}),
    ("POST", QUEST, {"event_id": "EV_GOOD"}),
    ("DELETE", QUEST, None),
])
def test_gamification_mutations_require_csrf(stack, method, path, body):
    client = stack[2]
    before = state(client)
    csrf = client.headers.pop("X-CSRF-Token")
    try:
        options = {"json": body} if body is not None else {}
        response = client.request(method, path, **options)
        assert response.status_code == 403, response.text
        assert state(client) == before
    finally:
        client.headers["X-CSRF-Token"] = csrf


def test_real_gain_awarded_once_and_survives_restart(stack):
    _, _, client, _, settings = stack
    enable(client)
    response = complete(client)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["reward"] == {
        "awarded": True, "xp": 40, "gained_levels": 2, "reason": "awarded",
    }
    current = state(client)
    assert current["xp"] == 40 and current["completed_count"] == 1
    assert current["skill_levels_gained"] == 2
    assert result["gamification"] == current
    assert earned_badges(current) == {"first_step"}
    assert len(current["recent_rewards"]) == 1
    assert current["recent_rewards"][0]["record_id"] == result["record"]["record_id"]
    assert complete(client).json() == result
    assert complete(client, key="another-key").status_code == 409
    assert state(client) == current
    with TestClient(create_app(settings)) as restarted:
        login(restarted, "one")
        assert state(restarted) == current


def test_import_and_repeated_apply_never_grant_retroactive_xp(stack):
    _, hr, client, data, _ = stack
    enable(client)
    record = deepcopy(data["history"][0])
    record.update(record_id="IMPORTED_NEW_COMPLETION", event_id="EV_GOOD", date="2026-09-25")
    data["history"].append(record)
    batch = apply_import(hr, data, ["activity_history.csv"])
    assert client.get("/api/me").json()["trajectory"]["effective_skills"]["SK_A"] == 4
    assert hr.post("/api/hr/import/apply", json={"batch_id": batch}).json()["already_applied"]
    apply_import(hr, data, ["activity_history.csv"])
    enable(client, False)
    result = enable(client)
    assert result["xp"] == 0 and result["completed_count"] == 0
    assert result["recent_rewards"] == [] and earned_badges(result) == set()


def test_reward_ledger_does_not_reward_same_record_after_history_update(stack):
    _, hr, client, data, _ = stack
    enable(client)
    response = complete(client)
    assert response.status_code == 200, response.text
    original = response.json()
    before = state(client)
    # An explicit HR history correction may reopen an existing record. Its ID
    # must retain its reward identity even though imported rows have no source.
    columns = data["history"][0].keys()
    reopened = {key: original["record"][key] for key in columns}
    reopened.update(status="in_progress", completion_pct=0)
    data["history"].append(reopened)
    apply_import(hr, data, ["activity_history.csv"], "update")
    repeated = complete(client, key="reopened", body={"activity_record_id": reopened["record_id"]})
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["reward"]["awarded"] is False
    assert repeated.json()["reward"]["reason"] == "already_awarded"
    assert repeated.json()["reward"]["xp"] == 0
    after = state(client)
    assert after["xp"] == before["xp"]
    assert after["recent_rewards"] == before["recent_rewards"]


def test_opt_out_preserves_progress_but_awards_nothing_new(stack):
    client = stack[2]
    enable(client)
    assert complete(client).status_code == 200
    before = state(client)
    disabled = enable(client, False)
    assert disabled["enabled"] is False and disabled["xp"] == before["xp"]
    response = complete(client, "EV_036", "disabled-club", {"session_date": "2026-10-01"})
    assert response.status_code == 200, response.text
    assert response.json()["reward"] == {
        "awarded": False, "xp": 0, "gained_levels": 1, "reason": "disabled",
    }
    assert response.json()["changes"] == [{"skill_id": "SK_B", "before": 0, "after": 1}]
    resumed = enable(client)
    assert resumed["xp"] == before["xp"]
    assert resumed["completed_count"] == before["completed_count"]
    assert resumed["recent_rewards"] == before["recent_rewards"]
    assert earned_badges(resumed) == earned_badges(before)


def test_no_skill_gain_gives_no_xp_even_when_completed(stack):
    client = stack[2]
    enable(client)
    response = complete(client, "EV_CAPPED", "capped")
    assert response.status_code == 200, response.text
    assert response.json()["changes"] == []
    assert response.json()["reward"] == {
        "awarded": False, "xp": 0, "gained_levels": 0, "reason": "no_skill_gain",
    }
    result = state(client)
    assert result["xp"] == 0 and result["completed_count"] == 0
    assert earned_badges(result) == set()
    assert complete(client, "EV_MAND", "mandatory").status_code == 409
    assert state(client) == result


def test_reward_uses_actual_capped_gain_not_catalog_promise(stack):
    _, hr, client, data, _ = stack
    data["employees"][0]["skills"]["SK_A"] = 3
    data["employees"][0]["last_review_date"] = "2026-10-01"
    apply_import(hr, data, ["employees.json"], "update")
    enable(client)
    response = complete(client, key="actual-cap")
    assert response.status_code == 200, response.text
    assert response.json()["changes"] == [{"skill_id": "SK_A", "before": 3, "after": 4}]
    assert response.json()["reward"]["xp"] == 30
    assert response.json()["reward"]["gained_levels"] == 1
    assert state(client)["skill_levels_gained"] == 1


def test_same_day_assessment_does_not_hide_application_reward(stack):
    _, hr, client, data, _ = stack
    data["employees"][0]["last_review_date"] = "2026-10-01"
    apply_import(hr, data, ["employees.json"], "update")
    enable(client)
    response = complete(client, key="assessment-day")
    assert response.status_code == 200, response.text
    assert response.json()["changes"] == [{"skill_id": "SK_A", "before": 1, "after": 3}]
    assert response.json()["reward"]["xp"] == 40
    assert state(client)["xp"] == 40


@pytest.mark.parametrize("event_id", ["UNKNOWN", "EV_MAND", "EV_PRE", "EV_CAPPED", "EV_BEFORE"])
def test_quest_accepts_only_current_candidates(stack, event_id):
    client = stack[2]
    enable(client)
    before = state(client)
    response = client.post(QUEST, json={"event_id": event_id})
    assert response.status_code in {404, 409, 422}, response.text
    assert state(client) == before


def test_personal_quest_pause_cancel_and_rewarded_completion(stack):
    client = stack[2]
    enable(client)
    selected = client.post(QUEST, json={"event_id": "EV_GOOD"})
    assert selected.status_code == 200, selected.text
    quest = selected.json()["quest"]
    assert quest["event_id"] == "EV_GOOD" and quest["status"] == "active"
    assert not {"deadline", "due_date"} & quest.keys()
    assert enable(client, False)["quest"]["status"] == "paused"
    assert enable(client)["quest"]["status"] == "active"
    cancelled = client.delete(QUEST)
    assert cancelled.status_code == 200 and cancelled.json()["quest"] is None
    assert client.post(QUEST, json={"event_id": "EV_GOOD"}).status_code == 200
    response = complete(client, key="personal-quest")
    assert response.status_code == 200, response.text
    result = state(client)
    assert result["quest"]["status"] == "completed"
    assert earned_badges(result) == {"first_step", "personal_quest"}
    assert enable(client, False)["quest"]["status"] == "completed"


def test_quest_becomes_unavailable_after_goal_changes(stack):
    client = stack[2]
    enable(client)
    assert client.post(QUEST, json={"event_id": "EV_GOOD"}).status_code == 200
    goal = client.patch("/api/me/goal", json={"career_goal": {"target_role": "Engineer", "target_grade": "Junior"}})
    assert goal.status_code == 200, goal.text
    quest = state(client)["quest"]
    assert quest["status"] == "unavailable"
    assert quest["unavailable_reasons"]


def test_badges_require_rewarded_distinct_events_and_real_gained_levels(stack):
    _, hr, client, data, _ = stack
    for event_id, gain in [("EV_SPEAKING_TWO", 2), ("EV_SPEAKING_ONE", 1)]:
        event = deepcopy(data["events"][0])
        event.update(event_id=event_id, title=event_id, develops_skills=[{"skill_id": "SK_B", "gain": gain, "max_level": 5}])
        data["events"].append(event)
    apply_import(hr, data, ["events.json"])
    enable(client)
    for event_id in ["EV_GOOD", "EV_SPEAKING_TWO", "EV_SPEAKING_ONE"]:
        response = complete(client, event_id, event_id)
        assert response.status_code == 200, response.text
    result = state(client)
    assert result["xp"] == 110 and result["completed_count"] == 3
    assert result["skill_levels_gained"] == 5
    assert earned_badges(result) == {"first_step", "three_steps", "skill_builder"}
    assert len({row["record_id"] for row in result["recent_rewards"]}) == 3


def test_repeatable_sessions_do_not_count_as_three_distinct_events(stack):
    client = stack[2]
    enable(client)
    assert complete(client).status_code == 200
    for day in ["2026-09-30", "2026-10-01"]:
        response = complete(client, "EV_036", day, {"session_date": day})
        assert response.status_code == 200, response.text
    result = state(client)
    assert result["completed_count"] == 3 and result["xp"] == 100
    assert "three_steps" not in earned_badges(result)


@pytest.mark.parametrize("same_key", [True, False])
def test_parallel_completions_never_duplicate_rewards(stack, same_key):
    client = stack[2]
    enable(client)

    def perform(index):
        return complete(client, key="parallel" if same_key else f"parallel-{index}")

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(perform, range(2)))
    assert sorted(response.status_code for response in responses) == ([200, 200] if same_key else [200, 409])
    if same_key:
        assert responses[0].json() == responses[1].json()
    result = state(client)
    assert result["xp"] == 40 and result["completed_count"] == 1
    assert len(result["recent_rewards"]) == 1


def test_gamification_is_private_to_employee_and_absent_from_hr(stack):
    app, hr, client, _, _ = stack
    profile_before = hr.get("/api/hr/employees/E1").json()
    overview_before = hr.get("/api/hr/overview").json()
    enable(client)
    assert client.post(QUEST, json={"event_id": "EV_GOOD"}).status_code == 200
    assert hr.get("/api/hr/employees/E1").json() == profile_before
    assert hr.get("/api/hr/overview").json() == overview_before
    assert complete(client).status_code == 200
    assert "gamification" not in hr.get("/api/hr/employees/E1").json()
    assert "gamification" not in hr.get("/api/hr/overview").json()
    with TestClient(app) as other:
        login(other, "two")
        private = state(other)
        assert private["enabled"] is False and private["xp"] == 0
        assert private["quest"] is None and private["recent_rewards"] == []
