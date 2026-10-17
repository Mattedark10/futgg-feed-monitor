import os
import re
import json
import time
from pathlib import Path
from collections import Counter

import requests
from bs4 import BeautifulSoup


# ============================================================
# CONFIG
# ============================================================

PAGES = {
    "Heroes": {
        "url": "https://www.fut.gg/fut-gallery/rarities/heroes/",
        "slots": 5,
        "emoji": "🦸‍♂️",
    },
    "Holographics": {
        "url": "https://www.fut.gg/fut-gallery/rarities/holographics/",
        "slots": 5,
        "emoji": "✨️",
    },
    "Season 1": {
        "url": "https://www.fut.gg/fut-gallery/rarities/season-1/",
        "slots": 10,
        "emoji": "1️⃣",
    },
}


PLAYERS_FILE = Path("players.json")
CACHE_FILE = Path("card_cache.json")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/xml;q=0.9,image/avif,"
        "image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}


session = requests.Session()
session.headers.update(HEADERS)


# ============================================================
# JSON
# ============================================================

def load_json(path, default):
    try:
        if not path.exists():
            return default

        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    except Exception as e:
        print(f"Error loading {path}: {e}")
        return default


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)

    tmp = path.with_suffix(path.suffix + ".tmp")

    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )

    tmp.replace(path)


# ============================================================
# TEXT
# ============================================================

def clean_text(value):
    if not value:
        return ""

    value = str(value)
    value = value.replace("\xa0", " ")
    value = re.sub(r"\s+", " ", value)

    return value.strip()


# ============================================================
# FINISH
# ============================================================

def normalize_finish(value):
    """
    Returns only:

    BASE
    HOLO
    PRISTINE HOLO
    """

    if not value:
        return None

    text = clean_text(value).upper()

    # IMPORTANT:
    # PRISTINE must be checked before normal HOLO.
    if (
        "PRISTINE HOLOGRAPHIC" in text
        or "PRISTINE HOLO" in text
        or (
            "PRISTINE" in text
            and "HOLO" in text
        )
    ):
        return "PRISTINE HOLO"

    if (
        "HOLOGRAPHIC" in text
        or re.search(r"\bHOLO\b", text)
    ):
        return "HOLO"

    if (
        re.search(r"\bBASE\b", text)
        or "BASE CARD" in text
        or "BASE ITEM" in text
    ):
        return "BASE"

    return None


# ============================================================
# CARD STRING
# ============================================================

CARD_PATTERN = re.compile(
    r"^\s*(.+?)\s*-\s*(\d{2,3})\s*-\s*(.+?)\s*$"
)


def parse_card_string(value):
    if not value:
        return None

    value = clean_text(value)

    if value.lower() in {
        "player card",
        "image: player card",
        "card",
    }:
        return None

    match = CARD_PATTERN.match(value)

    if not match:
        return None

    name = clean_text(match.group(1))
    overall = int(match.group(2))
    version = clean_text(match.group(3))

    if not name or not version:
        return None

    return {
        "name": name,
        "overall": overall,
        "version": version,
    }


# ============================================================
# LINEUP HTML
# ============================================================

def get_lineup_html(page_html):
    soup = BeautifulSoup(
        page_html,
        "html.parser"
    )

    headings = soup.find_all(
        string=re.compile(
            r"Cheapest grade",
            re.IGNORECASE
        )
    )

    if headings:

        heading = headings[-1]
        node = heading.parent

        candidates = []

        for _ in range(10):

            if node is None:
                break

            html = str(node)

            if (
                "Add players" in html
                and len(html) > 1000
            ):
                candidates.append(html)

            node = node.parent

        if candidates:

            candidates.sort(
                key=len
            )

            section = candidates[0]

            match = re.search(
                r"Add players",
                section,
                re.IGNORECASE
            )

            if match:
                section = section[:match.start()]

            return section

    # Fallback
    match = re.search(
        r"Cheapest grade.*?(?=Add players)",
        page_html,
        flags=re.IGNORECASE | re.DOTALL
    )

    if match:
        return match.group(0)

    raise ValueError(
        "Cheapest grade lineup not found"
    )


# ============================================================
# CARD METADATA
# ============================================================

