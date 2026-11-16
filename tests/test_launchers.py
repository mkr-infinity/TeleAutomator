"""Offline regression checks for launchers and container prerequisites."""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_launcher(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location("launcher_under_test", ROOT / "run.py")
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    monkeypatch.setattr(launcher, "ROOT_DIR", tmp_path)
    python = tmp_path / ".venv" / "bin" / "python3"
    python.parent.mkdir(parents=True)
    python.touch()
    monkeypatch.setattr(launcher, "get_venv_python", lambda: python)
    (tmp_path / "requirements.txt").write_text("example-package\n")
    return launcher, python


def test_failed_dependency_install_is_retried_without_recreating_venv(monkeypatch, tmp_path):
    launcher, python = load_launcher(monkeypatch, tmp_path)
    calls = []

    def install(command, **kwargs):
        assert kwargs["cwd"] == tmp_path
        calls.append(command)
        if len(calls) == 2:
            raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(launcher.subprocess, "check_call", install)
    with pytest.raises(subprocess.CalledProcessError):
        launcher.ensure_environment()
    marker = tmp_path / ".venv" / ".requirements-installed"
    assert not marker.exists()
    assert launcher.ensure_environment() == python
    assert len(calls) == 4
    assert marker.read_bytes() == (tmp_path / "requirements.txt").read_bytes()
    launcher.ensure_environment()
    assert len(calls) == 4
    (tmp_path / "requirements.txt").write_text("changed-package\n")
    launcher.ensure_environment()
    assert len(calls) == 6
    launcher.ensure_environment(force_install=True)
    assert len(calls) == 8


@pytest.mark.parametrize("flags,expected", [
    ([], ["-m", "app.main"]),
    (["--auth"], [str(ROOT / "scripts/authenticate.py")]),
    (["--session"], [str(ROOT / "scripts/generate_session.py")]),
    (["--new-session"], [str(ROOT / "scripts/generate_session.py"), "--new"]),
    (["--test"], ["-m", "pytest", str(ROOT / "tests")]),
    (["--check"], [str(ROOT / "scripts/check_connection.py")]),
])
def test_all_child_commands_use_repository_cwd(monkeypatch, tmp_path, flags, expected):
    launcher, python = load_launcher(monkeypatch, tmp_path)
    monkeypatch.setattr(launcher, "ROOT_DIR", ROOT)
    monkeypatch.setattr(launcher, "ensure_environment", lambda **kwargs: python)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["run.py", *flags])
    calls = []
    monkeypatch.setattr(launcher.subprocess, "call", lambda cmd, **kw: calls.append((cmd, kw)) or 7)
    with pytest.raises(SystemExit) as error:
        launcher.main()
    assert error.value.code == 7
    assert calls == [([str(python), *expected], {"cwd": ROOT})]


def entrypoint(tmp_path, **overrides):
    environment = {"PATH": os.environ["PATH"], "DATA_DIR": str(tmp_path), **overrides}
    return subprocess.run(["sh", str(ROOT / "entrypoint.sh"), "sh", "-c", "echo child-started"],
                          env=environment, text=True, capture_output=True)


def test_entrypoint_missing_local_session_cannot_start_child(tmp_path):
    result = entrypoint(tmp_path)
    assert result.returncode != 0
    assert "Local session missing" in result.stderr
    assert "child-started" not in result.stdout
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("session_name", ["custom", "custom.session", "custom.dotted"])
def test_entrypoint_existing_host_session_and_string_modes(tmp_path, session_name):
    filename = session_name if session_name.endswith(".session") else session_name + ".session"
    (tmp_path / filename).write_text("offline fixture")
    result = entrypoint(tmp_path, TG_SESSION_MODE="local", TG_SESSION_NAME=session_name)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "child-started"
    result = entrypoint(tmp_path, TG_SESSION_STRING="offline fixture")
    assert result.returncode == 0, result.stderr
    result = entrypoint(tmp_path, TG_SESSION_MODE="string")
    assert result.returncode != 0
    assert "TG_SESSION_STRING is empty" in result.stderr


