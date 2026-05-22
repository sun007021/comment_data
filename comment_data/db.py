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
    embedding_text TEXT NOT NULL DEFAULT '',
    github_url TEXT NOT NULL,
    file_path TEXT NULL,
    line_number INT NULL,
    comment_github_ids BIGINT[] NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (root_comment_github_id)
);

CREATE TABLE IF NOT EXISTS conversation_embeddings (
    conversation_document_id BIGINT PRIMARY KEY
        REFERENCES conversation_documents(id) ON DELETE CASCADE,
    embedding_model VARCHAR(100) NOT NULL,
    embedding JSONB NOT NULL,
    dimensions INT NOT NULL,
    source_hash VARCHAR(32) NOT NULL,
    embedded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE conversation_documents
    ADD COLUMN IF NOT EXISTS embedding_text TEXT NOT NULL DEFAULT '';

UPDATE conversation_documents
SET embedding_text = document_text
WHERE embedding_text = '';

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
CREATE INDEX IF NOT EXISTS idx_conversation_embeddings_model ON conversation_embeddings(embedding_model);
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


def fetch_review_comments_by_github_ids(
    connection: psycopg.Connection[Any],
    *,
    comment_github_ids: list[int],
) -> list[dict[str, Any]]:
    if not comment_github_ids:
        return []

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
            WHERE comment_github_id = ANY(%s)
            ORDER BY created_at ASC, comment_github_id ASC
            """,
            (comment_github_ids,),
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
    embedding_text: str,
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
                mission_id, pr_id, root_comment_github_id, document_kind, document_text, embedding_text,
                github_url, file_path, line_number, comment_github_ids, metadata
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (root_comment_github_id)
            DO UPDATE SET
                mission_id = EXCLUDED.mission_id,
                pr_id = EXCLUDED.pr_id,
                document_kind = EXCLUDED.document_kind,
                document_text = EXCLUDED.document_text,
                embedding_text = EXCLUDED.embedding_text,
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
                embedding_text,
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


def fetch_documents_needing_embeddings(
    connection: psycopg.Connection[Any],
    *,
    model: str,
    limit: int,
) -> list[dict[str, Any]]:
    with connection.cursor() as cursor:
        rows = cursor.execute(
            """
            SELECT cd.id, cd.embedding_text
            FROM conversation_documents cd
            LEFT JOIN conversation_embeddings ce
                ON ce.conversation_document_id = cd.id
            WHERE ce.conversation_document_id IS NULL
                OR ce.embedding_model <> %s
                OR ce.source_hash <> md5(cd.embedding_text)
            ORDER BY cd.updated_at ASC, cd.id ASC
            LIMIT %s
            """,
            (model, limit),
        ).fetchall()
    return list(rows)


def upsert_conversation_embedding(
    connection: psycopg.Connection[Any],
    *,
    conversation_document_id: int,
    model: str,
    embedding: list[float],
    source_text: str,
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO conversation_embeddings (
                conversation_document_id, embedding_model, embedding, dimensions, source_hash, embedded_at
            )
            VALUES (%s, %s, %s, %s, md5(%s), now())
            ON CONFLICT (conversation_document_id)
            DO UPDATE SET
                embedding_model = EXCLUDED.embedding_model,
                embedding = EXCLUDED.embedding,
                dimensions = EXCLUDED.dimensions,
                source_hash = EXCLUDED.source_hash,
                embedded_at = now()
            """,
            (
                conversation_document_id,
                model,
                Jsonb(embedding),
                len(embedding),
                source_text,
            ),
        )


