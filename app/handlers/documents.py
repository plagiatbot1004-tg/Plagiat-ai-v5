import asyncio
import hashlib
import html
import json
import logging
import re
import tempfile
import uuid
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.models import ExternalScan, Submission, User
from app.services.ai_risk import (
    analyze_document_ai_style,
    generate_authorship_questions,
    language_name,
    supports_external_ai,
)
from app.services.extractor import (
    SUPPORTED_EXTENSIONS,
    ExtractionError,
    extract_text,
    normalize_text,
)
from app.services.quetext import QuetextClient, QuetextError
from app.services.scan_manager import QuetextScanManager
from app.services.unicode_safety import safe_text

logger = logging.getLogger(__name__)
router = Router(name="documents")


def _safe_filename(filename: str) -> str:
    cleaned = re.sub(r"[^\w.() -]", "_", filename, flags=re.UNICODE).strip(". ")
    return cleaned[:120] or "document"


async def _registered_user(
    telegram_id: int, session_maker: async_sessionmaker[AsyncSession]
) -> User | None:
    async with session_maker() as session:
        return await session.scalar(select(User).where(User.telegram_id == telegram_id))


@router.message(F.document)
async def check_document(
    message: Message,
    bot: Bot,
    settings: Settings,
    session_maker: async_sessionmaker[AsyncSession],
    quetext_client: QuetextClient,
    scan_manager: QuetextScanManager,
) -> None:
    telegram_user = message.from_user
    document = message.document
    if telegram_user is None or document is None:
        return

    user = await _registered_user(telegram_user.id, session_maker)
    if user is None:
        await message.answer("Avval /start buyrug‘ini bosing.")
        return

    filename = _safe_filename(document.file_name or "document")
    extension = Path(filename).suffix.casefold()
    if extension not in SUPPORTED_EXTENSIONS:
        await message.answer("❌ Faqat <b>PDF, DOCX yoki TXT</b> fayl yuboring.")
        return
    if document.file_size and document.file_size > settings.max_file_bytes:
        await message.answer(
            f"❌ Fayl juda katta. Eng katta ruxsat etilgan hajm: <b>{settings.max_file_mb} MB</b>."
        )
        return
    if not quetext_client.ready:
        await message.answer(
            "❌ <b>Internet tekshiruvi sozlanmagan.</b>\n\n"
            "Quetext ulanishi bo‘lmagani uchun hujjat tekshirilmadi va "
            "hisobot yaratilmadi. Railway Variables’da QUETEXT_API_KEY qiymatini tekshiring."
        )
        return

    status = await message.answer("⏳ Fayl qabul qilindi. Matn ajratilmoqda…")
    try:
        with tempfile.TemporaryDirectory(prefix="plagiai_") as temp_directory:
            local_path = Path(temp_directory) / f"upload{extension}"
            await bot.download(document, destination=local_path)
            raw_text = safe_text(await extract_text(local_path, extension))

        normalized = safe_text(normalize_text(raw_text))
        word_count = len(normalized.split())
        if word_count < 20:
            await status.edit_text(
                "❌ Quetext plagiat tekshiruvi uchun hujjatda kamida <b>20 ta so‘z</b> "
                "bo‘lishi kerak."
            )
            return
        if len(normalized) > settings.max_text_chars:
            await status.edit_text(
                f"❌ Hujjat matni juda uzun. Limit: <b>{settings.max_text_chars:,}</b> belgi."
            )
            return

        await status.edit_text(
            "🌐 Hujjat internet va AI tekshiruviga tayyorlanmoqda…"
        )
        ai_assessment, authorship_questions = await asyncio.gather(
            asyncio.to_thread(analyze_document_ai_style, raw_text),
            asyncio.to_thread(generate_authorship_questions, raw_text),
        )
        scan_id = uuid.uuid4().hex
        enable_external_ai = supports_external_ai(ai_assessment.language)
        async with session_maker() as session:
            submission = Submission(
                user_id=user.id,
                telegram_file_id=document.file_id,
                filename=filename,
                content_hash=hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
                raw_text=raw_text,
                normalized_text=normalized,
                word_count=word_count,
                # These existing columns are finalized with V6 combined scores
                # after Internet + internal comparison completes.
                originality_score=0.0,
                plagiarism_score=0.0,
            )
            session.add(submission)
            await session.flush()

            external_scan = ExternalScan(
                submission_id=submission.id,
                provider="quetext",
                scan_id=scan_id,
                status="pending",
                ai_style_score=ai_assessment.score,
                ai_verdict=ai_assessment.verdict,
                ai_reasons_json=json.dumps(ai_assessment.reasons, ensure_ascii=False),
                authorship_questions_json=json.dumps(authorship_questions, ensure_ascii=False),
                provider_payload_json=json.dumps(
                    {
                        "detected_language": ai_assessment.language,
                        "ai_provider": ai_assessment.provider,
                        "ai_requested": enable_external_ai,
                    },
                    ensure_ascii=False,
                ),
            )
            session.add(external_scan)
            await session.commit()

        try:
            plagiarism_report_id = await quetext_client.submit_plagiarism(
                text=raw_text,
                title=filename,
            )
        except QuetextError as exc:
            logger.warning("Quetext submission failed: %s", exc)
            async with session_maker() as session:
                saved_scan = await session.scalar(
                    select(ExternalScan).where(ExternalScan.scan_id == scan_id)
                )
                if saved_scan:
                    saved_scan.status = "failed"
                    saved_scan.error_message = str(exc)[:1_000]
                    await session.commit()
            await status.edit_text(
                "❌ <b>Tekshiruv boshlanmadi.</b>\n\n"
                f"📄 <code>{html.escape(filename)}</code>\n"
                f"Sabab: {html.escape(exc.public_message)}\n\n"
                "Quetext plagiat so‘rovini qabul qilmagani uchun tekshirilmagan PDF "
                "yaratilmadi."
            )
            return

        ai_report_id: str | None = None
        ai_submission_error: str | None = None
        if enable_external_ai:
            try:
                ai_report_id = await quetext_client.submit_ai(
                    text=raw_text,
                    title=filename,
                )
            except QuetextError as exc:
                ai_submission_error = exc.public_message
                logger.warning("Quetext AI submission failed: %s", exc)

        async with session_maker() as session:
            saved_scan = await session.scalar(
                select(ExternalScan).where(ExternalScan.scan_id == scan_id)
            )
            if saved_scan is None:
                await status.edit_text(
                    "❌ Tekshiruv bazaga saqlanmadi. Administratorga murojaat qiling."
                )
                return
            provider_data = {
                "detected_language": ai_assessment.language,
                "ai_provider": ai_assessment.provider,
                "ai_requested": enable_external_ai,
                "plagiarism_report_id": plagiarism_report_id,
                "ai_report_id": ai_report_id,
            }
            if ai_submission_error:
                provider_data["ai_submission_error"] = ai_submission_error
            saved_scan.provider_payload_json = json.dumps(
                provider_data,
                ensure_ascii=False,
            )
            await session.commit()

        scan_manager.start(scan_id)
        ai_text = (
            "Quetext AI Detector"
            if enable_external_ai
            else (
                "o‘zbekcha ehtiyotkor uslub tahlili"
                if ai_assessment.language == "uz"
                else "ushbu til uchun AI bahosi mavjud emas"
            )
        )
        if ai_submission_error:
            ai_text = f"boshlanmadi - {ai_submission_error}"
        await status.edit_text(
            "🔎 <b>Tekshiruv boshlandi</b>\n\n"
            f"📄 <code>{html.escape(filename)}</code>\n"
            f"📝 So‘zlar: <b>{word_count}</b>\n"
            f"🌐 Til: <b>{html.escape(language_name(ai_assessment.language))}</b>\n"
            f"🧠 AI tahlili: <b>{html.escape(ai_text)}</b>\n"
            "⚙️ Rejim: <b>Quetext DeepSearch</b>\n\n"
            "Internet va AI natijalari yakunlangach bot bitta professional PDF "
            "hisobotni avtomatik yuboradi. Natija webhook emas, polling orqali olinadi."
        )
    except ExtractionError as exc:
        await status.edit_text(f"❌ {html.escape(str(exc))}")
    except Exception:
        logger.exception("Document processing failed")
        await status.edit_text(
            "❌ Tekshiruv vaqtida xatolik yuz berdi. Birozdan keyin qayta urinib ko‘ring."
        )


