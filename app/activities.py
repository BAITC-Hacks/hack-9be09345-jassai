from datetime import datetime, timezone
import hashlib
import json
import uuid

from fastapi import HTTPException

from app.db import bump_revision, encode, get_meta, put_entity, snapshot
from app.domain import REPEATABLE_EVENTS, effective_skills, eligibility, employee_history, profile_view


def fail(code, message, status=409):
    raise HTTPException(status, detail={"code": code, "message": message})


def load_activity(conn, employee_id, event_id):
    data = snapshot(conn)
    employee = data["employees"].get(employee_id)
    event = data["events"].get(event_id)
    if employee is None or event is None:
        fail("not_found", "Employee or event not found", 404)
    as_of = get_meta(conn, "as_of_date")
    history = employee_history(data, employee_id)
    levels = effective_skills(employee, data, as_of)
    reasons, ongoing, sessions = eligibility(employee, event, levels, history, as_of)
    return data, employee, event, as_of, history, levels, reasons, ongoing, sessions


def start_activity(conn, employee_id, event_id, body):
    data, employee, event, as_of, history, levels, reasons, ongoing, sessions = load_activity(conn, employee_id, event_id)
    if body.activity_record_id:
        fail("invalid_start", "activity_record_id is only used for completion", 422)
    if ongoing:
        return {"record": ongoing[0], "already_started": True}
    if reasons:
        fail("event_not_eligible", ", ".join(reasons))
    if event["format"] == "self_paced":
        if body.session_date:
            fail("invalid_session", "Self-paced events do not take a session_date", 422)
        session_date = as_of
    else:
        session_date = body.session_date.isoformat() if body.session_date else (sessions[0] if sessions else None)
        if session_date not in sessions:
            fail("invalid_session", "Select an available session")
    record = {
        "record_id": "APP_" + uuid.uuid4().hex, "employee_id": employee_id, "event_id": event_id,
        "date": session_date, "due_date": None, "status": "in_progress", "completion_pct": 0,
        "score": None, "feedback_rating": None, "assigned_by": "self", "source": "application",
    }
    put_entity(conn, "history", record["record_id"], record)
    bump_revision(conn)
    return {"record": record, "already_started": False}


def complete_activity(conn, username, employee_id, event_id, body, idempotency_key):
    if not idempotency_key or len(idempotency_key) > 200:
        fail("idempotency_key_required", "Send Idempotency-Key (1..200 characters)", 422)
    signature = hashlib.sha256(encode({"event_id": event_id, "employee_id": employee_id, "body": body.model_dump(mode="json")}).encode()).hexdigest()
    previous = conn.execute("SELECT request_hash,response FROM idempotency WHERE username=? AND key=?", (username, idempotency_key)).fetchone()
    if previous:
        if previous["request_hash"] != signature:
            fail("idempotency_conflict", "This key was used for a different request")
        return json.loads(previous["response"])

    data, employee, event, as_of, history, before, reasons, ongoing, sessions = load_activity(conn, employee_id, event_id)
    record = None
    if body.activity_record_id:
        record = data["history"].get(body.activity_record_id)
        if record is None or record["employee_id"] != employee_id or record["event_id"] != event_id:
            fail("activity_not_found", "Own activity record not found", 404)
        if record["status"] == "completed":
            fail("already_completed", "Activity was already completed")
        if record["status"] != "in_progress":
            fail("activity_not_active", "Only an in-progress record can be completed")
    elif ongoing:
        record = ongoing[0]

    # A started activity may no longer have an upcoming session; it is still completable.
    blocking = [reason for reason in reasons if reason != "no_available_session" or record is None]
    if blocking:
        fail("event_not_eligible", ", ".join(blocking))
    if event["format"] == "self_paced":
        if body.session_date:
            fail("invalid_session", "Self-paced events do not take a session_date", 422)
        session_date = as_of
    else:
        session_date = body.session_date.isoformat() if body.session_date else (record["date"] if record else None)
        if record and session_date != record["date"]:
            fail("session_mismatch", "Session must match the activity record")
        if not record and session_date not in event["upcoming_sessions"]:
            fail("invalid_session", "Choose an existing session or activity record")
        if session_date is None or session_date > as_of:
            fail("future_session", "Cannot complete a future session")
        if event_id in REPEATABLE_EVENTS and any(
            r["event_id"] == event_id and r["status"] == "completed" and r.get("session_date", r["date"]) == session_date
            for r in history
        ):
            fail("already_completed", "This session was already completed")

    record = dict(record) if record else {
        "record_id": "APP_" + uuid.uuid4().hex, "employee_id": employee_id, "event_id": event_id,
        "date": as_of, "due_date": None, "score": None, "feedback_rating": None, "assigned_by": "self",
    }
    record.update({
        "enrolled_date": record["date"], "date": as_of, "session_date": session_date,
        "status": "completed", "completion_pct": 100, "source": "application",
        "completed_at": datetime.now(timezone.utc).isoformat(),
    })
    put_entity(conn, "history", record["record_id"], record)
    data["history"][record["record_id"]] = record
    after = effective_skills(employee, data, as_of)
    bump_revision(conn)
    result = {
        "record": record,
        "changes": [{"skill_id": sid, "before": before.get(sid, 0), "after": value} for sid, value in after.items() if value != before.get(sid, 0)],
        "profile": profile_view(employee, data, as_of),
    }
    conn.execute("INSERT INTO idempotency VALUES (?,?,?,?)", (username, idempotency_key, signature, encode(result)))
    return result
