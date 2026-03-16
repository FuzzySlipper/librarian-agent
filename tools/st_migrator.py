#!/usr/bin/env python3
"""
SillyTavern to Narrative System Migration Tool

Converts SillyTavern data files to the markdown-based lore format.

Usage:
    python st_migrator.py --worlds-dir "/path/to/SillyTavern/data/default-user/worlds" \\
                          --characters-dir "/path/to/SillyTavern/data/default-user/characters" \\
                          --output-dir "~/Documents/narrative-content"

Supports:
    - World Info files (.json) -> lore/locations/ or lore/factions/
    - Character cards (.png with embedded chara metadata) -> lore/characters/
    - Character lorebooks (embedded in cards) -> lore/characters/{name}-lorebook/
"""

import argparse
import base64
import json
import re
import struct
import sys
import zlib
from pathlib import Path
from typing import Any


def sanitize_filename(name: str) -> str:
    """Convert a string to a safe filename."""
    # Remove or replace unsafe characters
    name = re.sub(r'[<>:"/\\|?*]', '', name)
    name = re.sub(r'\s+', '-', name.strip())
    name = re.sub(r'-+', '-', name)
    return name.lower()[:100]  # Limit length


def read_png_metadata(png_path: Path) -> dict[str, Any] | None:
    """
    Read tEXt chunks from PNG file.
    SillyTavern stores character data in 'chara' (v2) or 'ccv3' (v3) chunks.
    """
    try:
        with open(png_path, 'rb') as f:
            # Verify PNG signature
            signature = f.read(8)
            if signature != b'\x89PNG\r\n\x1a\n':
                return None

            chunks = {}
            while True:
                # Read chunk length (4 bytes, big-endian)
                length_bytes = f.read(4)
                if len(length_bytes) < 4:
                    break
                length = struct.unpack('>I', length_bytes)[0]

                # Read chunk type (4 bytes)
                chunk_type = f.read(4)
                if len(chunk_type) < 4:
                    break

                # Read chunk data
                data = f.read(length)
                if len(data) < length:
                    break

                # Read CRC (4 bytes)
                crc = f.read(4)
                if len(crc) < 4:
                    break

                # We're interested in tEXt chunks
                if chunk_type == b'tEXt':
                    # tEXt format: keyword\0text
                    try:
                        decoded = data.decode('latin-1')
                        if '\x00' in decoded:
                            keyword, text = decoded.split('\x00', 1)
                            chunks[keyword] = text
                    except UnicodeDecodeError:
                        continue

                # Stop at IEND
                if chunk_type == b'IEND':
                    break

        # Prefer ccv3 (v3 spec) over chara (v2 spec)
        if 'ccv3' in chunks:
            try:
                decoded = base64.b64decode(chunks['ccv3'])
                return json.loads(decoded)
            except (base64.binascii.Error, json.JSONDecodeError, UnicodeDecodeError):
                pass

        if 'chara' in chunks:
            try:
                decoded = base64.b64decode(chunks['chara'])
                return json.loads(decoded)
            except (base64.binascii.Error, json.JSONDecodeError, UnicodeDecodeError):
                pass

        return None

    except Exception as e:
        print(f"Error reading PNG {png_path}: {e}", file=sys.stderr)
        return None


def parse_world_info(json_path: Path) -> dict[str, Any] | None:
    """Parse a SillyTavern World Info JSON file."""
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        print(f"Error parsing {json_path}: {e}", file=sys.stderr)
        return None


def convert_entry_to_markdown(entry: dict[str, Any]) -> str:
    """Convert a single World Info entry to markdown format."""
    lines = []
    
    # Use comment as header if available, otherwise use first key
    title = entry.get('comment', '').strip()
    if not title and entry.get('key'):
        title = entry['key'][0] if isinstance(entry['key'], list) else str(entry['key'])
    if not title:
        title = f"Entry {entry.get('uid', 'unknown')}"
    
    lines.append(f"# {title}")
    lines.append("")
    
    # Add metadata as HTML comments (not rendered but preserved)
    lines.append("<!-- ST Original Metadata -->")
    if entry.get('key'):
        keys = entry['key'] if isinstance(entry['key'], list) else [entry['key']]
        lines.append(f"<!-- Keywords: {', '.join(keys)} -->")
    
    if entry.get('constant'):
        lines.append("<!-- Constant: Always included -->")
    
    lines.append("")
    
    # Content - clean up {{user}} and {{char}} macros if present
    content = entry.get('content', '').strip()
    if content:
        # Replace common ST macros
        content = content.replace('{{user}}:', '**User**:')
        content = content.replace('{{char}}:', '**Character**:')
        content = content.replace('{{user}}', 'the user')
        content = content.replace('{{char}}', 'the character')
        content = content.replace('*', '*')  # Keep asterisks as italics
        
        lines.append(content)
    
    lines.append("")
    lines.append("---")
    lines.append("")
    
    return '\n'.join(lines)


