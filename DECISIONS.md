# Architectural Decisions

Numbered decisions with context and rationale. These record *why* choices were made so future sessions don't re-litigate settled questions.

---

## ADR-001: Filesystem as database, no vector DB or ORM

**Status:** Accepted
**Date:** 2026-03-16

Lore files are plain markdown loaded into memory at startup. Story files are append-only markdown. No database, no vector store, no message queue.

**Why:** The system serves 2-3 non-technical users. Filesystem is debuggable, portable, and backed up by normal tools. Vector DB adds complexity without proportional benefit at this scale.

**Revisit when:** Lore corpus exceeds ~50MB or thousands of files, at which point RAG may earn its complexity.

---

## ADR-002: Two-tier lore scaling strategy

**Status:** Accepted
**Date:** 2026-03-16

**Tier 1 (current):** All lore loaded into Librarian's system prompt. Works up to ~1-2MB of markdown. Prompt caching makes subsequent queries cheap.

**Tier 2 (when needed):** Auto-generated index.md with file summaries and tags. Librarian does a two-phase lookup: index call to select relevant files, then answer call with those files loaded. Scales to tens of megabytes.

**Why:** LLM-based file selection from an index outperforms embedding similarity for narrative content (understands relationships like "Elena's mentor" → The Archivist). No external infrastructure needed. The index is generated at startup by scanning file frontmatter/first paragraphs, not maintained manually.

**Revisit when:** Sub-document retrieval becomes necessary (individual files are 10k+ words and only paragraphs are relevant) or corpus exceeds ~2000 files.

---

## ADR-003: Orchestrator has broad filesystem access within container

**Status:** Accepted
**Date:** 2026-03-16

The Orchestrator has read/write tools for the mounted volume directories (`/app/lore`, `/app/story`, `/app/code-requests`). It operates via a tool-use loop — the LLM requests file operations, Python handlers execute them. The LLM never has direct filesystem access.

**Why:** End users are non-technical. The Orchestrator should be able to help them fix, diagnose, and manage their content without requiring them to use a terminal. Docker container is the security boundary — even a worst-case scenario is scoped to mounted volumes. Private tool for a few users, so erring on helpfulness over restriction is appropriate.

**Constraints:** Tools can enforce path scoping (reject paths outside mounted volumes) as a lightweight guardrail.

---

## ADR-004: Code request handoff pattern (LLM-to-LLM)

**Status:** Accepted
**Date:** 2026-03-16

The Orchestrator can write structured markdown files to `/app/code-requests/` describing needed code changes. Users then point their coding assistant (Claude Code, etc.) at the requests directory to evaluate and implement.

**Why:** Non-technical users shouldn't be translating between the Orchestrator's product-level understanding and a coding tool's implementation needs. The Orchestrator has the context to write precise specs (what's broken, what files are likely affected, suggested approach). This creates an async ticket system where both reporter and implementer are LLMs, and the human just approves.

**Format:** Each request is a markdown file with frontmatter (title, priority, date, status) and sections for problem, suggested approach, affected files, and constraints.

---

## ADR-005: Persona system with token budgeting

**Status:** Accepted
**Date:** 2026-03-16

Personality/persona files are structured by priority tier:

- `persona/core.md` — Always loaded. Voice, values, boundaries.
- `persona/quirks.md` — Loaded if budget allows.
- `persona/references.md` — Loaded if budget allows.
- `persona/extended.md` — Only loaded for casual conversation.

A hard token budget (configurable, default ~2000 tokens) caps total persona content in the system prompt. Warnings are generated if persona files exceed budget.

**Why:** Users migrating from ChatGPT custom instructions experience hallucination drift when personality prompts grow too large and compete with task context for model attention. Tiered loading with a budget prevents this. Core personality is always present; flavor text is shed when context space is needed for accuracy.

---

## ADR-006: Intent-based routing with technical query delegation

**Status:** Accepted
**Date:** 2026-03-16

The Orchestrator classifies user intent and routes accordingly. For technical/factual queries, it delegates to a clean agent call with no persona overhead — minimal system prompt optimized for accuracy.

**Why:** Personality context actively harms technical accuracy. The model will hallucinate to stay in character rather than break voice. Delegation gives the best of both worlds: personality for creative interaction, precision for technical questions. The Orchestrator presents the delegated response, so the user experience is seamless.

**Implementation:** Can be a hardcoded tool (`delegate_technical`) or the Orchestrator can decide autonomously via a tool call with a reason field.

