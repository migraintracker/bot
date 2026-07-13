import uuid
from datetime import date, datetime, timezone

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select

from bot.database import async_session
from bot.keyboards.logging import (
    EFFECTIVENESS,
    MEDICATIONS,
    PAIN_SIDES,
    PAIN_TYPES,
    TRIGGERS,
    duration_kb,
    intensity_kb,
    multi_select_kb,
    single_select_kb,
    skip_kb,
    yes_no_kb,
)
from bot.keyboards.main_menu import main_menu_kb
from bot.models.daily_check import DailyCheck
from bot.models.migraine import MigraineEntry
from bot.models.user import User

router = Router(name="logging")


class LogMigraineStates(StatesGroup):
    waiting_intensity = State()
    waiting_duration = State()
    waiting_duration_custom = State()
    waiting_side = State()
    waiting_pain_type = State()
    waiting_aura = State()
    waiting_nausea = State()
    waiting_light_sensitivity = State()
    waiting_sound_sensitivity = State()
    waiting_sleep = State()
    waiting_stress = State()
    waiting_triggers = State()
    waiting_medications = State()
    waiting_effectiveness = State()
    waiting_notes = State()


async def get_user(telegram_id: int) -> User | None:
    async with async_session() as session:
        return (await session.scalars(select(User).where(User.telegram_id == telegram_id))).first()


@router.message(F.text.lower() == "/log")
async def cmd_log(message: Message, state: FSMContext):
    await state.set_state(LogMigraineStates.waiting_intensity)
    await message.answer(
        "Оцени интенсивность боли по шкале от 0 до 10:\n"
        "0 — нет боли, 1-3 — слабая, 4-6 — умеренная, "
        "7-9 — сильная, 10 — невыносимая",
        reply_markup=intensity_kb(),
    )


@router.callback_query(lambda c: c.data == "log_migraine_start")
async def log_migraine_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(LogMigraineStates.waiting_intensity)
    await callback.message.edit_text(
        "Оцени интенсивность боли по шкале от 0 до 10:\n"
        "0 — нет боли, 1-3 — слабая, 4-6 — умеренная, "
        "7-9 — сильная, 10 — невыносимая",
        reply_markup=intensity_kb(),
    )
    await callback.answer()


@router.callback_query(LogMigraineStates.waiting_intensity, F.data.startswith("intensity_"))
async def intensity_chosen(callback: CallbackQuery, state: FSMContext):
    intensity = int(callback.data.split("_")[1])
    await state.update_data(log_data={"intensity": intensity, "started_at": datetime.now(timezone.utc).isoformat()})
    await state.set_state(LogMigraineStates.waiting_duration)
    await callback.message.edit_text(
        f"Интенсивность: <b>{intensity}/10</b>\n\nСколько длился приступ?",
        reply_markup=duration_kb(),
    )
    await callback.answer()


@router.callback_query(LogMigraineStates.waiting_duration)
async def duration_chosen(callback: CallbackQuery, state: FSMContext):
    if callback.data == "duration_custom":
        await state.set_state(LogMigraineStates.waiting_duration_custom)
        await callback.message.edit_text("Введи длительность в минутах (например: 90):")
        await callback.answer()
        return

    duration = int(callback.data.split("_")[1])
    data = await state.get_data()
    data["log_data"]["duration_minutes"] = duration
    await state.update_data(log_data=data["log_data"])
    await state.set_state(LogMigraineStates.waiting_side)
    await callback.message.edit_text(
        f"Длительность: <b>{duration} мин</b>\n\nС какой стороны болит?",
        reply_markup=single_select_kb(PAIN_SIDES, "side"),
    )
    await callback.answer()


@router.message(LogMigraineStates.waiting_duration_custom)
async def duration_custom_received(message: Message, state: FSMContext):
    try:
        duration = int(message.text.strip())
        if duration <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Введи положительное число минут:", reply_markup=skip_kb("duration"))
        return

    data = await state.get_data()
    data["log_data"]["duration_minutes"] = duration
    await state.update_data(log_data=data["log_data"])
    await state.set_state(LogMigraineStates.waiting_side)
    await message.answer(
        f"Длительность: <b>{duration} мин</b>\n\nС какой стороны болит?",
        reply_markup=single_select_kb(PAIN_SIDES, "side"),
    )


@router.callback_query(LogMigraineStates.waiting_side, F.data.startswith("side_"))
async def side_chosen(callback: CallbackQuery, state: FSMContext):
    value = callback.data.replace("side_", "")
    data = await state.get_data()
    if value != "skip":
        data["log_data"]["side"] = value
    await state.update_data(log_data=data["log_data"])
    await state.set_state(LogMigraineStates.waiting_pain_type)
    await callback.message.edit_text("Тип боли:", reply_markup=single_select_kb(PAIN_TYPES, "paintype"))
    await callback.answer()


