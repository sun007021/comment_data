
```markdown
# 🚀 PR Insight - 우테코 코드리뷰 통합 검색 서비스 기획 및 설계서

우테코 크루들이 동일한 미션을 수행하며 생성하는 **"Pull Request(PR) 리뷰 코멘트 데이터"**를 자산화하여, 원하는 키워드(예: 예외 처리, 트랜잭션 등)의 질문과 답변을 한눈에 모아볼 수 있는 학습 보조 서비스의 최종 스펙 문서입니다.

---

## 1. 서비스 개요 및 핵심 UI/UX 스펙

본 서비스는 수천 개의 우테코 미션 PR 속에 담긴 리뷰어들의 인사이트를 키워드 기반으로 탐색하는 서비스입니다.

* **트랙 및 미션 필터링:** 백엔드, 프론트엔드, 모바일 등 분야별 필터와 [방탈출 사용자 예약], [쇼핑 주문], [페이먼츠] 등 기수별 핵심 미션 필터를 제공합니다.
* **인사이트 카드 UI:** * 검색 키워드가 포함된 리뷰 코멘트 본문을 하이라이팅하여 보여줍니다.
  * 동일한 질문/컨텍스트에 대해 여러 리뷰어(예: 컴프, 브라운)가 답변한 경우, 하나의 인사이트 카드에 그룹화하여 노출합니다.
  * **[GitHub PR 보기]** 아웃링크를 제공하여 실제 소스코드와 맥락을 즉시 확인할 수 있도록 합니다.

---

## 2. GitHub REST API 구조 및 연동 설계

GitHub API의 Rate Limit을 회피하고 빠른 검색 속도를 보장하기 위해, **실시간 조회가 아닌 주기적 배치(Batch) 수집 방식을 채택**합니다.

### ① 트랙별 미션 대상 PR 목록 조회
우테코 조직(`woowacourse`) 레포지토리 내의 수집 대상 PR 번호와 크루 정보를 식별합니다.
* **Endpoint:** `GET /repos/{owner}/{repo}/pulls?state=all&per_page=100`
* **주요 추출 필드:**
  * `number`: PR 번호 (식별자)
  * `user.login`: PR을 생성한 크루의 GitHub ID
  * `title`: PR 제목 (단계별 미션 구분용)

### ② 레포지토리 내 전체 리뷰 코멘트 일괄 조회
레포지토리 단위로 전체 리뷰 코멘트를 타임라인 순으로 가져오는 최적화 엔드포인트를 사용합니다.
* **Endpoint:** `GET /repos/{owner}/{repo}/pulls/comments?sort=created&direction=desc&per_page=100`
* **주요 추출 필드:**
  * `id`: GitHub 내 리뷰 코멘트 고유 ID
  * `body`: 리뷰어가 작성한 마크다운 형태의 코멘트 본문 (검색 대상)
  * `user.login`: 리뷰어(또는 답변한 크루)의 GitHub ID
  * `in_reply_to_id`: 대댓글 구조 확인용 부모 코멘트 ID (질문-답변 스레드 및 리뷰어 그룹화의 핵심)
  * `html_url`: 실제 GitHub에서 해당 코멘트를 볼 수 있는 URL ([GitHub PR 보기] 버튼에 매핑)
  * `path` & `line`: 코멘트가 달린 대상 파일 경로 및 소스코드 라인 번호

---

## 3. 데이터베이스 (DB) 스키마 디자인 (UI 피드백 반영)

화면의 분야(트랙) 필터와 리뷰어 그룹화 UI를 매끄럽게 지원하기 위해 보완된 관계형 데이터베이스 구조입니다.

```sql
-- 1. 미션 정보 테이블 (분야/트랙 필터 반영)
CREATE TABLE Mission (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    track VARCHAR(50) NOT NULL,                 -- 예: "BACKEND", "FRONTEND", "MOBILE"
    name VARCHAR(100) NOT NULL,                 -- 예: "방탈출 사용자 예약", "쇼핑 주문"
    repository_name VARCHAR(150) NOT NULL       -- 예: "woowacourse/java-roomescape"
);