def node_metadata(node):
    values = []

    attrs = getattr(
        node,
        "attrs",
        {}
    )

    for key in [
        "alt",
        "title",
        "aria-label",
        "data-name",
        "data-player-name",
        "data-card-name",
        "data-finish",
        "data-rarity",
        "data-version",
        "class",
    ]:

        value = attrs.get(key)

        if isinstance(value, list):
            value = " ".join(value)

        if value:
            values.append(
                str(value)
            )

    parent = node.parent

    for _ in range(5):

        if parent is None:
            break

        attrs = getattr(
            parent,
            "attrs",
            {}
        )

        for key, value in attrs.items():

            if isinstance(value, list):
                value = " ".join(value)

            if value:
                values.append(
                    str(value)
                )

        text = parent.get_text(
            " ",
            strip=True
        )

        if text:
            values.append(text)

        parent = parent.parent

    return values


# ============================================================
# FINISH FROM NODE
# ============================================================

def get_node_finish(node):

    values = node_metadata(node)

    # First try exact metadata.
    for value in values:

        finish = normalize_finish(
            value
        )

        if finish:
            return finish

    return None


# ============================================================
# EXTRACT CARDS
# ============================================================

def extract_cards(section_html, max_slots):
    """
    Extract visible real cards.

    IMPORTANT:
    No global deduplication.

    Harder BASE
    Harder HOLO

    are two different cards.
    """

    soup = BeautifulSoup(
        section_html,
        "html.parser"
    )

    cards = []

    # --------------------------------------------------------
    # IMG
    # --------------------------------------------------------

    for img in soup.find_all("img"):

        metadata = node_metadata(img)

        parsed = None

        for value in metadata:

            parsed = parse_card_string(
                value
            )

            if parsed:
                break

            # Flexible search inside longer text.
            match = re.search(
                r"([A-Za-zÀ-ÿ'’.\- ]+?)"
                r"\s*-\s*(\d{2,3})"
                r"\s*-\s*"
                r"([A-Za-zÀ-ÿ0-9'’& .\-]+)",
                value
            )

            if match:

                parsed = {
                    "name": clean_text(
                        match.group(1)
                    ),
                    "overall": int(
                        match.group(2)
                    ),
                    "version": clean_text(
                        match.group(3)
                    ),
                }

                break

        if not parsed:
            continue

        if parsed["name"].lower() == "player card":
            continue

        finish = get_node_finish(img)

        cards.append({
            "name": parsed["name"],
            "overall": parsed["overall"],
            "version": parsed["version"],
            "finish": finish,
        })

        if len(cards) >= max_slots:
            break

    # --------------------------------------------------------
    # FALLBACK
    # --------------------------------------------------------

    if len(cards) < max_slots:

        for node in soup.find_all(
            ["a", "button", "div"]
        ):

            if len(cards) >= max_slots:
                break

            metadata = node_metadata(
                node
            )

            parsed = None

            for value in metadata:

                parsed = parse_card_string(
                    value
                )

                if parsed:
                    break

            if not parsed:
                continue

            if parsed["name"].lower() == "player card":
                continue

            candidate = {
                "name": parsed["name"],
                "overall": parsed["overall"],
                "version": parsed["version"],
                "finish": get_node_finish(
                    node
                ),
            }

            # Only reject if this is obviously the same
            # DOM card already found by IMG.
            #
            # BUT:
            # duplicate players with different finishes
            # are allowed.
            already_same = False

            for existing in cards:

                if (
                    existing["name"]
                    == candidate["name"]
                    and existing["overall"]
                    == candidate["overall"]
                    and existing["version"]
                    == candidate["version"]
                    and normalize_finish(
                        existing.get("finish")
                    )
                    == normalize_finish(
                        candidate.get("finish")
                    )
                ):
                    already_same = True
                    break

            if not already_same:
                cards.append(
                    candidate
                )

    return cards[:max_slots]


# ============================================================
# UNKNOWN SLOTS
# ============================================================

def count_unknown_slots(
    section_html,
    total_slots,
    known_cards
):
    """
    FUT.GG can show:

        Image: Player Card

    for a slot whose player isn't yet in the database.

    Those slots are NOT errors.
    """

    soup = BeautifulSoup(
        section_html,
        "html.parser"
    )

    unknown = 0

    for img in soup.find_all("img"):

        values = node_metadata(
            img
        )

        combined = " ".join(
            values
        ).lower()

        if (
            "player card" in combined
            or "image: player card" in combined
        ):
            unknown += 1

    # Safety clamp.
    unknown = max(
        0,
        min(
            unknown,
            total_slots - len(known_cards)
        )
    )

    return unknown


