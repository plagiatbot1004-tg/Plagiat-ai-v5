from aiogram import F, Router
from aiogram.types import Message

router = Router(name="common")


@router.message(F.text == "ℹ️ Yordam")
async def help_message(message: Message) -> None:
    await message.answer(
        "<b>PlagiAI qanday ishlaydi?</b>\n\n"
        "1. PDF, DOCX yoki TXT fayl yuboring.\n"
        "2. Quetext DeepSearch ochiq internet va akademik veb manbalarni tekshiradi.\n"
        "3. Til qo‘llab-quvvatlansa AI indikatori ham olinadi.\n"
        "4. Faqat yakuniy natija kelgach manbalar, ekspert xulosasi va PDF yuboriladi.\n\n"
        "Inglizcha matnda Quetext AI indikatori, o‘zbekcha matnda "
        "ehtiyotkor stilometrik signal ishlatiladi. ⚠️ AI ko‘rsatkichi mualliflikni "
        "isbotlamaydi. Skan qilingan PDF uchun lokal OCR hali yo‘q."
    )


@router.message(F.text)
async def unknown_text(message: Message) -> None:
    await message.answer(
        "Tekshirish uchun PDF, DOCX yoki TXT fayl yuboring yoki menyudan bo‘lim tanlang."
    )
