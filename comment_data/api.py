import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query

from comment_data.cli import load_dotenv
from comment_data.db import (
    connect,
    fetch_conversation_detail,
    init_db,
    list_mission_options,
    list_track_options,
)
from comment_data.openai_client import OpenAIClient
from comment_data.search import SearchOptions, search_conversations

load_dotenv(Path(".env"))

app = FastAPI(title="PR Insight API", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/search")
def search(
    query: str = Query(min_length=1),
    track: str | None = None,
    mission: str | None = None,
    repository: str | None = None,
    limit: int = Query(default=5, ge=1, le=50),
    summarize: bool = True,
) -> dict[str, Any]:
    database_url = require_env("DATABASE_URL")
    embedding_model = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
    summary_model = os.getenv("OPENAI_SUMMARY_MODEL", "gpt-5.2")
    client = OpenAIClient(require_env("OPENAI_API_KEY"))

    with connect(database_url) as connection:
        init_db(connection)
        return search_conversations(
            connection,
            client,
            SearchOptions(
                query=query,
                track=track,
                mission=mission,
                repository=repository,
                limit=limit,
                summarize=summarize,
                embedding_model=embedding_model,
                summary_model=summary_model,
            ),
        )


@app.get("/api/conversations/{conversation_id}")
def get_conversation(conversation_id: int) -> dict[str, Any]:
    database_url = require_env("DATABASE_URL")
    with connect(database_url) as connection:
        detail = fetch_conversation_detail(connection, conversation_id=conversation_id)

    if detail is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    return to_conversation_response(detail)


@app.get("/api/tracks")
def list_tracks() -> list[dict[str, Any]]:
    database_url = require_env("DATABASE_URL")
    with connect(database_url) as connection:
        return [
            {"track": row["track"], "documentCount": row["document_count"]}
            for row in list_track_options(connection)
        ]


@app.get("/api/missions")
def list_missions(track: str | None = None) -> list[dict[str, Any]]:
    database_url = require_env("DATABASE_URL")
    with connect(database_url) as connection:
        return [
            {
                "id": row["id"],
                "track": row["track"],
                "name": row["name"],
                "repository": f"{row['repository_owner']}/{row['repository_name']}",
                "documentCount": row["document_count"],
            }
            for row in list_mission_options(connection, track=track)
        ]


def to_conversation_response(detail: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": detail["id"],
        "kind": detail["document_kind"],
        "documentText": detail["document_text"],
        "githubUrl": detail["github_url"],
        "filePath": detail["file_path"],
        "lineNumber": detail["line_number"],
        "track": detail["track"],
        "mission": detail["mission_name"],
        "repository": f"{detail['repository_owner']}/{detail['repository_name']}",
        "prNumber": detail["pr_number"],
        "prTitle": detail["pr_title"],
        "comments": [to_comment_response(comment, index) for index, comment in enumerate(detail["comments"])],
    }


def to_comment_response(comment: dict[str, Any], index: int) -> dict[str, Any]:
    return {
        "role": "CONTEXT" if index == 0 else "REPLY",
        "reviewer": comment["reviewer_id"],
        "avatarUrl": comment["reviewer_avatar_url"],
        "content": comment["content"],
        "githubUrl": comment["github_url"],
        "filePath": comment["file_path"],
        "lineNumber": comment["line_number"],
        "createdAt": comment["created_at"],
        "updatedAt": comment["updated_at"],
    }


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise HTTPException(status_code=500, detail=f"{name} is required")
    return value
