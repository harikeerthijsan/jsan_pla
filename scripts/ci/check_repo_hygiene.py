"""Fail when Git tracks secrets, customer data or unsafe CI configuration.

Run from anywhere: python scripts/ci/check_repo_hygiene.py
Used by .github/workflows/ci.yml and scripts/run_ci_local.ps1.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Customer LiDAR, workbooks, generated COPC, local databases and real env files never belong in Git.
FORBIDDEN_SUFFIXES = (
    ".las", ".laz", ".copc", ".xlsx", ".xlsm", ".xls",
    ".db", ".sqlite", ".sqlite3", ".pem", ".key", ".pfx", ".p12",
)
ALLOWED_ENV_FILES = {".env.railway.example", "api/.env.example"}

# Provider tokens are not needed: Railway deploys through its GitHub integration with "Wait for CI".
FORBIDDEN_WORKFLOW_PATTERNS = {
    "pull_request_target": re.compile(r"^\s*pull_request_target\s*:", re.MULTILINE),
    "provider token secret": re.compile(r"secrets\.(RAILWAY|VERCEL|AWS|BUCKET|DATABASE|JWT|ADMIN)[A-Z_]*", re.IGNORECASE),
    "write-all permissions": re.compile(r"permissions\s*:\s*write-all"),
}

SECRET_PATTERNS = {
    "AWS access key id": re.compile(r"AKIA[0-9A-Z]{16}"),
    "private key block": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "Postgres URL with inline password": re.compile(r"postgres(?:ql)?(?:\+\w+)?://[^:\s/@]+:(?!pass@|password@|<)[^@\s]{6,}@(?!localhost|127\.0\.0\.1|postgres\.railway\.internal)"),
}
TEXT_SCAN_SUFFIXES = {".py", ".ps1", ".sh", ".yml", ".yaml", ".json", ".ts", ".js", ".md", ".toml", ".example", ".txt", ".cfg", ".ini"}
SKIP_SCAN_PREFIXES = ("web/potree/", "web/libs/")


def tracked_files() -> list[str]:
    output = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT, check=True, capture_output=True,
    ).stdout.decode("utf-8")
    return [p for p in output.split("\0") if p]


def check(files: list[str]) -> list[str]:
    problems: list[str] = []
    for path in files:
        lower = path.lower()
        name = lower.rsplit("/", 1)[-1]
        if lower.endswith(FORBIDDEN_SUFFIXES):
            problems.append(f"{path}: forbidden file type in Git")
        if (name == ".env" or name.startswith(".env.")) and path not in ALLOWED_ENV_FILES and not name.endswith(".example"):
            problems.append(f"{path}: environment file must not be committed")

    for path in files:
        if not path.startswith(".github/workflows/"):
            continue
        text = (ROOT / path).read_text(encoding="utf-8")
        for label, pattern in FORBIDDEN_WORKFLOW_PATTERNS.items():
            if pattern.search(text):
                problems.append(f"{path}: workflow uses {label}")

    for path in files:
        if path.startswith(SKIP_SCAN_PREFIXES) or Path(path).suffix.lower() not in TEXT_SCAN_SUFFIXES and not path.endswith(".example"):
            continue
        file = ROOT / path
        if not file.is_file() or file.stat().st_size > 2_000_000:
            continue
        text = file.read_text(encoding="utf-8", errors="ignore")
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                problems.append(f"{path}: possible {label}")
    return problems


def main() -> int:
    problems = check(tracked_files())
    for problem in problems:
        print(f"HYGIENE: {problem}", file=sys.stderr)
    if problems:
        return 1
    print("Repository hygiene check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
