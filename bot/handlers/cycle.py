import uuid
from datetime import date, datetime, timezone

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import desc, select

from bot.database import async_session
from bot.keyboards.main_menu import cancel_kb, main_menu_kb
from bot.models.cycle import CycleEntry
from bot.models.user import User

router = Router(name="cycle")

PHASES = ["Менструация", "Фолликулярная", "Овуляция", "Лютеиновая", "Не знаю"]


class CycleStates(StatesGroup):
    waiting_phase = State()
    waiting_symptoms = State()


@router.message(F.text.lower() == "/cycle_start")
async def cycle_start(message: Message, state: FSMContext):
    async with async_session() as session:
        user = (await session.scalars(select(User).where(User.telegram_id == message.from_user.id))).first()
        if not user:
            await message.answer("Пользователь не найден, введи /start")
            return
        if user.gender != "female":
            await message.answer("Этот раздел доступен для женского пола.")
            return

    await state.set_state(CycleStates.waiting_phase)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=p, callback_data=f"cyclephase_{p}") for p in PHASES[:3]],
            [InlineKeyboardButton(text=p, callback_data=f"cyclephase_{p}") for p in PHASES[3:]],
            [InlineKeyboardButton(text="Отмена", callback_data="main_menu")],
        ]
    )
    await message.answer("Отмечаем начало цикла. В какой фазе ты сейчас?", reply_markup=kb)


@router.callback_query(CycleStates.waiting_phase, F.data.startswith("cyclephase_"))
async def cycle_phase_chosen(callback: CallbackQuery, state: FSMContext):
    phase = callback.data.replace("cyclephase_", "")
    await state.update_data(cycle_phase=phase)
    await state.set_state(CycleStates.waiting_symptoms)
    await callback.message.edit_text(
        "Есть ли дополнительные симптомы? Напиши текстом или нажми «Пропустить».",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


@router.message(CycleStates.waiting_symptoms)
async def cycle_symptoms_received(message: Message, state: FSMContext):
    symptoms = message.text.strip() if message.text.strip() else None
    data = await state.get_data()

    async with async_session() as session:
        user = (await session.scalars(select(User).where(User.telegram_id == message.from_user.id))).first()
        if not user:
            await message.answer("Пользователь не найден, введи /start")
            return

        entry = CycleEntry(
            user_id=user.id,
            entry_date=date.today(),
            phase=data.get("cycle_phase"),
            period_start=True,
            symptoms=symptoms,
        )
        session.add(entry)
        await session.commit()

    await state.clear()
    await message.answer(
        f"Начало цикла отмечено.\nФаза: <b>{data.get('cycle_phase', '--')}</b>",
        reply_markup=main_menu_kb(),
    )


@router.message(F.text.lower() == "/cycle_end")
async def cycle_end(message: Message):
    async with async_session() as session:
        user = (await session.scalars(select(User).where(User.telegram_id == message.from_user.id))).first()
        if not user:
            await message.answer("Пользователь не найден, введи /start")
            return
        if user.gender != "female":
            await message.answer("Этот раздел доступен для женского пола.")
            return

        entry = CycleEntry(
            user_id=user.id,
            entry_date=date.today(),
            period_end=True,
        )
        session.add(entry)
        await session.commit()

    await message.answer("Конец цикла отмечен.", reply_markup=main_menu_kb())


@router.message(F.text.lower() == "/cycle")
async def cycle_list(message: Message):
    async with async_session() as session:
        user = (await session.scalars(select(User).where(User.telegram_id == message.from_user.id))).first()
        if not user:
            await message.answer("Пользователь не найден, введи /start")
            return
        if user.gender != "female":
            await message.answer("Этот раздел доступен для женского пола.")
            return

        entries = (
            (await session.scalars(
                select(CycleEntry)
                .where(CycleEntry.user_id == user.id)
                .order_by(desc(CycleEntry.entry_date))
                .limit(10)
            ))
            .all()
        )

    if not entries:
        await message.answer(
            "<b>История цикла пуста</b>\n\nИспользуй /cycle_start чтобы отметить начало цикла.",
            reply_markup=main_menu_kb(),
        )
        return

    lines = ["<b>Последние записи цикла</b>\n"]
    for e in entries:
        tag = "Начало" if e.period_start else "Конец" if e.period_end else "--"
        phase_str = f" -- {e.phase}" if e.phase else ""
        lines.append(f"{tag} {e.entry_date.strftime('%d.%m.%Y')}{phase_str}")

    await message.answer("\n".join(lines), reply_markup=main_menu_kb())
