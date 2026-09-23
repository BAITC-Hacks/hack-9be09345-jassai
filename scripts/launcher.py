"""Windows launcher after the tiny CMD/verified-uv bootstrap. Standard library only."""
from __future__ import annotations

from contextlib import contextmanager
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import getpass
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

PROJECT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = "gpt-6-luna"
INSTANCE = "hack-9be09345-jassai"
KEY_ERROR = "The protected AI key cannot be read for this Windows user. Run launcher.cmd /configure-ai to replace it."
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
AI_ENV_KEYS = (
    "OPENAI_API_KEY", "NVIDIA_API_KEY", "OPENAI_MODEL", "OPENAI_COMPANION_MODEL",
    "NVIDIA_COMPANION_MODEL", "CAREERQUEST_COMPANION_PROVIDER", "CAREERQUEST_RECOMMENDER",
)


class LauncherError(RuntimeError):
    """A fixed, safe message that can be shown in the console and log."""


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def atomic_write(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + ".new")
    temporary.write_bytes(value)
    temporary.replace(path)


def write_json(path, value):
    atomic_write(path, json.dumps(value, ensure_ascii=False).encode("utf-8"))


def clean_environment():
    env = dict(os.environ)
    for key in (*AI_ENV_KEYS, "CAREERQUEST_BOOTSTRAP_TOKEN"):
        env.pop(key, None)
    return env


class Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def dpapi(data: bytes, *, decrypt=False) -> bytes:
    """Current-user DPAPI, compatible with PowerShell ConvertFrom-SecureString."""
    if os.name != "nt":
        raise LauncherError("Protected key storage requires Windows.")
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    function = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    function.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    result = Blob()
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)):
        raise LauncherError(KEY_ERROR)
    try:
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        kernel32.LocalFree(result.pbData)


def save_key(secret_path, settings_path, key, model):
    # Keep the existing hex DPAPI / UTF-16 format and file names across upgrades.
    encrypted = dpapi(key.encode("utf-16-le")).hex().encode("ascii")
    old_key = secret_path.read_bytes() if secret_path.exists() else None
    old_settings = settings_path.read_bytes() if settings_path.exists() else None
    try:
        atomic_write(secret_path, encrypted)
        write_json(settings_path, {"model": model})
    except OSError:
        for path, old in ((secret_path, old_key), (settings_path, old_settings)):
            if old is None:
                path.unlink(missing_ok=True)
            else:
                atomic_write(path, old)
        raise LauncherError("Could not save the protected AI configuration. Check folder permissions.") from None


def load_key(secret_path, settings_path):
    try:
        model = read_json(settings_path).get("model", DEFAULT_MODEL) if settings_path.exists() else DEFAULT_MODEL
        key = dpapi(bytes.fromhex(secret_path.read_text(encoding="ascii").strip()), decrypt=True).decode("utf-16-le")
        if not key.strip() or not isinstance(model, str) or not model.strip():
            raise ValueError("empty configuration")
        return key, model.strip()
    except Exception:
        raise LauncherError(KEY_ERROR) from None


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file, code, message, headers, new_url):
        return None


def request_json(url, *, payload=None, key=None, timeout=2, local=False):
    handlers = [NoRedirect()]
    if local:
        handlers.append(urllib.request.ProxyHandler({}))
    headers = {"Accept": "application/json"}
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    if key:
        headers["Authorization"] = "Bearer " + key
    request = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.build_opener(*handlers).open(request, timeout=timeout) as response:
        content = response.read(65537)
    if len(content) > 65536:
        raise ValueError("Response exceeded its size limit")
    return json.loads(content)


