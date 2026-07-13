import asyncio
import logging
from datetime import date, datetime, timedelta, timezone

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from arq import create_pool
from arq.connections import RedisSettings
from arq.cron import CronJob
from sqlalchemy import select

from bot.config import settings
from bot.database import async_session
from bot.models.user import User
from bot.models.weather import WeatherRecord
from bot.models.space_weather import SpaceWeatherRecord
from bot.models.daily_check import DailyCheck
from bot.services.prediction import generate_all_predictions, generate_prediction_for_user
from bot.services.space_weather import space_weather_service
from bot.services.weather import weather_service

logger = logging.getLogger(__name__)

REDIS_SETTINGS = RedisSettings(host=settings.redis_host, port=settings.redis_port)


async def sync_weather_for_city(ctx: dict) -> None:
    """Sync weather data for all unique cities."""
    async with async_session() as session:
        cities = (
            (
                await session.scalars(
                    select(User.city, User.latitude, User.longitude)
                    .where(User.city.isnot(None))
                    .distinct()
                )
            )
            .all()
        )

    today = date.today()

    if not cities:
        logger.info("No cities configured for weather sync")
        return

    for city, lat, lon in cities:
        if not lat or not lon:
            coords = await weather_service.resolve_city(city)
            if coords:
                lat, lon = coords
                async with async_session() as session:
                    users = (await session.scalars(select(User).where(User.city == city))).all()
                    for u in users:
                        u.latitude = lat
                        u.longitude = lon
                    await session.commit()
            else:
                logger.warning(f"Cannot resolve coordinates for {city}, skipping")
                continue

        async with async_session() as session:
            existing = (
                await session.scalars(
                    select(WeatherRecord).where(
                        WeatherRecord.city == city,
                        WeatherRecord.record_date == today,
                    )
                )
            ).first()

            if existing:
                logger.info(f"Weather for {city} already synced today")
                continue

            weather_data = await weather_service.get_daily_weather(city, lat, lon)

            if weather_data:
                record = WeatherRecord(
                    city=city,
                    latitude=lat,
                    longitude=lon,
                    record_date=today,
                    **{k: v for k, v in weather_data.items() if k != "source" and hasattr(WeatherRecord, k)},
                    source=weather_data.get("source", "unknown"),
                )
                session.add(record)
                await session.commit()
                logger.info(f"Saved weather for {city} from {weather_data.get('source')}")
            else:
                logger.error(f"Failed to get weather for {city}")

        await asyncio.sleep(1)


async def sync_weather_periodic(ctx: dict) -> None:
    """Periodic task: sync weather for all cities."""
    logger.info("Starting periodic weather sync")
    await sync_weather_for_city(ctx)


async def generate_predictions_periodic(ctx: dict) -> None:
    """Periodic task: generate predictions for all users."""
    logger.info("Starting periodic prediction generation")
    await generate_all_predictions()


async def send_reminders(ctx: dict) -> None:
    now_utc = datetime.now(timezone.utc)

    async with async_session() as session:
        users = (
            (await session.scalars(select(User).where(User.reminder_enabled == True)))
            .all()
        )

    if not users:
        return

    bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Да, болит", callback_data="dailycheck_yes"),
                InlineKeyboardButton(text="Нет, всё хорошо", callback_data="dailycheck_no"),
            ],
        ]
    )

    sent = 0
    for user in users:
        try:
            # Convert user's local hour to UTC to check if it's time
            tz_offset = user.timezone_offset or 0
            local_hour = user.reminder_hour or 20
            expected_utc_hour = (local_hour - tz_offset) % 24

            if now_utc.hour != expected_utc_hour:
                continue

            # Check if user already checked in today (in their local day)
            local_now = now_utc + timedelta(hours=tz_offset)
            async with async_session() as session:
                existing = (
                    await session.scalars(
                        select(DailyCheck).where(
                            DailyCheck.user_id == user.id,
                            DailyCheck.check_date == local_now.date(),
                        )
                    )
                ).first()
            if existing:
                continue

            await bot.send_message(
                user.telegram_id,
                "Ежедневный чекин: была ли сегодня мигрень?",
                reply_markup=kb,
            )
            sent += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.error(f"Failed to send reminder to user {user.id}: {e}")

    await bot.session.close()
    logger.info(f"Sent {sent} reminder(s)")


async def sync_space_weather(ctx: dict) -> None:
    """Sync space weather data from NOAA SWPC. Updates record if already exists."""
    today = date.today()

    summary = await space_weather_service.get_today_summary()
    if not summary:
        logger.warning("Failed to get space weather data")
        return

    async with async_session() as session:
        existing = (
            await session.scalars(
                select(SpaceWeatherRecord).where(SpaceWeatherRecord.record_date == today)
            )
        ).first()

        if existing:
            existing.kp_index = summary.get("kp_index")
            existing.kp_max = summary.get("kp_max")
            existing.kp_min = summary.get("kp_min")
            existing.solar_wind_speed = summary.get("solar_wind_speed")
            existing.solar_wind_density = summary.get("solar_wind_density")
            existing.bz_component = summary.get("bz_component")
            existing.geomagnetic_storm = summary.get("geomagnetic_storm", False)
            existing.storm_level = summary.get("storm_level")
            existing.source = summary.get("source", "noaa")
            await session.commit()
            logger.info(f"Space weather updated: Kp_max={summary.get('kp_max')}")
        else:
            record = SpaceWeatherRecord(
                record_date=today,
                kp_index=summary.get("kp_index"),
                kp_max=summary.get("kp_max"),
                kp_min=summary.get("kp_min"),
                solar_wind_speed=summary.get("solar_wind_speed"),
                solar_wind_density=summary.get("solar_wind_density"),
                bz_component=summary.get("bz_component"),
                geomagnetic_storm=summary.get("geomagnetic_storm", False),
                storm_level=summary.get("storm_level"),
                source=summary.get("source", "noaa"),
            )
            session.add(record)
            await session.commit()
            logger.info(f"Space weather synced: Kp={summary.get('kp_index')}")


