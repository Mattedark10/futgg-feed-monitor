import os
import json
import re
import traceback
import requests

from bs4 import BeautifulSoup
from collections import Counter
from datetime import datetime, timezone


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

HOLO_URLS = {
    "PRISTINE HOLO": "https://www.fut.gg/holographic-cards/?finish=pristine",
    "HOLO": "https://www.fut.gg/holographic-cards/?finish=holographic",
}

DATABASE_FILE = "card_database.json"
PLAYERS_FILE = "players.json"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


# ============================================================
# HTTP
# ============================================================

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0 Safari/537.36"
    )
}


def get(url):
    response = requests.get(
        url,
        headers=HEADERS,
        timeout=30,
    )

    response.raise_for_status()

    return response.text


# ============================================================
# JSON
# ============================================================

def load_json(path, default):
    try:
        if not os.path.exists(path):
            return default

        with open(
            path,
            "r",
            encoding="utf-8",
        ) as f:
            return json.load(f)

    except Exception:
        return default


def save_json(path, data):
    with open(
        path,
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2,
        )


# ============================================================
# DATABASE
# ============================================================

def load_database():
    database = load_json(
        DATABASE_FILE,
        {},
    )

    if not isinstance(database, dict):
        database = {}

    database.setdefault(
        "items",
        {},
    )

    database.setdefault(
        "players",
        {},
    )

    database.setdefault(
        "meta",
        {},
    )

    return database


# ============================================================
# NORMALIZATION
# ============================================================

def normalize_text(value):
    if value is None:
        return ""

    value = str(value)

    value = (
        value
        .replace("\u00a0", " ")
        .replace("–", "-")
        .replace("—", "-")
    )

    value = " ".join(
        value.split()
    )

    return value.strip().lower()


def player_key(
    name,
    overall,
    version,
):
    return (
        f"{normalize_text(name)}|"
        f"{overall}|"
        f"{normalize_text(version)}"
    )


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
        "overall": int(
            match.group(2)
        ),
        "version": match.group(3).strip(),
        "placeholder": False,
    }


# ============================================================
# ITEM ID
# ============================================================

def extract_item_id(src):
    if not src:
        return None

    # FUT.GG:
    # .../27-67368151-xxxxx.webp

    match = re.search(
        r"27-(\d{5,})",
        src,
    )

    if match:
        return match.group(1)

    return None


# ============================================================
# BUILD HOLOGRAPHIC DATABASE
# ============================================================

def scan_holographic_database(database):
    print()
    print("=" * 60)
    print("Updating holographic database")
    print("=" * 60)

    discovered = {
        "PRISTINE HOLO": 0,
        "HOLO": 0,
    }

    for finish, url in HOLO_URLS.items():

        print(
            f"Fetching {finish}: {url}"
        )

        try:
            html = get(url)

        except Exception as e:
            print(
                f"Could not fetch {finish}: {e}"
            )
            continue

        soup = BeautifulSoup(
            html,
            "html.parser",
        )

        count = 0

        for img in soup.find_all("img"):

            alt = img.get(
                "alt",
                "",
            )

            parsed = parse_alt(
                alt
            )

            if not parsed:
                continue

            if parsed.get("placeholder"):
                continue

            name = parsed["name"]
            overall = parsed["overall"]
            version = parsed["version"]

            if not name or overall is None:
                continue

            key = player_key(
                name,
                overall,
                version,
            )

            database["players"][key] = {
                "name": name,
                "overall": overall,
                "version": version,
                "finish": finish,
            }

            src = img.get(
                "src",
                ""
            )

            item_id = extract_item_id(
                src
            )

            if item_id:
                database["items"][
                    str(item_id)
                ] = {
                    "name": name,
                    "overall": overall,
                    "version": version,
                    "finish": finish,
                }

            count += 1

        discovered[finish] = count

        print(
            f"Discovered {count} "
            f"{finish} entries"
        )

    database["meta"][
        "last_update"
    ] = datetime.now(
        timezone.utc
    ).isoformat()

    database["meta"][
        "source"
    ] = "FUT.GG"

    save_json(
        DATABASE_FILE,
        database,
    )

    print(
        f"Database items: "
        f"{len(database['items'])}"
    )

    print(
        f"Database player definitions: "
        f"{len(database['players'])}"
    )

    return database


# ============================================================
# FINISH RESOLUTION
# ============================================================

