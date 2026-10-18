import os
import re
import json
import time
from pathlib import Path
from collections import Counter

import requests
from bs4 import BeautifulSoup


# ============================================================
# CONFIGURATION
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

PLAYERS_FILE = Path("players.json")
CARD_CACHE_FILE = Path("card_cache.json")
CARD_DATABASE_FILE = Path("card_database.json")

BASE_URL = "https://www.fut.gg"

CATEGORIES = {
    "Heroes": {
        "emoji": "🦸‍♂️",
        "url": f"{BASE_URL}/fut-gallery/rarities/heroes/",
        "slots": 5,
    },
    "Holographics": {
        "emoji": "✨️",
        "url": f"{BASE_URL}/fut-gallery/rarities/holographics/",
        "slots": 5,
    },
    "Season 1": {
        "emoji": "1️⃣",
        "url": f"{BASE_URL}/fut-gallery/rarities/season-1/",
        "slots": 10,
    },
}


HOLOGRAPHIC_DATABASE_URLS = {
    "PRISTINE HOLO":
        f"{BASE_URL}/holographic-cards/?finish=pristine",

    "HOLO":
        f"{BASE_URL}/holographic-cards/?finish=holographic",
}


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/140.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/xml;q=0.9,image/avif,image/webp,"
        "*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
}


session = requests.Session()
session.headers.update(HEADERS)


# ============================================================
# KNOWN CARD FINISHES
# ============================================================

KNOWN_FINISHES = {

    # ========================================================
    # PRISTINE HOLO
    # ========================================================

    "67335170": "PRISTINE HOLO",   # Šašić
    "67114537": "PRISTINE HOLO",   # Litmanen
    "67135573": "PRISTINE HOLO",   # Márquez
    "67371135": "PRISTINE HOLO",   # Milito
    "67342564": "PRISTINE HOLO",   # Vialli

    "67335157": "PRISTINE HOLO",   # Angerer
    "67384140": "PRISTINE HOLO",   # Prinz
    "67275770": "PRISTINE HOLO",   # Baresi
    "67180472": "PRISTINE HOLO",   # Foudy
    "67298908": "PRISTINE HOLO",   # Moore

    "67348095": "PRISTINE HOLO",   # Cucurella

    # ========================================================
    # HOLO
    # ========================================================

    "67179830": "HOLO",            # Jacobo Ramón
    "67188263": "HOLO",            # Mora
    "67368429": "HOLO",            # Bonny
    "67353040": "HOLO",            # Undav
    "67372629": "HOLO",            # Bischof
    "67386815": "HOLO",            # Yohannes
    "67374557": "HOLO",

    # ========================================================
    # BASE
    # ========================================================

    "226306": "BASE",              # Šašić
    "233700": "BASE",              # Vialli
    "5673": "BASE",                # Litmanen
    "50590935": "BASE",            # Harder

    "50590026": "BASE",            # Godts
    "50570879": "BASE",            # Cucurella
}


# ============================================================
# REGEX
# ============================================================

ITEM_ID_PATTERNS = [
    re.compile(
        r"futgg-player-item-card/27-(\d+)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:^|[/_-])27-(\d+)",
        re.IGNORECASE,
    ),
    re.compile(
        r'"itemId"\s*:\s*"?(\d+)',
        re.IGNORECASE,
    ),
    re.compile(
        r'"item_id"\s*:\s*"?(\d+)',
        re.IGNORECASE,
    ),
    re.compile(
        r'data-item-id=["\'](\d+)',
        re.IGNORECASE,
    ),
]


ALT_PATTERN = re.compile(
    r"^\s*(.*?)\s*-\s*(\d{2})\s*-\s*(.*?)\s*$"
)


# ============================================================
# BASIC HELPERS
# ============================================================

def clean_text(value):
    if value is None:
        return ""

    return re.sub(
        r"\s+",
        " ",
        str(value),
    ).strip()


