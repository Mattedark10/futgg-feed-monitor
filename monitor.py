import os
import json
import re
import traceback
import requests
from bs4 import BeautifulSoup
from collections import Counter


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


TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


# ============================================================
# KNOWN FINISHES
# ============================================================

KNOWN_FINISHES = {
    "67335170": "PRISTINE HOLO",
    "67114537": "PRISTINE HOLO",
    "67335237": "PRISTINE HOLO",
    "67371135": "PRISTINE HOLO",

    "226306": "BASE",
    "233700": "BASE",
    "67186651": "PRISTINE HOLO",

    "67335157": "PRISTINE HOLO",
    "67384140": "PRISTINE HOLO",
    "67275770": "PRISTINE HOLO",
    "67180472": "PRISTINE HOLO",
    "67298908": "PRISTINE HOLO",

    "67348095": "PRISTINE HOLO",
    "67368151": "PRISTINE HOLO",

    "67179830": "HOLO",
    "67188263": "HOLO",
    "67368429": "HOLO",
    "67353040": "HOLO",
    "67372629": "HOLO",
    "67386815": "HOLO",
    "67374557": "HOLO",

    "50590935": "BASE",
}


# ============================================================
# JSON
# ============================================================

def load_json(path, default):
    if not os.path.exists(path):
        return default

    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"JSON read error ({path}): {e}")
        return default


def save_json(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                data,
                f,
                ensure_ascii=False,
                indent=2
            )
    except Exception as e:
        print(f"JSON save error ({path}): {e}")
        raise


# ============================================================
# FETCH
# ============================================================

def fetch_page(url):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/140.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,"
            "application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }

    print(f"Fetching: {url}")

    response = requests.get(
        url,
        headers=headers,
        timeout=30
    )

    print(f"HTTP status: {response.status_code}")
    print(f"Downloaded: {len(response.text)} characters")

    response.raise_for_status()

    return response.text


# ============================================================
# FIND LINEUP
# ============================================================

def find_lineup(soup):
    """
    Find the visible FUT.GG lineup.

    We search for the "Cheapest grade X lineup"
    text and then walk up the DOM looking for
    a container containing the card images.
    """

    candidates = soup.find_all(
        string=re.compile(
            r"Cheapest\s+grade",
            re.IGNORECASE
        )
    )

    print(
        f"Cheapest grade matches found: {len(candidates)}"
    )

    if not candidates:
        return None

    for candidate in candidates:

        parent = candidate.parent

        for level in range(12):

            if parent is None:
                break

            imgs = parent.find_all("img")

            if len(imgs) >= 5:
                print(
                    f"Lineup container found at DOM level {level}"
                )
                print(
                    f"Images inside container: {len(imgs)}"
                )
                return parent

            parent = parent.parent

    return None


# ============================================================
# ITEM ID
# ============================================================

def extract_item_id(src):
    if not src:
        return None

    patterns = [
        r"/27-(\d+)",
        r"27-(\d+)",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            src
        )

        if match:
            return match.group(1)

    return None


# ============================================================
# ALT PARSER
# ============================================================

def parse_alt(alt):
    if not alt:
        return None

    alt = " ".join(
        alt.split()
    )

    if alt.lower() == "player card":
        return {
            "name": "Player Card",
            "overall": None,
            "version": "",
        }

    parts = [
        p.strip()
        for p in alt.split(" - ")
    ]

    if len(parts) < 2:
        return None

    name = parts[0]

    overall_match = re.search(
        r"\b(\d{2})\b",
        parts[1]
    )

    if not overall_match:
        return None

    overall = int(
        overall_match.group(1)
    )

    version = ""

    if len(parts) >= 3:
        version = " - ".join(
            parts[2:]
        ).strip()

    return {
        "name": name,
        "overall": overall,
        "version": version,
    }


# ============================================================
# FINISH
# ============================================================

