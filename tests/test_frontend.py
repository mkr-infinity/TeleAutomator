"""Execute real dashboard JavaScript with a small DOM stub when Node is available."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is required for dashboard workflow tests")
def test_dashboard_workflows():
    script = Path(__file__).with_name("test_miniapp_frontend.cjs")
    result = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(shutil.which("node") is None or shutil.which("playwright") is None,
                    reason="Playwright and Node are required for mobile browser checks")
def test_mobile_browser_workflows():
    environment = os.environ.copy()
    environment.setdefault("PLAYWRIGHT_MODULE", str(Path(shutil.which("playwright")).resolve().parent))
    script = Path(__file__).with_name("test_miniapp_browser.cjs")
    result = subprocess.run(["node", str(script)], env=environment, capture_output=True, text=True, timeout=240)
    if result.returncode == 77:
        pytest.skip(result.stdout.strip())
    assert result.returncode == 0, result.stdout + result.stderr
