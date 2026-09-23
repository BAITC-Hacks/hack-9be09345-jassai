"""Real launcher functions: no public network or real API credentials are used."""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
from types import SimpleNamespace
import urllib.parse

import pytest

from scripts import launcher

ROOT = Path(__file__).resolve().parents[1]
DUMMY = "launcher-unit-test-dummy-key"
WINDOWS = pytest.mark.skipif(sys.platform != "win32", reason="Windows runtime required")


def forbidden(*args, **kwargs):
    pytest.fail("Unexpected input, secret access or external request")


def test_configuration_accepts_message_after_reasoning_and_sends_private_bounded_request(monkeypatch):
    calls = []

    def response(url, **kwargs):
        calls.append((url, kwargs))
        return {"status": "completed", "output": [
            {"type": "reasoning", "summary": []},
            {"type": "message", "content": [{"type": "output_text", "text": '{"status":"ok"}'}]},
        ]}

    monkeypatch.setattr(launcher, "request_json", response)
    assert launcher.check_ai(DUMMY, launcher.DEFAULT_MODEL)
    url, args = calls[0]
    assert url == "https://api.openai.com/v1/responses"
    assert args["key"] == DUMMY and 0 < args["timeout"] <= 9
    payload = args["payload"]
    assert payload["model"] == launcher.DEFAULT_MODEL
    assert payload["max_output_tokens"] >= 1024
    assert payload["reasoning"] == {"effort": "none"}
    assert payload["store"] is False and payload["text"]["format"]["strict"] is True
    assert "employee" not in payload["input"].lower()


@pytest.mark.parametrize("response", [
    {"status": "incomplete", "output_text": '{"status":"ok"}'},
    {"status": "completed", "output": []},
    {"status": "completed", "output_text": "not json"},
    {"status": "completed", "output_text": '{"status":"not-ok"}'},
    {"status": "completed", "output": [{"type": "message", "content": [{"type": "refusal", "refusal": "No"}]}]},
])
def test_configuration_rejects_partial_invalid_and_refused_responses(monkeypatch, response):
    monkeypatch.setattr(launcher, "request_json", lambda *a, **kw: response)
    assert launcher.check_ai(DUMMY, launcher.DEFAULT_MODEL) is False


def test_provider_failure_does_not_print_secrets_or_response_body(monkeypatch, capsys):
    def failing(*args, **kwargs):
        raise RuntimeError(DUMMY + " private-provider-body")

    monkeypatch.setattr(launcher, "request_json", failing)
    assert launcher.check_ai(DUMMY, launcher.DEFAULT_MODEL) is False
    assert capsys.readouterr() == ("", "")


@WINDOWS
def test_dpapi_roundtrip_and_legacy_powershell_key_format(tmp_path):
    folder = tmp_path / "Ключи с пробелами"
    folder.mkdir()
    secret, settings = folder / "openai-key.dpapi", folder / "ai-settings.json"
    launcher.save_key(secret, settings, DUMMY, "saved-test-model")
    assert DUMMY.encode() not in secret.read_bytes()
    assert launcher.load_key(secret, settings) == (DUMMY, "saved-test-model")
    powershell = shutil.which("powershell.exe")
    if powershell:
        env = launcher.clean_environment()
        env["PSModulePath"] = os.environ["SystemRoot"] + "\\System32\\WindowsPowerShell\\v1.0\\Modules"
        env["CQ_TEST_KEY_FILE"] = str(secret)
        result = subprocess.run([
            powershell, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command",
            "$secure = ConvertTo-SecureString 'launcher-unit-test-dummy-key' -AsPlainText -Force; "
            "[IO.File]::WriteAllText($env:CQ_TEST_KEY_FILE, ($secure | ConvertFrom-SecureString), [Text.Encoding]::ASCII)",
        ], env=env, capture_output=True, text=True, timeout=15, creationflags=launcher.NO_WINDOW)
        assert result.returncode == 0, result.stderr
        assert DUMMY not in result.stdout + result.stderr
        assert launcher.load_key(secret, settings) == (DUMMY, "saved-test-model")


def test_check_mode_never_reads_saved_key_prompts_or_calls_ai(tmp_path, monkeypatch):
    (tmp_path / "openai-key.dpapi").write_text(DUMMY)
    monkeypatch.setattr(launcher, "load_key", forbidden)
    assert launcher.configuration(tmp_path, "/check", forbidden, ask=forbidden, hidden=forbidden, check=forbidden) == (None, launcher.DEFAULT_MODEL)


def test_rejected_new_key_preserves_existing_settings(tmp_path):
    secret, settings = tmp_path / "openai-key.dpapi", tmp_path / "ai-settings.json"
    secret.write_bytes(b"previous protected key")
    settings.write_text('{"model":"previous-model"}')
    before = secret.read_bytes(), settings.read_bytes()
    logs = []
    with pytest.raises(launcher.LauncherError, match="Saved settings were not changed"):
        launcher.configuration(tmp_path, "/configure-ai", logs.append, ask=lambda _: "", hidden=lambda _: DUMMY, check=lambda key, model: False)
    assert (secret.read_bytes(), settings.read_bytes()) == before
    assert DUMMY not in " ".join(logs)


