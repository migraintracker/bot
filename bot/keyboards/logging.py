from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

TRIGGERS = [
    "Стресс", "Недосып", "Пересып", "Голод", "Алкоголь",
    "Кофеин", "Шоколад", "Сыр", "Яркий свет", "Громкий звук",
    "Запахи", "Погода", "Экран", "Менструация", "Другое",
]

MEDICATIONS = [
    "Ибупрофен", "Парацетамол", "Аспирин", "Триптаны",
    "Напроксен", "Кеторолак", "Без лекарств", "Другое",
]

PAIN_SIDES = ["Левая", "Правая", "Обе стороны", "В центре"]

PAIN_TYPES = ["Пульсирующая", "Давящая", "Острая", "Тупая"]

EFFECTIVENESS = ["Помогло", "Частично", "Не помогло"]


def intensity_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for i in range(0, 11):
        builder.button(text=str(i), callback_data=f"intensity_{i}")
    builder.button(text="Отмена", callback_data="main_menu")
    builder.adjust(5)
    return builder.as_markup()


def yes_no_kb(prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Да", callback_data=f"{prefix}_yes"),
                InlineKeyboardButton(text="Нет", callback_data=f"{prefix}_no"),
            ],
            [InlineKeyboardButton(text="Пропустить", callback_data=f"{prefix}_skip")],
        ]
    )


def multi_select_kb(options: list[str], prefix: str, selected: set[int] | None = None) -> InlineKeyboardMarkup:
    selected = selected or set()
    builder = InlineKeyboardBuilder()
    for i, option in enumerate(options):
        mark = "[x] " if i in selected else "[ ] "
        builder.button(text=f"{mark}{option}", callback_data=f"{prefix}_toggle_{i}")
    builder.button(text="Готово", callback_data=f"{prefix}_done")
    builder.adjust(2)
    return builder.as_markup()


def single_select_kb(options: list[str], prefix: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for option in options:
        builder.button(text=option, callback_data=f"{prefix}_{option}")
    builder.button(text="Пропустить", callback_data=f"{prefix}_skip")
    builder.adjust(2)
    return builder.as_markup()


def duration_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for h in (1, 2, 3, 4, 6, 8, 12, 24, 48, 72):
        builder.button(text=f"{h} ч", callback_data=f"duration_{h * 60}")
    builder.button(text="Другое", callback_data="duration_custom")
    builder.adjust(4)
    return builder.as_markup()


def skip_kb(prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Пропустить", callback_data=f"{prefix}_skip")]]
    )