def resolve_finish(
    database,
    name,
    overall,
    version,
    item_id=None,
):
    # --------------------------------------------------------
    # 1. Exact Item ID
    # --------------------------------------------------------

    if item_id:
        item = database["items"].get(
            str(item_id)
        )

        if item:
            return item.get(
                "finish"
            )

    # --------------------------------------------------------
    # 2. Name + overall + version
    # --------------------------------------------------------

    key = player_key(
        name,
        overall,
        version,
    )

    player = database["players"].get(
        key
    )

    if player:
        return player.get(
            "finish"
        )

    # --------------------------------------------------------
    # 3. If not found in Holographic
    #    database, this is the standard
    #    version of the special card.
    # --------------------------------------------------------

    return "BASE"


# ============================================================
# PREVIOUS STATE
# ============================================================

def get_previous_category(
    state,
    category,
):
    if not isinstance(
        state,
        dict,
    ):
        return []

    value = state.get(
        category,
        [],
    )

    if isinstance(
        value,
        list,
    ):
        return value

    if isinstance(
        value,
        dict,
    ):
        current = value.get(
            "current",
            [],
        )

        if isinstance(
            current,
            list,
        ):
            return current

    return []


# ============================================================
# FIND CANDIDATE CONTAINERS
# ============================================================

def get_card_images(element):
    cards = []

    for img in element.find_all(
        "img"
    ):
        parsed = parse_alt(
            img.get(
                "alt",
                "",
            )
        )

        if parsed:
            cards.append(
                (
                    img,
                    parsed,
                )
            )

    return cards


def find_lineup(
    soup,
    expected_slots,
):
    candidates = []

    for element in soup.find_all(
        [
            "div",
            "section",
            "main",
            "article",
        ]
    ):
        text = element.get_text(
            " ",
            strip=True,
        )

        if "Cheapest grade" not in text:
            continue

        cards = get_card_images(
            element
        )

        if not cards:
            continue

        real_cards_count = sum(
            1
            for _, parsed in cards
            if not parsed.get(
                "placeholder"
            )
        )

        score = 0

        if len(cards) == expected_slots:
            score += 10000

        if real_cards_count == expected_slots:
            score += 500

        if len(cards) <= expected_slots + 2:
            score += 100

        candidates.append(
            (
                score,
                len(cards),
                element,
            )
        )

    print(
        f"Cheapest grade matches found: "
        f"{len(candidates)}"
    )

    if not candidates:
        return None

    candidates.sort(
        key=lambda x: x[0],
        reverse=True,
    )

    best = candidates[0]

    print(
        f"Selected lineup candidate: "
        f"{best[1]} cards "
        f"(score {best[0]})"
    )

    return best[2]


# ============================================================
# EXTRACT LINEUP
# ============================================================

def extract_lineup(
    container,
    expected_slots,
    database,
):
    images = container.find_all(
        "img"
    )

    print(
        f"Images/cards detected: "
        f"{len(images)}"
    )

    cards = []

    for img in images:

        parsed = parse_alt(
            img.get(
                "alt",
                "",
            )
        )

        if not parsed:
            continue

        if parsed.get(
            "placeholder"
        ):
            cards.append(
                parsed
            )
            continue

        item_id = extract_item_id(
            img.get(
                "src",
                "",
            )
        )

        finish = resolve_finish(
            database,
            parsed["name"],
            parsed["overall"],
            parsed["version"],
            item_id,
        )

        card = {
            "name": parsed["name"],
            "overall": parsed["overall"],
            "version": parsed["version"],
            "item_id": item_id,
            "finish": finish,
            "placeholder": False,
        }

        cards.append(
            card
        )

    # --------------------------------------------------------
    # Keep expected number of actual lineup slots
    # --------------------------------------------------------

    cards = cards[:expected_slots]

    real_count = sum(
        1
        for card in cards
        if not card.get(
            "placeholder"
        )
    )

    print(
        f"Rendered lineup: "
        f"{real_count}/{expected_slots} "
        f"real cards"
    )

    for card in cards:

        if card.get(
            "placeholder"
        ):
            print(
                "- Player Card"
            )
            continue

        print(
            f"- {card['name']} "
            f"{card['overall']} "
            f"{card['version']} "
            f"— ItemID "
            f"{card.get('item_id')} "
            f"— {card.get('finish')}"
        )

    return cards


# ============================================================
# FETCH + PARSE
# ============================================================

def fetch_lineup(
    category,
    config,
    database,
):
    print()
    print(
        f"Checking {config['emoji']} "
        f"{category.upper()} "
        f"({config['slots']} players)..."
    )

    print(
        "=" * 60
    )

    html = get(
        config["url"]
    )

    print(
        f"HTTP status: 200"
    )

    print(
        f"Downloaded: "
        f"{len(html)} characters"
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
        raise RuntimeError(
            "Lineup container not found"
        )

    return extract_lineup(
        container,
        config["slots"],
        database,
    )


# ============================================================
# CARD KEY
# ============================================================

def card_key(card):
    if not isinstance(
        card,
        dict,
    ):
        return None

    if card.get(
        "placeholder"
    ):
        return None

    item_id = card.get(
        "item_id"
    )

    if item_id:
        return str(
            item_id
        )

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
        "finish",
    )

    text = (
        f"<b>{name} {overall}</b>"
    )

    if finish:
        text += (
            f"　·　{finish}"
        )

    return text


