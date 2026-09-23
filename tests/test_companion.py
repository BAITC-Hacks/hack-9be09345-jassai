"""Wardrobe rewards remain private and factual; the tree cannot bypass eligibility."""
from copy import deepcopy
import importlib
import sqlite3

from fastapi import HTTPException
import pytest
from fastapi.testclient import TestClient

from app.companion import DEFAULT_EQUIPMENT, companion_view, equip_item, skill_tree
from app.db import Database, SCHEMA
from app.domain import candidates, role_key, trajectory
from app.gamification import award_completion, gamification_view, set_enabled
from tests.conftest import sample_dataset


AS_OF = "2026-10-01"


def test_public_mascot_asset_is_glb_and_does_not_expose_repository(stack):
    with TestClient(stack[0]) as anonymous:
        response = anonymous.get("/static/assets/mascot/character.glb")
        assert response.status_code == 200
        assert response.headers["content-type"] == "model/gltf-binary"
        assert response.content[:4] == b"glTF"
        assert int.from_bytes(response.content[4:8], "little") == 2
        assert int.from_bytes(response.content[8:12], "little") == len(response.content)
        for path in (
            "/static/assets/mascot/../app/config.py",
            "/static/assets/mascot/%2e%2e/%2e%2e/%2e%2e/app/config.py",
            "/static/assets/mascot/source/build_character.py",
            "/static/assets/mascot/character.blend",
        ):
            assert anonymous.get(path).status_code == 404


def test_missing_mascot_asset_returns_safe_404(stack, tmp_path, monkeypatch):
    app_main = importlib.import_module("app.main")
    monkeypatch.setattr(app_main, "MASCOT_MODEL_PATH", tmp_path / "missing.glb")
    response = stack[2].get("/static/assets/mascot/character.glb")
    assert response.status_code == 404 and response.json()["detail"]["code"] == "mascot_not_available"
    assert str(tmp_path) not in response.text


@pytest.fixture
def world(tmp_path):
    database = Database(tmp_path / "companion.sqlite3")
    database.initialize()
    raw = sample_dataset()
    data = {
        "employees": {item["employee_id"]: item for item in raw["employees"]},
        "skills": {item["skill_id"]: item for item in raw["skills"]},
        "role_profiles": {role_key(item["role"], item["grade"]): item for item in raw["role_profiles"]},
        "events": {item["event_id"]: item for item in raw["events"]},
        "history": {item["record_id"]: item for item in raw["history"]},
    }
    return database, data["employees"]["E1"], data


def reward(conn, record_id="C1", employee_id="E1", event_id="EV_GOOD", gained=2, quest=False, earned_at=AS_OF, xp=None):
    conn.execute("INSERT INTO gamification_rewards VALUES (?,?,?,?,?,?,?,?)", (
        record_id, employee_id, event_id, event_id, xp or 20 + gained * 10, gained, int(quest), earned_at,
    ))


def item(state, item_id):
    return next(row for row in state["wardrobe"] if row["id"] == item_id)


def test_imported_history_affects_tree_but_never_retroactively_awards_clothing(world):
    database, employee, data = world
    with database.connection() as conn:
        before = conn.total_changes
        state = companion_view(conn, employee, data, AS_OF)
        assert conn.total_changes == before, "A GET projection must not mutate the database"
        assert state["enabled"] is False and state["xp"] == 0
        assert len(data["history"]) == 2
        assert state["tree"]["branches"][0]["current"] == 2
        assert {row["id"] for row in state["wardrobe"] if row["unlocked"]} == set(DEFAULT_EQUIPMENT.values())
        assert state["equipped"] == DEFAULT_EQUIPMENT
        assert all(row["earned_at"] is None for row in state["wardrobe"])


def test_actual_opted_in_completion_unlocks_only_earned_items(world):
    database, employee, data = world
    record = {"record_id": "APP1", "source": "application", "completed_at": AS_OF}
    changes = [{"skill_id": "SK_A", "before": 2, "after": 4}]
    with database.connection(write=True) as conn:
        assert not award_completion(conn, employee, data["events"]["EV_GOOD"], record, changes)["awarded"]
        set_enabled(conn, "E1", True)
        assert award_completion(conn, employee, data["events"]["EV_GOOD"], record, changes)["awarded"]
        state = companion_view(conn, employee, data, AS_OF)
        assert item(state, "cap_spark")["unlocked"]
        assert item(state, "accessory_notebook")["unlocked"]
        assert not item(state, "accessory_compass")["unlocked"]
        assert item(state, "cap_spark")["earned_at"] == AS_OF
        assert state["equipped"] == DEFAULT_EQUIPMENT, "Unlocking is not an automatic outfit change"
        assert not award_completion(conn, employee, data["events"]["EV_GOOD"], record, changes)["awarded"]
        assert companion_view(conn, employee, data, AS_OF) == state