def categorize_world_info(name: str, entries: list[dict]) -> str:
    """Determine the category of a world info file based on its name and content."""
    name_lower = name.lower()
    
    # Heuristic categorization based on common naming patterns
    if any(word in name_lower for word in ['char', 'person', 'npc']):
        return 'characters'
    elif any(word in name_lower for word in ['place', 'loc', 'city', 'town', 'region', 'world']):
        return 'locations'
    elif any(word in name_lower for word in ['faction', 'group', 'org', 'guild', 'empire']):
        return 'factions'
    elif any(word in name_lower for word in ['item', 'artifact', 'weapon', 'object']):
        return 'items'
    elif any(word in name_lower for word in ['event', 'history', 'timeline']):
        return 'events'
    else:
        # Try to infer from entry content
        for entry in entries[:3]:  # Check first few entries
            content = entry.get('content', '').lower()
            keys = ' '.join(entry.get('key', [])).lower()
            combined = content + ' ' + keys
            
            if any(word in combined for word in [' character', 'personality', 'he', 'she', 'them']):
                return 'characters'
            elif any(word in combined for word in ['city', 'town', 'region', 'forest', 'mountain', 'castle']):
                return 'locations'
        
        return 'misc'  # Default category


def convert_world_info_file(json_path: Path, output_dir: Path) -> tuple[str, Path] | None:
    """
    Convert a World Info JSON file to markdown.
    Returns (category, output_path) for logging.
    """
    data = parse_world_info(json_path)
    if not data:
        return None
    
    entries = data.get('entries', {})
    if not entries:
        print(f"  No entries in {json_path.name}")
        return None
    
    # Convert entries dict to list, sorted by order/displayIndex
    entry_list = []
    for key, entry in entries.items():
        if isinstance(entry, dict):
            entry_list.append(entry)
    
    # Sort by displayIndex or order if available
    entry_list.sort(key=lambda e: (e.get('displayIndex', 999), e.get('order', 100)))
    
    # Skip disabled entries
    active_entries = [e for e in entry_list if not e.get('disable', False)]
    if not active_entries:
        print(f"  All entries disabled in {json_path.name}")
        return None
    
    # Determine category and filename
    category = categorize_world_info(json_path.stem, active_entries)
    safe_name = sanitize_filename(json_path.stem)
    
    # Determine output structure
    if len(active_entries) == 1:
        # Single entry -> single file in category folder
        output_path = output_dir / 'lore' / category / f"{safe_name}.md"
        content = convert_entry_to_markdown(active_entries[0])
    else:
        # Multiple entries -> folder with index.md + entry files, OR single combined file
        # For simplicity, create a combined file with clear sections
        output_path = output_dir / 'lore' / category / f"{safe_name}.md"
        
        lines = [f"# {json_path.stem}", ""]
        lines.append(f"*World Info with {len(active_entries)} entries*")
        lines.append("")
        lines.append("---")
        lines.append("")
        
        for entry in active_entries:
            lines.append(convert_entry_to_markdown(entry))
        
        content = '\n'.join(lines)
    
    # Write file
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    return (category, output_path)


