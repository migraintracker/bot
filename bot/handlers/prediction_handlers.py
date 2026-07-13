from datetime import datetime, timezone

from aiogram import Router
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import func, select

from bot.database import async_session
from bot.keyboards.main_menu import main_menu_kb
from bot.models.migraine import MigraineEntry
from bot.models.prediction import Prediction
from bot.models.user import User
from bot.services.prediction import generate_prediction_for_user

router = Router(name="prediction")


@router.callback_query(lambda c: c.data == "prediction_menu")
async def prediction_menu(callback: CallbackQuery):
    async with async_session() as session:
        user = (await session.scalars(select(User).where(User.telegram_id == callback.from_user.id))).first()
        if not user:
            await callback.answer("Пользователь не найден")
            return

        predictions = (
            (await session.scalars(
                select(Prediction)
                .where(Prediction.user_id == user.id)
                .order_by(Prediction.prediction_date.asc())
                .limit(7)
            ))
            .all()
        )

        entry_count = (
            await session.scalars(
                select(func.count(MigraineEntry.id)).where(MigraineEntry.user_id == user.id)
            )
        )

    if predictions:
        lines = ["<b>Прогноз на неделю</b>\n"]
        risk_text = {
            "low": "Низкий",
            "medium": "Средний",
            "high": "Высокий",
            "very_high": "Очень высокий",
        }

        for p in predictions:
            rtext = risk_text.get(p.risk_level, p.risk_level)
            lines.append(f"<b>{p.prediction_date.strftime('%d.%m')}</b> -- {rtext} ({p.risk_score:.0%})")

        lines.append("\nПрогноз носит ознакомительный характер. При симптомах -- к врачу.")

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Скачать календарь", callback_data="prediction_download_cal")],
                [InlineKeyboardButton(text="В меню", callback_data="main_menu")],
            ]
        )
        await callback.message.edit_text("\n".join(lines), reply_markup=kb)
        await callback.answer()
        return

    # No predictions yet -- figure out why
    missing = []
    if not user.city:
        missing.append("Указать город в профиле")
    if not entry_count:
        missing.append("Записать хотя бы несколько мигреней (/log)")

    if missing:
        text = (
            "<b>Прогноз мигреней</b>\n\n"
            "Пока не хватает данных. Нужно:\n"
            + "\n".join(f"-- {m}" for m in missing)
            + "\n\nПрогноз носит ознакомительный характер."
        )
        await callback.message.edit_text(text, reply_markup=main_menu_kb())
        await callback.answer()
        return

    # Has city AND entries, just no predictions generated yet
    await callback.message.edit_text(
        "<b>Прогноз мигреней</b>\n\n"
        "Данные собраны, но прогноз ещё не сгенерирован.\n"
        "Обычно это происходит раз в сутки автоматически.\n\n"
        "Хочешь запустить генерацию сейчас?",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Сгенерировать прогноз", callback_data="prediction_generate_now")],
                [InlineKeyboardButton(text="В меню", callback_data="main_menu")],
            ]
        ),
    )
    await callback.answer()


