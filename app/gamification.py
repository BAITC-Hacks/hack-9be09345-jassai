"""Opt-in personal rewards. Never used for HR ranking or career calculations."""
from fastapi import HTTPException

from app.domain import candidates

LEVELS = [(0, "Начало пути"), (60, "Первые шаги"), (150, "Новый ритм"), (300, "Широкий горизонт"), (500, "Длинный путь")]
BADGES = [
    ("first_step", "Первый шаг", "Завершить добровольную активность с приростом навыка после включения достижений."),
    ("three_steps", "Три направления", "Завершить три разных добровольных мероприятия с приростом навыков."),
    ("skill_builder", "Рост в деталях", "Получить суммарно пять уровней навыков за добровольные активности."),
    ("personal_quest", "Свой выбор", "Завершить выбранный личный квест с приростом навыка."),
]


def preference(conn, employee_id):
    row = conn.execute("SELECT * FROM gamification_preferences WHERE employee_id=?", (employee_id,)).fetchone()
    return dict(row) if row else {"employee_id": employee_id, "enabled": 0, "quest_event_id": None, "quest_state": None, "quest_completed_at": None}


def ensure_preference(conn, employee_id):
    conn.execute("INSERT OR IGNORE INTO gamification_preferences(employee_id) VALUES (?)", (employee_id,))


def set_enabled(conn, employee_id, enabled):
    ensure_preference(conn, employee_id)
    conn.execute("UPDATE gamification_preferences SET enabled=? WHERE employee_id=?", (int(enabled), employee_id))


def choose_quest(conn, employee, data, as_of, event_id):
    prefs = preference(conn, employee["employee_id"])
    if not prefs["enabled"]:
        raise HTTPException(409, detail={"code": "gamification_disabled", "message": "Сначала включите личные достижения"})
    available, _ = candidates(employee, data, as_of)
    if event_id not in {event["event_id"] for event in available}:
        raise HTTPException(409, detail={"code": "quest_not_available", "message": "Выберите доступный шаг, который помогает карьерной цели"})
    # Selecting the same active quest again does not reset its state.
    if prefs["quest_event_id"] != event_id or prefs["quest_state"] != "active":
        conn.execute("UPDATE gamification_preferences SET quest_event_id=?,quest_state='active',quest_completed_at=NULL WHERE employee_id=?", (event_id, employee["employee_id"]))


def clear_quest(conn, employee_id):
    ensure_preference(conn, employee_id)
    conn.execute("UPDATE gamification_preferences SET quest_event_id=NULL,quest_state=NULL,quest_completed_at=NULL WHERE employee_id=?", (employee_id,))


def award_completion(conn, employee, event, record, changes):
    """Called only inside the activity completion transaction, before idempotent response storage."""
    gained = sum(max(0, change["after"] - change["before"]) for change in changes)

    def none(reason):
        return {"awarded": False, "xp": 0, "gained_levels": gained, "reason": reason}

    if conn.execute("SELECT 1 FROM gamification_rewards WHERE record_id=?", (record["record_id"],)).fetchone():
        return none("already_awarded")
    prefs = preference(conn, employee["employee_id"])
    if not prefs["enabled"]:
        return none("disabled")
    if event["mandatory"] or record.get("source") != "application":
        return none("mandatory" if event["mandatory"] else "imported_history")
    quest_completed = prefs["quest_event_id"] == event["event_id"] and prefs["quest_state"] == "active"
    if quest_completed:
        conn.execute("UPDATE gamification_preferences SET quest_state='completed',quest_completed_at=? WHERE employee_id=?", (record["completed_at"], employee["employee_id"]))
    if gained == 0:
        return none("no_skill_gain")
    xp = 20 + 10 * gained
    conn.execute(
        "INSERT INTO gamification_rewards VALUES (?,?,?,?,?,?,?,?)",
        (record["record_id"], employee["employee_id"], event["event_id"], event["title"], xp, gained, int(quest_completed), record["completed_at"]),
    )
    return {"awarded": True, "xp": xp, "gained_levels": gained, "reason": "awarded"}


def gamification_view(conn, employee, data, as_of):
    employee_id = employee["employee_id"]
    prefs = preference(conn, employee_id)
    rewards = [dict(row) for row in conn.execute("SELECT * FROM gamification_rewards WHERE employee_id=? ORDER BY earned_at,record_id", (employee_id,))]
    xp = sum(row["xp"] for row in rewards)
    gained = sum(row["gained_levels"] for row in rewards)
    level_index = max(index for index, (minimum, _) in enumerate(LEVELS) if xp >= minimum)
    threshold, title = LEVELS[level_index]
    next_threshold = LEVELS[level_index + 1][0] if level_index + 1 < len(LEVELS) else None
    achieved = {}
    seen_events, cumulative_levels = set(), 0
    for row in rewards:
        seen_events.add(row["event_id"])
        cumulative_levels += row["gained_levels"]
        conditions = {
            "first_step": True, "three_steps": len(seen_events) >= 3,
            "skill_builder": cumulative_levels >= 5, "personal_quest": bool(row["quest_completed"]),
        }
        for badge, met in conditions.items():
            if met:
                achieved.setdefault(badge, row["earned_at"])
    quest = None
    if prefs["quest_event_id"]:
        event_id = prefs["quest_event_id"]
        event = data["events"].get(event_id)
        available, excluded = candidates(employee, data, as_of)
        candidate = next((item for item in available if item["event_id"] == event_id), None)
        state = prefs["quest_state"]
        if state != "completed":
            state = "paused" if not prefs["enabled"] else "active" if candidate else "unavailable"
        quest = {
            "event_id": event_id, "title": event["title"] if event else event_id, "status": state,
            "expected_gains": candidate["expected_gains"] if candidate else [],
            "unavailable_reasons": excluded.get(event_id, ["event_not_found"] if event is None else []) if state == "unavailable" else [],
        }
    return {
        "enabled": bool(prefs["enabled"]), "xp": xp, "level": level_index + 1, "level_name": title,
        "level_progress": {"current": xp - threshold, "required": next_threshold - threshold if next_threshold is not None else None},
        "completed_count": len(rewards), "skill_levels_gained": gained,
        "badges": [{"id": bid, "title": btitle, "description": description, "earned": bid in achieved, "earned_at": achieved.get(bid)} for bid, btitle, description in BADGES],
        "quest": quest,
        "recent_rewards": [{key: row[key] for key in ("record_id", "event_id", "title", "xp", "gained_levels", "earned_at")} for row in reversed(rewards[-10:])],
        "rules": [
            "Участие добровольное: включайте и выключайте достижения в любое время.",
            "20 XP за завершение добровольной активности с реальным ростом навыков и ещё 10 XP за каждый полученный уровень навыка.",
            "Награды начисляются только за действия в приложении после включения. Импортированная история не выдаёт XP.",
            "Обязательные мероприятия, повторы одного выполнения и занятия без прироста навыков не дают XP.",
            "Квест можно заменить или отменить. Сроков, штрафов и потери накопленных XP нет.",
            "Уровень пути — личное достижение; он не заменяет грейд и не влияет на AI-рекомендации.",
        ],
        "privacy": "Достижения видны только вам. Публичных рейтингов и доступа HR к вашим XP нет.",
    }
