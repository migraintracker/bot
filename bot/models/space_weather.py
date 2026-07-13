import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from bot.database import Base


class SpaceWeatherRecord(Base):
    __tablename__ = "space_weather_records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    record_date: Mapped[date] = mapped_column(Date, nullable=False, unique=True, index=True)
    kp_index: Mapped[float | None] = mapped_column(Float, nullable=True)
    kp_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    kp_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    solar_wind_speed: Mapped[float | None] = mapped_column(Float, nullable=True)
    solar_wind_density: Mapped[float | None] = mapped_column(Float, nullable=True)
    bz_component: Mapped[float | None] = mapped_column(Float, nullable=True)
    geomagnetic_storm: Mapped[bool] = mapped_column(default=False)
    storm_level: Mapped[str | None] = mapped_column(String(20), nullable=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="noaa")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
