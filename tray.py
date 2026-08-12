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

import ctypes
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pystray
from PIL import Image, ImageDraw, ImageFont

BASE_DIR = Path(__file__).resolve().parent
LOG_FILE = BASE_DIR / "bot.log"

# Защита от запуска нескольких копий трея (иначе каждый поднимет своего бота).
_MUTEX_NAME = "Global\\WG_TG_Bot_Tray_Mutex"
_hMutex = None

COLOR_OK = (76, 175, 80, 255)      # зелёный
COLOR_ERR = (229, 57, 53, 255)     # красный
COLOR_WHITE = (255, 255, 255, 255)
COLOR_BLUE = (42, 169, 224, 255)   # синий (как у Telegram)
COLOR_GRAY = (158, 158, 158, 255)  # серый (бот остановлен)

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


def _kill_stray_bots():
    """Убивает все осиротевшие процессы бота (main.py).

    Бот запускается через venv-загрузчик, который порождает дочерний
    интерпретатор. Если загрузчик умирает, интерпретатор может остаться
    жить и продолжать поллинг -> конфликт с новым экземпляром.
    """
    if os.name != "nt":
        return
    try:
        ps = (
            "Get-CimInstance Win32_Process -Filter \"Name like 'python%'\" | "
            "Where-Object { $_.ProcessId -ne $PID -and $_.CommandLine -match 'main\\.py' } | "
            "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True,
            timeout=20,
        )
    except Exception:
        pass


def _start():
    global _proc, _wanted
    _wanted = True
    _kill_stray_bots()
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
        if os.name == "nt":
            # Бот запускается через venv-загрузчик, который порождает
            # дочерний интерпретатор. Убиваем всё дерево процессов.
            subprocess.run(
                ["taskkill", "/PID", str(p.pid), "/T", "/F"],
                capture_output=True,
            )
        else:
            p.terminate()
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
    _kill_stray_bots()


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

    # Круг как у Telegram: синий — бот работает, серый — остановлен.
    bg = COLOR_BLUE if running else COLOR_GRAY
    d.ellipse([2, 2, size - 2, size - 2], fill=bg)

    # Белый самолётик (отправка сообщения) в стиле Telegram.
    plane = [
        (13, 35), (51, 14), (40, 47), (31, 40), (22, 56), (26, 40),
    ]
    d.polygon(plane, fill=COLOR_WHITE)

    # Надпись WG под самолётиком.
    font = _load_font(15)
    text = "WG"
    bbox = d.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    d.text(((size - tw) / 2 - bbox[0], 47), text, font=font, fill=COLOR_WHITE)

    # Цветная точка статуса в правом верхнем углу: зелёная — запущен, красная — остановлен.
    dot = COLOR_OK if running else COLOR_ERR
    d.ellipse([43, 4, 60, 21], fill=dot, outline=COLOR_WHITE, width=2)
    return img


def _load_font(size):
    for path in (
        r"C:\Windows\Fonts\segoeuib.ttf",
        r"C:\Windows\Fonts\arialbd.ttf",
    ):
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


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


def _acquire_mutex():
    global _hMutex
    if os.name != "nt":
        return True
    _hMutex = ctypes.windll.kernel32.CreateMutexW(None, False, _MUTEX_NAME)
    if not _hMutex:
        return False
    return ctypes.windll.kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS


def main():
    if not _acquire_mutex():
        print("Трей уже запущен. Выход.")
        return
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
