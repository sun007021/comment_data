from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS missions (
    id BIGSERIAL PRIMARY KEY,
    track VARCHAR(50) NOT NULL,
    name VARCHAR(100) NOT NULL,
    repository_owner VARCHAR(100) NOT NULL,
    repository_name VARCHAR(150) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (repository_owner, repository_name)
);

CREATE TABLE IF NOT EXISTS pull_requests (
    id BIGSERIAL PRIMARY KEY,
    mission_id BIGINT NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
    pr_number INT NOT NULL,
    crew_github_id VARCHAR(100) NOT NULL,
    title TEXT NOT NULL,
    github_url TEXT NOT NULL,
    state VARCHAR(20) NOT NULL,
    created_at TIMESTAMPTZ NULL,
    updated_at TIMESTAMPTZ NULL,
    UNIQUE (mission_id, pr_number)
);

CREATE TABLE IF NOT EXISTS review_comments (
    id BIGSERIAL PRIMARY KEY,
    pr_id BIGINT NOT NULL REFERENCES pull_requests(id) ON DELETE CASCADE,
    comment_github_id BIGINT NOT NULL UNIQUE,
    parent_github_id BIGINT NULL,
    reviewer_id VARCHAR(100) NOT NULL,
    reviewer_avatar_url TEXT NULL,
    content TEXT NOT NULL,
    github_url TEXT NOT NULL,
    file_path TEXT NULL,
    line_number INT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NULL
);

CREATE TABLE IF NOT EXISTS conversation_documents (
    id BIGSERIAL PRIMARY KEY,
    mission_id BIGINT NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
    pr_id BIGINT NOT NULL REFERENCES pull_requests(id) ON DELETE CASCADE,
    root_comment_github_id BIGINT NOT NULL,
    document_kind VARCHAR(30) NOT NULL,
    document_text TEXT NOT NULL,
    github_url TEXT NOT NULL,
    file_path TEXT NULL,
    line_number INT NULL,
    comment_github_ids BIGINT[] NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (root_comment_github_id)
);

CREATE INDEX IF NOT EXISTS idx_missions_track ON missions(track);
CREATE INDEX IF NOT EXISTS idx_pull_requests_mission ON pull_requests(mission_id);
CREATE INDEX IF NOT EXISTS idx_review_comments_pr ON review_comments(pr_id);
CREATE INDEX IF NOT EXISTS idx_review_comments_parent ON review_comments(parent_github_id);
CREATE INDEX IF NOT EXISTS idx_review_comments_created_at ON review_comments(created_at);
CREATE INDEX IF NOT EXISTS idx_review_comments_content_fts
    ON review_comments
    USING GIN (to_tsvector('simple', content));
CREATE INDEX IF NOT EXISTS idx_conversation_documents_mission ON conversation_documents(mission_id);
CREATE INDEX IF NOT EXISTS idx_conversation_documents_pr ON conversation_documents(pr_id);
CREATE INDEX IF NOT EXISTS idx_conversation_documents_kind ON conversation_documents(document_kind);
CREATE INDEX IF NOT EXISTS idx_conversation_documents_text_fts
    ON conversation_documents
    USING GIN (to_tsvector('simple', document_text));
