from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from bot.database import async_session
from bot.keyboards.main_menu import cancel_kb, main_menu_kb
from bot.models.user import User
from bot.services.weather import weather_service

router = Router(name="profile")


class ProfileStates(StatesGroup):
    waiting_city = State()
    waiting_gender = State()
    waiting_age = State()
    waiting_reminder_hour = State()


def profile_menu_kb(user: User):
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    reminder_status = "вкл" if user.reminder_enabled else "выкл"
    prediction_status = "вкл" if user.prediction_enabled else "выкл"
    gender_display = {"female": "Женский", "male": "Мужской"}.get(user.gender or "", "не указан")
    age_display = str(user.age) if user.age else "не указан"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"Пол: {gender_display}", callback_data="profile_set_gender")],
            [InlineKeyboardButton(text=f"Возраст: {age_display}", callback_data="profile_set_age")],
            [InlineKeyboardButton(text=f"Город: {user.city or 'не указан'}", callback_data="profile_set_city")],
            [InlineKeyboardButton(text=f"Напоминания: {reminder_status}", callback_data="profile_toggle_reminder")],
            [InlineKeyboardButton(text=f"Прогнозы: {prediction_status}", callback_data="profile_toggle_prediction")],
            [InlineKeyboardButton(text="Назад", callback_data="main_menu")],
        ]
    )


async def get_user(telegram_id: int) -> User | None:
    async with async_session() as session:
        return (await session.scalars(select(User).where(User.telegram_id == telegram_id))).first()


@router.callback_query(lambda c: c.data == "profile_menu")
async def profile_menu(callback: CallbackQuery):
    user = await get_user(callback.from_user.id)
    if not user:
        await callback.answer("Пользователь не найден, введи /start")
        return

    await callback.message.edit_text(
        "<b>Настройки профиля</b>\n\n"
        "Город обязателен для прогнозов погоды и магнитных бурь.\n"
        "Пол и возраст опциональны — они помогают улучшить точность анализа.",
        reply_markup=profile_menu_kb(user),
    )
    await callback.answer()


@router.callback_query(lambda c: c.data == "profile_set_gender")
async def profile_set_gender(callback: CallbackQuery, state: FSMContext):
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    await state.set_state(ProfileStates.waiting_gender)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Женский", callback_data="profile_gender_female"),
                InlineKeyboardButton(text="Мужской", callback_data="profile_gender_male"),
            ],
            [InlineKeyboardButton(text="Отмена", callback_data="profile_menu")],
        ]
    )
    await callback.message.edit_text("Выбери пол:", reply_markup=kb)
    await callback.answer()


@router.callback_query(ProfileStates.waiting_gender, F.data.startswith("profile_gender_"))
async def profile_gender_set(callback: CallbackQuery, state: FSMContext):
    gender = callback.data.replace("profile_gender_", "")
    async with async_session() as session:
        user = (await session.scalars(select(User).where(User.telegram_id == callback.from_user.id))).first()
        if user:
            user.gender = gender
            await session.commit()
    await state.clear()
    await callback.message.edit_text("<b>Настройки профиля</b>", reply_markup=profile_menu_kb(user))
    await callback.answer("Пол обновлён")


@router.callback_query(lambda c: c.data == "profile_set_age")
async def profile_set_age(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ProfileStates.waiting_age)
    await callback.message.edit_text(
        "Введи возраст (число от 5 до 120):",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


@router.message(ProfileStates.waiting_age)
async def profile_age_received(message: Message, state: FSMContext):
    try:
        age = int(message.text.strip())
        if not 5 <= age <= 120:
            raise ValueError
    except ValueError:
        await message.answer("Введи возраст числом от 5 до 120:", reply_markup=cancel_kb())
        return

    async with async_session() as session:
        user = (await session.scalars(select(User).where(User.telegram_id == message.from_user.id))).first()
        if user:
            user.age = age
            await session.commit()

    await state.clear()
    await message.answer("Возраст обновлён.", reply_markup=main_menu_kb())


@router.callback_query(lambda c: c.data == "profile_set_city")
async def profile_set_city(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ProfileStates.waiting_city)
    await callback.message.edit_text(
        "Введи город и страну (например: Минск, Беларусь или London, UK):",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


@router.message(ProfileStates.waiting_city)
async def profile_city_received(message: Message, state: FSMContext):
    city = message.text.strip()
    if len(city) < 2:
        await message.answer("Название города слишком короткое. Попробуй ещё раз:", reply_markup=cancel_kb())
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
    await message.answer(f"Город сохранён: <b>{city}</b>{tz_str}.", reply_markup=main_menu_kb())


@router.callback_query(lambda c: c.data == "profile_toggle_reminder")
async def profile_toggle_reminder(callback: CallbackQuery, state: FSMContext):
    async with async_session() as session:
        user = (await session.scalars(select(User).where(User.telegram_id == callback.from_user.id))).first()
        if user and user.reminder_enabled:
            user.reminder_enabled = False
            await session.commit()
            await callback.message.edit_text("<b>Настройки профиля</b>", reply_markup=profile_menu_kb(user))
            await callback.answer("Напоминания выключены")
            return

    await state.set_state(ProfileStates.waiting_reminder_hour)
    await callback.message.edit_text(
        "В какое время присылать напоминание? Введи час (0-23), например: <b>20</b>",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


@router.message(ProfileStates.waiting_reminder_hour)
async def profile_reminder_hour_received(message: Message, state: FSMContext):
    try:
        hour = int(message.text.strip())
        if not 0 <= hour <= 23:
            raise ValueError
    except ValueError:
        await message.answer("Введи число от 0 до 23:", reply_markup=cancel_kb())
        return

    async with async_session() as session:
        user = (await session.scalars(select(User).where(User.telegram_id == message.from_user.id))).first()
        if user:
            user.reminder_enabled = True
            user.reminder_hour = hour
            await session.commit()

    await state.clear()
    await message.answer(f"Напоминание установлено на <b>{hour}:00</b>.", reply_markup=main_menu_kb())


@router.callback_query(lambda c: c.data == "profile_toggle_prediction")
async def profile_toggle_prediction(callback: CallbackQuery):
    async with async_session() as session:
        user = (await session.scalars(select(User).where(User.telegram_id == callback.from_user.id))).first()
        if user:
            user.prediction_enabled = not user.prediction_enabled
            await session.commit()
            status = "включены" if user.prediction_enabled else "выключены"
            await callback.message.edit_text("<b>Настройки профиля</b>", reply_markup=profile_menu_kb(user))
            await callback.answer(f"Прогнозы {status}")