def convert_character_card(png_path: Path, output_dir: Path) -> Path | None:
    """
    Convert a character card PNG to markdown character file.
    Also extracts embedded lorebook if present.
    """
    data = read_png_metadata(png_path)
    if not data:
        return None
    
    # Handle both v1 (flat) and v2/v3 (wrapped in 'data') formats
    if 'data' in data:
        char_data = data['data']
        spec = data.get('spec', 'unknown')
    else:
        char_data = data
        spec = 'v1'
    
    name = char_data.get('name', png_path.stem)
    safe_name = sanitize_filename(name)
    
    # Build character markdown
    lines = [f"# {name}", ""]
    
    # Add metadata section
    lines.append("## Overview")
    lines.append("")
    
    if char_data.get('description'):
        desc = char_data['description'].strip()
        # Clean up common formatting
        desc = desc.replace('{{user}}', 'the user')
        desc = desc.replace('{{char}}', name)
        lines.append(desc)
        lines.append("")
    
    if char_data.get('personality'):
        lines.append("### Personality")
        lines.append("")
        personality = char_data['personality'].replace('{{char}}', name)
        lines.append(personality)
        lines.append("")
    
    if char_data.get('scenario'):
        lines.append("### Scenario")
        lines.append("")
        scenario = char_data['scenario'].replace('{{char}}', name).replace('{{user}}', 'the user')
        lines.append(scenario)
        lines.append("")
    
    # Creator notes (OOC information)
    if char_data.get('creator_notes'):
        lines.append("### Creator Notes")
        lines.append("")
        lines.append(char_data['creator_notes'])
        lines.append("")
    
    # First message / greeting
    if char_data.get('first_mes'):
        lines.append("### First Meeting")
        lines.append("")
        lines.append("*How a typical first interaction might begin:*")
        lines.append("")
        first_mes = char_data['first_mes'].replace('{{char}}', name).replace('{{user}}', 'the user')
        lines.append(f"> {first_mes}")
        lines.append("")
    
    # Example messages (style reference)
    if char_data.get('mes_example'):
        lines.append("### Dialogue Style")
        lines.append("")
        lines.append("*Example of how this character speaks:*")
        lines.append("")
        example = char_data['mes_example'].replace('{{char}}', name).replace('{{user}}', 'the user')
        lines.append(example)
        lines.append("")
    
    # System prompt / custom instructions
    if char_data.get('system_prompt'):
        lines.append("### Special Instructions")
        lines.append("")
        lines.append(char_data['system_prompt'])
        lines.append("")
    
    # Post-history instructions
    if char_data.get('post_history_instructions'):
        lines.append("### Post-History Instructions")
        lines.append("")
        lines.append(char_data['post_history_instructions'])
        lines.append("")
    
    # Extensions (depth prompt, etc.)
    extensions = char_data.get('extensions', {})
    if extensions.get('depth_prompt'):
        dp = extensions['depth_prompt']
        lines.append("### Depth Context")
        lines.append("")
        lines.append(dp.get('prompt', ''))
        lines.append("")
    
    # Tags
    if char_data.get('tags'):
        lines.append("### Tags")
        lines.append("")
        tags = char_data['tags'] if isinstance(char_data['tags'], list) else [char_data['tags']]
        lines.append(', '.join(f"`{t}`" for t in tags))
        lines.append("")
    
    # Source metadata
    lines.append("<!--")
    lines.append(f"Source: SillyTavern Character Card ({spec})")
    lines.append(f"Original file: {png_path.name}")
    if char_data.get('creator'):
        lines.append(f"Creator: {char_data['creator']}")
    if char_data.get('character_version'):
        lines.append(f"Version: {char_data['character_version']}")
    lines.append("-->")
    
    # Write main character file
    output_path = output_dir / 'lore' / 'characters' / f"{safe_name}.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    
    # Handle embedded character book (lorebook)
    char_book = char_data.get('character_book')
    if char_book and char_book.get('entries'):
        book_dir = output_dir / 'lore' / 'characters' / f"{safe_name}-lorebook"
        book_dir.mkdir(parents=True, exist_ok=True)
        
        entries = char_book['entries']
        if isinstance(entries, dict):
            entries = entries.values()
        
        for entry in entries:
            if entry.get('disable'):
                continue
            
            entry_md = convert_entry_to_markdown(entry)
            entry_name = sanitize_filename(entry.get('comment', f"entry-{entry.get('uid', 'unknown')}"))
            entry_path = book_dir / f"{entry_name}.md"
            
            with open(entry_path, 'w', encoding='utf-8') as f:
                f.write(entry_md)
        
        print(f"  Extracted {len([e for e in entries if not e.get('disable')])} lorebook entries to {book_dir}")
    
    return output_path


def create_world_overview(worlds_dir: Path, output_dir: Path) -> None:
    """Create a world-overview.md file if multiple worlds exist."""
    world_files = list(worlds_dir.glob('*.json'))
    if len(world_files) <= 1:
        return
    
    lines = ["# World Overview", ""]
    lines.append("*This document provides links to all lore categories in this world.*")
    lines.append("")
    lines.append("## Categories")
    lines.append("")
    
    categories = {
        'characters': [],
        'locations': [],
        'factions': [],
        'events': [],
        'items': [],
        'misc': []
    }
    
    for world_file in world_files:
        data = parse_world_info(world_file)
        if not data:
            continue
        
        entries = list(data.get('entries', {}).values())
        category = categorize_world_info(world_file.stem, entries)
        safe_name = sanitize_filename(world_file.stem)
        
        categories[category].append((world_file.stem, f"./{category}/{safe_name}.md"))
    
    for cat, items in categories.items():
        if items:
            lines.append(f"### {cat.title()}")
            lines.append("")
            for name, path in sorted(items):
                lines.append(f"- [{name}]({path})")
            lines.append("")
    
    output_path = output_dir / 'lore' / 'world-overview.md'
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))