@router.callback_query(LogMigraineStates.waiting_pain_type, F.data.startswith("paintype_"))
async def pain_type_chosen(callback: CallbackQuery, state: FSMContext):
    value = callback.data.replace("paintype_", "")
    data = await state.get_data()
    if value != "skip":
        data["log_data"]["pain_type"] = value
    await state.update_data(log_data=data["log_data"])
    await state.set_state(LogMigraineStates.waiting_aura)
    await callback.message.edit_text(
        "Была ли аура перед приступом? (визуальные нарушения, мерцания)",
        reply_markup=yes_no_kb("aura"),
    )
    await callback.answer()


@router.callback_query(LogMigraineStates.waiting_aura, F.data.startswith("aura_"))
async def aura_chosen(callback: CallbackQuery, state: FSMContext):
    value = callback.data.replace("aura_", "")
    data = await state.get_data()
    if value == "yes":
        data["log_data"]["aura"] = True
    elif value == "no":
        data["log_data"]["aura"] = False
    await state.update_data(log_data=data["log_data"])
    await state.set_state(LogMigraineStates.waiting_nausea)
    await callback.message.edit_text("Тошнота?", reply_markup=yes_no_kb("nausea"))
    await callback.answer()


@router.callback_query(LogMigraineStates.waiting_nausea, F.data.startswith("nausea_"))
async def nausea_chosen(callback: CallbackQuery, state: FSMContext):
    value = callback.data.replace("nausea_", "")
    data = await state.get_data()
    if value == "yes":
        data["log_data"]["nausea"] = True
    elif value == "no":
        data["log_data"]["nausea"] = False
    await state.update_data(log_data=data["log_data"])
    await state.set_state(LogMigraineStates.waiting_light_sensitivity)
    await callback.message.edit_text("Чувствительность к свету?", reply_markup=yes_no_kb("light"))
    await callback.answer()


@router.callback_query(LogMigraineStates.waiting_light_sensitivity, F.data.startswith("light_"))
async def light_chosen(callback: CallbackQuery, state: FSMContext):
    value = callback.data.replace("light_", "")
    data = await state.get_data()
    if value == "yes":
        data["log_data"]["light_sensitivity"] = True
    elif value == "no":
        data["log_data"]["light_sensitivity"] = False
    await state.update_data(log_data=data["log_data"])
    await state.set_state(LogMigraineStates.waiting_sound_sensitivity)
    await callback.message.edit_text("Чувствительность к звуку?", reply_markup=yes_no_kb("sound"))
    await callback.answer()


@router.callback_query(LogMigraineStates.waiting_sound_sensitivity, F.data.startswith("sound_"))
async def sound_chosen(callback: CallbackQuery, state: FSMContext):
    value = callback.data.replace("sound_", "")
    data = await state.get_data()
    if value == "yes":
        data["log_data"]["sound_sensitivity"] = True
    elif value == "no":
        data["log_data"]["sound_sensitivity"] = False
    await state.update_data(log_data=data["log_data"])
    await state.set_state(LogMigraineStates.waiting_stress)
    await callback.message.edit_text(
        "Уровень стресса (0-10):\n0 — спокоен, 10 — максимальный стресс",
        reply_markup=intensity_kb(),
    )
    await callback.answer()


@router.callback_query(LogMigraineStates.waiting_stress, F.data.startswith("intensity_"))
async def stress_chosen(callback: CallbackQuery, state: FSMContext):
    stress = int(callback.data.split("_")[1])
    data = await state.get_data()
    data["log_data"]["stress_level"] = stress
    await state.update_data(log_data=data["log_data"])
    await state.set_state(LogMigraineStates.waiting_sleep)
    await callback.message.edit_text(
        "Сколько часов сна прошлой ночью?\nВведи число (например: <b>7.5</b>):",
        reply_markup=skip_kb("sleep"),
    )
    await callback.answer()


@router.callback_query(LogMigraineStates.waiting_sleep, F.data == "sleep_skip")
async def sleep_skip(callback: CallbackQuery, state: FSMContext):
    await _ask_triggers(callback, state)


@router.message(LogMigraineStates.waiting_sleep)
async def sleep_received(message: Message, state: FSMContext):
    try:
        hours = float(message.text.strip().replace(",", "."))
        if hours < 0 or hours > 24:
            raise ValueError
    except ValueError:
        await message.answer("Введи число от 0 до 24:", reply_markup=skip_kb("sleep"))
        return

    data = await state.get_data()
    data["log_data"]["sleep_hours"] = hours
    await state.update_data(log_data=data["log_data"])
    await _ask_triggers(message, state)


