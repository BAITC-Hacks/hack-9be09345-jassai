"""Run launcher functions on Windows without launching servers or using a network."""

import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
PWSH = shutil.which("pwsh")
pytestmark = pytest.mark.skipif(sys.platform != "win32" or not PWSH, reason="Windows and pwsh are required for launcher/DPAPI tests")


# Import only the actual file's top-level function definitions. None of its
# setup, downloads, Read-Host, server startup or execution-policy handling runs.
FUNCTIONS = r"""
$ErrorActionPreference = 'Stop'
$script:LogPath = $null
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($env:CQ_TEST_LAUNCHER, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count -gt 0) { throw 'Launcher PowerShell syntax is invalid.' }
foreach ($statement in $ast.EndBlock.Statements) {
    if ($statement -is [System.Management.Automation.Language.FunctionDefinitionAst]) {
        . ([scriptblock]::Create($statement.Extent.Text))
    }
}
function Read-Host { throw 'Interactive input is forbidden in this test.' }
"""


def run_functions(code, **extra_env):
    env = dict(os.environ)
    env.pop("OPENAI_API_KEY", None)
    env.update(CQ_TEST_LAUNCHER=str(ROOT / "scripts" / "launcher.ps1"))
    env.update({key: str(value) for key, value in extra_env.items()})
    encoded = base64.b64encode((FUNCTIONS + code).encode("utf-16-le")).decode("ascii")
    result = subprocess.run(
        [PWSH, "-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        env=env, capture_output=True, text=True, encoding="utf-8", timeout=20,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    assert result.returncode == 0, result.stderr
    assert "launcher-unit-test-dummy-key" not in result.stdout + result.stderr
    return json.loads(result.stdout.strip())


CHECK_CONFIGURATION = r"""
$script:Request = $null
function Invoke-WebRequest {
    param([switch]$UseBasicParsing, [string]$Uri, [string]$Method, [hashtable]$Headers, [string]$ContentType, [string]$Body, [int]$TimeoutSec)
    $script:Request = @{
        uri = $Uri; method = $Method; content_type = $ContentType; timeout = $TimeoutSec
        authorized = $Headers.Authorization -eq 'Bearer launcher-unit-test-dummy-key'
        payload = $Body | ConvertFrom-Json
    }
    if ($env:CQ_TEST_FAILURE -eq 'error') { throw 'launcher-unit-test-dummy-key private-provider-error-body' }
    return [pscustomobject]@{Content = $env:CQ_TEST_RESPONSE}
}
$secure = ConvertTo-SecureString 'launcher-unit-test-dummy-key' -AsPlainText -Force
$valid = Test-OpenAiConfiguration -SecureKey $secure -Model 'gpt-6-luna'
@{valid = $valid; request = $script:Request} | ConvertTo-Json -Depth 20 -Compress
"""


def test_configuration_accepts_output_text_after_reasoning_and_validates_request():
    response = {
        "status": "completed",
        "output": [
            {"type": "reasoning", "summary": []},
            {"type": "message", "content": [{"type": "output_text", "text": '{"status":"ok"}'}]},
        ],
    }
    result = run_functions(CHECK_CONFIGURATION, CQ_TEST_RESPONSE=json.dumps(response))
    assert result["valid"] is True
    request = result["request"]
    assert request["uri"] == "https://api.openai.com/v1/responses"
    assert request["method"] == "Post" and request["content_type"] == "application/json"
    assert request["authorized"] is True and 0 < request["timeout"] <= 9
    payload = request["payload"]
    assert payload["model"] == "gpt-6-luna"
    assert payload["max_output_tokens"] >= 1024
    assert payload["reasoning"]["effort"] == "none"
    assert payload["store"] is False
    assert payload["text"]["format"]["strict"] is True
    assert "employee" not in payload["input"].lower()


@pytest.mark.parametrize("response", [
    {"status": "incomplete", "output_text": '{"status":"ok"}'},
    {"status": "completed", "output": []},
    {"status": "completed", "output_text": "not json"},
    {"status": "completed", "output_text": '{"status":"not-ok"}'},
    {"status": "completed", "output": [{"type": "message", "content": [{"type": "refusal", "refusal": "Cannot comply"}]}]},
])
def test_configuration_rejects_incomplete_empty_invalid_and_refused_responses(response):
    result = run_functions(CHECK_CONFIGURATION, CQ_TEST_RESPONSE=json.dumps(response))
    assert result["valid"] is False


def test_configuration_error_is_sanitized_without_secret_or_provider_body():
    result = run_functions(CHECK_CONFIGURATION, CQ_TEST_FAILURE="error", CQ_TEST_RESPONSE="{}")
    assert result["valid"] is False
    assert "private-provider-error-body" not in json.dumps(result)


def test_protected_key_dpapi_roundtrip_uses_saved_settings_without_input_or_network(tmp_path):
    folder = tmp_path / "Ключи и пробелы"
    folder.mkdir()
    result = run_functions(r"""
function Invoke-WebRequest { throw 'Network access is forbidden in the DPAPI test.' }
$secretPath = Join-Path $env:CQ_TEST_DIRECTORY 'dummy-key.dpapi'
$settingsPath = Join-Path $env:CQ_TEST_DIRECTORY 'ai-settings.json'
$secure = ConvertTo-SecureString 'launcher-unit-test-dummy-key' -AsPlainText -Force
$encrypted = $secure | ConvertFrom-SecureString
[IO.File]::WriteAllText($secretPath, $encrypted, [Text.Encoding]::ASCII)
@{model = 'saved-test-model'} | ConvertTo-Json | Set-Content -LiteralPath $settingsPath -Encoding UTF8
$restored = Get-ProtectedApiKey -SecretPath $secretPath -SettingsPath $settingsPath
@{
    restored = $restored -eq 'launcher-unit-test-dummy-key'
    encrypted = -not $encrypted.Contains('launcher-unit-test-dummy-key')
    model = $script:ConfiguredModel
} | ConvertTo-Json -Compress
""", CQ_TEST_DIRECTORY=folder)
    assert result == {"restored": True, "encrypted": True, "model": "saved-test-model"}
    assert b"launcher-unit-test-dummy-key" not in (folder / "dummy-key.dpapi").read_bytes()


def test_unreadable_protected_key_returns_fixed_error_without_echoing_contents(tmp_path):
    result = run_functions(r"""
function Invoke-WebRequest { throw 'Network access is forbidden in the DPAPI test.' }
$secretPath = Join-Path $env:CQ_TEST_DIRECTORY 'invalid-key.dpapi'
$settingsPath = Join-Path $env:CQ_TEST_DIRECTORY 'ai-settings.json'
[IO.File]::WriteAllText($secretPath, 'launcher-unit-test-dummy-key', [Text.Encoding]::ASCII)
@{model = 'saved-test-model'} | ConvertTo-Json | Set-Content -LiteralPath $settingsPath -Encoding UTF8
try {
    $null = Get-ProtectedApiKey -SecretPath $secretPath -SettingsPath $settingsPath
    @{failed = $false} | ConvertTo-Json -Compress
} catch {
    @{failed = $true; message = $_.Exception.Message} | ConvertTo-Json -Compress
}
""", CQ_TEST_DIRECTORY=tmp_path)
    assert result == {
        "failed": True,
        "message": "The protected AI key cannot be read for this Windows user. Run 'launcher.cmd /configure-ai' to replace it.",
    }
