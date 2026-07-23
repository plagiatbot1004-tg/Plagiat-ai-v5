from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.keyboards import main_menu
from app.models import User

router = Router(name="start")


async def get_or_create_user(
    message: Message, session_maker: async_sessionmaker[AsyncSession]
) -> User:
    telegram_user = message.from_user
    if telegram_user is None:
        raise ValueError("Telegram foydalanuvchisi topilmadi.")

    async with session_maker() as session:
        user = await session.scalar(select(User).where(User.telegram_id == telegram_user.id))
        if user is None:
            user = User(
                telegram_id=telegram_user.id,
                username=telegram_user.username,
                first_name=telegram_user.first_name or "",
                last_name=telegram_user.last_name,
            )
            session.add(user)
        else:
            user.username = telegram_user.username
            user.first_name = telegram_user.first_name or ""
            user.last_name = telegram_user.last_name
        await session.commit()
        return user


@router.message(CommandStart())
async def start_command(message: Message, session_maker: async_sessionmaker[AsyncSession]) -> None:
    await get_or_create_user(message, session_maker)
    name = message.from_user.first_name if message.from_user else "foydalanuvchi"
    await message.answer(
        f"Assalomu alaykum, <b>{name}</b>! 👋\n\n"
        "Men <b>PlagiAI</b> botiman. PDF, DOCX yoki TXT hujjatni yuboring — "
        "uni ochiq internet va akademik veb manbalar bilan solishtirib, tilga mos "
        "AI indikatori va yakuniy professional PDF hisobotni tayyorlayman.",
        reply_markup=main_menu(),
    )


@router.message(F.text == "📄 Faylni tekshirish")
async def ask_for_document(message: Message) -> None:
    await message.answer(
        "Tekshirish uchun <b>PDF, DOCX yoki TXT</b> faylni shu chatga yuboring.\n\n"
        "Skan ko‘rinishidagi PDF emas, matni belgilab olinadigan hujjat bo‘lishi kerak. "
        "Internet tekshiruvi bir necha daqiqa davom etishi mumkin."
    )
