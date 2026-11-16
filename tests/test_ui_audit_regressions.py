"""Focused UI regressions without live Telegram or provider requests."""
import os
from pathlib import Path
import runpy
import shutil
import subprocess
from types import SimpleNamespace

import pytest


def test_browser_module_override_without_cli(monkeypatch):
    monkeypatch.setenv("PLAYWRIGHT_MODULE", "/fixture/playwright")
    monkeypatch.setattr(shutil, "which", lambda command: "/fixture/node" if command == "node" else None)
    module = runpy.run_path(str(Path(__file__).with_name("test_frontend.py")))
    test = module["test_mobile_browser_workflows"]
    assert test.pytestmark[0].args[0] is False, "a module override must enable browser checks without the CLI"
    calls = []

    def run(*args, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", run)
    test()
    assert calls[0]["env"]["PLAYWRIGHT_MODULE"] == "/fixture/playwright"


@pytest.mark.skipif(shutil.which("node") is None or (not os.environ.get("PLAYWRIGHT_MODULE") and shutil.which("playwright") is None), reason="Node and Playwright required")
def test_ui_audit_browser_regressions():
    environment = os.environ.copy()
    if not environment.get("PLAYWRIGHT_MODULE"):
        environment["PLAYWRIGHT_MODULE"] = str(Path(shutil.which("playwright")).resolve().parent)
    result = subprocess.run(["node", str(Path(__file__).with_suffix(".cjs"))], env=environment, capture_output=True, text=True, timeout=120)
    if result.returncode == 77:
        pytest.skip(result.stdout.strip())
    assert result.returncode == 0, result.stdout + result.stderr
