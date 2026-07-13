from datetime import date, datetime, timezone

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select

from bot.database import async_session
from bot.keyboards.main_menu import main_menu_kb
from bot.models.prediction import Prediction
from bot.models.user import User
from bot.services.space_weather import space_weather_service
from bot.services.weather import weather_service
from bot.services.weather import weather_service

router = Router(name="start")


class OnboardingStates(StatesGroup):
    waiting_gender = State()
    waiting_age = State()
    waiting_city = State()


def gender_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Женский", callback_data="gender_female"),
                InlineKeyboardButton(text="Мужской", callback_data="gender_male"),
            ],
            [InlineKeyboardButton(text="Пропустить", callback_data="gender_skip")],
        ]
    )


def skip_kb(prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Пропустить", callback_data=f"{prefix}_skip")]]
    )


async def needs_onboarding(user: User) -> bool:
    return user.city is None


async def get_user(telegram_id: int) -> tuple[User | None, bool]:
    """Returns (user, is_new)."""
    async with async_session() as session:
        user = (await session.scalars(select(User).where(User.telegram_id == telegram_id))).first()
        if user:
            return user, False
        user = User(telegram_id=telegram_id)
        session.add(user)
        await session.commit()
        return user, True


async def get_live_text(user: User) -> str:
    """Fetch live dashboard: prediction if available, else weather + Kp."""
    lines = []

    # Try to get today's prediction
    today = date.today()
    prediction = None
    if user.city and user.latitude:
        async with async_session() as session:
            prediction = (
                await session.scalars(
                    select(Prediction)
                    .where(Prediction.user_id == user.id, Prediction.prediction_date == today)
                )
            ).first()

    if prediction:
        risk_icons = {"low": "низкий", "medium": "средний", "high": "высокий", "very_high": "очень высокий"}
        risk = risk_icons.get(prediction.risk_level, prediction.risk_level)
        lines.append(f"Риск мигрени сегодня: <b>{risk}</b> ({prediction.risk_score:.0%})")
        if prediction.factors:
            lines.append("Причины: " + ", ".join(prediction.factors[:3]))

    # Weather + Kp as supplementary info
    if user.city and user.latitude and user.longitude:
        weather = await weather_service.get_current_weather(user.latitude, user.longitude)
        kp = await space_weather_service.get_daily_kp_summary()

        parts = []
        if weather:
            temp = weather.get("temp_current") or "?"
            feels = weather.get("feels_like")
            cond_str = f", ощущается как {feels}°C" if feels else ""
            parts.append(f"{user.city}: {temp}°C{cond_str}")
        if not weather:
            daily = await weather_service.get_daily_weather(user.city, user.latitude, user.longitude)
            if daily:
                temp = daily.get("temp_avg") or daily.get("temp_max") or "?"
                parts.append(f"{user.city}: ~{temp}°C (ср. за день)")

        if kp:
            kp_val = kp.get("kp_index", "?")
            kp_str = f"Kp: {kp_val:.1f}" if isinstance(kp_val, (int, float)) else f"Kp: {kp_val}"
            if kp.get("geomagnetic_storm"):
                kp_str += " (магнитная буря)"
            parts.append(kp_str)
        if parts:
            lines.append(" | ".join(parts))

    return "\n".join(lines) + "\n\n" if lines else ""


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    user, is_new = await get_user(message.from_user.id)

    if is_new:
        user.username = message.from_user.username
        user.first_name = message.from_user.first_name
        user.last_name = message.from_user.last_name
        async with async_session() as session:
            await session.merge(user)
            await session.commit()

        await state.set_state(OnboardingStates.waiting_gender)
        await message.answer(
            "Привет! Я помогу отслеживать мигрени и находить закономерности.\n\n"
            "Укажи пол (это поможет в анализе, но можно пропустить):",
            reply_markup=gender_kb(),
        )
        return

    if await needs_onboarding(user):
        await state.set_state(OnboardingStates.waiting_gender)
        await message.answer(
            "Давай укажем твой город — это нужно для прогноза погоды и магнитных бурь.\n"
            "Сначала пол (можно пропустить):",
            reply_markup=gender_kb(),
        )
        return

    weather_text = await get_live_text(user)
    await message.answer(
        f"{weather_text}С возвращением, {user.first_name or 'пользователь'}.\n\n"
        "Выбери действие в меню:",
        reply_markup=main_menu_kb(),
    )


@router.callback_query(OnboardingStates.waiting_gender, lambda c: c.data.startswith("gender_"))
async def onboarding_gender(callback: CallbackQuery, state: FSMContext):
    gender = callback.data.replace("gender_", "")
    if gender != "skip":
        async with async_session() as session:
            user = (await session.scalars(select(User).where(User.telegram_id == callback.from_user.id))).first()
            if user:
                user.gender = gender
                await session.commit()

    await state.set_state(OnboardingStates.waiting_age)
    await callback.message.edit_text(
        "Сколько тебе полных лет? (можно пропустить)",
        reply_markup=skip_kb("age"),
    )
    await callback.answer()


