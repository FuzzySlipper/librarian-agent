"""LLM request/response debug logger.

Writes all LLM interactions to a rotating log file for debugging.
Each entry is pretty-printed JSON separated by a blank line and a divider
for easy visual scanning.

Log file: build/data/llm-debug.log
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

_log_path: Path | None = None
_logger: logging.Logger | None = None


def init(data_dir: Path) -> None:
    """Initialize the LLM debug logger."""
    global _log_path, _logger

    _log_path = data_dir / "llm-debug.log"
    _log_path.parent.mkdir(parents=True, exist_ok=True)

    _logger = logging.getLogger("llm_debug")
    _logger.setLevel(logging.DEBUG)
    _logger.propagate = False

    # Rotating file handler — keep last 10MB
    from logging.handlers import RotatingFileHandler
    handler = RotatingFileHandler(
        str(_log_path), maxBytes=10_000_000, backupCount=2,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    _logger.handlers.clear()
    _logger.addHandler(handler)


def _write(entry: dict) -> None:
    """Write a formatted log entry."""
    if not _logger:
        return
    direction = entry.get("dir", "?")
    agent = entry.get("agent", "?")
    ts = entry.get("ts", "")

    header = f"──── {direction.upper()} │ {agent} │ {ts} "
    header += "─" * max(0, 80 - len(header))

    formatted = json.dumps(entry, indent=2, ensure_ascii=False)
    _logger.debug(f"\n{header}\n{formatted}\n")


def log_request(*, agent: str, model: str, max_tokens: int,
                system_preview: str, messages_count: int,
                tools_count: int, extra: dict | None = None) -> None:
    """Log an outgoing LLM request."""
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dir": "request",
        "agent": agent,
        "model": model,
        "max_tokens": max_tokens,
        "system_len": len(system_preview),
        "system_preview": system_preview[:300],
        "messages": messages_count,
        "tools": tools_count,
    }
    if extra:
        entry.update(extra)
    _write(entry)


def log_response(*, agent: str, model: str, stop_reason: str | None,
                 content_preview: str, input_tokens: int = 0,
                 output_tokens: int = 0, content_blocks: list | None = None,
                 error: str | None = None) -> None:
    """Log an incoming LLM response."""
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dir": "response",
        "agent": agent,
        "model": model,
        "stop_reason": stop_reason,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "content_len": len(content_preview),
        "content_preview": content_preview[:500],
    }

    # Include block-level detail for diagnosing empty responses
    if content_blocks is not None:
        blocks_summary = []
        for b in content_blocks:
            btype = getattr(b, "type", "?")
            if btype == "text":
                text = getattr(b, "text", "")
                blocks_summary.append({
                    "type": "text",
                    "len": len(text),
                    "preview": text[:200] if text else "(empty)",
                })
            elif btype == "tool_use":
                blocks_summary.append({
                    "type": "tool_use",
                    "name": getattr(b, "name", "?"),
                    "input": getattr(b, "input", {}),
                })
            else:
                blocks_summary.append({"type": btype})
        entry["content_blocks"] = blocks_summary

    if error:
        entry["error"] = error
    _write(entry)


def log_error(*, agent: str, model: str, error: str) -> None:
    """Log an LLM call error."""
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dir": "error",
        "agent": agent,
        "model": model,
        "error": error,
    }
    _write(entry)
