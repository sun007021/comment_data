from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psycopg

from comment_data.config import MissionConfig
from comment_data.conversation import rebuild_conversation_documents_for_pr
from comment_data.db import (
    get_latest_comment_created_at,
    upsert_mission,
    upsert_pull_request,
    upsert_review_comment,
)
from comment_data.github_client import GitHubClient


@dataclass(frozen=True)
class CollectionResult:
    mission: MissionConfig
    pull_requests: int
    comments: int
    conversation_documents: int
    since: datetime | None


def collect_mission(
    connection: psycopg.Connection[Any],
    client: GitHubClient,
    mission: MissionConfig,
    *,
    full_refresh: bool,
    pr_limit: int,
) -> CollectionResult:
    mission_id = upsert_mission(
        connection,
        track=mission.track,
        name=mission.name,
        owner=mission.owner,
        repository_name=mission.repository_name,
    )

    prs = client.list_pull_requests(mission.owner, mission.repository_name, limit=pr_limit)
    pr_ids_by_number: dict[int, int] = {}
    for pr in prs:
        pr_number = int(pr["number"])
        pr_ids_by_number[pr_number] = upsert_pull_request(
            connection,
            mission_id=mission_id,
            pr=pr,
        )

    since = None if full_refresh else get_latest_comment_created_at(connection, mission_id=mission_id)

    saved_comments = 0
    saved_conversation_documents = 0
    for pr_number, pr_id in pr_ids_by_number.items():
        comments = client.list_pull_request_review_comments(
            mission.owner,
            mission.repository_name,
            pull_number=pr_number,
        )
        for comment in comments:
            if since is not None and not is_newer_than_latest(comment, since):
                continue
            upsert_review_comment(connection, pr_id=pr_id, comment=comment)
            saved_comments += 1
        result = rebuild_conversation_documents_for_pr(connection, mission_id=mission_id, pr_id=pr_id)
        saved_conversation_documents += result.documents

    connection.commit()
    return CollectionResult(
        mission=mission,
        pull_requests=len(prs),
        comments=saved_comments,
        conversation_documents=saved_conversation_documents,
        since=since,
    )


def is_newer_than_latest(comment: dict[str, Any], since: datetime) -> bool:
    value = comment.get("updated_at") or comment.get("created_at")
    if not value:
        return True

    comment_time = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return comment_time > since