def test_imported_no_gain_and_mandatory_records_do_not_unlock_clothing(world):
    database, employee, data = world
    with database.connection(write=True) as conn:
        set_enabled(conn, "E1", True)
        for index, (source, event_id, changes) in enumerate([
            ("import", "EV_GOOD", [{"before": 0, "after": 2}]),
            ("application", "EV_CAPPED", []),
            ("application", "EV_MAND", [{"before": 0, "after": 1}]),
        ]):
            record = {"record_id": f"IGNORED{index}", "source": source, "completed_at": AS_OF}
            assert not award_completion(conn, employee, data["events"][event_id], record, changes)["awarded"]
        assert not item(companion_view(conn, employee, data, AS_OF), "cap_spark")["unlocked"]


def test_three_distinct_rewarded_activities_ignore_repeated_sessions(world):
    database, employee, data = world
    with database.connection(write=True) as conn:
        for index in range(3):
            reward(conn, record_id=f"R{index}", event_id="EV_036", gained=1)
        state = companion_view(conn, employee, data, AS_OF)
        assert state["completed_count"] == 3
        assert item(state, "body_explorer")["requirement"]["current"] == 1
        assert not item(state, "body_explorer")["unlocked"]
        reward(conn, record_id="OTHER1", event_id="REMOVED_COURSE")
        reward(conn, record_id="OTHER2", event_id="REMOVED_MENTORING")
        assert item(companion_view(conn, employee, data, AS_OF), "body_explorer")["unlocked"]


def test_unlocks_survive_goal_assessment_catalog_and_opt_in_changes(world):
    database, employee, data = world
    with database.connection(write=True) as conn:
        reward(conn, gained=5, quest=True)
        original = companion_view(conn, employee, data, AS_OF)
        equip_item(conn, employee, data, AS_OF, "cap_quest")
        set_enabled(conn, "E1", False)
        changed = deepcopy(data)
        changed["employees"]["E1"].update(skills={"SK_A": 0}, last_review_date=AS_OF,
                                         career_goal={"target_role": "Engineer", "target_grade": "Junior"})
        changed["events"]["EV_GOOD"]["type"] = "meetup"
        current = companion_view(conn, changed["employees"]["E1"], changed, AS_OF)
        assert current["enabled"] is False and current["equipped"]["head"] == "cap_quest"
        assert {r["id"] for r in current["wardrobe"] if r["unlocked"]} == {r["id"] for r in original["wardrobe"] if r["unlocked"]}
        assert current["tree"]["goal"]["target_grade"] == "Junior"
        assert current["tree"]["branches"][0]["current"] == 0


def test_equipment_persists_is_private_and_can_be_reset_to_starter(world):
    database, employee, data = world
    with database.connection(write=True) as conn:
        reward(conn)
        chosen = equip_item(conn, employee, data, AS_OF, "cap_spark")
        assert chosen["equipped"]["head"] == "cap_spark"
        assert not item(chosen, "cap_starter")["equipped"]
        assert item(chosen, "cap_spark")["equipped"]
    restarted = Database(database.path)
    restarted.initialize()
    with restarted.connection(write=True) as conn:
        assert companion_view(conn, employee, data, AS_OF)["equipped"]["head"] == "cap_spark"
        other = companion_view(conn, data["employees"]["E2"], data, AS_OF)
        assert other["equipped"] == DEFAULT_EQUIPMENT
        assert other["xp"] == 0 and not item(other, "cap_spark")["unlocked"]
        assert equip_item(conn, employee, data, AS_OF, "cap_starter")["equipped"] == DEFAULT_EQUIPMENT


@pytest.mark.parametrize("item_id,status,code", [
    ("cap_quest", 409, "companion_item_locked"),
    ("invented_item", 404, "companion_item_not_found"),
])
def test_rejected_equipment_does_not_mutate_saved_outfit(world, item_id, status, code):
    database, employee, data = world
    with database.connection(write=True) as conn:
        before = companion_view(conn, employee, data, AS_OF)
        with pytest.raises(HTTPException) as exc:
            equip_item(conn, employee, data, AS_OF, item_id)
        assert exc.value.status_code == status and exc.value.detail["code"] == code
        assert companion_view(conn, employee, data, AS_OF) == before
        assert conn.execute("SELECT COUNT(*) FROM companion_equipment").fetchone()[0] == 0


def test_removed_or_mismatched_saved_item_falls_back_safely(world):
    database, employee, data = world
    with database.connection(write=True) as conn:
        conn.executemany("INSERT INTO companion_equipment VALUES ('E1',?,?)", [
            ("head", "removed_item"), ("body", "cap_starter"), ("background", "room_horizon"),
        ])
        assert companion_view(conn, employee, data, AS_OF)["equipped"] == DEFAULT_EQUIPMENT


def test_first_unlock_dates_use_when_the_threshold_was_crossed(world):
    database, employee, data = world
    with database.connection(write=True) as conn:
        reward(conn, "LATER", gained=3, earned_at="2026-09-30", quest=True)
        reward(conn, "EARLIER", gained=2, earned_at="2026-09-25")
        state = companion_view(conn, employee, data, AS_OF)
        assert item(state, "cap_spark")["earned_at"] == "2026-09-25"
        assert item(state, "accessory_compass")["earned_at"] == "2026-09-30"
        assert item(state, "cap_quest")["earned_at"] == "2026-09-30"


