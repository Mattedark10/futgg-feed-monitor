import json
import os
import re
from pathlib import Path
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup


# ============================================================
# CONFIG
# ============================================================

BASE_URL = "https://www.fut.gg"

CATEGORIES = {
    "Heroes": {
        "url": f"{BASE_URL}/fut-gallery/rarities/heroes/",
        "emoji": "🦸‍♂️",
        "slots": 5,
    },

    "Holographics": {
        "url": f"{BASE_URL}/fut-gallery/rarities/holographics/",
        "emoji": "✨️",
        "slots": 5,
    },

    "Season 1": {
        "url": f"{BASE_URL}/fut-gallery/rarities/season-1/",
        "emoji": "1️⃣",
        "slots": 10,
    },
}


PLAYERS_FILE = Path("players.json")
DATABASE_FILE = Path("card_database.json")


TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    ""
)

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID",
    ""
)


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/xml;q=0.9,image/avif,image/webp,"
        "*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


session = requests.Session()
session.headers.update(HEADERS)


# ============================================================
# KNOWN ITEM IDS
# ============================================================

KNOWN_FINISHES = {

    # ========================================================
    # PRISTINE HOLO
    # ========================================================

    "67335170": "PRISTINE HOLO",   # Šašić
    "67114537": "PRISTINE HOLO",   # Litmanen
    "67335237": "PRISTINE HOLO",
    "67371135": "PRISTINE HOLO",   # Milito
    "67342564": "PRISTINE HOLO",   # Vialli
    "67186651": "PRISTINE HOLO",
    "67335573": "PRISTINE HOLO",
    "67135573": "PRISTINE HOLO",   # Márquez

    # Holographics
    "67335157": "PRISTINE HOLO",   # Angerer
    "67384140": "PRISTINE HOLO",   # Prinz
    "67275770": "PRISTINE HOLO",   # Baresi
    "67180472": "PRISTINE HOLO",   # Foudy
    "67298908": "PRISTINE HOLO",   # Moore

    # Season 1
    "67348095": "PRISTINE HOLO",   # Cucurella
    "67368151": "PRISTINE HOLO",   # Harder

    # Paris Brunner
    "67382990": "PRISTINE HOLO",

    # ========================================================
    # HOLO
    # ========================================================

    "67179830": "HOLO",             # Jacobo Ramón
    "67188263": "HOLO",             # Mora
    "67368429": "HOLO",             # Bonny
    "67353040": "HOLO",             # Undav
    "67372629": "HOLO",             # Bischof
    "67386815": "HOLO",             # Yohannes
    "67374557": "HOLO",

    # Gisele Thompson
    "67383677": "HOLO",

    # ========================================================
    # BASE
    # ========================================================

    "226306": "BASE",               # Šašić
    "233700": "BASE",               # Vialli
    "5673": "BASE",                 # Litmanen
    "50590935": "BASE",             # Harder
    "50590026": "BASE",             # Godts
    "50570879": "BASE",             # Cucurella

    # Gisele Thompson
    "50606461": "BASE",

    # Paris Brunner
    "50605774": "BASE",
}


# ============================================================
# PLAYER FALLBACKS
# ============================================================

KNOWN_PLAYER_FINISHES = {

    "Mascherano": "BASE",

    "van Basten": "PRISTINE HOLO",
    "van Nistelrooy": "PRISTINE HOLO",
}


# ============================================================
# TEXT UTILS
# ============================================================

def clean_text(value):

    if value is None:
        return ""

    return re.sub(
        r"\s+",
        " ",
        str(value)
    ).strip()


def normalize_name(name):

    name = clean_text(name)

    replacements = {
        "Š": "S",
        "š": "s",
        "á": "a",
        "à": "a",
        "ä": "a",
        "é": "e",
        "è": "e",
        "ë": "e",
        "í": "i",
        "ì": "i",
        "ï": "i",
        "ó": "o",
        "ò": "o",
        "ö": "o",
        "ú": "u",
        "ù": "u",
        "ü": "u",
        "ñ": "n",
    }

    for old, new in replacements.items():
        name = name.replace(
            old,
            new
        )

    return name.lower()


# ============================================================
# DATABASE
# ============================================================

def load_database():

    if not DATABASE_FILE.exists():
        return {}

    try:

        with DATABASE_FILE.open(
            "r",
            encoding="utf-8"
        ) as file:

            data = json.load(file)

        if isinstance(data, dict):
            return data

    except Exception as error:

        print(
            f"Database error: {error}"
        )

    return {}


# ============================================================
# DATABASE FINISH
# ============================================================

