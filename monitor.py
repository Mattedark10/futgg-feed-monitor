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
    "HEROES": {
        "url": "https://www.fut.gg/fut-gallery/rarities/heroes/",
        "emoji": "🦸‍♂️",
        "slots": 5,
    },
    "HOLOGRAPHICS": {
        "url": "https://www.fut.gg/fut-gallery/rarities/holographics/",
        "emoji": "✨️",
        "slots": 5,
    },
    "SEASON 1": {
        "url": "https://www.fut.gg/fut-gallery/rarities/season-1/",
        "emoji": "1️⃣",
        "slots": 10,
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
    try:
        if not os.path.exists(path):
            return default

        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    except Exception:
        return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2,
        )


# ============================================================
# PREVIOUS STATE
# ============================================================

def get_previous_category(state, category):
    if not isinstance(state, dict):
        return []

    category_state = state.get(category, [])

    # New format
    if isinstance(category_state, list):
        return category_state

    # Old format
    if isinstance(category_state, dict):
        current = category_state.get("current", [])

        if isinstance(current, list):
            return current

    return []


# ============================================================
# FETCH PAGE
# ============================================================

def fetch_page(url):
    print(f"Fetching: {url}")

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/140.0 Safari/537.36"
        )
    }

    response = requests.get(
        url,
        headers=headers,
        timeout=30,
    )

    print(f"HTTP status: {response.status_code}")

    response.raise_for_status()

    print(f"Downloaded: {len(response.text)} characters")

    return response.text


# ============================================================
# FIND LINEUP
# ============================================================

def find_lineup(soup):
    candidates = []

    for element in soup.find_all(["div", "section", "main"]):
        text = element.get_text(" ", strip=True)

        if "Cheapest grade" in text:
            images = element.find_all("img")

            if images:
                candidates.append(
                    (
                        len(images),
                        element,
                    )
                )

    if not candidates:
        return None

    candidates.sort(
        key=lambda x: x[0],
        reverse=True,
    )

    container = candidates[0][1]

    print(
        f"Cheapest grade matches found: {len(candidates)}"
    )

    print(
        "Lineup container found at DOM level 1"
    )

    return container


# ============================================================
# ITEM ID
# ============================================================

