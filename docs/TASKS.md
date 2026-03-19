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
- [x] Basic functionality verified with Docker build and tool calling
- [ ] Test with 10-15 queries against real lore, verify accuracy and source attribution
- [ ] Verify prompt caching is working (check API response headers)

## Stage 3 — Prose Writer (CLI)

- [x] Implement `ProseWriter` class with tool-use loop for Librarian queries
  - Proper while loop: model calls query_lore, gets result, may call again or produce final text
  - Handles multiple tool calls per response
  - Logs each lore query made during generation
- [x] Swappable writing styles from writing-styles/*.md (default, literary, pulp)
- [x] Append-only story file output (auto-append configurable, --no-append flag)
- [x] CLI entry point: `python -m src.agents.prose_writer --scene "..."` (also --interactive)
- [ ] Test with 2-3 scenes, verify lore queries fire automatically

## Stage 4 — Orchestrator (CLI)

- [x] Implement `Orchestrator` class with tool-use loop and routing
  - 11 tools: query_lore, write_prose, read_file, write_file, list_files, search_files, request_code_change, delegate_technical, roll_dice, get_story_state, update_story_state
  - Intent routing handled by the model via tool selection (no manual classifier needed)
- [x] Three operating modes:
  - **General**: free-form routing (orchestrator decides intent)
  - **Writer**: project-based in writing/<project>/. Accept/reject/regenerate flow — prose shown before writing to file. Intercepted commands: accept, regenerate, etc.
  - **Roleplay**: chat-based in chats/<project>/. Auto-appends to file. Supports regenerate (replace last) and delete last entry.
- [x] Persona system with tiered loading and token budgeting (ADR-005)
  - Loads core.md, quirks.md, references.md, extended.md in priority order
  - Stops loading when token budget exceeded, logs warning
- [x] Profile system — switchable personas, lore sets, and writing styles
  - Personas: subdirectories of persona/ (narrator, editor, etc.)
  - Lore sets: subdirectories of lore/
  - Writing styles: .md files in writing-styles/
  - All discoverable via GET /api/profiles, switchable via POST /api/profiles/switch
- [x] Technical query delegation — clean agent call without persona overhead (ADR-006)
- [x] Filesystem tools — read/write/list/search within mounted volumes (ADR-003)
  - Path resolution with escape prevention (can't traverse outside content dirs)
  - Covers lore, story, writing, chats, code-requests directories
- [x] Code request tool — writes structured markdown with frontmatter to code-requests/ (ADR-004)
- [x] Dice rolling tool — pure RNG, standard notation (2d6, 1d20+5, 4d6kh3), no LLM overhead (ADR-011)
- [x] Story state tracking — companion .state.yaml files alongside prose, deep merge updates (ADR-011)
  - State injected into system prompt (outside cached lore) so model sees current plot threads/conditions
  - Structured YAML keeps metadata out of prose files and away from prompt caching
  - Event log with monotonic counter — every prose append, state update, dice roll, and entry removal is indexed
  - Counter exposed as `_update_count` in prompt; full event history available via get_story_state
  - Enables pacing logic: "don't escalate plot thread X until 20+ updates have passed"
- [x] Response logging to story/logs/ directory (ADR-009)
- [x] Conversation history maintained in memory across turns
- [x] CLI entry point: `python -m src.main`
- [ ] Full routing test with real API key across all three modes

## Stage 5 — Web Wrapper & Docker

- [x] FastAPI server in `src/web/server.py`
  - Sync Orchestrator calls wrapped in `run_in_executor` (ADR-008)
  - POST /api/chat, GET /api/status, GET / (UI)
  - GET/POST /api/mode — mode switching with project/file selection
  - GET /api/projects — list available projects for current mode
  - GET /api/profiles, POST /api/profiles/switch — profile management
- [x] Simple mobile-friendly web UI — inline HTML, dark theme, responsive (placeholder for React rewrite)
- [x] Dockerfile and docker-compose.yaml
  - Lore mounted read-only; story, writing, chats, code-requests read-write
  - No secrets at build time, env_file mounted at runtime
  - CONTENT_DIR env var for flexible content location
- [x] Docker build and basic functionality verified by user
- [ ] Test: accessible from other devices on same WiFi
- [ ] Test: add to iPad home screen for app-like experience

## Stage 6 — React Frontend

- [x] Scaffold Vite + React + TypeScript + Tailwind CSS in frontend/
- [x] Build integration: multi-stage Docker build, Vite output served by FastAPI as static files
- [x] Profile picker: persona, lore set, writing style dropdowns (centered overlay)
- [x] Mode switcher: general/writer/roleplay with project selection (centered overlay)
- [x] Chat message display with markdown rendering (react-markdown)
- [x] Context usage meter with detailed overlay (lore count, persona, model, turns)
- [x] Header bar: mode indicator, profile button, context button
- [x] Input bar: auto-resize textarea, Enter-to-send, Shift+Enter for newline
- [x] ST screenshot analysis: confirmed no sampling sliders, no sidebar config, centered overlays only
- [x] Writer mode UI: accept/regenerate buttons shown when prose is pending review
- [x] Roleplay mode UI: regenerate and delete-last buttons
- [x] Message editing: click user messages to edit (Ctrl+Enter to save, Esc to cancel)
- [x] Lore file browser: overlay with grouped file list, token counts, markdown editor (@uiw/react-md-editor) with save/discard
  - Backend: GET/PUT /api/lore endpoints with path traversal prevention
  - Saves trigger Librarian reinitialization to pick up changes
- [x] Session management: "+" button in header clears conversation, POST /api/session/new endpoint
- [x] Prose pending indicator: ring highlight on pending-review messages
- [x] Swipe between alternatives: regenerate adds variant to same message slot, arrow navigation
- [x] Streaming progress: SSE endpoint (POST /api/chat/stream) with status/tool/done events
  - Backend: handle_stream() generator yields progress events through tool-use loop
  - Frontend: live status indicator ("Querying lore...", "Writing prose...") with stop button
  - Replaces old synchronous POST /api/chat (kept as fallback)
- [x] Roleplay portraits: IM-style layout with avatar next to assistant messages
  - portraits/ directory mounted read-only, served as static files
  - Current portrait tracked in state file (`portrait` key), switchable per-response by the model
  - Model can update via update_story_state({portrait: "elena-angry.png"}) mid-conversation
  - Portrait preserved per variant in swipe history
  - GET /api/portraits lists available images and current selection
- [ ] SillyTavern reference code at reference/SillyTavern/ (gitignored)

## Tooling & Support

- [x] Site report tool (`tools/site_report.py`) for remote troubleshooting
  - AGENTS.md instructs any Claude instance to run this when users report problems
- [x] Architecture guide for non-technical users (`docs/architecture-guide.html`)

## Future / When Needed

- [ ] Provider abstraction layer — defer until second provider is actually needed (ADR-007)
- [ ] Tier 2 lore scaling — implement when lore exceeds system prompt capacity (ADR-002)
- [ ] Conversation history persistence across browser sessions
- [ ] Undo/confirmation for destructive file operations
- [ ] Streaming tool-use loop for real-time progress feedback (tied to Stage 6 SSE work)
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