def database_finish(
    item_id,
    database
):

    if not item_id:
        return None

    item_id = str(
        item_id
    )

    # Hardcoded verified IDs first
    if item_id in KNOWN_FINISHES:
        return KNOWN_FINISHES[
            item_id
        ]

    card = database.get(
        item_id
    )

    if not isinstance(
        card,
        dict
    ):
        return None

    finish = card.get(
        "finish"
    )

    if finish in (
        "BASE",
        "HOLO",
        "PRISTINE HOLO",
    ):
        return finish

    return None


# ============================================================
# FINISH DETECTION
# ============================================================

def detect_finish_from_text(text):

    text = clean_text(
        text
    ).lower()

    if not text:
        return None

    if (
        "pristine holographic" in text
        or "pristine holo" in text
    ):
        return "PRISTINE HOLO"

    if (
        "standard holographic" in text
        or "holographic" in text
    ):
        return "HOLO"

    if (
        text.endswith(" holo")
        or text == "holo"
    ):
        return "HOLO"

    if (
        "base hero" in text
        or "base icon" in text
    ):
        return "BASE"

    return None


# ============================================================
# PLAYER FALLBACK
# ============================================================

def player_fallback_finish(player):

    normalized = normalize_name(
        player
    )

    for known_name, finish in (
        KNOWN_PLAYER_FINISHES.items()
    ):

        if normalize_name(
            known_name
        ) == normalized:

            return finish

    return None


# ============================================================
# EXTRACT ITEM IDS FROM ONE VALUE
# ============================================================

def extract_item_ids(value):

    if not value:
        return []

    value = str(
        value
    )

    patterns = [

        # FUT.GG card URL
        r"/27-(\d+)",

        # Generic 27-ID
        r"\b27-(\d+)\b",

        # JSON
        r'"itemId"\s*:\s*"?(\\?\d+)',
        r'"item_id"\s*:\s*"?(\\?\d+)',
        r'"itemID"\s*:\s*"?(\\?\d+)',

        # HTML data attributes
        r'data-item-id=["\'](\d+)',

    ]

    results = []

    for pattern in patterns:

        matches = re.findall(
            pattern,
            value,
            re.IGNORECASE
        )

        for match in matches:

            item_id = str(
                match
            ).replace(
                "\\",
                ""
            )

            if item_id.isdigit():

                if item_id not in results:
                    results.append(
                        item_id
                    )

    return results


# ============================================================
# PARSE ALT
# ============================================================

def parse_card_alt(alt):

    alt = clean_text(
        alt
    )

    if not alt:
        return None

    if alt.lower() == "player card":

        return {
            "empty": True
        }

    # Example:
    # Šašić - 89 - Base Hero
    # Mora - 87 - Future Stars

    match = re.match(
        r"(.+?)\s*-\s*(\d{2,3})\s*-\s*(.+)",
        alt
    )

    if not match:
        return None

    player = clean_text(
        match.group(1)
    )

    try:

        overall = int(
            match.group(2)
        )

    except Exception:

        return None

    version = clean_text(
        match.group(3)
    )

    return {
        "empty": False,
        "player": player,
        "overall": overall,
        "version": version,
    }


# ============================================================
# FIND ITEM ID FOR THIS EXACT IMAGE
# ============================================================

def find_item_id_for_image(img):

    # IMPORTANT:
    # We ONLY inspect this image and its direct link.
    #
    # We DO NOT scan 8 parent containers anymore.
    #
    # That was the reason the same ItemID was being assigned
    # to every player in the lineup.

    attributes = [
        "src",
        "data-src",
        "data-lazy-src",
        "data-original",
        "srcset",
        "data-srcset",
    ]

    # --------------------------------------------------------
    # 1. Image attributes
    # --------------------------------------------------------

    for attribute in attributes:

        value = img.get(
            attribute
        )

        ids = extract_item_ids(
            value
        )

        if ids:
            return ids[0]

    # --------------------------------------------------------
    # 2. Direct parent <a>
    # --------------------------------------------------------

    parent_link = img.find_parent(
        "a"
    )

    if parent_link:

        href = parent_link.get(
            "href",
            ""
        )

        ids = extract_item_ids(
            href
        )

        if ids:
            return ids[0]

    # --------------------------------------------------------
    # 3. Very close wrapper only
    #
    # We inspect one immediate parent, but never the whole
    # lineup container.
    # --------------------------------------------------------

    parent = img.parent

    if parent:

        for attribute in (
            "data-item-id",
            "data-itemid",
            "data-id",
        ):

            value = parent.get(
                attribute
            )

            if value:

                ids = extract_item_ids(
                    value
                )

                if ids:
                    return ids[0]

                value = str(
                    value
                )

                if value.isdigit():
                    return value

    return None


# ============================================================
# FIND CHEAPEST LINEUP CONTAINER
# ============================================================

