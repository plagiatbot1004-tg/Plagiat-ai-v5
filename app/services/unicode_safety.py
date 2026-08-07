from html import unescape
from html.parser import HTMLParser
from typing import Any


def safe_text(value: Any) -> str:
    """Return UTF-8-safe text while preserving all valid Unicode characters."""
    text = str(value or "")
    return text.encode("utf-8", errors="replace").decode("utf-8")


class _PlainTextHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def html_fragment_to_text(value: Any) -> str:
    """Convert provider HTML highlights into readable plain text."""
    raw = unescape(safe_text(value))
    if not raw:
        return ""

    parser = _PlainTextHTMLParser()
    parser.feed(raw)
    parser.close()
    return " ".join("".join(parser.parts).split())


def sanitize_json_value(value: Any) -> Any:
    """Recursively make provider payloads safe for PostgreSQL UTF-8 storage."""
    if isinstance(value, str):
        return safe_text(value)
    if isinstance(value, list):
        return [sanitize_json_value(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_json_value(item) for item in value]
    if isinstance(value, dict):
        return {safe_text(key): sanitize_json_value(item) for key, item in value.items()}
    return value
