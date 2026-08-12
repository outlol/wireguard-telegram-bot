"""Системный трей для управления ботом.

Показывает в трее (около часов) иконку статуса бота:
  - зелёная  -> бот работает
  - красная  -> бот остановлен

Меню (по клику по иконке):
  - Статус бота
  - Перезапустить бота
  - Остановить бота
  - Запустить бота
  - Открыть терминал (живые логи)
  - Выход
"""

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pystray
from PIL import Image, ImageDraw

BASE_DIR = Path(__file__).resolve().parent
LOG_FILE = BASE_DIR / "bot.log"

COLOR_OK = (76, 175, 80, 255)      # зелёный
COLOR_ERR = (229, 57, 53, 255)     # красный
COLOR_WHITE = (255, 255, 255, 255)

_proc = None
_lock = threading.Lock()
_stop_ev = threading.Event()
_auto_restart = True
_wanted = False  # True — бот должен работать (учитывается при автоперезапуске)


def _python():
    venv = BASE_DIR / ".venv" / "Scripts" / "python.exe"
    if venv.exists():
        return str(venv)
    return sys.executable


def is_running():
    with _lock:
        p = _proc
    return p is not None and p.poll() is None


def _start():
    global _proc, _wanted
    _wanted = True
    with _lock:
        if _proc is not None and _proc.poll() is None:
            return
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        log = open(LOG_FILE, "a", encoding="utf-8", buffering=1)
        _proc = subprocess.Popen(
            [_python(), "main.py"],
            cwd=str(BASE_DIR),
            stdout=log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            env=env,
        )


def _stop():
    global _proc, _wanted
    _wanted = False
    with _lock:
        p, _proc = _proc, None
    if p is not None and p.poll() is None:
        p.terminate()
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()


def _restart():
    _stop()
    time.sleep(0.5)
    _start()


def _open_terminal():
    cmd = (
        'chcp 65001 >nul && echo === Bot log (%CD%) === && '
        'type bot.log 2>nul & echo. & '
        'powershell -NoProfile -ExecutionPolicy Bypass '
        '-Command "Get-Content -Path bot.log -Wait -Encoding UTF8"'
    )
    subprocess.Popen(["cmd", "/k", cmd], cwd=str(BASE_DIR))


def _make_icon(running):
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    color = COLOR_OK if running else COLOR_ERR
    d.ellipse([2, 2, size - 2, size - 2], fill=color, outline=COLOR_WHITE, width=4)
    if running:
        # белая галочка "работает"
        d.line([18, 34, 29, 46], fill=COLOR_WHITE, width=8)
        d.line([29, 46, 48, 22], fill=COLOR_WHITE, width=8)
    else:
        # белый крестик "остановлен"
        d.line([20, 20, 44, 44], fill=COLOR_WHITE, width=8)
        d.line([44, 20, 20, 44], fill=COLOR_WHITE, width=8)
    return img


def _build_menu():
    return pystray.Menu(
        pystray.MenuItem("Перезапустить бота", lambda i, ic: _restart(), default=True),
        pystray.MenuItem(
            "Остановить бота",
            lambda i, ic: _stop(),
            enabled=lambda i: is_running(),
        ),
        pystray.MenuItem(
            "Запустить бота",
            lambda i, ic: _start(),
            enabled=lambda i: not is_running(),
        ),
        pystray.MenuItem(
            "Автоперезапуск при сбое",
            lambda i, ic: _toggle_autorestart(),
            checked=lambda i: _auto_restart,
        ),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Открыть терминал (логи)", lambda i, ic: _open_terminal()),
        pystray.MenuItem("Выход", lambda i, ic: _quit(ic)),
    )


def _toggle_autorestart():
    global _auto_restart
    _auto_restart = not _auto_restart


def _quit(icon):
    _stop()
    _stop_ev.set()
    icon.stop()


def _monitor(icon):
    last = None
    while not _stop_ev.is_set():
        time.sleep(1.0)
        running = is_running()
        try:
            icon.icon = _make_icon(running)
            icon.title = "WG Bot — запущен" if running else "WG Bot — остановлен"
        except Exception:
            pass
        if running != last:
            last = running
            try:
                icon.update_menu()
            except Exception:
                pass
        if _auto_restart and _wanted and not running:
            _start()


def main():
    icon = pystray.Icon(
        "wg_telegram_bot",
        _make_icon(False),
        title="WG Bot — запуск...",
    )
    icon.menu = _build_menu()
    threading.Thread(target=_monitor, args=(icon,), daemon=True).start()
    _start()
    icon.run()


if __name__ == "__main__":
    main()
