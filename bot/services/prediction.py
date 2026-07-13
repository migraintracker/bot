import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select

from bot.database import async_session
from bot.models.cycle import CycleEntry
from bot.models.daily_check import DailyCheck
from bot.models.migraine import MigraineEntry
from bot.models.prediction import Prediction
from bot.models.space_weather import SpaceWeatherRecord
from bot.models.user import User
from bot.models.weather import WeatherRecord
from bot.services.deepseek import deepseek_service
from bot.services.space_weather import space_weather_service
from bot.services.weather import weather_service

logger = logging.getLogger(__name__)


async def generate_prediction_for_user(user_id: str) -> None:
    """Generate weekly prediction for a specific user."""
    async with async_session() as session:
        user = (await session.scalars(select(User).where(User.id == user_id))).first()
        if not user or not user.city:
            logger.info(f"Skipping prediction for user {user_id}: no city configured")
            return

        if not user.latitude or not user.longitude:
            coords = await weather_service.resolve_city(user.city)
            if coords:
                user.latitude, user.longitude = coords
                await session.commit()
            else:
                logger.warning(f"Cannot resolve coordinates for city: {user.city}")
                return

        thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)

        migraine_entries = (
            (await session.scalars(
                select(MigraineEntry)
                .where(
                    MigraineEntry.user_id == user.id,
                    MigraineEntry.started_at >= thirty_days_ago,
                )
                .order_by(MigraineEntry.started_at.asc())
            ))
            .unique()
            .all()
        )

        weather_entries = (
            (await session.scalars(
                select(WeatherRecord)
                .where(
                    WeatherRecord.city == user.city,
                    WeatherRecord.record_date >= thirty_days_ago.date(),
                )
                .order_by(WeatherRecord.record_date.asc())
            ))
            .all()
        )

        migraine_history = []
        for me in migraine_entries:
            migraine_history.append({
                "intensity": me.intensity,
                "duration_minutes": me.duration_minutes,
                "day_offset": (me.started_at.date() - thirty_days_ago.date()).days if me.started_at else None,
                "has_aura": me.aura,
                "stress_level": me.stress_level,
                "sleep_hours": me.sleep_hours,
            })

        # Daily check data (positive AND negative days)
        daily_checks = (
            (await session.scalars(
                select(DailyCheck)
                .where(
                    DailyCheck.user_id == user.id,
                    DailyCheck.check_date >= thirty_days_ago.date(),
                )
                .order_by(DailyCheck.check_date.asc())
            ))
            .all()
        )
        daily_check_data = []
        for dc in daily_checks:
            daily_check_data.append({
                "day_offset": (dc.check_date - thirty_days_ago.date()).days,
                "has_migraine": dc.has_migraine,
            })

        # Cycle data
        cycle_entries = (
            (await session.scalars(
                select(CycleEntry)
                .where(
                    CycleEntry.user_id == user.id,
                    CycleEntry.entry_date >= thirty_days_ago.date(),
                )
                .order_by(CycleEntry.entry_date.asc())
            ))
            .all()
        )
        cycle_data = []
        for ce in cycle_entries:
            cycle_data.append({
                "day_offset": (ce.entry_date - thirty_days_ago.date()).days,
                "phase": ce.phase,
                "period_start": ce.period_start,
                "period_end": ce.period_end,
                "symptoms": ce.symptoms,
            })

        weather_history = []
        for wr in weather_entries:
            weather_history.append({
                "day_offset": (wr.record_date - thirty_days_ago.date()).days,
                "temp_min": wr.temp_min,
                "temp_max": wr.temp_max,
                "temp_avg": wr.temp_avg,
                "pressure": wr.pressure,
                "humidity": wr.humidity,
                "wind_speed": wr.wind_speed,
                "cloudiness": wr.cloudiness,
                "precipitation_mm": wr.precipitation_mm,
                "condition": wr.weather_condition,
            })

        # Space weather history
        space_weather_entries = (
            (await session.scalars(
                select(SpaceWeatherRecord)
                .where(SpaceWeatherRecord.record_date >= thirty_days_ago.date())
                .order_by(SpaceWeatherRecord.record_date.asc())
            ))
            .all()
        )

        space_history = []
        for sr in space_weather_entries:
            space_history.append({
                "day_offset": (sr.record_date - thirty_days_ago.date()).days,
                "kp_index": sr.kp_index,
                "kp_max": sr.kp_max,
                "geomagnetic_storm": sr.geomagnetic_storm,
                "storm_level": sr.storm_level,
                "solar_wind_speed": sr.solar_wind_speed,
            })

        forecast = await weather_service.get_forecast(user.latitude, user.longitude)
        weather_forecast = []
        today = date.today()
        for i, day_data in enumerate(forecast):
            weather_forecast.append({
                "date_offset": i,
                "date": (today + timedelta(days=i)).isoformat(),
                "temp_min": day_data.get("temp_min"),
                "temp_max": day_data.get("temp_max"),
                "temp_avg": day_data.get("temp_avg"),
                "pressure": day_data.get("pressure"),
                "humidity": day_data.get("humidity"),
                "wind_speed": day_data.get("wind_speed"),
                "cloudiness": day_data.get("cloudiness"),
                "precipitation_mm": day_data.get("precipitation_mm"),
                "precipitation_probability": day_data.get("precipitation_probability"),
                "condition": day_data.get("weather_condition"),
            })

        kp_forecast = await space_weather_service.get_kp_forecast()

        result = await deepseek_service.generate_prediction(
            migraine_history, weather_history, weather_forecast,
            user_gender=user.gender, user_age=user.age,
            space_history=space_history, kp_forecast=kp_forecast,
            daily_checks=daily_check_data,
            cycle_data=cycle_data,
        )

        existing_predictions = (
            (await session.scalars(
                select(Prediction).where(
                    Prediction.user_id == user.id,
                    Prediction.prediction_date >= today,
                )
            ))
            .all()
        )
        existing_dates = {p.prediction_date for p in existing_predictions}

        for pred in result.get("predictions", []):
            pred_date = today + timedelta(days=pred.get("date_offset", 0))
            if pred_date in existing_dates:
                continue

            prediction = Prediction(
                user_id=user.id,
                prediction_date=pred_date,
                risk_level=pred.get("risk_level", "low"),
                risk_score=pred.get("risk_score", 0.0),
                factors=pred.get("factors"),
                ai_analysis=pred.get("analysis"),
            )
            session.add(prediction)

        await session.commit()
        logger.info(f"Generated {len(result.get('predictions', []))} predictions for user {user_id}")


async def generate_all_predictions() -> None:
    """Generate predictions for all users with prediction enabled."""
    async with async_session() as session:
        users = (
            (await session.scalars(select(User).where(User.prediction_enabled == True, User.city != None)))  # noqa: E711
            .all()
        )

    logger.info(f"Generating predictions for {len(users)} users")
    for user in users:
        try:
            await generate_prediction_for_user(user.id)
        except Exception as e:
            logger.error(f"Failed to generate prediction for user {user.id}: {e}")
