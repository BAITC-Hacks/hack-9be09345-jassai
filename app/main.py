import asyncio
from contextlib import asynccontextmanager
from datetime import date
import importlib
import inspect
import json
from pathlib import Path
import sqlite3
import time
import uuid

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app import auth
from app.activities import complete_activity, start_activity
from app.config import Settings
from app.db import Database, all_entities, bump_revision, encode, get_entity, get_meta, put_entity, revision, snapshot
from app.domain import hr_overview, profile_view, recommendation_context, role_key
from app.imports import MAX_FILE_BYTES, apply_validated, validate_files
from app.gamification import choose_quest, clear_quest, gamification_view, set_enabled
from app.companion import companion_view, equip_item
from app.companion_chat import CompanionCoach, compact_facts
from app.models import CompanionChat, CompanionEquip
from app.models import AIResult, ApplyImport, Completion, GamificationSettings, GoalChange, Login, NewUser, PersonalQuest, Setup


def error(status, code, message=None):
    raise HTTPException(status, detail={"code": code, **({"message": message} if message else {})})


def user_payload(user):
    return {key: user[key] for key in ("username", "role", "employee_id")}


def load_employee(conn, employee_id):
    data = snapshot(conn)
    if employee_id not in data["employees"]:
        error(404, "employee_not_found")
    return data["employees"][employee_id], data, get_meta(conn, "as_of_date")


