import os
import re
import json
import html
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup


# ============================================================
# CONFIG
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

PLAYERS_FILE = "players.json"
CARD_DATABASE_FILE = "card_database.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    )
}


CATEGORIES = {
    "Heroes": {
        "emoji": "🦸‍♂️",
        "url": "https://www.fut.gg/fut-gallery/rarities/heroes/",
        "slots": 5,
    },

    "Holographics": {
        "emoji": "✨️",
        "url": "https://www.fut.gg/fut-gallery/rarities/holographics/",
        "slots": 5,
    },

    "Season 1": {
        "emoji": "1️⃣",
        "url": "https://www.fut.gg/fut-gallery/rarities/season-1/",
        "slots": 10,
    },
}


# ============================================================
# KNOWN FINISHES
# ============================================================

KNOWN_FINISHES = {

    # --------------------------------------------------------
    # PRISTINE HOLO
    # --------------------------------------------------------

    "67335170": "PRISTINE HOLO",
    "67114537": "PRISTINE HOLO",
    "67335237": "PRISTINE HOLO",
    "67371135": "PRISTINE HOLO",
    "67342564": "PRISTINE HOLO",
    "67186651": "PRISTINE HOLO",

    "67335573": "PRISTINE HOLO",
    "67135573": "PRISTINE HOLO",

    "67335157": "PRISTINE HOLO",
    "67384140": "PRISTINE HOLO",
    "67275770": "PRISTINE HOLO",
    "67180472": "PRISTINE HOLO",
    "67298908": "PRISTINE HOLO",

    "67348095": "PRISTINE HOLO",
    "67368151": "PRISTINE HOLO",

    # --------------------------------------------------------
    # HOLO
    # --------------------------------------------------------

    "67179830": "HOLO",
    "67188263": "HOLO",
    "67368429": "HOLO",
    "67353040": "HOLO",
    "67372629": "HOLO",
    "67386815": "HOLO",
    "67374557": "HOLO",

    # --------------------------------------------------------
    # BASE
    # --------------------------------------------------------

    "226306": "BASE",
    "233700": "BASE",
    "5673": "BASE",
    "50590935": "BASE",
    "50590026": "BASE",
    "50570879": "BASE",
}


# ============================================================
# HTTP
# ============================================================

def fetch_url(url):
    print(f"Fetching: {url}")

    response = requests.get(
        url,
        headers=HEADERS,
        timeout=30,
    )

    print(f"HTTP status: {response.status_code}")
    print(f"Downloaded: {len(response.text)} characters")

    response.raise_for_status()

    return response.text


# ============================================================
# IMAGE / PLAYER VALIDATION
# ============================================================

def parse_player_alt(img):
    if not img:
        return None

    values = [
        img.get("alt"),
        img.get("data-alt"),
        img.get("title"),
        img.get("aria-label"),
    ]

    for value in values:

        if not value:
            continue

        value = html.unescape(
            str(value)
        ).strip()

        if value:
            return value

    return None


def is_player_placeholder(name):
    if not name:
        return False

    normalized = re.sub(
        r"\s+",
        " ",
        name.lower().strip()
    )

    normalized = normalized.replace(
        "–",
        "-"
    )

    normalized = normalized.replace(
        "—",
        "-"
    )

    placeholders = {
        "player card",
        "player-card",
        "player card placeholder",
        "empty slot",
        "empty",
    }

    return normalized in placeholders


def extract_overall(name):
    if not name:
        return None

    # Normal FC ratings.
    matches = re.findall(
        r"(?<!\d)(\d{2})(?!\d)",
        name
    )

    for value in matches:

        rating = int(value)

        # FC ratings we care about.
        if 70 <= rating <= 99:
            return rating

    return None


def is_bad_ui_text(name):
    if not name:
        return True

    normalized = name.lower().strip()

    bad_words = [
        "gallery token",
        "grading score",
        "fc coin",
        "fc coins",
        "gallery points",
        "buy now",
        "sell",
        "search",
        "filter",
        "close",
        "menu",
        "logo",
        "icon",
        "next",
        "previous",
        "arrow",
        "star",
        "token",
        "coin",
    ]

    for word in bad_words:

        if word in normalized:
            return True

    return False


def is_real_player_card(img):
    """
    A valid player-card image must have:

    - a player name
    - a valid FC rating
    - no known UI text
    """

    name = parse_player_alt(img)

    if not name:
        return False

    if is_player_placeholder(name):
        return False

    if is_bad_ui_text(name):
        return False

    overall = extract_overall(name)

    if overall is None:
        return False

    return True


