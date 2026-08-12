import os

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")

ALLOWED_USERS = {int(x) for x in os.getenv("ALLOWED_USERS", "").split(",") if x.strip()}
BOT_PASSWORD = os.getenv("BOT_PASSWORD", "")

MT_HOST = os.getenv("MT_HOST", "")
MT_USER = os.getenv("MT_USER", "admin")
MT_PASS = os.getenv("MT_PASS", "")
MT_PORT = int(os.getenv("MT_PORT", "8728"))
MT_USE_TLS = os.getenv("MT_USE_TLS", "false").lower() == "true"

WG_INTERFACE = os.getenv("WG_INTERFACE", "wg1")
WG_SUBNET = os.getenv("WG_SUBNET", "10.10.0.0/24")
WG_SERVER_ADDRESS = os.getenv("WG_SERVER_ADDRESS", "10.10.0.1")
WG_ENDPOINT = os.getenv("WG_ENDPOINT", "")
WG_DNS = os.getenv("WG_DNS", "1.1.1.1, 8.8.8.8")
