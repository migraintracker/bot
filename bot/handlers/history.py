from datetime import date

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import desc, func, select

from bot.database import async_session
from bot.keyboards.main_menu import main_menu_kb
from bot.models.migraine import MigraineEntry
from bot.models.space_weather import SpaceWeatherRecord
from bot.models.user import User
from bot.models.weather import WeatherRecord

router = Router(name="history")

ITEMS_PER_PAGE = 5


async def _get_weather_and_kp(entry_date: date, city: str) -> tuple[str, str]:
    """Get short weather and Kp strings for a given date."""
    weather_str = ""
    kp_str = ""

    async with async_session() as session:
        weather = (
            await session.scalars(
                select(WeatherRecord).where(
                    WeatherRecord.city == city,
                    WeatherRecord.record_date == entry_date,
                )
            )
        ).first()

        space = (
            await session.scalars(
                select(SpaceWeatherRecord).where(SpaceWeatherRecord.record_date == entry_date)
            )
        ).first()

    if weather:
        parts = []
        if weather.temp_avg is not None:
            parts.append(f"{weather.temp_avg:.0f}°")
        if weather.pressure is not None:
            parts.append(f"{weather.pressure:.0f} hPa")
        if weather.humidity is not None:
            parts.append(f"{weather.humidity:.0f}%")
        if parts:
            weather_str = ", ".join(parts)

    if space:
        if space.geomagnetic_storm:
            kp_str = f"Kp {space.kp_max:.1f} буря"
        elif space.kp_index is not None:
            kp_str = f"Kp {space.kp_index:.1f}"

    return weather_str, kp_str


@router.callback_query(lambda c: c.data == "stats_menu")
async def stats_menu(callback: CallbackQuery):
    async with async_session() as session:
        user = (await session.scalars(select(User).where(User.telegram_id == callback.from_user.id))).first()
        if not user:
            await callback.answer("Пользователь не найден")
            return

        total = (
            await session.scalars(select(func.count(MigraineEntry.id)).where(MigraineEntry.user_id == user.id))
        ).first()

        avg_intensity = (
            await session.scalars(
                select(func.avg(MigraineEntry.intensity)).where(MigraineEntry.user_id == user.id)
            )
        ).first()

        today = date.today()
        this_month_start = today.replace(day=1)
        this_month = (
            await session.scalars(
                select(func.count(MigraineEntry.id)).where(
                    MigraineEntry.user_id == user.id,
                    func.date(MigraineEntry.started_at) >= this_month_start,
                )
            )
        ).first()

        migraine_dates = (
            (await session.scalars(
                select(func.date(MigraineEntry.started_at))
                .where(MigraineEntry.user_id == user.id)
                .distinct()
            ))
            .all()
        )

    total_migraine_days = len(migraine_dates) if migraine_dates else 0
    avg_text = f"{avg_intensity:.1f}" if avg_intensity else "--"

    text = (
        "<b>Статистика мигреней</b>\n\n"
        f"Всего записей: <b>{total or 0}</b>\n"
        f"Дней с мигренью: <b>{total_migraine_days}</b>\n"
        f"За этот месяц: <b>{this_month or 0}</b>\n"
        f"Средняя интенсивность: <b>{avg_text}/10</b>"
    )

    await callback.message.edit_text(text, reply_markup=main_menu_kb())
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("history_page_"))
async def history_page(callback: CallbackQuery):
    page = int(callback.data.split("_")[-1])

    async with async_session() as session:
        user = (await session.scalars(select(User).where(User.telegram_id == callback.from_user.id))).first()
        if not user:
            await callback.answer("Пользователь не найден")
            return

        total = (
            await session.scalars(select(func.count(MigraineEntry.id)).where(MigraineEntry.user_id == user.id))
        ).first()

        entries = (
            (
                await session.scalars(
                    select(MigraineEntry)
                    .where(MigraineEntry.user_id == user.id)
                    .order_by(desc(MigraineEntry.started_at))
                    .offset(page * ITEMS_PER_PAGE)
                    .limit(ITEMS_PER_PAGE)
                )
            )
            .unique()
            .all()
        )

    if not entries:
        await callback.message.edit_text(
            "<b>История пуста</b>\n\nНачни с записи первой мигрени.",
            reply_markup=main_menu_kb(),
        )
        await callback.answer()
        return

    lines = [f"<b>История записей</b> (стр. {page + 1})\n"]
    for e in entries:
        entry_date = e.started_at.date() if e.started_at else date.today()
        date_str = e.started_at.strftime("%d.%m.%Y %H:%M")
        dur_str = ""
        if e.duration_minutes:
            h = e.duration_minutes // 60
            m = e.duration_minutes % 60
            dur_str = f" ({h} ч {m} мин)" if h else f" ({m} мин)"
        lines.append(f"-- {date_str} -- <b>{e.intensity}/10</b>{dur_str}")

        ctx_parts = []
        if e.triggers:
            ctx_parts.append(f"тр: {', '.join(e.triggers[:2])}")
        if e.stress_level is not None:
            ctx_parts.append(f"стресс {e.stress_level}/10")
        if e.sleep_hours is not None:
            ctx_parts.append(f"сон {e.sleep_hours}ч")
        if ctx_parts:
            lines.append(f"   {', '.join(ctx_parts)}")

        if user and user.city:
            wstr, kstr = await _get_weather_and_kp(entry_date, user.city)
            env_parts = []
            if wstr:
                env_parts.append(wstr)
            if kstr:
                env_parts.append(kstr)
            if env_parts:
                lines.append(f"   {', '.join(env_parts)}")

    text = "\n".join(lines)
    kb_buttons = []
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(text="< Назад", callback_data=f"history_page_{page - 1}"))
    if (page + 1) * ITEMS_PER_PAGE < (total or 0):
        nav_row.append(InlineKeyboardButton(text="Вперёд >", callback_data=f"history_page_{page + 1}"))
    if nav_row:
        kb_buttons.append(nav_row)
    kb_buttons.append([InlineKeyboardButton(text="В меню", callback_data="main_menu")])

    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_buttons))
    await callback.answer()
