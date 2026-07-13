from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Записать приступ", callback_data="log_migraine_start")],
            [
                InlineKeyboardButton(text="Статистика", callback_data="stats_menu"),
                InlineKeyboardButton(text="История", callback_data="history_page_0"),
            ],
            [
                InlineKeyboardButton(text="Прогноз", callback_data="prediction_menu"),
                InlineKeyboardButton(text="Цикл", callback_data="cycle_menu"),
            ],
            [
                InlineKeyboardButton(text="Профиль", callback_data="profile_menu"),
                InlineKeyboardButton(text="Помощь", callback_data="help"),
            ],
        ]
    )


def back_to_main_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Назад", callback_data="main_menu")]]
    )


def cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Отмена", callback_data="main_menu")]]
    )
