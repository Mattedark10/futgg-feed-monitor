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
        "heading_patterns": [
            "Cheapest grade"
        ],
    },

    "Holographics": {
        "url": f"{BASE_URL}/fut-gallery/rarities/holographics/",
        "emoji": "✨️",
        "slots": 5,
        "heading_patterns": [
            "Cheapest grade S"
        ],
    },

    "Season 1": {
        "url": f"{BASE_URL}/fut-gallery/rarities/season-1/",
        "emoji": "1️⃣",
        "slots": 10,
        "heading_patterns": [
            "Cheapest grade"
        ],
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

    "67335157": "PRISTINE HOLO",   # Angerer
    "67384140": "PRISTINE HOLO",   # Prinz
    "67275770": "PRISTINE HOLO",   # Baresi
    "67180472": "PRISTINE HOLO",   # Foudy
    "67298908": "PRISTINE HOLO",   # Moore

    "67348095": "PRISTINE HOLO",   # Cucurella
    "67368151": "PRISTINE HOLO",   # Harder

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

    # ========================================================
    # BASE
    # ========================================================

    "226306": "BASE",               # Šašić
    "233700": "BASE",               # Vialli
    "5673": "BASE",                 # Litmanen
    "50590935": "BASE",             # Harder
    "50590026": "BASE",             # Godts
    "50570879": "BASE",             # Cucurella

    # ========================================================
    # GISELE THOMPSON
    # ========================================================

    "50606461": "BASE",
    "67383677": "HOLO",

    # ========================================================
    # PARIS BRUNNER
    # ========================================================

    "50605774": "BASE",
    "67382990": "PRISTINE HOLO",
}


# ============================================================
# KNOWN PLAYER FALLBACKS
#
# Used ONLY when FUT.GG doesn't expose the finish/Item ID
# correctly in the lineup.
# ============================================================