# ============================================================
# CARD KEY
# ============================================================

def card_key(card):
    """
    Finish is part of the identity.

    Therefore:

        Harder 88 BASE
        Harder 88 HOLO

    are different.
    """

    return (
        clean_text(
            card.get("name", "")
        ).lower(),

        int(
            card.get(
                "overall",
                0
            )
        ),

        clean_text(
            card.get(
                "version",
                ""
            )
        ).lower(),

        normalize_finish(
            card.get(
                "finish"
            )
        ) or "BASE",
    )


# ============================================================
# FINISH FROM OLD STATE
# ============================================================

def resolve_missing_finishes(
    current_cards,
    old_cards
):
    """
    Only reuse an old finish when the current card matches
    an old occurrence.

    This allows:

        Harder BASE
        Harder HOLO

    to coexist.

    If no previous occurrence exists, finish remains unknown
    instead of inventing BASE.
    """

    old_pool = []

    for card in old_cards:

        old_pool.append({
            "name": card.get(
                "name",
                ""
            ),
            "overall": int(
                card.get(
                    "overall",
                    0
                )
            ),
            "version": card.get(
                "version",
                ""
            ),
            "finish": normalize_finish(
                card.get(
                    "finish"
                )
            ),
        })

    used = [
        False
        for _ in old_pool
    ]

    for card in current_cards:

        if normalize_finish(
            card.get("finish")
        ):
            continue

        for i, old in enumerate(
            old_pool
        ):

            if used[i]:
                continue

            if (
                old["name"] == card["name"]
                and old["overall"]
                == card["overall"]
                and old["version"]
                == card["version"]
                and old["finish"]
            ):

                card["finish"] = (
                    old["finish"]
                )

                used[i] = True

                break

    return current_cards


# ============================================================
# COMPARE
# ============================================================

def compare_lineups(
    old_cards,
    new_cards
):
    """
    Multiset comparison.

    Duplicate cards are preserved.
    """

    old_counter = Counter(
        card_key(card)
        for card in old_cards
    )

    new_counter = Counter(
        card_key(card)
        for card in new_cards
    )

    out_cards = []
    in_cards = []

    for key, count in (
        old_counter - new_counter
    ).items():

        for _ in range(count):

            out_cards.append(
                key_to_card(key)
            )

    for key, count in (
        new_counter - old_counter
    ).items():

        for _ in range(count):

            in_cards.append(
                key_to_card(key)
            )

    return (
        out_cards,
        in_cards
    )


def key_to_card(key):

    name, overall, version, finish = key

    return {
        "name": name,
        "overall": overall,
        "version": version,
        "finish": finish,
    }


# ============================================================
# FETCH
# ============================================================

def fetch_page(url):

    response = session.get(
        url,
        timeout=45
    )

    response.raise_for_status()

    return response.text


# ============================================================
# FORMAT
# ============================================================

def format_card(card):

    finish = normalize_finish(
        card.get("finish")
    )

    if not finish:
        finish = "UNKNOWN"

    return (
        f"{card.get('name', '')} "
        f"{card.get('overall', '')} — "
        f"{finish}"
    )


# ============================================================
# TELEGRAM CATEGORY
# ============================================================

def format_category(
    category,
    config,
    result
):

    lines = [
        f"{config['emoji']} {category}",
        ""
    ]

    out_cards = result["out"]
    in_cards = result["in"]
    current_cards = result["cards"]

    unknown_slots = result.get(
        "unknown_slots",
        0
    )

    # --------------------------------------------------------
    # NO CHANGE
    # --------------------------------------------------------

    if not out_cards and not in_cards:

        lines.append(
            "No feed changes"
        )

        return "\n".join(
            lines
        )

    # --------------------------------------------------------
    # OUT
    # --------------------------------------------------------

    if out_cards:

        lines.append(
            "🔴 OUT"
        )

        lines.append("")

        for card in out_cards:

            lines.append(
                f"• {format_card(card)}"
            )

        lines.append("")

    # --------------------------------------------------------
    # IN
    # --------------------------------------------------------

    if in_cards:

        lines.append(
            "🟢 IN"
        )

        lines.append("")

        for card in in_cards:

            lines.append(
                f"• {format_card(card)}"
            )

        lines.append("")

    # --------------------------------------------------------
    # CURRENT
    # --------------------------------------------------------

    lines.append(
        "Current lineup"
    )

    lines.append("")

    incoming = Counter(
        card_key(card)
        for card in in_cards
    )

    for card in current_cards:

        key = card_key(card)

        if incoming[key] > 0:

            lines.append(
                f"🟢 {format_card(card)}"
            )

            incoming[key] -= 1

        else:

            lines.append(
                format_card(card)
            )

    # Unknown Season 1 slots.
    if unknown_slots > 0:

        lines.append("")

        lines.append(
            f"🟡 {unknown_slots} "
            f"unknown slot(s)"
        )

    return "\n".join(
        lines
    )


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):

    if not TELEGRAM_BOT_TOKEN:
        print(
            "TELEGRAM_BOT_TOKEN missing"
        )
        return

    if not TELEGRAM_CHAT_ID:
        print(
            "TELEGRAM_CHAT_ID missing"
        )
        return

    url = (
        "https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
    }

    try:

        response = requests.post(
            url,
            json=payload,
            timeout=30
        )

        response.raise_for_status()

        print(
            "Telegram message sent."
        )

    except Exception as e:

        print(
            f"Telegram error: {e}"
        )


