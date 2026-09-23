"""Pure, deterministic domain rules. No DB, HTTP, or model calls."""
from collections import Counter
from copy import deepcopy

GRADES = ["Junior", "Middle", "Senior", "Lead"]
REPEATABLE_EVENTS = {"EV_036"}


def role_key(role, grade):
    return f"{role}|{grade}"


def employee_history(data, employee_id):
    return sorted(
        [r for r in data["history"].values() if r["employee_id"] == employee_id],
        key=lambda r: (r["date"], r.get("completed_at", ""), r["record_id"]),
    )


def apply_gains(levels, event):
    result = dict(levels)
    for gain in event["develops_skills"]:
        sid = gain["skill_id"]
        old = result.get(sid, 0)
        result[sid] = old + max(0, min(gain["gain"], gain["max_level"] - old, 5 - old))
    return result


def effective_skills(employee, data, as_of):
    levels = {sid: employee["skills"].get(sid, 0) for sid in data["skills"]}
    seen = set()
    for row in employee_history(data, employee["employee_id"]):
        if row["record_id"] in seen:
            continue
        seen.add(row["record_id"])
        after_review = row["date"] > employee["last_review_date"]
        # A locally completed action on the snapshot date follows the snapshot assessment.
        same_day_action = row.get("source") == "application" and row["date"] == employee["last_review_date"]
        if row["status"] == "completed" and row["date"] <= as_of and (after_review or same_day_action):
            levels = apply_gains(levels, data["events"][row["event_id"]])
    return levels


def target_profile(employee, data):
    goal = employee.get("career_goal")
    source = "explicit"
    if goal is None:
        index = GRADES.index(employee["grade"])
        if index == len(GRADES) - 1:
            return {"goal": None, "source": "not_set", "requirements": {}, "critical_skills": []}
        goal = {"target_role": employee["role"], "target_grade": GRADES[index + 1]}
        source = "suggested_next_grade"
    profile = data["role_profiles"].get(role_key(goal["target_role"], goal["target_grade"]))
    return {
        "goal": goal, "source": source,
        "requirements": profile["required_skills"] if profile else {},
        "critical_skills": profile["critical_skills"] if profile else [],
    }


def trajectory(employee, data, as_of):
    levels = effective_skills(employee, data, as_of)
    target = target_profile(employee, data)
    gaps = []
    for sid, required in target["requirements"].items():
        gaps.append({
            "skill_id": sid, "name": data["skills"][sid]["name"],
            "current": levels.get(sid, 0), "required": required,
            "gap": max(0, required - levels.get(sid, 0)),
            "critical": sid in target["critical_skills"],
        })
    total = sum(target["requirements"].values())
    covered = sum(min(x["current"], x["required"]) for x in gaps)
    return {
        "effective_skills": levels, "target": target,
        "skills": sorted(gaps, key=lambda x: (not x["critical"], -x["gap"], x["skill_id"])),
        "coverage_pct": round(100 * covered / total, 2) if total else None,
        "critical_gaps": [x for x in gaps if x["critical"] and x["gap"] > 0],
    }


def eligibility(employee, event, levels, history, as_of):
    reasons = []
    if event["mandatory"]:
        reasons.append("mandatory")
    if employee["role"] not in event["target_roles"]:
        reasons.append("role_not_eligible")
    if employee["grade"] not in event["target_grades"]:
        reasons.append("grade_not_eligible")
    if any(levels.get(sid, 0) < required for sid, required in event["prerequisites"].items()):
        reasons.append("prerequisites_not_met")
    completed = [r for r in history if r["event_id"] == event["event_id"] and r["status"] == "completed"]
    if completed and event["event_id"] not in REPEATABLE_EVENTS:
        reasons.append("already_completed")
    ongoing = [r for r in history if r["event_id"] == event["event_id"] and r["status"] == "in_progress"]
    completed_dates = {r.get("session_date", r["date"]) for r in completed}
    sessions = sorted(d for d in event["upcoming_sessions"] if d >= as_of and d not in completed_dates)
    if event["format"] != "self_paced" and not sessions and not ongoing:
        reasons.append("no_available_session")
    return reasons, ongoing, sessions