def fetch_search_documents(
    connection: psycopg.Connection[Any],
    *,
    embedding_model: str,
    query: str,
    track: str | None,
    mission: str | None,
    repository: str | None,
    max_candidates: int,
) -> list[dict[str, Any]]:
    filters = ["ce.embedding_model = %s"]
    filter_params: list[Any] = [embedding_model]

    if track:
        filters.append("m.track = %s")
        filter_params.append(track)
    if mission:
        filters.append("m.name = %s")
        filter_params.append(mission)
    if repository:
        owner, repo = repository.split("/", 1) if "/" in repository else ("", repository)
        filters.append("m.repository_owner = %s AND m.repository_name = %s")
        filter_params.extend([owner, repo])

    params = [query, *filter_params, max_candidates]
    where_sql = " AND ".join(filters)

    with connection.cursor() as cursor:
        rows = cursor.execute(
            f"""
            SELECT
                cd.id,
                cd.document_kind,
                cd.document_text,
                cd.embedding_text,
                cd.github_url,
                cd.file_path,
                cd.line_number,
                cd.comment_github_ids,
                cd.metadata,
                ce.embedding,
                m.track,
                m.name AS mission_name,
                m.repository_owner,
                m.repository_name,
                pr.pr_number,
                pr.title AS pr_title,
                ts_rank_cd(to_tsvector('simple', cd.document_text), plainto_tsquery('simple', %s)) AS text_rank
            FROM conversation_documents cd
            JOIN conversation_embeddings ce ON ce.conversation_document_id = cd.id
            JOIN missions m ON m.id = cd.mission_id
            JOIN pull_requests pr ON pr.id = cd.pr_id
            WHERE {where_sql}
            ORDER BY text_rank DESC, cd.updated_at DESC
            LIMIT %s
            """,
            params,
        ).fetchall()
    return list(rows)


def fetch_conversation_detail(
    connection: psycopg.Connection[Any],
    *,
    conversation_id: int,
) -> dict[str, Any] | None:
    with connection.cursor() as cursor:
        document = cursor.execute(
            """
            SELECT
                cd.id,
                cd.document_kind,
                cd.document_text,
                cd.github_url,
                cd.file_path,
                cd.line_number,
                cd.comment_github_ids,
                cd.metadata,
                m.track,
                m.name AS mission_name,
                m.repository_owner,
                m.repository_name,
                pr.pr_number,
                pr.title AS pr_title
            FROM conversation_documents cd
            JOIN missions m ON m.id = cd.mission_id
            JOIN pull_requests pr ON pr.id = cd.pr_id
            WHERE cd.id = %s
            """,
            (conversation_id,),
        ).fetchone()
        if document is None:
            return None

        comments = cursor.execute(
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
            WHERE comment_github_id = ANY(%s)
            ORDER BY created_at ASC, comment_github_id ASC
            """,
            (document["comment_github_ids"],),
        ).fetchall()

    detail = dict(document)
    detail["comments"] = list(comments)
    return detail


def list_track_options(connection: psycopg.Connection[Any]) -> list[dict[str, Any]]:
    with connection.cursor() as cursor:
        rows = cursor.execute(
            """
            SELECT m.track, count(cd.id) AS document_count
            FROM missions m
            LEFT JOIN conversation_documents cd ON cd.mission_id = m.id
            GROUP BY m.track
            ORDER BY m.track
            """
        ).fetchall()
    return list(rows)


def list_mission_options(
    connection: psycopg.Connection[Any],
    *,
    track: str | None,
) -> list[dict[str, Any]]:
    params: list[Any] = []
    where_sql = ""
    if track:
        where_sql = "WHERE m.track = %s"
        params.append(track)

    with connection.cursor() as cursor:
        rows = cursor.execute(
            f"""
            SELECT
                m.id,
                m.track,
                m.name,
                m.repository_owner,
                m.repository_name,
                count(cd.id) AS document_count
            FROM missions m
            LEFT JOIN conversation_documents cd ON cd.mission_id = m.id
            {where_sql}
            GROUP BY m.id, m.track, m.name, m.repository_owner, m.repository_name
            ORDER BY m.track, m.name, m.repository_owner, m.repository_name
            """,
            params,
        ).fetchall()
    return list(rows)


def parse_github_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
