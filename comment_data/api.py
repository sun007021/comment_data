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
from comment_data.schemas import (
    ConversationDetail,
    ErrorResponse,
    HealthResponse,
    MissionOption,
    SearchResponse,
    TrackOption,
)
from comment_data.search import SearchOptions, search_conversations

load_dotenv(Path(".env"))

app = FastAPI(
    title="PR Insight API",
    version="0.1.0",
    description=(
        "우테코 미션 PR 리뷰 코멘트를 자연어로 검색하고, 비슷한 의도의 답변끼리 "
        "그룹화하여 요약(2-3문장)과 PR 원문 링크를 함께 제공하는 API."
    ),
)


@app.get("/health", response_model=HealthResponse, tags=["system"], summary="헬스 체크")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get(
    "/api/search",
    response_model=SearchResponse,
    tags=["search"],
    summary="리뷰 코멘트 검색 (유사 답변 그룹화)",
    description=(
        "자연어 query로 conversation document를 검색한 뒤 비슷한 의도의 답변끼리 그룹화한다. "
        "각 그룹(items[])은 화면 인사이트 카드 한 장에 대응하며, 대표 요약과 PR 아웃링크를 포함한다."
    ),
)
def search(
    query: str = Query(min_length=1, description='검색할 자연어 질문', examples=["500에러 예외처리시 응답 구조"]),
    track: str | None = Query(default=None, description="트랙 필터", examples=["BACKEND"]),
    mission: str | None = Query(default=None, description="미션 이름 필터", examples=["roomescape"]),
    repository: str | None = Query(
        default=None, description="레포지토리 풀네임 필터", examples=["woowacourse/spring-roomescape-member"]
    ),
    limit: int = Query(default=5, ge=1, le=50, description="반환할 최대 그룹 수"),
    summarize: bool = Query(default=True, description="true면 GPT로 그룹 제목/요약 생성, false면 대표 snippet 사용"),
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


@app.get(
    "/api/conversations/{conversation_id}",
    response_model=ConversationDetail,
    tags=["conversations"],
    summary="대화 상세 조회",
    description=(
        "그룹 카드 클릭 시 호출한다. conversation document에 묶인 원본 리뷰 코멘트들을 "
        "시간순(CONTEXT → REPLY)으로 반환하며, 각 코멘트는 GitHub 원문 링크를 포함한다."
    ),
    responses={
        404: {
            "model": ErrorResponse,
            "description": "해당 conversation을 찾을 수 없음",
            "content": {"application/json": {"example": {"detail": "Conversation not found"}}},
        }
    },
)
def get_conversation(conversation_id: int) -> dict[str, Any]:
    database_url = require_env("DATABASE_URL")
    with connect(database_url) as connection:
        detail = fetch_conversation_detail(connection, conversation_id=conversation_id)

    if detail is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    return to_conversation_response(detail)


@app.get(
    "/api/tracks",
    response_model=list[TrackOption],
    tags=["filters"],
    summary="트랙 목록 조회",
    description="검색 필터 UI에 노출할 트랙 목록과 각 트랙의 문서 수를 반환한다.",
)
def list_tracks() -> list[dict[str, Any]]:
    database_url = require_env("DATABASE_URL")
    with connect(database_url) as connection:
        return [
            {"track": row["track"], "documentCount": row["document_count"]}
            for row in list_track_options(connection)
        ]


@app.get(
    "/api/missions",
    response_model=list[MissionOption],
    tags=["filters"],
    summary="미션 목록 조회",
    description="검색 필터 UI에 노출할 미션 목록을 반환한다. track으로 필터링할 수 있다.",
)
def list_missions(
    track: str | None = Query(default=None, description="특정 트랙의 미션만 조회", examples=["BACKEND"]),
) -> list[dict[str, Any]]:
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
