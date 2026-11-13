"""Text constraints shared by application commands and the protected facade."""

from .app_protocol import MAX_TEXT_BYTES
from .errors import ValidationError


def validate_chat_text(text: str) -> None:
    if not isinstance(text, str) or not text.strip():
        raise ValidationError("Message is empty")
    try:
        size = len(text.encode("utf-8"))
    except UnicodeEncodeError as error:
        raise ValidationError("Message is not valid Unicode") from error
    if size > MAX_TEXT_BYTES:
        raise ValidationError("Message exceeds the 16 KiB limit")
