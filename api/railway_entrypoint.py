"""Run the Railway web process and background worker in one container."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time


PROCESSES: list[subprocess.Popen] = []
STOPPING = False


def validate_production_environment() -> None:
    # Staging is production-like and must fail the same way on incomplete configuration.
    if os.getenv("APP_ENV", "development").lower() not in {"production", "staging"}:
        return

    required = ["DATABASE_URL", "ADMIN_EMAIL", "ADMIN_PASSWORD", "JWT_SECRET"]
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise RuntimeError(
            "Missing required Railway variables: " + ", ".join(missing)
        )

    if len(os.environ["JWT_SECRET"]) < 32:
        raise RuntimeError("JWT_SECRET must contain at least 32 characters")
    if len(os.environ["ADMIN_PASSWORD"]) < 12:
        raise RuntimeError("ADMIN_PASSWORD must contain at least 12 characters")
    if os.environ["ADMIN_PASSWORD"] == "ChangeMe123!":
        raise RuntimeError("ADMIN_PASSWORD must not use the development password")

    storage_mode = os.getenv("STORAGE_MODE", "local").lower()
    if storage_mode not in {"local", "s3"}:
        raise RuntimeError("STORAGE_MODE must be either 'local' or 's3'")
    if storage_mode == "s3":
        variable_groups = {
            "bucket name": ("BUCKET", "BUCKET_NAME", "S3_BUCKET", "AWS_S3_BUCKET_NAME"),
            "bucket endpoint": ("BUCKET_ENDPOINT", "S3_ENDPOINT_URL", "AWS_ENDPOINT_URL", "ENDPOINT"),
            "bucket access key": ("BUCKET_ACCESS_KEY_ID", "AWS_ACCESS_KEY_ID", "ACCESS_KEY_ID"),
            "bucket secret key": ("BUCKET_SECRET_ACCESS_KEY", "AWS_SECRET_ACCESS_KEY", "SECRET_ACCESS_KEY"),
        }
        missing_storage = [
            label
            for label, names in variable_groups.items()
            if not any(os.getenv(name) for name in names)
        ]
        if missing_storage:
            raise RuntimeError(
                "Missing Railway Storage Bucket configuration: "
                + ", ".join(missing_storage)
            )
        if os.getenv("AUTO_CONFIGURE_BUCKET_CORS", "false").lower() == "true":
            from app.storage import bucket_cors_origins
            bucket_cors_origins()


def wait_for_database() -> None:
    from sqlalchemy import text

    from app.db import engine

    timeout = int(os.getenv("DB_CONNECT_TIMEOUT", "120"))
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None

    while time.monotonic() < deadline:
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            print("Database connection ready", flush=True)
            return
        except Exception as exc:  # Railway may start the app before Postgres is ready.
            last_error = exc
            print(f"Waiting for database: {exc}", flush=True)
            time.sleep(2)

    raise RuntimeError(f"Database was not ready within {timeout}s: {last_error}")


def request_shutdown(signum: int, _frame: object) -> None:
    global STOPPING
    print(f"Received signal {signum}; stopping child processes", flush=True)
    STOPPING = True
    for process in PROCESSES:
        if process.poll() is None:
            process.terminate()


def stop_children() -> None:
    deadline = time.monotonic() + 15
    for process in PROCESSES:
        if process.poll() is None:
            process.terminate()
    for process in PROCESSES:
        remaining = max(0, deadline - time.monotonic())
        try:
            process.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            process.kill()
    for process in PROCESSES:
        if process.poll() is None:
            process.wait()


def main() -> int:
    global STOPPING

    validate_production_environment()
    wait_for_database()

    # Initialize the additive schema once before starting child processes.
    # initialize_schema also uses a PostgreSQL advisory lock, so concurrent
    # replicas are safe during rolling deploys.
    from app.db import initialize_schema
    initialize_schema()
    print("Database schema ready", flush=True)

    port = os.getenv("PORT", "8000")
    commands = [
        [sys.executable, "worker.py"],
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "0.0.0.0",
            "--port",
            port,
            "--proxy-headers",
            "--forwarded-allow-ips=*",
        ],
    ]

    for command in commands:
        print("Starting " + " ".join(command), flush=True)
        PROCESSES.append(subprocess.Popen(command))

    exit_code = 0
    try:
        while not STOPPING:
            for process in PROCESSES:
                code = process.poll()
                if code is not None:
                    print(f"Child process {process.pid} exited with code {code}", flush=True)
                    exit_code = code or 1
                    STOPPING = True
                    break
            time.sleep(0.5)
    finally:
        stop_children()

    return exit_code


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, request_shutdown)
    signal.signal(signal.SIGINT, request_shutdown)
    raise SystemExit(main())
