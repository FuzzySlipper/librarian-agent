# Game → Forge Integration: Automated Narrative from Game Data

## Concept

Turn game sessions into dramatized fiction by feeding structured game events into the forge pipeline. Games with rich emergent narratives (Rimworld, Dwarf Fortress, Civilization, Crusader Kings, XCOM) produce compelling stories that players currently write up manually as AARs (After Action Reports). This automates that process with quality prose.

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐     ┌──────────────┐
│  Game Mod    │────▶│  Ingest API  │────▶│  Forge       │────▶│  Narrative   │
│  (exports    │     │  (transforms │     │  Pipeline    │     │  Output      │
│   events)    │     │   to briefs) │     │  (writes     │     │  (chapters)  │
└─────────────┘     └──────────────┘     │   prose)     │     └──────────────┘
                                         └─────────────┘
```

### Layer 1: Game Mod (per-game)

The mod's job is minimal: export structured event data. Not raw save files — curated, narrative-relevant events.

**Export format (universal):**
```json
{
  "game": "rimworld",
  "session_id": "colony-hope-2026",
  "metadata": {
    "game_version": "1.5",
    "mod_version": "0.1",
    "export_date": "2026-03-24T12:00:00Z"
  },
  "world": {
    "name": "Arid Shrubland",
    "description": "A harsh desert biome with limited growing seasons.",
    "rules": ["permadeath", "losing is fun"],
    "era": "Medieval tech start"
  },
  "characters": [
    {
      "id": "pawn_01",
      "name": "Engie Vasquez",
      "traits": ["industrious", "kind", "ugly"],
      "skills": {"construction": 14, "crafting": 12, "social": 3},
      "backstory": "Former naval engineer, crash-landed.",
      "relationships": [
        {"target": "pawn_02", "type": "spouse", "opinion": 85}
      ],
      "status": "alive",
      "injuries": ["scarred left eye"],
      "joined_day": 1
    }
  ],
  "locations": [
    {
      "id": "loc_01",
      "name": "Hope Colony",
      "type": "settlement",
      "description": "A walled compound in the desert, growing slowly."
    }
  ],
  "events": [
    {
      "day": 1,
      "type": "founding",
      "severity": "major",
      "participants": ["pawn_01", "pawn_02", "pawn_03"],
      "description": "Three survivors crash-land and establish a camp.",
      "details": {
        "location": "loc_01",
        "resources": "minimal supplies, one assault rifle"
      }
    },
    {
      "day": 15,
      "type": "raid",
      "severity": "major",
      "participants": ["pawn_01", "pawn_02"],
      "description": "Five tribals attack from the south.",
      "outcome": "Repelled with no casualties. Captured one raider.",
      "details": {
        "enemy_count": 5,
        "enemy_faction": "Blood Crows tribe",
        "damage": "outer wall breached, repaired in 2 days"
      }
    },
    {
      "day": 23,
      "type": "social",
      "severity": "minor",
      "participants": ["pawn_01", "pawn_02"],
      "description": "Engie proposed to Kim. She accepted.",
      "details": {
        "relationship_change": "lovers → engaged"
      }
    },
    {
      "day": 45,
      "type": "construction",
      "severity": "moderate",
      "participants": ["pawn_01", "pawn_03"],
      "description": "Completed the main hall — first large structure.",
      "details": {
        "building": "Great Hall",
        "materials": "granite blocks, wood",
        "impressiveness": "somewhat impressive"
      }
    }
  ]
}
```

### Layer 2: Ingest API (game-agnostic processing + game-specific adapters)

**Endpoint:** `POST /api/forge/ingest`

The ingest layer does three things:

1. **Create lore files** from characters, locations, factions, world rules
2. **Structure events into chapters** using narrative logic
3. **Generate chapter briefs** from event clusters

**Chapter structuring logic:**

Events aren't 1:1 with chapters. The ingest layer groups events into narrative arcs:

- **Time-based clustering**: Events within N days form a candidate chapter
- **Severity weighting**: Major events anchor chapter boundaries
- **Character focus**: Chapters should have a POV or focal character
- **Pacing curve**: Don't put all raids together — interleave action with quiet moments
- **Arc detection**: Identify setup/payoff pairs (someone gets injured → recovery → return to action)

This is where an LLM planner agent adds value. Feed it the raw event list and let it decide the chapter structure, rather than using rigid rules.

**Game-specific adapters:**

Each game needs a thin adapter that knows how to interpret game-specific event types:

```python
class RimworldAdapter:
    """Translate Rimworld events into narrative-relevant descriptions."""

    def interpret_event(self, event: dict) -> dict:
        """Add narrative context to a raw game event."""
        if event["type"] == "raid":
            return {
                **event,
                "narrative_weight": self._raid_weight(event),
                "suggested_tone": "tense" if event["details"]["enemy_count"] > 8 else "action",
                "suggested_pov": self._best_combat_pov(event),
            }
        # ... other event types

    def suggest_chapter_breaks(self, events: list[dict]) -> list[list[dict]]:
        """Group events into chapter-sized clusters."""
        # Rimworld-specific: seasons make natural chapter breaks
        # Major raids and deaths are always chapter boundaries
        ...
