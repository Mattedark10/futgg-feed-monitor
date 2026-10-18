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
CARD_CACHE_FILE = "card_cache.json"
CARD_DATABASE_FILE = "card_database.json"

TRENDING_FILE = "docs/trending.json"

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

    # --------------------------------------------------------
    # HOLO
    # --------------------------------------------------------

    "67179830": "HOLO",            # Jacobo Ramón
    "67188263": "HOLO",            # Mora
    "67368429": "HOLO",            # Bonny
    "67353040": "HOLO",            # Undav
    "67372629": "HOLO",            # Bischof
    "67386815": "HOLO",            # Yohannes
    "67374557": "HOLO",

    # --------------------------------------------------------
    # BASE
    # --------------------------------------------------------

    "226306": "BASE",              # Šašić
    "233700": "BASE",              # Vialli
    "5673": "BASE",                # Litmanen
    "50590935": "BASE",            # Harder
    "50590026": "BASE",            # Godts
    "50570879": "BASE",            # Cucurella
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
# PLAYER PARSING
# ============================================================

def parse_player_alt(img):
    if not img:
        return None

    alt = (
        img.get("alt")
        or img.get("data-alt")
        or img.get("title")
        or ""
    )

    alt = html.unescape(alt).strip()

    if not alt:
        return None

    return alt


def is_player_placeholder(name):
    if not name:
        return True

    normalized = name.lower().strip()

    placeholders = {
        "player card",
        "player",
        "empty",
        "empty slot",
        "card",
        "placeholder",
    }

    return normalized in placeholders


def is_real_player_card(img):
    name = parse_player_alt(img)

    if not name:
        return False

    if is_player_placeholder(name):
        return False

    return True


# ============================================================
# ITEM ID EXTRACTION
# ============================================================

def extract_item_ids(text):
    if not text:
        return []

    text = html.unescape(str(text))

    patterns = [
        r"item[_\-\s]?id[\"'\s:=]+(\d{4,})",
        r"itemId[\"'\s:=]+(\d{4,})",
        r"itemID[\"'\s:=]+(\d{4,})",
        r"item[_\-]?id=(\d{4,})",
        r"item/(\d{4,})",
    ]

    found = []

    for pattern in patterns:
        matches = re.findall(pattern, text, flags=re.IGNORECASE)

        for match in matches:
            if match not in found:
                found.append(match)

    return found


