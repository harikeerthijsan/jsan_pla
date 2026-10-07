"""Set one cache-busting version for the reviewer UI's CSS and JavaScript.

The browser caches web/assets by URL, so every changed asset needs a new ``?v=`` value. app.js imports the feature
modules in web/assets/modules/, and the modules import each other: all of those specifiers must carry the *same*
value, otherwise the browser loads two copies of a module, each with its own state. Run this after any frontend
change instead of editing versions by hand:

    python scripts/set_web_version.py 20261008-my-change
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "web" / "assets"
VERSION_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
# index.html references app.css/app.js; app.js and the modules reference ./modules/*.js and ./<module>.js.
SPECIFIER = re.compile(r"""((?:assets/app\.(?:css|js)|\./modules/[\w-]+\.js|\./[\w-]+\.js)\?v=)[A-Za-z0-9._-]+""")


def targets() -> list[Path]:
    return [ROOT / "web" / "index.html", ASSETS / "app.js", *sorted((ASSETS / "modules").glob("*.js"))]


def set_version(version: str) -> int:
    if not VERSION_PATTERN.match(version):
        raise SystemExit("Version must be 1-64 characters of letters, digits, '.', '_' or '-'")
    changed = 0
    for path in targets():
        text = path.read_text(encoding="utf-8")
        updated = SPECIFIER.sub(lambda m: m.group(1) + version, text)
        if updated != text:
            path.write_text(updated, encoding="utf-8", newline="")
            changed += 1
    return changed


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    print(f"Updated {set_version(sys.argv[1])} file(s) to ?v={sys.argv[1]}")