# ============================================================
# REAL CARDS
# ============================================================

def real_cards(cards):
    return [
        card
        for card in cards
        if isinstance(
            card,
            dict,
        )
        and not card.get(
            "placeholder"
        )
    ]


# ============================================================
# COMPARE
# ============================================================

def compare_cards(
    previous,
    current,
):
    previous_counter = Counter(
        card_key(card)
        for card in real_cards(
            previous
        )
        if card_key(card)
        is not None
    )

    current_counter = Counter(
        card_key(card)
        for card in real_cards(
            current
        )
        if card_key(card)
        is not None
    )

    incoming = Counter()
    outgoing = Counter()

    for key, count in (
        current_counter.items()
    ):
        diff = (
            count
            - previous_counter.get(
                key,
                0,
            )
        )

        if diff > 0:
            incoming[key] = diff

    for key, count in (
        previous_counter.items()
    ):
        diff = (
            count
            - current_counter.get(
                key,
                0,
            )
        )

        if diff > 0:
            outgoing[key] = diff

    return (
        incoming,
        outgoing,
    )


# ============================================================
# FORMAT CURRENT
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

        if card.get(
            "placeholder"
        ):
            continue

        key = card_key(
            card
        )

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
            f"{prefix}"
            f"{card_label(card)}"
        )

    if not lines:
        return "—"

    return "\n".join(
        lines
    )


# ============================================================
# FORMAT CATEGORY
# ============================================================

def format_category(
    category,
    config,
    result,
):
    lines = [
        f"{config['emoji']} "
        f"<b>{category.upper()}</b>"
    ]

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

    status = result.get(
        "status"
    )

    if status == "error":
        lines += [
            "",
            "⚠️ Feed error",
            "Previous state kept",
        ]

    elif outgoing:
        lines += [
            "",
            "🔴 OUT",
        ]

        remaining = Counter(
            outgoing
        )

        for card in previous:

            key = card_key(
                card
            )

            if (
                key is not None
                and remaining.get(
                    key,
                    0,
                ) > 0
            ):
                lines.append(
                    f"🔴 "
                    f"{card_label(card)}"
                )

                remaining[key] -= 1

    elif incoming:
        lines += [
            "",
            "🟢 IN",
        ]

    else:
        lines += [
            "",
            "No feed changes",
        ]

    lines += [
        "",
        "📋 <b>Current lineup</b> 📋",
        format_current_lineup(
            current,
            incoming,
        ),
    ]

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

    # --------------------------------------------------------
    # Load database
    # --------------------------------------------------------

    database = load_database()

    # --------------------------------------------------------
    # Update Holographic database FIRST
    # --------------------------------------------------------

    database = scan_holographic_database(
        database
    )

    # --------------------------------------------------------
    # Load previous lineup state
    # --------------------------------------------------------

    previous_state = load_json(
        PLAYERS_FILE,
        {},
    )

    new_state = {}
    results = []

    # --------------------------------------------------------
    # Scan categories
    # --------------------------------------------------------

    for category, config in (
        PAGES.items()
    ):

        previous = get_previous_category(
            previous_state,
            category,
        )

        try:

            current = fetch_lineup(
                category,
                config,
                database,
            )

            if len(current) != config["slots"]:
                raise RuntimeError(
                    "Wrong lineup size"
                )

            incoming, outgoing = (
                compare_cards(
                    previous,
                    current,
                )
            )

            result = {
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
                f"ERROR processing "
                f"{category}: {e}"
            )

            traceback.print_exc()

            result = {
                "current": previous,
                "previous": previous,
                "incoming": [],
                "outgoing": [],
                "status": "error",
            }

        new_state[
            category
        ] = result["current"]

        results.append(
            (
                category,
                config,
                result,
            )
        )

    # --------------------------------------------------------
    # Save players
    # --------------------------------------------------------

    save_json(
        PLAYERS_FILE,
        new_state,
    )

    # --------------------------------------------------------
    # Telegram
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
    print(
        "=" * 60
    )
    print(
        "TELEGRAM MESSAGE"
    )
    print(
        "=" * 60
    )
    print(
        message
    )
    print(
        "=" * 60
    )

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