def test_next_unlock_is_locked_and_uses_real_ledger_progress(world):
    database, employee, data = world
    with database.connection(write=True) as conn:
        reward(conn, gained=1)
        state = companion_view(conn, employee, data, AS_OF)
        assert state["next_unlock"]["id"] == "accessory_notebook"
        assert state["next_unlock"]["requirement"]["current"] == 1
        reward(conn, "R2", event_id="OTHER", gained=2)
        reward(conn, "R3", event_id="THIRD", gained=2, quest=True, xp=100)
        assert companion_view(conn, employee, data, AS_OF)["next_unlock"] is None


def test_tree_shows_actual_gain_edges_only_and_handles_multi_level_courses(world):
    _, employee, data = world
    tree = skill_tree(employee, data, AS_OF)
    branch = next(row for row in tree["branches"] if row["skill_id"] == "SK_A")
    assert branch["current"] == 2 and branch["required"] == 4 and branch["critical"]
    assert [node["status"] for node in branch["nodes"]] == ["earned", "earned", "next", "locked", "locked"]
    assert branch["nodes"][0]["event_ids"] == []
    assert "EV_GOOD" in branch["nodes"][2]["event_ids"]
    assert "EV_GOOD" in branch["nodes"][3]["event_ids"]
    assert branch["nodes"][4]["event_ids"] == []
    event = next(row for row in branch["activities"] if row["event_id"] == "EV_GOOD")
    assert (event["before"], event["after"], event["gap_closed"]) == (2, 4, 2)
    assert event["coverage_after"] == 80 and tree["coverage_pct"] == 40
    allowed = {row["event_id"] for row in candidates(employee, data, AS_OF)[0]}
    linked = {event["event_id"] for row in tree["branches"] for event in row["activities"]}
    assert linked <= allowed
    assert not {"EV_PRE", "EV_CAPPED", "EV_MAND", "EV_AFTER"} & linked


def test_tree_applies_as_of_and_never_claims_future_imported_progress(world):
    _, employee, data = world
    before = skill_tree(employee, data, "2026-09-15")
    after = skill_tree(employee, data, AS_OF)
    assert before["branches"][0]["current"] == 1
    assert after["branches"][0]["current"] == 2
    assert before["coverage_pct"] == 20 and after["coverage_pct"] == 40


def test_tree_has_honest_no_goal_missing_profile_and_covered_states(world):
    _, employee, data = world
    no_goal = deepcopy(employee)
    no_goal.update(grade="Lead", career_goal=None)
    tree = skill_tree(no_goal, data, AS_OF)
    assert tree["goal"] is None and tree["empty_reason"] == "goal_not_set"
    assert all(row["required"] is None and not row["activities"] for row in tree["branches"])
    missing = deepcopy(data)
    missing["role_profiles"] = {}
    assert skill_tree(employee, missing, AS_OF)["empty_reason"] == "target_profile_missing"
    covered = deepcopy(employee)
    covered.update(skills={"SK_A": 5, "SK_B": 5}, last_review_date=AS_OF)
    full = skill_tree(covered, data, AS_OF)
    assert full["empty_reason"] == "goal_covered" and full["coverage_pct"] == 100
    assert all(not row["activities"] for row in full["branches"])


def test_tree_preserves_known_skills_outside_current_goal_without_inventing_requirement(world):
    _, employee, data = world
    data["role_profiles"]["Engineer|Senior"]["required_skills"] = {"SK_A": 4}
    employee["skills"]["SK_B"] = 3
    tree = skill_tree(employee, data, AS_OF)
    speaking = next(row for row in tree["branches"] if row["skill_id"] == "SK_B")
    assert speaking["current"] == 3 and speaking["required"] is None
    assert not speaking["critical"] and not speaking["activities"]


def test_companion_never_changes_existing_rewards_or_career_calculations(world):
    database, employee, data = world
    before = trajectory(employee, data, AS_OF)
    with database.connection(write=True) as conn:
        reward(conn)
        old = gamification_view(conn, employee, data, AS_OF)
        new = equip_item(conn, employee, data, AS_OF, "cap_spark")
        assert {key: new[key] for key in old} == old
        assert trajectory(employee, data, AS_OF) == before


def test_schema_upgrade_preserves_existing_reward_ledger(tmp_path):
    path = tmp_path / "old.sqlite3"
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA.split("CREATE TABLE IF NOT EXISTS companion_equipment")[0])
        reward(conn)
        conn.execute("INSERT INTO gamification_preferences(employee_id,enabled) VALUES ('E1',1)")
    database = Database(path)
    database.initialize()
    database.initialize()
    with database.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM companion_equipment").fetchone()[0] == 0
        assert conn.execute("SELECT xp FROM gamification_rewards WHERE record_id='C1'").fetchone()[0] == 40
        assert conn.execute("SELECT enabled FROM gamification_preferences WHERE employee_id='E1'").fetchone()[0] == 1
