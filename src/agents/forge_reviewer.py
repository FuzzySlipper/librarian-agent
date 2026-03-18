"""StoryForge review agent — scores chapters on a rubric.

Uses DelegatePool for simple prompt-in/text-out evaluation. The reviewer
returns structured JSON scores which are parsed into a ReviewResult.
"""

import json
import logging
from pathlib import Path

from src.agents.delegate import DelegatePool, Provider, Task
from src.models import ReviewResult

log = logging.getLogger(__name__)


def _load_reviewer_prompt(prompts_dir: Path) -> str:
    """Load the reviewer system prompt from forge-prompts/reviewer.md."""
    prompt_file = prompts_dir / "reviewer.md"
    if prompt_file.exists():
        return prompt_file.read_text(encoding="utf-8")
    return _DEFAULT_REVIEWER_PROMPT


_DEFAULT_REVIEWER_PROMPT = """\
You are a meticulous fiction editor reviewing a chapter draft. Score the \
chapter on four dimensions (1-10 scale) and provide specific, actionable \
feedback.

## Scoring Rubric

**CONTINUITY** (weight: 0.3)
- Character details match the lore and previous chapter
- Timeline consistency — events follow logically
- No contradictions with established facts
- Setting details are consistent

**BRIEF ADHERENCE** (weight: 0.3)
- All required plot beats from the chapter brief are present
- Character arc progression matches the specification
- Foreshadowing is planted as instructed
- Nothing critical from the brief is missing

**VOICE CONSISTENCY** (weight: 0.2)
- Prose style matches the style document
- Consistent POV and tense throughout
- Tone matches the intended atmosphere
- Character voices are distinct and consistent with their bios

**QUALITY** (weight: 0.2)
- Show-don't-tell: scenes are dramatized, not summarized
- Varied sentence structure and rhythm
- Dialogue feels natural and serves the scene
- Pacing is appropriate — no rushed or dragging sections
- Emotional beats land effectively

## Output Format

You MUST respond with valid JSON in exactly this format:

```json
{
  "continuity": <score 1-10>,
  "brief_adherence": <score 1-10>,
  "voice_consistency": <score 1-10>,
  "quality": <score 1-10>,
  "feedback": "<specific, actionable feedback — what needs to change and why>"
}
```

Be honest in your scoring. A 7 means competent but could be better. \
An 8 means good. A 9 means excellent. A 10 is reserved for exceptional work. \
Scores below 5 indicate serious problems.

In your feedback, cite specific passages or issues. Don't just say "improve \
pacing" — say WHERE the pacing drags and suggest how to fix it.
"""


def _parse_review_json(text: str, threshold: float) -> ReviewResult:
    """Parse the reviewer's JSON output into a ReviewResult."""
    # Try to extract JSON from the response (may be wrapped in markdown code block)
    json_str = text.strip()
    if "```json" in json_str:
        start = json_str.index("```json") + 7
        end = json_str.index("```", start)
        json_str = json_str[start:end].strip()
    elif "```" in json_str:
        start = json_str.index("```") + 3
        end = json_str.index("```", start)
        json_str = json_str[start:end].strip()

    data = json.loads(json_str)

    continuity = float(data["continuity"])
    brief_adherence = float(data["brief_adherence"])
    voice_consistency = float(data["voice_consistency"])
    quality = float(data["quality"])

    overall = (
        continuity * 0.3
        + brief_adherence * 0.3
        + voice_consistency * 0.2
        + quality * 0.2
    )

    return ReviewResult(
        continuity=continuity,
        brief_adherence=brief_adherence,
        voice_consistency=voice_consistency,
        quality=quality,
        overall=round(overall, 2),
        feedback=data.get("feedback", ""),
        passed=overall >= threshold,
    )