async def notify_kp_storm(ctx: dict) -> None:
    """Check Kp forecast and alert users about upcoming magnetic storms."""
    forecast = await space_weather_service.get_kp_forecast()
    alerts = await space_weather_service.get_storm_alerts()

    storm_days = []
    for day in forecast:
        if day.get("storm_risk") and day.get("storm_level") in ("G2", "G3", "G4", "G5"):
            storm_days.append(day)

    # Also check current alerts
    current_storm = any(
        a.get("severity") in ("G2", "G3", "G4", "G5") for a in alerts
    )

    if not storm_days and not current_storm:
        return

    async with async_session() as session:
        users = (
            (await session.scalars(
                select(User).where(User.prediction_enabled == True, User.is_active == True)
            ))
            .all()
        )

    if not users:
        return

    bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    storm_lines = []
    if current_storm:
        storm_lines.append("Текущая магнитная буря!")
    for day in storm_days[:3]:
        storm_lines.append(
            f"{day['date']}: Kp {day['kp_max']:.1f} ({day['storm_level']})"
        )

    if storm_lines:
        text = (
            "<b>Магнитная буря</b>\n\n"
            + "\n".join(storm_lines)
            + "\n\nЭто может повлиять на риск мигрени. "
            "Постарайся снизить нагрузку и избегать триггеров.\n\n"
            "Прогноз носит информационный характер."
        )
        sent = 0
        for user in users:
            try:
                await bot.send_message(user.telegram_id, text)
                sent += 1
                await asyncio.sleep(0.05)
            except Exception as e:
                logger.error(f"Failed to send storm alert to {user.id}: {e}")
        await bot.session.close()
        logger.info(f"Sent Kp storm alert to {sent} users")


async def startup(ctx: dict) -> None:
    logger.info("Worker started")


async def shutdown(ctx: dict) -> None:
    await weather_service.close()
    await space_weather_service.close()
    from bot.services.deepseek import deepseek_service
    await deepseek_service.close()
    logger.info("Worker shut down")


class WorkerSettings:
    functions = [
        sync_weather_periodic,
        generate_predictions_periodic,
        sync_weather_for_city,
        send_reminders,
        generate_prediction_for_user,
        sync_space_weather,
        notify_kp_storm,
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = REDIS_SETTINGS
    cron_jobs = [
        CronJob(
            name="sync_weather_morning",
            coroutine=sync_weather_periodic,
            month=None,
            day=None,
            weekday=None,
            hour={6, 18},
            minute=0,
            second=0,
            microsecond=0,
            run_at_startup=False,
            unique=True,
            job_id=None,
            timeout_s=300,
            keep_result_s=0,
            keep_result_forever=False,
            max_tries=1,
        ),
        CronJob(
            name="generate_predictions",
            coroutine=generate_predictions_periodic,
            month=None,
            day=None,
            weekday=None,
            hour={settings.prediction_send_hour},
            minute=0,
            second=0,
            microsecond=0,
            run_at_startup=False,
            unique=True,
            job_id=None,
            timeout_s=600,
            keep_result_s=0,
            keep_result_forever=False,
            max_tries=1,
        ),
        CronJob(
            name="sync_space_weather",
            coroutine=sync_space_weather,
            month=None,
            day=None,
            weekday=None,
            hour={0, 4, 8, 12, 16, 20},
            minute=30,
            second=0,
            microsecond=0,
            run_at_startup=False,
            unique=True,
            job_id=None,
            timeout_s=120,
            keep_result_s=0,
            keep_result_forever=False,
            max_tries=1,
        ),
        CronJob(
            name="notify_kp_storm",
            coroutine=notify_kp_storm,
            month=None,
            day=None,
            weekday=None,
            hour={6, 12, 18, 0},
            minute=0,
            second=0,
            microsecond=0,
            run_at_startup=False,
            unique=True,
            job_id=None,
            timeout_s=120,
            keep_result_s=0,
            keep_result_forever=False,
            max_tries=1,
        ),
        CronJob(
            name="send_reminders",
            coroutine=send_reminders,
            month=None,
            day=None,
            weekday=None,
            hour=None,
            minute=0,
            second=0,
            microsecond=0,
            run_at_startup=False,
            unique=True,
            job_id=None,
            timeout_s=300,
            keep_result_s=0,
            keep_result_forever=False,
            max_tries=1,
        ),
    ]
