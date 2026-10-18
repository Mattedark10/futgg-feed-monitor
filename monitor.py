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

    # PRISTINE HOLO
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

    # HOLO
    "67179830": "HOLO",
    "67188263": "HOLO",
    "67368429": "HOLO",
    "67353040": "HOLO",
    "67372629": "HOLO",
    "67386815": "HOLO",
    "67374557": "HOLO",

    # BASE
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

    print(
        f"HTTP status: {response.status_code}"
    )

    print(
        f"Downloaded: {len(response.text)} characters"
    )

    response.raise_for_status()

    return response.text


# ============================================================
# ALT PARSING
# ============================================================

def parse_player_alt(img):

    if not img:
        return None

    for attr in (
        "alt",
        "data-alt",
        "title",
        "aria-label",
    ):

        value = img.get(attr)

        if not value:
            continue

        value = html.unescape(
            str(value)
        ).strip()

        if value:
            return value

    return None


def parse_card_name_and_rating(
    raw_name
):

    if not raw_name:
        return None, None

    raw_name = html.unescape(
        raw_name
    ).strip()

    # FUT.GG format:
    #
    # Šašić - 89 - Base Hero
    # Cucurella - 88 - Destined for Glory
    # Mora - 87 - Future Stars
    #
    # We only need the first two parts.

    parts = [
        part.strip()
        for part in raw_name.split("-")
    ]

    if len(parts) >= 2:

        possible_rating = parts[1]

        match = re.search(
            r"\b(\d{2})\b",
            possible_rating
        )

        if match:

            rating = int(
                match.group(1)
            )

            if 70 <= rating <= 99:

                player_name = parts[0].strip()

                if player_name:
                    return (
                        player_name,
                        rating
                    )

    # Fallback for unexpected formatting.

    match = re.search(
        r"^(.*?)\s*[-|]\s*(\d{2})\b",
        raw_name
    )

    if match:

        player_name = (
            match.group(1).strip()
        )

        rating = int(
            match.group(2)
        )

        if 70 <= rating <= 99:

            return (
                player_name,
                rating
            )

    return None, None


# ============================================================
# PLACEHOLDERS / UI
# ============================================================

def is_player_placeholder(
    name
):

    if not name:
        return False

    normalized = re.sub(
        r"\s+",
        " ",
        name.lower().strip()
    )

    return normalized in {
        "player card",
        "player-card",
        "empty slot",
        "empty",
    }


def is_bad_ui_text(
    name
):

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
        "token",
        "coin",
    ]

    for word in bad_words:

        if word in normalized:
            return True

    return False


def is_real_player_card(
    img
):

    raw_name = parse_player_alt(
        img
    )

    if not raw_name:
        return False

    if is_player_placeholder(
        raw_name
    ):
        return False

    if is_bad_ui_text(
        raw_name
    ):
        return False

    player_name, rating = (
        parse_card_name_and_rating(
            raw_name
        )
    )

    if not player_name:
        return False

    if rating is None:
        return False

    return True


def is_valid_lineup_image(
    img
):

    raw_name = parse_player_alt(
        img
    )

    if not raw_name:
        return False

    if is_player_placeholder(
        raw_name
    ):
        return True

    return is_real_player_card(
        img
    )


# ============================================================
# ITEM ID
# ============================================================

