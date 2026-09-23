from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Level = Annotated[int, Field(strict=True, ge=0, le=5)]
ID = Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")]
Grade = Literal["Junior", "Middle", "Senior", "Lead"]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Goal(Model):
    target_role: str = Field(min_length=1, max_length=150)
    target_grade: Grade


class Employee(Model):
    employee_id: ID
    full_name: str = Field(min_length=1, max_length=200)
    department: str = Field(min_length=1, max_length=200)
    role: str = Field(min_length=1, max_length=150)
    grade: Grade
    manager_id: ID | None
    hire_date: date
    tenure_months: int = Field(strict=True, ge=0)
    work_format: Literal["office", "hybrid", "remote"]
    preferred_language: Literal["ru", "kk", "en"]
    career_goal: Goal | None
    skills: dict[ID, Level]
    last_review_date: date


class Skill(Model):
    skill_id: ID
    name: str = Field(min_length=1)
    type: Literal["hard", "soft"]
    category: str
    description: str


class RoleProfile(Model):
    role: str
    grade: Grade
    required_skills: dict[ID, Level]
    critical_skills: list[ID]

    @model_validator(mode="after")
    def critical_in_required(self):
        if not set(self.critical_skills) <= self.required_skills.keys():
            raise ValueError("critical_skills must be included in required_skills")
        return self


class SkillGain(Model):
    skill_id: ID
    gain: int = Field(strict=True, ge=0, le=5)
    max_level: Level


class Event(Model):
    event_id: ID
    title: str = Field(min_length=1)
    description: str
    type: Literal["compliance", "onboarding", "course", "workshop", "mentoring", "certification", "meetup"]
    format: Literal["online", "offline", "self_paced"]
    duration_hours: float = Field(gt=0)
    mandatory: bool = Field(strict=True)
    target_roles: list[str]
    target_grades: list[Grade]
    develops_skills: list[SkillGain]
    prerequisites: dict[ID, Level]
    upcoming_sessions: list[date]

    @model_validator(mode="after")
    def unique_gains(self):
        ids = [x.skill_id for x in self.develops_skills]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate develops_skills")
        return self


class History(Model):
    record_id: ID
    employee_id: ID
    event_id: ID
    date: date
    due_date: date | None
    status: Literal["completed", "in_progress", "dropped", "no_show", "declined", "overdue"]
    completion_pct: int = Field(strict=True, ge=0, le=100)
    score: int | None = Field(default=None, ge=0, le=100)
    feedback_rating: int | None = Field(default=None, ge=1, le=5)
    assigned_by: Literal["self", "manager", "hr"]

    @model_validator(mode="after")
    def status_progress(self):
        if self.status == "completed" and self.completion_pct != 100:
            raise ValueError("completed requires completion_pct=100")
        if self.status in ("no_show", "declined") and self.completion_pct != 0:
            raise ValueError("no_show/declined require completion_pct=0")
        if self.status in ("in_progress", "overdue") and self.completion_pct > 95:
            raise ValueError("in_progress/overdue require completion_pct<=95")
        if self.status == "dropped" and not 5 <= self.completion_pct <= 95:
            raise ValueError("dropped requires completion_pct=5..95")
        return self


class Login(Model):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=256)


class Setup(Login):
    token: str = Field(min_length=1, max_length=256)


class NewUser(Login):
    role: Literal["employee", "hr"] = "employee"
    employee_id: ID | None = None


class GoalChange(Model):
    career_goal: Goal | None


class Completion(Model):
    # For scheduled events this identifies the session; cannot complete a future session.
    session_date: date | None = None
    activity_record_id: ID | None = None


class ApplyImport(Model):
    batch_id: str


class GamificationSettings(Model):
    enabled: bool = Field(strict=True)


class PersonalQuest(Model):
    event_id: ID


class Factor(Model):
    type: Literal["goal", "skill_gap", "critical_skill", "history", "format", "duration"]
    text: str = Field(min_length=1, max_length=1500)


class AIChoice(Model):
    event_id: ID
    reason: str = Field(min_length=1, max_length=3000)
    factors: list[Factor] = Field(min_length=3, max_length=6)

    @model_validator(mode="after")
    def distinct_factors(self):
        if len({x.type for x in self.factors}) != len(self.factors):
            raise ValueError("factors must have distinct types")
        return self


class AIResult(Model):
    recommendations: list[AIChoice] = Field(min_length=1, max_length=3)
