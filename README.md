# comment-data

우테코 미션 PR의 리뷰 코멘트를 GitHub API로 수집해 PostgreSQL에 저장하는 수집기입니다.

## Docker 실행

Docker Compose 실행을 권장합니다. 호스트 머신에 Python이나 `uv`를 설치하지 않아도 됩니다.

로컬 환경변수 파일을 만듭니다.

```bash
cp .env.example .env
```

`.env`의 `GITHUB_TOKEN` 값을 실제 GitHub 토큰으로 변경합니다. Docker Compose로 실행할 때는 collector 컨테이너에 DB 접속 주소를 자동으로 주입하므로 `DATABASE_URL`은 기본값 그대로 둬도 됩니다.

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

## Make 명령

`make`가 설치되어 있다면 더 짧은 명령을 사용할 수 있습니다.

```bash
make db
make collect
make collect-full
make init-db
```

## 로컬 Python 실행

개발 중에 호스트에서 `uv`로 직접 실행할 수도 있습니다.

```bash
uv sync
uv run comment-data collect --missions missions.yml --pr-limit 50
```

CLI는 `.env`를 자동으로 읽습니다. 따라서 `DATABASE_URL`과 `GITHUB_TOKEN`을 명령어에 직접 넘기지 않아도 됩니다.

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
