# 검색 백엔드 및 유사 답변 그룹화 구현 계획

## 목표

사용자가 자연어로 질문을 입력하면, 수집된 우테코 PR 리뷰 코멘트 중 관련 있는 대화들을 찾아 보여준다.

예시 질문:

```text
500에러 예외처리시 응답 구조
```

검색 결과는 단순 코멘트 나열이 아니라 다음 형태를 목표로 한다.

- 비슷한 의도의 답변끼리 그룹화
- 각 그룹에는 간단한 대표 답변 또는 대표 코멘트 표시
- 상세 내용은 내부 conversation detail 또는 GitHub 원문 링크로 이동
- GPT API 없이도 동작하는 MVP를 먼저 구현
- 이후 필요하면 GPT API를 후처리 요약 단계에만 선택적으로 추가

## 현재 데이터 구조

원본 GitHub 리뷰 코멘트는 `review_comments`에 저장한다.

- comment 1개 = row 1개
- `comment_github_id` unique
- 재수집 시 upsert하므로 중복 저장되지 않음

벡터 검색용 대화 문서는 `conversation_documents`에 저장한다.

- 질문/맥락 + 답변 스레드 1개 = row 1개
- 대댓글 없는 단독 코멘트 = `STANDALONE` row 1개
- `document_text`에 구분자를 포함해 저장

형식:

```text
[CONTEXT]
reviewer: reviewer-id
created_at: 2026-05-21T05:33:09+00:00

...

---

[REPLY]
reviewer: reviewer-id
created_at: 2026-05-21T08:26:36+00:00

...
```

## 권장 검색 방식

벡터 검색만 사용하지 말고 Hybrid Search를 사용한다.

이유:

- 자연어 의미 검색은 vector search가 강함
- `500`, `400`, `HTTP`, `ErrorCode`, 클래스명, 메서드명 같은 정확한 토큰은 full-text search가 강함
- 예외 처리/응답 구조 같은 주제는 의미와 키워드가 모두 중요함

검색 흐름:

1. 사용자의 query를 입력받는다.
2. query embedding을 생성한다.
3. `conversation_documents` 대상으로 vector similarity 검색을 수행한다.
4. PostgreSQL full-text search도 함께 수행한다.
5. 두 결과를 합산해 rerank한다.
6. 상위 결과를 embedding similarity 기준으로 다시 그룹화한다.
7. 각 그룹의 대표 문서를 선택한다.
8. API 응답에는 그룹 요약, 대표 문서, 상세 링크, 원문 코멘트 정보를 포함한다.

## GPT API 사용 여부

GPT API는 필수가 아니다.

MVP에서는 GPT 없이 다음 방식으로 구현한다.

- embedding으로 관련 conversation 검색
- embedding similarity로 비슷한 답변끼리 그룹화
- 대표 답변은 그룹 내에서 query와 가장 가까운 conversation을 사용
- 상세 내용은 `conversation_documents.id` 기반 detail API 또는 GitHub 링크로 제공

GPT API는 고도화 단계에서만 선택적으로 사용한다.

사용하면 좋은 지점:

- 그룹 제목 생성
- 여러 conversation을 종합한 짧은 답변 생성
- 사용자의 질문 의도에 맞춘 요약

사용하지 않아도 되는 지점:

- 유사 conversation 검색
- 비슷한 답변끼리 묶기
- 원문 상세 링크 제공

권장 고도화 방식:

1. 검색과 클러스터링은 embedding으로 수행
2. 각 그룹의 상위 3개 conversation만 GPT에 전달
3. GPT는 그룹 제목과 요약만 생성
4. 원문 링크와 원본 코멘트는 DB 기준으로 제공

## DB 확장 계획

### 1. embedding 저장

PostgreSQL에 pgvector를 사용하는 방식을 우선 고려한다.

Docker Compose의 PostgreSQL 이미지는 pgvector 지원 이미지로 변경하는 것이 좋다.

예:

