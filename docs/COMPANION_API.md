# Career companion: factual progress and permanent earned clothing

`app/companion.py` projects the existing private reward ledger into a wardrobe and
builds a skill tree from the same domain rules as the employee profile. Mascot
visual assets are supplied separately; these identifiers are the integration
contract for the renderer.

## Projection and equipment

`companion_view(conn, employee, data, as_of)` returns all existing
`gamification_view` fields unchanged, plus:

```json
{
  "wardrobe": [{
    "id": "cap_spark", "name": "Кепка первого шага", "slot": "head",
    "description": "За первую активность, которая действительно развила навык.",
    "unlocked": false, "equipped": false, "earned_at": null,
    "requirement": {
      "kind": "completed_count", "target": 1, "current": 0,
      "label": "Завершить 1 добровольную активность с наградой"
    },
    "style": {"color": "#EDBA43", "icon": "star"}
  }],
  "equipped": {
    "head": "cap_starter", "body": "body_starter",
    "accessory": "accessory_none", "background": "room_starter"
  },
  "next_unlock": null,
  "tree": {
    "goal": {"target_role": "Engineer", "target_grade": "Senior"},
    "goal_source": "explicit", "coverage_pct": 40,
    "critical_gap_count": 1, "empty_reason": null,
    "branches": [{
      "skill_id": "SK_A", "name": "Architecture", "category": "test",
      "current": 2, "required": 4, "critical": true,
      "nodes": [{"level": 3, "status": "next", "event_ids": ["EV_GOOD"]}],
      "activities": [{
        "event_id": "EV_GOOD", "title": "EV_GOOD", "type": "course",
        "format": "self_paced", "duration_hours": 2, "action": "start",
        "activity_record_id": null, "next_session": null,
        "before": 2, "after": 4, "gap_closed": 2, "critical": true,
        "coverage_after": 80
      }]
    }]
  }
}
```

The example is abbreviated: every real branch has five level nodes, and the
wardrobe always includes ten items. `next_unlock` is the full locked item with
the smallest proportion of its requirement left; it is `null` only when every
item is unlocked. It is an informational progress hint, not an AI recommendation.

`equip_item(conn, employee, data, as_of, item_id)` requires a write transaction
and returns the full companion projection. It derives the slot from the item:
clients cannot equip a hat as a background. Locked items return HTTP 409 with
`companion_item_locked`; unknown IDs return 404 `companion_item_not_found`.
Equipping a starter item restores the default for that slot. Equipping the same
item twice is safe. Local try-on must not call this mutation. Route integration
must enforce the employee session and CSRF rules used by other private mutations.

## Stable appearance identifiers

| Item | Slot | Requirement |
|---|---|---|
| `cap_starter` | head | Starter; no headwear |
| `body_starter` | body | Starter green shirt |
| `accessory_none` | accessory | Starter; no accessory |
| `room_starter` | background | Starter light studio |
| `cap_spark` | head | 1 rewarded completion |
| `accessory_notebook` | accessory | 2 accumulated rewarded skill levels |
| `body_explorer` | body | 3 distinct rewarded activity IDs |
| `accessory_compass` | accessory | 5 accumulated rewarded skill levels |
| `cap_quest` | head | 1 rewarded personal quest |
| `room_horizon` | background | 150 XP |

Unlock requirements use only immutable `gamification_rewards` facts. Catalog
activity types are intentionally not used: an HR catalog correction must not
re-lock an earned item. Repeated sessions of one event count once toward the
three-distinct-activities requirement. A wardrobe unlock never changes the outfit
automatically. Only an employee's explicit choice writes `companion_equipment`.

Earned items and the saved outfit remain available while rewards are disabled.
Turning rewards on does not award imported history retroactively. Mandatory
activities, completions without actual skill gain, and duplicate completions do
not create clothing rewards. Changing goals or updating an assessment does not
remove already earned clothing. Clothing and XP do not affect the career grade,
the skill calculation, the ranking of recommendations, or HR reports.

## Reading the skill tree honestly

The tree uses `trajectory` for current levels, requirements, critical gaps and
coverage. It includes every required skill and assessed nonzero skills outside
the goal; the latter have `required: null`. Nodes represent levels 1–5:

- `earned`: the effective assessed level has reached this node;
- `next`: the next level on the scale, even if no course currently reaches it;
- `locked`: a later level on the scale.

These are **not course prerequisites**. A real course may bridge multiple nodes,
including a node visually marked `locked`. Node `event_ids` and branch
`activities` contain only currently eligible domain candidates with real gain.
There are no invented prerequisite chains or executable links to excluded events.
The usual activity API must revalidate eligibility at execution time.

`before`/`after` are capped skill forecasts. `coverage_after` includes all gains
from that activity, and is a forecast rather than completed progress. Actual
progress changes only after the existing completion transaction. `empty_reason`
is `goal_not_set`, `target_profile_missing`, `goal_covered`,
`no_available_steps`, or `null`. Missing requirements never become 0% completion.

This projection makes no network or model calls. AI conversation can consume it
as evidence, but model output cannot award clothing, complete courses or equip
items. The renderer should use A's mascot assets with these stable slot IDs.
