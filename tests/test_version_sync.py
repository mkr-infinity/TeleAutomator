import importlib.util
from pathlib import Path


def test_version_update_syncs_metadata_assets_and_detects_stale_urls(tmp_path):
    root = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location("version_sync", root / "scripts/update_version.py")
    updater = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(updater)
    updater.ROOT = tmp_path
    for name in ("INIT_FILE", "PYPROJECT_FILE", "CITATION_FILE", "INDEX_HTML", "APP_JS", "SW_JS", "BANNER_SVG"):
        source = getattr(updater, name)
        target = tmp_path / source.relative_to(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.exists():
            target.write_bytes(source.read_bytes())
        setattr(updater, name, target)
    updater.set_version("9.8.7")
    assert updater.current_version() == "9.8.7"
    for name in ("PYPROJECT_FILE", "CITATION_FILE", "INDEX_HTML", "APP_JS", "SW_JS"):
        assert "9.8.7" in getattr(updater, name).read_text()
    for name in ("INDEX_HTML", "SW_JS"):
        content = getattr(updater, name).read_text()
        assert "style.css?v=9.8.7" in content and "app.js?v=9.8.7" in content
    assert "cff-version: 1.2.0" in updater.CITATION_FILE.read_text()
    assert not updater.scan_for_stale_versions("9.8.7")
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    updater.sync_static_copies("9.8.7")
    assert all(path.read_bytes() == content for path, content in before.items())
    updater.SW_JS.write_text(updater.SW_JS.read_text().replace("app.js?v=9.8.7", "app.js?v=0.0.1"))
    assert updater.scan_for_stale_versions("9.8.7")
