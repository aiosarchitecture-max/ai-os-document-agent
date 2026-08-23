"""Bounded AI_OS service start.

A failed or unreachable database must not make the application completely
silent. Data endpoints remain closed through the application's readiness gate.
"""

import os
import subprocess


def run_migrations() -> str:
    timeout_seconds = int(os.getenv("MIGRATION_TIMEOUT_SECONDS", "30"))
    try:
        completed = subprocess.run(
            ["alembic", "upgrade", "head"],
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        print(
            f"AI_OS migration timed out after {timeout_seconds}s; starting in degraded mode.",
            flush=True,
        )
        return "timeout"

    if completed.returncode == 0:
        return "ok"

    print(
        f"AI_OS migration failed with exit code {completed.returncode}; starting in degraded mode.",
        flush=True,
    )
    return "failed"


def main() -> None:
    os.environ["AI_OS_MIGRATION_STATUS"] = run_migrations()
    port = os.environ.get("PORT", "8000")
    os.execvp(
        "uvicorn",
        [
            "uvicorn",
            "app.main:app",
            "--host",
            "0.0.0.0",
            "--port",
            port,
        ],
    )


if __name__ == "__main__":
    main()