def is_valid_lineup_image(img):
    """
    Valid lineup slot:

    1. Real player card
    OR
    2. Player Card placeholder
    """

    name = parse_player_alt(img)

    if not name:
        return False

    if is_player_placeholder(name):
        return True

    return is_real_player_card(img)


# ============================================================
# ITEM ID EXTRACTION
# ============================================================

def extract_item_ids(text):
    if not text:
        return []

    text = html.unescape(
        str(text)
    )

    patterns = [
        r"item[_\-\s]?id[\"'\s:=]+(\d{4,})",
        r"itemId[\"'\s:=]+(\d{4,})",
        r"itemID[\"'\s:=]+(\d{4,})",
        r"item[_\-]?id=(\d{4,})",
        r"item/(\d{4,})",
    ]

    found = []

    for pattern in patterns:

        matches = re.findall(
            pattern,
            text,
            flags=re.IGNORECASE
        )

        for match in matches:

            if match not in found:
                found.append(match)

    return found


def extract_item_id_from_attributes(element):

    if not element:
        return None

    attributes = [
        "src",
        "data-src",
        "data-lazy-src",
        "data-original",
        "srcset",
        "data-srcset",
        "href",
        "data-href",
        "data-item-id",
        "data-itemid",
    ]

    for attr in attributes:

        value = element.get(attr)

        if not value:
            continue

        ids = extract_item_ids(value)

        if ids:
            return ids[0]

    return None


def find_unique_card_wrapper(img):

    if not img:
        return None

    current = img

    for _ in range(6):

        current = current.parent

        if not current:
            break

        images = current.find_all(
            "img"
        )

        valid_images = [
            x
            for x in images
            if is_real_player_card(x)
        ]

        # IMPORTANT:
        # Never accept a container containing multiple
        # player cards.
        if len(valid_images) != 1:
            continue

        if valid_images[0] is not img:
            continue

        ids = extract_item_ids(
            str(current)
        )

        if ids:
            return current

    return None


def find_item_id_for_image(img):

    if not img:
        return None

    # --------------------------------------------------------
    # 1. IMAGE ATTRIBUTES
    # --------------------------------------------------------

    item_id = extract_item_id_from_attributes(
        img
    )

    if item_id:
        return item_id

    # --------------------------------------------------------
    # 2. PICTURE
    # --------------------------------------------------------

    picture = img.find_parent(
        "picture"
    )

    if picture:

        item_id = extract_item_id_from_attributes(
            picture
        )

        if item_id:
            return item_id

        for source in picture.find_all(
            "source",
            recursive=False
        ):

            item_id = extract_item_id_from_attributes(
                source
            )

            if item_id:
                return item_id

    # --------------------------------------------------------
    # 3. IMMEDIATE LINK
    # --------------------------------------------------------

    parent = img.parent

    if parent and parent.name == "a":

        item_id = extract_item_id_from_attributes(
            parent
        )

        if item_id:
            return item_id

    # --------------------------------------------------------
    # 4. UNIQUE CARD WRAPPER
    # --------------------------------------------------------

    wrapper = find_unique_card_wrapper(
        img
    )

    if wrapper:

        ids = extract_item_ids(
            str(wrapper)
        )

        if ids:
            return ids[0]

    return None


# ============================================================
# DATABASE
# ============================================================