@router.message(F.text == "🕘 Tekshiruvlarim")
async def show_history(message: Message, session_maker: async_sessionmaker[AsyncSession]) -> None:
    if message.from_user is None:
        return

    async with session_maker() as session:
        user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
        if user is None:
            await message.answer("Avval /start buyrug‘ini bosing.")
            return
        submissions = (
            await session.execute(
                select(Submission, ExternalScan)
                .outerjoin(ExternalScan, ExternalScan.submission_id == Submission.id)
                .where(Submission.user_id == user.id)
                .order_by(Submission.created_at.desc())
                .limit(10)
            )
        ).all()

    if not submissions:
        await message.answer("Sizda hozircha tekshiruvlar yo‘q.")
        return

    lines = ["<b>Oxirgi tekshiruvlaringiz:</b>\n"]
    status_names = {
        "pending": "🌐 internet va AI tekshirilmoqda",
        "completed": "✅ professional tekshiruv yakunlangan",
        "failed": "⚠️ tekshiruv boshlanmadi yoki xato bilan tugadi",
    }
    for item, external in submissions:
        date_text = item.created_at.strftime("%d.%m.%Y %H:%M")
        result_line = ""
        if external and external.status == "completed":
            originality = f"{item.originality_score:.2f}%"
            similarity = f"{item.plagiarism_score:.2f}%"
            result_line = (
                f"   🟢 Umumiy originallik: {originality} · 🔴 umumiy o‘xshashlik: {similarity}\n"
            )
        lines.append(
            f"📄 <code>{html.escape(item.filename)}</code>\n"
            f"   🕒 {date_text}\n"
            f"{result_line}"
            f"   {status_names.get(external.status if external else '', '⚠️ holat noma’lum')}"
        )
    await message.answer("\n\n".join(lines))
