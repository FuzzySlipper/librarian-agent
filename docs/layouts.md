# Layout Configuration

Layouts control the multi-panel grid structure and color theme of the UI. Each layout is a `.md` file in `build/layouts/` using a simple key-value format.

Layouts can be switched from the **Layout** button in the header bar, and edited in-browser via the edit button in the layout picker.

## File Format

```
columns: <css-grid-columns>

[panel-name]
type: <panel-type>
<panel-specific properties>

[another-panel]
type: <panel-type>
...

[style]
--css-variable: value
```

## Top-Level Properties

| Property | Required | Description |
|----------|----------|-------------|
| `columns` | No | CSS `grid-template-columns` value. Defines how many panels and their widths. Default: `100%` (single column). |

Examples:
- `columns: 100%` — single panel, full width
- `columns: 55% 45%` — two panels
- `columns: 10% 80% 10%` — three panels (side frames + center)
- `columns: 22% 56% 22%` — three panels (RPG-style with sidebars)
- `columns: 15% 70% 15%` — three panels (focused writing with margins)

## Panel Sections

Each `[name]` section defines a panel. Panels are rendered left-to-right in the order they appear. The number of panels should match the number of columns.

Panel names are arbitrary (e.g., `[left]`, `[center]`, `[right]`, `[sidebar]`) — they're just labels for organization.

### Panel Types

#### `chat`
The main conversation interface. Every layout needs exactly one chat panel.

```
[center]
type: chat
```

No additional properties. The chat panel contains the message list, input bar, header, and all overlays.

#### `image`
A decorative image panel. Used for visual framing (borders, artwork, atmosphere).

```
[left]
type: image
src: /layout-images/frame-left.png
fit: cover
position: right center
```

| Property | Default | Description |
|----------|---------|-------------|
| `src` | (none) | Image URL. Use `/layout-images/filename.png` for images in `build/layout-images/`. |
| `fit` | `cover` | CSS `background-size`. Options: `cover`, `contain`, `auto`, or pixel/percentage values. |
| `position` | `center center` | CSS `background-position`. Examples: `center center`, `right center`, `left top`, `50% 25%`. |

Images in `build/layout-images/` are served at `/layout-images/`. You can also use external URLs or `/portraits/` paths.

#### `artifact`
Displays generated artifacts (formatted documents like newspapers, letters, journals).

```
[right]
type: artifact
label: Artifact
```

| Property | Default | Description |
|----------|---------|-------------|
| `label` | `Artifact` | Header text shown above the artifact content. |

Artifacts are generated via the `/artifact` command and rendered with format-specific styling (serif fonts for letters, monospace for reports, etc.).

#### `panel`
A generic content panel with a header and placeholder text.

```
[left]
type: panel
label: Status
placeholder: Character sheet and inventory will appear here.
```

| Property | Default | Description |
|----------|---------|-------------|
| `label` | (none) | Header text. If omitted, no header is shown. |
| `placeholder` | (none) | Italic placeholder text shown when the panel is empty. |

#### `empty`
An empty transparent panel. Useful for creating margins or spacing. When a background image is set, empty panels let the background show through fully.

```
[left]
type: empty
```

No additional properties.

## Style Section

The `[style]` section defines CSS custom properties that override the default theme colors. All properties are optional — omit any to keep the default value.

```
[style]
--color-bg: #1a1a2e
--color-surface: #16213e
--color-surface-alt: #0f3460
--color-text: #e0e0e0
--color-text-muted: #888888
--color-accent: #e94560
--color-accent-hover: #ff6b81
--color-input-bg: #222244
--color-border: #333355
```

### Available Color Variables

| Variable | Default | Used For |
|----------|---------|----------|
| `--color-bg` | `#1a1a2e` | Main page background |
| `--color-surface` | `#16213e` | Header, overlays, panel backgrounds |
| `--color-surface-alt` | `#0f3460` | User message bubbles, buttons, secondary surfaces |
| `--color-text` | `#e0e0e0` | Primary text color |
| `--color-text-muted` | `#888888` | Secondary text, labels, timestamps |
| `--color-accent` | `#e94560` | Active states, highlights, prose borders |
| `--color-accent-hover` | `#ff6b81` | Hover state for accented elements |
| `--color-input-bg` | `#222244` | Text inputs, selects, code blocks |
| `--color-border` | `#333355` | Borders, dividers, separators |

### Color Tips

- Keep sufficient contrast between `--color-text` and `--color-bg` for readability
- `--color-surface` should be slightly lighter/darker than `--color-bg` for depth
- `--color-accent` is used for interactive elements — pick something that stands out
- All colors support CSS formats: hex (`#ff6b81`), rgb (`rgb(255,107,129)`), hsl (`hsl(350,100%,71%)`)

## Background Images

Background images are set separately from layouts via the **Layout** picker's "Change background" option. They're stored in `build/backgrounds/` and displayed behind all panels. When a background is active:

- `bg-bg` surfaces become 85% opaque
- `bg-surface` surfaces become 90% opaque
- Empty panels are fully transparent, showing the background
- The background is fixed (doesn't scroll with content)

Background selection is stored in the browser (localStorage) and persists independently of layout choice.

## Example Layouts

### Minimal (default)
```
columns: 100%

[center]
type: chat
```

### Writer Focus
```
columns: 15% 70% 15%

[left]
type: empty

[center]
type: chat

[right]
type: empty

[style]
--color-bg: #1c1c1c
--color-accent: #9cdcfe
```

### Framed with Side Art
```
columns: 10% 80% 10%

[left]
type: image
src: /layout-images/frame-left.png
fit: cover
position: right center

[center]
type: chat

[right]
type: image
src: /layout-images/frame-right.png
fit: cover
position: left center

[style]
--color-bg: #0a0a12
--color-accent: #c4a35a
```

### RPG with Artifact Sidebar
```
columns: 22% 56% 22%

[left]
type: panel
label: Status
placeholder: Character status will appear here.

[center]
type: chat

[right]
type: artifact
label: Artifact

[style]
--color-bg: #0d1117
--color-accent: #58a6ff
```

### Split View (Chat + Artifact)
```
columns: 55% 45%

[left]
type: chat

[right]
type: artifact
label: Artifact
```
