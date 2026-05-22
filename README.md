# comment-data

우테코 미션 PR의 리뷰 코멘트를 GitHub API로 수집해 PostgreSQL에 저장하는 수집기입니다.

## Docker 실행

Docker Compose 실행을 권장합니다. 호스트 머신에 Python이나 `uv`를 설치하지 않아도 됩니다.

로컬 환경변수 파일을 만듭니다.

```bash
cp .env.example .env
```

`.env`의 `GITHUB_TOKEN`과 `OPENAI_API_KEY` 값을 실제 토큰으로 변경합니다. Docker Compose로 실행할 때는 collector/API 컨테이너에 DB 접속 주소를 자동으로 주입하므로 `DATABASE_URL`은 기본값 그대로 둬도 됩니다.

PostgreSQL을 실행합니다.

```bash
docker compose up -d db
```

`missions.yml`에 등록된 레포지토리에서 closed PR을 포함해 최신 PR 50개의 리뷰 코멘트를 수집합니다.

```bash
docker compose run --rm collector collect --missions missions.yml --pr-limit 50
```

수집기는 실행 시 필요한 테이블을 자동으로 생성합니다. 따라서 초기 DB 세팅 명령을 꼭 따로 실행할 필요는 없습니다. 수집 없이 스키마만 미리 생성하거나 확인하고 싶을 때만 아래 명령을 사용합니다.

```bash
docker compose run --rm collector init-db
```

기존 증분 기준을 무시하고 GitHub 코멘트를 다시 읽으려면 `--full-refresh`를 사용합니다.

```bash
docker compose run --rm collector collect --missions missions.yml --pr-limit 50 --full-refresh
```

수집된 conversation document에 embedding을 생성합니다. 검색 API는 이 embedding을 사용합니다.

```bash
docker compose run --rm collector embed-documents
```

이 명령은 `.env`의 `OPENAI_API_KEY`와 `OPENAI_EMBEDDING_MODEL`을 collector 컨테이너에 주입해 실행합니다. 키를 추가한 뒤에도 같은 오류가 나면 컨테이너 설정을 다시 읽도록 아래처럼 실행합니다.

```bash
docker compose run --rm --build collector embed-documents
```

검색 API 서버를 실행합니다.

```bash
docker compose up --build api
```

프론트엔드에서 CORS가 발생하면 `.env`의 `CORS_ORIGINS`에 프론트 주소를 추가합니다.

```env
CORS_ORIGINS=http://localhost:3000,http://localhost:5173,http://localhost:5175,https://techocon-web-vercel.vercel.app
```

검색 요청 예시:

```bash
curl 'http://localhost:8000/api/search?query=500에러%20예외처리시%20응답%20구조&track=BACKEND&limit=5'
```

GPT 요약 없이 embedding 기반 대표 문구만 보고 싶다면 `summarize=false`를 붙입니다.

```bash
curl 'http://localhost:8000/api/search?query=500에러%20예외처리시%20응답%20구조&track=BACKEND&limit=5&summarize=false'
```

대화 상세 조회:

```bash
curl 'http://localhost:8000/api/conversations/1'
```

## Make 명령

`make`가 설치되어 있다면 더 짧은 명령을 사용할 수 있습니다.

```bash
make db
make collect
make collect-full
make embed
make api
make init-db
```

## 로컬 Python 실행

개발 중에 호스트에서 `uv`로 직접 실행할 수도 있습니다.

```bash
uv sync
uv run comment-data collect --missions missions.yml --pr-limit 50
uv run comment-data embed-documents
```

로컬에서 API를 실행하려면 다음 명령을 사용합니다.

```bash
uv run uvicorn comment_data.api:app --host 127.0.0.1 --port 8000
```

CLI와 API는 `.env`를 자동으로 읽습니다. 따라서 `DATABASE_URL`, `GITHUB_TOKEN`, `OPENAI_API_KEY`를 명령어에 직접 넘기지 않아도 됩니다.

## 저장 데이터

GitHub에서 받은 원본 리뷰 코멘트는 `review_comments` 테이블에 저장합니다. `comment_github_id`에 unique 제약을 두고 upsert로 저장하므로, 수집 명령을 다시 실행해도 같은 코멘트가 중복 저장되지 않습니다.

벡터 검색에 사용할 대화 단위 문서는 `conversation_documents` 테이블에 별도로 저장합니다. 하나의 리뷰 스레드는 구분자를 포함한 하나의 row로 저장됩니다.

```text
[CONTEXT]
reviewer: reviewer-id

...

---

[REPLY]
reviewer: reviewer-id

...
```

대댓글이 없는 단독 코멘트는 `STANDALONE` conversation document로 저장합니다.

`conversation_embeddings` 테이블에는 `conversation_documents.embedding_text`의 OpenAI embedding을 저장합니다. 현재 기본 embedding 모델은 `.env.example` 기준 `text-embedding-3-small`입니다.

검색 API는 다음 흐름으로 동작합니다.

1. 사용자 query의 embedding 생성
2. 저장된 conversation embedding과 cosine similarity 계산
3. PostgreSQL full-text 점수를 보정값으로 합산
4. 유사한 conversation끼리 클러스터링
5. 각 클러스터를 GPT로 짧게 요약
6. 상세 대화는 `/api/conversations/{id}`에서 조회

## 수집 대상 설정

수집할 레포지토리는 `missions.yml`에 추가합니다. 아래 두 형식을 모두 지원합니다.

```yaml
missions:
  - track: BACKEND
    name: roomescape
    repository:
      owner: woowacourse
      name: spring-roomescape-member

  - track: BACKEND
    name: roomescape
    repository:
      url: https://github.com/woowacourse/spring-roomescape-member
```
