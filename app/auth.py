import hashlib
import hmac
import secrets
import time

from fastapi import Header, HTTPException, Request

from app.db import get_meta, set_meta

SESSION_COOKIE = "careerquest_session"


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    key = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1).hex()
    return f"scrypt${salt}${key}"


def verify_password(password, encoded):
    _, salt, _ = encoded.split("$")
    return hmac.compare_digest(password_hash(password, salt), encoded)


def enforce_password(password):
    if len(password) < 10:
        raise HTTPException(422, detail={"code": "weak_password", "message": "Password must contain at least 10 characters"})


def initialize_bootstrap(db, settings):
    with db.connection(write=True) as conn:
        if conn.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            return
        # Preserve an unconsumed generated token across restarts. Launcher can supply its own.
        token_file = settings.data_dir / "setup-token.txt"
        token = settings.bootstrap_token
        if token is None:
            token = token_file.read_text(encoding="utf-8").strip() if token_file.exists() else secrets.token_urlsafe(32)
            if not token_file.exists():
                token_file.write_text(token, encoding="utf-8")
                token_file.chmod(0o600)
        set_meta(conn, "bootstrap_hash", digest(token))


def new_session(conn, username):
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    conn.execute("DELETE FROM sessions WHERE expires_at<?", (time.time(),))
    conn.execute("INSERT INTO sessions VALUES (?,?,?,?)", (digest(token), username, csrf, time.time() + 8 * 3600))
    return token, csrf


def set_session_cookie(response, request, token):
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="strict", secure=request.url.scheme == "https", max_age=8 * 3600, path="/")


def current_user(request: Request, x_csrf_token: str | None = Header(default=None, description="CSRF token returned by login/session; required for mutations")):
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(401, detail={"code": "authentication_required"})
    with request.app.state.db.connection() as conn:
        row = conn.execute(
            "SELECT u.username,u.role,u.employee_id,s.csrf_token FROM sessions s JOIN users u USING(username) WHERE s.token_hash=? AND s.expires_at>?",
            (digest(token), time.time()),
        ).fetchone()
    if row is None:
        raise HTTPException(401, detail={"code": "session_expired"})
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        csrf = x_csrf_token or ""
        if not hmac.compare_digest(csrf, row["csrf_token"]):
            raise HTTPException(403, detail={"code": "csrf_failed"})
    return dict(row)


def require_role(user, role):
    if user["role"] != role:
        raise HTTPException(403, detail={"code": "role_forbidden"})


def bootstrap_allowed(conn, token):
    stored = get_meta(conn, "bootstrap_hash")
    return not conn.execute("SELECT 1 FROM users LIMIT 1").fetchone() and stored and hmac.compare_digest(stored, digest(token))
