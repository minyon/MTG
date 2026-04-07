#!/usr/bin/env python3
"""
import_deck.py — Import decklists into the local decks directory.

Supports:
  - Moxfield plain text export
  - Deckstats plain text export

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


def deck_slug_from_filename(stem: str) -> str:
    """Derive a slug from a filename stem, stripping Moxfield timestamps if present."""
    stem = re.sub(r"-\d{8}-\d{6}$", "", stem)
    return slugify(stem)


def is_deckstats(text: str) -> bool:
    return bool(re.search(r"^(Main|Sideboard)\s*$", text, re.MULTILINE))


def parse_moxfield(text: str) -> tuple[list[str], list[str], list[str]]:
    """
    Moxfield format: flat card list, optional SIDEBOARD: section, commander(s) after final blank line.
    Returns (mainboard_lines, commander_lines, sideboard_lines).
    """
    sections = re.split(r"\n\s*\n", text.strip())

    # Pull out the SIDEBOARD: section if present
    sideboard: list[str] = []
    remaining: list[str] = []
    for section in sections:
        lines = section.splitlines()
        if lines and re.match(r"^SIDEBOARD\s*:", lines[0], re.IGNORECASE):
            sideboard = [l for l in lines[1:] if l.strip()]
        else:
            remaining.append(section)

    if len(remaining) == 0:
        return [], [], sideboard
    if len(remaining) == 1:
        return remaining[0].splitlines(), [], sideboard

    commanders = [l for l in remaining[-1].splitlines() if l.strip()]
    mainboard = [l for s in remaining[:-1] for l in s.splitlines() if l.strip()]
    return mainboard, commanders, sideboard


def parse_deckstats(text: str) -> tuple[list[str], list[str], list[str]]:
    """
    Deckstats format:
      Main
      1 Card Name
      ...

      Sideboard
      SB: 1 Commander Name # !Commander
      SB: 1 Other Card
    Returns (mainboard_lines, commander_lines, sideboard_lines) in plain `N Card Name` format.
    """
    mainboard: list[str] = []
    commanders: list[str] = []
    sideboard: list[str] = []
    section = None

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line == "Main":
            section = "main"
            continue
        if line == "Sideboard":
            section = "sideboard"
            continue

        if section == "main":
            mainboard.append(line)
        elif section == "sideboard":
            card = re.sub(r"^SB:\s*", "", line)
            annotation = re.search(r"#\s*(.+)$", card)
            card = re.sub(r"\s*#.*$", "", card).strip()
            if not card:
                continue
            if annotation and "Commander" in annotation.group(1):
                commanders.append(card)
            else:
                sideboard.append(card)

    return mainboard, commanders, sideboard


def parse_decklist(src: Path) -> tuple[list[str], list[str], list[str]]:
    text = src.read_text(encoding="utf-8")
    if is_deckstats(text):
        return parse_deckstats(text)
    return parse_moxfield(text)


def parse_forge_dck(src: Path) -> tuple[str | None, list[str], list[str], list[str]]:
    """
    Parse an MTG Forge .dck file.
    Returns (deck_name, mainboard_lines, commander_lines, sideboard_lines).
    Strips |SET|[NUM] collector suffixes from card names.
    """
    deck_name: str | None = None
    mainboard: list[str] = []
    commanders: list[str] = []
    sideboard: list[str] = []
    section: str | None = None

    for line in src.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].lower()
            continue
        if section == "metadata":
            if line.lower().startswith("name="):
                deck_name = line[5:].strip()
            continue
        # Strip collector suffix: "1 Card Name|SET|[NUM]" → "1 Card Name"
        card_line = re.sub(r"\|[^|]+\|\[[^\]]*\]$", "", line).strip()
        if section == "main":
            mainboard.append(card_line)
        elif section == "sideboard":
            sideboard.append(card_line)
        elif section == "commander":
            commanders.append(card_line)

    return deck_name, mainboard, commanders, sideboard


def to_forge_dck(slug: str, mainboard: list[str], commanders: list[str], sideboard: list[str]) -> str:
    """Format a deck as an MTG Forge .dck file."""
    lines = ["[metadata]", f"Name={slug}", "[Main]"]
    lines.extend(mainboard)
    if sideboard:
        lines.append("[Sideboard]")
        lines.extend(sideboard)
    if commanders:
        lines.append("[Commander]")
        lines.extend(commanders)
    return "\n".join(lines) + "\n"


def to_moxfield_txt(mainboard: list[str], commanders: list[str], sideboard: list[str]) -> str:
    """Format a deck as Moxfield-compatible plain text."""
    parts = ["\n".join(mainboard)]
    if commanders:
        parts.append("\n".join(commanders))
    result = "\n\n".join(parts) + "\n"
    if sideboard:
        result += "\nSIDEBOARD:\n" + "\n".join(sideboard) + "\n"
    return result


def import_deck(src: Path, deck_name: str | None = None) -> None:
    if src.suffix == ".dck":
        forge_name, mainboard, commanders, sideboard = parse_forge_dck(src)
        slug = slugify(deck_name) if deck_name else (slugify(forge_name) if forge_name else deck_slug_from_filename(src.stem))
    else:
        slug = slugify(deck_name) if deck_name else deck_slug_from_filename(src.stem)
        mainboard, commanders, sideboard = parse_decklist(src)

    dest_dir = DECKS_DIR / slug
    dest_dir.mkdir(parents=True, exist_ok=True)

    txt_dest = dest_dir / "deck.txt"
    txt_dest.write_text(to_moxfield_txt(mainboard, commanders, sideboard), encoding="utf-8")

    dck_dest = dest_dir / "deck.dck"
    dck_dest.write_text(to_forge_dck(slug, mainboard, commanders, sideboard), encoding="utf-8")

    print(f"Imported '{slug}'")
    print(f"  plain text → {txt_dest}")
    print(f"  forge dck  → {dck_dest}")
    if commanders:
        commander_names = [re.sub(r"^\d+\s+", "", c).strip() for c in commanders]
        print(f"  commander  : {', '.join(commander_names)}")
    if sideboard:
        sb_names = [re.sub(r"^\d+\s+", "", c).strip() for c in sideboard]
        print(f"  sideboard  : {', '.join(sb_names)}")


def process_import_folder() -> None:
    IMPORT_DIR.mkdir(exist_ok=True)
    files = sorted(IMPORT_DIR.glob("*.txt")) + sorted(IMPORT_DIR.glob("*.dck"))

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
