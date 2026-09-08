from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo

from . import catalog, config
from .format_author import format_authors

bot = Bot(config.TELEGRAM_BOT_TOKEN)
dp = Dispatcher()


@dp.message(CommandStart())
async def start(message: Message) -> None:
    await message.answer(
        "Привет! Напиши название книги или автора — найду в библиотеке.\n"
        "Дальше просто нажми на нужную книгу — откроется читалка прямо здесь, в Telegram."
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
        url = f"{config.WEBAPP_BASE_URL}/app/index.html?book={r.id}"
        buttons.append([InlineKeyboardButton(text=label, web_app=WebAppInfo(url=url))])

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer(f"Нашла {len(results)} книг:", reply_markup=kb)


async def run_bot() -> None:
    await dp.start_polling(bot)
