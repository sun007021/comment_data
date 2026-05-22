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
            text = str(document.get("reviewer_answer_text") or document["document_text"])[:2500]
            snippets.append(
                f"문서 {index}\n"
                f"종류: {document['document_kind']}\n"
                f"PR: {document['repository']}/pull/{document['pr_number']}\n"
                f"내용:\n{text}"
            )

        prompt = (
            "사용자 질문과 관련된 코드리뷰 대화 묶음을 보고, 검색 결과 카드에 보여줄 "
            "짧은 제목과 2-3문장 답변을 JSON으로 작성해줘.\n"
            "원문에 없는 내용을 추측하지 말고, 여러 문서의 공통된 의도만 요약해.\n\n"
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