def find_best_lineup_container(
    soup,
    category
):

    target_slots = CATEGORIES[
        category
    ]["slots"]

    candidates = []

    # Find headings specifically
    # containing "Cheapest grade".
    headings = soup.find_all(
        string=re.compile(
            r"Cheapest grade",
            re.IGNORECASE
        )
    )

    for heading_text in headings:

        heading = heading_text.parent

        if heading is None:
            continue

        parent = heading

        for _ in range(8):

            if parent is None:
                break

            images = parent.find_all(
                "img"
            )

            cards = []

            for img in images:

                parsed = parse_card_alt(
                    img.get(
                        "alt",
                        ""
                    )
                )

                if parsed:

                    cards.append(
                        (
                            img,
                            parsed
                        )
                    )

            if len(cards) >= target_slots:

                candidates.append(
                    (
                        len(cards),
                        parent,
                        cards
                    )
                )

            parent = parent.parent

    if not candidates:
        return None

    # Prefer candidate closest to target slot count
    candidates.sort(
        key=lambda x: (
            abs(
                x[0] - target_slots
            ),
            x[0]
        )
    )

    return candidates[0]


# ============================================================
# PARSE LINEUP
# ============================================================

def parse_lineup(
    html,
    category,
    database
):

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    target_slots = CATEGORIES[
        category
    ]["slots"]

    candidate = find_best_lineup_container(
        soup,
        category
    )

    if not candidate:

        print(
            "Could not find lineup container."
        )

        return []

    _, container, cards = candidate

    print(
        f"Lineup slot images found: "
        f"{len(cards)}/{target_slots}"
    )

    lineup = []

    # --------------------------------------------------------
    # IMPORTANT:
    # We use the actual card images in DOM order.
    # --------------------------------------------------------

    for img, parsed in cards:

        if len(lineup) >= target_slots:
            break

        # ----------------------------------------------------
        # EMPTY SLOT
        # ----------------------------------------------------

        if parsed.get(
            "empty"
        ):

            lineup.append({
                "empty": True,
                "player": "Player Card",
                "overall": None,
                "item_id": None,
                "finish": None,
                "version": None,
            })

            continue

        player = parsed[
            "player"
        ]

        overall = parsed[
            "overall"
        ]

        version = parsed[
            "version"
        ]

        # ----------------------------------------------------
        # EXACT ITEM ID
        # ----------------------------------------------------

        item_id = find_item_id_for_image(
            img
        )

        # ----------------------------------------------------
        # FINISH
        # ----------------------------------------------------

        finish = None

        # 1. Verified Item ID
        if item_id:

            finish = database_finish(
                item_id,
                database
            )

        # 2. Version text
        if not finish:

            finish = detect_finish_from_text(
                version
            )

        # 3. Player fallback
        if not finish:

            finish = player_fallback_finish(
                player
            )

        lineup.append({
            "empty": False,
            "player": player,
            "overall": overall,
            "item_id": item_id,
            "finish": finish,
            "version": version,
        })

    # --------------------------------------------------------
    # EXACTLY N SLOTS
    # --------------------------------------------------------

    while len(lineup) < target_slots:

        lineup.append({
            "empty": True,
            "player": "Player Card",
            "overall": None,
            "item_id": None,
            "finish": None,
            "version": None,
        })

    lineup = lineup[
        :target_slots
    ]

    print(
        f"Rendered lineup: "
        f"{len(lineup)}/{target_slots} slots"
    )

    return lineup


# ============================================================
# FETCH PAGE
# ============================================================

def fetch_page(url):

    print(
        f"Fetching: {url}"
    )

    response = session.get(
        url,
        timeout=45
    )

    print(
        f"HTTP status: "
        f"{response.status_code}"
    )

    print(
        f"Downloaded: "
        f"{len(response.text)} characters"
    )

    response.raise_for_status()

    return response.text


# ============================================================
# CARD KEY
# ============================================================

def card_key(card):

    if card.get(
        "empty"
    ):
        return None

    player = clean_text(
        card.get(
            "player",
            ""
        )
    )

    overall = card.get(
        "overall"
    )

    finish = card.get(
        "finish"
    )

    item_id = card.get(
        "item_id"
    )

    # Item ID = strongest identity
    if item_id:

        return (
            "ID",
            str(item_id)
        )

    # Fallback
    return (
        "CARD",
        normalize_name(
            player
        ),
        overall,
        finish,
    )


# ============================================================
# LOAD PREVIOUS STATE
# ============================================================

def load_previous_state():

    if not PLAYERS_FILE.exists():
        return {}

    try:

        with PLAYERS_FILE.open(
            "r",
            encoding="utf-8"
        ) as file:

            data = json.load(
                file
            )

        if isinstance(
            data,
            dict
        ):
            return data

    except Exception as error:

        print(
            f"Previous state error: "
            f"{error}"
        )

    return {}


