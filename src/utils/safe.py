"""Safe access utilities — graceful handling of index/key errors.

Not for hot paths. For LLM response parsing and other areas where
data shape is unpredictable and crashing is worse than a default value.
"""

import logging
from typing import TypeVar

log = logging.getLogger(__name__)

T = TypeVar("T")


def safe_get(collection, index_or_key, default=None, context: str = ""):
    """Safely access a list index or dict key, returning default on failure.

    Args:
        collection: A list, dict, or any subscriptable object.
        index_or_key: The index (int) or key (str) to access.
        default: Value to return if access fails.
        context: Optional label for log messages (e.g., "librarian response").

    Returns:
        The value at the index/key, or default if anything goes wrong.
    """
    if collection is None:
        log.warning("safe_get: None collection%s", f" ({context})" if context else "")
        return default

    try:
        return collection[index_or_key]
    except (IndexError, KeyError, TypeError) as e:
        log.warning(
            "safe_get: %s accessing [%r] on %s (len=%s)%s",
            type(e).__name__,
            index_or_key,
            type(collection).__name__,
            len(collection) if hasattr(collection, "__len__") else "?",
            f" ({context})" if context else "",
        )
        return default


def safe_attr(obj, attr: str, default=None, context: str = ""):
    """Safely access an object attribute, returning default on failure.

    Args:
        obj: Any object.
        attr: Attribute name to access.
        default: Value to return if attribute doesn't exist.
        context: Optional label for log messages.
    """
    if obj is None:
        log.warning("safe_attr: None object%s", f" ({context})" if context else "")
        return default

    try:
        return getattr(obj, attr, default)
    except Exception as e:
        log.warning(
            "safe_attr: %s accessing .%s on %s%s",
            type(e).__name__,
            attr,
            type(obj).__name__,
            f" ({context})" if context else "",
        )
        return default


def safe_first_text(content_blocks, default: str = "", context: str = "") -> str:
    """Extract text from the first text block in an LLM response's content list.

    This is the most common crash site — response.content[0].text when
    the model returns empty content, reasoning-only, or tool_use blocks.

    Args:
        content_blocks: List of response content blocks (each has .type and .text).
        default: String to return if no text block found.
        context: Optional label for log messages.
    """
    if not content_blocks:
        log.warning("safe_first_text: empty content blocks%s", f" ({context})" if context else "")
        return default

    for block in content_blocks:
        block_type = safe_attr(block, "type", context=context)
        if block_type == "text":
            text = safe_attr(block, "text", "", context=context)
            if text:
                return text

    log.warning(
        "safe_first_text: no text blocks found in %d blocks (types: %s)%s",
        len(content_blocks),
        ", ".join(safe_attr(b, "type", "?") for b in content_blocks),
        f" ({context})" if context else "",
    )
    return default