@router.callback_query(lambda c: c.data == "prediction_generate_now")
async def prediction_generate_now(callback: CallbackQuery):
    await callback.message.edit_text("Анализирую данные и погоду, это может занять до минуты...")

    async with async_session() as session:
        user = (await session.scalars(select(User).where(User.telegram_id == callback.from_user.id))).first()

    try:
        await generate_prediction_for_user(user.id)
    except Exception as e:
        await callback.message.edit_text(
            f"Не удалось сгенерировать прогноз. Попробуй позже.\n\n"
            "Возможные причины: не указан город, нет записей мигреней, "
            "или сервис погоды временно недоступен.",
            reply_markup=main_menu_kb(),
        )
        await callback.answer()
        return

    # Reload and show
    async with async_session() as session:
        predictions = (
            (await session.scalars(
                select(Prediction)
                .where(Prediction.user_id == user.id)
                .order_by(Prediction.prediction_date.asc())
                .limit(7)
            ))
            .all()
        )

    if not predictions:
        await callback.message.edit_text(
            "Прогноз пока не удалось сформировать. "
            "Убедись что указан город и есть записи мигреней.",
            reply_markup=main_menu_kb(),
        )
        await callback.answer()
        return

    lines = ["<b>Прогноз на неделю</b>\n"]
    risk_text = {
        "low": "Низкий",
        "medium": "Средний",
        "high": "Высокий",
        "very_high": "Очень высокий",
    }

    for p in predictions:
        rtext = risk_text.get(p.risk_level, p.risk_level)
        lines.append(f"<b>{p.prediction_date.strftime('%d.%m')}</b> -- {rtext} ({p.risk_score:.0%})")

    lines.append("\nПрогноз носит ознакомительный характер. При симптомах -- к врачу.")

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Скачать календарь", callback_data="prediction_download_cal")],
            [InlineKeyboardButton(text="В меню", callback_data="main_menu")],
        ]
    )
    await callback.message.edit_text("\n".join(lines), reply_markup=kb)
    await callback.answer()


@router.callback_query(lambda c: c.data == "cycle_menu")
async def cycle_menu(callback: CallbackQuery):
    async with async_session() as session:
        user = (await session.scalars(select(User).where(User.telegram_id == callback.from_user.id))).first()
        if not user:
            await callback.answer("Пользователь не найден")
            return

        show_cycle = user.gender == "female"

    if show_cycle:
        text = (
            "<b>Отслеживание цикла</b>\n\n"
            "Отмечай начало и конец менструального цикла, фазы и симптомы. "
            "Эти данные помогут найти корреляции с мигренями.\n\n"
            "Команды:\n"
            "/cycle_start -- отметить начало цикла\n"
            "/cycle_end -- отметить конец цикла\n"
            "/cycle -- история цикла"
        )
    else:
        text = (
            "<b>Отслеживание цикла</b>\n\n"
            "Этот раздел доступен для женского пола. "
            "Ты можешь изменить пол в настройках профиля."
        )

    await callback.message.edit_text(text, reply_markup=main_menu_kb())
    await callback.answer()


@router.callback_query(lambda c: c.data == "prediction_download_cal")
async def prediction_download_cal(callback: CallbackQuery):
    async with async_session() as session:
        user = (await session.scalars(select(User).where(User.telegram_id == callback.from_user.id))).first()
        if not user:
            await callback.answer("Пользователь не найден")
            return

        predictions = (
            (await session.scalars(
                select(Prediction)
                .where(Prediction.user_id == user.id)
                .order_by(Prediction.prediction_date.asc())
                .limit(30)
            ))
            .all()
        )

    if not predictions:
        await callback.answer("Нет прогнозов для экспорта")
        return

    ics = _generate_ics(predictions)
    await callback.message.answer_document(
        BufferedInputFile(ics.encode("utf-8"), filename="migraine_forecast.ics"),
        caption="Календарь прогнозов. Импортируй в Google/Apple Calendar.",
    )
    await callback.answer("Календарь отправлен")


def _generate_ics(predictions: list[Prediction]) -> str:
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    risk_labels = {"low": "Low", "medium": "Medium", "high": "High", "very_high": "Very High"}

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//MigraineTrackerBot//RU",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]

    for p in predictions:
        dt = p.prediction_date.strftime("%Y%m%d")
        risk = risk_labels.get(p.risk_level, p.risk_level)
        summary = f"Migraine: {risk} ({p.risk_score:.0%})"
        factors = "; ".join(p.factors or [])
        desc = f"Risk: {p.risk_score:.0%}. Factors: {factors}"

        lines.append("BEGIN:VEVENT")
        lines.append(f"DTSTART;VALUE=DATE:{dt}")
        lines.append(f"DTEND;VALUE=DATE:{dt}")
        lines.append(f"DTSTAMP:{now}")
        lines.append(f"SUMMARY:{summary}")
        lines.append(f"DESCRIPTION:{desc}")
        lines.append("TRANSP:TRANSPARENT")
        lines.append("END:VEVENT")

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines)
