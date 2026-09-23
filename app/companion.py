"""Personal companion appearance and a factual skill tree, independent of AI.

Clothing is derived from the existing immutable reward ledger. Imported history
can change assessed skill levels, but cannot retroactively award clothing or XP.
Only the employee's explicit equipment choice is persisted here.
"""
from copy import deepcopy

from fastapi import HTTPException

from app.domain import apply_gains, candidates, trajectory
from app.gamification import gamification_view


DEFAULT_EQUIPMENT = {
    "head": "cap_starter", "body": "body_starter",
    "accessory": "accessory_none", "background": "room_starter",
}

# These identifiers are the stable visual contract for the mascot renderer.
# Requirements use only facts stored in gamification_rewards, never mutable
# catalog classifications, the employee's current goal, or a model response.
ITEMS = (
    {"id": "cap_starter", "name": "Без головного убора", "slot": "head",
     "description": "Базовый образ вашего напарника.", "kind": "starter", "target": 0,
     "label": "Доступно с самого начала", "color": "#F3D49B", "icon": "sparkles"},
    {"id": "body_starter", "name": "Зелёная футболка", "slot": "body",
     "description": "Первый образ для нового пути.", "kind": "starter", "target": 0,
     "label": "Доступно с самого начала", "color": "#087B5A", "icon": "shirt"},
    {"id": "accessory_none", "name": "Без аксессуара", "slot": "accessory",
     "description": "Ничего лишнего — только ваш напарник.", "kind": "starter", "target": 0,
     "label": "Доступно с самого начала", "color": "#C6D1CA", "icon": "circle"},
    {"id": "room_starter", "name": "Светлая студия", "slot": "background",
     "description": "Спокойное место, чтобы планировать следующий шаг.", "kind": "starter", "target": 0,
     "label": "Доступно с самого начала", "color": "#E5F1E9", "icon": "home"},
    {"id": "cap_spark", "name": "Кепка первого шага", "slot": "head",
     "description": "За первую активность, которая действительно развила навык.",
     "kind": "completed_count", "target": 1,
     "label": "Завершить 1 добровольную активность с наградой", "color": "#EDBA43", "icon": "star"},
    {"id": "accessory_notebook", "name": "Блокнот открытий", "slot": "accessory",
     "description": "Сохраняет память о первых заметных изменениях.",
     "kind": "gained_levels", "target": 2,
     "label": "Получить суммарно 2 уровня навыков с наградами", "color": "#688BC7", "icon": "book-open"},
    {"id": "body_explorer", "name": "Худи исследователя", "slot": "body",
     "description": "За три разных опыта на вашем пути.",
     "kind": "distinct_events", "target": 3,
     "label": "Завершить 3 разные активности с наградами", "color": "#5A72B5", "icon": "shirt"},
    {"id": "accessory_compass", "name": "Компас роста", "slot": "accessory",
     "description": "Пять полученных уровней навыков — уже заметный путь.",
     "kind": "gained_levels", "target": 5,
     "label": "Получить суммарно 5 уровней навыков с наградами", "color": "#C19645", "icon": "compass"},
    {"id": "cap_quest", "name": "Шапка личного квеста", "slot": "head",
     "description": "За завершение квеста, который вы выбрали сами.",
     "kind": "quest_count", "target": 1,
     "label": "Завершить 1 личный квест с наградой", "color": "#BE7254", "icon": "flag"},
    {"id": "room_horizon", "name": "Комната с горизонтом", "slot": "background",
     "description": "Новый вид за окном отмечает накопленный опыт.",
     "kind": "xp", "target": 150,
     "label": "Накопить 150 XP", "color": "#B2CFDD", "icon": "sunrise"},
)


def _reward_progress(rewards):
    """Return cumulative immutable facts and first-earned item timestamps."""
    metrics = {"starter": 0, "completed_count": 0, "distinct_events": 0,
               "gained_levels": 0, "quest_count": 0, "xp": 0}
    earned_at, event_ids = {}, set()
    for reward in rewards:
        event_ids.add(reward["event_id"])
        metrics["completed_count"] += 1
        metrics["distinct_events"] = len(event_ids)
        metrics["gained_levels"] += reward["gained_levels"]
        metrics["quest_count"] += int(bool(reward["quest_completed"]))
        metrics["xp"] += reward["xp"]
        for item in ITEMS:
            if item["kind"] != "starter" and metrics[item["kind"]] >= item["target"]:
                earned_at.setdefault(item["id"], reward["earned_at"])
    return metrics, earned_at


