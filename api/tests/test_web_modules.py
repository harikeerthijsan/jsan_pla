"""The reviewer UI is split into ES modules; these checks keep the split safe to change."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "web" / "assets"
MODULES = sorted((ASSETS / "modules").glob("*.js"))
IMPORT = re.compile(r'import\s*(?:\{[^}]*\}|\*\s+as\s+\w+)?\s*(?:from\s*)?"([^"]+)"')


def imports_of(path: Path) -> list[str]:
    return IMPORT.findall(path.read_text(encoding="utf-8"))


def test_app_entry_loads_and_initialises_every_module_once():
    entry = (ASSETS / "app.js").read_text(encoding="utf-8")
    assert len(MODULES) >= 20
    for module in MODULES:
        assert entry.count(f'"./modules/{module.name}?v=') == 1, module.name
        assert "export function init(" in module.read_text(encoding="utf-8"), module.name
    # Each module's setup is called exactly once, and the session restore runs after all of them.
    init_calls = re.findall(r"^(init\w*)\(\);$", entry, flags=re.M)
    assert len(init_calls) == len(set(init_calls)) and len(init_calls) >= len(MODULES)
    last_init = max(match.end() for match in re.finditer(r"^init\w*\(\);$", entry, flags=re.M))
    assert last_init < entry.index("(async function(){if(state.token&&state.apiBase)")


def test_every_module_specifier_uses_one_version():
    # Two different ?v= values for the same module would load it twice, each copy with its own state.
    versions = set()
    for path in [ASSETS / "app.js", *MODULES]:
        for spec in imports_of(path):
            if "/modules/" in spec or (path.parent.name == "modules" and spec.startswith("./")):
                assert "?v=" in spec, (path.name, spec)
                versions.add(spec.split("?v=")[1])
    assert len(versions) == 1, versions
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    assert f'assets/app.js?v=' in html


def test_modules_import_only_existing_modules_and_never_the_entry():
    names = {module.name for module in MODULES}
    for module in MODULES:
        for spec in imports_of(module):
            target = spec.split("?")[0]
            assert not target.endswith("app.js"), module.name
            if target.startswith("./"):
                assert target[2:] in names, (module.name, spec)


def test_set_web_version_script_updates_every_specifier(tmp_path, monkeypatch):
    import importlib.util

    spec = importlib.util.spec_from_file_location("set_web_version", ROOT / "scripts" / "set_web_version.py")
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    # Work on a copy so the real files are untouched.
    web = tmp_path / "web"
    (web / "assets" / "modules").mkdir(parents=True)
    (web / "index.html").write_text((ROOT / "web" / "index.html").read_text(encoding="utf-8"), encoding="utf-8")
    (web / "assets" / "app.js").write_text((ASSETS / "app.js").read_text(encoding="utf-8"), encoding="utf-8")
    for asset_name in ("login-background.js", "lidar-login-scene.js"):
        (web / "assets" / asset_name).write_text(
            (ASSETS / asset_name).read_text(encoding="utf-8"), encoding="utf-8"
        )
    for module in MODULES:
        (web / "assets" / "modules" / module.name).write_text(module.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(tool, "ROOT", tmp_path)
    monkeypatch.setattr(tool, "ASSETS", web / "assets")
    assert tool.set_version("test-bump") > len(MODULES)
    for path in [*(web / "assets").glob("*.js"), *(web / "assets" / "modules").glob("*.js")]:
        for value in re.findall(r'\./(?:modules/)?[\w-]+\.js\?v=([\w.-]+)', path.read_text(encoding="utf-8")):
            assert value == "test-bump", path.name
    assert 'assets/app.js?v=test-bump' in (web / "index.html").read_text(encoding="utf-8")
    assert 'assets/login-lidar.css?v=test-bump' in (web / "index.html").read_text(encoding="utf-8")
