import logging

from aiogram.types import BufferedInputFile

from app.config import Settings
from app.models import ExternalScan, Submission
from app.services.certificate import get_or_create_certificate
from app.services.scan_manager import QuetextScanManager

logger = logging.getLogger(__name__)


class CertifiedQuetextScanManager(QuetextScanManager):
    """Quetext manager that also issues a verifiable certificate after success."""

    def __init__(self, *, settings: Settings, **kwargs) -> None:
        super().__init__(**kwargs)
        self.settings = settings

    async def _send_completed(
        self,
        external: ExternalScan,
        submission: Submission,
        telegram_id: int,
    ) -> None:
        await super()._send_completed(external, submission, telegram_id)
        try:
            certificate, pdf, verify_url = await get_or_create_certificate(
                session_maker=self.session_maker,
                submission=submission,
                external=external,
                telegram_id=telegram_id,
                settings=self.settings,
            )
            await self.bot.send_document(
                telegram_id,
                BufferedInputFile(
                    pdf,
                    filename=f"PlagiAI_Sertifikat_{certificate.certificate_number}.pdf",
                ),
                caption=(
                    "📜 <b>PlagiAI hujjat tekshiruvi sertifikati</b>\n"
                    f"🆔 <code>{certificate.certificate_number}</code>\n"
                    f"🔐 QR/verifikatsiya: {verify_url}"
                ),
            )
        except Exception:
            logger.exception("Certificate delivery failed for submission %s", submission.id)
            await self.bot.send_message(
                telegram_id,
                "⚠️ Tekshiruv hisobotini oldingiz, ammo sertifikat yaratishda texnik xatolik "
                "yuz berdi. Administrator loglarini tekshirish kerak.",
            )