def check_ai(key, model):
    payload = {
        "model": model, "input": "Return JSON with status set to ok.", "store": False,
        "max_output_tokens": 1024,
        "text": {"format": {"type": "json_schema", "name": "career_quest_launcher_check", "strict": True,
                            "schema": {"type": "object", "additionalProperties": False, "properties": {"status": {"type": "string"}}, "required": ["status"]}}},
    }
    if model == DEFAULT_MODEL:
        payload["reasoning"] = {"effort": "none"}
    try:
        response = request_json("https://api.openai.com/v1/responses", payload=payload, key=key, timeout=9)
        if response.get("status") != "completed":
            return False
        text = response.get("output_text") or "".join(
            item.get("text", "") for message in response.get("output", []) if message.get("type") == "message"
            for item in message.get("content", []) if item.get("type") == "output_text"
        )
        return json.loads(text) == {"status": "ok"}
    except Exception:
        return False  # Provider bodies and request headers may contain secrets.


def configuration(directory, mode, log, *, ask=None, hidden=None, check=None):
    ask, hidden, check = ask or input, hidden or getpass.getpass, check or check_ai
    secret, settings = directory / "openai-key.dpapi", directory / "ai-settings.json"
    if mode == "/check":
        return None, DEFAULT_MODEL
    if mode == "/disable-ai":
        if ask("Remove this app's saved AI key? Data and progress stay. [y/N] ").strip().lower() in {"y", "д"}:
            secret.unlink(missing_ok=True)
            settings.unlink(missing_ok=True)
            log("Removed the protected AI key; starting without AI.")
            return None, DEFAULT_MODEL
    if mode == "/configure-ai" or not secret.exists():
        if mode != "/configure-ai" and ask("Configure OpenAI now? You can start without AI. [y/N] ").strip().lower() not in {"y", "д"}:
            return None, DEFAULT_MODEL
        key = hidden("OpenAI API key (hidden; Enter starts without a new key): ").strip()
        if key:
            model = DEFAULT_MODEL
            if settings.exists():
                try:
                    model = read_json(settings).get("model") or DEFAULT_MODEL
                except (ValueError, OSError):
                    pass
            model = ask(f"Model ID [{model}]: ").strip() or model
            log("Checking the key and selected model without employee data.")
            if not check(key, model):
                raise LauncherError("AI configuration could not be verified. Saved settings were not changed. Check the network, API credits and model access.")
            save_key(secret, settings, key, model)
            log("Saved the Windows-user-protected AI configuration.")
        elif not secret.exists():
            return None, DEFAULT_MODEL
    return load_key(secret, settings) if secret.exists() else (None, DEFAULT_MODEL)


