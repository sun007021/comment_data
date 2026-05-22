import argparse
import os
from pathlib import Path


def main() -> None:
    load_dotenv(Path(".env"))

    parser = argparse.ArgumentParser(description="Collect GitHub PR review comments into PostgreSQL")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init-db", help="Create database tables and indexes")
    init_parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))

    collect_parser = subparsers.add_parser("collect", help="Collect configured mission comments")
    collect_parser.add_argument("--missions", type=Path, default=Path("missions.yml"))
    collect_parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    collect_parser.add_argument("--github-token", default=os.getenv("GITHUB_TOKEN"))
    collect_parser.add_argument("--full-refresh", action="store_true")
    collect_parser.add_argument("--pr-limit", type=int, default=50)

    args = parser.parse_args()

    if args.command == "init-db":
        from comment_data.db import connect, init_db

        database_url = require_value(args.database_url, "DATABASE_URL")
        with connect(database_url) as connection:
            init_db(connection)
        print("Database schema is ready.")
        return

    if args.command == "collect":
        from comment_data.collector import collect_mission
        from comment_data.config import load_missions
        from comment_data.db import connect, init_db
        from comment_data.github_client import GitHubClient

        database_url = require_value(args.database_url, "DATABASE_URL")
        github_token = require_value(args.github_token, "GITHUB_TOKEN")
        missions = load_missions(args.missions)
        client = GitHubClient(github_token)

        with connect(database_url) as connection:
            init_db(connection)
            for mission in missions:
                result = collect_mission(
                    connection,
                    client,
                    mission,
                    full_refresh=args.full_refresh,
                    pr_limit=args.pr_limit,
                )
                since_text = result.since.isoformat() if result.since else "from beginning"
                print(
                    f"{mission.owner}/{mission.repository_name}: "
                    f"prs={result.pull_requests}, comments={result.comments}, "
                    f"conversation_documents={result.conversation_documents}, "
                    f"since={since_text}"
                )


def require_value(value: str | None, name: str) -> str:
    if not value:
        raise SystemExit(f"{name} is required")
    return value


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