@router.callback_query(OnboardingStates.waiting_age, lambda c: c.data == "age_skip")
async def onboarding_age_skip(callback: CallbackQuery, state: FSMContext):
    async with async_session() as session:
        user = (await session.scalars(select(User).where(User.telegram_id == callback.from_user.id))).first()
        if user:
            user.first_name = callback.from_user.first_name
            user.last_name = callback.from_user.last_name
            user.username = callback.from_user.username
            await session.commit()

    await state.set_state(OnboardingStates.waiting_city)
    text = (
        "Введи город и страну для отслеживания погоды и магнитных бурь.\n"
        "(например: Минск, Беларусь или London, UK)\n\n"
        "Город нужен для прогнозов. Без него прогнозы работать не будут."
    )
    await callback.message.edit_text(text, reply_markup=skip_kb("city"))
    await callback.answer()


@router.message(OnboardingStates.waiting_age)
async def onboarding_age(message: Message, state: FSMContext):
    try:
        age = int(message.text.strip())
        if not 5 <= age <= 120:
            raise ValueError
    except ValueError:
        await message.answer("Введи возраст числом от 5 до 120:", reply_markup=skip_kb("age"))
        return

    async with async_session() as session:
        user = (await session.scalars(select(User).where(User.telegram_id == message.from_user.id))).first()
        if user:
            user.age = age
            user.first_name = message.from_user.first_name
            user.last_name = message.from_user.last_name
            user.username = message.from_user.username
            await session.commit()

    await state.set_state(OnboardingStates.waiting_city)
    await message.answer(
        "Город и страна (например: Минск, Беларусь или London, UK):\n\n"
        "Город нужен для прогнозов. Без него прогнозы работать не будут.",
        reply_markup=skip_kb("city"),
    )


@router.callback_query(OnboardingStates.waiting_city, lambda c: c.data == "city_skip")
async def onboarding_city_skip(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "Настройка завершена. Теперь ты можешь записывать мигрени.\n\n"
        "Город можно указать позже в профиле (кнопка Профиль).\n"
        "Без города прогноз погоды и магнитных бурь работать не будет.",
        reply_markup=main_menu_kb(),
    )
    await callback.answer()


@router.message(OnboardingStates.waiting_city)
async def onboarding_city(message: Message, state: FSMContext):
    city = message.text.strip()
    if len(city) < 2:
        await message.answer("Название слишком короткое. Попробуй ещё раз:", reply_markup=skip_kb("city"))
        return

    await message.answer("Определяю координаты и часовой пояс...")
    coords = await weather_service.resolve_city(city)
    tz_offset = None
    if coords:
        tz_offset = await weather_service.resolve_timezone(*coords)

    async with async_session() as session:
        user = (await session.scalars(select(User).where(User.telegram_id == message.from_user.id))).first()
        if user:
            user.city = city
            if coords:
                user.latitude, user.longitude = coords
            if tz_offset is not None:
                user.timezone_offset = tz_offset
            await session.commit()

    await state.clear()
    tz_str = f" (UTC{tz_offset:+d})" if tz_offset is not None else ""
    await message.answer(
        f"Город: <b>{city}</b>{tz_str}. Настройка завершена!\n\n"
        "Теперь записывай мигрени, а я помогу с анализом.",
        reply_markup=main_menu_kb(),
    )


@router.callback_query(lambda c: c.data == "main_menu")
async def back_to_main(callback: CallbackQuery):
    async with async_session() as session:
        user = (await session.scalars(select(User).where(User.telegram_id == callback.from_user.id))).first()
    weather_text = await get_live_text(user) if user else ""
    await callback.message.edit_text(
        f"{weather_text}Главное меню:",
        reply_markup=main_menu_kb(),
    )
    await callback.answer()


@router.callback_query(lambda c: c.data == "help")
async def cmd_help(callback: CallbackQuery):
    text = (
        "<b>Помощь</b>\n\n"
        "Выбери раздел:"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Как пользоваться", callback_data="help_usage")],
            [InlineKeyboardButton(text="Как это работает", callback_data="help_how")],
            [InlineKeyboardButton(text="Приватность и данные", callback_data="help_privacy")],
            [InlineKeyboardButton(text="Назад", callback_data="main_menu")],
        ]
    )
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


