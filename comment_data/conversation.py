from collections import defaultdict
from dataclasses import dataclass
from typing import Any

import psycopg

from comment_data.db import (
    delete_conversation_documents_for_pr,
    fetch_review_comments_for_pr,
    insert_conversation_document,
)


@dataclass(frozen=True)
class ConversationBuildResult:
    documents: int


def rebuild_conversation_documents_for_pr(
    connection: psycopg.Connection[Any],
    *,
    mission_id: int,
    pr_id: int,
) -> ConversationBuildResult:
    comments = fetch_review_comments_for_pr(connection, pr_id=pr_id)
    delete_conversation_documents_for_pr(connection, pr_id=pr_id)

    by_parent: dict[int, list[dict[str, Any]]] = defaultdict(list)
    roots: list[dict[str, Any]] = []
    comments_by_github_id: dict[int, dict[str, Any]] = {}

    for comment in comments:
        comment_github_id = int(comment["comment_github_id"])
        comments_by_github_id[comment_github_id] = comment
        parent_github_id = comment["parent_github_id"]
        if parent_github_id is None:
            roots.append(comment)
        else:
            by_parent[int(parent_github_id)].append(comment)

    saved = 0
    handled_child_ids: set[int] = set()
    for root in roots:
        root_id = int(root["comment_github_id"])
        replies = sorted(by_parent.get(root_id, []), key=comment_sort_key)
        handled_child_ids.update(int(reply["comment_github_id"]) for reply in replies)
        conversation = [root, *replies]
        document_kind = "THREAD" if replies else "STANDALONE"
        insert_document(connection, mission_id, pr_id, root, conversation, document_kind)
        saved += 1

    # If the parent comment was not collected for any reason, keep the reply searchable as its own document.
    for comment in comments:
        comment_id = int(comment["comment_github_id"])
        parent_id = comment["parent_github_id"]
        if parent_id is None or comment_id in handled_child_ids or int(parent_id) in comments_by_github_id:
            continue
        insert_document(connection, mission_id, pr_id, comment, [comment], "ORPHAN_REPLY")
        saved += 1

    return ConversationBuildResult(documents=saved)


def insert_document(
    connection: psycopg.Connection[Any],
    mission_id: int,
    pr_id: int,
    root: dict[str, Any],
    conversation: list[dict[str, Any]],
    document_kind: str,
) -> None:
    insert_conversation_document(
        connection,
        mission_id=mission_id,
        pr_id=pr_id,
        root_comment_github_id=int(root["comment_github_id"]),
        document_kind=document_kind,
        document_text=build_document_text(conversation),
        github_url=root["github_url"],
        file_path=root["file_path"],
        line_number=root["line_number"],
        comment_github_ids=[int(comment["comment_github_id"]) for comment in conversation],
        metadata={
            "reviewers": sorted({comment["reviewer_id"] for comment in conversation if comment["reviewer_id"]}),
            "comment_count": len(conversation),
        },
    )


def build_document_text(conversation: list[dict[str, Any]]) -> str:
    blocks: list[str] = []
    for index, comment in enumerate(conversation):
        label = "CONTEXT" if index == 0 else "REPLY"
        reviewer = comment["reviewer_id"]
        created_at = comment["created_at"].isoformat() if comment["created_at"] else ""
        content = comment["content"].strip()
        blocks.append(f"[{label}]\nreviewer: {reviewer}\ncreated_at: {created_at}\n\n{content}")
    return "\n\n---\n\n".join(blocks)


def comment_sort_key(comment: dict[str, Any]) -> tuple[Any, int]:
    return comment["created_at"], int(comment["comment_github_id"])
