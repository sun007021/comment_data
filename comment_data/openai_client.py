import json
from typing import Any

import requests


class OpenAIClient:
    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required")
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }
        )

    def create_embeddings(self, *, model: str, inputs: list[str]) -> list[list[float]]:
        if not inputs:
            return []

        response = self._session.post(
            "https://api.openai.com/v1/embeddings",
            json={"model": model, "input": inputs},
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()
        data = sorted(payload["data"], key=lambda item: item["index"])
        return [item["embedding"] for item in data]

    def summarize_cluster(
        self,
        *,
        model: str,
        query: str,
        documents: list[dict[str, Any]],
    ) -> dict[str, str]:
        snippets = []
        for index, document in enumerate(documents, start=1):
            text = str(document.get("reviewer_answer_text") or document.get("content") or document["document_text"])[
                :2500
            ]
            snippets.append(
                f"문서 {index}\n"
                f"종류: {document['document_kind']}\n"
                f"PR: {document['repository']}/pull/{document['pr_number']}\n"
                f"내용:\n{text}"
            )

        prompt = (
            "사용자 질문과 관련된 코드리뷰 답변 묶음을 보고, 검색 결과 카드에 보여줄 "
            "짧은 제목과 2-3문장 답변을 JSON으로 작성해줘.\n"
            "원문에 없는 내용을 추측하지 말고, 여러 리뷰어 답변의 공통된 방향성만 요약해.\n\n"
            f"사용자 질문: {query}\n\n"
            + "\n\n---\n\n".join(snippets)
            + '\n\n출력 JSON 형식: {"title": "...", "answer": "..."}'
        )

        response = self._session.post(
            "https://api.openai.com/v1/responses",
            json={
                "model": model,
                "input": prompt,
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": "cluster_summary",
                        "strict": True,
                        "schema": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "title": {"type": "string"},
                                "answer": {"type": "string"},
                            },
                            "required": ["title", "answer"],
                        },
                    }
                },
            },
            timeout=90,
        )
        response.raise_for_status()
        output_text = extract_response_text(response.json())
        return parse_summary_json(output_text)

    def classify_answer_groups(
        self,
        *,
        model: str,
        query: str,
        answers: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not answers:
            return []

        groups = self._classify_answer_groups(model=model, query=query, answers=answers, retry_over_split=False)
        if is_over_split(groups, len(answers)):
            groups = self._classify_answer_groups(model=model, query=query, answers=answers, retry_over_split=True)
        return groups

    def _classify_answer_groups(
        self,
        *,
        model: str,
        query: str,
        answers: list[dict[str, Any]],
        retry_over_split: bool,
    ) -> list[dict[str, Any]]:
        answer_blocks = []
        for index, answer in enumerate(answers, start=1):
            text = str(answer["reviewer_answer_text"])[:1800]
            answer_blocks.append(
                f"답변 {index}\n"
                f"answer_id: {answer['answer_id']}\n"
                f"reviewer: {answer['reviewer']}\n"
                f"PR: {answer['repository']}/pull/{answer['pr_number']}\n"
                f"내용:\n{text}"
            )

        grouping_instruction = (
            "답변이 20-30개라면 보통 4-8개 정도의 그룹을 목표로 해. 단, 억지로 무관한 답변을 합치지는 마.\n"
        )
        if retry_over_split:
            grouping_instruction = (
                "이전 분류가 너무 잘게 나뉘었어. 이번에는 반드시 병합 중심으로 다시 분류해.\n"
                "답변이 20-30개라면 4-8개 그룹을 강하게 목표로 하고, singleton 그룹은 최대한 만들지 마.\n"
                "비슷한 에러 응답 기준, 예외 타입/핸들러 설계, Validation 예외 전달, 계층 책임 분리처럼 넓은 학습 포인트로 병합해.\n"
                "완전히 무관한 답변만 별도 그룹으로 남겨.\n"
            )

        prompt = (
            "사용자 질문과 관련된 코드리뷰 답변들을 넓은 학습 포인트/피드백 방향성 기준으로 그룹화해줘.\n"
            "목표는 세부 구현 차이를 나누는 것이 아니라, 사용자가 같은 종류의 리뷰 인사이트를 한 번에 볼 수 있게 묶는 것이야.\n"
            "코드 예시, 설명 길이, 근거 표현, 질문형/제안형 말투, 언급된 클래스명이 달라도 최종적으로 배우는 포인트가 같으면 반드시 같은 그룹으로 묶어.\n"
            "예를 들어 ErrorCode, 에러 메시지, 응답 바디 형식, HTTP 상태 코드 기준을 다룬 답변은 모두 '에러 응답 기준과 일관성'처럼 한 그룹으로 묶을 수 있어.\n"
            "예를 들어 Validation 애노테이션이 어떻게 예외로 전달되는지 묻는 답변들은 파일이나 DTO가 달라도 같은 그룹으로 묶어.\n"
            "예를 들어 커스텀 예외, 예외 계층, ExceptionHandler 처리 기준을 다룬 답변은 세부 제안이 달라도 '예외 타입과 핸들러 설계'처럼 넓게 묶어.\n"
            "서로 완전히 다른 학습 포인트일 때만 그룹을 나눠. 사소한 근거 차이나 예시 차이만으로는 나누지 마.\n"
            "singleton 그룹은 정말로 함께 묶을 관련 답변이 없을 때만 만들어. 가능한 한 singleton을 줄여.\n"
            f"{grouping_instruction}"
            "입력된 answer_id만 사용하고, 모든 answer_id를 정확히 한 번씩 포함해.\n"
            "원문에 없는 내용을 추측하지 말고 title과 summary는 그룹에 포함된 답변들의 공통 방향성만 요약해.\n\n"
            f"사용자 질문: {query}\n\n"
            + "\n\n---\n\n".join(answer_blocks)
            + '\n\n출력 JSON 형식: {"groups": [{"groupKey": "...", "title": "...", "summary": "...", '
            '"answerIds": ["..."]}]}'
        )

        response = self._session.post(
            "https://api.openai.com/v1/responses",
            json={
                "model": model,
                "input": prompt,
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": "answer_group_classification",
                        "strict": True,
                        "schema": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "groups": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "additionalProperties": False,
                                        "properties": {
                                            "groupKey": {"type": "string"},
                                            "title": {"type": "string"},
                                            "summary": {"type": "string"},
                                            "answerIds": {
                                                "type": "array",
                                                "items": {"type": "string"},
                                            },
                                        },
                                        "required": ["groupKey", "title", "summary", "answerIds"],
                                    },
                                }
                            },
                            "required": ["groups"],
                        },
                    }
                },
            },
            timeout=90,
        )
        response.raise_for_status()
        output_text = extract_response_text(response.json())
        return parse_classification_json(output_text)