def extract_item_ids(
    text
):

    if not text:
        return []

    text = html.unescape(
        str(text)
    )

    patterns = [

        # FUT.GG image URL:
        # .../2027/futgg-player-item-card/27-67335170....
        r"/27-(\d{4,})(?:[./?_-]|$)",

        # Generic 27-ITEMID
        r"\b27-(\d{4,})\b",

        # itemId
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


def extract_item_id_from_attributes(
    element
):

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

        value = element.get(
            attr
        )

        if not value:
            continue

        ids = extract_item_ids(
            value
        )

        if ids:
            return ids[0]

    return None


def find_item_id_for_image(
    img
):

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
    # 4. SMALL LOCAL WRAPPER
    # --------------------------------------------------------

    current = img

    for _ in range(5):

        current = current.parent

        if not current:
            break

        local_images = current.find_all(
            "img"
        )

        valid_player_images = [
            x
            for x in local_images
            if is_real_player_card(x)
        ]

        # Never use a large wrapper containing
        # several cards.
        if len(valid_player_images) != 1:
            continue

        if valid_player_images[0] is not img:
            continue

        ids = extract_item_ids(
            str(current)
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

        if isinstance(
            data,
            dict
        ):
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
        return KNOWN_FINISHES[
            item_id
        ]

    record = database.get(
        item_id
    )

    if isinstance(
        record,
        dict
    ):

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

        if not isinstance(
            record,
            dict
        ):
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

        if isinstance(
            data,
            dict
        ):
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
# FIND LINEUP
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

    valid_images = [
        img
        for img in all_images
        if is_valid_lineup_image(img)
    ]

    real_players = [
        img
        for img in valid_images
        if is_real_player_card(img)
    ]

    placeholders = [
        img
        for img in valid_images
        if is_player_placeholder(
            parse_player_alt(img)
        )
    ]

    print(
        f"Valid lineup images found: "
        f"{len(valid_images)} "
        f"(players={len(real_players)}, "
        f"placeholders={len(placeholders)})"
    )

    # --------------------------------------------------------
    # IMPORTANT:
    #
    # Find the container around the "Cheapest grade" heading
    # first. This avoids accidentally selecting "Add players"
    # or other UI sections.
    # --------------------------------------------------------

    lineup_heading = None

    for heading in headings:

        if heading.parent:

            lineup_heading = heading.parent

            break

    candidates = []

    # --------------------------------------------------------
    # SEARCH FROM HEADING
    # --------------------------------------------------------

    if lineup_heading:

        current = lineup_heading

        for depth in range(1, 12):

            current = current.parent

            if not current:
                break

            images = current.find_all(
                "img"
            )

            candidate = [
                img
                for img in images
                if is_valid_lineup_image(img)
            ]

            if len(candidate) != expected_slots:
                continue

            # Must contain at least one actual card.
            if not any(
                is_real_player_card(img)
                for img in candidate
            ):
                continue

            candidates.append(
                (
                    depth,
                    current,
                    candidate
                )
            )

    # --------------------------------------------------------
    # FALLBACK SEARCH
    # --------------------------------------------------------

    if not candidates:

        for img in valid_images:

            current = img

            for depth in range(1, 9):

                current = current.parent

                if not current:
                    break

                candidate = [
                    x
                    for x in current.find_all("img")
                    if is_valid_lineup_image(x)
                ]

                if len(candidate) != expected_slots:
                    continue

                if not any(
                    is_real_player_card(x)
                    for x in candidate
                ):
                    continue

                candidates.append(
                    (
                        depth,
                        current,
                        candidate
                    )
                )

    if candidates:

        candidates.sort(
            key=lambda x: x[0]
        )

        depth, container, images = (
            candidates[0]
        )

        print(
            f"Selected lineup candidate: "
            f"{len(images)} lineup slots"
        )

        return images

    # --------------------------------------------------------
    # LAST FALLBACK
    # --------------------------------------------------------

    # Build lineup from real player cards first,
    # preserving placeholders only if necessary.
    result = []

    for img in valid_images:

        if is_real_player_card(img):

            result.append(img)

            if len(result) >= expected_slots:
                break

    if len(result) < expected_slots:

        for img in valid_images:

            if is_player_placeholder(
                parse_player_alt(img)
            ):

                result.append(img)

                if len(result) >= expected_slots:
                    break

    print(
        f"Fallback lineup candidate: "
        f"{len(result)} slots"
    )

    return result


# ============================================================
# PARSE SLOT
# ============================================================

def parse_lineup_slot(
    img,
    database
):

    raw_name = parse_player_alt(
        img
    )

    # Empty slot
    if is_player_placeholder(
        raw_name
    ):

        return {
            "player": "Player Card",
            "overall": None,
            "item_id": None,
            "finish": "UNKNOWN",
            "empty": True,
        }

    # Invalid UI
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

    player_name, overall = (
        parse_card_name_and_rating(
            raw_name
        )
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

        lineup.append(
            card
        )

    # Fill missing positions.
    while len(lineup) < config["slots"]:

        lineup.append({
            "player": "Player Card",
            "overall": None,
            "item_id": None,
            "finish": "UNKNOWN",
            "empty": True,
        })

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
# IDENTITY
# ============================================================

def card_identity(
    card
):

    if not card:
        return None

    if card.get(
        "empty"
    ):
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
# NORMALIZE
# ============================================================

def normalize_card(
    card
):

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


def unique_cards(
    cards
):

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

def format_card(
    card
):

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

    # Current lineup
    for card in current_lineup:

        lines.append(
            f"🟢 {format_card(card)}"
        )

    # OUT
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

        sections.append(
            build_category_message(
                category_name,
                CATEGORIES[category_name],
                result["current"],
                result["new"],
                result["out"],
            )
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

            # Do NOT wipe the previous state if
            # FUT.GG temporarily fails.
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
    # SAVE STATE
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