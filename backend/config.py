"""Configuration reads do not create directories or open the business database."""

from dataclasses import dataclass
import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parent.parent


def _commit() -> str:
    supplied = os.environ.get("WH_BACKEND_COMMIT")
    try:
        result = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            check=True, capture_output=True, text=True, timeout=3,
        )
        dirty = subprocess.run(
            ["git", "-C", str(ROOT), "status", "--porcelain", "--", "backend", "config/schools.json"],
            check=True, capture_output=True, text=True, timeout=3,
        ).stdout.strip()
        return (supplied or result.stdout.strip()) + ("+dirty" if dirty else "")
    except (OSError, subprocess.SubprocessError):
        return supplied or "unavailable"


@dataclass(frozen=True)
class Settings:
    db_path: Path
    backend_commit: str
    service_token: str = ""
    recent_days: int = 30
    maintenance_password_hash: str = ""
    maintenance_actor: str = ""
    maintenance_origin: str = ""
    acceptance_db_path: Path | None = None

    @classmethod
    def from_env(cls, db_path: Path | None = None) -> "Settings":
        return cls(
            db_path=Path(db_path or os.environ.get(
                "WH_DB_PATH", ROOT / ".runtime" / "dev" / "workhunter-v2.sqlite3",
            )).resolve(),
            backend_commit=_commit(),
            service_token=os.environ.get("WH_API_SERVICE_TOKEN", ""),
            maintenance_password_hash=os.environ.get("WH_MAINTENANCE_PASSWORD_HASH", ""),
            maintenance_actor=os.environ.get("WH_MAINTENANCE_ACTOR", ""),
            maintenance_origin=os.environ.get("WH_MAINTENANCE_ORIGIN", ""),
            acceptance_db_path=Path(os.environ["WH_ACCEPTANCE_DB_PATH"]).resolve() if os.environ.get("WH_ACCEPTANCE_DB_PATH") else None,
        )
