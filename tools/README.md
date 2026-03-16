# Migration Tools

Tools for importing data from SillyTavern and other sources into the Narrative System.

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