def main():
    parser = argparse.ArgumentParser(
        description='Migrate SillyTavern data to Narrative System markdown format'
    )
    parser.add_argument(
        '--worlds-dir',
        type=Path,
        help='Directory containing ST World Info JSON files'
    )
    parser.add_argument(
        '--characters-dir',
        type=Path,
        help='Directory containing ST character card PNG files'
    )
    parser.add_argument(
        '-o', '--output-dir',
        type=Path,
        default=Path.home() / 'Documents' / 'narrative-content',
        help='Output directory for markdown files (default: ~/Documents/narrative-content)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be created without writing files'
    )
    
    args = parser.parse_args()
    
    if not args.worlds_dir and not args.characters_dir:
        parser.print_help()
        print("\nError: Must specify at least one of --worlds-dir or --characters-dir")
        sys.exit(1)
    
    output_dir = args.output_dir.expanduser().resolve()
    
    if args.dry_run:
        print(f"DRY RUN: Would create files in {output_dir}")
    else:
        print(f"Creating output directory: {output_dir}")
        output_dir.mkdir(parents=True, exist_ok=True)
    
    stats = {'worlds': 0, 'characters': 0, 'entries': 0, 'lorebooks': 0}
    
    # Process World Info files
    if args.worlds_dir:
        worlds_dir = args.worlds_dir.expanduser().resolve()
        if not worlds_dir.exists():
            print(f"Warning: Worlds directory not found: {worlds_dir}")
        else:
            print(f"\nProcessing World Info files from {worlds_dir}...")
            json_files = list(worlds_dir.glob('*.json'))
            
            for json_file in json_files:
                print(f"  Processing {json_file.name}...")
                
                if args.dry_run:
                    data = parse_world_info(json_file)
                    if data:
                        entries = [e for e in data.get('entries', {}).values() if not e.get('disable')]
                        category = categorize_world_info(json_file.stem, entries)
                        print(f"    -> Would create lore/{category}/{sanitize_filename(json_file.stem)}.md ({len(entries)} entries)")
                        stats['worlds'] += 1
                        stats['entries'] += len(entries)
                else:
                    result = convert_world_info_file(json_file, output_dir)
                    if result:
                        category, path = result
                        entries_count = len(parse_world_info(json_file).get('entries', {}))
                        print(f"    -> Created lore/{category}/{path.name}")
                        stats['worlds'] += 1
                        stats['entries'] += entries_count
            
            # Create world overview index
            if not args.dry_run and json_files:
                create_world_overview(worlds_dir, output_dir)
                print(f"  -> Created lore/world-overview.md")
    
    # Process Character cards
    if args.characters_dir:
        chars_dir = args.characters_dir.expanduser().resolve()
        if not chars_dir.exists():
            print(f"Warning: Characters directory not found: {chars_dir}")
        else:
            print(f"\nProcessing Character cards from {chars_dir}...")
            png_files = list(chars_dir.glob('*.png'))
            
            for png_file in png_files:
                print(f"  Processing {png_file.name}...")
                
                if args.dry_run:
                    data = read_png_metadata(png_file)
                    if data:
                        char_data = data.get('data', data)
                        name = char_data.get('name', png_file.stem)
                        has_lorebook = bool(char_data.get('character_book', {}).get('entries'))
                        print(f"    -> Would create lore/characters/{sanitize_filename(name)}.md")
                        if has_lorebook:
                            print(f"    -> Would create lore/characters/{sanitize_filename(name)}-lorebook/")
                        stats['characters'] += 1
                        if has_lorebook:
                            stats['lorebooks'] += 1
                else:
                    result = convert_character_card(png_file, output_dir)
                    if result:
                        print(f"    -> Created {result.relative_to(output_dir)}")
                        stats['characters'] += 1
    
    # Summary
    print("\n" + "=" * 50)
    print("Migration Summary")
    print("=" * 50)
    print(f"World Info files: {stats['worlds']}")
    print(f"  Total entries: {stats['entries']}")
    print(f"Characters: {stats['characters']}")
    print(f"  With lorebooks: {stats['lorebooks']}")
    print(f"\nOutput location: {output_dir / 'lore'}")
    
    if not args.dry_run:
        print("\nNext steps:")
        print("1. Review the generated markdown files")
        print("2. Move files between categories if needed")
        print("3. Edit world-overview.md to add narrative coherence")
        print("4. Test with: python -m src.agents.librarian --query 'test'")


if __name__ == '__main__':
    main()