@router.callback_query(lambda c: c.data == "help_usage")
async def help_usage(callback: CallbackQuery):
    text = (
        "<b>Как пользоваться</b>\n\n"
        "<b>Запись мигрени</b>\n"
        "Кнопка «Записать приступ» или команда /log — пошаговый опрос: "
        "интенсивность (0-10), длительность, сторона, тип боли, аура, "
        "тошнота, чувствительность к свету/звуку, стресс, сон, триггеры, "
        "лекарства и заметки.\n\n"
        "<b>Ежедневный чекин</b>\n"
        "Команда /check — быстрая отметка «есть мигрень» или «нет». "
        "Важно отмечаться каждый день, даже если голова не болит — "
        "это нужно для точного анализа.\n\n"
        "<b>Напоминания</b>\n"
        "В профиле можно включить ежедневное напоминание в удобное время. "
        "Бот пришлёт сообщение с кнопками Да/Нет. Часовой пояс "
        "определяется автоматически по городу.\n\n"
        "<b>Прогноз</b>\n"
        "Анализирует погоду, магнитные бури и твою историю мигреней. "
        "Показывает риск на ближайшие дни. Доступен после накопления "
        "нескольких записей.\n\n"
        "<b>Цикл</b>\n"
        "Доступен при женском поле. Команды /cycle_start и /cycle_end "
        "для отметки фаз цикла. Помогает найти связь с мигренями.\n\n"
        "<b>Команды</b>\n"
        "/start — главное меню\n"
        "/log — записать приступ\n"
        "/check — ежедневный чекин\n"
        "/stats — статистика\n"
        "/predict — прогноз"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Назад к справке", callback_data="help")]]
    )
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


@router.callback_query(lambda c: c.data == "help_how")
async def help_how(callback: CallbackQuery):
    text = (
        "<b>Как это работает</b>\n\n"
        "Бот собирает три типа данных для анализа:\n\n"
        "1. <b>Твои записи</b> (ты сам решаешь, когда и что "
        "записывать):\n"
        "— Интенсивность, длительность, тип боли, сторона\n"
        "— Триггеры, лекарства, их эффективность\n"
        "— Аура, тошнота, чувствительность к свету/звуку\n"
        "— Стресс, сон, заметки\n\n"
        "2. <b>Погода</b> (автоматически):\n"
        "— Текущая температура, давление, влажность\n"
        "— Ветер, облачность, осадки\n"
        "— Источник: Open-Meteo (Норвежский метеоинститут)\n\n"
        "3. <b>Космическая погода</b> (автоматически):\n"
        "— Kp-индекс магнитных бурь\n"
        "— Скорость и плотность солнечного ветра, Bz-компонента\n"
        "— Штормовые предупреждения (G1–G5)\n"
        "— Источник: NOAA (США)\n\n"
        "Данные сопоставляются по дням и отправляются в "
        "нейросеть DeepSeek для поиска закономерностей. "
        "На выходе — прогноз риска на ближайшие дни.\n\n"
        "<b>Обязательно:</b> город (для погоды и Kp)\n"
        "<b>Опционально:</b> пол, возраст, цикл, записи приступов\n\n"
        "<b>Важно:</b> отмечайся каждый день — и когда болит, "
        "и когда нет. Только так бот отличит реальные триггеры "
        "от случайных совпадений."
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Назад к справке", callback_data="help")]]
    )
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


@router.callback_query(lambda c: c.data == "help_privacy")
async def help_privacy(callback: CallbackQuery):
    text = (
        "<b>Приватность и данные</b>\n\n"
        "<b>Какие данные собираем и зачем:</b>\n"
        "— <b>Telegram ID</b> (обязательно) — для связи с тобой\n"
        "— <b>Город</b> (обязательно для прогнозов) — "
        "чтобы получать погоду и магнитные бури в твоём регионе\n"
        "— <b>Пол и возраст</b> (опционально) — "
        "повышают точность анализа DeepSeek\n"
        "— <b>Записи приступов</b> (опционально, ты сам решаешь) "
        "— твоя история мигреней\n"
        "— <b>Данные цикла</b> (опционально, только для женщин) "
        "— поиск связи цикла с мигренями\n\n"
        "<b>Что передаётся в DeepSeek:</b>\n"
        "Только обезличенные данные (без имени, ID, адреса):\n"
        "— Пол и возраст (если указаны)\n"
        "— Интенсивность и длительность приступов\n"
        "— Погода и Kp-индекс по дням\n"
        "— Отметки «была мигрень / не было»\n\n"
        "Никакие персональные данные (имя, username, "
        "точное местоположение) <b>не передаются</b> третьим "
        "сторонам.\n\n"
        "<b>Что будет, если не указывать данные:</b>\n"
        "— Без города — нет прогнозов и уведомлений\n"
        "— Без пола/возраста — прогнозы работают, "
        "но без демографической поправки\n"
        "— Без записей приступов — нечему анализировать\n\n"
        "<b>Юридически:</b>\n"
        "Сервис не является медицинским изделием. "
        "Прогнозы носят ознакомительный характер и "
        "не заменяют консультацию врача.\n\n"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Назад к справке", callback_data="help")]]
    )
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()
