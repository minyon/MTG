#!/usr/bin/env python3
"""
import_deck.py — Import Moxfield-exported decklists into the local decks directory.

Watches the `import/` folder. All .txt files found there are imported, then deleted.

Saves per deck:
  decks/{slug}/deck.txt   — plain text (Moxfield-compatible)
  decks/{slug}/deck.dck   — MTG Forge format

Usage:
    python3 import_deck.py               # process all files in import/
    python3 import_deck.py <file.txt>    # import a single file
    python3 import_deck.py <file.txt> <deck-name>  # import with explicit name

Deck name is derived from the filename by stripping the Moxfield timestamp
(e.g. norin-bounce-20250519-061823.txt → norin-bounce).
"""

import re
import shutil
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent
DECKS_DIR = BASE_DIR / "decks"
IMPORT_DIR = BASE_DIR / "import"


def slugify(name: str) -> str:
    name = name.lower().strip()
    name = re.sub(r"[^\w\s-]", "", name)
    name = re.sub(r"[\s_]+", "-", name)
    return name.strip("-")


def strip_moxfield_timestamp(stem: str) -> str:
    """Remove trailing -YYYYMMDD-HHMMSS from a filename stem if present."""
    return re.sub(r"-\d{8}-\d{6}$", "", stem)


def parse_moxfield_txt(src: Path) -> tuple[list[str], list[str]]:
    """
    Parse a Moxfield plain text export.
    Returns (mainboard_lines, commander_lines).
    Cards after the last blank line are treated as commanders.
    """
    text = src.read_text(encoding="utf-8")
    sections = re.split(r"\n\s*\n", text.strip())

    if len(sections) == 1:
        return sections[0].splitlines(), []

    commanders = [l for l in sections[-1].splitlines() if l.strip()]
    mainboard = [l for s in sections[:-1] for l in s.splitlines() if l.strip()]
    return mainboard, commanders


def to_forge_dck(slug: str, mainboard: list[str], commanders: list[str]) -> str:
    """Format a deck as an MTG Forge .dck file."""
    key_cards = ", ".join(
        re.sub(r"^\d+\s+", "", c).strip() for c in commanders
    )

    lines = ["[metadata]", f"Name={slug}"]
    if key_cards:
        lines.append(f"KeyCards={key_cards}")
    lines.append("[Main]")
    lines.extend(mainboard)
    lines.extend(commanders)
    return "\n".join(lines) + "\n"


def import_deck(src: Path, deck_name: str | None = None) -> None:
    slug = slugify(deck_name) if deck_name else strip_moxfield_timestamp(src.stem)
    mainboard, commanders = parse_moxfield_txt(src)

    dest_dir = DECKS_DIR / slug
    dest_dir.mkdir(parents=True, exist_ok=True)

    txt_dest = dest_dir / "deck.txt"
    shutil.copy2(src, txt_dest)

    dck_content = to_forge_dck(slug, mainboard, commanders)
    dck_dest = dest_dir / "deck.dck"
    dck_dest.write_text(dck_content, encoding="utf-8")

    print(f"Imported '{slug}'")
    print(f"  plain text → {txt_dest}")
    print(f"  forge dck  → {dck_dest}")
    if commanders:
        commander_names = [re.sub(r"^\d+\s+", "", c).strip() for c in commanders]
        print(f"  commander  : {', '.join(commander_names)}")


def process_import_folder() -> None:
    IMPORT_DIR.mkdir(exist_ok=True)
    files = sorted(IMPORT_DIR.glob("*.txt"))

    if not files:
        print(f"No .txt files found in {IMPORT_DIR}")
        return

    for src in files:
        try:
            import_deck(src)
            src.unlink()
        except Exception as e:
            print(f"Error importing {src.name}: {e}")


def main():
    if len(sys.argv) == 1:
        process_import_folder()
    elif len(sys.argv) == 2:
        src = Path(sys.argv[1])
        if not src.exists():
            print(f"Error: file not found: {src}")
            sys.exit(1)
        import_deck(src)
    else:
        src = Path(sys.argv[1])
        if not src.exists():
            print(f"Error: file not found: {src}")
            sys.exit(1)
        import_deck(src, deck_name=sys.argv[2])


if __name__ == "__main__":
    main()