@pytest.mark.parametrize("environment", [
    {"REQUIRE_PERSISTENT_STORAGE": "true"},
    {"RAILWAY_ENVIRONMENT_ID": "fixture"},
    {"RENDER": "true"},
])
def test_entrypoint_rejects_ephemeral_cloud_storage(tmp_path, environment):
    result = entrypoint(tmp_path, TG_SESSION_STRING="offline fixture", **environment)
    assert result.returncode != 0
    assert "Mount a persistent volume" in result.stderr
    assert "child-started" not in result.stdout


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="PowerShell not installed")
@pytest.mark.parametrize("failure", ["version", "venv"])
def test_powershell_rejects_old_python_and_failed_venv_from_other_cwd(tmp_path, failure):
    project = tmp_path / "project"
    project.mkdir()
    shutil.copyfile(ROOT / "setup.ps1", project / "setup.ps1")
    # Functions shadow real Python: no interpreter, installer, or network is run.
    driver = tmp_path / "driver.ps1"
    driver.write_text('''
function python {
    if ($args -contains "venv") { $global:LASTEXITCODE = 1 }
    else { $global:LASTEXITCODE = VERSION_EXIT }
}
function py { $global:LASTEXITCODE = 1 }
& (Join-Path $PSScriptRoot "project/setup.ps1")
'''.replace("VERSION_EXIT", "1" if failure == "version" else "0"))
    result = subprocess.run(["pwsh", "-NoProfile", "-File", str(driver)], cwd=tmp_path,
                            text=True, capture_output=True)
    assert result.returncode != 0
    assert "Setup complete!" not in result.stdout
    assert not (tmp_path / ".venv").exists()
    assert not (project / ".env").exists()


def test_cloud_with_provisioned_mount_still_requires_string_session(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    mount_probe = fake_bin / "python3"
    mount_probe.write_text("#!/bin/sh\nexit 0\n")
    mount_probe.chmod(0o700)
    # Simulate a successful mount probe without mounting or contacting a service.
    environment = {"PATH": str(fake_bin) + os.pathsep + os.environ["PATH"], "RENDER": "true"}
    result = entrypoint(tmp_path, TG_SESSION_MODE="local", **environment)
    assert result.returncode != 0
    assert "Hosted deployments require" in result.stderr
    result = entrypoint(tmp_path, TG_SESSION_MODE="string", **environment)
    assert result.returncode != 0
    assert "TG_SESSION_STRING is empty" in result.stderr
    result = entrypoint(tmp_path, TG_SESSION_STRING="offline fixture", **environment)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "child-started"


def test_root_start_fixes_volume_ownership_then_drops_privileges(tmp_path):
    """Railway mounts volumes as root: chown once, then re-run as UID 10001 before any app code."""
    fake_bin, log = tmp_path / "bin", tmp_path / "calls.log"
    fake_bin.mkdir()
    scripts = {
        "id": 'echo "${FAKE_UID:-0}"',
        "stat": "echo 0",
        "chown": f'echo "chown $*" >> {log}',
        "chmod": "exit 0",
        "setpriv": f'echo "setpriv $*" >> {log}; shift 3; FAKE_UID=10001; export FAKE_UID; exec "$@"',
    }
    for name, body in scripts.items():
        (fake_bin / name).write_text("#!/bin/sh\n" + body + "\n")
        (fake_bin / name).chmod(0o700)
    data = tmp_path / "data"
    result = entrypoint(tmp_path, DATA_DIR=str(data), TG_SESSION_STRING="offline fixture",
                        PATH=str(fake_bin) + os.pathsep + os.environ["PATH"])
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "child-started"
    calls = log.read_text()
    assert f"chown -R 10001:10001 {data}" in calls
    assert "setpriv --reuid=10001 --regid=10001 --clear-groups" in calls


def test_railway_volume_path_overrides_data_dir(tmp_path):
    volume = tmp_path / "volume"
    result = entrypoint(tmp_path, RAILWAY_VOLUME_MOUNT_PATH=str(volume), TG_SESSION_STRING="offline fixture")
    assert result.returncode == 0, result.stderr
    assert volume.is_dir() and not (tmp_path / "data").exists()
