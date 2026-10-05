import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.models.knowledge import KnowledgeChunk, KnowledgeDocument
from app.schemas.knowledge import KnowledgeDocumentCreate, KnowledgeDocumentResponse
from app.security import CurrentUser
from app.services.knowledge import chunk_text, embed_texts

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.get("", response_model=list[KnowledgeDocumentResponse])
async def list_knowledge_documents(
    current_user: CurrentUser, db: Annotated[AsyncSession, Depends(get_db)]
) -> list[KnowledgeDocumentResponse]:
    result = await db.execute(
        select(KnowledgeDocument)
        .where(KnowledgeDocument.org_id == current_user.org_id)
        .options(selectinload(KnowledgeDocument.chunks))
        .order_by(KnowledgeDocument.created_at.desc())
    )
    return [
        KnowledgeDocumentResponse(
            id=doc.id, name=doc.name, chunk_count=len(doc.chunks), created_at=doc.created_at
        )
        for doc in result.scalars().all()
    ]


@router.post("", response_model=KnowledgeDocumentResponse, status_code=status.HTTP_201_CREATED)
async def create_knowledge_document(
    payload: KnowledgeDocumentCreate,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> KnowledgeDocumentResponse:
    chunks = chunk_text(payload.content)
    if not chunks:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Document is empty")

    embeddings = await embed_texts(chunks)
    document = KnowledgeDocument(org_id=current_user.org_id, name=payload.name)
    document.chunks = [
        KnowledgeChunk(org_id=current_user.org_id, text=text, embedding=embedding)
        for text, embedding in zip(chunks, embeddings, strict=True)
    ]
    db.add(document)
    await db.commit()
    await db.refresh(document)

    return KnowledgeDocumentResponse(
        id=document.id, name=document.name, chunk_count=len(chunks), created_at=document.created_at
    )


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_knowledge_document(
    document_id: uuid.UUID,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    result = await db.execute(
        select(KnowledgeDocument).where(
            KnowledgeDocument.id == document_id, KnowledgeDocument.org_id == current_user.org_id
        )
    )
    document = result.scalar_one_or_none()
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    await db.delete(document)
    await db.commit()
