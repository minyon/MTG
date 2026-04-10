#!/usr/bin/env python3
"""
apply_suggestions.py — Apply marked cards from a suggestions file to a deck.

Cards marked with a trailing '+' are added to the deck. Duplicates are skipped
(basic lands are exempt — multiples are always added). Applied lines are removed
from the suggestions file.

Usage:
    python3 apply_suggestions.py <deck-slug>
    python3 apply_suggestions.py <path/to/suggestions.md>
"""

import re
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent
DECKS_DIR = BASE_DIR / "decks"
WORKING_DIR = BASE_DIR / "working"

BASIC_LANDS = {
    "Plains", "Island", "Swamp", "Mountain", "Forest", "Wastes",
    "Snow-Covered Plains", "Snow-Covered Island", "Snow-Covered Swamp",
    "Snow-Covered Mountain", "Snow-Covered Forest",
}


def parse_deck_txt(path: Path) -> tuple[list[str], list[str], list[str]]:
    """Return (mainboard_lines, commander_lines, sideboard_lines) from a deck.txt."""
    text = path.read_text(encoding="utf-8")

    sideboard: list[str] = []
    sb_split = re.split(r"\nSIDEBOARD:\n", text, maxsplit=1)
    if len(sb_split) == 2:
        text = sb_split[0]
        sideboard = [l for l in sb_split[1].splitlines() if l.strip()]

    sections = re.split(r"\n\s*\n", text.strip())
    if len(sections) == 1:
        return [l for l in sections[0].splitlines() if l.strip()], [], sideboard

    commanders = [l for l in sections[-1].splitlines() if l.strip()]
    mainboard = [l for s in sections[:-1] for l in s.splitlines() if l.strip()]
    return mainboard, commanders, sideboard


def existing_names(mainboard: list[str], commanders: list[str]) -> set[str]:
    names: set[str] = set()
    for line in mainboard + commanders:
        m = re.match(r"^\d+\s+(.+)$", line.strip())
        if m:
            names.add(m.group(1).strip())
    return names


def parse_marked(suggestions_path: Path) -> list[tuple[int, str, int]]:
    """
    Return (line_index, card_name, quantity) for every line ending with '+'.
    Handles optional quantity prefix: "14x Island +" → (idx, "Island", 14).
    """
    marked = []
    for i, line in enumerate(suggestions_path.read_text(encoding="utf-8").splitlines()):
        stripped = line.strip()
        if not (stripped.startswith("-") and stripped.endswith("+")):
            continue
        card_part = re.sub(r"^-\s*", "", stripped)
        card_part = re.sub(r"\s*\+$", "", card_part).strip()
        card_part = re.sub(r"\s*[—–-]{1,2}\s.*$", "", card_part).strip()
        m = re.match(r"^(\d+)x\s+(.+)$", card_part)
        if m:
            marked.append((i, m.group(2).strip(), int(m.group(1))))
        else:
            marked.append((i, card_part, 1))
    return marked


def to_moxfield_txt(mainboard: list[str], commanders: list[str], sideboard: list[str]) -> str:
    parts = ["\n".join(mainboard)]
    if commanders:
        parts.append("\n".join(commanders))
    result = "\n\n".join(parts) + "\n"
    if sideboard:
        result += "\nSIDEBOARD:\n" + "\n".join(sideboard) + "\n"
    return result


def to_forge_dck(slug: str, mainboard: list[str], commanders: list[str], sideboard: list[str]) -> str:
    lines = ["[metadata]", f"Name={slug}", "[Main]"]
    lines.extend(mainboard)
    if sideboard:
        lines.append("[Sideboard]")
        lines.extend(sideboard)
    if commanders:
        lines.append("[Commander]")
        lines.extend(commanders)
    return "\n".join(lines) + "\n"


def remove_lines(suggestions_path: Path, indices: set[int]) -> None:
    lines = suggestions_path.read_text(encoding="utf-8").splitlines()
    kept = [l for i, l in enumerate(lines) if i not in indices]
    result = re.sub(r"\n{3,}", "\n\n", "\n".join(kept))
    suggestions_path.write_text(result.rstrip() + "\n", encoding="utf-8")


def resolve(arg: str) -> tuple[Path, Path]:
    """Return (deck_dir, suggestions_path) from a slug or suggestions file path."""
    p = Path(arg)
    if p.suffix == ".md" and p.exists():
        slug = re.sub(r"-suggestions$", "", p.stem)
        return DECKS_DIR / slug, p
    return DECKS_DIR / arg, WORKING_DIR / f"{arg}-suggestions.md"


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    deck_dir, suggestions_path = resolve(sys.argv[1])
    deck_txt = deck_dir / "deck.txt"

    if not deck_txt.exists():
        print(f"Error: deck not found: {deck_txt}")
        sys.exit(1)
    if not suggestions_path.exists():
        print(f"Error: suggestions file not found: {suggestions_path}")
        sys.exit(1)

    mainboard, commanders, sideboard = parse_deck_txt(deck_txt)
    in_deck = existing_names(mainboard, commanders)
    marked = parse_marked(suggestions_path)

    if not marked:
        print("No cards marked with '+' found.")
        return

    added: list[tuple[int, str]] = []
    skipped: list[str] = []
    applied: set[int] = set()

    for line_idx, name, qty in marked:
        if name in in_deck and name not in BASIC_LANDS:
            skipped.append(name)
        else:
            mainboard.append(f"{qty} {name}")
            in_deck.add(name)
            added.append((qty, name))
        applied.add(line_idx)

    slug = deck_dir.name
    deck_txt.write_text(to_moxfield_txt(mainboard, commanders, sideboard), encoding="utf-8")
    (deck_dir / "deck.dck").write_text(to_forge_dck(slug, mainboard, commanders, sideboard), encoding="utf-8")
    remove_lines(suggestions_path, applied)

    print(f"Deck: {slug}")
    if added:
        print(f"\nAdded ({len(added)}):")
        for qty, name in added:
            print(f"  {qty}x {name}")
    if skipped:
        print(f"\nSkipped — already in deck ({len(skipped)}):")
        for name in skipped:
            print(f"  {name}")
    print(f"\nRun: python3 analyze_deck.py {slug}")


if __name__ == "__main__":
    main()