def extract_item_id(src):
    if not src:
        return None

    # Example:
    # .../27-67368151-xxxxx.webp
    match = re.search(
        r"(?:^|/)(?:27-)?(\d{5,})",
        src,
    )

    if match:
        return match.group(1)

    # Fallback: find long number after 27-
    match = re.search(
        r"27-(\d{5,})",
        src,
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

    alt = " ".join(alt.split())

    if alt.lower() == "player card":
        return {
            "name": "Player Card",
            "overall": None,
            "version": None,
            "placeholder": True,
        }

    # Example:
    # Harder - 88 - Destined for Glory
    match = re.match(
        r"^(.*?)\s*-\s*(\d+)\s*-\s*(.*?)$",
        alt,
    )

    if match:
        return {
            "name": match.group(1).strip(),
            "overall": int(match.group(2)),
            "version": match.group(3).strip(),
            "placeholder": False,
        }

    return None


# ============================================================
# FINISH
# ============================================================

def resolve_finish(item_id):
    if not item_id:
        return None

    item_id = str(item_id)

    return KNOWN_FINISHES.get(item_id)


# ============================================================
# EXTRACT LINEUP
# ============================================================

def extract_lineup(container, expected_slots):
    images = container.find_all("img")

    print(
        f"Images inside container: {len(images)}"
    )

    print(
        f"Scanning {len(images)} images..."
    )

    lineup = []

    seen_signatures = set()

    for img in images:
        alt = img.get("alt", "")
        src = img.get("src", "")

        parsed = parse_alt(alt)

        if not parsed:
            continue

        # Ignore repeated HTML copies of the exact same image
        signature = (
            alt,
            src,
        )

        if signature in seen_signatures:
            continue

        seen_signatures.add(signature)

        if parsed.get("placeholder"):
            lineup.append(parsed)
            continue

        item_id = extract_item_id(src)

        finish = resolve_finish(item_id)

        card = {
            "name": parsed.get("name"),
            "overall": parsed.get("overall"),
            "version": parsed.get("version"),
            "item_id": item_id,
            "finish": finish,
            "placeholder": False,
        }

        lineup.append(card)

    # Keep only the actual lineup slots
    lineup = lineup[:expected_slots]

    real_count = sum(
        1
        for card in lineup
        if not card.get("placeholder")
    )

    print(
        f"Rendered lineup: {real_count}/{expected_slots} real cards"
    )

    # IMPORTANT:
    # Print Item ID for every real card
    for card in lineup:
        if card.get("placeholder"):
            print("- Player Card")
            continue

        print(
            f"- {card['name']} "
            f"{card['overall']} "
            f"{card['version']} "
            f"— ItemID {card.get('item_id')} "
            f"— {card.get('finish') or 'UNKNOWN'}"
        )

    return lineup


# ============================================================
# CARD KEY
# ============================================================

def card_key(card):
    if not isinstance(card, dict):
        return None

    if card.get("placeholder"):
        return None

    item_id = card.get("item_id")

    if item_id:
        return str(item_id)

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
    name = card.get("name", "Unknown")
    overall = card.get("overall", "")
    finish = card.get("finish")

    player_text = f"<b>{name} {overall}</b>"

    if finish:
        return f"{player_text}　·　{finish}"

    return player_text


# ============================================================
# REAL CARDS
# ============================================================

def real_cards(cards):
    return [
        card
        for card in cards
        if isinstance(card, dict)
        and not card.get("placeholder")
    ]


# ============================================================
# COMPARE
# ============================================================

def compare_cards(previous, current):
    previous_counter = Counter(
        card_key(card)
        for card in real_cards(previous)
        if card_key(card) is not None
    )

    current_counter = Counter(
        card_key(card)
        for card in real_cards(current)
        if card_key(card) is not None
    )

    incoming = Counter()

    for key, count in current_counter.items():
        difference = count - previous_counter.get(key, 0)

        if difference > 0:
            incoming[key] = difference

    outgoing = Counter()

    for key, count in previous_counter.items():
        difference = count - current_counter.get(key, 0)

        if difference > 0:
            outgoing[key] = difference

    return incoming, outgoing


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

def process_category(category, config, previous_state):
    print()
    print(
        f"Checking {config['emoji']} "
        f"{category} ({config['slots']} players)..."
    )
    print("=" * 60)

    try:
        html = fetch_page(config["url"])

        soup = BeautifulSoup(
            html,
            "html.parser",
        )

        container = find_lineup(soup)

        if not container:
            print("ERROR: Lineup container not found.")
            return {
                "current": get_previous_category(
                    previous_state,
                    category,
                ),
                "incoming": [],
                "outgoing": [],
                "status": "error",
                "message": "⚠️ Feed unavailable",
            }

        current = extract_lineup(
            container,
            config["slots"],
        )

        previous = get_previous_category(
            previous_state,
            category,
        )

        # Do not update state if any finish is unknown
        if has_unknown_finish(current):
            print(
                "WARNING: Unknown finish detected."
            )

            print(
                "Previous state kept."
            )

            return {
                "current": previous,
                "incoming": [],
                "outgoing": [],
                "status": "unresolved",
                "message": "⚠️ Finish unresolved\nPrevious state kept",
            }

        incoming, outgoing = compare_cards(
            previous,
            current,
        )

        return {
            "current": current,
            "incoming": list(incoming.elements()),
            "outgoing": list(outgoing.elements()),
            "status": "ok",
            "message": None,
        }

    except Exception as e:
        print(
            f"ERROR processing {category}: {e}"
        )

        traceback.print_exc()

        return {
            "current": get_previous_category(
                previous_state,
                category,
            ),
            "incoming": [],
            "outgoing": [],
            "status": "error",
            "message": "⚠️ Feed error\nPrevious state kept",
        }


# ============================================================
# CURRENT LINEUP FORMAT
# ============================================================

def format_current_lineup(current, incoming):
    lines = []

    incoming_counter = Counter(incoming)

    for card in current:
        if card.get("placeholder"):
            continue

        key = card_key(card)

        prefix = ""

        if (
            key is not None
            and incoming_counter.get(key, 0) > 0
        ):
            prefix = "🟢 "
            incoming_counter[key] -= 1

        lines.append(
            f"{prefix}{card_label(card)}"
        )

    if not lines:
        return "—"

    return "\n".join(lines)


# ============================================================
# CATEGORY FORMAT
# ============================================================

def format_category(category, config, result):
    lines = []

    lines.append(
        f"{config['emoji']} <b>{category}</b>"
    )

    status = result.get("status")

    if status == "unresolved":
        lines.append("")
        lines.append(
            "⚠️ Finish unresolved"
        )
        lines.append(
            "Previous state kept"
        )

    elif status == "error":
        lines.append("")
        lines.append(
            result.get(
                "message",
                "⚠️ Feed error",
            )
        )

    else:
        incoming = result.get(
            "incoming",
            [],
        )

        outgoing = result.get(
            "outgoing",
            [],
        )

        if outgoing:
            lines.append("")
            lines.append("🔴 OUT")

            # Find outgoing cards from previous state
            previous = result.get(
                "previous",
                [],
            )

            for key in outgoing:
                for card in previous:
                    if card_key(card) == key:
                        lines.append(
                            f"🔴 {card_label(card)}"
                        )
                        break

        elif incoming:
            lines.append("")
            lines.append(
                "🟢 IN"
            )

            current = result.get(
                "current",
                [],
            )

            incoming_counter = Counter(
                incoming
            )

            for card in current:
                key = card_key(card)

                if (
                    key is not None
                    and incoming_counter.get(key, 0) > 0
                ):
                    lines.append(
                        f"🟢 {card_label(card)}"
                    )

                    incoming_counter[key] -= 1

        else:
            lines.append("")
            lines.append(
                "No feed changes"
            )

    lines.append("")
    lines.append(
        "📋 <b>Current lineup</b> 📋"
    )
    lines.append(
        format_current_lineup(
            result.get("current", []),
            result.get("incoming", []),
        )
    )

    return "\n".join(lines)


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN:
        print(
            "TELEGRAM_BOT_TOKEN not configured."
        )
        return

    if not TELEGRAM_CHAT_ID:
        print(
            "TELEGRAM_CHAT_ID not configured."
        )
        return

    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    response = requests.post(
        url,
        json=payload,
        timeout=30,
    )

    print(
        f"Telegram status: {response.status_code}"
    )

    response.raise_for_status()


# ============================================================
# MAIN
# ============================================================

def main():
    state = load_json(
        "players.json",
        {},
    )

    new_state = {}

    results = []

    for category, config in PAGES.items():
        previous = get_previous_category(
            state,
            category,
        )

        result = process_category(
            category,
            config,
            state,
        )

        # Keep previous cards available for OUT detection
        result["previous"] = previous

        new_state[category] = result["current"]

        results.append(
            (
                category,
                config,
                result,
            )
        )

    # --------------------------------------------------------
    # SAVE STATE
    # --------------------------------------------------------

    save_json(
        "players.json",
        new_state,
    )

    # --------------------------------------------------------
    # TELEGRAM MESSAGE
    # --------------------------------------------------------

    parts = []

    for category, config, result in results:
        parts.append(
            format_category(
                category,
                config,
                result,
            )
        )

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

    send_telegram(message)


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    try:
        main()

    except Exception as e:
        print(
            f"FATAL ERROR: {e}"
        )

        traceback.print_exc()
        raise