```

**Output:** A complete forge project seeded with:
- `plan/premise.md` — Generated from world description + event summary
- `plan/style.md` — Default narrative style or user-specified
- `lore/characters/*.md` — From character export data
- `lore/locations/*.md` — From location data
- `lore/factions/*.md` — From faction data
- `chapters/ch-NN-brief.md` — From structured event clusters

### Layer 3: Forge Pipeline (unchanged)

The existing forge pipeline runs exactly as-is:
- Planner may optionally refine the briefs (or be skipped if ingest produced good ones)
- Writer dramatizes each chapter, querying lore for character details
- Reviewer checks coherence
- Assembly produces final output

## Game-Specific Notes

### Rimworld
**Mod complexity:** Low-medium. Rimworld has excellent C# modding API.
**Event richness:** Very high — raids, social events, mental breaks, construction, trade, weather, injuries, deaths, births, art descriptions, even poetry.
**Natural chapter structure:** Seasons (quadrums) map well to chapters. Each quadrum has a rhythm: planting/building → events → harvest/crisis.
**Character depth:** Traits, backstories, relationships, skills all provide rich material.
**Unique angle:** Rimworld already has an internal "story AI" (Cassandra, Randy, Phoebe) — the narrative system would be dramatizing what that AI decided to do.
**Key events to export:** Colony founding, raids, deaths, marriages, mental breaks, art created, buildings completed, caravan events, quest outcomes, prisoner interactions.

### Dwarf Fortress
**Mod complexity:** Medium. DFHack provides extensive Lua scripting.
**Event richness:** Extremely high — possibly the richest emergent narrative of any game.
**Natural chapter structure:** Seasons, migrations, sieges, moods.
**Unique angle:** The procedurally generated history and legends could populate the lore system. A fortress narrative could reference world history seamlessly.

### Civilization
**Mod complexity:** Low. Good Lua/Python modding support.
**Event richness:** Moderate — more strategic/diplomatic, less personal.
**Natural chapter structure:** Eras map to acts. War/peace transitions are natural breaks.
**Character depth:** Lower — leaders are archetypes, not individuals. Works better as geopolitical drama than character fiction.
**Unique angle:** "History book" narrative style — could produce something like a dramatized historical account rather than character-driven fiction.

### Crusader Kings 3
**Mod complexity:** Medium. Good event modding system.
**Event richness:** Very high — personal drama + political intrigue.
**Natural chapter structure:** Character lifetimes, successions, wars, schemes.
**Character depth:** Extremely high — traits, secrets, relationships, rivalries, alliances.
**Unique angle:** This is basically already a story generator — the mod just needs to export what the game already tracks. Could produce Game of Thrones-style dynastic fiction.

### XCOM 2
**Mod complexity:** Medium. Good C# modding.
**Event richness:** High for tactical missions, moderate for strategy layer.
**Natural chapter structure:** Each mission is a natural chapter.
**Character depth:** Customizable soldiers with procedural nicknames and class specializations. Death is permanent and impactful.
**Unique angle:** Military science fiction with named characters who can die. The "memorial" aspect writes itself.

## Implementation Phases

### Phase 1: Core Ingest API
- Define the universal event format (the JSON above)
- Build `POST /api/forge/ingest` endpoint
- Implement basic chapter structuring (time-based + severity)
- Generate lore files from character/location data
- Generate chapter briefs from event clusters
- Output: a forge project ready for `/forge start`

### Phase 2: Rimworld Adapter
- Build the C# mod that exports events
- Implement Rimworld-specific event interpretation
- Add quadrum-based chapter structuring
- Test with real colony data
- Handle Rimworld-specific quirks (art descriptions, mental break flavors, etc.)

### Phase 3: LLM-Powered Chapter Planning
- Instead of rule-based chapter structuring, use a planner agent
- Feed it the raw event timeline and let it decide narrative structure
- Identify dramatic arcs, POV shifts, pacing
- This is the "design" phase but with game data as input

### Phase 4: Interactive Mode
- Real-time export: mod sends events as they happen
- System maintains a running narrative that updates live
- Player can read chapters as they complete during gameplay
- Could integrate with in-game readable books (Rimworld supports custom art/book text)

### Phase 5: Additional Game Adapters
- Prioritize by community demand
- Each adapter is relatively thin once the core works
- Community could contribute adapters for their favorite games

## API Design

### Ingest Endpoint

```
POST /api/forge/ingest
Content-Type: application/json

{
  "game": "rimworld",
  "project_name": "hope-colony",     // forge project name
  "style": "gritty-survival",        // optional: writing style override
  "pov": "rotating",                 // "single:<character_id>" | "rotating" | "omniscient"
  "events": [...],
  "characters": [...],
  "locations": [...],
  "world": {...}
}

Response:
{
  "status": "ok",
  "project": "hope-colony",
  "chapters_planned": 12,
  "characters_imported": 8,
  "locations_imported": 3,
  "message": "Project created. Run /forge design hope-colony to refine, or /forge start hope-colony to begin writing."
}
```

### Live Export Endpoint (Phase 4)

```
POST /api/forge/{project}/events
Content-Type: application/json

{
  "events": [
    {"day": 67, "type": "death", "severity": "critical", ...}
  ]
}

Response:
{
  "status": "ok",
  "events_added": 1,
  "chapters_affected": ["ch-07"],
  "message": "Event added. Chapter 7 brief updated."
}
```

## Open Questions

1. **How much interpretation should the adapter do vs the LLM?** The adapter could just export raw data and let the planner figure out the narrative, or it could provide highly curated narrative hints. Probably start raw and add interpretation if quality is lacking.

2. **POV strategy for multi-character games?** Rimworld colonies have many pawns. Rotating POV per chapter? Single protagonist? Omniscient narrator? Probably make this user-configurable.

3. **How to handle game mechanics in prose?** "Engie's construction skill is 14" → how does the writer know what that means narratively? The adapter should translate mechanics into narrative descriptions ("master builder," "barely competent").

4. **Real-time vs batch?** Batch (export full game, generate story) is simpler and more reliable. Real-time (stream events during gameplay) is cooler but much harder. Start with batch.

5. **Save game vs event log?** Parsing save files gives complete state but is complex and game-version-fragile. Event logs are simpler but miss context. The mod should export events as they happen rather than trying to reconstruct from saves.