def extract_item_ids(text):
    if not text:
        return set()

    results = set()

    text = str(text)

    for pattern in ITEM_ID_PATTERNS:

        matches = pattern.findall(
            text
        )

        for value in matches:
            results.add(
                str(value)
            )

    return results


def parse_player_alt(alt):
    alt = clean_text(alt)

    if not alt:
        return None

    if alt.lower() == "player card":
        return None

    match = ALT_PATTERN.match(
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

    if not player:
        return None

    return {
        "player": player,
        "overall": overall,
        "version": version,
    }


def detect_finish_from_version(version):
    text = clean_text(
        version
    ).lower()

    if (
        "pristine" in text
        or "pristine holo" in text
        or "pristine holographic" in text
    ):
        return "PRISTINE HOLO"

    if (
        "holographic" in text
        or "holo" in text
    ):
        return "HOLO"

    return "BASE"


# ============================================================
# REQUEST
# ============================================================

def fetch_url(url):
    print(
        f"Fetching: {url}"
    )

    response = session.get(
        url,
        timeout=45,
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
# PLAYER CARD DETECTION
# ============================================================

def is_player_placeholder(img):
    alt = clean_text(
        img.get(
            "alt",
            ""
        )
    )

    return (
        alt.lower()
        == "player card"
    )


def is_real_player_card(img):
    alt = clean_text(
        img.get(
            "alt",
            ""
        )
    )

    if parse_player_alt(alt):
        return True

    attributes = [
        img.get("src"),
        img.get("data-src"),
        img.get("data-lazy-src"),
        img.get("data-original"),
        img.get("srcset"),
        img.get("data-srcset"),
    ]

    combined = " ".join(
        str(x)
        for x in attributes
        if x
    ).lower()

    return (
        "futgg-player-item-card"
        in combined
    )


# ============================================================
# IMPORTANT:
# FIND ITEM ID ONLY LOCALLY
# ============================================================

def find_item_id_for_image(img):
    """
    Cerca l'Item ID SOLO nella card specifica.

    NON risale ai grandi container della lineup,
    perché lì possono essere presenti gli Item ID
    di tutte le altre carte.
    """

    # --------------------------------------------------------
    # 1. Attributi dell'immagine
    # --------------------------------------------------------

    attributes = [
        img.get("src"),
        img.get("data-src"),
        img.get("data-lazy-src"),
        img.get("data-original"),
        img.get("srcset"),
        img.get("data-srcset"),
    ]

    for value in attributes:

        if not value:
            continue

        ids = extract_item_ids(
            value
        )

        if len(ids) == 1:
            return next(
                iter(ids)
            )

    # --------------------------------------------------------
    # 2. <picture> immediatamente attorno all'immagine
    # --------------------------------------------------------

    picture = img.find_parent(
        "picture"
    )

    if picture:

        ids = extract_item_ids(
            str(picture)
        )

        if len(ids) == 1:
            return next(
                iter(ids)
            )

    # --------------------------------------------------------
    # 3. <a> immediatamente attorno all'immagine
    # --------------------------------------------------------

    link = img.find_parent(
        "a"
    )

    if link:

        # Prima controlliamo solo l'elemento link.
        ids = extract_item_ids(
            str(link)
        )

        if len(ids) == 1:
            return next(
                iter(ids)
            )

    # --------------------------------------------------------
    # 4. <source> vicini
    # --------------------------------------------------------

    parent = img.parent

    if parent:

        for source in parent.find_all(
            "source",
            recursive=False,
        ):

            attributes = [
                source.get("src"),
                source.get("srcset"),
                source.get("data-src"),
                source.get("data-srcset"),
            ]

            for value in attributes:

                if not value:
                    continue

                ids = extract_item_ids(
                    value
                )

                if len(ids) == 1:
                    return next(
                        iter(ids)
                    )

    # --------------------------------------------------------
    # IMPORTANT:
    #
    # NON cerchiamo nei parent successivi.
    # Altrimenti prendiamo l'ID di un'altra carta.
    # --------------------------------------------------------

    return None


# ============================================================
# FINISH DATABASE
# ============================================================

def load_card_database():

    if not CARD_DATABASE_FILE.exists():
        return {}

    try:

        with CARD_DATABASE_FILE.open(
            "r",
            encoding="utf-8",
        ) as file:

            data = json.load(
                file
            )

        if isinstance(
            data,
            dict,
        ):
            return data

    except Exception as error:

        print(
            "Could not load card_database.json:"
        )

        print(error)

    return {}


def finish_from_database(
    item_id,
    database,
):
    item_id = str(
        item_id
    )

    # KNOWN_FINISHES ha priorità
    if item_id in KNOWN_FINISHES:

        return KNOWN_FINISHES[
            item_id
        ]

    card = database.get(
        item_id
    )

    if isinstance(
        card,
        dict,
    ):

        finish = card.get(
            "finish"
        )

        if finish in {
            "BASE",
            "HOLO",
            "PRISTINE HOLO",
        }:
            return finish

        version = card.get(
            "version"
        )

        if version:
            return detect_finish_from_version(
                version
            )

        rarity = card.get(
            "rarity"
        )

        if rarity:
            return detect_finish_from_version(
                rarity
            )

    return "UNKNOWN"


# ============================================================
# PREVIOUS STATE
# ============================================================

def normalize_card(card):

    if not isinstance(
        card,
        dict,
    ):
        return None

    item_id = card.get(
        "item_id"
    )

    if item_id is None:
        item_id = card.get(
            "itemId"
        )

    if item_id is None:
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

    try:
        overall = int(
            overall
        )
    except Exception:
        overall = 0

    version = clean_text(
        card.get(
            "version",
            ""
        )
    )

    finish = card.get(
        "finish",
        "UNKNOWN",
    )

    return {
        "item_id": str(item_id),
        "player": player,
        "overall": overall,
        "version": version,
        "finish": finish,
    }


def normalize_category_state(
    value
):
    result = []

    if isinstance(
        value,
        list,
    ):

        for card in value:

            normalized = normalize_card(
                card
            )

            if normalized:
                result.append(
                    normalized
                )

    elif isinstance(
        value,
        dict,
    ):

        for key, card in value.items():

            if not isinstance(
                card,
                dict,
            ):
                continue

            if "item_id" not in card:

                card = {
                    **card,
                    "item_id": key,
                }

            normalized = normalize_card(
                card
            )

            if normalized:
                result.append(
                    normalized
                )

    return result


def load_previous_state():

    if not PLAYERS_FILE.exists():
        return {}

    try:

        with PLAYERS_FILE.open(
            "r",
            encoding="utf-8",
        ) as file:

            data = json.load(
                file
            )

    except Exception as error:

        print(
            "Could not load players.json:"
        )

        print(error)

        return {}

    if not isinstance(
        data,
        dict,
    ):
        return {}

    result = {}

    for category in CATEGORIES:

        result[category] = (
            normalize_category_state(
                data.get(
                    category,
                    []
                )
            )
        )

    return result


def save_previous_state(
    state
):
    with PLAYERS_FILE.open(
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            state,
            file,
            ensure_ascii=False,
            indent=2,
        )


# ============================================================
# FIND LINEUP
# ============================================================

def find_cheapest_lineup_images(
    soup,
    expected_slots,
):

    headings = soup.find_all(
        string=re.compile(
            r"Cheapest grade",
            re.IGNORECASE,
        )
    )

    if not headings:

        print(
            "Cheapest grade heading NOT found."
        )

        return []

    print(
        "Cheapest grade heading found."
    )

    candidates = []

    for heading in headings:

        current = heading

        for _ in range(8):

            if current is None:
                break

            parent = current.parent

            if parent is None:
                break

            images = parent.find_all(
                "img"
            )

            slots = []

            for img in images:

                if (
                    is_real_player_card(img)
                    or is_player_placeholder(img)
                ):
                    slots.append(
                        img
                    )

            if len(slots) >= expected_slots:

                candidates.append(
                    slots[
                        :expected_slots
                    ]
                )

            current = parent

    if not candidates:

        print(
            "No valid lineup container found."
        )

        return []

    # Scegliamo il candidato più vicino
    # al numero richiesto.
    candidates.sort(
        key=lambda x: abs(
            len(x)
            - expected_slots
        )
    )

    selected = candidates[0]

    print(
        "Lineup slot images found: "
        f"{len(selected)}/{expected_slots}"
    )

    print(
        "Selected lineup candidate: "
        f"{len(selected)} lineup slots"
    )

    return selected


# ============================================================
# PARSE LINEUP SLOT
# ============================================================

def parse_lineup_slot(
    img,
    database,
):

    alt = clean_text(
        img.get(
            "alt",
            ""
        )
    )

    # --------------------------------------------------------
    # EMPTY SLOT
    # --------------------------------------------------------

    if is_player_placeholder(
        img
    ):

        return {
            "empty": True,
            "item_id": None,
            "player": "Player Card",
            "overall": None,
            "version": "",
            "finish": None,
        }

    parsed = parse_player_alt(
        alt
    )

    if not parsed:
        return None

    # --------------------------------------------------------
    # QUESTO È IL FIX PRINCIPALE
    # --------------------------------------------------------

    item_id = find_item_id_for_image(
        img
    )

    if item_id is None:

        print(
            f"WARNING: Item ID not found "
            f"for {parsed['player']} "
            f"{parsed['overall']}"
        )

        return {
            "empty": False,
            "item_id": None,
            "player": parsed["player"],
            "overall": parsed["overall"],
            "version": parsed["version"],
            "finish": "UNKNOWN",
        }

    finish = finish_from_database(
        item_id,
        database,
    )

    return {
        "empty": False,
        "item_id": str(item_id),
        "player": parsed["player"],
        "overall": parsed["overall"],
        "version": parsed["version"],
        "finish": finish,
    }


# ============================================================
# PARSE CATEGORY
# ============================================================

def parse_category(
    category_name,
    config,
    database,
):

    print()
    print("=" * 60)

    print(
        f"Checking {config['emoji']} "
        f"{category_name.upper()} "
        f"({config['slots']} players)..."
    )

    print("=" * 60)

    html = fetch_url(
        config["url"]
    )

    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    real_images = []

    for img in soup.find_all(
        "img"
    ):

        if is_real_player_card(
            img
        ):
            real_images.append(
                img
            )

    print(
        "Real player-card images found "
        f"in page: {len(real_images)}"
    )

    lineup_images = (
        find_cheapest_lineup_images(
            soup,
            config["slots"],
        )
    )

    if not lineup_images:

        print(
            "Could not locate lineup."
        )

        return []

    print(
        "Images/cards detected in "
        f"selected container: "
        f"{len(lineup_images)}"
    )

    lineup = []

    for img in lineup_images:

        card = parse_lineup_slot(
            img,
            database,
        )

        if card is None:
            continue

        lineup.append(
            card
        )

    lineup = lineup[
        :config["slots"]
    ]

    print(
        "Rendered lineup: "
        f"{len(lineup)}/{config['slots']} slots"
    )

    for card in lineup:

        if card.get(
            "empty"
        ):

            print(
                "- Player Card — EMPTY SLOT"
            )

        else:

            print(
                f"- {card['player']} "
                f"{card['overall']} "
                f"{card['version']} "
                f"— ItemID "
                f"{card['item_id']} "
                f"— {card['finish']}"
            )

    return lineup


# ============================================================
# CARD IDENTITY
# ============================================================

def card_identity(card):

    if not card:
        return None

    if card.get(
        "empty"
    ):
        return None

    item_id = card.get(
        "item_id"
    )

    if not item_id:
        return None

    return str(
        item_id
    )


# ============================================================
# CHANGES
# ============================================================

def calculate_changes(
    previous,
    current,
):

    previous_ids = []

    current_ids = []

    for card in previous:

        identity = card_identity(
            card
        )

        if identity:
            previous_ids.append(
                identity
            )

    for card in current:

        identity = card_identity(
            card
        )

        if identity:
            current_ids.append(
                identity
            )

    previous_counter = Counter(
        previous_ids
    )

    current_counter = Counter(
        current_ids
    )

    gone = []

    new = []

    for item_id in previous_counter:

        difference = (
            previous_counter[item_id]
            - current_counter[item_id]
        )

        for _ in range(
            max(0, difference)
        ):

            gone.append(
                item_id
            )

    for item_id in current_counter:

        difference = (
            current_counter[item_id]
            - previous_counter[item_id]
        )

        for _ in range(
            max(0, difference)
        ):

            new.append(
                item_id
            )

    return gone, new


def find_card_by_id(
    cards,
    item_id,
):

    item_id = str(
        item_id
    )

    for card in cards:

        if str(
            card.get(
                "item_id"
            )
        ) == item_id:

            return card

    return None


# ============================================================
# FORMAT
# ============================================================

def format_card(card):

    if not card:
        return ""

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
        "finish",
        "UNKNOWN",
    )

    if overall is None:

        return (
            f"<b>{player}</b>"
        )

    return (
        f"<b>{player} {overall}</b>"
        f"　·　{finish}"
    )


# ============================================================
# HOLOGRAPHIC DATABASE
# ============================================================

def extract_holographic_records(
    html,
    finish,
):

    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    records = {}

    for img in soup.find_all(
        "img"
    ):

        alt = clean_text(
            img.get(
                "alt",
                ""
            )
        )

        parsed = parse_player_alt(
            alt
        )

        if not parsed:
            continue

        item_id = find_item_id_for_image(
            img
        )

        if item_id is None:
            continue

        records[
            str(item_id)
        ] = {
            "item_id": str(item_id),
            "player": parsed["player"],
            "overall": parsed["overall"],
            "rarity": parsed["version"],
            "version": parsed["version"],
            "finish": finish,
        }

    return records


def update_holographic_database(
    database,
):

    print()
    print("=" * 60)
    print(
        "Updating Holographic database"
    )
    print("=" * 60)

    discovered = {}

    for finish, url in (
        HOLOGRAPHIC_DATABASE_URLS.items()
    ):

        print()
        print(
            f"Scanning {finish}..."
        )

        try:

            html = fetch_url(
                url
            )

        except Exception as error:

            print(
                f"Error scanning {finish}: "
                f"{error}"
            )

            continue

        records = extract_holographic_records(
            html,
            finish,
        )

        print(
            f"  Records found on page: "
            f"{len(records)}"
        )

        for item_id, record in records.items():

            discovered[
                item_id
            ] = record

    print()
    print(
        "Holographic records discovered: "
        f"{len(discovered)}"
    )

    for item_id, record in discovered.items():

        if item_id in KNOWN_FINISHES:

            record["finish"] = (
                KNOWN_FINISHES[
                    item_id
                ]
            )

        database[item_id] = record

    return database


# ============================================================
# SAVE DATABASE
# ============================================================

def save_card_database(
    database
):

    with CARD_DATABASE_FILE.open(
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            database,
            file,
            ensure_ascii=False,
            indent=2,
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
        return False

    if not TELEGRAM_CHAT_ID:
        print(
            "TELEGRAM_CHAT_ID missing."
        )
        return False

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
        data=payload,
        timeout=30,
    )

    print(
        f"Telegram status: "
        f"{response.status_code}"
    )

    if response.status_code != 200:

        print(
            response.text
        )

        return False

    return True


# ============================================================
# TELEGRAM MESSAGE
# ============================================================

def build_telegram_message(
    current_state,
    changes,
):

    lines = []

    lines.append(
        "<b>📋 FUT.GG Monitor</b>"
    )

    categories = list(
        CATEGORIES.keys()
    )

    for index, category in enumerate(
        categories
    ):

        config = CATEGORIES[
            category
        ]

        lines.append(
            f"<b>{config['emoji']} "
            f"{category}</b>"
        )

        lines.append(
            "<b>📋 Current lineup 📋</b>"
        )

        current = current_state.get(
            category,
            []
        )

        new_ids = set(
            changes.get(
                category,
                {}
            ).get(
                "new",
                []
            )
        )

        for card in current:

            if card.get(
                "empty"
            ):
                continue

            identity = card_identity(
                card
            )

            prefix = ""

            if identity in new_ids:
                prefix = "🟢 "

            lines.append(
                prefix
                + format_card(card)
            )

        gone_ids = changes.get(
            category,
            {}
        ).get(
            "gone",
            []
        )

        previous_cards = changes.get(
            category,
            {}
        ).get(
            "previous_cards",
            {}
        )

        for item_id in gone_ids:

            previous_card = (
                previous_cards.get(
                    str(item_id)
                )
            )

            if previous_card:

                lines.append(
                    "🔴 OUT — "
                    + format_card(
                        previous_card
                    )
                )

        if index < len(categories) - 1:

            lines.append("")
            lines.append(
                "--------------------"
            )
            lines.append("")

    return "\n".join(
        lines
    )


# ============================================================
# CLEAN STATE
# ============================================================

def clean_state(
    state
):

    result = {}

    for category in CATEGORIES:

        cards = state.get(
            category,
            []
        )

        clean_cards = []

        for card in cards:

            if not isinstance(
                card,
                dict,
            ):
                continue

            if card.get(
                "empty"
            ):
                continue

            # NON salviamo carte senza Item ID
            if not card.get(
                "item_id"
            ):
                continue

            clean_cards.append(
                card
            )

        result[category] = (
            clean_cards
        )

    return result


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print(
        "FUT.GG MONITOR"
    )

    print(
        time.strftime(
            "%Y-%m-%dT%H:%M:%S"
        )
    )

    print("=" * 60)

    # --------------------------------------------------------
    # DATABASE
    # --------------------------------------------------------

    database = load_card_database()

    # KNOWN_FINISHES
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

        else:

            database[item_id][
                "finish"
            ] = finish

    print()
    print(
        "Known card finishes added to database: "
        f"{len(KNOWN_FINISHES)}"
    )

    # --------------------------------------------------------
    # HOLOGRAPHIC DATABASE
    # --------------------------------------------------------

    database = update_holographic_database(
        database
    )

    print()
    print(
        f"Database items: "
        f"{len(database)}"
    )

    players_count = 0

    for card in database.values():

        if (
            isinstance(
                card,
                dict,
            )
            and card.get(
                "player"
            )
        ):

            players_count += 1

    print(
        f"Database players: "
        f"{players_count}"
    )

    # --------------------------------------------------------
    # PREVIOUS
    # --------------------------------------------------------

    previous_state = (
        load_previous_state()
    )

    # --------------------------------------------------------
    # CURRENT
    # --------------------------------------------------------

    current_state = {}

    changes = {}

    for category, config in (
        CATEGORIES.items()
    ):

        current = parse_category(
            category,
            config,
            database,
        )

        current_state[
            category
        ] = current

        previous = previous_state.get(
            category,
            []
        )

        gone, new = calculate_changes(
            previous,
            current,
        )

        previous_cards = {}

        for item_id in gone:

            card = find_card_by_id(
                previous,
                item_id,
            )

            if card:

                previous_cards[
                    str(item_id)
                ] = card

        changes[
            category
        ] = {
            "gone": gone,
            "new": new,
            "previous_cards": previous_cards,
        }

    # --------------------------------------------------------
    # TELEGRAM
    # --------------------------------------------------------

    message = build_telegram_message(
        current_state,
        changes,
    )

    print()
    print("=" * 60)
    print(
        "TELEGRAM MESSAGE"
    )
    print("=" * 60)

    print(
        message
    )

    send_telegram_message(
        message
    )

    # --------------------------------------------------------
    # SAVE
    # --------------------------------------------------------

    clean_current_state = clean_state(
        current_state
    )

    save_previous_state(
        clean_current_state
    )

    save_card_database(
        database
    )

    print()
    print(
        "DONE"
    )


if __name__ == "__main__":
    main()