KNOWN_PLAYER_FINISHES = {

    # Heroes
    "Mascherano": "BASE",

    # Holographics
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
        name = name.replace(old, new)

    return name.lower()


# ============================================================
# DATABASE
# ============================================================

def load_database():

    if not DATABASE_FILE.exists():
        print(
            "card_database.json not found."
        )

        return {}

    try:

        with DATABASE_FILE.open(
            "r",
            encoding="utf-8"
        ) as file:

            data = json.load(file)

        if not isinstance(data, dict):
            return {}

        return data

    except Exception as error:

        print(
            f"Database error: {error}"
        )

        return {}


def database_finish(item_id):

    if not item_id:
        return None

    item_id = str(item_id)

    # Known hardcoded mapping first
    if item_id in KNOWN_FINISHES:
        return KNOWN_FINISHES[item_id]

    database = load_database()

    card = database.get(
        item_id
    )

    if not card:
        return None

    finish = card.get(
        "finish"
    )

    if finish in [
        "BASE",
        "HOLO",
        "PRISTINE HOLO",
    ]:
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
# ITEM ID EXTRACTION
# ============================================================

def extract_item_ids(text):

    if not text:
        return set()

    text = str(text)

    patterns = [
        r"/27-(\d+)",
        r"\b27-(\d+)\b",
        r'futgg-player-item-card/27-(\d+)',
        r'"itemId"\s*:\s*"?(\\?\d+)',
        r'"item_id"\s*:\s*"?(\\?\d+)',
        r'"itemID"\s*:\s*"?(\\?\d+)',
        r'data-item-id=["\'](\d+)',
    ]

    results = set()

    for pattern in patterns:

        matches = re.findall(
            pattern,
            text,
            re.IGNORECASE
        )

        for match in matches:

            value = str(
                match
            ).replace(
                "\\",
                ""
            )

            if value.isdigit():
                results.add(
                    value
                )

    return results


# ============================================================
# ALT PARSER
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
# FIND ITEM IDS NEAR IMAGE
# ============================================================

def find_item_ids_near_image(img):

    item_ids = set()

    attributes = [
        "src",
        "data-src",
        "data-lazy-src",
        "data-original",
        "srcset",
        "data-srcset",
    ]

    for attribute in attributes:

        value = img.get(
            attribute
        )

        if value:

            item_ids.update(
                extract_item_ids(
                    value
                )
            )

    current = img

    for _ in range(8):

        if current is None:
            break

        try:
            html = str(
                current
            )
        except Exception:
            html = ""

        item_ids.update(
            extract_item_ids(
                html
            )
        )

        current = current.parent

    return item_ids


# ============================================================
# FIND CHEAPEST LINEUP
# ============================================================

def find_best_lineup_container(
    soup,
    category
):

    config = CATEGORIES[
        category
    ]

    target_slots = config[
        "slots"
    ]

    headings = soup.find_all(
        ["h1", "h2", "h3", "h4", "div", "span"]
    )

    candidates = []

    for heading in headings:

        text = clean_text(
            heading.get_text(
                " ",
                strip=True
            )
        )

        if not text:
            continue

        if "Cheapest grade" not in text:
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

    # Closest candidate with enough cards
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
    category
):

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    config = CATEGORIES[
        category
    ]

    target_slots = config[
        "slots"
    ]

    candidate = find_best_lineup_container(
        soup,
        category
    )

    if not candidate:

        print(
            "Could not find lineup container."
        )

        return []

    _, container, _ = candidate

    images = container.find_all(
        "img"
    )

    print(
        f"Lineup slot images found: "
        f"{len(images)}/{target_slots}"
    )

    lineup = []

    used_image_indexes = set()

    for index, img in enumerate(
        images
    ):

        if len(lineup) >= target_slots:
            break

        parsed = parse_card_alt(
            img.get(
                "alt",
                ""
            )
        )

        if not parsed:
            continue

        if parsed.get(
            "empty"
        ):

            lineup.append({
                "empty": True,
                "player": "Player Card",
                "overall": None,
                "item_id": None,
                "finish": None,
            })

            used_image_indexes.add(
                index
            )

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

        item_ids = (
            find_item_ids_near_image(
                img
            )
        )

        item_id = None

        if item_ids:

            # Prefer the first numeric ID
            item_id = sorted(
                item_ids,
                key=lambda x: int(x)
            )[0]

        finish = None

        # ----------------------------------------------------
        # 1. Known Item ID
        # ----------------------------------------------------

        if item_id:

            finish = database_finish(
                item_id
            )

        # ----------------------------------------------------
        # 2. Version text
        # ----------------------------------------------------

        if not finish:

            finish = detect_finish_from_text(
                version
            )

        # ----------------------------------------------------
        # 3. Player fallback
        # ----------------------------------------------------

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

        used_image_indexes.add(
            index
        )

    # --------------------------------------------------------
    # Safety: make sure exactly N slots
    # --------------------------------------------------------

    while len(lineup) < target_slots:

        lineup.append({
            "empty": True,
            "player": "Player Card",
            "overall": None,
            "item_id": None,
            "finish": None,
        })

    if len(lineup) > target_slots:

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

    # Item ID is strongest identity
    if item_id:

        return (
            "ID",
            str(item_id)
        )

    # Fallback identity
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

        if not isinstance(
            data,
            dict
        ):
            return {}

        return data

    except Exception:

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

    previous = load_previous_state()

    current_state = {}

    message_parts = [
        "<b>📋 FUT.GG Monitor</b>"
    ]

    # ========================================================
    # DATABASE INFO
    # ========================================================

    database = load_database()

    print()
    print(
        f"Database items: "
        f"{len(database)}"
    )

    # ========================================================
    # CATEGORIES
    # ========================================================

    for category, config in CATEGORIES.items():

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
            category
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
        # MESSAGE
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

            status = (
                "IN"
                if key in previous_keys
                or not previous_lineup
                else "IN"
            )

            formatted = format_card(
                card,
                status
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
        #
        # Keep old cards that disappeared.
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
                f"— "
                f"{old_card.get('finish') or 'UNKNOWN'}"
            )

        # ----------------------------------------------------
        # SEPARATOR
        # ----------------------------------------------------

        if category != list(
            CATEGORIES.keys()
        )[-1]:

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
    print(message)

    send_telegram(
        message
    )

    print()
    print("DONE")


if __name__ == "__main__":
    main()