def review_chapter(
    *,
    chapter_text: str,
    brief: str,
    style_doc: str,
    previous_chapter: str,
    prompts_dir: Path,
    model: str,
    threshold: float = 7.0,
) -> tuple[ReviewResult, dict]:
    """Review a single chapter draft against its brief.

    Returns:
        (ReviewResult, stats_dict)
    """
    system_prompt = _load_reviewer_prompt(prompts_dir)

    parts: list[str] = [
        f"## Style Document\n\n{style_doc}",
        f"## Chapter Brief\n\n{brief}",
    ]

    if previous_chapter.strip():
        tail = previous_chapter[-2000:] if len(previous_chapter) > 2000 else previous_chapter
        parts.append(f"## Previous Chapter (ending)\n\n{tail}")

    parts.append(f"## Chapter Draft to Review\n\n{chapter_text}")
    parts.append("\nScore this chapter according to the rubric. Return JSON only.")

    user_prompt = "\n\n".join(parts)

    pool = DelegatePool()
    result = pool.run_single(Task(
        id="review",
        system=system_prompt,
        prompt=user_prompt,
        provider=Provider.ANTHROPIC,
        model=model,
        max_tokens=2048,
        temperature=0.3,  # Low temp for consistent scoring
    ))

    stats = {"input_tokens": 0, "output_tokens": 0, "agent_calls": 1}

    if result.error:
        log.error("Review failed: %s", result.error)
        # Return a failing review so the chapter gets flagged
        return ReviewResult(
            continuity=0, brief_adherence=0, voice_consistency=0, quality=0,
            overall=0, feedback=f"Review error: {result.error}", passed=False,
        ), stats

    try:
        review = _parse_review_json(result.content, threshold)
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        log.error("Failed to parse review JSON: %s\nRaw: %s", e, result.content[:500])
        return ReviewResult(
            continuity=0, brief_adherence=0, voice_consistency=0, quality=0,
            overall=0, feedback=f"Parse error: {e}. Raw response: {result.content[:300]}",
            passed=False,
        ), stats

    return review, stats


def review_window(
    *,
    chapters_text: str,
    briefs_text: str,
    window_chapters: list[str],
    prompts_dir: Path,
    model: str,
) -> dict:
    """Review a window of chapters for cross-chapter coherence (stage 4).

    Returns dict with 'chapter_reviews' and 'stats' keys.
    """
    system_prompt = (
        "You are reviewing a group of consecutive chapters for cross-chapter "
        "coherence. Check for:\n"
        "- Continuity errors between chapters\n"
        "- Pacing issues across the sequence\n"
        "- Dropped or forgotten plot threads\n"
        "- Repeated information or redundant scenes\n"
        "- Character consistency across chapters\n\n"
        "For each chapter in the window, provide a score (1-10) and specific "
        "feedback on cross-chapter issues.\n\n"
        "Respond with JSON:\n"
        "```json\n"
        '{\n  "chapters": {\n'
        '    "ch-NN": {"score": <1-10>, "feedback": "..."},\n'
        "    ...\n  }\n}\n```"
    )

    user_prompt = f"## Chapter Briefs\n{briefs_text}\n\n## Chapter Texts\n{chapters_text}"

    pool = DelegatePool()
    result = pool.run_single(Task(
        id="quality-window",
        system=system_prompt,
        prompt=user_prompt,
        provider=Provider.ANTHROPIC,
        model=model,
        max_tokens=4096,
        temperature=0.3,
    ))

    stats = {"input_tokens": 0, "output_tokens": 0, "agent_calls": 1}

    if result.error:
        log.error("Window review failed: %s", result.error)
        return {"chapter_reviews": {}, "stats": stats}

    try:
        text = result.content.strip()
        if "```json" in text:
            start = text.index("```json") + 7
            end = text.index("```", start)
            text = text[start:end].strip()
        elif "```" in text:
            start = text.index("```") + 3
            end = text.index("```", start)
            text = text[start:end].strip()

        data = json.loads(text)
        chapter_reviews = data.get("chapters", {})
    except (json.JSONDecodeError, ValueError) as e:
        log.error("Failed to parse window review: %s", e)
        chapter_reviews = {}

    return {"chapter_reviews": chapter_reviews, "stats": stats}