"""


@contextmanager
def connect(database_url: str) -> Iterator[psycopg.Connection[Any]]:
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        yield connection


def init_db(connection: psycopg.Connection[Any]) -> None:
    with connection.cursor() as cursor:
        cursor.execute(SCHEMA_SQL)
    connection.commit()


def upsert_mission(
    connection: psycopg.Connection[Any],
    *,
    track: str,
    name: str,
    owner: str,
    repository_name: str,
) -> int:
    with connection.cursor() as cursor:
        row = cursor.execute(
            """
            INSERT INTO missions (track, name, repository_owner, repository_name)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (repository_owner, repository_name)
            DO UPDATE SET track = EXCLUDED.track, name = EXCLUDED.name
            RETURNING id
            """,
            (track, name, owner, repository_name),
        ).fetchone()
    if row is None:
        raise RuntimeError("Failed to upsert mission")
    return int(row["id"])


def upsert_pull_request(
    connection: psycopg.Connection[Any],
    *,
    mission_id: int,
    pr: dict[str, Any],
) -> int:
    user = pr.get("user") or {}
    with connection.cursor() as cursor:
        row = cursor.execute(
            """
            INSERT INTO pull_requests (
                mission_id, pr_number, crew_github_id, title, github_url, state, created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (mission_id, pr_number)
            DO UPDATE SET
                crew_github_id = EXCLUDED.crew_github_id,
                title = EXCLUDED.title,
                github_url = EXCLUDED.github_url,
                state = EXCLUDED.state,
                created_at = EXCLUDED.created_at,
                updated_at = EXCLUDED.updated_at
            RETURNING id
            """,
            (
                mission_id,
                pr["number"],
                user.get("login", ""),
                pr.get("title", ""),
                pr.get("html_url", ""),
                pr.get("state", ""),
                parse_github_datetime(pr.get("created_at")),
                parse_github_datetime(pr.get("updated_at")),
            ),
        ).fetchone()
    if row is None:
        raise RuntimeError("Failed to upsert pull request")
    return int(row["id"])


def upsert_review_comment(
    connection: psycopg.Connection[Any],
    *,
    pr_id: int,
    comment: dict[str, Any],
) -> int:
    user = comment.get("user") or {}
    with connection.cursor() as cursor:
        row = cursor.execute(
            """
            INSERT INTO review_comments (
                pr_id, comment_github_id, parent_github_id, reviewer_id, reviewer_avatar_url,
                content, github_url, file_path, line_number, created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (comment_github_id)
            DO UPDATE SET
                pr_id = EXCLUDED.pr_id,
                parent_github_id = EXCLUDED.parent_github_id,
                reviewer_id = EXCLUDED.reviewer_id,
                reviewer_avatar_url = EXCLUDED.reviewer_avatar_url,
                content = EXCLUDED.content,
                github_url = EXCLUDED.github_url,
                file_path = EXCLUDED.file_path,
                line_number = EXCLUDED.line_number,
                created_at = EXCLUDED.created_at,
                updated_at = EXCLUDED.updated_at
            RETURNING id
            """,
            (
                pr_id,
                comment["id"],
                comment.get("in_reply_to_id"),
                user.get("login", ""),
                user.get("avatar_url"),
                comment.get("body", ""),
                comment.get("html_url", ""),
                comment.get("path"),
                comment.get("line") or comment.get("original_line"),
                parse_github_datetime(comment.get("created_at")),
                parse_github_datetime(comment.get("updated_at")),
            ),
        ).fetchone()
    if row is None:
        raise RuntimeError("Failed to upsert review comment")
    return int(row["id"])


def get_latest_comment_created_at(
    connection: psycopg.Connection[Any],
    *,
    mission_id: int,
) -> datetime | None:
    with connection.cursor() as cursor:
        row = cursor.execute(
            """
            SELECT max(rc.created_at) AS latest_created_at
            FROM review_comments rc
            JOIN pull_requests pr ON pr.id = rc.pr_id
            WHERE pr.mission_id = %s
            """,
            (mission_id,),
        ).fetchone()

    if row is None:
        return None
    return row["latest_created_at"]


def fetch_review_comments_for_pr(
    connection: psycopg.Connection[Any],
    *,
    pr_id: int,
) -> list[dict[str, Any]]:
    with connection.cursor() as cursor:
        rows = cursor.execute(
            """
            SELECT
                comment_github_id,
                parent_github_id,
                reviewer_id,
                reviewer_avatar_url,
                content,
                github_url,
                file_path,
                line_number,
                created_at,
                updated_at
            FROM review_comments
            WHERE pr_id = %s
            ORDER BY created_at ASC, comment_github_id ASC
            """,
            (pr_id,),
        ).fetchall()
    return list(rows)


def delete_conversation_documents_for_pr(
    connection: psycopg.Connection[Any],
    *,
    pr_id: int,
) -> None:
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM conversation_documents WHERE pr_id = %s", (pr_id,))


def insert_conversation_document(
    connection: psycopg.Connection[Any],
    *,
    mission_id: int,
    pr_id: int,
    root_comment_github_id: int,
    document_kind: str,
    document_text: str,
    github_url: str,
    file_path: str | None,
    line_number: int | None,
    comment_github_ids: list[int],
    metadata: dict[str, Any],
) -> int:
    with connection.cursor() as cursor:
        row = cursor.execute(
            """
            INSERT INTO conversation_documents (
                mission_id, pr_id, root_comment_github_id, document_kind, document_text,
                github_url, file_path, line_number, comment_github_ids, metadata
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (root_comment_github_id)
            DO UPDATE SET
                mission_id = EXCLUDED.mission_id,
                pr_id = EXCLUDED.pr_id,
                document_kind = EXCLUDED.document_kind,
                document_text = EXCLUDED.document_text,
                github_url = EXCLUDED.github_url,
                file_path = EXCLUDED.file_path,
                line_number = EXCLUDED.line_number,
                comment_github_ids = EXCLUDED.comment_github_ids,
                metadata = EXCLUDED.metadata,
                updated_at = now()
            RETURNING id
            """,
            (
                mission_id,
                pr_id,
                root_comment_github_id,
                document_kind,
                document_text,
                github_url,
                file_path,
                line_number,
                comment_github_ids,
                Jsonb(metadata),
            ),
        ).fetchone()
    if row is None:
        raise RuntimeError("Failed to insert conversation document")
    return int(row["id"])


def parse_github_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
