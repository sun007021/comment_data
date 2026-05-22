import math
import re
from dataclasses import dataclass
from typing import Any

import psycopg

from comment_data.db import fetch_review_comments_by_github_ids, fetch_search_documents
from comment_data.openai_client import OpenAIClient
from comment_data.reviewers import is_reviewer, reviewer_nickname


@dataclass(frozen=True)
class SearchOptions:
    query: str
    track: str | None
    mission: str | None
    repository: str | None
    limit: int
    summarize: bool
    embedding_model: str
    classification_model: str
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
    scored = scored[: max(options.limit * 30, 100)]
    comment_map = fetch_comment_map(connection, scored)
    answer_items = extract_answer_items(scored, comment_map)
    answer_items = embed_answer_items(client, options.embedding_model, query_embedding, answer_items)
    answer_items.sort(key=lambda item: item["score"], reverse=True)
    answer_items = answer_items[: options.limit]
    clusters = classify_answer_items(client, options.classification_model, options.query, answer_items)

    items = []
    for cluster in clusters:
        representative = cluster[0]
        fallback = fallback_summary(options.query, representative, cluster)
        summary = {
            "title": representative.get("classification_title") or fallback["title"],
            "answer": representative.get("classification_summary") or fallback["answer"],
        }
        if options.summarize:
            summary = client.summarize_cluster(
                model=options.summary_model,
                query=options.query,
                documents=cluster[:3],
            )

        items.append(
            {
                "groupId": f"cluster-{len(items) + 1}",
                "groupTitle": summary["title"],
                "representativeAnswer": summary["answer"],
                "count": len(cluster),
                "score": representative["score"],
                "documents": documents_for_answer_cluster(cluster),
                "reviewerSections": reviewer_sections_for_answer_cluster(cluster),
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


def classify_answer_items(
    client: OpenAIClient,
    classification_model: str,
    query: str,
    answer_items: list[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    items_by_id = {item["answer_id"]: item for item in answer_items}
    classifications = client.classify_answer_groups(model=classification_model, query=query, answers=answer_items)

    clusters: list[list[dict[str, Any]]] = []
    assigned_ids: set[str] = set()
    for index, classification in enumerate(classifications, start=1):
        cluster = []
        for answer_id in classification["answerIds"]:
            if answer_id in assigned_ids:
                continue
            item = items_by_id.get(answer_id)
            if item is None:
                continue
            assigned_ids.add(answer_id)
            enriched = dict(item)
            enriched["classification_group_key"] = classification["groupKey"] or f"group-{index}"
            enriched["classification_title"] = classification["title"]
            enriched["classification_summary"] = classification["summary"]
            cluster.append(enriched)
        if cluster:
            clusters.append(cluster)

    for item in answer_items:
        if item["answer_id"] in assigned_ids:
            continue
        enriched = dict(item)
        fallback = fallback_summary(query, item, [item])
        enriched["classification_group_key"] = f"ungrouped-{len(clusters) + 1}"
        enriched["classification_title"] = fallback["title"]
        enriched["classification_summary"] = fallback["answer"]
        clusters.append([enriched])

    clusters.sort(key=lambda cluster: cluster[0]["score"], reverse=True)
    return clusters


def fallback_summary(query: str, representative: dict[str, Any], cluster: list[dict[str, Any]]) -> dict[str, str]:
    snippet = make_snippet(representative_answer_text(representative))
    title = extract_title(query, representative)
    answer = snippet
    if len(cluster) > 1:
        answer = f"비슷한 리뷰어 답변 {len(cluster)}건이 있습니다. 대표 내용: {snippet}"
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


def fetch_comment_map(
    connection: psycopg.Connection[Any],
    documents: list[dict[str, Any]],
) -> dict[int, dict[str, Any]]:
    comment_ids = sorted(
        {
            int(comment_id)
            for document in documents
            for comment_id in document.get("comment_github_ids", [])
            if comment_id is not None
        }
    )
    comments = fetch_review_comments_by_github_ids(connection, comment_github_ids=comment_ids)
    return {int(comment["comment_github_id"]): comment for comment in comments}


def extract_answer_items(
    documents: list[dict[str, Any]],
    comment_map: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    items = []
    for document in documents:
        blocks = split_comment_blocks(document["document_text"])
        comment_ids = [int(comment_id) for comment_id in document.get("comment_github_ids", [])]
        for index, block in enumerate(blocks):
            parsed = parse_comment_block(block)
            if parsed is None or not is_reviewer(parsed["reviewer"]):
                continue

            comment_id = comment_ids[index] if index < len(comment_ids) else None
            comment = comment_map.get(comment_id) if comment_id is not None else None
            content = str((comment or {}).get("content") or parsed["content"]).strip()
            if not content:
                continue

            reviewer = str((comment or {}).get("reviewer_id") or parsed["reviewer"])
            if not is_reviewer(reviewer):
                continue

            items.append(
                {
                    **document,
                    "answer_id": f"{document['id']}:{comment_id or index}",
                    "comment_github_id": comment_id,
                    "reviewer": reviewer,
                    "reviewer_nickname": reviewer_nickname(reviewer),
                    "reviewer_answer_text": content,
                    "comment_github_url": (comment or {}).get("github_url") or document["github_url"],
                    "comment_file_path": (comment or {}).get("file_path") or document["file_path"],
                    "comment_line_number": (comment or {}).get("line_number") or document["line_number"],
                    "comment_created_at": (comment or {}).get("created_at"),
                    "comment_updated_at": (comment or {}).get("updated_at"),
                    "document_github_url": document["github_url"],
                    "source_document_score": document["score"],
                    "source_vector_score": document["vector_score"],
                }
            )
    return items


def embed_answer_items(
    client: OpenAIClient,
    embedding_model: str,
    query_embedding: list[float],
    answer_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not answer_items:
        return []

    embeddings = client.create_embeddings(
        model=embedding_model,
        inputs=[item["reviewer_answer_text"] for item in answer_items],
    )
    enriched_items = []
    for item, embedding in zip(answer_items, embeddings, strict=True):
        vector_score = cosine_similarity(query_embedding, embedding)
        enriched = dict(item)
        enriched["answer_embedding"] = embedding
        enriched["answer_vector_score"] = vector_score
        enriched["score"] = vector_score * 0.8 + float(item["source_document_score"]) * 0.2
        enriched_items.append(enriched)
    return enriched_items


def representative_answer_text(document: dict[str, Any]) -> str:
    return str(document.get("reviewer_answer_text") or document["document_text"])


def extract_reviewer_answer_text(document_text: str) -> str:
    blocks = []
    for block in split_comment_blocks(document_text):
        parsed = parse_comment_block(block)
        if parsed is None or not is_reviewer(parsed["reviewer"]):
            continue
        nickname = reviewer_nickname(parsed["reviewer"])
        reviewer_label = parsed["reviewer"]
        if nickname:
            reviewer_label = f"{reviewer_label} ({nickname})"
        blocks.append(f"reviewer: {reviewer_label}\n\n{parsed['content']}")
    return "\n\n---\n\n".join(blocks)


def split_comment_blocks(document_text: str) -> list[str]:
    return [block.strip() for block in re.split(r"\n\s*---\s*\n", document_text) if block.strip()]


def parse_comment_block(block: str) -> dict[str, str] | None:
    reviewer_match = re.search(r"^reviewer:\s*(?P<reviewer>\S+)\s*$", block, flags=re.MULTILINE)
    if not reviewer_match:
        return None

    content_match = re.search(r"\n\s*\n(?P<content>.*)\Z", block, flags=re.DOTALL)
    if not content_match:
        return None

    content = content_match.group("content").strip()
    if not content:
        return None

    return {"reviewer": reviewer_match.group("reviewer"), "content": content}


def documents_for_answer_cluster(cluster: list[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    documents = []
    by_document_id: dict[int, list[dict[str, Any]]] = {}
    for item in cluster:
        document_id = int(item["id"])
        by_document_id.setdefault(document_id, []).append(item)

    for document_items in by_document_id.values():
        representative = dict(document_items[0])
        representative["cluster_reviewers"] = sorted({item["reviewer"] for item in document_items})
        representative["reviewer_answer_text"] = "\n\n---\n\n".join(
            item["reviewer_answer_text"] for item in document_items
        )
        documents.append(to_document_response(representative))
        if len(documents) >= limit:
            break
    return documents


def reviewer_sections_for_answer_cluster(cluster: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    first_seen_order: list[str] = []

    for item in cluster:
        reviewer = item["reviewer"]
        if reviewer not in grouped:
            grouped[reviewer] = []
            first_seen_order.append(reviewer)
        grouped[reviewer].append(item)

    sections = []
    for reviewer in first_seen_order:
        comments = sorted(grouped[reviewer], key=answer_item_sort_key)
        sections.append(
            {
                "reviewer": reviewer,
                "nickname": reviewer_nickname(reviewer),
                "commentCount": len(comments),
                "comments": [to_reviewer_comment_response(comment) for comment in comments],
            }
        )
    return sections


def answer_item_sort_key(item: dict[str, Any]) -> tuple[float, str, int]:
    created_at = item.get("comment_created_at")
    comment_github_id = item.get("comment_github_id") or 0
    created_at_key = created_at.isoformat() if created_at else ""
    return (-float(item["score"]), created_at_key, int(comment_github_id))


def to_reviewer_comment_response(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "commentGithubId": item["comment_github_id"],
        "conversationId": item["id"],
        "content": item["reviewer_answer_text"],
        "snippet": make_snippet(item["reviewer_answer_text"]),
        "githubUrl": item["comment_github_url"],
        "documentGithubUrl": item["document_github_url"],
        "repository": item["repository"],
        "prNumber": item["pr_number"],
        "prTitle": item["pr_title"],
        "filePath": item["comment_file_path"],
        "lineNumber": item["comment_line_number"],
        "createdAt": item["comment_created_at"],
        "score": item["score"],
    }


def to_document_response(document: dict[str, Any]) -> dict[str, Any]:
    metadata = document.get("metadata") or {}
    reviewers = document.get("cluster_reviewers")
    if reviewers is None:
        reviewers = [reviewer for reviewer in metadata.get("reviewers", []) if is_reviewer(reviewer)]
    if document.get("reviewer") and document["reviewer"] not in reviewers:
        reviewers = [document["reviewer"], *reviewers]
    return {
        "id": document["id"],
        "kind": document["document_kind"],
        "track": document["track"],
        "mission": document["mission_name"],
        "repository": document["repository"],
        "prNumber": document["pr_number"],
        "prTitle": document["pr_title"],
        "githubUrl": document.get("document_github_url") or document["github_url"],
        "filePath": document.get("comment_file_path") or document["file_path"],
        "lineNumber": document.get("comment_line_number") or document["line_number"],
        "reviewers": reviewers,
        "snippet": make_snippet(representative_answer_text(document)),
        "score": document["score"],
    }


def cosine_similarity(left: list[float], right: list[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)
