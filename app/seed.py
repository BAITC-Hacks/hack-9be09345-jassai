"""Validated starter data for an empty installation; never reset user data."""
from pathlib import Path

from app.db import get_meta, set_meta
from app.imports import MAX_FILE_BYTES, apply_validated, validate_files

BUNDLED_DATA_DIR = Path(__file__).resolve().parents[1] / "starter-data"
DATA_FILES = ("employees.json", "events.json", "skills.json", "activity_history.csv")


def read_seed_files(directory: Path):
    files = {}
    for name in DATA_FILES:
        try:
            with (directory / name).open("rb") as stream:
                content = stream.read(MAX_FILE_BYTES + 1)
        except OSError as exc:
            raise RuntimeError(f"Cannot read starter data file: {name}") from exc
        if len(content) > MAX_FILE_BYTES:
            raise RuntimeError(f"Starter data file exceeds 8 MiB: {name}")
        files[name] = content
    return files


def seed_dataset(db, directory: Path | None):
    if directory is None:
        return False
    # One lock covers the empty check and import, including concurrent startup.
    with db.connection(write=True) as conn:
        if get_meta(conn, "as_of_date") is not None or conn.execute("SELECT 1 FROM entities LIMIT 1").fetchone():
            return False
        report, incoming = validate_files(conn, read_seed_files(directory), "add")
        if not report["valid"]:
            first = report["errors"][0]
            raise RuntimeError(f"Invalid starter data: {first['file']}: {first['message']}")
        apply_validated(conn, incoming, report["as_of_date"])
        set_meta(conn, "starter_data_loaded", "1")
    return True