def load_card_database():

    if not os.path.exists(
        CARD_DATABASE_FILE
    ):
        return {}

    try:

        with open(
            CARD_DATABASE_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

        if isinstance(data, dict):
            return data

    except Exception as e:

        print(
            f"Error loading card database: {e}"
        )

    return {}


def finish_from_database(
    item_id,
    database
):

    if not item_id:
        return "UNKNOWN"

    item_id = str(
        item_id
    )

    if item_id in KNOWN_FINISHES:
        return KNOWN_FINISHES[item_id]

    record = database.get(
        item_id
    )

    if isinstance(record, dict):

        finish = record.get(
            "finish"
        )

        if finish:
            return finish

    return "UNKNOWN"


def add_known_finishes(
    database
):

    added = 0

    for item_id, finish in KNOWN_FINISHES.items():

        item_id = str(
            item_id
        )

        if item_id not in database:

            database[item_id] = {
                "item_id": item_id,
                "player": "",
                "overall": None,
                "rarity": "",
                "version": "",
                "finish": finish,
            }

            added += 1

        else:

            database[item_id][
                "finish"
            ] = finish

    return added


def save_card_database(
    database
):

    with open(
        CARD_DATABASE_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            database,
            f,
            ensure_ascii=False,
            indent=2
        )

    players = set()

    for record in database.values():

        if not isinstance(record, dict):
            continue

        player = record.get(
            "player"
        )

        if player:
            players.add(
                player
            )

    print()
    print(
        f"Database items: {len(database)}"
    )

    print(
        f"Database players: {len(players)}"
    )


# ============================================================
# STATE
# ============================================================

def load_previous_state():

    if not os.path.exists(
        PLAYERS_FILE
    ):
        return {}

    try:

        with open(
            PLAYERS_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

        if isinstance(data, dict):
            return data

    except Exception as e:

        print(
            f"Error loading previous state: {e}"
        )

    return {}


def save_previous_state(
    state
):

    with open(
        PLAYERS_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            state,
            f,
            ensure_ascii=False,
            indent=2
        )


# ============================================================
# FIND CHEAPEST LINEUP
# ============================================================

def find_cheapest_lineup_images(
    soup,
    expected_slots
):

    headings = soup.find_all(
        string=re.compile(
            r"Cheapest grade",
            re.IGNORECASE
        )
    )

    if headings:
        print(
            "Cheapest grade heading found."
        )
    else:
        print(
            "Cheapest grade heading NOT found."
        )

    all_images = soup.find_all(
        "img"
    )

    # --------------------------------------------------------
    # ONLY VALID PLAYER / PLACEHOLDER IMAGES
    # --------------------------------------------------------

    valid_images = []

    for img in all_images:

        if is_valid_lineup_image(img):

            valid_images.append(
                img
            )

    real_count = sum(
        1
        for img in valid_images
        if is_real_player_card(img)
    )

    placeholder_count = sum(
        1
        for img in valid_images
        if is_player_placeholder(
            parse_player_alt(img)
        )
    )

    print(
        f"Valid lineup images found: "
        f"{len(valid_images)} "
        f"(players={real_count}, "
        f"placeholders={placeholder_count})"
    )

    # --------------------------------------------------------
    # SEARCH CONTAINERS
    # --------------------------------------------------------

    candidates = []

    for img in valid_images:

        current = img

        for depth in range(1, 10):

            current = current.parent

            if not current:
                break

            images = current.find_all(
                "img"
            )

            candidate_images = [
                x
                for x in images
                if is_valid_lineup_image(x)
            ]

            if len(candidate_images) != expected_slots:
                continue

            # Candidate must contain at least one real card.
            if not any(
                is_real_player_card(x)
                for x in candidate_images
            ):
                continue

            # For the current page's lineup, all selected
            # images must be unique DOM image nodes.
            if len(set(
                id(x)
                for x in candidate_images
            )) != expected_slots:
                continue

            candidates.append(
                (
                    depth,
                    current,
                    candidate_images
                )
            )

    if candidates:

        # Prefer smallest matching container.
        candidates.sort(
            key=lambda x: x[0]
        )

        depth, container, images = candidates[0]

        print(
            f"Selected lineup candidate: "
            f"{len(images)} lineup slots"
        )

        return images

    # --------------------------------------------------------
    # FALLBACK
    # --------------------------------------------------------

    # Never return arbitrary images.
    # Only valid player/Player Card images.
    fallback = valid_images[
        :expected_slots
    ]

    print(
        f"Fallback lineup candidate: "
        f"{len(fallback)} slots"
    )

    return fallback


# ============================================================
# PARSE SLOT
# ============================================================

def parse_lineup_slot(
    img,
    database
):

    player_name = parse_player_alt(
        img
    )

    # --------------------------------------------------------
    # EMPTY / PLACEHOLDER
    # --------------------------------------------------------

    if is_player_placeholder(
        player_name
    ):

        return {
            "player": "Player Card",
            "overall": None,
            "item_id": None,
            "finish": "UNKNOWN",
            "empty": True,
        }

    # --------------------------------------------------------
    # INVALID IMAGE
    # --------------------------------------------------------

    if not is_real_player_card(
        img
    ):

        return {
            "player": "Player Card",
            "overall": None,
            "item_id": None,
            "finish": "UNKNOWN",
            "empty": True,
        }

    # --------------------------------------------------------
    # REAL PLAYER
    # --------------------------------------------------------

    overall = extract_overall(
        player_name
    )

    item_id = find_item_id_for_image(
        img
    )

    finish = finish_from_database(
        item_id,
        database
    )

    return {
        "player": player_name,
        "overall": overall,
        "item_id": item_id,
        "finish": finish,
        "empty": False,
    }


# ============================================================
# CATEGORY
# ============================================================

def parse_category(
    category_name,
    config,
    database
):

    print()
    print(
        "=" * 60
    )

    print(
        f"Checking "
        f"{config['emoji']} "
        f"{category_name.upper()} "
        f"({config['slots']} players)..."
    )

    print(
        "=" * 60
    )

    html_text = fetch_url(
        config["url"]
    )

    soup = BeautifulSoup(
        html_text,
        "html.parser"
    )

    images = find_cheapest_lineup_images(
        soup,
        config["slots"]
    )

    print(
        f"Lineup slot images found: "
        f"{len(images)}/{config['slots']}"
    )

    print(
        f"Images/cards detected in selected container: "
        f"{len(images)}"
    )

    lineup = []

    for img in images:

        if len(lineup) >= config["slots"]:
            break

        card = parse_lineup_slot(
            img,
            database
        )

        # Safety:
        # NEVER allow Gallery Token, Grading score,
        # FC Coin or other UI elements into the lineup.
        if not card["empty"]:

            if is_bad_ui_text(
                card["player"]
            ):
                continue

            if card["overall"] is None:
                continue

        lineup.append(
            card
        )

    # --------------------------------------------------------
    # FILL MISSING SLOTS
    # --------------------------------------------------------

    while len(lineup) < config["slots"]:

        lineup.append({
            "player": "Player Card",
            "overall": None,
            "item_id": None,
            "finish": "UNKNOWN",
            "empty": True,
        })

    # --------------------------------------------------------
    # LOG
    # --------------------------------------------------------

    print(
        f"Rendered lineup: "
        f"{len(lineup)}/{config['slots']} slots"
    )

    for card in lineup:

        if card["empty"]:

            print(
                "- Player Card — EMPTY SLOT"
            )

        else:

            print(
                f"- {card['player']} "
                f"{card['overall']} "
                f"— ItemID {card['item_id']} "
                f"— {card['finish']}"
            )

    return lineup


# ============================================================
# CARD IDENTITY
# ============================================================

def card_identity(card):

    if not card:
        return None

    if card.get("empty"):
        return None

    item_id = card.get(
        "item_id"
    )

    if item_id:

        return (
            "ITEM",
            str(item_id),
            str(
                card.get(
                    "finish",
                    "UNKNOWN"
                )
            )
        )

    return (
        "PLAYER",
        str(
            card.get(
                "player",
                ""
            )
        ),
        str(
            card.get(
                "overall",
                ""
            )
        ),
        str(
            card.get(
                "finish",
                "UNKNOWN"
            )
        )
    )


# ============================================================
# NORMALIZATION
# ============================================================

def normalize_card(card):

    if not isinstance(
        card,
        dict
    ):
        return None

    if card.get(
        "empty"
    ):
        return None

    return {
        "player": card.get(
            "player",
            ""
        ),
        "overall": card.get(
            "overall"
        ),
        "item_id": (
            str(
                card["item_id"]
            )
            if card.get(
                "item_id"
            ) is not None
            else None
        ),
        "finish": card.get(
            "finish",
            "UNKNOWN"
        ),
        "empty": False,
    }


def unique_cards(cards):

    result = []
    seen = set()

    for card in cards:

        normalized = normalize_card(
            card
        )

        if not normalized:
            continue

        identity = card_identity(
            normalized
        )

        if identity in seen:
            continue

        seen.add(
            identity
        )

        result.append(
            normalized
        )

    return result


# ============================================================
# CHANGES
# ============================================================

def calculate_changes(
    previous_lineup,
    current_lineup
):

    previous_unique = unique_cards(
        previous_lineup or []
    )

    current_unique = unique_cards(
        current_lineup or []
    )

    previous_map = {
        card_identity(card): card
        for card in previous_unique
    }

    current_map = {
        card_identity(card): card
        for card in current_unique
    }

    new_cards = []

    for identity, card in current_map.items():

        if identity not in previous_map:

            new_cards.append(
                card
            )

    out_cards = []

    for identity, card in previous_map.items():

        if identity not in current_map:

            out_cards.append(
                card
            )

    return (
        current_unique,
        new_cards,
        out_cards
    )


# ============================================================
# FORMAT
# ============================================================

def format_card(card):

    player = card.get(
        "player",
        ""
    )

    overall = card.get(
        "overall"
    )

    if overall:

        name = (
            f"{player} {overall}"
        )

    else:

        name = player

    finish = card.get(
        "finish",
        "UNKNOWN"
    )

    return (
        f"<b>{html.escape(name)}</b>"
        f"　·　"
        f"{html.escape(finish)}"
    )


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram_message(
    message
):

    if not TELEGRAM_BOT_TOKEN:

        print(
            "TELEGRAM_BOT_TOKEN missing."
        )

        return

    if not TELEGRAM_CHAT_ID:

        print(
            "TELEGRAM_CHAT_ID missing."
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
        timeout=30
    )

    print(
        f"Telegram status: "
        f"{response.status_code}"
    )

    if response.status_code != 200:

        print(
            response.text
        )


# ============================================================
# TELEGRAM MESSAGE
# ============================================================

def build_category_message(
    category_name,
    config,
    current_lineup,
    new_cards,
    out_cards
):

    lines = []

    lines.append(
        f"<b>{config['emoji']} "
        f"{html.escape(category_name)}</b>"
    )

    lines.append(
        "<b>📋 Current lineup 📋</b>"
    )

    # --------------------------------------------------------
    # CURRENT
    # --------------------------------------------------------

    for card in current_lineup:

        lines.append(
            f"🟢 {format_card(card)}"
        )

    # --------------------------------------------------------
    # OUT
    # --------------------------------------------------------

    for card in out_cards:

        lines.append(
            f"🔴 OUT — {format_card(card)}"
        )

    return "\n".join(
        lines
    )


def build_telegram_message(
    results
):

    sections = []

    for category_name in CATEGORIES:

        result = results[
            category_name
        ]

        section = build_category_message(
            category_name,
            CATEGORIES[category_name],
            result["current"],
            result["new"],
            result["out"],
        )

        sections.append(
            section
        )

    return (
        "<b>📋 FUT.GG Monitor</b>\n"
        + "\n\n--------------------\n\n".join(
            sections
        )
    )


# ============================================================
# CLEAN STATE
# ============================================================

def clean_state(
    state
):

    cleaned = {}

    if not isinstance(
        state,
        dict
    ):
        return cleaned

    for category_name, lineup in state.items():

        if not isinstance(
            lineup,
            list
        ):

            cleaned[
                category_name
            ] = []

            continue

        cleaned_lineup = []

        for card in lineup:

            if not isinstance(
                card,
                dict
            ):
                continue

            if card.get(
                "empty"
            ):

                cleaned_lineup.append({
                    "player": "Player Card",
                    "overall": None,
                    "item_id": None,
                    "finish": "UNKNOWN",
                    "empty": True,
                })

                continue

            normalized = normalize_card(
                card
            )

            if normalized:

                cleaned_lineup.append(
                    normalized
                )

        cleaned[
            category_name
        ] = cleaned_lineup

    return cleaned


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print(
        "FUT.GG MONITOR"
    )

    print(
        datetime.now(
            timezone.utc
        ).strftime(
            "%Y-%m-%dT%H:%M:%S"
        )
    )

    print(
        "=" * 60
    )

    # --------------------------------------------------------
    # DATABASE
    # --------------------------------------------------------

    database = load_card_database()

    added = add_known_finishes(
        database
    )

    print()
    print(
        f"Known card finishes added to database: "
        f"{added}"
    )

    save_card_database(
        database
    )

    # --------------------------------------------------------
    # PREVIOUS STATE
    # --------------------------------------------------------

    previous_state = clean_state(
        load_previous_state()
    )

    # --------------------------------------------------------
    # SCAN
    # --------------------------------------------------------

    current_state = {}

    results = {}

    for category_name, config in CATEGORIES.items():

        try:

            lineup = parse_category(
                category_name,
                config,
                database
            )

        except Exception as e:

            print()
            print(
                f"ERROR scanning "
                f"{category_name}: {e}"
            )

            # Do not declare everything OUT if FUT.GG
            # temporarily fails.
            lineup = previous_state.get(
                category_name,
                []
            )

        current_state[
            category_name
        ] = lineup

        previous_lineup = previous_state.get(
            category_name,
            []
        )

        (
            current_unique,
            new_cards,
            out_cards
        ) = calculate_changes(
            previous_lineup,
            lineup
        )

        results[
            category_name
        ] = {
            "current": current_unique,
            "new": new_cards,
            "out": out_cards,
        }

    # --------------------------------------------------------
    # SAVE CURRENT STATE
    # --------------------------------------------------------

    save_previous_state(
        current_state
    )

    # --------------------------------------------------------
    # TELEGRAM
    # --------------------------------------------------------

    message = build_telegram_message(
        results
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

    send_telegram_message(
        message
    )

    print()
    print(
        "DONE"
    )


if __name__ == "__main__":
    main()