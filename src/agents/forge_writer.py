"""StoryForge chapter writing agent.

Adapted from ProseWriter's tool-use loop.  Each call writes a single chapter
with limited cognition: the writer sees only its chapter brief + the previous
chapter's text.  It can query lore via the Librarian for factual consistency.
"""

import json
import logging
from pathlib import Path

from src.llm import LLMClient

log = logging.getLogger(__name__)

# Same lore query tool the ProseWriter uses
LORE_TOOL = {
    "name": "query_lore",
    "description": (
        "Query the world's lore for character details, locations, events, "
        "or world rules. Use this when you need to verify a fact or find "
        "a character's physical description."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "A specific lore question."},
        },
        "required": ["query"],
    },
}


def _load_system_prompt(prompts_dir: Path, style_doc: str) -> str:
    """Build the writer system prompt from base template + style doc."""
    prompt_file = prompts_dir / "writer.md"
    if prompt_file.exists():
        base = prompt_file.read_text(encoding="utf-8")
    else:
        base = _DEFAULT_WRITER_PROMPT

    return f"{base}\n\n## Narrative Style\n\n{style_doc}"


_DEFAULT_WRITER_PROMPT = """\
You are a skilled prose writer working on a chapter of a longer story. You \
will receive a chapter brief (your implementation spec) and optionally the \
ending of the previous chapter for continuity.

Write the chapter as polished prose — not a summary, not an outline. This is \
the final text that readers will see.

Guidelines:
- Follow the chapter brief's required beats faithfully
- Maintain continuity with the previous chapter's ending
- Use the query_lore tool to verify character details, locations, and world \
  facts before writing about them. Physical descriptions are especially \
  important — always verify before describing a character's appearance.
- Write complete scenes with dialogue, action, and interiority
- End at a natural chapter break point
- Do NOT reference events from future chapters or the overall plot outline \
  — you only know what has happened so far
"""


def _search_drafts(query: str, chapters_dir: Path, max_chars: int = 2000) -> str:
    """Search existing chapter drafts for content matching a query.

    Returns relevant excerpts or empty string if nothing found.
    """
    if not chapters_dir or not chapters_dir.is_dir():
        return ""

    query_lower = query.lower()
    keywords = [w for w in query_lower.split() if len(w) > 3]
    if not keywords:
        return ""

    matches = []
    for draft in sorted(chapters_dir.glob("ch-*-draft.md")):
        try:
            text = draft.read_text(encoding="utf-8")
        except Exception:
            continue

        # Check if any keywords appear in this chapter
        text_lower = text.lower()
        score = sum(1 for kw in keywords if kw in text_lower)
        if score == 0:
            continue

        # Find the most relevant paragraph
        paragraphs = text.split("\n\n")
        best_para = ""
        best_score = 0
        for para in paragraphs:
            para_lower = para.lower()
            s = sum(1 for kw in keywords if kw in para_lower)
            if s > best_score:
                best_score = s
                best_para = para

        if best_para:
            ch_name = draft.stem.replace("-draft", "")
            matches.append((score, ch_name, best_para[:500]))

    if not matches:
        return ""

    matches.sort(reverse=True)
    parts = []
    chars = 0
    for _, ch_name, excerpt in matches[:3]:
        if chars + len(excerpt) > max_chars:
            break
        parts.append(f"[From {ch_name}]: {excerpt}")
        chars += len(excerpt)

    return "\n\n".join(parts)


def write_chapter(
    *,
    brief: str,
    style_doc: str,
    previous_chapter: str,
    librarian,
    prompts_dir: Path,
    model: str,
    max_tokens: int = 8192,
    revision_feedback: str | None = None,
    previous_draft: str | None = None,
    client: LLMClient | None = None,
    chapters_dir: Path | None = None,
) -> tuple[str, dict]:
    """Write (or revise) a single chapter.

    Returns:
        (chapter_text, stats_dict) where stats_dict has input_tokens,
        output_tokens, agent_calls keys.
    """
    system_prompt = _load_system_prompt(prompts_dir, style_doc)

    # Build user prompt — limited cognition: only brief + previous chapter
    parts: list[str] = []
    parts.append(f"## Chapter Brief\n\n{brief}")

    if previous_chapter.strip():
        # Only include the tail for context
        tail = previous_chapter[-3000:] if len(previous_chapter) > 3000 else previous_chapter
        if len(previous_chapter) > 3000:
            # Break at paragraph boundary
            nl = tail.find("\n\n")
            if nl != -1 and nl < len(tail) // 2:
                tail = tail[nl + 2:]
        parts.append(f"## Previous Chapter (ending)\n\n{tail}")

    if revision_feedback and previous_draft:
        parts.append(f"## Revision Required\n\nYour previous draft needs revision. Reviewer feedback:\n\n{revision_feedback}")
        parts.append(f"## Your Previous Draft\n\n{previous_draft}")
        parts.append("\nRevise the chapter addressing the feedback above. Write the complete revised chapter.")
    else:
        parts.append("\nWrite the complete chapter now.")

    user_prompt = "\n\n".join(parts)

    if client is None:
        raise RuntimeError("No LLM client provided to forge writer. Set up a provider in the Model settings.")
    messages: list[dict] = [{"role": "user", "content": user_prompt}]
    lore_queries: list[str] = []
    total_input = 0
    total_output = 0
    calls = 0

    while True:
        response = client.create(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=messages,
            tools=[LORE_TOOL],
        )
        total_input += response.usage.input_tokens
        total_output += response.usage.output_tokens
        calls += 1

        if response.stop_reason == "end_turn":
            break

        if response.stop_reason == "tool_use":
            asst_msg = {"role": "assistant", "content": response.content}
            if response.reasoning:
                asst_msg["reasoning"] = response.reasoning
            messages.append(asst_msg)

            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                query = block.input["query"]
                lore_queries.append(query)
                log.info("Forge writer lore query: %s", query)

                lore_bundle = librarian.query(query)

                # If librarian found nothing, search existing chapter drafts
                if lore_bundle.confidence == "low" and chapters_dir:
                    draft_context = _search_drafts(query, chapters_dir)
                    if draft_context:
                        lore_bundle.relevant_passages.append(draft_context)
                        lore_bundle.source_files.append("(previous chapters)")
                        lore_bundle.confidence = "medium"
                        log.info("Augmented lore with draft context for: %s", query[:60])

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps({
                        "passages": lore_bundle.relevant_passages,
                        "sources": lore_bundle.source_files,
                        "confidence": lore_bundle.confidence,
                    }),
                })

            messages.append({"role": "user", "content": tool_results})
            continue

        log.warning("Forge writer: unexpected stop_reason: %s", response.stop_reason)
        break

    # Extract text from final response
    text_parts = []
    for block in response.content:
        if block.type == "text":
            text_parts.append(block.text)
    chapter_text = "\n\n".join(text_parts)

    stats = {"input_tokens": total_input, "output_tokens": total_output, "agent_calls": calls}
    return chapter_text, stats
