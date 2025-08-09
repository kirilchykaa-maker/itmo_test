from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from typing import Dict, Optional
from pathlib import Path

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

# Gemini SDK
from google import genai
from google.genai import types

DATA_DIR = Path("data")
PROCESSED_DIR = DATA_DIR / "processed"
LATEST_FILE = DATA_DIR / "latest.txt"


@dataclass
class BotConfig:
    token: str
    gemini_api_key: str | None = None


@dataclass
class ChatState:
    chat: any | None = None
    program_path: Optional[Path] = None
    knowledge_text: str = ""
    background: str = ""


@dataclass
class ChatSessions:
    sessions: Dict[int, ChatState] = field(default_factory=dict)

    def get(self, chat_id: int) -> ChatState:
        st = self.sessions.get(chat_id)
        if st is None:
            st = ChatState()
            self.sessions[chat_id] = st
        return st


BASE_SYSTEM_POLICY = (
    "Ты — ассистент-консультант по обучению в магистратуре. Отвечай кратко и по делу, на русском. "
    "Отвечай ТОЛЬКО на релевантные вопросы по обучению в выбранной магистратуре (учебные планы, дисциплины, семестры, трудоёмкость, ГИА, практика, выборные дисциплины)."
    "Если вопрос вне этой темы — вежливо откажись и уточни, что отвечаешь только по учебной программе."
    "Если информации недостаточно в материалах программы, так и скажи."
)


def build_system_instruction(knowledge_text: str, background: str) -> str:
    parts = [BASE_SYSTEM_POLICY]
    if background.strip():
        parts.append(f"\n\nВводные абитуриента (учитывай при рекомендациях по выборным дисциплинам):\n{background.strip()}")
    # Ограничим объём знаний, чтобы не переполнить контекст
    max_chars = 120_000
    kn = knowledge_text.strip()
    if len(kn) > max_chars:
        kn = kn[:max_chars] + "\n...[обрезано]"
    parts.append("\n\nМатериалы учебной программы (используй как источник истины):\n" + kn)
    return "\n".join(parts)


def load_config() -> BotConfig:
    load_dotenv()
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("Переменная окружения TELEGRAM_BOT_TOKEN не установлена")
    gemini_key = os.getenv("GEMINI_API_KEY")
    return BotConfig(token=token, gemini_api_key=gemini_key)


def read_program_text_from_latest() -> tuple[Optional[Path], str]:
    if not LATEST_FILE.exists():
        return None, ""
    try:
        pdf_path = Path(LATEST_FILE.read_text(encoding="utf-8").strip())
    except Exception:
        return None, ""
    if not pdf_path.exists():
        return None, ""
    stem = pdf_path.stem
    # Предпочтём TXT для компактности; при отсутствии — structured XML
    txt = PROCESSED_DIR / f"{stem}.txt"
    if txt.exists():
        return pdf_path, txt.read_text(encoding="utf-8", errors="ignore")
    sx = PROCESSED_DIR / f"{stem}.structured.xml"
    if sx.exists():
        return pdf_path, sx.read_text(encoding="utf-8", errors="ignore")
    return pdf_path, ""


def create_or_refresh_chat(genai_client: genai.Client, st: ChatState) -> None:
    system_instruction = build_system_instruction(st.knowledge_text, st.background)
    st.chat = genai_client.chats.create(
        model="gemini-2.5-flash",
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            # Можно при желании отключить thinking, но оставляем по умолчанию для качества
            # thinking_config=types.ThinkingConfig(thinking_budget=0),
            temperature=0.2,
        ),
    )


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    st = context.bot_data["chats"].get(update.effective_chat.id)
    if not st.program_path:
        p, text = read_program_text_from_latest()
        if p is not None:
            st.program_path = p
            st.knowledge_text = text
    # Обновляем чат по текущему состоянию
    create_or_refresh_chat(context.bot_data["genai_client"], st)
    await update.message.reply_text(
        "Готов к диалогу по учебной программе. Команды: /set_program, /set_background, /reset, /help"
    )