async def _ask_triggers(event: Message | CallbackQuery, state: FSMContext):
    await state.set_state(LogMigraineStates.waiting_triggers)
    text = "Какие триггеры могли вызвать приступ? (можно выбрать несколько)"
    if isinstance(event, CallbackQuery):
        await event.message.edit_text(text, reply_markup=multi_select_kb(TRIGGERS, "triggers"))
        await event.answer()
    else:
        await event.answer(text, reply_markup=multi_select_kb(TRIGGERS, "triggers"))


@router.callback_query(LogMigraineStates.waiting_triggers, F.data.startswith("triggers_toggle_"))
async def triggers_toggle(callback: CallbackQuery, state: FSMContext):
    idx = int(callback.data.split("_")[-1])
    data = await state.get_data()
    log_data = data.get("log_data", {})
    selected = list(log_data.get("_triggers_selected", []))
    if idx in selected:
        selected.remove(idx)
    else:
        selected.append(idx)
    log_data["_triggers_selected"] = selected
    await state.update_data(log_data=log_data)
    await callback.message.edit_reply_markup(reply_markup=multi_select_kb(TRIGGERS, "triggers", set(selected)))
    await callback.answer()


@router.callback_query(LogMigraineStates.waiting_triggers, F.data == "triggers_done")
async def triggers_done(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    log_data = data["log_data"]
    selected = log_data.pop("_triggers_selected", [])
    log_data["triggers"] = [TRIGGERS[i] for i in selected] if selected else None
    await state.update_data(log_data=log_data)
    await state.set_state(LogMigraineStates.waiting_medications)
    await callback.message.edit_text(
        "Какие лекарства принимались? (можно выбрать несколько)",
        reply_markup=multi_select_kb(MEDICATIONS, "meds"),
    )
    await callback.answer()


@router.callback_query(LogMigraineStates.waiting_medications, F.data.startswith("meds_toggle_"))
async def meds_toggle(callback: CallbackQuery, state: FSMContext):
    idx = int(callback.data.split("_")[-1])
    data = await state.get_data()
    log_data = data.get("log_data", {})
    selected = list(log_data.get("_meds_selected", []))
    if idx in selected:
        selected.remove(idx)
    else:
        selected.append(idx)
    log_data["_meds_selected"] = selected
    await state.update_data(log_data=log_data)
    await callback.message.edit_reply_markup(reply_markup=multi_select_kb(MEDICATIONS, "meds", set(selected)))
    await callback.answer()


@router.callback_query(LogMigraineStates.waiting_medications, F.data == "meds_done")
async def meds_done(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    log_data = data["log_data"]
    selected = log_data.pop("_meds_selected", [])
    log_data["medications"] = [MEDICATIONS[i] for i in selected] if selected else None
    await state.update_data(log_data=log_data)
    await state.set_state(LogMigraineStates.waiting_effectiveness)
    await callback.message.edit_text(
        "Насколько помогли лекарства?",
        reply_markup=single_select_kb(EFFECTIVENESS, "eff"),
    )
    await callback.answer()


@router.callback_query(LogMigraineStates.waiting_effectiveness, F.data.startswith("eff_"))
async def eff_chosen(callback: CallbackQuery, state: FSMContext):
    value = callback.data.replace("eff_", "")
    data = await state.get_data()
    if value != "skip":
        data["log_data"]["medication_effectiveness"] = value
    await state.update_data(log_data=data["log_data"])
    await state.set_state(LogMigraineStates.waiting_notes)
    await callback.message.edit_text(
        "Добавь заметку (или нажми «Пропустить»):\n"
        "Например: что предшествовало, что помогало, любые наблюдения.",
        reply_markup=skip_kb("notes"),
    )
    await callback.answer()


@router.callback_query(LogMigraineStates.waiting_notes, F.data == "notes_skip")
async def notes_skip(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    data["log_data"]["notes"] = None
    await state.update_data(log_data=data["log_data"])
    await _save_and_finish(callback, state)


@router.message(LogMigraineStates.waiting_notes)
async def notes_received(message: Message, state: FSMContext):
    data = await state.get_data()
    data["log_data"]["notes"] = message.text.strip() if message.text.strip() else None
    await state.update_data(log_data=data["log_data"])
    await _save_and_finish(message, state)


async def _save_and_finish(event: Message | CallbackQuery, state: FSMContext):
    data = await state.get_data()
    log_data = data["log_data"]

    telegram_id = event.from_user.id

    async with async_session() as session:
        user = (await session.scalars(select(User).where(User.telegram_id == telegram_id))).first()

        entry = MigraineEntry(
            user_id=user.id,
            intensity=log_data["intensity"],
            started_at=datetime.fromisoformat(log_data["started_at"]),
            ended_at=datetime.now(timezone.utc),
            duration_minutes=log_data.get("duration_minutes"),
            side=log_data.get("side"),
            pain_type=log_data.get("pain_type"),
            aura=log_data.get("aura"),
            nausea=log_data.get("nausea"),
            light_sensitivity=log_data.get("light_sensitivity"),
            sound_sensitivity=log_data.get("sound_sensitivity"),
            sleep_hours=log_data.get("sleep_hours"),
            stress_level=log_data.get("stress_level"),
            triggers=log_data.get("triggers"),
            medications=log_data.get("medications"),
            medication_effectiveness=log_data.get("medication_effectiveness"),
            notes=log_data.get("notes"),
        )
        session.add(entry)
        await session.commit()

        existing_check = (
            await session.scalars(
                select(DailyCheck).where(
                    DailyCheck.user_id == user.id,
                    DailyCheck.check_date == date.today(),
                )
            )
        ).first()
        if not existing_check:
            check = DailyCheck(user_id=user.id, check_date=date.today(), has_migraine=True)
            session.add(check)
            await session.commit()

    await state.clear()

    summary = _format_summary(log_data)
    if isinstance(event, CallbackQuery):
        await event.message.edit_text(summary, reply_markup=main_menu_kb())
        await event.answer("Запись сохранена")
    else:
        await event.answer(summary, reply_markup=main_menu_kb())


def _format_summary(log_data: dict) -> str:
    lines = ["<b>Запись сохранена</b>\n"]
    lines.append(f"Интенсивность: <b>{log_data['intensity']}/10</b>")
    if log_data.get("duration_minutes"):
        h = log_data["duration_minutes"] // 60
        m = log_data["duration_minutes"] % 60
        dur = f"{h} ч {m} мин" if h else f"{m} мин"
        lines.append(f"Длительность: <b>{dur}</b>")
    if log_data.get("side"):
        lines.append(f"Сторона: <b>{log_data['side']}</b>")
    if log_data.get("pain_type"):
        lines.append(f"Тип: <b>{log_data['pain_type']}</b>")
    if log_data.get("aura") is True:
        lines.append("Была аура")
    if log_data.get("nausea") is True:
        lines.append("Тошнота")
    if log_data.get("light_sensitivity") is True:
        lines.append("Светочувствительность")
    if log_data.get("sound_sensitivity") is True:
        lines.append("Звукочувствительность")
    if log_data.get("stress_level") is not None:
        lines.append(f"Стресс: <b>{log_data['stress_level']}/10</b>")
    if log_data.get("sleep_hours") is not None:
        lines.append(f"Сон: <b>{log_data['sleep_hours']} ч</b>")
    if log_data.get("triggers"):
        lines.append(f"Триггеры: <b>{', '.join(log_data['triggers'])}</b>")
    if log_data.get("medications"):
        lines.append(f"Лекарства: <b>{', '.join(log_data['medications'])}</b>")
    if log_data.get("medication_effectiveness"):
        lines.append(f"Эффективность: <b>{log_data['medication_effectiveness']}</b>")
    if log_data.get("notes"):
        lines.append(f"\nЗаметка: {log_data['notes']}")

    return "\n".join(lines)


def daily_check_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Да, болит", callback_data="dailycheck_yes"),
                InlineKeyboardButton(text="Нет, всё хорошо", callback_data="dailycheck_no"),
            ],
            [InlineKeyboardButton(text="Позже", callback_data="main_menu")],
        ]
    )


@router.message(F.text.lower() == "/check")
async def cmd_daily_check(message: Message):
    await message.answer(
        "Была ли сегодня мигрень?",
        reply_markup=daily_check_kb(),
    )


@router.callback_query(lambda c: c.data == "dailycheck_yes")
async def daily_check_yes(callback: CallbackQuery, state: FSMContext):
    await log_migraine_start(callback, state)
    await callback.answer()


@router.callback_query(lambda c: c.data == "dailycheck_no")
async def daily_check_no(callback: CallbackQuery):
    async with async_session() as session:
        user = (await session.scalars(select(User).where(User.telegram_id == callback.from_user.id))).first()
        if not user:
            await callback.answer("Пользователь не найден")
            return

        existing = (
            await session.scalars(
                select(DailyCheck).where(
                    DailyCheck.user_id == user.id,
                    DailyCheck.check_date == date.today(),
                )
            )
        ).first()

        if not existing:
            check = DailyCheck(user_id=user.id, check_date=date.today(), has_migraine=False)
            session.add(check)
            await session.commit()

    await callback.message.edit_text(
        "Отмечено: сегодня без мигрени. Хорошего дня.",
        reply_markup=main_menu_kb(),
    )
    await callback.answer()