def extract_response_text(payload: dict[str, Any]) -> str:
    if payload.get("output_text"):
        return str(payload["output_text"])

    parts: list[str] = []
    for item in payload.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"}:
                parts.append(str(content.get("text", "")))
    return "".join(parts)


def parse_summary_json(value: str) -> dict[str, str]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {"title": "관련 리뷰", "answer": value.strip()}

    return {
        "title": str(parsed.get("title", "관련 리뷰")).strip(),
        "answer": str(parsed.get("answer", "")).strip(),
    }


def parse_classification_json(value: str) -> list[dict[str, Any]]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []

    groups = parsed.get("groups", [])
    if not isinstance(groups, list):
        return []

    normalized = []
    for group in groups:
        if not isinstance(group, dict):
            continue
        answer_ids = group.get("answerIds", [])
        if not isinstance(answer_ids, list):
            answer_ids = []
        normalized.append(
            {
                "groupKey": str(group.get("groupKey", "")).strip(),
                "title": str(group.get("title", "관련 리뷰")).strip(),
                "summary": str(group.get("summary", "")).strip(),
                "answerIds": [str(answer_id) for answer_id in answer_ids],
            }
        )
    return normalized


def is_over_split(groups: list[dict[str, Any]], answer_count: int) -> bool:
    if answer_count < 4 or not groups:
        return False

    singleton_count = sum(1 for group in groups if len(group["answerIds"]) == 1)
    group_ratio = len(groups) / answer_count
    singleton_ratio = singleton_count / len(groups)
    return group_ratio >= 0.7 or singleton_ratio >= 0.8