def resolve_finish(item_id, version=""):

    if item_id in KNOWN_FINISHES:
        return KNOWN_FINISHES[item_id]

    version_lower = version.lower()

    if (
        "pristine" in version_lower
        and "holo" in version_lower
    ):
        return "PRISTINE HOLO"

    if (
        "holographic" in version_lower
        or "holo" in version_lower
    ):
        return "HOLO"

    return None


# ============================================================
# EXTRACT LINEUP
# ============================================================

def extract_lineup(container, slots):

    if container is None:
        return []

    cards = []

    imgs = container.find_all("img")

    print(
        f"Scanning {len(imgs)} images..."
    )

    for img in imgs:

        alt = img.get(
            "alt",
            ""
        ).strip()

        src = img.get(
            "src",
            ""
        )

        if not alt:
            continue

        # ----------------------------------------------------
        # EMPTY SLOT
        # ----------------------------------------------------

        if alt.lower() == "player card":

            cards.append({
                "name": "Player Card",
                "overall": None,
                "version": "",
                "item_id": None,
                "finish": None,
                "placeholder": True,
            })

            continue

        # ----------------------------------------------------
        # PLAYER
        # ----------------------------------------------------

        parsed = parse_alt(
            alt
        )

        if not parsed:
            continue

        item_id = extract_item_id(
            src
        )

        finish = resolve_finish(
            item_id,
            parsed["version"]
        )

        cards.append({
            "name": parsed["name"],
            "overall": parsed["overall"],
            "version": parsed["version"],
            "item_id": item_id,
            "finish": finish,
            "placeholder": False,
        })

    if len(cards) > slots:
        cards = cards[:slots]

    return cards


# ============================================================
# CARD KEY
# ============================================================

def card_key(card):

    if card.get("placeholder"):
        return None

    item_id = card.get(
        "item_id"
    )

    if item_id:
        return item_id

    return (
        card.get("name"),
        card.get("overall"),
        card.get("version"),
        card.get("finish"),
    )


# ============================================================
# CARD LABEL
# ============================================================

def card_label(card):

    name = card.get(
        "name",
        "Unknown"
    )

    overall = card.get(
        "overall",
        ""
    )

    finish = card.get(
        "finish"
    )

    player_text = (
        f"<b>{name} {overall}</b>"
    )

    if finish:
        return (
            f"{player_text}　·　{finish}"
        )

    return player_text


# ============================================================
# REAL CARDS
# ============================================================

def real_cards(cards):

    return [
        card
        for card in cards
        if not card.get(
            "placeholder"
        )
    ]


# ============================================================
# COMPARE
# ============================================================

def compare_cards(previous, current):

    previous_keys = [
        card_key(card)
        for card in real_cards(previous)
    ]

    current_keys = [
        card_key(card)
        for card in real_cards(current)
    ]

    previous_counter = Counter(
        previous_keys
    )

    current_counter = Counter(
        current_keys
    )

    outgoing = []
    incoming = []

    # --------------------------------------------------------
    # OUT
    # --------------------------------------------------------

    difference_out = (
        previous_counter
        - current_counter
    )

    for key, count in difference_out.items():

        matches = [
            card
            for card in real_cards(previous)
            if card_key(card) == key
        ]

        for card in matches[:count]:
            outgoing.append(card)

    # --------------------------------------------------------
    # IN
    # --------------------------------------------------------

    difference_in = (
        current_counter
        - previous_counter
    )

    for key, count in difference_in.items():

        matches = [
            card
            for card in real_cards(current)
            if card_key(card) == key
        ]

        for card in matches[:count]:
            incoming.append(card)

    return outgoing, incoming


# ============================================================
# UNKNOWN FINISH
# ============================================================

def has_unknown_finish(cards):

    for card in real_cards(cards):

        if not card.get("finish"):
            return True

    return False


# ============================================================
# PROCESS CATEGORY
# ============================================================

