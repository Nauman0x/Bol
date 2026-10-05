import uuid

from sqlalchemy import JSON, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.mixins import TimestampMixin, UUIDPk


class KnowledgeDocument(UUIDPk, TimestampMixin, Base):
    __tablename__ = "knowledge_documents"

    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(Text)

    chunks: Mapped[list["KnowledgeChunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class KnowledgeChunk(UUIDPk, Base):
    __tablename__ = "knowledge_chunks"

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"), index=True
    )
    # Denormalized from the parent document so a search can filter by org
    # without a join — see app/services/knowledge.py:search.
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    text: Mapped[str] = mapped_column(Text)
    # A single dense vector, stored as a plain JSON float array rather than
    # a pgvector column — see app/services/knowledge.py for why (portable
    # across SQLite/Postgres, and brute-force cosine similarity over a few
    # hundred chunks is well under the latency budget this needs).
    embedding: Mapped[list[float]] = mapped_column(JSON)

    document: Mapped["KnowledgeDocument"] = relationship(back_populates="chunks")
