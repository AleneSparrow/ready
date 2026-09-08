import time

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    MenuButtonWebApp,
    Message,
    WebAppInfo,
)

from . import catalog, config
from .format_author import format_authors

bot = Bot(config.TELEGRAM_BOT_TOKEN)
dp = Dispatcher()

# Telegram-клиент может закэшировать Mini App по URL независимо от HTTP-кэша.
# Версия меняется при каждом рестарте процесса (= при каждом деплое) —
# новый URL гарантированно не подставит старую закэшированную версию.
_APP_VERSION = str(int(time.time()))
APP_URL = f"{config.WEBAPP_BASE_URL}/app/index.html?v={_APP_VERSION}"


@dp.message(CommandStart())
async def start(message: Message) -> None:
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="📚 Открыть библиотеку", web_app=WebAppInfo(url=APP_URL))]]
    )
    await message.answer(
        "Привет! Это твоя читалка.\n\n"
        "Открывай библиотеку кнопкой ниже (или значком рядом с полем ввода) — "
        "там поиск с обложками, закладки и статистика чтения. "
        "Либо просто напиши название книги прямо сюда — пришлю подборку.",
        reply_markup=kb,
    )


@dp.message(F.text)
async def search_handler(message: Message) -> None:
    query = (message.text or "").strip()
    if not query:
        return

    results = catalog.search(query)
    if not results:
        await message.answer("Ничего не нашла 🤷")
        return

    buttons = []
    for r in results:
        author = format_authors(r.author)
        label = f"{author} — {r.title}" if author else r.title
        label = label[:64]
        url = f"{APP_URL}&book={r.id}"
        buttons.append([InlineKeyboardButton(text=label, web_app=WebAppInfo(url=url))])

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer(f"Нашла {len(results)} книг:", reply_markup=kb)


async def run_bot() -> None:
    await bot.set_chat_menu_button(
        menu_button=MenuButtonWebApp(text="Библиотека", web_app=WebAppInfo(url=APP_URL))
    )
    await dp.start_polling(bot)
