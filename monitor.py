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
        "emoji": "🦸‍♂️",
        "slots": 5,
    },
    "Holographics": {
        "url": "https://www.fut.gg/fut-gallery/rarities/holographics/",
        "emoji": "✨️",
        "slots": 5,
    },
    "Season 1": {
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
    # HEROES
    "67335170": "PRISTINE HOLO",
    "67114537": "PRISTINE HOLO",
    "67335237": "PRISTINE HOLO",
    "67371135": "PRISTINE HOLO",
    "67186651": "PRISTINE HOLO",

    "226306": "BASE",
    "233700": "BASE",

    # HOLOGRAPHICS
    "67335157": "PRISTINE HOLO",
    "67384140": "PRISTINE HOLO",
    "67275770": "PRISTINE HOLO",
    "67180472": "PRISTINE HOLO",
    "67298908": "PRISTINE HOLO",

    # SEASON 1
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

    value = state.get(category, [])

    if isinstance(value, list):
        return value

    if isinstance(value, dict):
        current = value.get("current", [])

        if isinstance(current, list):
            return current

    return []


# ============================================================
# FETCH
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

    print(
        f"HTTP status: {response.status_code}"
    )

    response.raise_for_status()

    print(
        f"Downloaded: {len(response.text)} characters"
    )

    return response.text


# ============================================================
# ITEM ID
# ============================================================

def extract_item_id(src):
    if not src:
        return None

    # FUT.GG asset examples:
    # .../27-67368151-xxxxx.webp

    match = re.search(
        r"27-(\d{5,})",
        src,
    )

    if match:
        return match.group(1)

    # Fallback
    match = re.search(
        r"/(\d{5,})[-_]",
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

    match = re.match(
        r"^(.*?)\s*-\s*(\d+)\s*-\s*(.*?)$",
        alt,
    )

    if not match:
        return None

    return {
        "name": match.group(1).strip(),
        "overall": int(match.group(2)),
        "version": match.group(3).strip(),
        "placeholder": False,
    }


# ============================================================
# FINISH
# ============================================================

def resolve_finish(item_id):
    if not item_id:
        return None

    return KNOWN_FINISHES.get(
        str(item_id)
    )


# ============================================================
# IMAGE -> CARD
# ============================================================

def image_to_card(img):
    alt = img.get("alt", "")
    src = img.get("src", "")

    parsed = parse_alt(alt)

    if not parsed:
        return None

    if parsed.get("placeholder"):
        return parsed

    item_id = extract_item_id(src)

    return {
        "name": parsed["name"],
        "overall": parsed["overall"],
        "version": parsed["version"],
        "item_id": item_id,
        "finish": resolve_finish(item_id),
        "placeholder": False,
    }


# ============================================================
# LINEUP CANDIDATE
# ============================================================

def candidate_cards(element):
    cards = []

    for img in element.find_all("img"):
        card = image_to_card(img)

        if card:
            cards.append(card)

    return cards


def candidate_score(cards, expected_slots):
    """
    Score a possible lineup.

    Prefer:
    - exact number of slots
    - known finishes
    - real cards
    - fewer duplicate HTML copies
    """

    if not cards:
        return -999999

    real = [
        c for c in cards
        if not c.get("placeholder")
    ]

    placeholders = [
        c for c in cards
        if c.get("placeholder")
    ]

    # Exact slot count is extremely important
    score = 0

    if len(cards) == expected_slots:
        score += 10000

    # A candidate with more than the required slots is likely
    # a parent/container containing multiple lineups.
    if len(cards) > expected_slots:
        score -= (len(cards) - expected_slots) * 100

    # Known finishes are strong evidence.
    for card in real:
        if card.get("finish"):
            score += 100

    # Real cards are preferred.
    score += len(real) * 20

    # Player Card placeholders are legitimate Season 1 slots.
    score += len(placeholders) * 10

    return score


# ============================================================
# FIND BEST LINEUP
# ============================================================

def find_lineup(soup, expected_slots):
    candidates = []

    # Search all elements containing "Cheapest grade".
    for element in soup.find_all(
        ["div", "section", "main", "article"]
    ):
        text = element.get_text(
            " ",
            strip=True,
        )

        if "Cheapest grade" not in text:
            continue

        cards = candidate_cards(element)

        if not cards:
            continue

        score = candidate_score(
            cards,
            expected_slots,
        )

        candidates.append(
            (
                score,
                len(cards),
                element,
                cards,
            )
        )

    print(
        f"Cheapest grade matches found: {len(candidates)}"
    )

    if not candidates:
        return None

    # Highest score wins.
    candidates.sort(
        key=lambda x: x[0],
        reverse=True,
    )

    best_score, best_count, best_element, best_cards = (
        candidates[0]
    )

    print(
        f"Selected lineup candidate: "
        f"{best_count} cards "
        f"(score {best_score})"
    )

    return best_element


# ============================================================
# EXTRACT LINEUP
# ============================================================

def extract_lineup(container, expected_slots):
    cards = candidate_cards(container)

    print(
        f"Images/cards detected in selected container: "
        f"{len(cards)}"
    )

    # --------------------------------------------------------
    # If the selected container still contains more cards than
    # the expected lineup, try to find a consecutive window
    # containing the expected number of valid cards.
    # --------------------------------------------------------

    if len(cards) > expected_slots:
        windows = []

        for start in range(
            0,
            len(cards) - expected_slots + 1,
        ):
            window = cards[
                start:start + expected_slots
            ]

            score = candidate_score(
                window,
                expected_slots,
            )

            windows.append(
                (
                    score,
                    start,
                    window,
                )
            )

        windows.sort(
            key=lambda x: x[0],
            reverse=True,
        )

        if windows:
            cards = windows[0][2]

    cards = cards[:expected_slots]

    real_count = sum(
        1
        for card in cards
        if not card.get("placeholder")
    )

    print(
        f"Rendered lineup: "
        f"{real_count}/{expected_slots} real cards"
    )

    for card in cards:
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

    return cards


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
# LABEL
# ============================================================

def card_label(card):
    name = card.get(
        "name",
        "Unknown",
    )

    overall = card.get(
        "overall",
        "",
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
    outgoing = Counter()

    for key, count in current_counter.items():
        diff = count - previous_counter.get(
            key,
            0,
        )

        if diff > 0:
            incoming[key] = diff

    for key, count in previous_counter.items():
        diff = count - current_counter.get(
            key,
            0,
        )

        if diff > 0:
            outgoing[key] = diff

    return incoming, outgoing


# ============================================================
# UNKNOWN CHECK
# ============================================================

def has_unknown_finish(cards):
    """
    Only cards in the FINAL SELECTED LINEUP are checked.
    Images outside the selected lineup are irrelevant.
    """

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
    previous_state,
):
    print()
    print(
        f"Checking {config['emoji']} "
        f"{category.upper()} "
        f"({config['slots']} players)..."
    )

    print("=" * 60)

    previous = get_previous_category(
        previous_state,
        category,
    )

    try:
        html = fetch_page(
            config["url"]
        )

        soup = BeautifulSoup(
            html,
            "html.parser",
        )

        container = find_lineup(
            soup,
            config["slots"],
        )

        if not container:
            print(
                "ERROR: Lineup container not found."
            )

            return {
                "current": previous,
                "previous": previous,
                "incoming": [],
                "outgoing": [],
                "status": "error",
            }

        current = extract_lineup(
            container,
            config["slots"],
        )

        # ----------------------------------------------------
        # IMPORTANT
        # Only the final selected lineup is checked.
        # ----------------------------------------------------

        if len(current) != config["slots"]:
            print(
                "WARNING: Wrong lineup size."
            )

            print(
                "Previous state kept."
            )

            return {
                "current": previous,
                "previous": previous,
                "incoming": [],
                "outgoing": [],
                "status": "unresolved",
            }

        if has_unknown_finish(current):
            print(
                "WARNING: Unknown finish detected "
                "inside selected lineup."
            )

            print(
                "Previous state kept."
            )

            return {
                "current": previous,
                "previous": previous,
                "incoming": [],
                "outgoing": [],
                "status": "unresolved",
            }

        incoming, outgoing = compare_cards(
            previous,
            current,
        )

        return {
            "current": current,
            "previous": previous,
            "incoming": list(
                incoming.elements()
            ),
            "outgoing": list(
                outgoing.elements()
            ),
            "status": "ok",
        }

    except Exception as e:
        print(
            f"ERROR processing {category}: {e}"
        )

        traceback.print_exc()

        return {
            "current": previous,
            "previous": previous,
            "incoming": [],
            "outgoing": [],
            "status": "error",
        }


# ============================================================
# CURRENT LINEUP
# ============================================================

def format_current_lineup(
    current,
    incoming,
):
    lines = []

    incoming_counter = Counter(
        incoming
    )

    for card in current:
        if card.get("placeholder"):
            continue

        key = card_key(card)

        prefix = ""

        if (
            key is not None
            and incoming_counter.get(
                key,
                0,
            ) > 0
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
# CATEGORY TELEGRAM
# ============================================================

def format_category(
    category,
    config,
    result,
):
    lines = []

    lines.append(
        f"{config['emoji']} "
        f"<b>{category.upper()}</b>"
    )

    status = result.get(
        "status"
    )

    incoming = result.get(
        "incoming",
        [],
    )

    outgoing = result.get(
        "outgoing",
        [],
    )

    previous = result.get(
        "previous",
        [],
    )

    current = result.get(
        "current",
        [],
    )

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
            "⚠️ Feed error"
        )
        lines.append(
            "Previous state kept"
        )

    else:
        if outgoing:
            lines.append("")
            lines.append(
                "🔴 OUT"
            )

            remaining = Counter(
                outgoing
            )

            for card in previous:
                key = card_key(card)

                if (
                    key is not None
                    and remaining.get(
                        key,
                        0,
                    ) > 0
                ):
                    lines.append(
                        f"🔴 {card_label(card)}"
                    )

                    remaining[key] -= 1

        elif incoming:
            lines.append("")
            lines.append(
                "🟢 IN"
            )

            # The current lineup already marks
            # incoming cards with 🟢.
            # No duplicate listing here.
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
            current,
            incoming,
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
        "https://api.telegram.org/"
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
        f"Telegram status: "
        f"{response.status_code}"
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

        result = process_category(
            category,
            config,
            state,
        )

        new_state[category] = (
            result["current"]
        )

        results.append(
            (
                category,
                config,
                result,
            )
        )

    # --------------------------------------------------------
    # SAVE
    # --------------------------------------------------------

    save_json(
        "players.json",
        new_state,
    )

    # --------------------------------------------------------
    # TELEGRAM
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

    send_telegram(
        message
    )


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