# ============================================================
# SAVE STATE
# ============================================================

def save_state(state):

    with PLAYERS_FILE.open(
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            state,
            file,
            ensure_ascii=False,
            indent=2
        )


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):

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

    response.raise_for_status()


# ============================================================
# FORMAT CARD
# ============================================================

def format_card(
    card,
    status
):

    if card.get(
        "empty"
    ):
        return None

    player = clean_text(
        card.get(
            "player",
            ""
        )
    )

    overall = card.get(
        "overall"
    )

    finish = card.get(
        "finish"
    )

    if not finish:
        finish = "UNKNOWN"

    if overall is not None:

        player_text = (
            f"{player} {overall}"
        )

    else:

        player_text = player

    if status == "OUT":

        return (
            f"🔴 OUT — "
            f"<b>{player_text}</b>"
            f"　·　{finish}"
        )

    return (
        f"🟢 <b>{player_text}</b>"
        f"　·　{finish}"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    now = datetime.now(
        timezone.utc
    )

    print()
    print("=" * 60)
    print("FUT.GG MONITOR")
    print(
        now.strftime(
            "%Y-%m-%dT%H:%M:%S"
        )
    )
    print("=" * 60)

    # --------------------------------------------------------
    # LOAD ONCE
    # --------------------------------------------------------

    previous = load_previous_state()

    database = load_database()

    print()
    print(
        f"Database items: "
        f"{len(database)}"
    )

    current_state = {}

    message_parts = [
        "<b>📋 FUT.GG Monitor</b>"
    ]

    categories = list(
        CATEGORIES.items()
    )

    # ========================================================
    # CATEGORIES
    # ========================================================

    for category_index, (
        category,
        config
    ) in enumerate(categories):

        print()
        print("=" * 60)

        print(
            f"Checking "
            f"{config['emoji']} "
            f"{category.upper()} "
            f"({config['slots']} players)..."
        )

        print("=" * 60)

        try:

            html = fetch_page(
                config["url"]
            )

        except Exception as error:

            print(
                f"ERROR: {error}"
            )

            continue

        lineup = parse_lineup(
            html,
            category,
            database
        )

        current_state[
            category
        ] = lineup

        previous_lineup = previous.get(
            category,
            []
        )

        # ----------------------------------------------------
        # PREVIOUS KEYS
        # ----------------------------------------------------

        previous_keys = set()

        for card in previous_lineup:

            key = card_key(
                card
            )

            if key:
                previous_keys.add(
                    key
                )

        # ----------------------------------------------------
        # TELEGRAM CATEGORY
        # ----------------------------------------------------

        message_parts.append(
            ""
        )

        message_parts.append(
            f"<b>{config['emoji']} "
            f"{category}</b>"
        )

        message_parts.append(
            "<b>📋 Current lineup 📋</b>"
        )

        # ----------------------------------------------------
        # CURRENT CARDS
        # ----------------------------------------------------

        current_keys = set()

        for card in lineup:

            if card.get(
                "empty"
            ):
                continue

            key = card_key(
                card
            )

            if key:

                current_keys.add(
                    key
                )

            formatted = format_card(
                card,
                "IN"
            )

            if formatted:

                message_parts.append(
                    formatted
                )

            print(
                f"- "
                f"{card.get('player')} "
                f"{card.get('overall')} "
                f"— ItemID "
                f"{card.get('item_id')} "
                f"— "
                f"{card.get('finish') or 'UNKNOWN'}"
            )

        # ----------------------------------------------------
        # OUT CARDS
        # ----------------------------------------------------

        for old_card in previous_lineup:

            if old_card.get(
                "empty"
            ):
                continue

            old_key = card_key(
                old_card
            )

            if not old_key:
                continue

            if old_key in current_keys:
                continue

            formatted = format_card(
                old_card,
                "OUT"
            )

            if formatted:

                message_parts.append(
                    formatted
                )

            print(
                f"OUT — "
                f"{old_card.get('player')} "
                f"{old_card.get('overall')} "
                f"— ItemID "
                f"{old_card.get('item_id')} "
                f"— "
                f"{old_card.get('finish') or 'UNKNOWN'}"
            )

        # ----------------------------------------------------
        # SEPARATOR
        # ----------------------------------------------------

        if category_index < len(
            categories
        ) - 1:

            message_parts.append(
                ""
            )

            message_parts.append(
                "--------------------"
            )

    # ========================================================
    # SAVE STATE
    # ========================================================

    save_state(
        current_state
    )

    # ========================================================
    # TELEGRAM
    # ========================================================

    message = "\n".join(
        message_parts
    )

    print()
    print("=" * 60)
    print("TELEGRAM MESSAGE")
    print("=" * 60)

    print(
        message
    )

    send_telegram(
        message
    )

    print()
    print("DONE")


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()