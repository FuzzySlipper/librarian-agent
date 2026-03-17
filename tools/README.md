# Tools

Utilities for the Narrative Orchestration System.

## site_report.py

Generates a structured diagnostic report for remote troubleshooting. When something isn't working, run this to collect system state into a report that can be sent to the developer.

### When to use this

If a user says something like "it's not working" or "I got an error," run this script first. It captures everything a remote developer needs to diagnose the problem without a back-and-forth Q&A.

### Usage

```bash
# Basic report
python tools/site_report.py

# With a description of the problem
python tools/site_report.py --issue "The librarian returns empty results when I ask about Elena"

# Specify output location
python tools/site_report.py --issue "Docker container won't start" -o ~/Desktop/
```

The report is written to `code-requests/` by default (where the developer picks up requests) and includes:
- System info (OS, Python version, Docker status)
- Project state (git branch, recent commits, missing files)
- Content state (lore file count, story size, .env presence)
- API key availability (not the key itself)
- Dependency check
- Recent session logs

### For AI coding assistants

If you are a Claude instance or other AI coding assistant helping a user with this project, and they report a problem:

1. Run `python tools/site_report.py --issue "description of what the user reported"`
2. Read the generated report
3. If you can fix the issue, do so
4. If you can't, tell the user to send the report file to Patch

---

## st_migrator.py

Converts SillyTavern World Info (lorebooks) and Character Cards to markdown format.

## st_migrator.py

Converts SillyTavern World Info (lorebooks) and Character Cards to markdown format.

### Prerequisites

```bash
# No external dependencies - uses only Python standard library
python3 --version  # Requires 3.10+
```

### Finding Your SillyTavern Data

**World Info / Lorebooks:**
```
# Default location on Mac (OrbStack/Docker)
~/OrbStack/docker/volumes/sillytavern/_data/data/default-user/worlds/

# Or if running SillyTavern locally
/path/to/SillyTavern/data/default-user/worlds/
```

**Character Cards:**
```
~/OrbStack/docker/volumes/sillytavern/_data/data/default-user/characters/
# or
/path/to/SillyTavern/data/default-user/characters/
```

### Usage

**Preview what would be created (dry run):**
```bash
python tools/st_migrator.py \\
    --worlds-dir "/path/to/SillyTavern/data/default-user/worlds" \\
    --characters-dir "/path/to/SillyTavern/data/default-user/characters" \\
    --dry-run
```

**Actually perform the migration:**
```bash
python tools/st_migrator.py \\
    --worlds-dir "/path/to/SillyTavern/data/default-user/worlds" \\
    --characters-dir "/path/to/SillyTavern/data/default-user/characters" \\
    -o ~/Documents/narrative-content
```

**Migrate only world info:**
```bash
python tools/st_migrator.py --worlds-dir "/path/to/worlds"
```

**Migrate only characters:**
```bash
python tools/st_migrator.py --characters-dir "/path/to/characters"
```

### What Gets Created

```
~/Documents/narrative-content/lore/
├── world-overview.md          # Index of all world info files
├── characters/
│   ├── elena-vasquez.md       # Main character file
│   ├── the-archivist.md
│   └── elena-vasquez-lorebook/   # Embedded lorebook (if present)
│       ├── entry-0.md
│       └── entry-1.md
├── locations/
│   ├── eldoria.md             # World info file with entries
│   └── the-pale-city.md
├── factions/
│   └── shadowfangs.md
├── events/
├── items/
└── misc/                      # Uncategorized world info
```

### Output Format

**Character files** include:
- Overview (description)
- Personality
- Scenario
- Creator Notes (OOC info)
- First Meeting (greeting)
- Dialogue Style (example messages)
- Special Instructions (system prompt)
- Source metadata as HTML comments

**World Info entries** include:
- Title (from comment or first keyword)
- Original keywords as HTML comments
- Cleaned content ({{user}}/{{char}} macros replaced)

### Post-Migration Cleanup

The migrator uses heuristics to categorize files. You may want to:

1. **Review categorization:**
   ```bash
   # Check if files landed in the right folders
   ls -la ~/Documents/narrative-content/lore/*/
   ```

2. **Merge related files:**
   If "Eldoria" world info has 20 entries about different locations, consider splitting into separate files.

3. **Edit world-overview.md:**
   Add narrative coherence - describe how locations connect, faction relationships, etc.

4. **Clean up character lorebooks:**
   Embedded character lorebooks become separate folders. Consider merging with main character file if small.

### Troubleshooting

**"No PNG metadata" errors:**
- Some PNG files may not be character cards (avatars, backgrounds, etc.)
- The migrator skips these automatically

**Gibberish in output:**
- Very old ST character cards may use different encoding
- Try opening the PNG in ST first and re-exporting

**Missing entries:**
- Disabled entries in ST are skipped (this is correct behavior)
- Check that the JSON files are valid (try opening in a text editor)

### Preserving ST Investment

This tool is intentionally one-way (ST → Markdown). Your ST data is not modified. You can:

1. Keep ST running in parallel during testing
2. Re-run migration if you update ST lorebooks
3. Manually copy new scenes from ST chats to `story/current-draft.md`

Once satisfied with the Narrative System, you can retire ST and archive the data.