def create_app(settings=None, recommender=None):
    settings = settings or Settings.from_env()
    db = Database(settings.data_dir / "careerquest.sqlite3")

    @asynccontextmanager
    async def lifespan(application):
        db.initialize()
        auth.initialize_bootstrap(db, settings)
        provider = recommender
        if provider is None and settings.recommender:
            module, attribute = settings.recommender.split(":", 1)
            provider = getattr(importlib.import_module(module), attribute)
            if not callable(provider):
                raise TypeError("CAREERQUEST_RECOMMENDER must point to a callable")
        application.state.recommender = provider
        with db.connection(write=True) as conn:
            # Provider code/configuration may have changed while data stayed the same.
            conn.execute("DELETE FROM recommendation_cache")
        try:
            yield
        finally:
            await application.state.companion_coach.close()

    app = FastAPI(title="Career Quest API", version="0.1.0", lifespan=lifespan)
    app.state.db = db
    app.state.settings = settings
    app.state.recommender = recommender
    app.state.companion_coach = CompanionCoach()
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"] + (["testserver"] if settings.testing else []))

    @app.middleware("http")
    async def protect_browser_requests(request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if origin and origin != f"{request.url.scheme}://{request.url.netloc}":
                return JSONResponse(status_code=403, content={"detail": {"code": "origin_forbidden"}})
            if request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse(status_code=403, content={"detail": {"code": "origin_forbidden"}})
            # Bound request memory before multipart parsing (small application, not streaming data lake).
            try:
                if int(request.headers.get("content-length", "0")) > 4 * MAX_FILE_BYTES + 65536:
                    return JSONResponse(status_code=413, content={"detail": {"code": "payload_too_large"}})
            except ValueError:
                return JSONResponse(status_code=400, content={"detail": {"code": "invalid_content_length"}})
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request, exc):
        # FastAPI normally echoes invalid values: never echo password/token fields.
        return JSONResponse(status_code=422, content={"detail": [{"loc": e["loc"], "msg": e["msg"], "type": e["type"]} for e in exc.errors()]})

    @app.get("/health")
    def health():
        return {"status": "ok", "application": "career-quest", "version": "0.1.0"}

    @app.get("/ready")
    def ready():
        with db.connection() as conn:
            return {
                "ready": True, "setup_required": not bool(conn.execute("SELECT 1 FROM users LIMIT 1").fetchone()),
                "dataset_loaded": bool(get_meta(conn, "as_of_date")), "ai_configured": app.state.recommender is not None,
            }

    @app.post("/api/setup", status_code=201)
    def setup(body: Setup):
        auth.enforce_password(body.password)
        with db.connection(write=True) as conn:
            if not auth.bootstrap_allowed(conn, body.token):
                error(403, "setup_forbidden")
            conn.execute("INSERT INTO users VALUES (?,?,?,NULL)", (body.username, auth.password_hash(body.password), "hr"))
            conn.execute("DELETE FROM meta WHERE key='bootstrap_hash'")
        (settings.data_dir / "setup-token.txt").unlink(missing_ok=True)
        return {"created": True, "username": body.username, "role": "hr"}

    @app.post("/api/auth/login")
    def login(body: Login, request: Request, response: Response):
        client = request.client.host if request.client else "local"
        failure = False
        with db.connection(write=True) as conn:
            limit = conn.execute("SELECT * FROM login_limits WHERE client=?", (client,)).fetchone()
            if limit and time.time() - limit["started_at"] < 300 and limit["failures"] >= 10:
                error(429, "login_rate_limited", "Wait five minutes before retrying")
            user = conn.execute("SELECT * FROM users WHERE username=?", (body.username,)).fetchone()
            if user:
                valid = auth.verify_password(body.password, user["password_hash"])
            else:
                auth.password_hash(body.password)  # Preserve password hashing work for unknown usernames.
                valid = False
            if not valid:
                started = limit["started_at"] if limit and time.time() - limit["started_at"] < 300 else time.time()
                failures = limit["failures"] + 1 if limit and started == limit["started_at"] else 1
                conn.execute("INSERT OR REPLACE INTO login_limits VALUES (?,?,?)", (client, failures, started))
                failure = True
            else:
                conn.execute("DELETE FROM login_limits WHERE client=?", (client,))
                # Rotate the current session on re-authentication.
                old = request.cookies.get(auth.SESSION_COOKIE)
                if old:
                    conn.execute("DELETE FROM sessions WHERE token_hash=?", (auth.digest(old),))
                token, csrf = auth.new_session(conn, body.username)
        if failure:
            error(401, "invalid_credentials")
        auth.set_session_cookie(response, request, token)
        return {"user": user_payload(user), "csrf_token": csrf}

    @app.get("/api/auth/session")
    def session(user=Depends(auth.current_user)):
        return {"user": user_payload(user), "csrf_token": user["csrf_token"]}

    @app.post("/api/auth/logout")
    def logout(request: Request, response: Response, user=Depends(auth.current_user)):
        with db.connection(write=True) as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash=?", (auth.digest(request.cookies[auth.SESSION_COOKIE]),))
        response.delete_cookie(auth.SESSION_COOKIE, path="/")
        return {"logged_out": True}

    @app.post("/api/hr/users", status_code=201)
    def add_user(body: NewUser, user=Depends(auth.current_user)):
        auth.require_role(user, "hr")
        auth.enforce_password(body.password)
        with db.connection(write=True) as conn:
            if body.role == "employee" and (not body.employee_id or get_entity(conn, "employees", body.employee_id) is None):
                error(422, "employee_not_found")
            if body.role == "hr" and body.employee_id is not None:
                error(422, "hr_has_no_employee_id")
            try:
                conn.execute("INSERT INTO users VALUES (?,?,?,?)", (body.username, auth.password_hash(body.password), body.role, body.employee_id))
            except sqlite3.IntegrityError:
                error(409, "user_already_exists")
        return {"user": {"username": body.username, "role": body.role, "employee_id": body.employee_id}}

    @app.get("/api/catalog")
    def catalog(user=Depends(auth.current_user)):
        with db.connection() as conn:
            return {"as_of_date": get_meta(conn, "as_of_date"), **{kind: list(all_entities(conn, kind).values()) for kind in ("skills", "role_profiles", "events")}}

    @app.get("/api/me")
    def me(user=Depends(auth.current_user)):
        auth.require_role(user, "employee")
        with db.connection() as conn:
            employee, data, as_of = load_employee(conn, user["employee_id"])
            return profile_view(employee, data, as_of)

    @app.patch("/api/me/goal")
    def change_goal(body: GoalChange, user=Depends(auth.current_user)):
        auth.require_role(user, "employee")
        with db.connection(write=True) as conn:
            employee, data, as_of = load_employee(conn, user["employee_id"])
            goal = body.career_goal.model_dump() if body.career_goal else None
            if goal and role_key(goal["target_role"], goal["target_grade"]) not in data["role_profiles"]:
                error(422, "unknown_target")
            if employee["career_goal"] != goal:
                employee["career_goal"] = goal
                put_entity(conn, "employees", employee["employee_id"], employee)
                bump_revision(conn)
            return profile_view(employee, data, as_of)

    @app.get("/api/me/gamification")
    def gamification(user=Depends(auth.current_user)):
        auth.require_role(user, "employee")
        with db.connection() as conn:
            employee, data, as_of = load_employee(conn, user["employee_id"])
            return gamification_view(conn, employee, data, as_of)

    @app.patch("/api/me/gamification")
    def gamification_settings(body: GamificationSettings, user=Depends(auth.current_user)):
        auth.require_role(user, "employee")
        with db.connection(write=True) as conn:
            employee, data, as_of = load_employee(conn, user["employee_id"])
            set_enabled(conn, employee["employee_id"], body.enabled)
            return gamification_view(conn, employee, data, as_of)

    @app.post("/api/me/gamification/quest")
    def select_personal_quest(body: PersonalQuest, user=Depends(auth.current_user)):
        auth.require_role(user, "employee")
        with db.connection(write=True) as conn:
            employee, data, as_of = load_employee(conn, user["employee_id"])
            choose_quest(conn, employee, data, as_of, body.event_id)
            return gamification_view(conn, employee, data, as_of)

    @app.delete("/api/me/gamification/quest")
    def cancel_personal_quest(user=Depends(auth.current_user)):
        auth.require_role(user, "employee")
        with db.connection(write=True) as conn:
            employee, data, as_of = load_employee(conn, user["employee_id"])
            clear_quest(conn, employee["employee_id"])
            return gamification_view(conn, employee, data, as_of)

    @app.get("/api/me/companion")
    def companion(user=Depends(auth.current_user)):
        auth.require_role(user, "employee")
        with db.connection() as conn:
            employee, data, as_of = load_employee(conn, user["employee_id"])
            return companion_view(conn, employee, data, as_of)

    @app.post("/api/me/companion/equip")
    def companion_equip(body: CompanionEquip, user=Depends(auth.current_user)):
        auth.require_role(user, "employee")
        with db.connection(write=True) as conn:
            employee, data, as_of = load_employee(conn, user["employee_id"])
            return equip_item(conn, employee, data, as_of, body.item_id)

    @app.post("/api/me/companion/chat")
    async def companion_chat(body: CompanionChat, user=Depends(auth.current_user)):
        auth.require_role(user, "employee")
        with db.connection() as conn:
            employee, data, as_of = load_employee(conn, user["employee_id"])
            context = recommendation_context(employee, data, as_of, revision(conn))
            context["skill_names"] = {key: value["name"] for key, value in data["skills"].items()}
            if body.event_id:
                context["candidates"].sort(key=lambda event: event["event_id"] != body.event_id)
            facts = compact_facts(context, companion_view(conn, employee, data, as_of))

        async def lines():
            async for item in app.state.companion_coach.stream(
                user["employee_id"], facts, body.message.strip(),
                [turn.model_dump() for turn in body.history], body.event_id, body.skill_id,
            ):
                yield json.dumps(item, ensure_ascii=False) + "\n"
        return StreamingResponse(lines(), media_type="application/x-ndjson", headers={"X-Accel-Buffering": "no"})

    @app.post("/api/me/activities/{event_id}/start")
    def start(event_id: str, body: Completion, user=Depends(auth.current_user)):
        auth.require_role(user, "employee")
        with db.connection(write=True) as conn:
            return start_activity(conn, user["employee_id"], event_id, body)

    @app.post("/api/me/activities/{event_id}/complete")
    def complete(event_id: str, body: Completion, idempotency_key: str | None = Header(default=None), user=Depends(auth.current_user)):
        auth.require_role(user, "employee")
        with db.connection(write=True) as conn:
            return complete_activity(conn, user["username"], user["employee_id"], event_id, body, idempotency_key)

    @app.get("/api/hr/employees")
    def employees(user=Depends(auth.current_user)):
        auth.require_role(user, "hr")
        with db.connection() as conn:
            return {"employees": [{k: e[k] for k in ("employee_id", "full_name", "role", "grade", "department")} for e in all_entities(conn, "employees").values()]}

    @app.get("/api/hr/employees/{employee_id}")
    def employee_profile(employee_id: str, user=Depends(auth.current_user)):
        auth.require_role(user, "hr")
        with db.connection() as conn:
            employee, data, as_of = load_employee(conn, employee_id)
            return profile_view(employee, data, as_of)

    @app.get("/api/hr/employees/{employee_id}/recommendation-context")
    def context_for_hr(employee_id: str, user=Depends(auth.current_user)):
        auth.require_role(user, "hr")
        with db.connection() as conn:
            employee, data, as_of = load_employee(conn, employee_id)
            return recommendation_context(employee, data, as_of, revision(conn))

    @app.get("/api/hr/overview")
    def overview(date_from: date | None = None, date_to: date | None = None, user=Depends(auth.current_user)):
        auth.require_role(user, "hr")
        if date_from and date_to and date_from > date_to:
            error(422, "invalid_period")
        with db.connection() as conn:
            as_of = get_meta(conn, "as_of_date")
            if as_of is None:
                error(409, "dataset_not_loaded")
            if date_to and date_to.isoformat() > as_of:
                error(422, "period_exceeds_snapshot")
            if date_from and date_from.isoformat() > (date_to.isoformat() if date_to else as_of):
                error(422, "invalid_period")
            return hr_overview(snapshot(conn), as_of, date_from.isoformat() if date_from else None, date_to.isoformat() if date_to else None)

    @app.post("/api/hr/import/validate")
    async def validate_import(files: list[UploadFile] = File(...), mode: str = Form("add"), user=Depends(auth.current_user)):
        auth.require_role(user, "hr")
        if mode not in {"add", "update"} or len(files) > 4:
            error(422, "invalid_import_options")
        uploads = {}
        for file in files:
            if file.filename in uploads:
                error(422, "duplicate_filename")
            content = await file.read(MAX_FILE_BYTES + 1)
            await file.close()
            if len(content) > MAX_FILE_BYTES:
                error(413, "file_too_large")
            uploads[file.filename] = content

        def validate_and_store():
            with db.connection(write=True) as conn:
                report, incoming = validate_files(conn, uploads, mode)
                if report["valid"]:
                    batch_id = uuid.uuid4().hex
                    conn.execute("DELETE FROM import_batches WHERE applied=0 AND created_at<?", (time.time() - 86400,))
                    conn.execute("INSERT INTO import_batches VALUES (?,?,?,?,?,0,?)", (batch_id, user["username"], revision(conn), encode(incoming), encode(report), time.time()))
                    report["batch_id"] = batch_id
                return report
        return await asyncio.to_thread(validate_and_store)

    @app.post("/api/hr/import/apply")
    def apply_import(body: ApplyImport, user=Depends(auth.current_user)):
        auth.require_role(user, "hr")
        with db.connection(write=True) as conn:
            batch = conn.execute("SELECT * FROM import_batches WHERE id=? AND username=?", (body.batch_id, user["username"])).fetchone()
            if batch is None:
                error(404, "batch_not_found")
            if batch["applied"]:
                return {"applied": True, "already_applied": True, "report": json.loads(batch["report"])}
            if batch["base_revision"] != revision(conn):
                error(409, "stale_import", "Data changed after validation; validate again")
            report = json.loads(batch["report"])
            apply_validated(conn, json.loads(batch["payload"]), report["as_of_date"])
            conn.execute("UPDATE import_batches SET applied=1 WHERE id=?", (body.batch_id,))
            return {"applied": True, "already_applied": False, "data_revision": revision(conn), "report": report}

    @app.post("/api/me/recommendations")
    async def recommendations(user=Depends(auth.current_user)):
        auth.require_role(user, "employee")
        with db.connection() as conn:
            employee, data, as_of = load_employee(conn, user["employee_id"])
            context = recommendation_context(employee, data, as_of, revision(conn))
            context_hash = auth.digest(encode(context))
            cached = conn.execute("SELECT response FROM recommendation_cache WHERE context_hash=?", (context_hash,)).fetchone()
        if not context["candidates"]:
            return {"status": "no_candidates", "mode": "none", "recommendations": [], "reasons": context["no_step_reasons"]}
        if cached:
            return {**json.loads(cached[0]), "cached": True}
        provider = app.state.recommender
        if provider is None:
            error(503, "ai_not_configured", "Connect the AI provider; no model result is fabricated")

        async def invoke():
            if inspect.iscoroutinefunction(provider):
                return await provider(context)
            value = await asyncio.to_thread(provider, context)
            return await value if inspect.isawaitable(value) else value

        try:
            result = await asyncio.wait_for(invoke(), timeout=settings.ai_timeout)
            parsed = AIResult.model_validate(result)
        except asyncio.TimeoutError:
            error(504, "ai_timeout")
        except ValidationError:
            error(502, "invalid_ai_response")
        except Exception:
            # Never expose provider exceptions: they can contain API keys/request bodies.
            error(502, "ai_provider_failed")
        allowed = {e["event_id"]: e for e in context["candidates"]}
        ids = [r.event_id for r in parsed.recommendations]
        if len(ids) != len(set(ids)) or not set(ids) <= allowed.keys():
            error(502, "invalid_ai_event")
        response = {
            "status": "ok", "mode": "ai", "data_revision": context["data_revision"], "cached": False,
            "recommendations": [{**r.model_dump(), "event": allowed[r.event_id]} for r in parsed.recommendations],
        }
        with db.connection(write=True) as conn:
            if revision(conn) != context["data_revision"]:
                error(409, "stale_recommendation", "Data changed during AI request; retry")
            conn.execute("INSERT OR REPLACE INTO recommendation_cache VALUES (?,?)", (context_hash, encode(response)))
        return response

    static_dir = settings.static_dir or Path(__file__).resolve().parents[1] / "frontend"
    if static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        if (static_dir / "index.html").is_file():
            return FileResponse(static_dir / "index.html")
        return {"application": "career-quest", "component": "backend", "ui_status": "not_connected", "api_docs": "/docs"}

    return app


app = create_app()
