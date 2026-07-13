import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage
from redis.asyncio import Redis

from bot.config import settings
from bot.handlers.start import router as start_router
from bot.handlers.profile import router as profile_router
from bot.handlers.logging_handlers import router as logging_router
from bot.handlers.history import router as history_router
from bot.handlers.prediction_handlers import router as prediction_router
from bot.handlers.cycle import router as cycle_router
from bot.middlewares.db import DbSessionMiddleware

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


async def main():
    redis = Redis(host=settings.redis_host, port=settings.redis_port)
    storage = RedisStorage(redis=redis)

    bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=storage)

    dp.update.middleware(DbSessionMiddleware())

    dp.include_router(start_router)
    dp.include_router(profile_router)
    dp.include_router(logging_router)
    dp.include_router(history_router)
    dp.include_router(prediction_router)
    dp.include_router(cycle_router)

    logger.info("Starting bot...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
