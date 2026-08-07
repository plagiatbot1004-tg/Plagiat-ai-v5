import asyncio
import logging
import sys

import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.config import get_settings
from app.database import create_engine_and_session, create_tables
from app.handlers import build_router
from app.services.certified_scan_manager import CertifiedQuetextScanManager
from app.services.quetext import QuetextClient
from app.web import create_web_app


async def main() -> None:
    settings = get_settings()
    engine, session_maker = create_engine_and_session(settings.database_url)
    await create_tables(engine)

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = Dispatcher()
    dispatcher.include_router(build_router())
    quetext_client = QuetextClient(settings)
    scan_manager = CertifiedQuetextScanManager(
        bot=bot,
        client=quetext_client,
        session_maker=session_maker,
        settings=settings,
    )
    web_app = create_web_app(settings=settings, session_maker=session_maker)
    web_server = uvicorn.Server(
        uvicorn.Config(
            web_app,
            host="0.0.0.0",
            port=settings.port,
            log_level="info",
            access_log=False,
        )
    )
    web_server.install_signal_handlers = lambda: None

    try:
        await bot.delete_webhook(drop_pending_updates=False)
        await scan_manager.recover()
        polling_task = asyncio.create_task(
            dispatcher.start_polling(
                bot,
                settings=settings,
                session_maker=session_maker,
                quetext_client=quetext_client,
                scan_manager=scan_manager,
                allowed_updates=dispatcher.resolve_used_update_types(),
                handle_signals=False,
            )
        )
        web_task = asyncio.create_task(web_server.serve())
        done, pending = await asyncio.wait(
            {polling_task, web_task}, return_when=asyncio.FIRST_COMPLETED
        )
        for task in done:
            if task.cancelled():
                continue
            error = task.exception()
            if error:
                raise error
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
    finally:
        web_server.should_exit = True
        await scan_manager.close()
        await bot.session.close()
        await engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stdout,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Bot stopped")
