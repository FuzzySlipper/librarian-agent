# Artifacts

Artifacts are in-world documents — newspaper articles, letters, text messages, wanted posters, and more — generated alongside your main story. They use the same lore and context as your regular chat but display in a separate panel so they don't clutter the conversation.

## Quick Start

1. Switch to a layout that has an artifact panel:
   ```
   /layout split
   ```
2. Generate an artifact:
   ```
   /artifact newspaper The king has declared war on the eastern provinces
   ```
3. The artifact appears in the side panel, formatted as a newspaper article.

## Commands

| Command | Description |
|---------|-------------|
| `/artifact <format> <prompt>` | Generate an artifact |
| `/artifact` | List available formats |
| `/artifact-clear` | Clear the artifact panel |

## Formats

| Format | What it generates |
|--------|------------------|
| `newspaper` | News article with headline, byline, and journalistic style |
| `letter` | Written correspondence with salutation and closing |
| `texts` | Chat/text message exchange between characters |
| `social` | Social media post with engagement metrics |
| `journal` | Personal diary entry in first person |
| `report` | Official report, briefing, or dossier |
| `wanted` | Wanted poster or bounty notice |
| `prose` | Generic prose with no specific formatting |

## Examples

```
/artifact newspaper A mysterious fire destroyed the market district last night

/artifact texts Elena texting Marcus about the suspicious stranger at the tavern

/artifact journal Kira's diary entry after discovering the hidden passage

/artifact wanted The bandit leader who robbed the merchant caravan

/artifact report Intelligence briefing on troop movements near the border

/artifact social A viral post about the dragon sighting over the capital
```

## Layouts with Artifact Panels

These layouts include an artifact panel:

- **split** — Chat on the left (55%), artifact on the right (45%). Good for artifact-heavy work.
- **rpg** — Three columns: status panel, chat, artifact panel. Designed for game sessions.

You can also create your own layout with an artifact panel. In your layout MD file, set a panel's type to `artifact`:

```
columns: 60% 40%

[left]
type: chat

[right]
type: artifact
label: Documents
```

## How It Works

When you use `/artifact`, the system:

1. Takes your prompt and the format you chose
2. Sends it to the AI with format-specific instructions (e.g., "write this as a newspaper article with a headline and byline")
3. The AI queries your lore files for accuracy, just like it does for regular writing
4. The result displays in the artifact panel and is saved to the `artifacts/` folder

Artifacts use all the same world-building context as your main conversation — characters, locations, events, and lore are all available. The artifact content doesn't enter your main chat history, so it won't affect the flow of conversation.

## Tips

- Artifacts work best when your lore files have good coverage of the characters, places, and events you're referencing.
- You can generate multiple artifacts in a row — each one replaces the previous in the panel, but all are saved to `artifacts/`.
- Use `/artifact-clear` to empty the panel when you're done.
- The `texts` format works well for showing character relationships through casual conversation.
- The `report` format is great for world-building — intelligence briefings, scientific reports, bureaucratic documents.
