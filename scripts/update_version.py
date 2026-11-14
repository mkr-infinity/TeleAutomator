#!/usr/bin/env python3
"""Keep the project version in sync everywhere.

Single source of truth: `app/__init__.py` (`__version__`).

What gets synced/checked:
  - pyproject.toml                       -> version = "X.Y.Z"
  - assets/banner.svg                    -> "TELEAUTOMATOR vX.Y" branding text
  - everything else is DYNAMIC by design (startup banner, welcome cards,
    /status, /prompt all read app.__version__ at runtime — never bump by hand)

Usage:
  python3 scripts/update_version.py            # sync + scan for stale versions
  python3 scripts/update_version.py 2.9.0      # set a new version everywhere first

Exit code 1 if stale hardcoded versions are found anywhere (CI-friendly check).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INIT_FILE = ROOT / "app" / "__init__.py"
PYPROJECT_FILE = ROOT / "pyproject.toml"
CITATION_FILE = ROOT / "CITATION.cff"
INDEX_HTML = ROOT / "miniapp" / "index.html"
APP_JS = ROOT / "miniapp" / "app.js"
SW_JS = ROOT / "miniapp" / "sw.js"
BANNER_SVG = ROOT / "assets" / "banner.svg"

# Files/dirs never scanned (venvs, caches, git internals)
SCAN_EXCLUDES = {".git", ".venv", "__pycache__", "node_modules", ".pytest_cache", "data"}


def current_version() -> str:
    """Read the version from the single source of truth (app/__init__.py)."""
    match = re.search(r'__version__\s*=\s*"([^"]+)"', INIT_FILE.read_text(encoding="utf-8"))
    if not match:
        raise SystemExit(f"ERROR: could not find __version__ in {INIT_FILE}")
    return match.group(1)


def set_version(new_version: str) -> None:
    """Write a new version into the single source of truth, then sync every static copy."""
    if not re.fullmatch(r"\d+\.\d+\.\d+", new_version):
        raise SystemExit(f"ERROR: '{new_version}' is not a valid X.Y.Z version")
    INIT_FILE.write_text(
        re.sub(r'__version__\s*=\s*"[^"]+"', f'__version__ = "{new_version}"', INIT_FILE.read_text(encoding="utf-8")),
        encoding="utf-8",
    )
    sync_static_copies(new_version)
    print(f"✅ Version set to {new_version} in app/__init__.py")


def sync_static_copies(version: str) -> None:
    """Sync every static copy of the version to the current one."""
    # pyproject.toml
    pyproject = PYPROJECT_FILE.read_text(encoding="utf-8")
    updated = re.sub(r'(version\s*=\s*)"[^"]+"', rf'\1"{version}"', pyproject, count=1)
    if updated != pyproject:
        PYPROJECT_FILE.write_text(updated, encoding="utf-8")
        print(f"✅ pyproject.toml -> {version}")
    else:
        print(f"•  pyproject.toml already at {version}")

    # CITATION.cff (project version, keeping cff-version spec intact)
    if CITATION_FILE.exists():
        cff = CITATION_FILE.read_text(encoding="utf-8")
        updated_cff = re.sub(r'((?<!cff-)version:\s*)\d+\.\d+\.\d+', rf'\g<1>{version}', cff, count=1)
        if updated_cff != cff:
            CITATION_FILE.write_text(updated_cff, encoding="utf-8")
            print(f"✅ CITATION.cff -> {version}")
        else:
            print(f"•  CITATION.cff already at {version}")

    # miniapp/index.html (JSON-LD structured data softwareVersion)
    if INDEX_HTML.exists():
        html = INDEX_HTML.read_text(encoding="utf-8")
        updated_html = re.sub(r'("softwareVersion":\s*)"\d+\.\d+\.\d+"', rf'\1"{version}"', html, count=1)
        if updated_html != html:
            INDEX_HTML.write_text(updated_html, encoding="utf-8")
            print(f"✅ miniapp/index.html -> {version}")
        else:
            print(f"•  miniapp/index.html already at {version}")

    # miniapp/app.js (demo & fallback version strings)
    if APP_JS.exists():
        js = APP_JS.read_text(encoding="utf-8")
        updated_js = re.sub(r'(version:\s*)"\d+\.\d+\.\d+"', rf'\1"{version}"', js)
        if updated_js != js:
            APP_JS.write_text(updated_js, encoding="utf-8")
            print(f"✅ miniapp/app.js -> {version}")
        else:
            print(f"•  miniapp/app.js already at {version}")

    # miniapp/sw.js (PWA offline cache version)
    if SW_JS.exists():
        sw = SW_JS.read_text(encoding="utf-8")
        updated_sw = re.sub(r'(CACHE_NAME\s*=\s*"teleautomator-v)\d+\.\d+\.\d+"', rf'\g<1>{version}"', sw)
        if updated_sw != sw:
            SW_JS.write_text(updated_sw, encoding="utf-8")
            print(f"✅ miniapp/sw.js -> v{version}")
        else:
            print(f"•  miniapp/sw.js already at v{version}")

    # assets/banner.svg branding text ("TELEAUTOMATOR vX.Y" — major.minor only)
    if BANNER_SVG.exists():
        svg = BANNER_SVG.read_text(encoding="utf-8")
        major_minor = ".".join(version.split(".")[:2])
        updated = re.sub(r"(TELEAUTOMATOR\s+v)\d+\.\d+", rf"\g<1>{major_minor}", svg)
        if updated != svg:
            BANNER_SVG.write_text(updated, encoding="utf-8")
            print(f"✅ assets/banner.svg -> v{major_minor}")
        else:
            print(f"•  assets/banner.svg already at v{major_minor}")


# Hardcoded PROJECT versions only matter in these contexts (dependency pins like
# telethon>=1.36.0 and infra python versions are NOT project versions):
STALE_PATTERNS = [
    re.compile(r'__version__\s*=\s*"(\d+\.\d+\.\d+)"'),           # python version constants
    re.compile(r'(?<![\w.-])version\s*=\s*"(\d+\.\d+\.\d+)"'),    # pyproject/setup assignments
    re.compile(r"TeleAutomator[^\n]{0,40}?v(\d+\.\d+\.\d+)"),     # branding strings in any file
]


def scan_for_stale_versions(version: str) -> list[str]:
    """Find hardcoded PROJECT version strings anywhere that do NOT match the current
    version. Dynamic references (from app import __version__ etc.) are never flagged."""
    stale: list[str] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SCAN_EXCLUDES for part in path.parts):
            continue
        if path.suffix not in {".py", ".md", ".toml", ".txt", ".yml", ".yaml", ".json", ".svg", ".cfg"}:
            continue
        if path.name == "update_version.py":  # this script's own docs/examples
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except Exception:
            continue
        for i, line in enumerate(lines, 1):
            for pattern in STALE_PATTERNS:
                for m in pattern.finditer(line):
                    if m.group(1) != version:
                        stale.append(f"{path.relative_to(ROOT)}:{i}: {line.strip()[:120]}")
    return stale


def main() -> None:
    args = sys.argv[1:]
    if args:
        set_version(args[0].lstrip("v"))

    version = current_version()
    print(f"🔍 Current version: {version}")
    sync_static_copies(version)

    stale = scan_for_stale_versions(version)
    if stale:
        print(f"\n⚠️  Found {len(stale)} hardcoded version string(s) that do NOT match {version}:")
        for entry in stale:
            print(f"   {entry}")
        sys.exit(1)
    print("\n✅ All clean — no stale hardcoded versions anywhere.")


if __name__ == "__main__":
    main()