def test_disable_ai_preserves_database_and_other_state(tmp_path):
    for name in ("openai-key.dpapi", "ai-settings.json", "app.db", "progress.json"):
        (tmp_path / name).write_text("preserve unless key")
    assert launcher.configuration(tmp_path, "/disable-ai", lambda _: None, ask=lambda _: "y", hidden=forbidden, check=forbidden) == (None, launcher.DEFAULT_MODEL)
    assert not (tmp_path / "openai-key.dpapi").exists()
    assert not (tmp_path / "ai-settings.json").exists()
    assert (tmp_path / "app.db").read_text() == "preserve unless key"
    assert (tmp_path / "progress.json").exists()


def test_unreadable_key_returns_fixed_error_without_its_contents(tmp_path):
    secret, settings = tmp_path / "key.dpapi", tmp_path / "settings.json"
    secret.write_text(DUMMY)
    with pytest.raises(launcher.LauncherError) as error:
        launcher.load_key(secret, settings)
    assert str(error.value) == launcher.KEY_ERROR
    assert DUMMY not in str(error.value)


def test_sync_uses_locked_external_environment_and_removes_inherited_secrets(tmp_path, monkeypatch):
    python = tmp_path / "venv" / "Scripts" / "python.exe"
    python.parent.mkdir(parents=True)
    python.touch()
    monkeypatch.setenv("OPENAI_API_KEY", DUMMY)
    monkeypatch.setenv("CAREERQUEST_RECOMMENDER", "untrusted:callable")
    monkeypatch.setenv("CAREERQUEST_BOOTSTRAP_TOKEN", "inherited-token")
    calls = []
    monkeypatch.setattr(launcher.subprocess, "run", lambda command, **kw: calls.append((command, kw)) or SimpleNamespace(returncode=0))
    uv = tmp_path / "tools" / "uv.exe"
    assert launcher.sync_environment(ROOT, tmp_path, uv) == python
    command, args = calls[0]
    assert command == [str(uv), "sync", "--locked", "--no-dev", "--managed-python", "--project", str(ROOT)]
    env = args["env"]
    assert env["UV_PROJECT_ENVIRONMENT"] == str(tmp_path / "venv")
    assert env["UV_PYTHON_INSTALL_DIR"] == str(tmp_path / "python")
    assert env["UV_CACHE_DIR"] == str(tmp_path / "uv-cache")
    assert not {"OPENAI_API_KEY", "CAREERQUEST_RECOMMENDER", "CAREERQUEST_BOOTSTRAP_TOKEN"} & env.keys()


def test_sync_network_failure_has_actionable_safe_message(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=1))
    with pytest.raises(launcher.LauncherError, match="internet to GitHub and PyPI"):
        launcher.sync_environment(ROOT, tmp_path, Path("uv.exe"))


def test_managed_process_requires_matching_executable_creation_time_and_pid(tmp_path, monkeypatch):
    python = tmp_path / "python.exe"
    identity = {"executable": os.path.normcase(str(python.resolve())), "created": 123}
    monkeypatch.setattr(launcher, "process_identity", lambda pid: identity if pid == 17 else None)
    state = {"pid": 17, "identity": dict(identity)}
    assert launcher.managed_instance(state, python)
    assert not launcher.managed_instance({**state, "pid": 18}, python)
    assert not launcher.managed_instance({**state, "identity": {**identity, "created": 124}}, python)
    assert not launcher.managed_instance(state, tmp_path / "other.exe")


@WINDOWS
def test_process_identity_reads_real_windows_process():
    identity = launcher.process_identity(os.getpid())
    assert identity and identity["created"] > 0
    assert Path(identity["executable"]).name.lower() == "python.exe"
    assert launcher.process_identity(-1) is None
    assert launcher.process_identity(None) is None


def test_ready_requires_product_identity_and_readiness(monkeypatch):
    calls = []
    def response(url, **kwargs):
        calls.append((url, kwargs))
        return {"application": "career-quest", "status": "ok"} if url.endswith("/health") else {"ready": True}
    monkeypatch.setattr(launcher, "request_json", response)
    assert launcher.ready(8000) == {"ready": True}
    assert all(args["local"] for _, args in calls)
    monkeypatch.setattr(launcher, "request_json", lambda *a, **kw: {"application": "another-app", "status": "ok"})
    with pytest.raises(launcher.LauncherError, match="does not belong"):
        launcher.ready(8000)


def test_setup_token_stays_in_fragment_and_is_omitted_after_setup(tmp_path):
    token = "dummy-token/with+chars"
    (tmp_path / "setup-token.txt").write_text(token)
    url = urllib.parse.urlsplit(launcher.browser_url(54321, tmp_path, {"setup_required": True}))
    assert url.hostname == "127.0.0.1" and url.query == ""
    assert urllib.parse.parse_qs(url.fragment) == {"setup_token": [token]}
    assert launcher.browser_url(54321, tmp_path, {"setup_required": False}) == "http://127.0.0.1:54321/"