def process_category(
    category,
    config,
    state
):

    print()
    print("=" * 60)

    print(
        f"Checking "
        f"{config['emoji']} "
        f"{category.upper()} "
        f"({config['slots']} players)..."
    )

    print("=" * 60)

    previous = (
        state
        .get(category, {})
        .get("current", [])
    )

    try:

        html = fetch_page(
            config["url"]
        )

        soup = BeautifulSoup(
            html,
            "html.parser"
        )

        lineup_container = find_lineup(
            soup
        )

        if lineup_container is None:

            raise RuntimeError(
                "FUT.GG lineup container not found."
            )

        current = extract_lineup(
            lineup_container,
            config["slots"]
        )

        print(
            f"Rendered lineup: "
            f"{len(real_cards(current))}/"
            f"{config['slots']} real cards"
        )

        if not current:

            raise RuntimeError(
                "No cards extracted from lineup."
            )

        # ----------------------------------------------------
        # PRINT CARDS
        # ----------------------------------------------------

        for card in current:

            if card.get("placeholder"):
                print(
                    "- Player Card"
                )
                continue

            finish = (
                card.get("finish")
                or "UNKNOWN"
            )

            print(
                f"- {card['name']} "
                f"{card['overall']} "
                f"{card['version']} "
                f"— {finish}"
            )

        # ----------------------------------------------------
        # UNKNOWN FINISH
        # ----------------------------------------------------

        if has_unknown_finish(
            current
        ):

            print(
                "WARNING: "
                "Unknown finish detected."
            )

            print(
                "Previous state kept."
            )

            return {
                "status": "unknown_finish",
                "previous": previous,
                "current": previous,
                "incoming": [],
                "outgoing": [],
            }

        # ----------------------------------------------------
        # INITIAL
        # ----------------------------------------------------

        if not previous:

            print(
                "Initial lineup saved."
            )

            return {
                "status": "initial",
                "previous": [],
                "current": current,
                "incoming": [],
                "outgoing": [],
            }

        # ----------------------------------------------------
        # COMPARE
        # ----------------------------------------------------

        outgoing, incoming = compare_cards(
            previous,
            current
        )

        if outgoing:

            print("OUT:")

            for card in outgoing:

                print(
                    f"  - "
                    f"{card_label(card)}"
                )

        if incoming:

            print("IN:")

            for card in incoming:

                print(
                    f"  + "
                    f"{card_label(card)}"
                )

        if not outgoing and not incoming:

            print(
                "No feed changes."
            )

        return {
            "status": "ok",
            "previous": previous,
            "current": current,
            "incoming": incoming,
            "outgoing": outgoing,
        }

    except Exception as e:

        print()
        print(
            f"ERROR in {category}:"
        )

        print(
            repr(e)
        )

        print()
        print(
            "FULL TRACEBACK:"
        )

        traceback.print_exc()

        return {
            "status": "error",
            "previous": previous,
            "current": previous,
            "incoming": [],
            "outgoing": [],
        }


# ============================================================
# CURRENT LINEUP
# ============================================================

def format_current_lineup(
    current,
    incoming
):

    incoming_keys = {
        card_key(card)
        for card in incoming
    }

    lines = []

    for card in current:

        if card.get("placeholder"):
            continue

        key = card_key(
            card
        )

        prefix = ""

        if key in incoming_keys:
            prefix = "🟢 "

        lines.append(
            prefix
            + card_label(card)
        )

    if not lines:
        return "No real cards"

    return "\n".join(
        lines
    )


# ============================================================
# FORMAT CATEGORY
# ============================================================

