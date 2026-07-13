import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.database import Base


class MigraineEntry(Base):
    __tablename__ = "migraine_entries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    intensity: Mapped[int] = mapped_column(Integer, nullable=False)
    side: Mapped[str | None] = mapped_column(String(50), nullable=True)
    pain_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    triggers: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    medications: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    medication_effectiveness: Mapped[str | None] = mapped_column(String(50), nullable=True)
    aura: Mapped[bool | None] = mapped_column(nullable=True)
    nausea: Mapped[bool | None] = mapped_column(nullable=True)
    light_sensitivity: Mapped[bool | None] = mapped_column(nullable=True)
    sound_sensitivity: Mapped[bool | None] = mapped_column(nullable=True)
    sleep_hours: Mapped[float | None] = mapped_column(nullable=True)
    stress_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    weather_record_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("weather_records.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="migraines")
    weather_record = relationship("WeatherRecord", back_populates="migraine_entries")
