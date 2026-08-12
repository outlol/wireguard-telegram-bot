import asyncio
import logging
import socket

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

import config
from handlers import router


# api.telegram.org может быть заблокирован на уровне DNS/провайдера.
# Пин DNS-запроса на рабочий IP, чтобы бот не падал с таймаутом подключения.
TELEGRAM_API_IP = "149.154.167.220"

_orig_getaddrinfo = socket.getaddrinfo


def _patched_getaddrinfo(host, port, *args, **kwargs):
    if host == "api.telegram.org":
        host = TELEGRAM_API_IP
    return _orig_getaddrinfo(host, port, *args, **kwargs)


socket.getaddrinfo = _patched_getaddrinfo


async def main():
    if not config.BOT_TOKEN:
        raise SystemExit("Нет BOT_TOKEN. Скопируй .env.example в .env и заполни его.")
    bot = Bot(config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)
    await dp.start_polling(bot)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
