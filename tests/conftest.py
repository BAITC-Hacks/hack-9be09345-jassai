from copy import deepcopy
import csv
import io
import json

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def sample_dataset():
    # Independent synthetic fixtures, not redistributed organizer data.
    employee = {
        "employee_id": "E1", "full_name": "Test Employee", "department": "Engineering",
        "role": "Engineer", "grade": "Middle", "manager_id": None,
        "hire_date": "2024-01-01", "tenure_months": 33, "work_format": "remote", "preferred_language": "ru",
        "career_goal": {"target_role": "Engineer", "target_grade": "Senior"},
        "skills": {"SK_A": 1}, "last_review_date": "2026-09-10",
    }
    other = deepcopy(employee)
    other.update(employee_id="E2", full_name="Other Employee", career_goal=None)
    skills = [{"skill_id": sid, "name": name, "type": typ, "category": "test", "description": name} for sid, name, typ in [("SK_A", "Architecture", "hard"), ("SK_B", "Speaking", "soft")]]
    roles = [{"role": "Engineer", "grade": grade, "required_skills": {"SK_A": level, "SK_B": 1}, "critical_skills": ["SK_A"]} for grade, level in [("Junior", 1), ("Middle", 2), ("Senior", 4), ("Lead", 5)]]

    def event(eid, skill="SK_A", gain=2, cap=4, **changes):
        return {
            "event_id": eid, "title": eid, "description": "Test activity", "type": "course", "format": "self_paced",
            "duration_hours": 2, "mandatory": False, "target_roles": ["Engineer"], "target_grades": ["Middle", "Senior", "Lead"],
            "develops_skills": [{"skill_id": skill, "gain": gain, "max_level": cap}], "prerequisites": {}, "upcoming_sessions": [], **changes,
        }

    events = [
        event("EV_GOOD"), event("EV_BEFORE", gain=3), event("EV_AFTER", gain=1),
        event("EV_CAPPED", cap=1), event("EV_PRE", prerequisites={"SK_A": 5}),
        event("EV_MAND", mandatory=True, develops_skills=[], type="compliance"),
        event("EV_FUTURE", "SK_B", format="online", upcoming_sessions=["2026-10-10"]),
        event("EV_036", "SK_B", gain=1, cap=5, format="online", type="meetup", upcoming_sessions=["2026-09-30", "2026-10-01", "2026-10-02"]),
    ]
    history = [
        {"record_id": rid, "employee_id": "E1", "event_id": eid, "date": day, "due_date": None, "status": "completed", "completion_pct": 100, "score": None, "feedback_rating": None, "assigned_by": "self"}
        for rid, eid, day in [("R1", "EV_BEFORE", "2026-09-01"), ("R2", "EV_AFTER", "2026-09-20")]
    ]
    return {"employees": [employee, other], "skills": skills, "role_profiles": roles, "events": events, "history": history}


def dataset_files(data, names=None):
    meta = {"dataset": "Independent test fixture", "version": "1.0", "as_of_date": "2026-10-01"}
    payloads = {
        "employees.json": json.dumps({"meta": meta, "employees": data["employees"]}).encode(),
        "events.json": json.dumps({"meta": meta, "events": data["events"]}).encode(),
        "skills.json": json.dumps({"meta": meta, "skills": data["skills"], "role_profiles": data["role_profiles"], "proficiency_scale": {}}).encode(),
    }
    text = io.StringIO(newline="")
    writer = csv.DictWriter(text, fieldnames=["record_id", "employee_id", "event_id", "date", "due_date", "status", "completion_pct", "score", "feedback_rating", "assigned_by"])
    writer.writeheader()
    writer.writerows(data["history"])
    payloads["activity_history.csv"] = text.getvalue().encode()
    return {k: v for k, v in payloads.items() if names is None or k in names}


def upload(client, payloads, mode="add"):
    return client.post("/api/hr/import/validate", data={"mode": mode}, files=[("files", (name, raw)) for name, raw in payloads.items()])


def login(client, username="hr", password="test-password-123"):
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    return response


@pytest.fixture
def stack(tmp_path):
    settings = Settings(data_dir=tmp_path / "Кириллица и пробелы", bootstrap_token="test-bootstrap-secret", testing=True)
    app = create_app(settings)
    with TestClient(app) as hr:
        response = hr.post("/api/setup", json={"token": settings.bootstrap_token, "username": "hr", "password": "test-password-123"})
        assert response.status_code == 201, response.text
        login(hr)
        data = sample_dataset()
        report = upload(hr, dataset_files(data)).json()
        assert report["valid"], report
        applied = hr.post("/api/hr/import/apply", json={"batch_id": report["batch_id"]})
        assert applied.status_code == 200, applied.text
        for username, employee_id in [("one", "E1"), ("two", "E2")]:
            response = hr.post("/api/hr/users", json={"username": username, "password": "test-password-123", "employee_id": employee_id})
            assert response.status_code == 201, response.text
        employee = TestClient(app)
        login(employee, "one")
        try:
            yield app, hr, employee, data, settings
        finally:
            employee.close()
