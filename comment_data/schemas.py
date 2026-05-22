"""API 응답 스키마.

엔드포인트 핸들러는 dict를 그대로 반환하지만, 각 라우트에 ``response_model`` 로
이 모델들을 연결하면 FastAPI가 OpenAPI(Swagger) 문서에 정상 응답 구조와 예제 데이터를
자동으로 포함시킨다. 필드 구성은 ``comment_data.search`` 와 ``comment_data.api`` 가
실제로 반환하는 dict 모양과 동일하게 맞춘다.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SearchDocument(BaseModel):
    """검색 그룹에 묶인 conversation document 한 건."""

    id: int = Field(description="conversation_documents.id. 상세 조회 키.", examples=[123])
    kind: str = Field(
        description="대화 종류: THREAD(질문-답변 스레드), STANDALONE(단독 코멘트), ORPHAN_REPLY(부모 미수집 답변).",
        examples=["THREAD"],
    )
    track: str = Field(examples=["BACKEND"])
    mission: str = Field(examples=["roomescape"])
    repository: str = Field(description="owner/name 형태.", examples=["woowacourse/spring-roomescape-member"])
    prNumber: int = Field(examples=[42])
    prTitle: str = Field(examples=["방탈출 예약 미션 1단계"])
    githubUrl: str = Field(
        description="해당 코멘트의 GitHub 원문 링크([GitHub PR 보기] 버튼).",
        examples=["https://github.com/woowacourse/spring-roomescape-member/pull/42#discussion_r123"],
    )
    filePath: str | None = Field(default=None, examples=["src/main/java/.../GlobalExceptionHandler.java"])
    lineNumber: int | None = Field(default=None, examples=[23])
    reviewers: list[str] = Field(
        description="응답 snippet에 포함된 공식 리뷰어 GitHub ID 목록(중복 제거).",
        examples=[["robinjoon"]],
    )
    snippet: str = Field(
        description="공식 리뷰어가 작성한 답변 본문 발췌. 화면에서 검색어 하이라이팅에 사용.",
        examples=["에러 응답에는 클라이언트가 분기할 수 있는 구조화된 정보가 필요합니다."],
    )
    score: float = Field(description="문서 점수(0~1). vector_score*0.8 + text_score*0.2.", examples=[0.87])


class SearchGroup(BaseModel):
    """비슷한 의도의 답변끼리 묶인 인사이트 카드 한 장."""

    groupId: str = Field(examples=["cluster-1"])
    groupTitle: str = Field(
        description="그룹 대표 제목. summarize=true면 GPT 생성, 아니면 대표 문서 파일명/키워드 기반.",
        examples=["에러 응답 구조"],
    )
    representativeAnswer: str = Field(
        description="그룹을 대표하는 2-3문장 요약/답변. summarize=true면 GPT 요약, 아니면 대표 snippet.",
        examples=[
            "에러 메시지만 내려주면 프론트엔드에서 상황별 분기 처리가 어렵습니다. "
            "errorCode나 HTTP 상태 코드 기반으로 응답을 구조화하라는 리뷰가 다수입니다. "
            "클라이언트가 에러 유형을 명확히 구분하도록 하기 위함입니다."
        ],
    )
    count: int = Field(description="그룹에 묶인 문서 수.", examples=[5])
    score: float = Field(description="그룹 대표 점수(대표 문서 기준).", examples=[0.87])
    documents: list[SearchDocument] = Field(description="그룹에 묶인 문서 목록(상위 5개).")


class SearchResponse(BaseModel):
    """검색 응답. items는 화면 인사이트 카드 목록에 대응."""

    items: list[SearchGroup]

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "items": [
                        {
                            "groupId": "cluster-1",
                            "groupTitle": "에러 응답 구조",
                            "representativeAnswer": (
                                "에러 메시지만 내려주면 프론트엔드에서 상황별 분기 처리가 어렵습니다. "
                                "errorCode나 HTTP 상태 코드 기반으로 응답을 구조화하라는 리뷰가 다수입니다. "
                                "클라이언트가 에러 유형을 명확히 구분하도록 하기 위함입니다."
                            ),
                            "count": 5,
                            "score": 0.87,
                            "documents": [
                                {
                                    "id": 123,
                                    "kind": "THREAD",
                                    "track": "BACKEND",
                                    "mission": "roomescape",
                                    "repository": "woowacourse/spring-roomescape-member",
                                    "prNumber": 42,
                                    "prTitle": "방탈출 예약 미션 1단계",
                                    "githubUrl": "https://github.com/woowacourse/spring-roomescape-member/pull/42#discussion_r123",
                                    "filePath": "src/main/java/.../GlobalExceptionHandler.java",
                                    "lineNumber": 23,
                                    "reviewers": ["robinjoon"],
                                    "snippet": "에러 응답에는 클라이언트가 분기할 수 있는 구조화된 정보가 필요합니다.",
                                    "score": 0.87,
                                }
                            ],
                        }
                    ]
                }
            ]
        }
    )


class ConversationComment(BaseModel):
    """대화에 포함된 원본 리뷰 코멘트 한 건."""

    role: str = Field(description="대화 내 역할: 첫 코멘트는 CONTEXT, 이후는 REPLY.", examples=["CONTEXT"])
    reviewer: str = Field(description="리뷰어 GitHub ID.", examples=["robinjoon"])
    avatarUrl: str | None = Field(default=None, examples=["https://avatars.githubusercontent.com/u/12345"])
    content: str = Field(
        description="마크다운 본문.",
        examples=["다른 정보 없이 메세지만 응답하게 설계한 이유가 있을까요?"],
    )
    githubUrl: str = Field(
        description="이 코멘트의 GitHub 원문 링크.",
        examples=["https://github.com/woowacourse/spring-roomescape-member/pull/42#discussion_r123"],
    )
    filePath: str | None = Field(default=None, examples=["src/main/java/.../GlobalExceptionHandler.java"])
    lineNumber: int | None = Field(default=None, examples=[23])
    createdAt: datetime = Field(examples=["2026-05-21T05:33:09Z"])
    updatedAt: datetime | None = Field(default=None, examples=["2026-05-21T05:40:00Z"])


class ConversationDetail(BaseModel):
    """대화 상세. 그룹 카드 클릭 시 원본 코멘트들을 시간순으로 반환."""

    id: int = Field(examples=[123])
    kind: str = Field(examples=["THREAD"])
    documentText: str = Field(
        description="CONTEXT/REPLY 구분자를 포함한 원본 대화 텍스트.",
        examples=["[CONTEXT]\nreviewer: robinjoon\n...\n\n---\n\n[REPLY]\nreviewer: yj9107v\n..."],
    )
    githubUrl: str = Field(
        examples=["https://github.com/woowacourse/spring-roomescape-member/pull/42#discussion_r123"]
    )
    filePath: str | None = Field(default=None, examples=["src/main/java/.../GlobalExceptionHandler.java"])
    lineNumber: int | None = Field(default=None, examples=[23])
    track: str = Field(examples=["BACKEND"])
    mission: str = Field(examples=["roomescape"])
    repository: str = Field(examples=["woowacourse/spring-roomescape-member"])
    prNumber: int = Field(examples=[42])
    prTitle: str = Field(examples=["방탈출 예약 미션 1단계"])
    comments: list[ConversationComment]

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "id": 123,
                    "kind": "THREAD",
                    "documentText": (
                        "[CONTEXT]\nreviewer: robinjoon\ncreated_at: 2026-05-21T05:33:09+00:00\n\n"
                        "다른 정보 없이 메세지만 응답하게 설계한 이유가 있을까요?\n\n---\n\n"
                        "[REPLY]\nreviewer: yj9107v\ncreated_at: 2026-05-21T08:26:36+00:00\n\n"
                        "상태 코드만으로는 구체적 상황 구분이 어려워 errorCode를 함께 내리도록 수정했습니다."
                    ),
                    "githubUrl": "https://github.com/woowacourse/spring-roomescape-member/pull/42#discussion_r123",
                    "filePath": "src/main/java/.../GlobalExceptionHandler.java",
                    "lineNumber": 23,
                    "track": "BACKEND",
                    "mission": "roomescape",
                    "repository": "woowacourse/spring-roomescape-member",
                    "prNumber": 42,
                    "prTitle": "방탈출 예약 미션 1단계",
                    "comments": [
                        {
                            "role": "CONTEXT",
                            "reviewer": "robinjoon",
                            "avatarUrl": "https://avatars.githubusercontent.com/u/12345",
                            "content": "다른 정보 없이 메세지만 응답하게 설계한 이유가 있을까요?",
                            "githubUrl": "https://github.com/woowacourse/spring-roomescape-member/pull/42#discussion_r123",
                            "filePath": "src/main/java/.../GlobalExceptionHandler.java",
                            "lineNumber": 23,
                            "createdAt": "2026-05-21T05:33:09Z",
                            "updatedAt": None,
                        },
                        {
                            "role": "REPLY",
                            "reviewer": "yj9107v",
                            "avatarUrl": "https://avatars.githubusercontent.com/u/67890",
                            "content": "상태 코드만으로는 구체적 상황 구분이 어려워 errorCode를 함께 내리도록 수정했습니다.",
                            "githubUrl": "https://github.com/woowacourse/spring-roomescape-member/pull/42#discussion_r456",
                            "filePath": "src/main/java/.../GlobalExceptionHandler.java",
                            "lineNumber": 23,
                            "createdAt": "2026-05-21T08:26:36Z",
                            "updatedAt": None,
                        },
                    ],
                }
            ]
        }
    )


class TrackOption(BaseModel):
    """트랙 필터 항목."""

    track: str = Field(examples=["BACKEND"])
    documentCount: int = Field(description="해당 트랙의 대화 문서 수.", examples=[128])


class MissionOption(BaseModel):
    """미션 필터 항목."""

    id: int = Field(examples=[1])
    track: str = Field(examples=["BACKEND"])
    name: str = Field(examples=["roomescape"])
    repository: str = Field(examples=["woowacourse/spring-roomescape-member"])
    documentCount: int = Field(description="해당 미션의 대화 문서 수.", examples=[64])


class HealthResponse(BaseModel):
    """헬스 체크 응답."""

    status: str = Field(examples=["ok"])


class ErrorResponse(BaseModel):
    """오류 응답."""

    detail: str = Field(examples=["Conversation not found"])