async def cmd_set_program(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    st = context.bot_data["chats"].get(update.effective_chat.id)
    arg = (" ".join(context.args)).strip() if context.args else ""
    if not arg or arg.lower() == "latest":
        p, text = read_program_text_from_latest()
        if p is None:
            await update.message.reply_text("Не найден последний PDF. Запустите сервер со скачиванием или укажите путь.")
            return
        st.program_path, st.knowledge_text = p, text
    else:
        # Пользователь может прислать путь к PDF или стему
        candidate = Path(arg)
        if candidate.exists() and candidate.suffix.lower() == ".pdf":
            stem = candidate.stem
        else:
            stem = arg
        txt = PROCESSED_DIR / f"{stem}.txt"
        sx = PROCESSED_DIR / f"{stem}.structured.xml"
        if txt.exists():
            st.program_path = candidate if candidate.exists() else (DATA_DIR / "downloads" / f"{stem}.pdf")
            st.knowledge_text = txt.read_text(encoding="utf-8", errors="ignore")
        elif sx.exists():
            st.program_path = candidate if candidate.exists() else (DATA_DIR / "downloads" / f"{stem}.pdf")
            st.knowledge_text = sx.read_text(encoding="utf-8", errors="ignore")
        else:
            await update.message.reply_text("Не удалось найти материалы программы (txt/xml) по заданному имени/пути.")
            return
    create_or_refresh_chat(context.bot_data["genai_client"], st)
    await update.message.reply_text(f"Программа установлена: {st.program_path.name if st.program_path else '—'}")


async def cmd_set_background(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    st = context.bot_data["chats"].get(update.effective_chat.id)
    bg = (" ".join(context.args)).strip() if context.args else ""
    if not bg:
        await update.message.reply_text("Укажите бэкграунд после команды, например: /set_background опыт Python, ML, интерес к NLP")
        return
    st.background = bg
    # Пересоздадим чат с обновлённым системным промптом
    create_or_refresh_chat(context.bot_data["genai_client"], st)
    await update.message.reply_text("Бэкграунд сохранён. Готов рекомендовать выборные с учётом вводных.")


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    st = context.bot_data["chats"].get(update.effective_chat.id)
    st.chat = None
    create_or_refresh_chat(context.bot_data["genai_client"], st)
    await update.message.reply_text("Контекст диалога сброшен.")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Команды:\n"
        "/start — инициализация\n"
        "/set_program [latest|stem|путь_к_pdf] — выбрать программу\n"
        "/set_background <описание> — задать ваш бэкграунд\n"
        "/reset — сбросить контекст\n"
        "/help — помощь"
    )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return
    genai_client: genai.Client = context.bot_data["genai_client"]
    chats: ChatSessions = context.bot_data["chats"]
    st = chats.get(update.effective_chat.id)

    # Если чат ещё не инициализирован — попытаемся привязать к latest
    if st.chat is None:
        p, text = read_program_text_from_latest()
        if p is not None:
            st.program_path = p
            st.knowledge_text = text
        create_or_refresh_chat(genai_client, st)

    try:
        response = st.chat.send_message(update.message.text)
        text = getattr(response, "text", None) or "(пустой ответ)"
        await update.message.reply_text(text)
    except Exception as e:
        logging.exception("Gemini request failed: %s", e)
        await update.message.reply_text("Ошибка запроса к Gemini")


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = load_config()

    app = Application.builder().token(cfg.token).build()

    # Инициализируем Gemini-клиент (ключ берётся из переменной окружения GEMINI_API_KEY автоматически)
    genai_client = genai.Client()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("set_program", cmd_set_program))
    app.add_handler(CommandHandler("set_background", cmd_set_background))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # Сохраняем конфиг и клиенты в bot_data
    app.bot_data["cfg"] = cfg
    app.bot_data["genai_client"] = genai_client
    app.bot_data["chats"] = ChatSessions()

    await app.initialize()
    await app.start()
    try:
        await app.updater.start_polling(drop_pending_updates=True)
        logging.info("Telegram bot started (polling)")
        await asyncio.Event().wait()
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()


if __name__ == "__main__":
    asyncio.run(main()) 