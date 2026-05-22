from dataclasses import dataclass
from typing import Any

import psycopg

from comment_data.db import fetch_documents_needing_embeddings, upsert_conversation_embedding
from comment_data.openai_client import OpenAIClient


@dataclass(frozen=True)
class EmbeddingResult:
    embedded: int


def embed_conversation_documents(
    connection: psycopg.Connection[Any],
    client: OpenAIClient,
    *,
    model: str,
    batch_size: int,
    limit: int,
) -> EmbeddingResult:
    embedded = 0
    remaining = limit

    while remaining > 0:
        current_batch_size = min(batch_size, remaining)
        documents = fetch_documents_needing_embeddings(
            connection,
            model=model,
            limit=current_batch_size,
        )
        if not documents:
            break

        texts = [document["embedding_text"] for document in documents]
        embeddings = client.create_embeddings(model=model, inputs=texts)
        for document, embedding in zip(documents, embeddings, strict=True):
            upsert_conversation_embedding(
                connection,
                conversation_document_id=int(document["id"]),
                model=model,
                embedding=embedding,
                source_text=document["embedding_text"],
            )
            embedded += 1

        connection.commit()
        remaining -= len(documents)

    return EmbeddingResult(embedded=embedded)
