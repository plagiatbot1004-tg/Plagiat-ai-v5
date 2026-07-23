from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.models import ExternalScan, Submission, User

router = Router(name="admin")


@router.message(Command("admin"))
async def admin_statistics(
    message: Message,
    settings: Settings,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    if message.from_user is None or message.from_user.id not in settings.admin_id_set:
        await message.answer("Bu bo‘lim faqat administrator uchun.")
        return

    async with session_maker() as session:
        users_count = await session.scalar(select(func.count(User.id))) or 0
        submissions_count = await session.scalar(select(func.count(Submission.id))) or 0
        avg_originality = await session.scalar(
            select(func.avg(ExternalScan.internet_originality)).where(
                ExternalScan.status == "completed"
            )
        )
        internet_completed = (
            await session.scalar(
                select(func.count(ExternalScan.id)).where(ExternalScan.status == "completed")
            )
            or 0
        )
        internet_pending = (
            await session.scalar(
                select(func.count(ExternalScan.id)).where(ExternalScan.status == "pending")
            )
            or 0
        )

    average = float(avg_originality or 0)
    await message.answer(
        "🛠 <b>PlagiAI admin statistikasi</b>\n\n"
        f"👥 Foydalanuvchilar: <b>{users_count}</b>\n"
        f"📄 Tekshiruvlar: <b>{submissions_count}</b>\n"
        f"📊 O‘rtacha internet originalligi: <b>{average:.2f}%</b>\n"
        f"🌐 Internet yakunlangan: <b>{internet_completed}</b>\n"
        f"⏳ Internet kutilmoqda: <b>{internet_pending}</b>"
    )
