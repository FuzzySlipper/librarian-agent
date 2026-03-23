"""StoryForge — autonomous long-form story generation pipeline.

Treats fiction writing like a software project: plan -> design -> implement ->
review -> QA.  All intermediate artifacts are markdown files the user can
inspect and hand-edit between runs.

Usage:
    from src.services.forge import ForgeProject

    project = ForgeProject("my-novel", config)
    project.create()                    # Stage 1 prep — dirs + manifest
    for event in project.run_pipeline(librarian):
        send_sse(event)                 # Yields progress events for stages 2-5
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator

import yaml

from src.agents.delegate import DelegatePool, Provider, Task
from src.config import AppConfig
from src.models import ChapterStatus, ForgeManifest, ForgeStats, ReviewResult

log = logging.getLogger(__name__)

# In-memory lock — prevents two pipelines on the same project
_running: set[str] = set()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── ForgeProject ─────────────────────────────────────────────────────


class ForgeProject:
    """Manages a single StoryForge project lifecycle."""

    def __init__(self, name: str, config: AppConfig):
        self.name = name
        self.config = config
        self.root = config.paths.forge / name
        self.manifest_path = self.root / "manifest.yaml"
        self.plan_dir = self.root / "plan"
        self.chapters_dir = self.root / "chapters"
        self.output_dir = self.root / "output"
        self.manifest: ForgeManifest | None = None

    # ── Directory & manifest management ──────────────────────────────

    def create(self) -> ForgeManifest:
        """Create project directory structure and initial manifest."""
        for d in (self.plan_dir, self.chapters_dir, self.output_dir):
            d.mkdir(parents=True, exist_ok=True)

        now = _now()
        self.manifest = ForgeManifest(
            project_name=self.name,
            stage="planning",
            pause_after_ch1=self.config.forge.pause_after_ch1,
            created_at=now,
            updated_at=now,
        )
        self._save_manifest()
        log.info("Created forge project: %s", self.name)
        return self.manifest

    def load(self) -> ForgeManifest:
        """Load manifest from disk, auto-fixing common schema issues."""
        if not self.manifest_path.exists():
            raise FileNotFoundError(f"No manifest for forge project: {self.name}")
        raw = yaml.safe_load(self.manifest_path.read_text(encoding="utf-8")) or {}
        raw = self._normalize_manifest(raw)
        try:
            self.manifest = ForgeManifest(**raw)
        except Exception as e:
            log.warning("Manifest validation failed, rebuilding from files: %s", e)
            self.manifest = self._rebuild_manifest_from_files(raw)
        return self.manifest

    def _normalize_manifest(self, raw: dict) -> dict:
        """Fix common schema mismatches from LLM-generated manifests."""
        # Fix stage values
        stage_map = {
            "active": "writing", "in-progress": "writing",
            "planned": "planning", "complete": "done", "completed": "done",
            "draft": "writing",
        }
        if raw.get("stage") in stage_map:
            raw["stage"] = stage_map[raw["stage"]]
        valid_stages = {"planning", "design", "writing", "quality", "assembly", "done"}
        if raw.get("stage") not in valid_stages:
            raw["stage"] = "planning"

        # Fix chapter keys and statuses
        status_map = {
            "completed": "done", "complete": "done",
            "in_progress": "writing", "in-progress": "writing",
            "planned": "pending", "queued": "pending",
            "draft": "writing", "drafted": "done",
        }
        if "chapters" in raw and isinstance(raw["chapters"], dict):
            fixed_chapters = {}
            for key, ch in raw["chapters"].items():
                # Normalize key: "1" -> "ch-01", "ch-1" -> "ch-01"
                norm_key = self._normalize_chapter_key(key)
                if isinstance(ch, dict):
                    if ch.get("status") in status_map:
                        ch["status"] = status_map[ch["status"]]
                    # Strip unknown fields that Pydantic won't accept
                    valid_fields = {"status", "revision_count", "word_count", "scores", "feedback"}
                    ch = {k: v for k, v in ch.items() if k in valid_fields}
                    fixed_chapters[norm_key] = ch
                else:
                    fixed_chapters[norm_key] = {}
            raw["chapters"] = fixed_chapters

        # Strip extra top-level fields Pydantic won't accept
        valid_top = {
            "project_name", "stage", "chapter_count", "chapters",
            "paused", "pause_after_ch1", "arc_type", "stats",
            "created_at", "updated_at",
        }
        raw = {k: v for k, v in raw.items() if k in valid_top}

        # Ensure project_name
        raw.setdefault("project_name", self.name)

        return raw

    @staticmethod
    def _normalize_chapter_key(key: str) -> str:
        """Normalize chapter keys to 'ch-NN' format."""
        key = str(key).strip()
        # Bare number: "1" -> "ch-01"
        try:
            num = int(key)
            return f"ch-{num:02d}"
        except ValueError:
            pass
        # "ch-1" or "ch-01" -> "ch-01" (always zero-pad)
        if key.startswith("ch-"):
            try:
                num = int(key[3:])
                return f"ch-{num:02d}"
            except ValueError:
                pass
        return key

    def _rebuild_manifest_from_files(self, raw: dict) -> ForgeManifest:
        """Build a valid manifest by scanning the project directory."""
        now = _now()
        ch_keys = self._discover_chapters()
        chapters = {}
        for ch_key in ch_keys:
            draft = self.chapters_dir / f"{ch_key}-draft.md"
            if draft.exists():
                text = draft.read_text(encoding="utf-8")
                chapters[ch_key] = ChapterStatus(status="done", word_count=len(text.split()))
            else:
                chapters[ch_key] = ChapterStatus()

        # Determine stage from file state
        stage = "planning"
        if self._design_complete():
            stage = "design"
            if any(ch.status == "done" for ch in chapters.values()):
                stage = "writing"

        manifest = ForgeManifest(
            project_name=self.name,
            stage=stage,
            chapter_count=len(ch_keys),
            chapters=chapters,
            pause_after_ch1=self.config.forge.pause_after_ch1,
            created_at=raw.get("created_at", now),
            updated_at=now,
        )
        # Save the fixed manifest
        self.manifest = manifest
        self._save_manifest()
        log.info("Rebuilt manifest for %s: stage=%s, %d chapters", self.name, stage, len(ch_keys))
        return manifest

    def _save_manifest(self) -> None:
        """Persist manifest to disk."""
        if self.manifest is None:
            return
        self.manifest.updated_at = _now()
        self.manifest_path.write_text(
            yaml.dump(self.manifest.model_dump(), default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )

    def _update_chapter(self, ch_key: str, **kwargs) -> None:
        """Update a chapter's status fields and save."""
        if self.manifest is None:
            return
        ch = self.manifest.chapters.get(ch_key)
        if ch is None:
            ch = ChapterStatus()
            self.manifest.chapters[ch_key] = ch
        for k, v in kwargs.items():
            setattr(ch, k, v)
        self._save_manifest()

    def _set_stage(self, stage: str) -> None:
        if self.manifest:
            self.manifest.stage = stage
            self._save_manifest()

    def _record_timing(self, stage: str, phase: str) -> None:
        """Record start/end timing for a pipeline stage."""
        if self.manifest is None:
            return
        if stage not in self.manifest.stats.stage_timing:
            self.manifest.stats.stage_timing[stage] = {}
        self.manifest.stats.stage_timing[stage][phase] = _now()
        self._save_manifest()

    def _bump_stats(self, input_tokens: int = 0, output_tokens: int = 0, agent_calls: int = 0) -> None:
        """Increment running token/call counters."""
        if self.manifest is None:
            return
        self.manifest.stats.total_input_tokens += input_tokens
        self.manifest.stats.total_output_tokens += output_tokens
        self.manifest.stats.agent_calls += agent_calls
        # Don't save on every bump — caller saves when appropriate

    # ── Resume detection ─────────────────────────────────────────────

    def _design_complete(self) -> bool:
        """Check if stage 2 outputs already exist (user may have edited them)."""
        outline = self.plan_dir / "outline.md"
        style = self.plan_dir / "style.md"
        briefs = sorted(self.chapters_dir.glob("ch-*-brief.md"))
        return outline.exists() and style.exists() and len(briefs) > 0

    def _discover_chapters(self) -> list[str]:
        """Return sorted chapter keys from existing brief files."""
        briefs = sorted(self.chapters_dir.glob("ch-*-brief.md"))
        keys = []
        for b in briefs:
            # ch-01-brief.md -> ch-01
            parts = b.stem.split("-brief")
            if parts:
                keys.append(parts[0])
        return keys

    def _next_pending_chapter(self) -> str | None:
        """Find the first chapter not yet in 'done' or 'flagged' status."""
        if self.manifest is None:
            return None
        for ch_key in self._discover_chapters():
            ch = self.manifest.chapters.get(ch_key)
            if ch is None or ch.status not in ("done", "flagged"):
                return ch_key
        return None

    # ── Pipeline entry point ─────────────────────────────────────────

    def run_design(self, librarian, client=None, resolved_models: dict | None = None) -> Generator[dict, None, None]:
        """Run only the design stage (planner creates outline, style, briefs, lore).

        Args:
            librarian: Initialized Librarian agent.
            client: LLMClient to use. If None, agents fall back to their defaults.
            resolved_models: Dict mapping role names to actual model IDs (not aliases).

        Stops after design. User reviews output, then runs run_pipeline() to write.
        """
        if self.name in _running:
            yield {"event": "error", "message": f"Pipeline already running for {self.name}"}
            return

        _running.add(self.name)
        try:
            self.load()
            assert self.manifest is not None

            if self._design_complete():
                yield {"event": "stage", "stage": "design",
                       "message": "Design files already exist. Review them and run `/forge start` when ready."}
                # Still update manifest chapter count from briefs
                ch_keys = self._discover_chapters()
                self.manifest.chapter_count = len(ch_keys)
                for ch_key in ch_keys:
                    if ch_key not in self.manifest.chapters:
                        self.manifest.chapters[ch_key] = ChapterStatus()
                self._set_stage("design")
                self._save_manifest()
                return

            self._set_stage("design")
            self._record_timing("design", "start")
            yield {"event": "stage", "stage": "design", "message": "Starting design phase..."}
            yield from self._run_design(librarian, client=client, resolved_models=resolved_models)
            self._record_timing("design", "end")

            # Discover chapters from briefs
            ch_keys = self._discover_chapters()
            self.manifest.chapter_count = len(ch_keys)
            for ch_key in ch_keys:
                if ch_key not in self.manifest.chapters:
                    self.manifest.chapters[ch_key] = ChapterStatus()
            self._save_manifest()

            yield {"event": "complete", "stage": "design",
                   "message": f"Design complete — {len(ch_keys)} chapters planned. "
                              f"Review the files in plan/ and chapters/, then run `/forge start` to begin writing."}
        except Exception as e:
            log.exception("Forge design error for %s", self.name)
            yield {"event": "error", "message": str(e)}
        finally:
            _running.discard(self.name)

    def run_pipeline(self, librarian, client=None, resolved_models: dict | None = None) -> Generator[dict, None, None]:
        """Execute the writing pipeline (stages 3-5), yielding SSE events.

        Design must be complete before calling this. If not, runs design first.
        """
        if self.name in _running:
            yield {"event": "error", "message": f"Pipeline already running for {self.name}"}
            return

        _running.add(self.name)
        try:
            self.load()
            yield from self._run_pipeline_inner(librarian, client=client, resolved_models=resolved_models)
        except Exception as e:
            log.exception("Forge pipeline error for %s", self.name)
            yield {"event": "error", "message": str(e)}
        finally:
            _running.discard(self.name)

    def _run_pipeline_inner(self, librarian, client=None, resolved_models: dict | None = None) -> Generator[dict, None, None]:
        assert self.manifest is not None

        # ── Stage 2: Design ──────────────────────────────────────────
        if self.manifest.stage in ("planning", "design") and not self._design_complete():
            self._set_stage("design")
            self._record_timing("design", "start")
            yield {"event": "stage", "stage": "design", "message": "Starting design phase..."}
            yield from self._run_design(librarian, client=client, resolved_models=resolved_models)
            self._record_timing("design", "end")

            # Reload chapter count from briefs
            ch_keys = self._discover_chapters()
            self.manifest.chapter_count = len(ch_keys)
            for ch_key in ch_keys:
                if ch_key not in self.manifest.chapters:
                    self.manifest.chapters[ch_key] = ChapterStatus()
            self._save_manifest()
        elif self.manifest.stage in ("planning", "design"):
            # Design files exist — resume from them
            yield {"event": "stage", "stage": "design", "message": "Design files found, skipping to writing..."}
            ch_keys = self._discover_chapters()
            self.manifest.chapter_count = len(ch_keys)
            for ch_key in ch_keys:
                if ch_key not in self.manifest.chapters:
                    self.manifest.chapters[ch_key] = ChapterStatus()
            self._save_manifest()

        # ── Stage 3: Writing ─────────────────────────────────────────
        if self.manifest.stage in ("design", "writing"):
            self._set_stage("writing")
            self._record_timing("writing", "start")
            yield {"event": "stage", "stage": "writing", "message": "Starting writing phase..."}
            yield from self._run_writing(librarian, client=client, resolved_models=resolved_models)
            self._record_timing("writing", "end")

            if self.manifest.paused:
                yield {"event": "pause", "reason": "ch1_review",
                       "message": "Chapter 1 complete. Review and /forge approve to continue."}
                return

        # ── Stage 4: Quality pass ────────────────────────────────────
        if self.manifest.stage == "quality" or (
            self.manifest.stage == "writing"
            and self._next_pending_chapter() is None
            and self.config.forge.quality_pass
        ):
            self._set_stage("quality")
            self._record_timing("quality", "start")
            yield {"event": "stage", "stage": "quality", "message": "Starting quality review pass..."}
            yield from self._run_quality_pass(librarian)
            self._record_timing("quality", "end")

        # ── Stage 5: Assembly ────────────────────────────────────────
        if self.manifest.stage in ("quality", "writing"):
            self._set_stage("assembly")
            self._record_timing("assembly", "start")
            yield {"event": "stage", "stage": "assembly", "message": "Assembling final output..."}
            yield from self._run_assembly()
            self._record_timing("assembly", "end")

        self._set_stage("done")
        yield {"event": "complete", "stage": "done",
               "output_path": str(self.output_dir / "final.md"),
               "stats": self.manifest.stats.model_dump()}

    # ── Stage 2: Design ──────────────────────────────────────────────

    def _run_design(self, librarian, client=None, resolved_models: dict | None = None) -> Generator[dict, None, None]:
        """Run the planner agent to produce outline, style, bible, and chapter briefs."""
        from src.agents.forge_planner import run_planner

        rm = resolved_models or {}

        # Gather all stage 1 inputs
        premise_path = self.plan_dir / "premise.md"
        premise = premise_path.read_text(encoding="utf-8") if premise_path.exists() else ""

        # Gather existing lore for context
        lore_context = ""
        lore_dir = self.config.active_lore_path
        if lore_dir.exists():
            for md_file in sorted(lore_dir.rglob("*.md")):
                content = md_file.read_text(encoding="utf-8")
                rel = md_file.relative_to(lore_dir)
                lore_context += f"\n\n--- {rel} ---\n{content}"

        planner_model = rm.get("planner") or self.config.forge.planner_model or self.config.models.orchestrator

        yield {"event": "progress", "action": "design", "message": "Planner agent working..."}

        for event in run_planner(
            premise=premise,
            lore_context=lore_context,
            plan_dir=self.plan_dir,
            chapters_dir=self.chapters_dir,
            lore_dir=self.config.active_lore_path,
            prompts_dir=self.config.paths.forge_prompts,
            model=planner_model,
            stats_callback=self._bump_stats,
            client=client,
        ):
            if event.get("event") == "progress":
                yield event
            # Planner may report files written
            if event.get("event") == "file_written":
                yield {"event": "progress", "action": "design",
                       "message": f"Created {event['path']}"}

        self._save_manifest()

    # ── Stage 3: Writing ─────────────────────────────────────────────

    def _run_writing(self, librarian, client=None, resolved_models: dict | None = None) -> Generator[dict, None, None]:
        """Write chapters one by one with review/revise loop."""
        from src.agents.forge_reviewer import review_chapter
        from src.agents.forge_writer import write_chapter

        rm = resolved_models or {}
        assert self.manifest is not None

        # Load the style doc for the writing prompt
        style_path = self.plan_dir / "style.md"
        style_doc = style_path.read_text(encoding="utf-8") if style_path.exists() else ""

        writer_model = rm.get("writer") or self.config.forge.writer_model or self.config.models.prose_writer
        reviewer_model = rm.get("reviewer") or self.config.forge.reviewer_model or self.config.models.librarian
        max_revisions = self.config.forge.max_revisions
        threshold = self.config.forge.review_threshold

        ch_keys = self._discover_chapters()
        prev_chapter_text = ""

        for i, ch_key in enumerate(ch_keys):
            # Check pause/resume
            if self.manifest.paused:
                return

            ch_status = self.manifest.chapters.get(ch_key)
            if ch_status and ch_status.status in ("done", "flagged"):
                # Load previous chapter text for context even if skipping
                draft_path = self.chapters_dir / f"{ch_key}-draft.md"
                if draft_path.exists():
                    prev_chapter_text = draft_path.read_text(encoding="utf-8")
                continue

            # Read the chapter brief
            brief_path = self.chapters_dir / f"{ch_key}-brief.md"
            if not brief_path.exists():
                log.warning("Missing brief for %s, skipping", ch_key)
                continue

            brief = brief_path.read_text(encoding="utf-8")
            self._update_chapter(ch_key, status="writing")

            yield {"event": "progress", "chapter": ch_key, "action": "writing",
                   "message": f"Writing {ch_key}..."}

            # ── Write ────────────────────────────────────────────────
            draft_text, write_stats = write_chapter(
                brief=brief,
                style_doc=style_doc,
                previous_chapter=prev_chapter_text,
                librarian=librarian,
                prompts_dir=self.config.paths.forge_prompts,
                model=writer_model,
                max_tokens=self.config.forge.chapter_max_tokens,
                client=client,
            )

            draft_path = self.chapters_dir / f"{ch_key}-draft.md"
            draft_path.write_text(draft_text, encoding="utf-8")
            self._bump_stats(**write_stats)

            word_count = len(draft_text.split())
            self._update_chapter(ch_key, word_count=word_count)

            # ── Review/revise loop ───────────────────────────────────
            revision_count = 0
            while True:
                self._update_chapter(ch_key, status="review")
                yield {"event": "progress", "chapter": ch_key, "action": "review",
                       "message": f"Reviewing {ch_key}..."}

                review_result, review_stats = review_chapter(
                    chapter_text=draft_text,
                    brief=brief,
                    style_doc=style_doc,
                    previous_chapter=prev_chapter_text,
                    prompts_dir=self.config.paths.forge_prompts,
                    model=reviewer_model,
                    threshold=threshold,
                    client=client,
                )
                self._bump_stats(**review_stats)

                # Record feedback
                review_path = self.chapters_dir / f"{ch_key}-review.md"
                review_entry = (
                    f"\n\n---\n## Review (revision {revision_count})\n"
                    f"**Scores:** continuity={review_result.continuity:.1f}, "
                    f"brief_adherence={review_result.brief_adherence:.1f}, "
                    f"voice_consistency={review_result.voice_consistency:.1f}, "
                    f"quality={review_result.quality:.1f}, "
                    f"overall={review_result.overall:.1f}\n"
                    f"**Passed:** {review_result.passed}\n\n"
                    f"{review_result.feedback}\n"
                )
                with open(review_path, "a", encoding="utf-8") as f:
                    f.write(review_entry)

                scores = {
                    "continuity": review_result.continuity,
                    "brief_adherence": review_result.brief_adherence,
                    "voice_consistency": review_result.voice_consistency,
                    "quality": review_result.quality,
                    "overall": review_result.overall,
                }
                self._update_chapter(ch_key, scores=scores)
                self.manifest.chapters[ch_key].feedback.append(review_result.feedback)
                self._save_manifest()

                yield {"event": "progress", "chapter": ch_key, "action": "review",
                       "scores": scores, "passed": review_result.passed}

                if review_result.passed:
                    break

                if revision_count >= max_revisions:
                    self._update_chapter(ch_key, status="flagged")
                    self.manifest.stats.chapters_revised += revision_count
                    self._save_manifest()
                    yield {"event": "chapter", "chapter": ch_key, "status": "flagged",
                           "word_count": word_count, "scores": scores}
                    break

                # ── Revise ───────────────────────────────────────────
                revision_count += 1
                self._update_chapter(ch_key, status="revision", revision_count=revision_count)

                yield {"event": "progress", "chapter": ch_key, "action": "revision",
                       "attempt": revision_count,
                       "message": f"Revising {ch_key} (attempt {revision_count})..."}

                draft_text, write_stats = write_chapter(
                    brief=brief,
                    style_doc=style_doc,
                    previous_chapter=prev_chapter_text,
                    librarian=librarian,
                    prompts_dir=self.config.paths.forge_prompts,
                    model=writer_model,
                    max_tokens=self.config.forge.chapter_max_tokens,
                    revision_feedback=review_result.feedback,
                    previous_draft=draft_text,
                    client=client,
                )
                draft_path.write_text(draft_text, encoding="utf-8")
                self._bump_stats(**write_stats)
                word_count = len(draft_text.split())
                self._update_chapter(ch_key, word_count=word_count)
            else:
                # Loop completed without break — shouldn't happen, but handle gracefully
                pass

            if review_result.passed:
                self._update_chapter(ch_key, status="done", revision_count=revision_count)
                self.manifest.stats.chapters_revised += revision_count
                self._save_manifest()
                yield {"event": "chapter", "chapter": ch_key, "status": "done",
                       "word_count": word_count, "scores": scores}

            # Update running context for next chapter
            prev_chapter_text = draft_text

            # Stats update
            yield {"event": "stats",
                   "total_tokens": self.manifest.stats.total_input_tokens + self.manifest.stats.total_output_tokens,
                   "chapters_complete": sum(1 for c in self.manifest.chapters.values() if c.status in ("done", "flagged")),
                   "chapters_total": self.manifest.chapter_count}

            # Pause after chapter 1 if configured
            if i == 0 and self.manifest.pause_after_ch1:
                self.manifest.paused = True
                self._save_manifest()
                return

    # ── Stage 4: Quality pass ────────────────────────────────────────

    def _run_quality_pass(self, librarian) -> Generator[dict, None, None]:
        """Windowed review across chapter groups for cross-chapter coherence."""
        from src.agents.forge_reviewer import review_window

        assert self.manifest is not None

        ch_keys = self._discover_chapters()
        if len(ch_keys) < 2:
            yield {"event": "progress", "action": "quality", "message": "Too few chapters for quality pass, skipping."}
            return

        reviewer_model = self.config.forge.reviewer_model or self.config.models.librarian
        window_size = 4
        stride = 2

        # Build windows with overlap
        windows: list[list[str]] = []
        for start in range(0, len(ch_keys), stride):
            window = ch_keys[start:start + window_size]
            if len(window) >= 2:
                windows.append(window)

        yield {"event": "progress", "action": "quality",
               "message": f"Running {len(windows)} windowed reviews..."}

        # Prepare all window review tasks
        pool = DelegatePool(max_workers=min(len(windows), 4))
        window_data: list[dict] = []

        for wi, window in enumerate(windows):
            chapters_text = ""
            briefs_text = ""
            for ch_key in window:
                draft_path = self.chapters_dir / f"{ch_key}-draft.md"
                brief_path = self.chapters_dir / f"{ch_key}-brief.md"
                if draft_path.exists():
                    chapters_text += f"\n\n--- {ch_key} ---\n{draft_path.read_text(encoding='utf-8')}"
                if brief_path.exists():
                    briefs_text += f"\n\n--- {ch_key} brief ---\n{brief_path.read_text(encoding='utf-8')}"

            window_data.append({
                "index": wi,
                "chapters": window,
                "chapters_text": chapters_text,
                "briefs_text": briefs_text,
            })

        # Run windowed reviews
        for wd in window_data:
            results = review_window(
                chapters_text=wd["chapters_text"],
                briefs_text=wd["briefs_text"],
                window_chapters=wd["chapters"],
                prompts_dir=self.config.paths.forge_prompts,
                model=reviewer_model,
            )
            self._bump_stats(**results.get("stats", {}))

            for ch_key, ch_review in results.get("chapter_reviews", {}).items():
                review_path = self.chapters_dir / f"{ch_key}-review.md"
                review_entry = (
                    f"\n\n---\n## Quality Pass Review (window {wd['index']})\n"
                    f"**Score:** {ch_review.get('score', 'N/A')}\n\n"
                    f"{ch_review.get('feedback', '')}\n"
                )
                with open(review_path, "a", encoding="utf-8") as f:
                    f.write(review_entry)

                yield {"event": "progress", "chapter": ch_key, "action": "quality_review",
                       "score": ch_review.get("score"), "window": wd["chapters"]}

        self._save_manifest()

    # ── Stage 5: Assembly ────────────────────────────────────────────

    def _run_assembly(self) -> Generator[dict, None, None]:
        """Concatenate chapters into final output and generate diagnostics."""
        assert self.manifest is not None

        ch_keys = self._discover_chapters()
        final_parts: list[str] = []

        for i, ch_key in enumerate(ch_keys, 1):
            draft_path = self.chapters_dir / f"{ch_key}-draft.md"
            if draft_path.exists():
                text = draft_path.read_text(encoding="utf-8")
                final_parts.append(f"# Chapter {i}\n\n{text}")

        # Write final
        final_path = self.output_dir / "final.md"
        final_path.write_text("\n\n---\n\n".join(final_parts), encoding="utf-8")

        total_words = sum(
            ch.word_count for ch in self.manifest.chapters.values()
        )

        yield {"event": "progress", "action": "assembly",
               "message": f"Assembled {len(ch_keys)} chapters, {total_words} words."}

        # Generate meta/diagnostics
        meta = self._build_meta(ch_keys, total_words)
        meta_path = self.output_dir / "meta.md"
        meta_path.write_text(meta, encoding="utf-8")

        self._save_manifest()

    def _build_meta(self, ch_keys: list[str], total_words: int) -> str:
        """Build the diagnostics markdown file."""
        assert self.manifest is not None
        s = self.manifest.stats

        lines = [
            f"# StoryForge Diagnostics: {self.name}",
            "",
            f"**Generated:** {_now()}",
            f"**Chapters:** {len(ch_keys)}",
            f"**Total words:** {total_words:,}",
            f"**Arc type:** {self.manifest.arc_type}",
            "",
            "## Token Usage",
            f"- Input tokens: {s.total_input_tokens:,}",
            f"- Output tokens: {s.total_output_tokens:,}",
            f"- Total tokens: {s.total_input_tokens + s.total_output_tokens:,}",
            f"- Agent calls: {s.agent_calls}",
            f"- Chapters revised: {s.chapters_revised}",
            "",
            "## Stage Timing",
        ]

        for stage, timing in s.stage_timing.items():
            start = timing.get("start", "?")
            end = timing.get("end", "?")
            lines.append(f"- **{stage}**: {start} -> {end}")

        lines.extend(["", "## Chapter Details", ""])

        for ch_key in ch_keys:
            ch = self.manifest.chapters.get(ch_key)
            if ch is None:
                continue
            lines.append(f"### {ch_key}")
            lines.append(f"- **Status:** {ch.status}")
            lines.append(f"- **Word count:** {ch.word_count:,}")
            lines.append(f"- **Revisions:** {ch.revision_count}")
            if ch.scores:
                scores_str = ", ".join(f"{k}={v:.1f}" for k, v in ch.scores.items())
                lines.append(f"- **Final scores:** {scores_str}")
            if ch.feedback:
                lines.append("- **Reviewer feedback:**")
                for fi, fb in enumerate(ch.feedback):
                    lines.append(f"  - Revision {fi}: {fb[:200]}{'...' if len(fb) > 200 else ''}")
            lines.append("")

        flagged = [k for k, c in self.manifest.chapters.items() if c.status == "flagged"]
        if flagged:
            lines.extend(["## Flagged Chapters", ""])
            for ch_key in flagged:
                lines.append(f"- **{ch_key}**: hit max revision limit")
            lines.append("")

        return "\n".join(lines)


# ── Project listing ──────────────────────────────────────────────────


def list_forge_projects(config: AppConfig) -> list[dict]:
    """List all forge projects with their current stage."""
    forge_dir = config.paths.forge
    if not forge_dir.exists():
        return []

    projects = []
    for d in sorted(forge_dir.iterdir()):
        if d.is_dir():
            manifest_path = d / "manifest.yaml"
            if manifest_path.exists():
                try:
                    raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
                    projects.append({
                        "name": d.name,
                        "stage": raw.get("stage", "unknown"),
                        "chapter_count": raw.get("chapter_count", 0),
                        "paused": raw.get("paused", False),
                    })
                except Exception:
                    projects.append({"name": d.name, "stage": "error", "chapter_count": 0, "paused": False})

    return projects
