from aiogram import Bot, BaseMiddleware, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config
import wireguard
from wireguard import WGError

router = Router()

AUTHED = set()
CONFIGS = {}

HELP_TEXT = (
    "<b>WireGuardPilot — управление VPN</b>\n\n"
    "<b>Команды:</b>\n"
    "/start — главное меню\n"
    "/help — эта справка\n"
    "/create <имя> — создать пользователя (QR + настройки по кнопке)\n"
    "/config <имя> — настройки существующего пользователя\n"
    "/peers — список пользователей\n"
    "/toggle <имя> — включить/выключить\n"
    "/delete <имя> — удалить пользователя\n"
    "/status — статус сервера\n"
    "/stats — статистика подключений (трафик)\n"
    "/login <пароль> — вход (если задан пароль)\n\n"
    "Все функции доступны и по кнопкам в меню ниже."
)


def main_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="📋 Список пользователей", callback_data="peers")
    kb.button(text="📊 Статус сервера", callback_data="status")
    kb.button(text="📈 Статистика подключений", callback_data="stats")
    kb.button(text="➕ Создать пользователя", callback_data="create")
    kb.button(text="🔑 Конфиг пользователя", callback_data="config")
    kb.button(text="⏯ Вкл/выкл", callback_data="toggle")
    kb.button(text="🗑 Удалить", callback_data="delete")
    kb.button(text="❓ Помощь", callback_data="help")
    kb.adjust(1)
    return kb.as_markup()


def back_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ В меню", callback_data="menu")
    return kb.as_markup()


