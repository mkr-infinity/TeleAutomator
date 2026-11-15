"""Execute real dashboard JavaScript with a small DOM stub when Node is available."""

import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is required for dashboard workflow tests")
def test_dashboard_workflows():
    script = Path(__file__).with_name("test_miniapp_frontend.cjs")
    result = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
