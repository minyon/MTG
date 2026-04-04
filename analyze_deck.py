#!/usr/bin/env python3
"""
analyze_deck.py — Analyze a local deck against the Scryfall API.

Reports:
  - Total card count
  - Color identity
  - Cards not found on Scryfall (likely typos)
  - Cards not legal in Commander (banned or not_legal)
  - Cards on the Commander Game Changer list

Usage:
    python3 analyze_deck.py <deck-slug>
    python3 analyze_deck.py <path/to/deck.txt>
"""

import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).parent
DECKS_DIR = BASE_DIR / "decks"

SCRYFALL_COLLECTION = "https://api.scryfall.com/cards/collection"
SCRYFALL_GAME_CHANGERS = "https://api.scryfall.com/cards/search?q=is%3Agame_changer"

COLOR_NAMES = {"W": "White", "U": "Blue", "B": "Black", "R": "Red", "G": "Green"}
WUBRG = ["W", "U", "B", "R", "G"]


def scryfall_get(url: str) -> dict:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "MTG-Deck-Manager/1.0", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def scryfall_post(url: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "User-Agent": "MTG-Deck-Manager/1.0",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def fetch_game_changer_names() -> set[str]:
    result = scryfall_get(SCRYFALL_GAME_CHANGERS)
    return {card["name"] for card in result.get("data", [])}


def fetch_cards_collection(names: list[str]) -> tuple[list[dict], list[dict]]:
    """
    Fetch card data in batches of 75 (Scryfall limit).
    Returns (found_cards, not_found_entries).
    """
    found: list[dict] = []
    not_found: list[dict] = []

    for i in range(0, len(names), 75):
        batch = names[i : i + 75]
        payload = {"identifiers": [{"name": n} for n in batch]}
        result = scryfall_post(SCRYFALL_COLLECTION, payload)
        found.extend(result.get("data", []))
        not_found.extend(result.get("not_found", []))
        if i + 75 < len(names):
            time.sleep(0.1)  # respect Scryfall rate limit between batches

    return found, not_found


def card_price(card: dict) -> float | None:
    """Return the best available USD price for a card, or None."""
    prices = card.get("prices", {})
    for key in ("usd", "usd_foil", "usd_etched"):
        val = prices.get(key)
        if val is not None:
            return float(val)
    return None


def fetch_cheapest_printing(name: str) -> dict | None:
    """Find the cheapest paper printing of a card that has a USD price."""
    q = urllib.parse.quote(f'!"{name}" has:usdprice')
    url = f"https://api.scryfall.com/cards/search?q={q}&order=usd&dir=asc"
    try:
        result = scryfall_get(url)
        data = result.get("data", [])
        return data[0] if data else None
    except Exception:
        return None


def parse_decklist(path: Path) -> tuple[dict[str, int], list[str]]:
    """
    Parse a plain text decklist.
    Returns (card_name -> quantity, commanders).
    Commanders are cards after the final blank line.
    """
    text = path.read_text(encoding="utf-8")
    sections = re.split(r"\n\s*\n", text.strip())

    def parse_lines(lines: list[str]) -> dict[str, int]:
        cards: dict[str, int] = {}
        for line in lines:
            line = line.strip()
            m = re.match(r"^(\d+)\s+(.+)$", line)
            if m:
                qty, name = int(m.group(1)), m.group(2).strip()
                cards[name] = cards.get(name, 0) + qty
        return cards

    if len(sections) == 1:
        return parse_lines(sections[0].splitlines()), []

    commander_lines = [l for l in sections[-1].splitlines() if l.strip()]
    main_lines = [l for s in sections[:-1] for l in s.splitlines()]

    commanders = [re.sub(r"^\d+\s+", "", l).strip() for l in commander_lines]
    cards = parse_lines(main_lines + commander_lines)
    return cards, commanders


def color_identity_label(colors: list[str]) -> str:
    if not colors:
        return "Colorless"
    ordered = [c for c in WUBRG if c in colors]
    names = [COLOR_NAMES[c] for c in ordered]
    return "/".join(names) + f"  ({' '.join(ordered)})"


def write_meta(deck_dir: Path, slug: str, commanders: list[str], total: int,
               deck_colors: set[str], not_found: list[dict],
               illegal: list[str], game_changer_hits: list[str],
               price_total: float | None, no_price: list[str]) -> Path:
    """Write analysis results to meta.md in the deck directory."""
    from datetime import date

    color_label = color_identity_label(sorted(deck_colors, key=WUBRG.index))
    price_str = f"${price_total:.2f}" if price_total is not None else "N/A"
    lines = [
        f"# {slug}",
        f"",
        f"## Overview",
        f"",
        f"| | |",
        f"|---|---|",
        f"| **Total cards** | {total}{' ⚠️ incomplete' if total < 100 else ''} |",
        f"| **Color identity** | {color_label} |",
        f"| **Estimated price** | {price_str} |",
    ]

    if commanders:
        lines.append(f"| **Commander** | {', '.join(commanders)} |")

    lines += ["", f"*Last analyzed: {date.today()}*", ""]

    if total < 100:
        lines += ["## Incomplete Deck", "", f"This deck has {total}/100 cards. {100 - total} card(s) still needed.", ""]

    if not_found:
        lines += [f"## Not Found on Scryfall", ""]
        for c in not_found:
            lines.append(f"- {c.get('name', c)}")
        lines.append("")
    else:
        lines += ["## Validity", "", "All cards found on Scryfall.", ""]

    if illegal:
        lines += ["## Not Legal in Commander", ""]
        for c in illegal:
            lines.append(f"- {c.strip()}")
        lines.append("")
    else:
        lines += ["## Legality", "", "All cards are Commander-legal.", ""]

    if game_changer_hits:
        lines += [f"## Game Changers ({len(game_changer_hits)})", ""]
        for c in game_changer_hits:
            lines.append(f"- {c.strip()}")
        lines.append("")
    else:
        lines += ["## Game Changers", "", "None.", ""]

    if no_price:
        lines += ["## No Price Data", ""]
        for c in no_price:
            lines.append(f"- {c}")
        lines.append("")

    meta_path = deck_dir / "meta.md"
    meta_path.write_text("\n".join(lines), encoding="utf-8")
    return meta_path


def resolve_deck_path(arg: str) -> Path:
    p = Path(arg)
    if p.suffix == ".txt" and p.exists():
        return p
    # treat as slug
    candidate = DECKS_DIR / arg / "deck.txt"
    if candidate.exists():
        return candidate
    print(f"Error: could not find deck '{arg}'")
    sys.exit(1)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    deck_path = resolve_deck_path(sys.argv[1])
    cards, commanders = parse_decklist(deck_path)

    total = sum(cards.values())
    unique_names = list(cards.keys())

    print(f"\nAnalyzing '{deck_path.parent.name}' ...")
    print(f"Fetching game changer list ...")
    game_changers = fetch_game_changer_names()

    print(f"Fetching {len(unique_names)} cards from Scryfall ...\n")
    found_cards, not_found = fetch_cards_collection(unique_names)

    # Build color identity, legality, price, and game changer data
    deck_colors: set[str] = set()
    illegal: list[str] = []
    game_changer_hits: list[str] = []
    price_total: float = 0.0
    no_price: list[str] = []

    for card in found_cards:
        deck_colors.update(card.get("color_identity", []))
        legality = card.get("legalities", {}).get("commander", "unknown")
        if legality in ("banned", "not_legal"):
            illegal.append(f"  {card['name']}  [{legality}]")
        if card["name"] in game_changers:
            game_changer_hits.append(f"  {card['name']}")

        if "Basic Land" in card.get("type_line", ""):
            unit_price = 0.0
        else:
            unit_price = card_price(card)
            if unit_price is None:
                fallback = fetch_cheapest_printing(card["name"])
                if fallback:
                    unit_price = card_price(fallback)
                time.sleep(0.1)
        qty = cards.get(card["name"], 1)
        if unit_price is not None:
            price_total += unit_price * qty
        else:
            no_price.append(card["name"])

    price_display = f"${price_total:.2f}" if found_cards else "N/A"

    # --- Output ---
    print(f"{'='*50}")
    print(f"  {deck_path.parent.name}")
    print(f"{'='*50}")

    incomplete_note = f"  ⚠  INCOMPLETE: {total}/100 cards ({100 - total} still needed)" if total < 100 else ""
    print(f"\n  Total cards   : {total}{' (incomplete)' if total < 100 else ''}")
    if incomplete_note:
        print(incomplete_note)
    print(f"  Color identity: {color_identity_label(sorted(deck_colors, key=WUBRG.index))}")
    print(f"  Est. price    : {price_display}")
    if no_price:
        print(f"  No price data : {len(no_price)} card(s)")

    if not_found:
        print(f"\n  NOT FOUND ({len(not_found)}) — possible typos:")
        for c in not_found:
            print(f"  {c.get('name', c)}")
    else:
        print(f"\n  All cards found on Scryfall.")

    if illegal:
        print(f"\n  NOT LEGAL IN COMMANDER ({len(illegal)}):")
        for c in illegal:
            print(c)
    else:
        print(f"  All cards are Commander-legal.")

    if game_changer_hits:
        print(f"\n  GAME CHANGERS ({len(game_changer_hits)}):")
        for c in game_changer_hits:
            print(c)
    else:
        print(f"  No game changers in this deck.")

    meta_path = write_meta(
        deck_path.parent, deck_path.parent.name, commanders,
        total, deck_colors, not_found, illegal, game_changer_hits,
        price_total if found_cards else None, no_price,
    )
    print(f"\n  meta.md written → {meta_path}\n")


if __name__ == "__main__":
    main()
