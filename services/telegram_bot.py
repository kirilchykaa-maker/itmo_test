from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from typing import Dict

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

# Gemini SDK
from google import genai


@dataclass
class BotConfig:
    token: str
    gemini_api_key: str | None = None


@dataclass
class ChatSessions:
    sessions: Dict[int, any] = field(default_factory=dict)

    def get_or_create(self, client: genai.Client, chat_id: int):
        chat = self.sessions.get(chat_id)
        if chat is None:
            chat = client.chats.create(model="gemini-2.5-flash")
            self.sessions[chat_id] = chat
        return chat


def load_config() -> BotConfig:
    load_dotenv()
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("Переменная окружения TELEGRAM_BOT_TOKEN не установлена")
    gemini_key = os.getenv("GEMINI_API_KEY")
    return BotConfig(token=token, gemini_api_key=gemini_key)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Бот готов. Пишите ваш вопрос — я отвечу через Gemini 2.5 Flash.")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return
    cfg: BotConfig = context.bot_data["cfg"]
    genai_client: genai.Client = context.bot_data["genai_client"]
    chats: ChatSessions = context.bot_data["chats"]

    chat = chats.get_or_create(genai_client, update.effective_chat.id)

    try:
        # Отправляем сообщение в текущий чат Gemini с сохранением истории
        response = chat.send_message(update.message.text)
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

    app.add_handler(CommandHandler("start", start))
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