def process_identity(pid):
    """Executable and creation timestamp distinguish our process from a reused PID."""
    if os.name != "nt" or not isinstance(pid, int) or pid <= 0:
        return None
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return None
    try:
        name = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(name))
        times = [wintypes.FILETIME() for _ in range(4)]
        if not kernel.QueryFullProcessImageNameW(handle, 0, name, ctypes.byref(size)) or not kernel.GetProcessTimes(handle, *(ctypes.byref(item) for item in times)):
            return None
        return {"executable": os.path.normcase(os.path.abspath(name.value)), "created": (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime}
    finally:
        kernel.CloseHandle(handle)


def ready(port):
    if not isinstance(port, int) or not 1 <= port <= 65535:
        raise LauncherError("Invalid local server port.")
    base = f"http://127.0.0.1:{port}"
    health = request_json(base + "/health", local=True)
    if health.get("application") != "career-quest" or health.get("status") != "ok":
        raise LauncherError("The local port does not belong to Career Quest.")
    result = request_json(base + "/ready", local=True)
    if result.get("ready") is not True:
        raise LauncherError("The local application is not ready.")
    return result


def managed_instance(state, python_path):
    if not isinstance(state, dict) or not state.get("identity"):
        return False
    actual = process_identity(state.get("pid"))
    return bool(actual and actual == state["identity"] and actual["executable"] == os.path.normcase(str(python_path.resolve())))


def browser_url(port, directory, status):
    url = f"http://127.0.0.1:{port}/"
    token_path = directory / "setup-token.txt"
    if status.get("setup_required") and token_path.exists():
        token = token_path.read_text(encoding="utf-8").strip()
        if token:
            url += "#setup_token=" + urllib.parse.quote(token, safe="")
    return url


def check_ui(port):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    for route in ("/", "/static/app.js"):
        with opener.open(f"http://127.0.0.1:{port}{route}", timeout=5) as response:
            if response.status != 200 or not response.read(1):
                raise LauncherError("The server started but the UI is unavailable.")
    with opener.open(f"http://127.0.0.1:{port}/static/mascot-assets.json", timeout=5) as response:
        manifest = json.loads(response.read(16_384))
    model_url = manifest.get("modelUrl", "").split("?", 1)[0]
    if model_url != "/static/assets/mascot/character.glb":
        raise LauncherError("The 3D character is not configured. Extract the complete project ZIP.")
    with opener.open(f"http://127.0.0.1:{port}{model_url}", timeout=5) as response:
        if response.read(4) != b"glTF":
            raise LauncherError("The 3D character is missing or invalid. Extract the complete project ZIP.")


@contextmanager
def launcher_lock(path):
    import msvcrt
    with path.open("a+b") as stream:
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            raise LauncherError("Career Quest is already starting. Wait for its launcher window, then retry.") from None
        try:
            yield
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def sync_environment(project, directory, uv_path):
    env = clean_environment()
    env.update(UV_PROJECT_ENVIRONMENT=str(directory / "venv"), UV_CACHE_DIR=str(directory / "uv-cache"),
               UV_PYTHON_INSTALL_DIR=str(directory / "python"), UV_NO_PROGRESS="1")
    command = [str(uv_path), "sync", "--locked", "--no-dev", "--managed-python", "--project", str(project)]
    if subprocess.run(command, env=env, cwd=project).returncode:
        raise LauncherError("Dependency setup failed. First launch requires internet to GitHub and PyPI; retry after checking the network. Cached dependencies are reused on later launches.")
    python = directory / "venv" / "Scripts" / "python.exe"
    if not python.is_file():
        raise LauncherError("The managed Python environment is incomplete. Retry the launcher.")
    return python


def serve(project, directory, python, mode, key, model, log):
    env = clean_environment()
    env.update(CAREERQUEST_DATA_DIR=str(directory), CAREERQUEST_AI_TIMEOUT="9", OPENAI_MODEL=model,
               CAREERQUEST_COMPANION_PROVIDER="openai" if key else "none")
    if key:
        env.update(OPENAI_API_KEY=key, CAREERQUEST_RECOMMENDER="app.ai.provider:recommend")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    state_path = directory / "runtime" / "server.json"
    command = [str(python), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)]
    server = None
    with (directory / "logs" / "server.stdout.log").open("ab") as stdout, (directory / "logs" / "server.stderr.log").open("ab") as stderr:
        try:
            server = subprocess.Popen(command, cwd=project, env=env, stdout=stdout, stderr=stderr, creationflags=NO_WINDOW)
            env.pop("OPENAI_API_KEY", None)
            key = None
            identity = process_identity(server.pid)
            if identity is None:
                raise LauncherError("Could not identify the managed server process.")
            write_json(state_path, {"pid": server.pid, "port": port, "identity": identity, "project": str(project)})
            deadline = time.monotonic() + 30
            status = None
            while time.monotonic() < deadline:
                if server.poll() is not None:
                    raise LauncherError("The server stopped during startup. See logs/server.stderr.log in the application data folder.")
                try:
                    status = ready(port)
                    break
                except (OSError, ValueError, LauncherError):
                    time.sleep(0.25)
            if status is None:
                raise LauncherError("The server did not become ready in 30 seconds. See logs/server.stderr.log.")
            check_ui(port)
            if mode == "/check":
                log("Launcher check passed: server and UI are ready. No AI request or browser interaction was performed.")
                return
            log(f"Career Quest is ready on 127.0.0.1:{port}. Opening the browser.")
            webbrowser.open(browser_url(port, directory, status))  # Never log the setup-token URL.
            log("Keep this window open. Press Ctrl+C to stop this server; data is preserved.")
            server.wait()
            if server.returncode:
                raise LauncherError("The application stopped unexpectedly. See logs/server.stderr.log.")
        except KeyboardInterrupt:
            log("Stopping this Career Quest instance. Saved data is preserved.")
        finally:
            env.pop("OPENAI_API_KEY", None)
            if server is not None:
                if server.poll() is None:
                    server.terminate()
                    try:
                        server.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        server.kill()
                        server.wait(timeout=5)
                try:
                    if read_json(state_path).get("pid") == server.pid:
                        state_path.unlink()
                except (OSError, ValueError):
                    pass


