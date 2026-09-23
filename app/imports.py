"""Dataset parsing, whole-batch validation, and transactional application."""
import csv
from datetime import date
import io
import json

from pydantic import ValidationError

from app.db import all_entities, bump_revision, get_meta, put_entity, set_meta, snapshot
from app.domain import REPEATABLE_EVENTS, role_key
from app.models import Employee, Event, History, RoleProfile, Skill

FILE_KINDS = {
    "employees.json": [("employees", Employee, "employee_id")],
    "events.json": [("events", Event, "event_id")],
    "skills.json": [("skills", Skill, "skill_id"), ("role_profiles", RoleProfile, None)],
}
HISTORY_COLUMNS = list(History.model_fields)
MAX_FILE_BYTES = 8 * 1024 * 1024


def validate_files(conn, files, mode="add"):
    errors = []
    incoming = {k: {} for k in ("employees", "events", "skills", "role_profiles", "history")}
    locations = {}
    current = snapshot(conn)
    existing_as_of = get_meta(conn, "as_of_date")
    as_of = existing_as_of

    def error(file, row, field, message):
        if len(errors) < 100:
            errors.append({"file": file, "row": row, "field": field, "message": message})

    if not current["skills"] and not (set(FILE_KINDS) | {"activity_history.csv"}) <= files.keys():
        error("batch", None, "files", "Initial import requires employees.json, events.json, skills.json and activity_history.csv")
    if not files:
        error("batch", None, "files", "No files supplied")

    def parse_record(kind, model, id_field, raw, file, index):
        try:
            item = model.model_validate(raw).model_dump(mode="json")
        except ValidationError as exc:
            for detail in exc.errors():
                error(file, index, ".".join(str(x) for x in detail["loc"]), detail["msg"])
            return
        eid = item[id_field] if id_field else role_key(item["role"], item["grade"])
        if eid in incoming[kind]:
            error(file, index, id_field or "role,grade", f"Duplicate identifier: {eid}")
            return
        incoming[kind][eid] = item
        locations[(kind, eid)] = (file, index)

    for filename, raw in files.items():
        if filename not in FILE_KINDS and filename != "activity_history.csv":
            error(filename, None, "filename", "Unsupported filename")
            continue
        if len(raw) > MAX_FILE_BYTES:
            error(filename, None, "size", "File exceeds 8 MiB")
            continue
        try:
            content = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            error(filename, None, "encoding", "Expected UTF-8")
            continue
        if filename == "activity_history.csv":
            reader = csv.DictReader(io.StringIO(content, newline=""))
            if not reader.fieldnames or set(reader.fieldnames) != set(HISTORY_COLUMNS) or len(reader.fieldnames) != len(HISTORY_COLUMNS):
                error(filename, 1, "header", "CSV columns must match the dataset schema")
                continue
            try:
                for index, row in enumerate(reader, 2):
                    if index > 100_001:
                        error(filename, index, "rows", "Too many records")
                        break
                    try:
                        for field in ("completion_pct", "score", "feedback_rating"):
                            row[field] = int(row[field]) if row.get(field) else None
                        row["due_date"] = row.get("due_date") or None
                    except (ValueError, TypeError):
                        error(filename, index, "numeric", "Invalid integer")
                        continue
                    parse_record("history", History, "record_id", row, filename, index)
            except csv.Error as exc:
                error(filename, None, "csv", str(exc))
            continue
        try:
            document = json.loads(content)
            if not isinstance(document, dict):
                raise ValueError("Expected dataset object with meta and named arrays")
            file_as_of = date.fromisoformat(document["meta"]["as_of_date"]).isoformat()
            if as_of is not None and as_of != file_as_of:
                raise ValueError("as_of_date must match other files and the existing dataset")
            as_of = file_as_of
            for kind, model, id_field in FILE_KINDS[filename]:
                rows = document[kind]
                if not isinstance(rows, list) or len(rows) > 100_000:
                    raise ValueError(f"{kind} must be an array of at most 100000 records")
                for index, row in enumerate(rows, 1):
                    parse_record(kind, model, id_field, row, filename, index)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            error(filename, None, "document", str(exc))

    if as_of is None:
        error("batch", None, "meta.as_of_date", "Missing dataset date")
    report = {k: {"added": 0, "updated": 0, "skipped": 0} for k in incoming}
    merged = {kind: dict(items) for kind, items in current.items()}
    for kind, records in incoming.items():
        for eid, item in records.items():
            old = current[kind].get(eid)
            if old == item:
                report[kind]["skipped"] += 1
            elif old is not None:
                if mode != "update":
                    file, index = locations[(kind, eid)]
                    error(file, index, "id", f"Conflicting existing ID {eid}; select update mode explicitly")
                report[kind]["updated"] += 1
            else:
                report[kind]["added"] += 1
            merged[kind][eid] = item

    def issue(kind, eid, field, message):
        file, index = locations.get((kind, eid), (f"existing:{kind}", eid))
        error(file, index, field, message)

    def skill_refs(kind, eid, refs):
        unknown = set(refs) - merged["skills"].keys()
        if unknown:
            issue(kind, eid, "skills", f"Unknown skill IDs: {', '.join(sorted(unknown))}")

    for eid, item in merged["role_profiles"].items():
        skill_refs("role_profiles", eid, item["required_skills"])
    roles = {x["role"] for x in merged["role_profiles"].values()}
    for eid, item in merged["employees"].items():
        skill_refs("employees", eid, item["skills"])
        if role_key(item["role"], item["grade"]) not in merged["role_profiles"]:
            issue("employees", eid, "role,grade", "Unknown role/grade")
        if item["manager_id"] is not None and item["manager_id"] not in merged["employees"]:
            issue("employees", eid, "manager_id", "Unknown manager")
        if item["manager_id"] == eid:
            issue("employees", eid, "manager_id", "Employee cannot manage themselves")
        goal = item["career_goal"]
        if goal and role_key(goal["target_role"], goal["target_grade"]) not in merged["role_profiles"]:
            issue("employees", eid, "career_goal", "Unknown target role/grade")
        if as_of and (item["hire_date"] > as_of or item["last_review_date"] > as_of):
            issue("employees", eid, "date", "Profile dates cannot exceed as_of_date")
    for eid, item in merged["events"].items():
        skill_refs("events", eid, list(item["prerequisites"]) + [x["skill_id"] for x in item["develops_skills"]])
        if not set(item["target_roles"]) <= roles:
            issue("events", eid, "target_roles", "Unknown target role")
    completions = set()
    for eid, item in merged["history"].items():
        if item["employee_id"] not in merged["employees"]:
            issue("history", eid, "employee_id", "Unknown employee")
        event = merged["events"].get(item["event_id"])
        if event is None:
            issue("history", eid, "event_id", "Unknown event")
        if as_of and item["date"] > as_of and item.get("source") != "application":
            issue("history", eid, "date", "Imported history cannot exceed as_of_date")
        if item["status"] == "no_show" and event and event["format"] == "self_paced":
            issue("history", eid, "status", "Self-paced event cannot have no_show status")
        if item["due_date"] and event and not event["mandatory"]:
            issue("history", eid, "due_date", "due_date is only valid for mandatory events")
        if item["status"] == "completed":
            # The supplied history contains recurring annual mandatory compliance records.
            # Preserve them; mandatory events are never recommended for development.
            repeatable_history = item["event_id"] in REPEATABLE_EVENTS or (event and event["mandatory"])
            key = (item["employee_id"], item["event_id"], item.get("session_date", item["date"]) if repeatable_history else None)
            if key in completions:
                issue("history", eid, "event_id", "Duplicate completion (repeatable events require distinct session dates)")
            completions.add(key)
    return {"valid": not errors, "errors": errors, "counts": report, "as_of_date": as_of}, incoming


def apply_validated(conn, incoming, as_of):
    changed = False
    for kind, items in incoming.items():
        old = all_entities(conn, kind)
        for eid, item in items.items():
            if old.get(eid) != item:
                put_entity(conn, kind, eid, item)
                changed = True
    if get_meta(conn, "as_of_date") != as_of:
        set_meta(conn, "as_of_date", as_of)
        changed = True
    if changed:
        bump_revision(conn)
    return changed