---

## ADR-007: Swappable LLM providers, but no premature abstraction

**Status:** Accepted
**Date:** 2026-03-16

Build directly against the Anthropic SDK initially. Provider abstraction layer is deferred until a second provider is actually needed. When built, it will be a thin wrapper (~50-100 lines) normalizing request/response formats.

**Why:** Anthropic SDK prompt caching is a core cost optimization for the Librarian and is provider-specific. Building a full abstraction now would either compromise caching or add unused complexity. The agent architecture already supports mixing providers per-agent (different client instances), so the Librarian can stay on Anthropic for caching while the Prose Writer moves elsewhere.

**Key difference between providers:** Tool use response format (Anthropic: content blocks with `type: "tool_use"`, OpenAI: separate `tool_calls` field). This is the main normalization work.

**Context:** Chinese LLM providers (Kimi, Qwen, etc.) offer Anthropic-compatible API proxies. Content policy landscape may shift — the agent-per-function architecture means only the Prose Writer needs to move if creative content policies change. Provider config lives in mounted `.env` and `config.yaml`, not baked into the Docker image, so switching doesn't require a rebuild.

---

## ADR-008: Synchronous Python, async carve-out for web layer

**Status:** Accepted
**Date:** 2026-03-16

All agent code is synchronous Python. No async/await in the core logic.

**Why:** Simpler debugging for non-technical users and contributors. The system handles one user request at a time — there's no concurrency benefit.

**Exception:** Stage 5 (FastAPI web wrapper) is inherently async. Synchronous SDK calls inside FastAPI will need `run_in_executor` or the sync adapter to avoid blocking the event loop. This is a localized concern in `src/web/server.py`, not a reason to make everything async.

---

## ADR-009: Response logging for portability

**Status:** Accepted
**Date:** 2026-03-16

The Orchestrator's conversational responses (not just prose output) should be logged to the mounted volume.

**Why:** If a provider disappears or changes terms, generated content shouldn't be trapped in ephemeral API calls. The append-only story file already captures prose output. Logging planning discussions and creative direction provides a complete record. Also useful for the users to review what was discussed across sessions.

---

## ADR-010: Task and decision tracking in markdown, no external tooling

**Status:** Accepted
**Date:** 2026-03-16

Project tasks tracked in `TASKS.md`, architectural decisions in `DECISIONS.md` (this file). Both are plain markdown in the repo.

**Why:** MCP task systems add overhead and dependencies for something that's essentially a list in a file. The primary risk is losing architectural context between coding sessions. Markdown files in the repo are readable by any coding assistant, greppable, and versioned by git. Decisions are preserved with rationale so future sessions don't re-litigate settled questions.

---

## ADR-011: Dice rolls and companion state files for plot progression

**Status:** Accepted
**Date:** 2026-03-17

Non-LLM execution logic (dice rolls) and structured narrative metadata (story state) are handled through dedicated orchestrator tools rather than prompt engineering hacks.

**Dice rolling:** `roll_dice` tool provides pure RNG with standard notation (2d6, 1d20+5, 4d6kh3). The model calls it when randomness should influence events — combat, encounters, plot forks. No LLM involved in the roll itself.

**Story state:** `get_story_state` / `update_story_state` tools read/write a companion `.state.yaml` file alongside the active prose/chat file (e.g. `chapter-03.state.yaml` sits next to `chapter-03.md`). State tracks plot threads, character conditions, relationship levels, tension — anything the model needs to remember across turns but that shouldn't live in prose.

**Why companion files instead of prompt metadata:** Users were injecting tracking metadata into SillyTavern prompts, which (a) clutters the context where it can affect prose quality, (b) breaks prompt caching since the system prompt changes every turn, (c) mixes structured data with unstructured prose. Companion YAML files keep state structured, separate from prose, and outside the cached lore/persona system prompt. The state *summary* is injected into the non-cached portion of the prompt so the model sees it without cache invalidation.

**Event log and pacing:** Every mutation (prose append, state update, dice roll, entry removal) increments a monotonic `_event_counter` and appends to a capped `_events` list (last 50). The counter is surfaced to the model as `_update_count` in the state summary. This gives the LLM a sense of time — it can check "how many updates since the last major plot event" and pace escalation accordingly. The full event history is available via `get_story_state` for more detailed reasoning.

**Why not a database:** Consistent with ADR-001. YAML files in the mounted volume are human-readable, editable, and backed up alongside the prose. No additional dependencies.