def peer_buttons(peers, prefix: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for p in peers:
        name = p["name"] or "(без имени)"
        mark = "🟢" if not p["disabled"] else "🔴"
        kb.button(text=f"{mark} {name}", callback_data=f"{prefix}:{name}")
    kb.adjust(1)
    kb.row(InlineKeyboardButton(text="⬅️ В меню", callback_data="menu"))
    return kb.as_markup()


def fmt_peers(data) -> str:
    if not data:
        return "Пользователей пока нет."
    lines = []
    for p in data:
        status = "🟢 активен" if not p["disabled"] else "🔴 отключён"
        handshake = p["handshake"] or "нет"
        name = p["name"] or "(без имени)"
        lines.append(
            f"<b>{name}</b>\n"
            f"  IP: {p['address']}\n"
            f"  Статус: {status}\n"
            f"  Handshake: {handshake}"
        )
    return "\n\n".join(lines)


def fmt_status(info) -> str:
    return (
        f"📡 WireGuard интерфейс: <b>{config.WG_INTERFACE}</b>\n"
        f"Публичный ключ: <code>{info['public_key']}</code>\n\n"
        f"👥 Пользователей: {info['total']}\n"
        f"🟢 Активных: {info['enabled']}\n"
        f"🔴 Отключено: {info['disabled']}"
    )


def fmt_stats(stats) -> str:
    if not stats:
        return "Пользователей пока нет."
    lines = []
    total_rx = total_tx = 0
    for s in stats:
        total_rx += s["rx"]
        total_tx += s["tx"]
        status = "🟢 активен" if not s["disabled"] else "🔴 отключён"
        handshake = s["handshake"] or "нет"
        lines.append(
            f"<b>{s['name'] or '(без имени)'}</b>\n"
            f"  IP: {s['address']}\n"
            f"  Статус: {status}\n"
            f"  ↓ Получено: {wireguard._fmt_bytes(s['rx'])}\n"
            f"  ↑ Отправлено: {wireguard._fmt_bytes(s['tx'])}\n"
            f"  Handshake: {handshake}\n"
            f"  Endpoint: {s['endpoint'] or '—'}"
        )
    lines.append(
        f"\n<b>Итого:</b>\n"
        f"  ↓ {wireguard._fmt_bytes(total_rx)}\n"
        f"  ↑ {wireguard._fmt_bytes(total_tx)}"
    )
    return "\n\n".join(lines)


class AccessMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = getattr(event, "from_user", None)
        if not user:
            return
        if config.ALLOWED_USERS and user.id not in config.ALLOWED_USERS:
            await event.answer("⛔ У вас нет доступа к этому боту.")
            return
        if config.BOT_PASSWORD and user.id not in AUTHED:
            text = getattr(event, "text", "") or ""
            if text.startswith("/login"):
                return await handler(event, data)
            await event.answer("🔒 Доступ ограничен. Введите пароль: /login <пароль>")
            return
        return await handler(event, data)


router.message.outer_middleware(AccessMiddleware())
router.callback_query.outer_middleware(AccessMiddleware())


@router.message(CommandStart())
async def start(msg: Message):
    if config.BOT_PASSWORD and msg.from_user.id not in AUTHED:
        await msg.answer("🔒 Привет! Введи пароль: /login <пароль>")
        return
    await msg.answer(
        "Привет! Я управляю WireGuard на MikroTik.\n"
        "Выбери действие кнопкой ниже или напиши /help.",
        reply_markup=main_menu(),
    )


@router.message(Command("help"))
async def help_cmd(msg: Message):
    await msg.answer(HELP_TEXT, reply_markup=main_menu())


@router.message(Command("login"))
async def login(msg: Message):
    parts = (msg.text or "").strip().split(maxsplit=1)
    if len(parts) < 2:
        await msg.answer("Использование: /login <пароль>")
        return
    if parts[1] == config.BOT_PASSWORD:
        AUTHED.add(msg.from_user.id)
        await msg.answer("✅ Авторизация успешна!", reply_markup=main_menu())
    else:
        await msg.answer("❌ Неверный пароль.")


@router.message(Command("peers"))
async def peers(msg: Message):
    await msg.answer("Загружаю список...")
    try:
        data = wireguard.list_peers()
    except Exception as e:
        await msg.answer(f"⚠️ Ошибка: {e}")
        return
    await msg.answer(fmt_peers(data), reply_markup=back_menu())


@router.message(Command("create"))
async def create(msg: Message):
    parts = (msg.text or "").strip().split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await msg.answer("Использование: /create <имя>", reply_markup=main_menu())
        return
    name = parts[1].strip()
    status_msg = await msg.answer("Создаю пользователя...")
    try:
        cfg, qr = wireguard.create_peer(name)
    except WGError as e:
        await status_msg.delete()
        await msg.answer(f"⚠️ {e}")
        return
    except Exception as e:
        await status_msg.delete()
        await msg.answer(f"⚠️ Ошибка MikroTik: {e}")
        return
    CONFIGS[name.lower()] = {"cfg": cfg, "status_id": status_msg.message_id}
    kb = InlineKeyboardBuilder()
    kb.button(text="⚙️ Показать настройки", callback_data=f"cfg:{name}")
    await msg.answer_photo(
        BufferedInputFile(qr.read(), filename="config.png"),
        caption=(
            f"Пользователь <b>{name}</b> создан!\n"
            "Отсканируй QR-код или нажми кнопку, чтобы увидеть настройки:"
        ),
        reply_markup=kb.as_markup(),
    )


@router.message(Command("config"))
async def config_cmd(msg: Message):
    parts = (msg.text or "").strip().split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await msg.answer("Использование: /config <имя>", reply_markup=main_menu())
        return
    name = parts[1].strip()
    try:
        cfg = wireguard.get_peer_config(name)
    except WGError as e:
        await msg.answer(f"⚠️ {e}")
        return
    qr = wireguard._make_qr(cfg)
    await msg.answer_photo(
        BufferedInputFile(qr.read(), filename="config.png"),
        caption=f"Настройки пользователя <b>{name}</b>:",
    )
    await msg.answer(f"<pre>{cfg}</pre>")


@router.message(Command("toggle"))
async def toggle(msg: Message):
    parts = (msg.text or "").strip().split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await msg.answer("Использование: /toggle <имя>", reply_markup=main_menu())
        return
    name = parts[1].strip()
    try:
        data = wireguard.list_peers()
        peer = next((p for p in data if p["name"].lower() == name.lower()), None)
        if not peer:
            await msg.answer("⚠️ Пользователь не найден")
            return
        new_state = not peer["disabled"]
        wireguard.set_disabled(peer["name"], new_state)
        await msg.answer(f"{'⛔ Отключён' if new_state else '✅ Включён'}: {peer['name']}")
    except WGError as e:
        await msg.answer(f"⚠️ {e}")
    except Exception as e:
        await msg.answer(f"⚠️ Ошибка MikroTik: {e}")


@router.message(Command("delete"))
async def delete(msg: Message):
    parts = (msg.text or "").strip().split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await msg.answer("Использование: /delete <имя>", reply_markup=main_menu())
        return
    name = parts[1].strip()
    try:
        wireguard.remove_peer(name)
        await msg.answer(f"🗑️ Пользователь <b>{name}</b> удалён")
    except WGError as e:
        await msg.answer(f"⚠️ {e}")
    except Exception as e:
        await msg.answer(f"⚠️ Ошибка MikroTik: {e}")


@router.message(Command("status"))
async def status(msg: Message):
    await msg.answer("Проверяю сервер...")
    try:
        info = wireguard.server_status()
    except Exception as e:
        await msg.answer(f"⚠️ Ошибка: {e}")
        return
    await msg.answer(fmt_status(info), reply_markup=back_menu())


@router.message(Command("stats"))
async def stats(msg: Message):
    await msg.answer("Загружаю статистику...")
    try:
        data = wireguard.peer_stats()
    except Exception as e:
        await msg.answer(f"⚠️ Ошибка: {e}")
        return
    await msg.answer(fmt_stats(data), reply_markup=back_menu())


@router.callback_query(F.data == "menu")
async def cq_menu(cq: CallbackQuery):
    await cq.message.edit_text(
        "Главное меню. Выбери действие:", reply_markup=main_menu()
    )
    await cq.answer()


@router.callback_query(F.data == "help")
async def cq_help(cq: CallbackQuery):
    await cq.message.edit_text(HELP_TEXT, reply_markup=main_menu())
    await cq.answer()


@router.callback_query(F.data == "peers")
async def cq_peers(cq: CallbackQuery):
    try:
        data = wireguard.list_peers()
    except Exception as e:
        await cq.answer(f"⚠️ {e}", show_alert=True)
        return
    await cq.message.edit_text(fmt_peers(data), reply_markup=back_menu())
    await cq.answer()


@router.callback_query(F.data == "status")
async def cq_status(cq: CallbackQuery):
    try:
        info = wireguard.server_status()
    except Exception as e:
        await cq.answer(f"⚠️ {e}", show_alert=True)
        return
    await cq.message.edit_text(fmt_status(info), reply_markup=back_menu())
    await cq.answer()


@router.callback_query(F.data == "stats")
async def cq_stats(cq: CallbackQuery):
    try:
        data = wireguard.peer_stats()
    except Exception as e:
        await cq.answer(f"⚠️ {e}", show_alert=True)
        return
    await cq.message.edit_text(fmt_stats(data), reply_markup=back_menu())
    await cq.answer()


@router.callback_query(F.data == "create")
async def cq_create(cq: CallbackQuery):
    await cq.answer("Напиши в чат: /create <имя>", show_alert=True)


@router.callback_query(F.data.startswith("cfg:"))
async def cq_show_config(cq: CallbackQuery, bot: Bot):
    name = cq.data.split(":", 1)[1]
    info = CONFIGS.get(name.lower(), {})
    try:
        cfg = wireguard.get_peer_config(name)
    except WGError:
        cfg = info.get("cfg")
        if not cfg:
            await cq.answer(
                "Настройки недоступны. Создай пользователя заново: /create <имя>",
                show_alert=True,
            )
            return
    try:
        await bot.delete_message(cq.message.chat.id, info["status_id"])
    except Exception:
        pass
    await cq.message.answer(f"<pre>{cfg}</pre>")
    await cq.answer()


@router.callback_query(F.data == "config")
async def cq_config_list(cq: CallbackQuery):
    try:
        peers = wireguard.list_peers()
    except Exception as e:
        await cq.answer(f"⚠️ {e}", show_alert=True)
        return
    if not peers:
        await cq.message.edit_text("Пользователей пока нет.", reply_markup=back_menu())
        await cq.answer()
        return
    await cq.message.edit_text(
        "Выбери пользователя, чтобы увидеть его настройки:",
        reply_markup=peer_buttons(peers, "showcfg"),
    )
    await cq.answer()


@router.callback_query(F.data.startswith("showcfg:"))
async def cq_show_peer_cfg(cq: CallbackQuery):
    name = cq.data.split(":", 1)[1]
    try:
        cfg = wireguard.get_peer_config(name)
    except WGError as e:
        await cq.answer(str(e), show_alert=True)
        return
    qr = wireguard._make_qr(cfg)
    await cq.message.answer_photo(
        BufferedInputFile(qr.read(), filename="config.png"),
        caption=f"Настройки пользователя <b>{name}</b>:",
    )
    await cq.message.answer(f"<pre>{cfg}</pre>")
    await cq.answer()


@router.callback_query(F.data == "toggle")
async def cq_toggle_list(cq: CallbackQuery):
    try:
        peers = wireguard.list_peers()
    except Exception as e:
        await cq.answer(f"⚠️ {e}", show_alert=True)
        return
    if not peers:
        await cq.message.edit_text("Пользователей пока нет.", reply_markup=back_menu())
        await cq.answer()
        return
    await cq.message.edit_text(
        "Выбери пользователя для вкл/выкл:", reply_markup=peer_buttons(peers, "tg")
    )
    await cq.answer()


@router.callback_query(F.data.startswith("tg:"))
async def cq_toggle_one(cq: CallbackQuery):
    name = cq.data.split(":", 1)[1]
    try:
        peers = wireguard.list_peers()
        peer = next((p for p in peers if p["name"].lower() == name.lower()), None)
        if not peer:
            await cq.answer("Пользователь не найден", show_alert=True)
            return
        new_state = not peer["disabled"]
        wireguard.set_disabled(peer["name"], new_state)
        action = "⛔ Отключён" if new_state else "✅ Включён"
    except Exception as e:
        await cq.answer(f"⚠️ {e}", show_alert=True)
        return
    try:
        peers = wireguard.list_peers()
    except Exception:
        peers = []
    await cq.message.edit_text(
        "Выбери пользователя для вкл/выкл:", reply_markup=peer_buttons(peers, "tg")
    )
    await cq.answer(f"{action}: {name}")


@router.callback_query(F.data == "delete")
async def cq_delete_list(cq: CallbackQuery):
    try:
        peers = wireguard.list_peers()
    except Exception as e:
        await cq.answer(f"⚠️ {e}", show_alert=True)
        return
    if not peers:
        await cq.message.edit_text("Пользователей пока нет.", reply_markup=back_menu())
        await cq.answer()
        return
    await cq.message.edit_text(
        "Выбери пользователя для удаления:", reply_markup=peer_buttons(peers, "dl")
    )
    await cq.answer()


@router.callback_query(F.data.startswith("dl:"))
async def cq_delete_one(cq: CallbackQuery):
    name = cq.data.split(":", 1)[1]
    try:
        wireguard.remove_peer(name)
    except Exception as e:
        await cq.answer(f"⚠️ {e}", show_alert=True)
        return
    try:
        peers = wireguard.list_peers()
    except Exception:
        peers = []
    text = f"🗑️ Пользователь <b>{name}</b> удалён." if peers else "Все пользователи удалены."
    await cq.message.edit_text(text, reply_markup=peer_buttons(peers, "dl"))
    await cq.answer()