def extract_item_id_from_attributes(element):
    if not element:
        return None

    attrs_to_check = [
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

    for attr in attrs_to_check:
        value = element.get(attr)

        if not value:
            continue

        ids = extract_item_ids(value)

        if ids:
            return ids[0]

    return None


def find_card_wrapper(img):
    """
    Find a SMALL DOM wrapper belonging only to this card.

    IMPORTANT:
    Never use a large parent containing multiple player cards.
    """

    if not img:
        return None

    current = img

    for _ in range(6):

        current = current.parent

        if not current:
            break

        imgs = current.find_all("img")

        real_imgs = [
            x for x in imgs
            if is_real_player_card(x)
        ]

        # A valid card wrapper must contain exactly one
        # real player-card image.
        if len(real_imgs) == 1 and real_imgs[0] is img:

            # Check whether this small wrapper contains
            # an Item ID.
            text_blob = str(current)

            ids = extract_item_ids(text_blob)

            if ids:
                return current

    return None


def find_item_id_for_image(img):
    """
    Extract Item ID strictly from the current card.

    Order:
    1. image attributes
    2. picture/source
    3. immediate link
    4. small unique card wrapper

    NEVER search a large common parent.
    """

    if not img:
        return None

    # --------------------------------------------------------
    # 1. IMAGE ATTRIBUTES
    # --------------------------------------------------------

    item_id = extract_item_id_from_attributes(img)

    if item_id:
        return item_id

    # --------------------------------------------------------
    # 2. PICTURE / SOURCE
    # --------------------------------------------------------

    picture = img.find_parent("picture", recursive=False)

    if picture:

        item_id = extract_item_id_from_attributes(picture)

        if item_id:
            return item_id

        for source in picture.find_all("source", recursive=False):

            item_id = extract_item_id_from_attributes(source)

            if item_id:
                return item_id

    # --------------------------------------------------------
    # 3. IMMEDIATE LINK
    # --------------------------------------------------------

    parent = img.parent

    if parent and parent.name == "a":

        item_id = extract_item_id_from_attributes(parent)

        if item_id:
            return item_id

    # --------------------------------------------------------
    # 4. UNIQUE SMALL CARD WRAPPER
    # --------------------------------------------------------

    wrapper = find_card_wrapper(img)

    if wrapper:

        ids = extract_item_ids(str(wrapper))

        if ids:
            return ids[0]

    # --------------------------------------------------------
    # NOTHING FOUND
    # --------------------------------------------------------

    return None


# ============================================================
# CARD DATABASE
# ============================================================

def load_card_database():
    if not os.path.exists(CARD_DATABASE_FILE):
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
        print(f"Error loading card database: {e}")

    return {}


def finish_from_database(item_id, database):
    if not item_id:
        return "UNKNOWN"

    item_id = str(item_id)

    # Known mapping always has priority.
    if item_id in KNOWN_FINISHES:
        return KNOWN_FINISHES[item_id]

    record = database.get(item_id)

    if isinstance(record, dict):

        finish = record.get("finish")

        if finish:
            return finish

    return "UNKNOWN"


def add_known_finishes(database):
    added = 0

    for item_id, finish in KNOWN_FINISHES.items():

        item_id = str(item_id)

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
            if database[item_id].get("finish") != finish:
                database[item_id]["finish"] = finish

    return added


# ============================================================
# STATE
# ============================================================

def load_previous_state():
    if not os.path.exists(PLAYERS_FILE):
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
        print(f"Error loading previous state: {e}")

    return {}


def save_previous_state(state):
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

def find_cheapest_lineup_images(soup, expected_slots):
    headings = soup.find_all(
        string=re.compile(
            r"Cheapest grade",
            re.IGNORECASE
        )
    )

    if headings:
        print("Cheapest grade heading found.")
    else:
        print("Cheapest grade heading NOT found.")

    all_images = soup.find_all("img")

    player_images = [
        img
        for img in all_images
        if is_real_player_card(img)
    ]

    print(
        f"Real player-card images found in page: "
        f"{len(player_images)}"
    )

    candidates = []

    # Search around each real player image.
    for img in player_images:

        current = img

        for depth in range(1, 9):

            current = current.parent

            if not current:
                break

            imgs = current.find_all("img")

            real_imgs = [
                x
                for x in imgs
                if is_real_player_card(x)
            ]

            # Candidate must have exactly expected number
            # of real cards.
            if len(real_imgs) == expected_slots:

                candidates.append(
                    (
                        depth,
                        current,
                        real_imgs
                    )
                )

    if candidates:

        # Prefer the smallest container.
        candidates.sort(
            key=lambda x: x[0]
        )

        depth, container, images = candidates[0]

        print(
            f"Selected lineup candidate: "
            f"{len(images)} lineup slots"
        )

        return images

    # Fallback: first expected real player cards.
    return player_images[:expected_slots]


# ============================================================
# PARSE SLOT
# ============================================================

def parse_lineup_slot(img, database):
    player_name = parse_player_alt(img)

    if not player_name:
        return {
            "player": "Player Card",
            "item_id": None,
            "finish": "UNKNOWN",
            "empty": True,
        }

    if is_player_placeholder(player_name):

        return {
            "player": "Player Card",
            "item_id": None,
            "finish": "UNKNOWN",
            "empty": True,
        }

    item_id = find_item_id_for_image(img)

    finish = finish_from_database(
        item_id,
        database
    )

    # Try to obtain overall from name.
    overall = None

    match = re.search(
        r"\b(\d{2})\b",
        player_name
    )

    if match:
        overall = int(match.group(1))

    return {
        "player": player_name,
        "overall": overall,
        "item_id": item_id,
        "finish": finish,
        "empty": False,
    }


# ============================================================
# CATEGORY PARSER
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
        f"Checking {config['emoji']} "
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

    for img in images[:config["slots"]]:

        card = parse_lineup_slot(
            img,
            database
        )

        lineup.append(card)

    # Fill missing slots.
    while len(lineup) < config["slots"]:

        lineup.append({
            "player": "Player Card",
            "overall": None,
            "item_id": None,
            "finish": "UNKNOWN",
            "empty": True,
        })

    real_count = sum(
        1
        for card in lineup
        if not card["empty"]
    )

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

            overall = card.get("overall")

            if overall:
                player_display = (
                    f"{card['player']}"
                )
            else:
                player_display = card["player"]

            print(
                f"- {player_display} "
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

    item_id = card.get("item_id")

    if item_id:
        return (
            "ITEM",
            str(item_id),
            str(card.get("finish") or "UNKNOWN")
        )

    return (
        "PLAYER",
        str(card.get("player") or ""),
        str(card.get("overall") or ""),
        str(card.get("finish") or "UNKNOWN")
    )


# ============================================================
# CLEAN / NORMALIZE STATE
# ============================================================

def normalize_card(card):
    if not isinstance(card, dict):
        return None

    if card.get("empty"):
        return None

    return {
        "player": card.get("player", ""),
        "overall": card.get("overall"),
        "item_id": (
            str(card["item_id"])
            if card.get("item_id") is not None
            else None
        ),
        "finish": card.get("finish", "UNKNOWN"),
        "empty": False,
    }


def unique_cards(cards):
    """
    Deduplicate only for change detection.

    This does NOT change the actual lineup.

    If the same card appears twice legitimately in the current
    lineup with the same Item ID, the lineup still keeps both.
    """

    result = []
    seen = set()

    for card in cards:

        normalized = normalize_card(card)

        if not normalized:
            continue

        identity = card_identity(normalized)

        if identity in seen:
            continue

        seen.add(identity)
        result.append(normalized)

    return result


# ============================================================
# CHANGES
# ============================================================

def calculate_changes(
    previous_lineup,
    current_lineup
):
    """
    Returns:
        current_cards
        new_cards
        out_cards

    Change detection is intentionally based on UNIQUE identities.

    This prevents old corrupted state from producing:
        OUT
        OUT
        OUT
        OUT
    for the same card.
    """

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
            new_cards.append(card)

    out_cards = []

    for identity, card in previous_map.items():

        if identity not in current_map:
            out_cards.append(card)

    return (
        current_unique,
        new_cards,
        out_cards,
    )


# ============================================================
# FIND CARD
# ============================================================

def find_card_by_id(
    lineup,
    item_id
):
    if not item_id:
        return None

    item_id = str(item_id)

    for card in lineup:

        if str(card.get("item_id")) == item_id:
            return card

    return None


# ============================================================
# FORMAT
# ============================================================

def format_card(card):
    player = card.get("player", "")

    overall = card.get("overall")

    if overall:
        name = f"{player} {overall}"
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
# HOLOGRAPHIC DATABASE
# ============================================================

def extract_holographic_records(
    html_text
):
    """
    FUT.GG currently renders this page in a way where the
    records may not be present in normal server-side HTML.

    Therefore this parser is deliberately conservative.

    It NEVER invents cards.
    """

    soup = BeautifulSoup(
        html_text,
        "html.parser"
    )

    records = []

    # Look for obvious Item ID patterns.
    all_text = str(soup)

    ids = extract_item_ids(
        all_text
    )

    # Avoid importing arbitrary page IDs.
    # Only IDs already known to belong to holographic cards
    # are accepted here.
    for item_id in ids:

        if item_id not in KNOWN_FINISHES:
            continue

        finish = KNOWN_FINISHES[item_id]

        if finish not in (
            "HOLO",
            "PRISTINE HOLO"
        ):
            continue

        records.append({
            "item_id": item_id,
            "finish": finish,
        })

    # Deduplicate.
    unique = {}

    for record in records:
        unique[
            record["item_id"]
        ] = record

    return list(
        unique.values()
    )


def update_holographic_database(
    database
):
    print()
    print(
        "=" * 60
    )
    print(
        "Updating Holographic database"
    )
    print(
        "=" * 60
    )

    all_records = []

    pages = [
        (
            "PRISTINE HOLO",
            "https://www.fut.gg/holographic-cards/?finish=pristine"
        ),
        (
            "HOLO",
            "https://www.fut.gg/holographic-cards/?finish=holographic"
        ),
    ]

    for finish_name, url in pages:

        print()
        print(
            f"Scanning {finish_name}..."
        )

        try:
            html_text = fetch_url(url)

            records = extract_holographic_records(
                html_text
            )

            print(
                f"  Records found on page: "
                f"{len(records)}"
            )

            all_records.extend(
                records
            )

        except Exception as e:

            print(
                f"  Error: {e}"
            )

    # Deduplicate.
    unique_records = {}

    for record in all_records:

        item_id = str(
            record["item_id"]
        )

        unique_records[
            item_id
        ] = record

    print()
    print(
        f"Holographic records discovered: "
        f"{len(unique_records)}"
    )

    # Add/update only records actually discovered.
    for item_id, record in unique_records.items():

        if item_id not in database:

            database[item_id] = {
                "item_id": item_id,
                "player": "",
                "overall": None,
                "rarity": "",
                "version": "",
                "finish": record["finish"],
            }

        else:

            database[item_id]["finish"] = (
                record["finish"]
            )


# ============================================================
# SAVE DATABASE
# ============================================================

def save_card_database(database):

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
# TELEGRAM
# ============================================================

def send_telegram_message(message):

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
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
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
    # CURRENT LINEUP
    # --------------------------------------------------------

    for card in current_lineup:

        lines.append(
            f"🟢 {format_card(card)}"
        )

    # --------------------------------------------------------
    # OUT
    # --------------------------------------------------------

    # IMPORTANT:
    # unique_cards() guarantees only one OUT per identity.

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

    for category_name, result in results.items():

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

def clean_state(state):

    cleaned = {}

    if not isinstance(state, dict):
        return cleaned

    for category_name, lineup in state.items():

        if not isinstance(lineup, list):
            cleaned[category_name] = []
            continue

        cleaned_lineup = []

        for card in lineup:

            if not isinstance(card, dict):
                continue

            if card.get("empty"):
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

        cleaned[category_name] = cleaned_lineup

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
    # LOAD DATABASE
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

    # --------------------------------------------------------
    # HOLOGRAPHIC DATABASE
    # --------------------------------------------------------

    update_holographic_database(
        database
    )

    save_card_database(
        database
    )

    # --------------------------------------------------------
    # LOAD PREVIOUS STATE
    # --------------------------------------------------------

    previous_state = clean_state(
        load_previous_state()
    )

    # --------------------------------------------------------
    # SCAN CATEGORIES
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

            # Keep previous state if scan fails.
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
            out_cards,
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
    # SAVE CLEAN CURRENT STATE
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