def candidates(employee, data, as_of):
    progress = trajectory(employee, data, as_of)
    levels = progress["effective_skills"]
    history = employee_history(data, employee["employee_id"])
    requirements = progress["target"]["requirements"]
    result, excluded = [], {}
    for event in data["events"].values():
        reasons, ongoing, sessions = eligibility(employee, event, levels, history, as_of)
        after = apply_gains(levels, event)
        gains = [
            {"skill_id": sid, "before": levels.get(sid, 0), "after": value, "gain": value - levels.get(sid, 0),
             "gap_closed": min(max(0, requirements.get(sid, 0) - levels.get(sid, 0)), value - levels.get(sid, 0)),
             "critical": sid in progress["target"]["critical_skills"]}
            for sid, value in after.items() if value > levels.get(sid, 0)
        ]
        if not progress["target"]["goal"]:
            reasons.append("goal_not_set")
        elif not any(g["gap_closed"] for g in gains):
            reasons.append("no_target_gain")
        if reasons:
            excluded[event["event_id"]] = reasons
            continue
        result.append({
            **deepcopy(event), "expected_gains": gains,
            "action": "continue" if ongoing else "start",
            "activity_record_id": ongoing[0]["record_id"] if ongoing else None,
            "next_session": ongoing[0]["date"] if ongoing else (sessions[0] if sessions else None),
        })
    # Stable input order only. AI, not this ordering, is responsible for recommendations.
    result.sort(key=lambda x: x["event_id"])
    return result, excluded


def profile_view(employee, data, as_of):
    available, excluded = candidates(employee, data, as_of)
    return {
        "employee": deepcopy(employee), "as_of_date": as_of,
        "trajectory": trajectory(employee, data, as_of),
        "history": employee_history(data, employee["employee_id"]),
        "available_steps": available,
        "no_step_reasons": dict(Counter(reason for reasons in excluded.values() for reason in reasons)) if not available else {},
    }


def recommendation_context(employee, data, as_of, revision):
    view = profile_view(employee, data, as_of)
    types, formats = {}, {}
    for row in view["history"]:
        if row["date"] > as_of:
            continue
        event = data["events"][row["event_id"]]
        for group, key in [(types, event["type"]), (formats, event["format"])]:
            group.setdefault(key, Counter())[row["status"]] += 1
    return {
        "schema_version": "1.0", "data_revision": revision, "as_of_date": as_of,
        "employee": {key: employee[key] for key in ("employee_id", "role", "grade", "tenure_months", "work_format", "preferred_language")},
        "trajectory": view["trajectory"], "candidates": view["available_steps"],
        "history_summary": {"by_type": types, "by_format": formats, "total_records": len(view["history"])},
        "no_step_reasons": view["no_step_reasons"],
    }


def hr_overview(data, as_of, date_from=None, date_to=None):
    deficits, no_steps = {}, []
    for employee in data["employees"].values():
        progress = trajectory(employee, data, as_of)
        for skill in progress["skills"]:
            row = deficits.setdefault(skill["skill_id"], {
                "skill_id": skill["skill_id"], "name": skill["name"], "target_population": 0,
                "employees_with_gap": 0, "critical_gaps": 0,
            })
            row["target_population"] += 1
            if skill["gap"]:
                row["employees_with_gap"] += 1
                row["critical_gaps"] += int(skill["critical"])
        available, excluded = candidates(employee, data, as_of)
        if not available:
            no_steps.append({
                "employee_id": employee["employee_id"], "full_name": employee["full_name"],
                "role": employee["role"], "grade": employee["grade"],
                "reasons": dict(Counter(r for reasons in excluded.values() for r in reasons)),
                "goal": progress["target"]["goal"], "coverage_pct": progress["coverage_pct"],
            })
    for row in deficits.values():
        row["gap_pct"] = round(100 * row["employees_with_gap"] / row["target_population"], 2)
    participation = {eid: {"event_id": eid, "title": e["title"], "records": 0, "statuses": {s: 0 for s in ("completed", "in_progress", "dropped", "no_show", "declined", "overdue")}} for eid, e in data["events"].items()}
    for row in data["history"].values():
        if row["date"] > (date_to or as_of) or (date_from and row["date"] < date_from):
            continue
        item = participation[row["event_id"]]
        item["records"] += 1
        item["statuses"][row["status"]] += 1
    for item in participation.values():
        item["completion_pct"] = round(100 * item["statuses"]["completed"] / item["records"], 2) if item["records"] else None
    return {
        "as_of_date": as_of, "employee_count": len(data["employees"]),
        "skill_deficits": sorted(deficits.values(), key=lambda x: (-x["employees_with_gap"], x["skill_id"])),
        "employees_without_step": no_steps,
        "participation": list(participation.values()),
        "period": {"from": date_from, "to": date_to or as_of},
        "definitions": {"gap_pct": "employees_with_gap / target_population × 100", "completion_pct": "completed records / all records in period × 100"},
    }