def main(argv=None):
    mode = ((sys.argv[1:] if argv is None else argv) or [""])[0].lower()
    if mode not in {"", "/check", "/configure-ai", "/disable-ai"}:
        print("Use launcher.cmd /help for supported options.")
        return 2
    if os.name != "nt":
        print("Use launcher.cmd on Windows 10/11 x64.")
        return 1
    for name in AI_ENV_KEYS:
        os.environ.pop(name, None)
    base = os.environ.get("CAREERQUEST_DATA_DIR")
    if not base:
        local = os.environ.get("LOCALAPPDATA")
        if not local:
            print("The Windows LOCALAPPDATA folder is unavailable. Set CAREERQUEST_DATA_DIR to a writable data folder.")
            return 1
        base = Path(local) / "CareerQuest" / "instances" / INSTANCE
    directory = Path(base).resolve()
    log_path = directory / "logs" / "launcher.log"

    def log(message):
        line = datetime.now(timezone.utc).isoformat(timespec="seconds") + " " + message
        print(line, flush=True)
        with log_path.open("a", encoding="utf-8") as output:
            output.write(line + "\n")

    try:
        for child in ("logs", "settings", "runtime"):
            (directory / child).mkdir(parents=True, exist_ok=True)
        log("Starting Career Quest launcher.")
        for name in ("pyproject.toml", "uv.lock", ".python-version", "app/main.py", "frontend/index.html"):
            if not (PROJECT / name).is_file():
                raise LauncherError(f"Required file missing: {name}. Extract the complete ZIP before launching.")
        state = None
        try:
            state = read_json(directory / "runtime" / "server.json")
        except (OSError, ValueError):
            pass
        python = directory / "venv" / "Scripts" / "python.exe"
        if isinstance(state, dict) and not state.get("identity") and process_identity(state.get("pid")):
            raise LauncherError("A process from the previous launcher is still running. Stop the old launcher before starting this version; saved data is preserved.")
        if managed_instance(state, python):
            if mode in {"/configure-ai", "/disable-ai"}:
                raise LauncherError("Stop the running instance with Ctrl+C before changing its AI configuration.")
            if state.get("project") != str(PROJECT):
                raise LauncherError("Another copy of Career Quest is running. Stop its launcher with Ctrl+C before opening this copy.")
            try:
                status = ready(state["port"])
                check_ui(state["port"])
            except (OSError, ValueError, LauncherError):
                raise LauncherError("Career Quest is already running but is not ready. Wait or stop its launcher with Ctrl+C, then retry.") from None
            if mode != "/check":
                webbrowser.open(browser_url(state["port"], directory, status))
            log("Existing managed Career Quest instance passed readiness and UI checks.")
            return 0
        with launcher_lock(directory / "runtime" / "launcher.lock"):
            log("Preparing pinned Python dependencies; later launches reuse the local cache.")
            python = sync_environment(PROJECT, directory, Path(os.environ["CQ_UV_PATH"]))
            key, model = configuration(directory / "settings", mode, log)
            serve(PROJECT, directory, python, mode, key, model, log)
        return 0
    except LauncherError as exc:
        message = str(exc)
    except KeyboardInterrupt:
        message = "Startup cancelled. Run launcher.cmd again when ready."
    except Exception as exc:
        message = f"Startup failed ({type(exc).__name__}). Check folder permissions and the README; no protected credentials were printed."
    try:
        log("ERROR: " + message)
    except OSError:
        print("ERROR: " + message)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
