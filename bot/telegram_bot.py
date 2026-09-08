import time

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    BotCommand,
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


HELP_TEXT = (
    "📖 Как пользоваться читалкой\n\n"
    "В мини-приложении две вкладки внизу:\n"
    "🔍 Поиск — найти книгу по названию или автору\n"
    "📚 Библиотека — три папки: продолжить чтение, закладки, читать дальше. "
    "Нажми на папку, чтобы увидеть книги обложками. "
    "Внутри папки кнопка «Изменить» позволяет убрать одну книгу, "
    "а «Сбросить всё» на главной библиотеки стирает все списки сразу.\n\n"
    "Кнопки в шапке читалки (слева направо):\n"
    "← — закрыть книгу и вернуться\n"
    "🔖 — закладка на эту книгу\n"
    "➕ — в список «читать дальше»\n"
    "📖 / 📜 — страницы или лента (скролл)\n"
    "▶️ / ⏸ — запустить или остановить автопрокрутку\n"
    "1× / 2× / 3× / 4× — скорость автопрокрутки (отдельная кнопка)\n"
    "A− / A+ — мельче или крупнее шрифт\n\n"
    "Шапку с настройками можно спрятать, чтобы не мешала тексту: "
    "тап по центру страницы или кнопка «настройки» сверху. "
    "Листать страницы — тап или свайп по левому и правому краю. "
    "Когда кнопка подсвечена — она включена."
)

START_TEXT = (
    "Привет! Это Readbook — библиотека на 600 000 книг и читалка внутри Telegram.\n\n"
    "Открой приложение кнопкой ниже (или «Библиотека» рядом с полем ввода). "
    "Можно также написать название книги прямо сюда в чат — пришлю подборку.\n\n"
    "Вкладки внизу:\n"
    "🔍 Поиск — найти книгу по названию или автору\n"
    "📚 Библиотека — три папки: продолжить чтение, закладки, читать дальше. "
    "Нажми на папку, чтобы открыть книги. Внутри «Изменить» убирает одну книгу. "
    "«Сбросить закладки и историю» на главной библиотеки стирает все списки сразу.\n\n"
    "Кнопки в шапке читалки (слева направо):\n"
    "← — закрыть книгу и вернуться\n"
    "🔖 — закладка на эту книгу\n"
    "➕ — в список «читать дальше»\n"
    "📖 / 📜 — страницы или лента (скролл)\n"
    "▶️ / ⏸ — запустить или остановить автопрокрутку\n"
    "1× / 2× / 3× / 4× — скорость автопрокрутки\n"
    "A− / A+ — мельче или крупнее шрифт\n"
    "⌃ — спрятать шапку, чтобы не мешала тексту\n\n"
    "Вернуть шапку: тап по центру страницы или кнопка «настройки» сверху. "
    "Листать страницы — тап или свайп по левому и правому краю. "
    "Когда кнопка подсвечена — она включена.\n\n"
    "Это же описание всегда можно открыть командой /help."
)


@dp.message(CommandStart())
async def start(message: Message) -> None:
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="📚 Открыть библиотеку", web_app=WebAppInfo(url=APP_URL))]]
    )
    await message.answer(START_TEXT, reply_markup=kb)


@dp.message(Command("help"))
async def help_cmd(message: Message) -> None:
    await message.answer(HELP_TEXT)


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
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Приветствие и открыть библиотеку"),
            BotCommand(command="help", description="Что делает каждая кнопка"),
        ]
    )
    await bot.set_my_short_description("Библиотека 600 000 книг и читалка внутри Telegram")
    await bot.set_my_description(
        "Readbook — библиотека на 600 000 книг и читалка внутри Telegram.\n\n"
        "Нажми «Библиотека» или /start, чтобы открыть приложение. "
        "В приветствии и в /help — что делает каждая кнопка."
    )
    await bot.set_chat_menu_button(
        menu_button=MenuButtonWebApp(text="Библиотека", web_app=WebAppInfo(url=APP_URL))
    )
    await dp.start_polling(bot)
