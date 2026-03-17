# Tasks

Active work items grouped by development stage. Mark done with `[x]` but keep entries — the notes preserve implementation context.

---

## Stage 1 — Lore Structure & Migration

- [x] Define lore folder structure (characters/, locations/, factions/, events/)
- [x] Build SillyTavern migration tool (`tools/st_migrator.py`)
- [ ] Migrate actual user lore from SillyTavern — depends on user running migrator against their ST data
- [ ] Review and clean up migrated files (recategorize, merge related entries)
- [ ] Validate: can every factual question about the story world be answered from lore files alone?

## Stage 2 — Librarian (CLI)

- [x] Scaffold `src/` directory structure per AGENTS.md
- [x] Implement `config.py` — Pydantic models for `config.yaml`
- [x] Implement `models.py` — shared data models (LoreBundle, ProseRequest, etc.)
- [x] Implement `Librarian` class — load all lore at startup, query via cached system prompt
  - Prompt caching enabled via `cache_control: {"type": "ephemeral"}` on system prompt
  - JSON response parsing with fallback for non-JSON responses
  - Cache hit/miss logging from API response usage stats
- [ ] Auto-generate lore index from file frontmatter/first paragraphs (prep for Tier 2 scaling, ADR-002)
- [x] CLI entry point: `python -m src.agents.librarian --query "..."` (also --interactive, --summary)
- [ ] Test with 10-15 queries against real lore, verify accuracy and source attribution
- [ ] Verify prompt caching is working (check API response headers)

## Stage 3 — Prose Writer (CLI)

- [x] Implement `ProseWriter` class with tool-use loop for Librarian queries
  - Proper while loop: model calls query_lore, gets result, may call again or produce final text
  - Handles multiple tool calls per response
  - Logs each lore query made during generation
- [x] Append-only story file output (auto-append configurable, --no-append flag)
- [x] CLI entry point: `python -m src.agents.prose_writer --scene "..."` (also --interactive)
- [x] Main entry point updated with /lore and /write commands
- [ ] Test with 2-3 scenes, verify lore queries fire automatically

## Stage 4 — Orchestrator (CLI)

- [x] Implement `Orchestrator` class with tool-use loop and routing
  - 8 tools: query_lore, write_scene, read_file, write_file, list_files, search_files, request_code_change, delegate_technical
  - Intent routing handled by the model via tool selection (no manual classifier needed)
- [x] Persona system with tiered loading and token budgeting (ADR-005)
  - Loads core.md, quirks.md, references.md, extended.md in priority order
  - Stops loading when token budget exceeded, logs warning
  - Sample persona files created in persona/
- [x] Technical query delegation — clean agent call without persona overhead (ADR-006)
- [x] Filesystem tools — read/write/list/search within mounted volumes (ADR-003)
  - Path resolution with escape prevention (can't traverse outside content dirs)
- [x] Code request tool — writes structured markdown with frontmatter to code-requests/ (ADR-004)
- [x] Response logging to story/logs/ directory (ADR-009)
- [x] Conversation history maintained in memory across turns
- [x] CLI entry point: `python -m src.main`
- [ ] Full routing test: lore question → Librarian, scene request → Writer, technical question → delegated, planning → discussion mode

## Stage 5 — Web Wrapper & Docker

- [ ] FastAPI server in `src/web/server.py`
  - Sync SDK calls need `run_in_executor` or sync adapter (ADR-008)
- [ ] Simple mobile-friendly web UI — text in, text out
- [ ] Dockerfile and docker-compose.yaml
  - Lore mounted read-only, story read-write, code-requests read-write
  - No secrets at build time, `.env` mounted at runtime
- [ ] Test: accessible from iPad/phone on same WiFi
- [ ] Add to home screen for app-like experience

## Future / When Needed

- [ ] Provider abstraction layer — defer until second provider is actually needed (ADR-007)
- [ ] Tier 2 lore scaling — implement when lore exceeds system prompt capacity (ADR-002)
- [ ] Conversation history persistence across browser sessions
- [ ] Undo/confirmation for destructive file operations
- [ ] Streaming tool-use loop for real-time progress feedback
- [ ] Token budget management to cap runaway tool-use loops

## Nice to Have / Long-term Ideas

- [ ] **Controlled messaging system** — Unix `.plan`-style message passing between users and the Orchestrator
  - `outbox/`: Orchestrator writes messages on behalf of user, triggers lightweight notification (email webhook, etc.)
  - `inbox/`: External messages land here (email inbound, manual file drop, etc.)
  - `processed/`: Moved here after user explicitly reads them
  - User must explicitly say "check messages" — no ambient polling or auto-ingestion
  - Inbox content presented as quoted data, never injected as system instructions (structural prompt injection defense)
  - Enables "I don't understand this, send it to patch" → patch replies → "read messages from patch" flow
  - Just two more Orchestrator tools (`send_message`, `check_messages`) and a new mounted directory
- [ ] **Cross-LLM handoff improvements** — beyond the code-request markdown pattern, explore tighter integration where the coding assistant can mark requests as "implemented" and the Orchestrator can notify the user on next interaction
- [ ] **Multi-user awareness** — if both users are interacting with the system, lightweight presence/state so the Orchestrator knows "patch updated the lore files 10 minutes ago, you might want to check the changes"
