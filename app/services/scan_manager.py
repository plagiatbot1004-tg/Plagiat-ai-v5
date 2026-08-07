import asyncio
import html
import json
import logging
from datetime import UTC, datetime
from typing import Any

from aiogram import Bot
from aiogram.types import BufferedInputFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import ExternalScan, Submission, User
from app.services.ai_risk import AIStyleAssessment, language_name
from app.services.internal_similarity import (
    InternalDocument,
    InternalScanResult,
    MultiSourceResult,
    combine_similarity_results,
    scan_internal_documents,
)
from app.services.quetext import (
    ExternalAIAssessment,
    InternetScanResult,
    InternetSource,
    QuetextClient,
    QuetextError,
)
from app.services.report import build_report
from app.services.unicode_safety import safe_text, sanitize_json_value

logger = logging.getLogger(__name__)


def _json_list(value: str) -> list[Any]:
    try:
        result = json.loads(value)
        return result if isinstance(result, list) else []
    except (TypeError, json.JSONDecodeError):
        return []


def _json_object(value: str) -> dict[str, Any]:
    try:
        result = json.loads(value)
        return result if isinstance(result, dict) else {}
    except (TypeError, json.JSONDecodeError):
        return {}


class QuetextScanManager:
    def __init__(
        self,
        *,
        bot: Bot,
        client: QuetextClient,
        session_maker: async_sessionmaker[AsyncSession],
    ) -> None:
        self.bot = bot
        self.client = client
        self.session_maker = session_maker
        self._tasks: dict[str, asyncio.Task[None]] = {}

    def start(self, scan_id: str) -> None:
        current = self._tasks.get(scan_id)
        if current is not None and not current.done():
            return
        task = asyncio.create_task(self._process(scan_id), name=f"quetext-{scan_id}")
        self._tasks[scan_id] = task
        task.add_done_callback(lambda completed: self._task_done(scan_id, completed))

    def _task_done(self, scan_id: str, task: asyncio.Task[None]) -> None:
        self._tasks.pop(scan_id, None)
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            logger.error(
                "Quetext background task crashed for %s",
                scan_id,
                exc_info=(type(error), error, error.__traceback__),
            )

    async def recover(self) -> None:
        async with self.session_maker() as session:
            rows = (
                await session.scalars(
                    select(ExternalScan.scan_id)
                    .where(ExternalScan.provider == "quetext")
                    .where(ExternalScan.notified_at.is_(None))
                    .where(ExternalScan.status.in_(("pending", "completed", "failed")))
                )
            ).all()
        for scan_id in rows:
            self.start(scan_id)

    async def close(self) -> None:
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()

    async def _process(self, scan_id: str) -> None:
        try:
            external, submission, telegram_id = await self._load_scan(scan_id)
            if external.status == "completed":
                await self._send_completed(external, submission, telegram_id)
                await self._mark_notified(scan_id)
                return
            if external.status == "failed":
                await self._send_failed(
                    telegram_id,
                    submission.filename,
                    external.error_message or "Quetext tekshiruvi muvaffaqiyatsiz tugadi.",
                )
                await self._mark_notified(scan_id)
                return

            provider_data = _json_object(external.provider_payload_json)
            plagiarism_id = str(provider_data.get("plagiarism_report_id") or "")
            ai_id = str(provider_data.get("ai_report_id") or "")
            language = str(provider_data.get("detected_language") or "unknown").casefold()
            if not plagiarism_id:
                raise QuetextError("Quetext plagiat hisobot ID raqami saqlanmagan.")

            plagiarism_task = asyncio.create_task(self.client.get_plagiarism_result(plagiarism_id))
            ai_task = (
                asyncio.create_task(self.client.get_ai_result(ai_id, language=language))
                if ai_id
                else None
            )
            if ai_task is None:
                internet = await plagiarism_task
                external_ai: ExternalAIAssessment | Exception | None = None
            else:
                internet_result, ai_result = await asyncio.gather(
                    plagiarism_task,
                    ai_task,
                    return_exceptions=True,
                )
                if isinstance(internet_result, BaseException):
                    if isinstance(internet_result, Exception):
                        raise internet_result
                    raise QuetextError("Quetext plagiat vazifasi bekor qilindi.")
                internet = internet_result
                external_ai = ai_result

            ai_assessment = self._stored_ai_assessment(external, provider_data)
            if isinstance(external_ai, ExternalAIAssessment):
                ai_assessment = self._convert_external_ai(external_ai)
            elif isinstance(external_ai, Exception):
                provider_data["ai_result_error"] = str(external_ai)[:800]
                ai_assessment = AIStyleAssessment(
                    score=None,
                    verdict="Quetext AI tahlili yakunlanmadi",
                    reasons=[
                        getattr(external_ai, "public_message", str(external_ai)),
                        "Plagiat natijasi AI tahlilining o‘rnini bosmaydi.",
                    ],
                    supported=False,
                    language=language,
                    provider="Quetext AI Detector",
                    confidence="mavjud emas",
                )
            elif provider_data.get("ai_requested") and not ai_id:
                ai_assessment = AIStyleAssessment(
                    score=None,
                    verdict="Quetext AI tahlili boshlanmadi",
                    reasons=[
                        str(
                            provider_data.get("ai_submission_error")
                            or "AI so‘rovi Quetext tomonidan qabul qilinmadi."
                        )
                    ],
                    supported=False,
                    language=language,
                    provider="Quetext AI Detector",
                    confidence="mavjud emas",
                )

            # Internal-document comparison is intentionally disabled in the
            # production result path. Keep the engine available for a future
            # opt-in mode, but make Quetext the sole similarity source shown
            # to users and used for the final score.
            internal = InternalScanResult(
                similarity=0.0,
                matched_words=0,
                total_words=submission.word_count,
                sources=[],
            )
            multi_source = combine_similarity_results(
                current_text=submission.raw_text,
                internet_similarity=float(internet.similarity or 0.0),
                internet_sources=internet.sources,
                internal=internal,
            )

            await self._save_completed(
                scan_id,
                internet,
                ai_assessment,
                provider_data,
                multi_source,
            )
            refreshed, refreshed_submission, refreshed_telegram_id = await self._load_scan(scan_id)
            await self._send_completed(
                refreshed,
                refreshed_submission,
                refreshed_telegram_id,
            )
            await self._mark_notified(scan_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Quetext scan processing failed for %s", scan_id)
            public_message = getattr(exc, "public_message", str(exc))
            await self._save_failed(scan_id, public_message)
            try:
                _, submission, telegram_id = await self._load_scan(scan_id)
                await self._send_failed(telegram_id, submission.filename, public_message)
                await self._mark_notified(scan_id)
            except Exception:
                logger.exception("Could not notify user about failed Quetext scan %s", scan_id)

    async def _load_scan(
        self,
        scan_id: str,
    ) -> tuple[ExternalScan, Submission, int]:
        async with self.session_maker() as session:
            row = (
                await session.execute(
                    select(ExternalScan, Submission, User.telegram_id)
                    .join(Submission, Submission.id == ExternalScan.submission_id)
                    .join(User, User.id == Submission.user_id)
                    .where(ExternalScan.scan_id == scan_id)
                )
            ).one()
            return row

    async def _run_internal_scan(self, submission: Submission) -> InternalScanResult:
        """Compare the current document with every earlier PlagAI submission."""
        async with self.session_maker() as session:
            rows = (
                await session.execute(
                    select(
                        Submission.id,
                        Submission.user_id,
                        Submission.filename,
                        Submission.raw_text,
                    )
                    .where(Submission.id < submission.id)
                    .order_by(Submission.id.asc())
                )
            ).all()
        candidates = [
            InternalDocument(
                document_id=row.id,
                owner_user_id=row.user_id,
                filename=safe_text(row.filename),
                text=safe_text(row.raw_text),
            )
            for row in rows
            if row.raw_text
        ]
        return await asyncio.to_thread(
            scan_internal_documents,
            current_document_id=submission.id,
            current_user_id=submission.user_id,
            current_text=safe_text(submission.raw_text),
            candidates=candidates,
        )

    def _stored_ai_assessment(
        self,
        external: ExternalScan,
        provider_data: dict[str, Any],
    ) -> AIStyleAssessment:
        language = str(provider_data.get("detected_language") or "unknown").casefold()
        return AIStyleAssessment(
            score=external.ai_style_score,
            verdict=external.ai_verdict,
            reasons=[str(value) for value in _json_list(external.ai_reasons_json)],
            supported=external.ai_style_score is not None,
            language=language,
            provider=str(provider_data.get("ai_provider") or "mavjud emas"),
            confidence=str(provider_data.get("ai_confidence") or "past"),
        )

    @staticmethod
    def _convert_external_ai(result: ExternalAIAssessment) -> AIStyleAssessment:
        confidence = (
            "mavjud emas"
            if result.confidence is None
            else f"{result.confidence:.2f}% eng yuqori gap ehtimoli"
        )
        return AIStyleAssessment(
            score=result.score,
            verdict=result.verdict,
            reasons=result.reasons,
            supported=result.score is not None,
            language=result.language,
            provider="Quetext AI Detector",
            confidence=confidence,
            disclaimer=(
                "Quetext AI ko‘rsatkichi ehtimollik bahosidir; u mualliflik yoki "
                "qoidabuzarlikni yakka o‘zi isbotlamaydi."
            ),
        )

    async def _save_completed(
        self,
        scan_id: str,
        internet: InternetScanResult,
        ai: AIStyleAssessment,
        provider_data: dict[str, Any],
        multi_source: MultiSourceResult,
    ) -> None:
        async with self.session_maker() as session:
            external = await session.scalar(
                select(ExternalScan).where(ExternalScan.scan_id == scan_id)
            )
            if external is None:
                raise QuetextError("Tekshiruv bazadan topilmadi.")
            external.status = "completed"
            external.internet_similarity = internet.similarity
            external.internet_originality = internet.originality
            external.internet_sources_json = json.dumps(
                sanitize_json_value(
                    [
                        {
                            "title": source.title,
                            "url": source.url,
                            "matched_words": source.matched_words,
                            "introduction": source.introduction,
                            "kind": source.kind,
                            "similarity": source.similarity,
                            "input_offset": source.input_offset,
                            "matched_text": source.matched_text,
                            "match_id": source.match_id,
                        }
                        for source in internet.sources
                    ]
                ),
                ensure_ascii=False,
            )
            external.ai_style_score = ai.score
            external.ai_verdict = ai.verdict
            external.ai_reasons_json = json.dumps(ai.reasons, ensure_ascii=False)
            provider_data["ai_provider"] = ai.provider
            provider_data["ai_confidence"] = ai.confidence
            provider_data["internal_scan_status"] = "completed"
            provider_data["multi_source"] = multi_source.to_dict()
            external.provider_payload_json = json.dumps(
                sanitize_json_value(provider_data),
                ensure_ascii=False,
            )
            submission = await session.get(Submission, external.submission_id)
            if submission is not None:
                submission.plagiarism_score = multi_source.combined_similarity
                submission.originality_score = multi_source.combined_originality
            external.completed_at = datetime.now(UTC)
            external.error_message = None
            await session.commit()

    async def _save_failed(self, scan_id: str, message: str) -> None:
        async with self.session_maker() as session:
            external = await session.scalar(
                select(ExternalScan).where(ExternalScan.scan_id == scan_id)
            )
            if external is None:
                return
            external.status = "failed"
            external.error_message = message[:1_000]
            external.completed_at = datetime.now(UTC)
            await session.commit()

    async def _mark_notified(self, scan_id: str) -> None:
        async with self.session_maker() as session:
            external = await session.scalar(
                select(ExternalScan).where(ExternalScan.scan_id == scan_id)
            )
            if external is not None:
                external.notified_at = datetime.now(UTC)
                await session.commit()

    async def _send_completed(
        self,
        external: ExternalScan,
        submission: Submission,
        telegram_id: int,
    ) -> None:
        provider_data = _json_object(external.provider_payload_json)
        sources = [
            InternetSource(
                title=str(value.get("title") or value.get("url") or "Manba"),
                url=str(value.get("url") or ""),
                matched_words=int(value.get("matched_words") or 0),
                introduction=str(value.get("introduction") or ""),
                kind=str(value.get("kind") or "internet"),
                similarity=(
                    float(value["similarity"]) if value.get("similarity") is not None else None
                ),
                input_offset=(
                    int(value["input_offset"]) if value.get("input_offset") is not None else None
                ),
                matched_text=str(value.get("matched_text") or ""),
                match_id=str(value.get("match_id") or ""),
            )
            for value in _json_list(external.internet_sources_json)
            if isinstance(value, dict)
        ]
        internet = InternetScanResult(
            similarity=external.internet_similarity,
            originality=external.internet_originality,
            sources=sources,
            status=external.status,
        )
        raw_multi_source = provider_data.get("multi_source")
        if isinstance(raw_multi_source, dict):
            multi_source = MultiSourceResult.from_dict(raw_multi_source)
        else:
            internet_similarity = float(external.internet_similarity or 0.0)
            multi_source = MultiSourceResult(
                internet_similarity=internet_similarity,
                internal_similarity=0.0,
                combined_similarity=internet_similarity,
                combined_originality=float(external.internet_originality or 0.0),
                internet_matched_words=round(submission.word_count * internet_similarity / 100.0),
                internal_matched_words=0,
                deduplicated_matched_words=round(
                    submission.word_count * internet_similarity / 100.0
                ),
                total_words=submission.word_count,
                internal_sources=[],
            )
        ai_assessment = self._stored_ai_assessment(external, provider_data)
        questions = [str(value) for value in _json_list(external.authorship_questions_json)]
        report_warning = ""
        try:
            report = await asyncio.to_thread(
                build_report,
                submission.filename,
                submission.word_count,
                None,
                internet,
                ai_assessment,
                questions,
                multi_source,
            )
        except Exception:
            logger.exception(
                "PDF report generation failed after a completed scan for submission %s",
                submission.id,
            )
            report_warning = (
                "\n\n⚠️ <b>Plagiat tekshiruvi muvaffaqiyatli yakunlandi, ammo PDF hisobotni "
                "yaratishda texnik xatolik yuz berdi.</b> Natija Quetext xatosi sifatida "
                "belgilanmadi."
            )
        else:
            await self.bot.send_document(
                telegram_id,
                BufferedInputFile(
                    report,
                    filename=f"PlagiAI_Quetext_{submission.id}.pdf",
                ),
                caption="📊 PlagiAI V6 ko‘p manbali yakuniy professional hisobot",
            )

        source_lines = []
        for source in internet.sources[:3]:
            title = html.escape(source.title)
            if source.url:
                url = html.escape(source.url, quote=True)
                label = f'<a href="{url}">{title}</a>'
            else:
                label = title
            source_lines.append(f"• {label} - {source.matched_words} mos so‘z")
        sources_text = "\n".join(source_lines) or "Manba topilmadi."
        ai_score = (
            "ishonchli baho mavjud emas"
            if ai_assessment.score is None
            else f"{ai_assessment.score:.2f}%"
        )
        await self.bot.send_message(
            telegram_id,
            "✅ <b>V6 ko‘p manbali tekshiruv yakunlandi</b>\n\n"
            f"📄 <code>{html.escape(submission.filename)}</code>\n"
            f"🔎 Rejim: <b>Quetext DeepSearch</b>\n"
            f"🌐 Til: <b>{html.escape(language_name(ai_assessment.language))}</b>\n"
            f"🌐 Internet o‘xshashligi: <b>{multi_source.internet_similarity:.2f}%</b>\n"
            f"🟢 Umumiy originallik: <b>{multi_source.combined_originality:.2f}%</b>\n"
            f"🧠 AIga o‘xshash matn: <b>{ai_score}</b>\n"
            f"ℹ️ {html.escape(ai_assessment.verdict)}\n\n"
            f"<b>Asosiy manbalar:</b>\n{sources_text}\n\n"
            "⚠️ AI ko‘rsatkichi mualliflikni isbotlamaydi; yakuniy qaror "
            "manbalar va mualliflik dalillari bilan birga qabul qilinadi."
            f"{report_warning}",
            disable_web_page_preview=True,
        )

    async def _send_failed(
        self,
        telegram_id: int,
        filename: str,
        message: str,
    ) -> None:
        await self.bot.send_message(
            telegram_id,
            "❌ <b>Quetext tekshiruvi xato bilan tugadi</b>\n\n"
            f"📄 <code>{html.escape(filename)}</code>\n"
            f"Sabab: {html.escape(message)}\n\n"
            "Yakuniy plagiat natijasi olinmagani uchun PDF hisobot yaratilmadi.",
        )