def _wardrobe(conn, employee_id):
    rewards = [dict(row) for row in conn.execute(
        "SELECT * FROM gamification_rewards WHERE employee_id=? ORDER BY earned_at,record_id",
        (employee_id,),
    )]
    metrics, earned_at = _reward_progress(rewards)
    wardrobe = [
        {"id": item["id"], "name": item["name"], "slot": item["slot"],
         "description": item["description"],
         "unlocked": item["kind"] == "starter" or item["id"] in earned_at,
         "earned_at": earned_at.get(item["id"]),
         "requirement": {"kind": item["kind"], "target": item["target"],
                         "current": metrics[item["kind"]], "label": item["label"]},
         "style": {"color": item["color"], "icon": item["icon"]}}
        for item in ITEMS
    ]
    by_id = {item["id"]: item for item in wardrobe}
    equipped = dict(DEFAULT_EQUIPMENT)
    for row in conn.execute("SELECT slot,item_id FROM companion_equipment WHERE employee_id=?", (employee_id,)):
        item = by_id.get(row["item_id"])
        # A removed/renamed catalog entry must not make the whole profile fail.
        if item and item["unlocked"] and item["slot"] == row["slot"]:
            equipped[row["slot"]] = item["id"]
    for item in wardrobe:
        item["equipped"] = equipped[item["slot"]] == item["id"]
    return wardrobe, equipped


def skill_tree(employee, data, as_of):
    """Show assessed skill levels and eligible activities; never invent edges.

    Level nodes are a visual proficiency scale, not prerequisites. An activity
    may bridge multiple levels. All links come from domain.candidates, so locked
    catalog activities cannot become executable by appearing in the tree.
    """
    progress = trajectory(employee, data, as_of)
    available, _ = candidates(employee, data, as_of)
    levels = progress["effective_skills"]
    requirements = progress["target"]["requirements"]
    total = sum(requirements.values())
    after_coverage = {}
    for event in available:
        after = apply_gains(levels, event)
        after_coverage[event["event_id"]] = (
            round(100 * sum(min(after.get(sid, 0), required)
                            for sid, required in requirements.items()) / total, 2)
            if total else None
        )
    skill_ids = [item["skill_id"] for item in progress["skills"]]
    skill_ids += sorted(sid for sid, current in levels.items() if current > 0 and sid not in requirements)
    branches = []
    for sid in skill_ids:
        current = levels.get(sid, 0)
        activities = []
        for event in available:
            gain = next((gain for gain in event["expected_gains"] if gain["skill_id"] == sid), None)
            if gain is None:
                continue
            activities.append({
                **{key: event[key] for key in ("event_id", "title", "type", "format", "duration_hours",
                                               "action", "activity_record_id", "next_session")},
                **{key: gain[key] for key in ("before", "after", "gap_closed", "critical")},
                "coverage_after": after_coverage[event["event_id"]],
            })
        branches.append({
            "skill_id": sid, "name": data["skills"][sid]["name"],
            "category": data["skills"][sid].get("category", ""),
            "current": current, "required": requirements.get(sid),
            "critical": sid in progress["target"]["critical_skills"],
            "nodes": [{
                "level": level,
                "status": "earned" if level <= current else "next" if level == current + 1 else "locked",
                "event_ids": [event["event_id"] for event in activities if current < level <= event["after"]],
            } for level in range(1, 6)],
            "activities": activities,
        })
    empty_reason = None
    if not progress["target"]["goal"]:
        empty_reason = "goal_not_set"
    elif not requirements:
        empty_reason = "target_profile_missing"
    elif not available:
        empty_reason = "goal_covered" if progress["coverage_pct"] == 100 else "no_available_steps"
    return {
        "goal": deepcopy(progress["target"]["goal"]), "goal_source": progress["target"]["source"],
        "coverage_pct": progress["coverage_pct"], "critical_gap_count": len(progress["critical_gaps"]),
        "branches": branches, "empty_reason": empty_reason,
    }


def companion_view(conn, employee, data, as_of):
    wardrobe, equipped = _wardrobe(conn, employee["employee_id"])
    locked = [item for item in wardrobe if not item["unlocked"]]
    next_unlock = min(locked, key=lambda item: (
        (item["requirement"]["target"] - item["requirement"]["current"]) / item["requirement"]["target"]
    ), default=None)
    return {
        **gamification_view(conn, employee, data, as_of),
        "wardrobe": wardrobe, "equipped": equipped, "tree": skill_tree(employee, data, as_of),
        "next_unlock": deepcopy(next_unlock),
    }


def equip_item(conn, employee, data, as_of, item_id):
    """Persist a personal choice. Call inside Database.connection(write=True)."""
    wardrobe, _ = _wardrobe(conn, employee["employee_id"])
    item = next((item for item in wardrobe if item["id"] == item_id), None)
    if item is None:
        raise HTTPException(404, detail={"code": "companion_item_not_found", "message": "Такого предмета нет в гардеробе"})
    if not item["unlocked"]:
        raise HTTPException(409, detail={"code": "companion_item_locked", "message": "Сначала выполните условие открытия предмета"})
    conn.execute(
        "INSERT INTO companion_equipment(employee_id,slot,item_id) VALUES (?,?,?) "
        "ON CONFLICT(employee_id,slot) DO UPDATE SET item_id=excluded.item_id",
        (employee["employee_id"], item["slot"], item_id),
    )
    return companion_view(conn, employee, data, as_of)