@WINDOWS
def test_check_starts_real_server_checks_ui_and_closes_port_and_process(tmp_path, monkeypatch):
    directory = tmp_path / "Данные с пробелами"
    for name in ("logs", "runtime", "settings"):
        (directory / name).mkdir(parents=True)
    monkeypatch.setattr(launcher.webbrowser, "open", forbidden)
    monkeypatch.setenv("OPENAI_API_KEY", DUMMY)
    monkeypatch.setenv("CAREERQUEST_RECOMMENDER", "must_not_be_loaded:invalid")
    logs, started, ports = [], [], []
    real_identity, real_ready = launcher.process_identity, launcher.ready
    def identity(pid):
        started.append(pid)
        return real_identity(pid)
    def ready(port):
        ports.append(port)
        state = launcher.read_json(directory / "runtime" / "server.json")
        assert launcher.managed_instance(state, Path(sys.executable)), "The real venv process cannot be safely recognized for reuse"
        return real_ready(port)
    monkeypatch.setattr(launcher, "process_identity", identity)
    monkeypatch.setattr(launcher, "ready", ready)
    launcher.serve(ROOT, directory, Path(sys.executable), "/check", None, launcher.DEFAULT_MODEL, logs.append)
    assert any("Launcher check passed" in text for text in logs)
    assert started and real_identity(started[0]) is None
    with socket.socket() as connection:
        connection.settimeout(1)
        assert connection.connect_ex(("127.0.0.1", ports[-1])) != 0, "A child server remained alive after launcher cleanup"
    assert not (directory / "runtime" / "server.json").exists()
    assert (directory / "setup-token.txt").is_file()
    assert list(directory.glob("*.sqlite3")) or list(directory.glob("*.db"))
    for path in (directory / "logs").glob("*.log"):
        assert DUMMY not in path.read_text(encoding="utf-8")


@WINDOWS
def test_cmd_help_does_not_create_data_or_require_python_or_pwsh(tmp_path):
    env = launcher.clean_environment()
    env["CAREERQUEST_DATA_DIR"] = str(tmp_path / "should-not-exist")
    env["PATH"] = os.environ["SystemRoot"] + "\\System32"
    result = subprocess.run([os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", str(ROOT / "launcher.cmd"), "/help"], env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert "/configure-ai" in result.stdout and "/disable-ai" in result.stdout and "/check" in result.stdout
    assert "First launch needs internet" in result.stdout
    assert not (tmp_path / "should-not-exist").exists()


@WINDOWS
def test_launcher_lock_blocks_second_start_and_releases_after_failure(tmp_path):
    path = tmp_path / "launcher.lock"
    with pytest.raises(RuntimeError, match="test startup failure"):
        with launcher.launcher_lock(path):
            with pytest.raises(launcher.LauncherError, match="already starting"):
                with launcher.launcher_lock(path):
                    pytest.fail("Second launcher acquired the same lock")
            raise RuntimeError("test startup failure")
    with launcher.launcher_lock(path):
        pass


@WINDOWS
def test_live_legacy_server_state_stops_upgrade_before_dependency_or_database_change(tmp_path, monkeypatch, capsys):
    (tmp_path / "runtime").mkdir()
    state = {"pid": os.getpid(), "port": 12345, "python_path": sys.executable}
    launcher.write_json(tmp_path / "runtime" / "server.json", state)
    monkeypatch.setenv("CAREERQUEST_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(launcher, "sync_environment", forbidden)
    monkeypatch.setattr(launcher, "serve", forbidden)
    assert launcher.main(["/check"]) == 1
    assert "previous launcher is still running" in capsys.readouterr().out
    assert launcher.read_json(tmp_path / "runtime" / "server.json") == state


@WINDOWS
def test_managed_server_is_reused_only_after_health_and_ui_checks(tmp_path, monkeypatch):
    (tmp_path / "runtime").mkdir()
    python = tmp_path / "venv" / "Scripts" / "python.exe"
    identity = {"executable": os.path.normcase(str(python.resolve())), "created": 987}
    state = {"pid": 1234, "port": 12345, "identity": identity, "project": str(ROOT)}
    launcher.write_json(tmp_path / "runtime" / "server.json", state)
    monkeypatch.setenv("CAREERQUEST_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(launcher, "process_identity", lambda pid: identity if pid == 1234 else None)
    monkeypatch.setattr(launcher, "sync_environment", forbidden)
    monkeypatch.setattr(launcher, "serve", forbidden)
    monkeypatch.setattr(launcher.webbrowser, "open", forbidden)
    calls = []
    monkeypatch.setattr(launcher, "ready", lambda port: calls.append(("ready", port)) or {"ready": True})
    monkeypatch.setattr(launcher, "check_ui", lambda port: calls.append(("ui", port)))
    assert launcher.main(["/check"]) == 0
    assert calls == [("ready", 12345), ("ui", 12345)]
    assert launcher.read_json(tmp_path / "runtime" / "server.json") == state
