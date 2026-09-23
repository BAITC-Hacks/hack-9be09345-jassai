"""Functional smoke check of a locally supplied dataset, using a disposable DB.

Does not copy the organizer dataset into the repository and does not call an LLM.
Run: uv run python scripts/check_dataset.py <path-to-career_quest_dataset>
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import secrets
import sys
import tempfile
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app


def checked(response, status=200):
    if response.status_code != status:
        raise RuntimeError(f"HTTP {response.status_code}: {response.text[:1000]}")
    return response.json()


def run(dataset):
    files = {name: (dataset / name).read_bytes() for name in ["employees.json", "events.json", "skills.json", "activity_history.csv"]}
    password = secrets.token_urlsafe(20)
    token = secrets.token_urlsafe(32)
    result = {}
    with tempfile.TemporaryDirectory(prefix="careerquest-smoke-") as temp:
        settings = Settings(Path(temp) / "Проверка с пробелами", bootstrap_token=token, testing=True)
        app = create_app(settings)
        with TestClient(app) as client:
            checked(client.post("/api/setup", json={"token": token, "username": "smoke_hr", "password": password}), 201)
            session = checked(client.post("/api/auth/login", json={"username": "smoke_hr", "password": password}))
            client.headers["X-CSRF-Token"] = session["csrf_token"]
            report = checked(client.post("/api/hr/import/validate", files=[("files", (name, content)) for name, content in files.items()]))
            if not report["valid"]:
                raise RuntimeError(json.dumps(report["errors"], ensure_ascii=False))
            checked(client.post("/api/hr/import/apply", json={"batch_id": report["batch_id"]}))
            result["import_counts"] = report["counts"]
            started = perf_counter()
            overview = checked(client.get("/api/hr/overview"))
            result["hr_seconds"] = round(perf_counter() - started, 4)
            result["employee_count"] = overview["employee_count"]
            result["employees_without_step"] = len(overview["employees_without_step"])
            result["history_records"] = sum(row["records"] for row in overview["participation"])

            employees_document = json.loads(files["employees.json"])
            # Pick a profile with a genuinely available self-paced step, without weakening rules.
            # Carry its effective levels into a new same-day assessment for the jury-like fixture.
            selected = None
            for source in employees_document["employees"]:
                view = checked(client.get(f"/api/hr/employees/{source['employee_id']}"))
                if any(e["format"] == "self_paced" for e in view["available_steps"]):
                    selected = view
                    break
            if selected is None:
                raise RuntimeError("No source profile has an eligible self-paced step")
            jury = deepcopy(selected["employee"])
            jury.update(employee_id="JURY_SMOKE", manager_id=None, skills=selected["trajectory"]["effective_skills"], last_review_date=selected["as_of_date"])
            new_profile = json.dumps({"meta": employees_document["meta"], "employees": [jury]}).encode()
            report = checked(client.post("/api/hr/import/validate", files=[("files", ("employees.json", new_profile))]))
            if not report["valid"]:
                raise RuntimeError(json.dumps(report["errors"]))
            checked(client.post("/api/hr/import/apply", json={"batch_id": report["batch_id"]}))
            checked(client.post("/api/hr/users", json={"username": "smoke_employee", "password": password, "employee_id": "JURY_SMOKE"}), 201)
            session = checked(client.post("/api/auth/login", json={"username": "smoke_employee", "password": password}))
            client.headers["X-CSRF-Token"] = session["csrf_token"]
            started = perf_counter()
            profile = checked(client.get("/api/me"))
            result["profile_seconds"] = round(perf_counter() - started, 4)
            event = next((e for e in profile["available_steps"] if e["format"] == "self_paced"), None)
            if event is None:
                raise RuntimeError("Smoke profile has no self-paced candidate; select another fixture")
            url = f"/api/me/activities/{event['event_id']}/complete"
            completion = checked(client.post(url, json={}, headers={"Idempotency-Key": "smoke-complete"}))
            duplicate = checked(client.post(url, json={}, headers={"Idempotency-Key": "smoke-complete"}))
            assert completion == duplicate
            assert completion["changes"]
            assert client.get("/api/hr/overview").status_code == 403
            expected_skills = completion["profile"]["trajectory"]["effective_skills"]
            result["jury_import"] = "passed"
            result["completion_and_idempotency"] = "passed"
            result["role_check"] = "passed"
        with TestClient(create_app(settings)) as restarted:
            session = checked(restarted.post("/api/auth/login", json={"username": "smoke_employee", "password": password}))
            restarted.headers["X-CSRF-Token"] = session["csrf_token"]
            assert checked(restarted.get("/api/me"))["trajectory"]["effective_skills"] == expected_skills
            assert restarted.post("/api/me/recommendations").status_code == 503
            result["restart_persistence"] = "passed"
            result["real_ai_tested"] = False
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    args = parser.parse_args()
    print(json.dumps(run(args.dataset), ensure_ascii=False, indent=2))