-- 2. 크루들이 제출한 PR 정보 테이블
CREATE TABLE PullRequest (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    mission_id BIGINT NOT NULL,
    pr_number INT NOT NULL,
    crew_github_id VARCHAR(100) NOT NULL,
    FOREIGN KEY (mission_id) REFERENCES Mission(id)
);

-- 3. 코드 라인에 달린 리뷰 코멘트 테이블 (스레드 및 아웃링크 반영)
CREATE TABLE ReviewComment (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    pr_id BIGINT NOT NULL,
    comment_github_id BIGINT NOT NULL UNIQUE,
    parent_github_id BIGINT NULL,                -- in_reply_to_id 맵핑 (질문-답변 스레드 그룹화용)
    reviewer_id VARCHAR(100) NOT NULL,           -- 리뷰어 혹은 크루 GitHub ID (컴프, 브라운 등)
    reviewer_avatar_url VARCHAR(255) NULL,       -- 리뷰어 프로필 이미지 URL
    content TEXT NOT NULL,                       -- 코멘트 마크다운 본문
    github_url VARCHAR(255) NOT NULL,            -- GitHub PR 보기 링크용 URL
    file_path VARCHAR(255) NOT NULL,             -- 리뷰 대상 파일 경로
    line_number INT NOT NULL,                    -- 리뷰 대상 코드 라인
    created_at TIMESTAMP NOT NULL,
    FOREIGN KEY (pr_id) REFERENCES PullRequest(id),
    FOREIGN KEY (parent_github_id) REFERENCES ReviewComment(comment_github_id)
);

```

---

## 4. 데이터 흐름 및 아키텍처 (Data Flow)

```
[GitHub API] 
     │
     ▼ (1시간/하루 주기 Scheduler: Spring Batch 등)
[Data Ingestion Layer] -> 최신 코멘트 수집 및 부모-자식 ID 기준 스레드 묶기
     │
     ▼
[Database (RDB / FT Index)] -> 트랙(Track) 및 미션별 데이터 정제 후 적재
     │
     ▼ (유저가 "예외 처리" 검색 + 백엔드 + 방탈출 미션 필터링)
[Backend Server] -> Full-Text Search 및 동일 스레드 내 리뷰어 다중 매핑 그룹화 로직 수행
     │
     ▼
[Frontend UI (PR Insight)] -> 검색어 하이라이팅, 리뷰어 프로필 모음, 마크다운 렌더링

```

---

## 5. 핵심 개발 및 고도화 과제

1. **유사 답변 및 스레드 그룹화 알고리즘 (화면 핵심 기능):**
* 하나의 코드 라인(`parent_github_id`가 같거나 동일 파일/라인)에 여러 리뷰어가 대댓글로 의견을 남긴 경우, 백엔드에서 `GROUP BY` 또는 데이터 가공을 통해 한 장의 인사이트 카드로 묶어 프론트엔드에 `List<Reviewer>` 구조로 반환해야 합니다.


2. **증분 수집(Incremental Collection)을 통한 Rate Limit 방어:**
* 배치가 작동할 때 DB에 저장된 가장 최근의 `created_at`을 기준으로 GitHub API의 `since` 파라미터를 사용해 변경/추가된 데이터만 긁어오도록 설계합니다.


3. **텍스트 하이라이팅 및 마크다운 파싱:**
* 프론트엔드(`React` 등)에서 검색 키워드와 일치하는 단어에 특정 CSS 클래스(예: `bg-yellow-100`)를 입히고, 코멘트 내의 마크다운 서식 및 코드 스니펫이 깨지지 않도록 마크다운 파서 뷰어를 정교하게 세팅합니다.

