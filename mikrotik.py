import ssl

import librouteros

from config import MT_HOST, MT_PASS, MT_PORT, MT_USE_TLS, MT_USER


def connect():
    if not MT_HOST:
        raise ConnectionError("Не задан MT_HOST в .env")
    kwargs = {}
    if MT_USE_TLS:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        kwargs["ssl_wrapper"] = ctx.wrap_socket
    return librouteros.connect(MT_HOST, MT_USER, MT_PASS, port=MT_PORT, **kwargs)
