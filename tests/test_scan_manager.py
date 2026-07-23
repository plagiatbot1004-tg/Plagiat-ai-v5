import json

from sqlalchemy import select

from app.database import create_engine_and_session, create_tables
from app.models import ExternalScan, Submission, User
from app.services.quetext import (
    ExternalAIAssessment,
    InternetScanResult,
    InternetSource,
)
from app.services.scan_manager import QuetextScanManager


class FakeBot:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str]] = []
        self.documents: list[tuple[int, object]] = []

    async def send_message(self, chat_id: int, text: str, **kwargs: object) -> None:
        self.messages.append((chat_id, text))

    async def send_document(self, chat_id: int, document: object, **kwargs: object) -> None:
        self.documents.append((chat_id, document))


class FakeQuetextClient:
    def __init__(self) -> None:
        self.plagiarism_ids: list[str] = []
        self.ai_ids: list[str] = []

    async def get_plagiarism_result(self, report_id: str) -> InternetScanResult:
        self.plagiarism_ids.append(report_id)
        return InternetScanResult(
            similarity=18.5,
            originality=81.5,
            sources=[
                InternetSource(
                    title="Example source",
                    url="https://example.com/article",
                    matched_words=27,
                    similarity=88,
                )
            ],
            status="completed",
        )

    async def get_ai_result(
        self,
        report_id: str,
        *,
        language: str,
    ) -> ExternalAIAssessment:
        self.ai_ids.append(report_id)
        return ExternalAIAssessment(
            score=64.0,
            verdict="AIga o‘xshash matn ulushi yuqori",
            reasons=["Ehtimoliy AI qismi (92%): “Example sentence.”"],
            language=language,
            confidence=92,
        )


async def test_manager_completes_persists_and_notifies(tmp_path) -> None:
    engine, session_maker = create_engine_and_session(
        f"sqlite+aiosqlite:///{tmp_path / 'manager.db'}"
    )
    await create_tables(engine)
    async with session_maker() as session:
        user = User(telegram_id=998877, first_name="Ali")
        session.add(user)
        await session.flush()
        submission = Submission(
            user_id=user.id,
            telegram_file_id="telegram-file",
            filename="paper.docx",
            content_hash="0" * 64,
            raw_text="This is a professional test document. " * 40,
            normalized_text="this is a professional test document " * 40,
            word_count=240,
            originality_score=0,
            plagiarism_score=0,
        )
        session.add(submission)
        await session.flush()
        session.add(
            ExternalScan(
                submission_id=submission.id,
                provider="quetext",
                scan_id="scan123",
                status="pending",
                ai_verdict="Quetext AI tekshiruvi kutilmoqda",
                ai_reasons_json="[]",
                authorship_questions_json=json.dumps(
                    ["Asosiy xulosani tushuntiring."],
                    ensure_ascii=False,
                ),
                provider_payload_json=json.dumps(
                    {
                        "detected_language": "en",
                        "ai_provider": "Quetext AI Detector",
                        "ai_requested": True,
                        "plagiarism_report_id": "plag-1",
                        "ai_report_id": "ai-1",
                    }
                ),
            )
        )
        await session.commit()

    bot = FakeBot()
    client = FakeQuetextClient()
    manager = QuetextScanManager(
        bot=bot,  # type: ignore[arg-type]
        client=client,  # type: ignore[arg-type]
        session_maker=session_maker,
    )
    await manager._process("scan123")

    async with session_maker() as session:
        external = await session.scalar(
            select(ExternalScan).where(ExternalScan.scan_id == "scan123")
        )
        assert external is not None
        assert external.status == "completed"
        assert external.internet_similarity == 18.5
        assert external.internet_originality == 81.5
        assert external.ai_style_score == 64
        assert external.notified_at is not None

    assert client.plagiarism_ids == ["plag-1"]
    assert client.ai_ids == ["ai-1"]
    assert len(bot.documents) == 1
    assert len(bot.messages) == 1
    assert "Quetext DeepSearch" in bot.messages[0][1]
    await engine.dispose()
