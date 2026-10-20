import os
from urllib.parse import urlsplit

LOCAL_ORIGINS = {f"http://{host}:{port}" for host in ("localhost", "127.0.0.1") for port in (5173, 8000)}


def public_origin():
    origin = os.environ.get("AFTERCARE_PUBLIC_ORIGIN", "").rstrip("/")
    if origin:
        url = urlsplit(origin)
        if url.scheme != "https" or not url.hostname or url.username or url.password or url.path or url.query or url.fragment:
            raise ValueError("AFTERCARE_PUBLIC_ORIGIN must be an HTTPS origin without a path.")
    return origin


def validate():
    origin = public_origin()
    if origin and (os.environ.get("AFTERCARE_SECURE_COOKIE") != "1" or not os.environ.get("AFTERCARE_VAULT_KEY")):
        raise ValueError("Remote hosting requires secure cookies and an externally managed vault key.")
    if origin:
        from .vault import key
        from .store import DATA
        key(DATA)
    ollama = urlsplit(os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434"))
    if ollama.scheme != "http" or ollama.hostname not in {"127.0.0.1", "localhost", "ollama"} or ollama.username or ollama.password:
        raise ValueError("Ollama must run locally or in the private 'ollama' container.")


def allowed_origins():
    origin = public_origin()
    return LOCAL_ORIGINS | ({origin} if origin else set())


def allowed_hosts():
    return {"localhost", "127.0.0.1"} | ({urlsplit(public_origin()).hostname} if public_origin() else set())