# ============================================================
# PROCESS PAGE
# ============================================================

def process_page(
    category,
    config,
    previous_state
):

    print()
    print("=" * 60)
    print(
        f"Checking {category}..."
    )
    print(
        config["url"]
    )

    html = fetch_page(
        config["url"]
    )

    section = get_lineup_html(
        html
    )

    cards = extract_cards(
        section,
        config["slots"]
    )

    old_cards = previous_state.get(
        category,
        []
    )

    cards = resolve_missing_finishes(
        cards,
        old_cards
    )

    unknown_slots = 0

    if category == "Season 1":

        unknown_slots = count_unknown_slots(
            section,
            config["slots"],
            cards
        )

    print(
        f"Rendered lineup: "
        f"{len(cards)}/{config['slots']} "
        f"real cards"
    )

    if category == "Season 1":

        print(
            f"Unknown slots: "
            f"{unknown_slots}"
        )

    print(
        "Detected cards:"
    )

    for i, card in enumerate(
        cards,
        1
    ):

        print(
            f"  [{i}] "
            f"{format_card(card)}"
        )

    out_cards, in_cards = compare_lineups(
        old_cards,
        cards
    )

    print(
        f"OUT: {len(out_cards)}"
    )

    print(
        f"IN: {len(in_cards)}"
    )

    return {
        "cards": cards,
        "out": out_cards,
        "in": in_cards,
        "unknown_slots": unknown_slots,
    }


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 60)
    print("FUT.GG MONITOR")
    print("=" * 60)

    previous_state = load_json(
        PLAYERS_FILE,
        {
            "Heroes": [],
            "Holographics": [],
            "Season 1": [],
        }
    )

    current_state = {}

    telegram_sections = []

    for category, config in PAGES.items():

        try:

            result = process_page(
                category,
                config,
                previous_state
            )

            current_state[
                category
            ] = result["cards"]

            telegram_sections.append(
                format_category(
                    category,
                    config,
                    result
                )
            )

        except Exception as e:

            print(
                f"ERROR on {category}: "
                f"{e}"
            )

            # Keep previous valid state.
            current_state[
                category
            ] = previous_state.get(
                category,
                []
            )

            telegram_sections.append(
                "\n".join([
                    f"{config['emoji']} {category}",
                    "",
                    "⚠️ Scan error",
                    "",
                    str(e),
                ])
            )

    # --------------------------------------------------------
    # SAVE PLAYERS
    # --------------------------------------------------------

    save_json(
        PLAYERS_FILE,
        current_state
    )

    # --------------------------------------------------------
    # TELEGRAM
    # --------------------------------------------------------

    message = (
        "\n\n"
        "------------------------------"
        "\n\n"
    ).join(
        telegram_sections
    )

    send_telegram(
        message
    )

    # --------------------------------------------------------
    # FINAL LOG
    # --------------------------------------------------------

    print()
    print("=" * 60)
    print("FINAL STATE")
    print("=" * 60)

    for category in PAGES:

        cards = current_state.get(
            category,
            []
        )

        print(
            f"{category}: "
            f"{len(cards)} cards"
        )

        for card in cards:

            print(
                f"  - "
                f"{format_card(card)}"
            )

    print()
    print("Done.")


if __name__ == "__main__":
    main()