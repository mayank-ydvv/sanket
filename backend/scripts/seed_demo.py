"""Reset the database to a clean demo state with one dispatcher account.

Run from ``backend/`` with the API stopped: ``python -m scripts.seed_demo``.

* The current database (and its WAL/SHM files) is moved to ``backend/backups/``,
  never deleted, so a reset can always be undone.
* A fresh schema is created and the demo account is added: DEMO_EMAIL with
  DEMO_PASSWORD from ``.env``. If DEMO_PASSWORD is unset, a random password is
  generated and printed once.
* It refuses to run while the API answers on ``--api`` (SQLite is open there),
  unless ``--force`` is given.
"""

import argparse
import asyncio
import secrets
import shutil
import time
import uuid
from pathlib import Path

import httpx

from app.auth import hash_password
from app.config import ROOT, get_settings
from app.db import Database

BACKUP_DIR = ROOT / "backend" / "backups"


def api_is_running(url: str) -> bool:
    try:
        return httpx.get(f"{url}/health", timeout=1.0).status_code == 200
    except httpx.HTTPError:
        return False


def back_up(db_path: Path) -> Path | None:
    """Move the database files aside. O(1): a rename on the same disk."""
    files = [p for p in (db_path, Path(f"{db_path}-wal"), Path(f"{db_path}-shm")) if p.exists()]
    if not files:
        return None
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for path in files:
        shutil.move(path, BACKUP_DIR / f"{db_path.stem}-{stamp}{path.name.removeprefix(db_path.stem)}")
    return BACKUP_DIR / f"{db_path.stem}-{stamp}{db_path.suffix}"


async def seed(db_path: Path, name: str, email: str, password: str) -> None:
    db = await Database.open(db_path)
    try:
        async with db.transaction():
            await db.create_user(f"u_{uuid.uuid4().hex}", name, email.lower(), hash_password(password))
    finally:
        await db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api", default="http://127.0.0.1:8010", help="where a running API would answer")
    parser.add_argument("--force", action="store_true", help="reset even if the API seems to be running")
    parser.add_argument("--name", default="Demo dispatcher")
    args = parser.parse_args()

    settings = get_settings()
    if not args.force and api_is_running(args.api):
        raise SystemExit(f"The API is running at {args.api}. Stop it first (or pass --force).")
    backup = back_up(settings.db_path)
    password = settings.demo_password or secrets.token_urlsafe(9)
    asyncio.run(seed(settings.db_path, args.name, settings.demo_email, password))

    print(f"Clean demo database: {settings.db_path}")
    print(f"Previous database:   {backup or 'none (first run)'}")
    print(f"Demo account:        {settings.demo_email}")
    if settings.demo_password is None:
        print(f"Generated password:  {password}   (set DEMO_PASSWORD in .env to choose your own)")
    else:
        print("Password:            DEMO_PASSWORD from .env")


if __name__ == "__main__":
    main()
