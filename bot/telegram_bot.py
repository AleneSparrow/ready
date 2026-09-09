import asyncio
import time

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    BotCommand,
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    MenuButtonWebApp,
    Message,
    WebAppInfo,
)

from . import bookfile, catalog, config
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
    "или нажми «настройки» сверху, чтобы она вернулась.\n\n"
    "⬇ Скачать — в чате рядом с книгой или в читалке. "
    "Файл fb2 или epub придёт сюда сообщением, его можно открыть в другой читалке."
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

    results = await asyncio.to_thread(catalog.search, query)
    if not results:
        await message.answer("Ничего не нашла 🤷")
        return

    buttons = []
    for r in results:
        author = format_authors(r.author)
        label = f"{author} — {r.title}" if author else r.title
        label = label[:64]
        url = f"{APP_URL}&book={r.id}"
        buttons.append([
            InlineKeyboardButton(text=label, web_app=WebAppInfo(url=url)),
            InlineKeyboardButton(text="⬇ файл", callback_data=f"dl:{r.id}"),
        ])

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer(
        f"Нашла {len(results)} книг. Слева — открыть, справа «файл» — пришлю fb2 или epub сюда.",
        reply_markup=kb,
    )


@dp.callback_query(F.data.startswith("dl:"))
async def download_callback(query: CallbackQuery) -> None:
    await query.answer("Собираю файл…")
    chat_id = query.from_user.id
    try:
        book_id = int((query.data or "").split(":", 1)[1])
    except (ValueError, IndexError):
        await bot.send_message(chat_id, "Не поняла, какую книгу скачать.")
        return
    status = await bot.send_message(chat_id, "Качаю файл, подожди минутку…")
    try:
        data, name = await asyncio.to_thread(bookfile.get_book_file, book_id)
        if len(data) > bookfile.TELEGRAM_DOC_MAX:
            await status.edit_text("Файл слишком большой, чтобы прислать его в Telegram.")
            return
        await bot.send_document(chat_id, BufferedInputFile(data, filename=name))
        await status.delete()
    except bookfile.BookFileError:
        await status.edit_text("Не получилось скачать книгу. Попробуй ещё раз через минуту.")
    except Exception:
        await status.edit_text("Не получилось скачать книгу. Попробуй ещё раз через минуту.")


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
