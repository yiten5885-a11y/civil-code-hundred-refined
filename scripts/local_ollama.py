"""Allow local Qwen generation only through an explicit loopback Ollama URL."""
from urllib.parse import urlsplit


def local_endpoint(host: str) -> str:
    value = host if "://" in host else "http://" + host
    try:
        parsed = urlsplit(value)
        port = parsed.port or 11434
    except ValueError as exc:
        raise ValueError("本地 Ollama 地址或端口无效") from exc
    if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.username or parsed.password or parsed.path not in {"", "/"}
        or parsed.query or parsed.fragment or not 1 <= port <= 65535):
        raise ValueError("仅支持本机回环地址上的 HTTP Ollama，不调用远端或云端模型")
    name = "[::1]" if parsed.hostname == "::1" else parsed.hostname
    return f"http://{name}:{port}/api/chat"