```yaml
image: pgvector/pgvector:pg16
```

스키마:

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE conversation_embeddings (
    conversation_document_id BIGINT PRIMARY KEY
        REFERENCES conversation_documents(id) ON DELETE CASCADE,
    embedding_model VARCHAR(100) NOT NULL,
    embedding vector(1536) NOT NULL,
    embedded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

주의:

- `1536`은 embedding 모델에 따라 달라질 수 있다.
- 모델 변경 가능성을 고려해 embedding은 별도 테이블에 둔다.
- 모델을 바꿀 때는 `embedding_model` 기준으로 재생성 가능해야 한다.

### 2. embedding_text 추가

현재 `document_text`는 원문 보존에 가깝다.

검색 품질을 높이기 위해 `conversation_documents`에 embedding 전용 텍스트를 추가하는 것이 좋다.

```sql
ALTER TABLE conversation_documents
ADD COLUMN embedding_text TEXT NULL;
```

초기에는 `document_text`와 동일하게 채워도 된다.

추후에는 다음처럼 정제할 수 있다.

```text
주제: 예외 처리와 에러 응답 구조
맥락: 리뷰어가 에러 응답에 메시지만 포함한 이유와 프론트엔드 분기 가능성을 질문함
답변: 메시지만으로는 에러 상황을 구분하기 어렵고, 상태 코드나 에러 코드 같은 구조화된 응답이 필요함
원문:
[CONTEXT] ...
[REPLY] ...
```

GPT 없는 MVP에서는 `embedding_text = document_text`로 시작한다.

## 백엔드 API 설계

### Search API

```http
GET /api/search?query=500에러 예외처리시 응답 구조&track=BACKEND&mission=roomescape&limit=20
```

요청 파라미터:

- `query`: 필수
- `track`: 선택
- `mission`: 선택
- `repository`: 선택
- `limit`: 선택, 기본 20

응답 예시:

```json
{
  "items": [
    {
      "groupId": "cluster-1",
      "groupTitle": "에러 응답 구조",
      "representativeAnswer": "에러 메시지만 내려주면 프론트엔드에서 상황별 분기 처리가 어렵기 때문에 errorCode나 상태 코드 기반 구조화가 필요하다는 리뷰입니다.",
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
          "prTitle": "방탈출 예약 미션",
          "githubUrl": "https://github.com/...",
          "filePath": "src/main/...",
          "lineNumber": 23,
          "reviewers": ["robinjoon", "yj9107v"],
          "snippet": "다른 정보 없이 메세지만 응답하게 설계한 이유가 있을까요?"
        }
      ]
    }
  ]
}
```

MVP에서는 `groupTitle`과 `representativeAnswer`를 GPT로 만들지 않는다.

대신:

- `groupTitle`: 대표 문서의 file path, 키워드, 또는 첫 문장 기반
- `representativeAnswer`: 그룹 내 query와 가장 가까운 문서의 snippet

### Conversation Detail API

```http
GET /api/conversations/{conversationDocumentId}
```

응답 예시:

```json
{
  "id": 123,
  "kind": "THREAD",
  "documentText": "...",
  "githubUrl": "https://github.com/...",
  "filePath": "src/main/...",
  "lineNumber": 23,
  "comments": [
    {
      "role": "CONTEXT",
      "reviewer": "robinjoon",
      "avatarUrl": "https://...",
      "content": "...",
      "githubUrl": "https://github.com/...",
      "createdAt": "2026-05-21T05:33:09Z"
    },
    {
      "role": "REPLY",
      "reviewer": "yj9107v",
      "avatarUrl": "https://...",
      "content": "...",
      "githubUrl": "https://github.com/...",
      "createdAt": "2026-05-21T08:26:36Z"
    }
  ]
}
```

detail API는 `conversation_documents.comment_github_ids`를 기준으로 `review_comments`를 조회해 구성한다.

## 내부 컴포넌트 설계

### SearchController

역할:

- HTTP 요청 파라미터 검증
- `query`, filter, limit을 `SearchService`에 전달
- API 응답 DTO 반환

### SearchService

역할:

- query embedding 생성
- vector search 수행
- full-text search 수행
- 두 검색 결과를 병합하고 rerank
- 비슷한 문서끼리 그룹화
- 대표 문서 및 snippet 선택

### ConversationDocumentRepository

역할:

- vector similarity query
- full-text query
- 필터 조건 적용
- conversation document 조회

### ReviewCommentRepository

역할:

- `comment_github_ids` 기반 원본 코멘트 조회
- detail API 응답용 comment list 구성

### EmbeddingClient

역할:

- embedding API 호출부 격리
- OpenAI, local model, 다른 provider로 교체 가능하게 설계

### Optional SummaryClient

역할:

- GPT API 등으로 그룹 제목/요약 생성
- MVP에서는 구현하지 않음
- 나중에 feature flag로 켤 수 있게 분리

## 검색 점수 계산

초기 점수 계산:

```text
final_score = vector_score * 0.7 + text_score * 0.3
```

조정 기준:

- 자연어 질문 중심이면 vector 비중을 높인다.
- HTTP status, 예외 클래스명, 메서드명 검색 품질이 낮으면 text 비중을 높인다.

## 그룹화 전략

MVP에서는 검색 결과 상위 N개만 대상으로 그룹화한다.

권장값:

- 검색 후보: 50개
- 최종 그룹: 5개 이하
- 그룹당 노출 문서: 3개 이하

간단한 threshold 기반 그룹화:

1. 검색 결과를 score 순으로 정렬한다.
2. 아직 그룹에 들어가지 않은 문서를 하나 고른다.
3. 해당 문서와 cosine similarity가 `0.82` 이상인 문서를 같은 그룹으로 묶는다.
4. 그룹 대표 문서는 사용자 query와 가장 가까운 문서로 선택한다.

초기 threshold:

```text
same_group_threshold = 0.82
```

데이터를 보며 조정한다.

## 구현 순서

1. PostgreSQL 이미지를 pgvector 지원 이미지로 변경
2. `conversation_embeddings` 테이블 추가
3. `conversation_documents.embedding_text` 컬럼 추가
4. embedding 생성 CLI 추가
   - 예: `comment-data embed-conversations`
   - embedding 없는 conversation만 처리
   - `--force` 옵션으로 재생성 가능
5. Search API 구현
6. Conversation Detail API 구현
7. Hybrid search 및 rerank 구현
8. 검색 결과 그룹화 구현
9. 대표 snippet 선택 구현
10. 필요 시 GPT 기반 그룹 제목/요약 기능 추가

## GPT 없는 MVP 기준

필수:

- vector search
- full-text search
- score 병합
- similarity grouping
- 대표 문서 선택
- detail API

제외:

- GPT 요약
- GPT 기반 의도 분류
- GPT 기반 그룹 제목 생성

## GPT 고도화 기준

추후 GPT API를 붙일 경우에도 전체 검색에 GPT를 사용하지 않는다.

사용 위치:

- 검색된 결과 그룹의 상위 문서 2-3개만 입력
- 그룹 제목 생성
- 2-3문장 요약 생성

주의:

- GPT가 만든 답변만 단독으로 보여주지 않는다.
- 항상 원문 conversation 링크와 GitHub 링크를 함께 제공한다.
- hallucination 방지를 위해 입력 문서 밖의 내용을 만들지 말라고 제한한다.
- 가성비 모델을 사용한다

## 수용 기준

MVP 완료 조건:

- 사용자가 자연어 query로 검색할 수 있다.
- 관련 conversation document가 score 순으로 반환된다.
- 비슷한 의도의 결과가 그룹화된다.
- 각 그룹에 대표 snippet이 표시된다.
- 상세 API에서 원본 context/reply 코멘트를 확인할 수 있다.
- GitHub 원문 링크로 이동할 수 있다.
- GPT API 없이 동작한다.
