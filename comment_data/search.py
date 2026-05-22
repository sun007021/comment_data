import math
import re
from dataclasses import dataclass
from typing import Any

import psycopg

from comment_data.db import fetch_search_documents
from comment_data.openai_client import OpenAIClient


@dataclass(frozen=True)
class SearchOptions:
    query: str
    track: str | None
    mission: str | None
    repository: str | None
    limit: int
    summarize: bool
    embedding_model: str
    summary_model: str


def search_conversations(
    connection: psycopg.Connection[Any],
    client: OpenAIClient,
    options: SearchOptions,
) -> dict[str, Any]:
    query_embedding = client.create_embeddings(model=options.embedding_model, inputs=[options.query])[0]
    candidates = fetch_search_documents(
        connection,
        embedding_model=options.embedding_model,
        query=options.query,
        track=options.track,
        mission=options.mission,
        repository=options.repository,
        max_candidates=max(options.limit * 30, 100),
    )

    scored = [score_document(candidate, query_embedding) for candidate in candidates]
    scored.sort(key=lambda item: item["score"], reverse=True)
    clusters = cluster_documents(scored[: max(options.limit * 8, 40)])

    items = []
    for index, cluster in enumerate(clusters[: options.limit], start=1):
        representative = cluster[0]
        summary = fallback_summary(options.query, representative, cluster)
        if options.summarize:
            summary = client.summarize_cluster(
                model=options.summary_model,
                query=options.query,
                documents=cluster[:3],
            )

        items.append(
            {
                "groupId": f"cluster-{index}",
                "groupTitle": summary["title"],
                "representativeAnswer": summary["answer"],
                "count": len(cluster),
                "score": representative["score"],
                "documents": [to_document_response(document) for document in cluster[:5]],
            }
        )

    return {"items": items}


def score_document(document: dict[str, Any], query_embedding: list[float]) -> dict[str, Any]:
    embedding = [float(value) for value in document["embedding"]]
    vector_score = cosine_similarity(query_embedding, embedding)
    text_rank = float(document["text_rank"] or 0.0)
    text_score = min(text_rank, 1.0)
    score = vector_score * 0.8 + text_score * 0.2

    enriched = dict(document)
    enriched["vector_score"] = vector_score
    enriched["score"] = score
    enriched["repository"] = f"{document['repository_owner']}/{document['repository_name']}"
    return enriched


def cluster_documents(documents: list[dict[str, Any]], threshold: float = 0.84) -> list[list[dict[str, Any]]]:
    clusters: list[list[dict[str, Any]]] = []
    centroids: list[list[float]] = []

    for document in documents:
        embedding = [float(value) for value in document["embedding"]]
        best_index = None
        best_score = -1.0
        for index, centroid in enumerate(centroids):
            similarity = cosine_similarity(embedding, centroid)
            if similarity > best_score:
                best_index = index
                best_score = similarity

        if best_index is not None and best_score >= threshold:
            clusters[best_index].append(document)
            centroids[best_index] = average_embedding(centroids[best_index], embedding, len(clusters[best_index]))
        else:
            clusters.append([document])
            centroids.append(embedding)

    clusters.sort(key=lambda cluster: cluster[0]["score"], reverse=True)
    return clusters


def fallback_summary(query: str, representative: dict[str, Any], cluster: list[dict[str, Any]]) -> dict[str, str]:
    snippet = make_snippet(representative["document_text"])
    title = extract_title(query, representative)
    answer = snippet
    if len(cluster) > 1:
        answer = f"비슷한 리뷰 대화 {len(cluster)}건이 있습니다. 대표 내용: {snippet}"
    return {"title": title, "answer": answer}


def extract_title(query: str, document: dict[str, Any]) -> str:
    file_path = document.get("file_path")
    if file_path:
        return file_path.split("/")[-1]
    words = re.findall(r"[가-힣A-Za-z0-9_]+", query)
    return " ".join(words[:4]) or "관련 리뷰"


def make_snippet(text: str, limit: int = 1000) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit].rstrip() + "..."


def to_document_response(document: dict[str, Any]) -> dict[str, Any]:
    metadata = document.get("metadata") or {}
    return {
        "id": document["id"],
        "kind": document["document_kind"],
        "track": document["track"],
        "mission": document["mission_name"],
        "repository": document["repository"],
        "prNumber": document["pr_number"],
        "prTitle": document["pr_title"],
        "githubUrl": document["github_url"],
        "filePath": document["file_path"],
        "lineNumber": document["line_number"],
        "reviewers": metadata.get("reviewers", []),
        "snippet": make_snippet(document["document_text"]),
        "score": document["score"],
    }


def cosine_similarity(left: list[float], right: list[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def average_embedding(current: list[float], new: list[float], count: int) -> list[float]:
    previous_count = count - 1
    return [((value * previous_count) + new[index]) / count for index, value in enumerate(current)]
