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


HOW_TO = (
    "Как пользоваться, когда книга открыта:\n\n"
    "♥ Любимое — сердечко вверху слева. "
    "Нажми, чтобы добавить книгу в любимое. "
    "Нажми ещё раз — уберёшь. Когда сердечко красное, книга уже в любимом.\n\n"
    "➕ Читать дальше — кнопка со знаком плюс рядом. "
    "Нажми, чтобы положить книгу в папку «Читать дальше». "
    "Ещё раз — убрать из списка.\n\n"
    "▶️ Авточтение — кнопка с треугольником: запускает прокрутку текста. "
    "⏸ Пауза — та же кнопка, останавливает.\n\n"
    "1× Скорость — отдельная кнопка справа от старта. "
    "Каждое нажатие переключает темп: 1× → 2× → 3× → 4× → снова 1×. "
    "Скорость можно менять и на паузе, и пока текст уже ползёт.\n\n"
    "Если шапка с кнопками спряталась — тапни по центру страницы "
    "или нажми «настройки» сверху, чтобы она вернулась."
)

HELP_TEXT = "📖 Подсказка\n\n" + HOW_TO

START_TEXT = (
    "Привет! Это Readbook — библиотека на 600 000 книг и читалка внутри Telegram.\n\n"
    "Открой приложение кнопкой ниже (или «Библиотека» рядом с полем ввода). "
    "Можно написать название книги сюда в чат — пришлю подборку.\n\n"
    + HOW_TO
    + "\n\nЭто же описание всегда можно открыть командой /help."
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
