import os
import re
import json
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

PLAYERS_FILE = "players.json"
CACHE_FILE = "card_cache.json"

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    )
}

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
# JSON HELPERS
# ============================================================

def load_json(filename, default):
    if not os.path.exists(filename):
        return default

    try:
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(filename, data):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )


# ============================================================
# FIND LINEUP
# ============================================================

def find_lineup(soup):
    text = soup.get_text(" ", strip=True)

    patterns = [
        r"Cheapest grade [^ ]+ lineup",
        r"Cheapest grade .*? lineup",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.I)

        if match:
            return match.group(0)

    return None


# ============================================================
# ITEM ID
# ============================================================

def extract_item_id(src):
    if not src:
        return None

    match = re.search(
        r"/27-(\d+)(?:\.|/)",
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

    overall = overall_match.group(1)

    version = ""

    if len(parts) >= 3:
        version = " - ".join(parts[2:]).strip()

    return {
        "name": name,
        "overall": overall,
        "version": version,
    }


# ============================================================
# FINISH RESOLUTION
# ============================================================

def resolve_finish(item_id, cache, previous_cards):
    if not item_id:
        return None

    item_id = str(item_id)

    if item_id in KNOWN_FINISHES:
        finish = KNOWN_FINISHES[item_id]
        cache[item_id] = finish
        return finish

    if item_id in cache:
        return cache[item_id]

    for card in previous_cards:
        if not card:
            continue

        if str(card.get("item_id")) == item_id:
            finish = card.get("finish")

            if finish:
                cache[item_id] = finish
                return finish

    return None


# ============================================================
# EXTRACT LINEUP
# ============================================================

def extract_lineup(
    soup,
    expected_slots,
    cache,
    previous_cards
):
    lineup = []

    images = soup.find_all("img")

    cards = []

    for img in images:
        alt = img.get("alt", "").strip()
        src = img.get("src", "")

        if not alt:
            continue

        parsed = parse_alt(alt)

        if not parsed:
            continue

        item_id = extract_item_id(src)

        if not item_id:
            continue

        cards.append({
            "name": parsed["name"],
            "overall": parsed["overall"],
            "version": parsed["version"],
            "item_id": item_id,
        })

    unique_cards = []
    seen_occurrences = set()

    for card in cards:
        occurrence_key = (
            card["item_id"],
            card["name"],
            card["overall"],
            card["version"],
        )

        if occurrence_key in seen_occurrences:
            continue

        seen_occurrences.add(occurrence_key)
        unique_cards.append(card)

    cards = unique_cards

    real_count = min(
        len(cards),
        expected_slots
    )

    cards = cards[:real_count]

    for card in cards:
        item_id = card["item_id"]

        finish = resolve_finish(
            item_id,
            cache,
            previous_cards
        )

        card["finish"] = finish

        lineup.append(card)

    while len(lineup) < expected_slots:
        lineup.append(None)

    return lineup


# ============================================================
# CARD KEY
# ============================================================

def card_key(card):
    if not card:
        return None

    return (
        str(card.get("item_id")),
        card.get("name"),
        str(card.get("overall")),
        card.get("finish"),
    )


# ============================================================
# CARD LABEL
# ============================================================

def card_label(card):
    if not card:
        return "Player Card"

    name = card.get("name", "?")
    overall = card.get("overall", "?")
    finish = card.get("finish")

    # Nome + overall in grassetto
    player_text = f"<b>{name} {overall}</b>"

    if finish:
        return f"{player_text} — {finish}"

    return player_text


# ============================================================
# REAL CARDS
# ============================================================

def real_cards(lineup):
    return [
        card
        for card in lineup
        if card is not None
    ]


# ============================================================
# COMPARE CARDS
# ============================================================

def compare_cards(previous, current):
    previous_counter = Counter(
        card_key(card)
        for card in real_cards(previous)
    )

    current_counter = Counter(
        card_key(card)
        for card in real_cards(current)
    )

    outs = []
    ins = []

    for key, count in previous_counter.items():
        difference = count - current_counter.get(key, 0)

        for _ in range(max(0, difference)):
            outs.append(key)

    for key, count in current_counter.items():
        difference = count - previous_counter.get(key, 0)

        for _ in range(max(0, difference)):
            ins.append(key)

    return outs, ins


# ============================================================
# UNKNOWN FINISH
# ============================================================

def has_unknown_finish(lineup):
    for card in real_cards(lineup):
        if not card.get("finish"):
            return True

    return False


# ============================================================
# PROCESS CATEGORY
# ============================================================

def process_category(
    category,
    config,
    players,
    cache
):
    url = config["url"]
    expected_slots = config["slots"]

    print("=" * 60)
    print(f"Scanning {category.upper()}")
    print(url)
    print("=" * 60)

    previous = players.get(category)

    if not previous:
        previous = []

    while len(previous) < expected_slots:
        previous.append(None)

    previous = previous[:expected_slots]

    # --------------------------------------------------------
    # REQUEST
    # --------------------------------------------------------

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=30
        )

        response.raise_for_status()

    except Exception as e:
        print(f"Request error: {e}")

        return {
            "changed": False,
            "error": True,
            "slots": previous,
            "outs": [],
            "ins": [],
        }

    # --------------------------------------------------------
    # PARSE
    # --------------------------------------------------------

    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )

    find_lineup(soup)

    current = extract_lineup(
        soup,
        expected_slots,
        cache,
        previous
    )

    print(
        f"Rendered lineup: "
        f"{len(real_cards(current))}/{expected_slots} real cards"
    )

    # --------------------------------------------------------
    # VALIDATION
    # --------------------------------------------------------

    if len(current) != expected_slots:
        print(
            f"Invalid lineup size: "
            f"{len(current)}/{expected_slots}"
        )

        return {
            "changed": False,
            "error": True,
            "slots": previous,
            "outs": [],
            "ins": [],
        }

    # --------------------------------------------------------
    # UNKNOWN FINISH
    # --------------------------------------------------------

    if has_unknown_finish(current):
        print("Finish unresolved - keeping previous state")

        return {
            "changed": False,
            "error": True,
            "unresolved": True,
            "slots": previous,
            "outs": [],
            "ins": [],
        }

    # --------------------------------------------------------
    # INITIAL RUN
    # --------------------------------------------------------

    if not previous:
        players[category] = current

        return {
            "changed": False,
            "initial": True,
            "error": False,
            "slots": current,
            "outs": [],
            "ins": [],
        }

    # --------------------------------------------------------
    # COMPARE
    # --------------------------------------------------------

    outs, ins = compare_cards(
        previous,
        current
    )

    changed = bool(
        outs or ins
    )

    players[category] = current

    return {
        "changed": changed,
        "initial": False,
        "error": False,
        "slots": current,
        "outs": outs,
        "ins": ins,
    }


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN:
        print("TELEGRAM_BOT_TOKEN missing")
        return

    if not TELEGRAM_CHAT_ID:
        print("TELEGRAM_CHAT_ID missing")
        return

    url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
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

        response.raise_for_status()

        print("Telegram message sent")

    except Exception as e:
        print(f"Telegram error: {e}")


