from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    first_name: Mapped[str] = mapped_column(String(255), default="")
    last_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    submissions: Mapped[list["Submission"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Submission(Base):
    __tablename__ = "submissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    telegram_file_id: Mapped[str] = mapped_column(String(512))
    filename: Mapped[str] = mapped_column(String(512))
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    raw_text: Mapped[str] = mapped_column(Text)
    normalized_text: Mapped[str] = mapped_column(Text)
    word_count: Mapped[int] = mapped_column(Integer)
    # Legacy schema fields. V5 does not calculate internal similarity and always
    # writes zero here so existing Railway PostgreSQL databases remain compatible.
    originality_score: Mapped[float] = mapped_column(Float)
    plagiarism_score: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    user: Mapped[User] = relationship(back_populates="submissions")
    external_scan: Mapped["ExternalScan"] = relationship(
        back_populates="submission", cascade="all, delete-orphan", uselist=False
    )


class ExternalScan(Base):
    __tablename__ = "external_scans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    submission_id: Mapped[int] = mapped_column(
        ForeignKey("submissions.id", ondelete="CASCADE"), unique=True, index=True
    )
    provider: Mapped[str] = mapped_column(String(50), default="quetext")
    scan_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    internet_similarity: Mapped[float | None] = mapped_column(Float, nullable=True)
    internet_originality: Mapped[float | None] = mapped_column(Float, nullable=True)
    internet_sources_json: Mapped[str] = mapped_column(Text, default="[]")
    ai_style_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    ai_verdict: Mapped[str] = mapped_column(String(255), default="")
    ai_reasons_json: Mapped[str] = mapped_column(Text, default="[]")
    authorship_questions_json: Mapped[str] = mapped_column(Text, default="[]")
    provider_payload_json: Mapped[str] = mapped_column(Text, default="{}")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    submission: Mapped[Submission] = relationship(back_populates="external_scan")