def format_category(
    category,
    config,
    result
):

    emoji = config["emoji"]

    status = result["status"]

    previous = result["previous"]
    current = result["current"]

    incoming = result["incoming"]
    outgoing = result["outgoing"]

    lines = []

    # --------------------------------------------------------
    # TITLE
    # --------------------------------------------------------

    lines.append(
        f"{emoji} <b>{category.upper()}</b>"
    )

    lines.append("")

    # --------------------------------------------------------
    # UNKNOWN FINISH
    # --------------------------------------------------------

    if status == "unknown_finish":

        lines.append(
            "⚠️ Finish unresolved"
        )

        lines.append(
            "Previous state kept"
        )

        lines.append("")

        lines.append(
            "📋 Current lineup 📋"
        )

        lines.append("")

        lines.append(
            format_current_lineup(
                previous,
                []
            )
        )

        return "\n".join(
            lines
        )

    # --------------------------------------------------------
    # INITIAL
    # --------------------------------------------------------

    if status == "initial":

        lines.append(
            "Initial lineup saved"
        )

        lines.append("")

        lines.append(
            "📋 Current lineup 📋"
        )

        lines.append("")

        lines.append(
            format_current_lineup(
                current,
                []
            )
        )

        return "\n".join(
            lines
        )

    # --------------------------------------------------------
    # ERROR
    # --------------------------------------------------------

    if status == "error":

        lines.append(
            "⚠️ Feed unavailable"
        )

        lines.append(
            "Previous state kept"
        )

        lines.append("")

        lines.append(
            "📋 Current lineup 📋"
        )

        lines.append("")

        lines.append(
            format_current_lineup(
                previous,
                []
            )
        )

        return "\n".join(
            lines
        )

    # --------------------------------------------------------
    # OUT
    # --------------------------------------------------------

    if outgoing:

        lines.append(
            "🔴 <b>OUT</b>"
        )

        for card in outgoing:

            lines.append(
                f"🔴 {card_label(card)}"
            )

        lines.append("")

    # --------------------------------------------------------
    # IN
    # --------------------------------------------------------

    if incoming:

        lines.append(
            "🟢 <b>IN</b>"
        )

        for card in incoming:

            lines.append(
                f"🟢 {card_label(card)}"
            )

        lines.append("")

    # --------------------------------------------------------
    # NO CHANGES
    # --------------------------------------------------------

    if not outgoing and not incoming:

        lines.append(
            "No feed changes"
        )

        lines.append("")

    # --------------------------------------------------------
    # CURRENT LINEUP
    # --------------------------------------------------------

    lines.append(
        "📋 Current lineup 📋"
    )

    lines.append("")

    lines.append(
        format_current_lineup(
            current,
            incoming
        )
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
            "WARNING: "
            "TELEGRAM_BOT_TOKEN missing."
        )

        return

    if not TELEGRAM_CHAT_ID:

        print(
            "WARNING: "
            "TELEGRAM_CHAT_ID missing."
        )

        return

    url = (
        "https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}"
        "/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    try:

        response = requests.post(
            url,
            json=payload,
            timeout=30
        )

        print(
            f"Telegram HTTP status: "
            f"{response.status_code}"
        )

        if not response.ok:

            print(
                "Telegram response:"
            )

            print(
                response.text
            )

        response.raise_for_status()

        print(
            "Telegram message sent."
        )

    except Exception as e:

        print(
            f"Telegram error: {e}"
        )

        traceback.print_exc()


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        "Starting FUT.GG monitor..."
    )

    state = load_json(
        "players.json",
        {}
    )

    new_state = {}

    parts = []

    for category, config in PAGES.items():

        result = process_category(
            category,
            config,
            state
        )

        new_state[category] = {
            "current": result["current"]
        }

        parts.append(
            format_category(
                category,
                config,
                result
            )
        )

    # --------------------------------------------------------
    # SAVE
    # --------------------------------------------------------

    save_json(
        "players.json",
        new_state
    )

    print(
        "players.json updated."
    )

    # --------------------------------------------------------
    # TELEGRAM
    # --------------------------------------------------------

    message = (
        "\n\n"
        + "\n\n--------------------\n\n".join(
            parts
        )
    )

    print()
    print("=" * 60)
    print("TELEGRAM MESSAGE")
    print("=" * 60)
    print(message)
    print("=" * 60)

    send_telegram(
        message
    )

    print()
    print(
        "Monitor completed."
    )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    try:

        main()

    except Exception as e:

        print()
        print(
            "FATAL ERROR:"
        )

        print(
            repr(e)
        )

        print()
        print(
            "FULL TRACEBACK:"
        )

        traceback.print_exc()

        raise