# ============================================================
# FORMAT CATEGORY
# ============================================================

def format_category(
    category,
    config,
    result
):
    emoji = config["emoji"]

    lines = []

    lines.append(
        f"{emoji} {category}"
    )

    lines.append("")

    # --------------------------------------------------------
    # UNRESOLVED
    # --------------------------------------------------------

    if result.get("unresolved"):
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

        for card in real_cards(
            result["slots"]
        ):
            lines.append(
                card_label(card)
            )

        return "\n".join(lines)

    # --------------------------------------------------------
    # ERROR
    # --------------------------------------------------------

    if result.get("error"):
        lines.append(
            "⚠️ Feed error"
        )

        lines.append(
            "Previous state kept"
        )

        lines.append("")

        lines.append(
            "📋 Current lineup 📋"
        )

        lines.append("")

        for card in real_cards(
            result["slots"]
        ):
            lines.append(
                card_label(card)
            )

        return "\n".join(lines)

    # --------------------------------------------------------
    # INITIAL
    # --------------------------------------------------------

    if result.get("initial"):
        lines.append(
            "Initial lineup saved"
        )

    # --------------------------------------------------------
    # NORMAL
    # --------------------------------------------------------

    else:
        outs = result.get(
            "outs",
            []
        )

        ins = result.get(
            "ins",
            []
        )

        # ----------------------------------------------------
        # OUT
        # ----------------------------------------------------

        if outs:
            lines.append(
                "🔴 OUT"
            )

            for key in outs:
                if key:
                    _, name, overall, finish = key

                    if finish:
                        lines.append(
                            f"<b>{name} {overall}</b> — {finish}"
                        )
                    else:
                        lines.append(
                            f"<b>{name} {overall}</b>"
                        )

        # ----------------------------------------------------
        # IN
        # ----------------------------------------------------

        if ins:
            lines.append(
                "🟢 IN"
            )

            for key in ins:
                if key:
                    _, name, overall, finish = key

                    if finish:
                        lines.append(
                            f"<b>{name} {overall}</b> — {finish}"
                        )
                    else:
                        lines.append(
                            f"<b>{name} {overall}</b>"
                        )

        if not outs and not ins:
            lines.append(
                "No feed changes"
            )

    # --------------------------------------------------------
    # CURRENT LINEUP
    # --------------------------------------------------------

    lines.append("")

    lines.append(
        "📋 Current lineup 📋"
    )

    lines.append("")

    incoming_keys = Counter(
        result.get("ins", [])
    )

    for card in real_cards(
        result["slots"]
    ):
        key = card_key(card)

        if incoming_keys.get(key, 0) > 0:
            lines.append(
                f"🟢 {card_label(card)}"
            )

            incoming_keys[key] -= 1

        else:
            lines.append(
                card_label(card)
            )

    return "\n".join(lines)


# ============================================================
# MAIN
# ============================================================

def main():
    players = load_json(
        PLAYERS_FILE,
        {}
    )

    cache = load_json(
        CACHE_FILE,
        {}
    )

    results = {}

    for category, config in PAGES.items():
        results[category] = process_category(
            category,
            config,
            players,
            cache
        )

    # --------------------------------------------------------
    # SAVE
    # --------------------------------------------------------

    save_json(
        PLAYERS_FILE,
        players
    )

    save_json(
        CACHE_FILE,
        cache
    )

    # --------------------------------------------------------
    # TELEGRAM MESSAGE
    # --------------------------------------------------------

    parts = []

    for category, config in PAGES.items():
        parts.append(
            format_category(
                category,
                config,
                results[category]
            )
        )

    # --------------------------------------------------------
    # SEPARATOR BETWEEN CATEGORIES
    # --------------------------------------------------------

    message = (
        "\n\n"
        + "\n\n--------------------\n\n".join(
            parts
        )
    )

    print("\n" + "=" * 60)
    print("TELEGRAM MESSAGE")
    print("=" * 60)
    print(message)
    print("=" * 60)

    send_telegram(message)


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    main()