"""Bundled synthetic data is a first-run convenience, never a replacement import."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import csv
import io
import json
from pathlib import Path
import shutil
from threading import Barrier

from fastapi.testclient import TestClient
import pytest

from app.config import Settings
from app.db import Database, bump_revision, get_meta, put_entity, revision, set_meta, snapshot
from app.imports import validate_files
from app.main import create_app
from app.seed import seed_dataset
from tests.conftest import login, upload


BUNDLE = Path(__file__).resolve().parents[1] / "starter-data"
FILENAMES = ("employees.json", "events.json", "skills.json", "activity_history.csv")
COUNTS = {"employees": 200, "skills": 60, "events": 40, "role_profiles": 32, "history": 2743}


@pytest.fixture
def empty_database(tmp_path):
    database = Database(tmp_path / "empty.sqlite3")
    database.initialize()
    return database


def database_state(database):
    with database.connection() as conn:
        return {
            "entities": snapshot(conn),
            "meta": dict(conn.execute("SELECT key,value FROM meta").fetchall()),
            "recommendation_cache": [tuple(row) for row in conn.execute("SELECT * FROM recommendation_cache ORDER BY context_hash")],
        }


def copy_bundle(destination):
    destination.mkdir()
    for filename in FILENAMES:
        shutil.copyfile(BUNDLE / filename, destination / filename)
    return destination


def assert_empty_dataset(database):
    with database.connection() as conn:
        assert all(not values for values in snapshot(conn).values())
        assert get_meta(conn, "as_of_date") is None
        assert revision(conn) == 0


def test_bundled_files_pass_the_existing_importer_without_schema_exceptions(empty_database):
    files = {filename: (BUNDLE / filename).read_bytes() for filename in FILENAMES}
    with empty_database.connection() as conn:
        report, incoming = validate_files(conn, files, "add")
        assert report["valid"], report["errors"]
        assert {kind: len(rows) for kind, rows in incoming.items()} == COUNTS
        assert report["as_of_date"]
    assert_empty_dataset(empty_database)


def test_fresh_database_gets_all_bundled_entities_once(empty_database):
    assert seed_dataset(empty_database, BUNDLE) is True
    with empty_database.connection() as conn:
        data = snapshot(conn)
        assert {kind: len(rows) for kind, rows in data.items()} == COUNTS
        assert get_meta(conn, "as_of_date")
        assert revision(conn) == 1
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM gamification_rewards").fetchone()[0] == 0
        assert all("source" not in row or row["source"] != "application" for row in data["history"].values())


def test_seed_repeat_is_read_only_and_preserves_revision_and_cached_results(empty_database):
    assert seed_dataset(empty_database, BUNDLE) is True
    with empty_database.connection(write=True) as conn:
        conn.execute("INSERT INTO recommendation_cache VALUES (?,?)", ("existing-cache", '{"cached":"keep"}'))
    before = database_state(empty_database)
    assert seed_dataset(empty_database, BUNDLE) is False
    assert seed_dataset(empty_database, BUNDLE) is False
    assert database_state(empty_database) == before


def test_two_concurrent_first_startups_import_exactly_once(empty_database):
    ready = Barrier(2)
    def start(_):
        ready.wait(timeout=5)
        return seed_dataset(empty_database, BUNDLE)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(start, range(2)))
    assert sorted(results) == [False, True]
    with empty_database.connection() as conn:
        assert revision(conn) == 1
        assert {kind: len(rows) for kind, rows in snapshot(conn).items()} == COUNTS


@pytest.mark.parametrize("marker", ["entities", "as_of_date"])
def test_existing_partial_dataset_is_preserved_even_if_seed_bundle_is_missing(empty_database, tmp_path, marker):
    with empty_database.connection(write=True) as conn:
        if marker == "entities":
            put_entity(conn, "skills", "EXISTING_USER_SKILL", {"skill_id": "EXISTING_USER_SKILL", "name": "Keep existing data"})
        else:
            set_meta(conn, "as_of_date", "2025-01-01")
        set_meta(conn, "revision", 7)
    before = database_state(empty_database)
    assert seed_dataset(empty_database, tmp_path / "missing-seed-directory") is False
    assert database_state(empty_database) == before


def test_existing_complete_data_is_preserved_without_overwriting_corrections(empty_database):
    assert seed_dataset(empty_database, BUNDLE) is True
    with empty_database.connection(write=True) as conn:
        data = snapshot(conn)
        employee = deepcopy(next(iter(data["employees"].values())))
        employee["full_name"] = "Изменено пользователем после импорта"
        put_entity(conn, "employees", employee["employee_id"], employee)
        set_meta(conn, "revision", 9)
    before = database_state(empty_database)
    assert seed_dataset(empty_database, BUNDLE) is False
    assert database_state(empty_database) == before


def test_missing_seed_directory_raises_without_partial_dataset(empty_database, tmp_path):
    with pytest.raises(RuntimeError):
        seed_dataset(empty_database, tmp_path / "missing-seed-directory")
    assert_empty_dataset(empty_database)


@pytest.mark.parametrize("filename", FILENAMES)
def test_missing_bundle_member_raises_without_partial_dataset(empty_database, tmp_path, filename):
    bundle = copy_bundle(tmp_path / "incomplete")
    (bundle / filename).unlink()
    with pytest.raises(RuntimeError):
        seed_dataset(empty_database, bundle)
    assert_empty_dataset(empty_database)


@pytest.mark.parametrize("damage", ["invalid_json", "unknown_employee_skill", "inconsistent_date", "invalid_history_reference"])
def test_invalid_bundle_raises_without_partial_dataset(empty_database, tmp_path, damage):
    bundle = copy_bundle(tmp_path / "invalid")
    if damage == "invalid_json":
        (bundle / "events.json").write_text("{not-json", encoding="utf-8")
    elif damage == "unknown_employee_skill":
        document = json.loads((bundle / "employees.json").read_text(encoding="utf-8-sig"))
        document["employees"][0]["skills"]["MISSING_SEED_SKILL"] = 2
        (bundle / "employees.json").write_text(json.dumps(document), encoding="utf-8")
    elif damage == "inconsistent_date":
        document = json.loads((bundle / "events.json").read_text(encoding="utf-8-sig"))
        document["meta"]["as_of_date"] = "2020-01-01"
        (bundle / "events.json").write_text(json.dumps(document), encoding="utf-8")
    else:
        with (bundle / "activity_history.csv").open(encoding="utf-8-sig", newline="") as source:
            reader = csv.DictReader(source)
            columns, rows = reader.fieldnames, list(reader)
        rows[0]["event_id"] = "MISSING_SEED_EVENT"
        with (bundle / "activity_history.csv").open("w", encoding="utf-8", newline="") as target:
            writer = csv.DictWriter(target, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)
    with pytest.raises(RuntimeError):
        seed_dataset(empty_database, bundle)
    assert_empty_dataset(empty_database)


def test_environment_default_seed_path_and_explicit_disable(monkeypatch, tmp_path):
    monkeypatch.setenv("CAREERQUEST_DATA_DIR", str(tmp_path / "runtime"))
    monkeypatch.delenv("CAREERQUEST_SEED_DATA_DIR", raising=False)
    assert Settings.from_env().seed_data_dir == BUNDLE
    monkeypatch.setenv("CAREERQUEST_SEED_DATA_DIR", "off")
    assert Settings.from_env().seed_data_dir is None
    custom = tmp_path / "custom-starter"
    monkeypatch.setenv("CAREERQUEST_SEED_DATA_DIR", str(custom))
    assert Settings.from_env().seed_data_dir == custom.resolve()


def test_explicitly_disabled_seed_keeps_manual_initial_import_available(tmp_path):
    settings = Settings(data_dir=tmp_path / "disabled", bootstrap_token="test-seed-bootstrap", seed_data_dir=None, testing=True)
    app = create_app(settings)
    with TestClient(app) as client:
        ready = client.get("/ready").json()
        assert ready["setup_required"] and not ready["dataset_loaded"]
        with app.state.db.connection() as conn:
            assert all(not rows for rows in snapshot(conn).values())


def test_seeded_startup_retains_authenticated_add_employee_and_history_import(tmp_path):
    settings = Settings(data_dir=tmp_path / "seeded", bootstrap_token="test-seed-bootstrap", seed_data_dir=BUNDLE, testing=True)
    app = create_app(settings)
    with TestClient(app) as hr:
        ready = hr.get("/ready").json()
        assert ready["setup_required"] and ready["dataset_loaded"]
        assert hr.get("/api/catalog").status_code == 401
        response = hr.post("/api/setup", json={"token": settings.bootstrap_token, "username": "hr", "password": "test-password-123"})
        assert response.status_code == 201, response.text
        login(hr)
        with app.state.db.connection() as conn:
            baseline = snapshot(conn)
            as_of = get_meta(conn, "as_of_date")
        employee = deepcopy(next(iter(baseline["employees"].values())))
        employee.update(employee_id="SEED_TEST_NEW_EMPLOYEE", full_name="Новый синтетический сотрудник", manager_id=None)
        record = deepcopy(next(iter(baseline["history"].values())))
        record.update(record_id="SEED_TEST_NEW_HISTORY", employee_id=employee["employee_id"])
        text = io.StringIO(newline="")
        writer = csv.DictWriter(text, fieldnames=list(record))
        writer.writeheader()
        writer.writerow(record)
        payloads = {
            "employees.json": json.dumps({"meta": {"as_of_date": as_of}, "employees": [employee]}).encode(),
            "activity_history.csv": text.getvalue().encode(),
        }
        validation = upload(hr, payloads)
        assert validation.status_code == 200, validation.text
        report = validation.json()
        assert report["valid"], report["errors"]
        assert report["counts"]["employees"]["added"] == 1
        assert report["counts"]["history"]["added"] == 1
        applied = hr.post("/api/hr/import/apply", json={"batch_id": report["batch_id"]})
        assert applied.status_code == 200, applied.text
        listed = hr.get("/api/hr/employees").json()["employees"]
        assert len(listed) == COUNTS["employees"] + 1
        profile = hr.get("/api/hr/employees/" + employee["employee_id"])
        assert profile.status_code == 200, profile.text
        assert profile.json()["history"][0]["record_id"] == record["record_id"]
        with app.state.db.connection() as conn:
            after = snapshot(conn)
            assert len(after["history"]) == COUNTS["history"] + 1
            assert all(after[kind][key] == item for kind, rows in baseline.items() for key, item in rows.items())
        assert seed_dataset(app.state.db, BUNDLE) is False
    with TestClient(create_app(settings)) as restarted:
        login(restarted)
        assert len(restarted.get("/api/hr/employees").json()["employees"]) == COUNTS["employees"] + 1
        profile = restarted.get("/api/hr/employees/" + employee["employee_id"]).json()
        assert profile["history"][0]["record_id"] == record["record_id"]


@pytest.fixture
def starter_admin(tmp_path):
    settings = Settings(data_dir=tmp_path / "manual-starter", bootstrap_token="test-seed-bootstrap", seed_data_dir=None, testing=True)
    app = create_app(settings)
    with TestClient(app) as hr:
        response = hr.post("/api/setup", json={"token": settings.bootstrap_token, "username": "hr", "password": "test-password-123"})
        assert response.status_code == 201, response.text
        login(hr)
        yield app, hr


def test_starter_import_endpoint_requires_hr_session_and_csrf(stack):
    app, hr, employee, _, _ = stack
    path = "/api/hr/import/starter"
    assert employee.post(path).status_code == 403
    with TestClient(app) as anonymous:
        assert anonymous.post(path).status_code == 401
    csrf = hr.headers.pop("X-CSRF-Token")
    try:
        assert hr.post(path).status_code == 403
    finally:
        hr.headers["X-CSRF-Token"] = csrf


def test_starter_endpoint_previews_then_applies_idempotently(starter_admin):
    app, hr = starter_admin
    before = database_state(app.state.db)
    response = hr.post("/api/hr/import/starter")
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["valid"] and report["batch_id"]
    assert {kind: counts["added"] for kind, counts in report["counts"].items()} == COUNTS
    assert database_state(app.state.db) == before, "Preview must not write entities, the dataset date or revision"
    another = hr.post("/api/hr/import/starter").json()
    assert another["batch_id"] != report["batch_id"]
    assert database_state(app.state.db) == before
    first = hr.post("/api/hr/import/apply", json={"batch_id": report["batch_id"]})
    assert first.status_code == 200 and first.json()["already_applied"] is False
    imported = database_state(app.state.db)
    assert {kind: len(rows) for kind, rows in imported["entities"].items()} == COUNTS
    repeated = hr.post("/api/hr/import/apply", json={"batch_id": report["batch_id"]})
    assert repeated.status_code == 200 and repeated.json()["already_applied"] is True
    assert database_state(app.state.db) == imported
    fresh = hr.post("/api/hr/import/starter").json()
    assert fresh["valid"]
    assert {kind: counts["skipped"] for kind, counts in fresh["counts"].items()} == COUNTS
    assert all(counts["added"] == counts["updated"] == 0 for counts in fresh["counts"].values())
    assert hr.post("/api/hr/import/apply", json={"batch_id": fresh["batch_id"]}).status_code == 200
    assert database_state(app.state.db) == imported


def test_starter_endpoint_reports_conflicts_without_overwriting_or_creating_batch(starter_admin):
    app, hr = starter_admin
    assert seed_dataset(app.state.db, BUNDLE)
    with app.state.db.connection(write=True) as conn:
        employee = deepcopy(next(iter(snapshot(conn)["employees"].values())))
        employee["full_name"] = "Сохранить ручное изменение"
        put_entity(conn, "employees", employee["employee_id"], employee)
        bump_revision(conn)
        previous_batches = conn.execute("SELECT COUNT(*) FROM import_batches").fetchone()[0]
    before = database_state(app.state.db)
    response = hr.post("/api/hr/import/starter")
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["valid"] is False and "batch_id" not in report
    assert any("Conflicting existing ID" in error["message"] for error in report["errors"])
    assert database_state(app.state.db) == before
    with app.state.db.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM import_batches").fetchone()[0] == previous_batches


def test_starter_endpoint_missing_bundle_is_controlled_and_writes_nothing(starter_admin, monkeypatch, tmp_path):
    app, hr = starter_admin
    monkeypatch.setattr("app.main.BUNDLED_DATA_DIR", tmp_path / "missing-bundle")
    before = database_state(app.state.db)
    response = hr.post("/api/hr/import/starter")
    assert response.status_code == 503
    assert response.json()["detail"] == {"code": "starter_data_unavailable"}
    assert database_state(app.state.db) == before


def test_starter_batch_is_owned_by_the_validating_hr(starter_admin):
    app, hr = starter_admin
    report = hr.post("/api/hr/import/starter").json()
    created = hr.post("/api/hr/users", json={"username": "other-hr", "password": "test-password-123", "role": "hr"})
    assert created.status_code == 201, created.text
    before = database_state(app.state.db)
    with TestClient(app) as other:
        login(other, "other-hr")
        response = other.post("/api/hr/import/apply", json={"batch_id": report["batch_id"]})
        assert response.status_code == 404
    assert database_state(app.state.db) == before


def test_starter_batch_becomes_stale_after_another_import(starter_admin):
    app, hr = starter_admin
    report = hr.post("/api/hr/import/starter").json()
    assert seed_dataset(app.state.db, BUNDLE)
    before = database_state(app.state.db)
    response = hr.post("/api/hr/import/apply", json={"batch_id": report["batch_id"]})
    assert response.status_code == 409 and response.json()["detail"]["code"] == "stale_import"
    assert database_state(app.state.db) == before
