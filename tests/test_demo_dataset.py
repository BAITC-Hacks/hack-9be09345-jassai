"""The shipped fictional files must support the jury's offline development walkthrough."""

from pathlib import Path
import secrets

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.conftest import login, upload


DEMO_DIR = Path(__file__).resolve().parents[1] / "demo"


def test_shipped_demo_import_progress_quest_and_idempotent_reward(tmp_path):
    files = {
        name: (DEMO_DIR / name).read_bytes()
        for name in ("employees.json", "events.json", "skills.json", "activity_history.csv")
    }
    password = secrets.token_urlsafe(24)
    settings = Settings(data_dir=tmp_path, bootstrap_token=secrets.token_urlsafe(24), testing=True)
    with TestClient(create_app(settings)) as client:
        setup = client.post("/api/setup", json={
            "token": settings.bootstrap_token, "username": "demo-hr-check", "password": password,
        })
        assert setup.status_code == 201, setup.text
        login(client, "demo-hr-check", password)
        validation = upload(client, files)
        assert validation.status_code == 200, validation.text
        report = validation.json()
        assert report["valid"], report["errors"]
        assert report["as_of_date"] == "2026-10-01"
        assert report["counts"]["employees"]["added"] == 3
        assert report["counts"]["events"]["added"] == 8
        applied = client.post("/api/hr/import/apply", json={"batch_id": report["batch_id"]})
        assert applied.status_code == 200, applied.text
        overview = client.get("/api/hr/overview").json()
        assert overview["employee_count"] == 3
        assert any(row["employee_id"] == "DEMO_E003" and row["goal"] is None for row in overview["employees_without_step"])

        created = client.post("/api/hr/users", json={
            "username": "demo-employee-check", "password": password, "employee_id": "DEMO_E001",
        })
        assert created.status_code == 201, created.text
        login(client, "demo-employee-check", password)
        profile = client.get("/api/me").json()
        assert profile["trajectory"]["effective_skills"]["DEMO_ARCH"] == 2  # History after review counts.
        assert profile["trajectory"]["effective_skills"]["DEMO_SQL"] == 1  # History before review is already included.
        assert profile["trajectory"]["coverage_pct"] == 55.56
        assert {event["event_id"] for event in profile["available_steps"]} == {
            "DEMO_EV_DESIGN", "DEMO_EV_PRESENT", "DEMO_EV_FUTURE",
        }
        game = client.get("/api/me/gamification").json()
        assert game["enabled"] is False and game["xp"] == 0
        assert client.patch("/api/me/gamification", json={"enabled": True}).status_code == 200
        assert client.post("/api/me/gamification/quest", json={"event_id": "DEMO_EV_DESIGN"}).status_code == 200

        started = client.post("/api/me/activities/DEMO_EV_DESIGN/start", json={})
        assert started.status_code == 200, started.text
        body = {"activity_record_id": started.json()["record"]["record_id"]}
        headers = {"Idempotency-Key": "demo-completion-once"}
        path = "/api/me/activities/DEMO_EV_DESIGN/complete"
        completed = client.post(path, json=body, headers=headers)
        assert completed.status_code == 200, completed.text
        result = completed.json()
        assert result["changes"] == [{"skill_id": "DEMO_ARCH", "before": 2, "after": 4}]
        assert result["profile"]["trajectory"]["coverage_pct"] == 77.78
        assert result["profile"]["trajectory"]["critical_gaps"] == []
        assert "DEMO_EV_RELIABILITY" in {event["event_id"] for event in result["profile"]["available_steps"]}
        assert result["reward"] == {"awarded": True, "xp": 40, "gained_levels": 2, "reason": "awarded"}
        assert result["gamification"]["quest"]["status"] == "completed"
        assert {badge["id"] for badge in result["gamification"]["badges"] if badge["earned"]} == {"first_step", "personal_quest"}

        assert client.post(path, json=body, headers=headers).json() == result
        assert client.post(path, json=body, headers={"Idempotency-Key": "demo-other-key"}).status_code == 409
        final_game = client.get("/api/me/gamification").json()
        assert final_game["xp"] == 40 and final_game["completed_count"] == 1
