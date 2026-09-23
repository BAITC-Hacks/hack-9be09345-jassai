"""Developer entrypoint; end-user launcher is maintained by teammate B."""
import argparse
import json
from pathlib import Path

from app.auth import initialize_bootstrap
from app.config import Settings
from app.db import Database, revision
from app.imports import apply_validated, validate_files
from app.seed import seed_dataset


def main():
    parser = argparse.ArgumentParser(description="Career Quest backend")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="Initialize database and one-time bootstrap token")
    serve = commands.add_parser("serve", help="Run the local HTTP server")
    serve.add_argument("--port", type=int, default=8000)
    importer = commands.add_parser("import", help="Validate and import an organizer dataset locally")
    importer.add_argument("dataset", type=Path)
    importer.add_argument("--mode", choices=["add", "update"], default="add")
    args = parser.parse_args()
    settings = Settings.from_env()
    if args.command == "serve":
        import uvicorn
        uvicorn.run("app.main:app", host="127.0.0.1", port=args.port)
        return
    db = Database(settings.data_dir / "careerquest.sqlite3")
    db.initialize()
    if args.command == "init":
        seed_dataset(db, settings.seed_data_dir)
    initialize_bootstrap(db, settings)
    if args.command == "init":
        print(json.dumps({"data_dir": str(settings.data_dir), "bootstrap_token_file": str(settings.data_dir / "setup-token.txt") if not settings.bootstrap_token else None}, ensure_ascii=False))
        return
    names = ["employees.json", "events.json", "skills.json", "activity_history.csv"]
    files = {name: (args.dataset / name).read_bytes() for name in names if (args.dataset / name).is_file()}
    with db.connection(write=True) as conn:
        report, payload = validate_files(conn, files, args.mode)
        if report["valid"]:
            apply_validated(conn, payload, report["as_of_date"])
            report["data_revision"] = revision(conn)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["valid"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
