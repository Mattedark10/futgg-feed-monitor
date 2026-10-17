import os
import re
import json
from datetime import datetime
from collections import Counter
from html import escape

import requests
from bs4 import BeautifulSoup


# ============================================================
# CONFIG
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

PLAYERS_FILE = "players.json"
CARD_CACHE_FILE = "card_cache.json"

HOLO_DB_FILE = "card_database.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0 Safari/537.36"
    )
}

CATEGORY_CONFIG = {
    "Heroes": {
        "url": "https://www.fut.gg/fut-gallery/rarities/heroes/",
        "emoji": "🦸‍♂️",
        "expected_slots": 5,
    },
    "Holographics": {
        "url": "https://www.fut.gg/fut-gallery/rarities/holographics/",
        "emoji": "✨️",
        "expected_slots": 5,
    },
    "Season 1": {
        "url": "https://www.fut.gg/fut-gallery/rarities/season-1/",
        "emoji": "1️⃣",
        "expected_slots": 10,
    },
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
# REGEX
# ============================================================

ITEM_ID_PATTERN = re.compile(
    r"futgg-player-item-card/27-(\d+)",
    re.IGNORECASE
)

ALT_PATTERN = re.compile(
    r"^\s*(.*?)\s*-\s*(\d+)\s*-\s*(.*?)\s*$"
)


# ============================================================
# JSON HELPERS
# ============================================================

def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ============================================================
# HTTP
# ============================================================

def fetch_html(url):
    print(f"Fetching: {url}")

    response = requests.get(
        url,
        headers=HEADERS,
        timeout=30
    )

    print(f"HTTP status: {response.status_code}")

    response.raise_for_status()

    html = response.text

    print(f"Downloaded: {len(html)} characters")

    return html


# ============================================================
# ITEM ID
# ============================================================

def extract_item_id(img):
    """
    Extract FUT.GG item ID from the player-card image URL.
    """

    values = [
        img.get("src", ""),
        img.get("data-src", ""),
        img.get("data-lazy-src", ""),
        img.get("srcset", ""),
    ]

    for value in values:
        if not value:
            continue

        match = ITEM_ID_PATTERN.search(value)

        if match:
            return match.group(1)

    return None


# ============================================================
# IMAGE TYPE
# ============================================================

def is_real_player_card(img):
    """
    A real FUT.GG player card has:
        futgg-player-item-card/27-<ID>
    in one of its image URL attributes.
    """

    return extract_item_id(img) is not None


def is_player_placeholder(img):
    """
    Empty gallery slot.
    """

    alt = (img.get("alt") or "").strip().lower()

    return alt == "player card"


# ============================================================
# ALT PARSER
# ============================================================

def parse_player_alt(alt):
    """
    FUT.GG currently exposes player information like:

        Šašić - 89 - Base Hero
        Vialli - 89 - Base Hero
        Mora - 87 - Future Stars

    Returns:
        name
        overall
        version
    """

    if not alt:
        return None, None, None

    alt = " ".join(alt.split()).strip()

    match = ALT_PATTERN.match(alt)

    if not match:
        return None, None, None

    name = match.group(1).strip()
    overall = int(match.group(2))
    version = match.group(3).strip()

    # Safety: don't accidentally accept utility images.
    if name.lower() in {
        "fc coin",
        "gallery token",
        "grading score",
        "player card",
    }:
        return None, None, None

    return name, overall, version


# ============================================================
# FIND CHEAPEST LINEUP
# ============================================================

def find_cheapest_lineup_images(soup, expected_slots):
    """
    Find exactly the images belonging to:

        Cheapest grade X lineup

    and stop before:

        Add players

    This is much safer than selecting a large ancestor container.
    """

    cheapest_heading = None

    # Search headings first.
    for tag in soup.find_all(["h1", "h2", "h3", "h4", "div"]):

        text = " ".join(tag.stripped_strings)

        if not text:
            continue

        if re.search(
            r"Cheapest\s+grade\s+.*\s+lineup",
            text,
            re.IGNORECASE
        ):
            cheapest_heading = tag
            break

    if cheapest_heading is None:
        print("WARNING: Cheapest grade heading not found.")
        return []

    print("Cheapest grade heading found.")

    lineup_images = []

    # Walk forward through relevant DOM nodes.
    for tag in cheapest_heading.find_all_next(["img", "h1", "h2", "h3", "h4"]):

        if tag.name in {"h1", "h2", "h3", "h4"}:

            text = " ".join(tag.stripped_strings).strip()

            if re.search(r"^Add players$", text, re.IGNORECASE):
                break

        elif tag.name == "img":

            # Only accept actual player cards OR Player Card placeholders.
            if is_real_player_card(tag) or is_player_placeholder(tag):
                lineup_images.append(tag)

                if len(lineup_images) >= expected_slots:
                    break

    print(
        f"Lineup slot images found: "
        f"{len(lineup_images)}/{expected_slots}"
    )

    return lineup_images


# ============================================================
# PARSE ONE LINEUP SLOT
# ============================================================

def parse_lineup_slot(img, database, previous_categories=None):
    """
    Parse a single lineup slot.

    Real player:
        item_id
        name
        overall
        version
        finish

    Empty Player Card:
        placeholder=True
    """

    # --------------------------------------------------------
    # EMPTY SLOT
    # --------------------------------------------------------

    if is_player_placeholder(img) and not is_real_player_card(img):

        return {
            "name": "",
            "overall": None,
            "version": "",
            "item_id": None,
            "finish": "UNKNOWN",
            "placeholder": True,
        }

    # --------------------------------------------------------
    # REAL PLAYER
    # --------------------------------------------------------

    item_id = extract_item_id(img)

    if not item_id:
        return None

    alt = (img.get("alt") or "").strip()

    name, overall, version = parse_player_alt(alt)

    if not name or overall is None:
        print(
            f"WARNING: Could not parse player alt: {alt!r}"
        )
        return None

    # --------------------------------------------------------
    # FINISH
    # --------------------------------------------------------

    finish = "UNKNOWN"

    # 1. Database has priority.
    record = database.get(item_id)

    if isinstance(record, dict):
        db_finish = record.get("finish")

        if db_finish and db_finish != "UNKNOWN":
            finish = db_finish

    # 2. Known static mapping.
    if finish == "UNKNOWN":
        finish = KNOWN_FINISHES.get(item_id, "UNKNOWN")

    # 3. Previous state can preserve a previously known finish.
    if finish == "UNKNOWN" and previous_categories:
        for old in previous_categories:

            if str(old.get("item_id")) == str(item_id):

                old_finish = old.get("finish")

                if old_finish and old_finish != "UNKNOWN":
                    finish = old_finish
                    break

    return {
        "name": name,
        "overall": overall,
        "version": version,
        "item_id": item_id,
        "finish": finish,
        "placeholder": False,
    }


# ============================================================
# VALIDATE LINEUP
# ============================================================

def validate_lineup(lineup, expected_slots):
    """
    Reject dangerous parses.

    Never allow FC Coin / Gallery Token / missing names
    to overwrite a valid previous lineup.
    """

    if not lineup:
        return False

    if len(lineup) != expected_slots:
        return False

    real_cards = [
        card for card in lineup
        if not card.get("placeholder")
    ]

    # Must have at least one real player.
    if not real_cards:
        return False

    for card in real_cards:

        name = (card.get("name") or "").strip()

        if not name:
            return False

        if name.lower() in {
            "fc coin",
            "gallery token",
            "player card",
        }:
            return False

        if not card.get("item_id"):
            return False

        if card.get("overall") is None:
            return False

    return True


# ============================================================
# PARSE CATEGORY
# ============================================================

def parse_category(category, config, database, previous_state):
    print()
    print("=" * 60)
    print(f"Checking {config['emoji']} {category.upper()} "
          f"({config['expected_slots']} players)...")
    print("=" * 60)

    html = fetch_html(config["url"])

    soup = BeautifulSoup(html, "html.parser")

    all_real_images = [
        img
        for img in soup.find_all("img")
        if is_real_player_card(img)
    ]

    print(
        f"Real player-card images found in page: "
        f"{len(all_real_images)}"
    )

    images = find_cheapest_lineup_images(
        soup,
        config["expected_slots"]
    )

    if not images:
        print("WARNING: Could not find lineup images.")
        print("WARNING: Previous state kept.")
        return None

    print(
        f"Selected lineup candidate: "
        f"{len(images)} lineup slots"
    )

    old_category = previous_state.get(category, {})
    old_current = old_category.get("current", [])

    lineup = []

    for img in images:

        card = parse_lineup_slot(
            img,
            database,
            previous_categories=old_current
        )

        if card is None:
            print(
                "WARNING: Failed to parse one lineup slot."
            )
            print("WARNING: Previous state kept.")
            return None

        lineup.append(card)

    print(
        f"Images/cards detected in selected lineup: "
        f"{len(lineup)}"
    )

    if not validate_lineup(
        lineup,
        config["expected_slots"]
    ):
        print(
            "WARNING: Invalid lineup detected."
        )
        print("WARNING: Previous state kept.")
        return None

    print(
        f"Rendered lineup: "
        f"{len(lineup)}/{config['expected_slots']} slots"
    )

    for card in lineup:

        if card["placeholder"]:
            print("- Player Card — EMPTY SLOT")
        else:
            print(
                f"- {card['name']} "
                f"{card['overall']} "
                f"{card['version']} "
                f"— ItemID {card['item_id']} "
                f"— {card['finish']}"
            )

    return lineup


# ============================================================
# HOLOGRAPHIC DATABASE
# ============================================================

def update_holographic_database(database):
    print()
    print("=" * 60)
    print("Updating Holographic database")
    print("=" * 60)

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

    discovered = {}

    for finish, url in pages:

        print()
        print(f"Scanning {finish}...")

        try:
            html = fetch_html(url)
        except Exception as e:
            print(
                f"WARNING: Failed to scan holographic page: {e}"
            )
            continue

        soup = BeautifulSoup(html, "html.parser")

        records = {}

        for img in soup.find_all("img"):

            item_id = extract_item_id(img)

            if not item_id:
                continue

            records[item_id] = {
                "item_id": item_id,
                "finish": finish,
            }

        print(
            f"  Records found on page: {len(records)}"
        )

        for item_id, record in records.items():
            discovered[item_id] = record

    print()
    print(
        f"Holographic records discovered: "
        f"{len(discovered)}"
    )

    # Add discovered records.
    for item_id, record in discovered.items():

        database[item_id] = record

    # Add known finishes that aren't discovered on the page.
    for item_id, finish in KNOWN_FINISHES.items():

        if item_id not in database:

            database[item_id] = {
                "item_id": item_id,
                "finish": finish,
            }

    print(
        f"Database items: {len(database)}"
    )

    # This database intentionally stores card identity + finish.
    players_count = sum(
        1
        for value in database.values()
        if isinstance(value, dict)
        and value.get("name")
    )

    print(
        f"Database players: {players_count}"
    )

    save_json(
        HOLO_DB_FILE,
        database
    )

    return database


# ============================================================
# FINISH DATABASE LOAD
# ============================================================

def load_card_database():
    database = load_json(
        HOLO_DB_FILE,
        {}
    )

    if not isinstance(database, dict):
        database = {}

    added = 0

    for item_id, finish in KNOWN_FINISHES.items():

        if item_id not in database:

            database[item_id] = {
                "item_id": item_id,
                "finish": finish,
            }

            added += 1

    print(
        f"Known card finishes added to database: "
        f"{added}"
    )

    return database


# ============================================================
# CARD IDENTITY
# ============================================================

def card_identity(card):
    """
    Item ID is the primary identity.

    This intentionally allows two cards with the same
    player/name/rating to coexist when Item IDs differ.
    """

    if card.get("placeholder"):
        return "PLACEHOLDER"

    item_id = card.get("item_id")

    if item_id:
        return f"ITEM:{item_id}"

    return (
        f"UNKNOWN:"
        f"{card.get('name','')}:"
        f"{card.get('overall','')}:"
        f"{card.get('finish','')}"
    )


# ============================================================
# MULTISET COMPARISON
# ============================================================

def counter_from_cards(cards):
    return Counter(
        card_identity(card)
        for card in cards
    )


def calculate_changes(old_cards, new_cards):
    """
    Returns actual OUT and IN occurrences.

    Order changes are ignored.

    Duplicate Item IDs are handled as separate occurrences.
    """

    old_counter = counter_from_cards(old_cards)
    new_counter = counter_from_cards(new_cards)

    outs = []
    ins = []

    old_by_identity = {}

    for card in old_cards:
        key = card_identity(card)
        old_by_identity.setdefault(key, []).append(card)

    new_by_identity = {}

    for card in new_cards:
        key = card_identity(card)
        new_by_identity.setdefault(key, []).append(card)

    # OUT
    for key, count in (old_counter - new_counter).items():

        cards = old_by_identity.get(key, [])

        for card in cards[:count]:

            # Never report placeholders as OUT.
            if card.get("placeholder"):
                continue

            outs.append(card)

    # IN
    for key, count in (new_counter - old_counter).items():

        cards = new_by_identity.get(key, [])

        for card in cards[:count]:

            # Never report placeholders as IN.
            if card.get("placeholder"):
                continue

            ins.append(card)

    return outs, ins


# ============================================================
# FORMAT CARD
# ============================================================

def format_card(card):
    name = card.get("name") or "?"
    overall = card.get("overall")

    if overall is None:
        overall_text = "?"
    else:
        overall_text = str(overall)

    finish = card.get("finish") or "UNKNOWN"

    return (
        f"<b>{escape(str(name))} "
        f"{escape(overall_text)}</b>"
        f"　·　"
        f"{escape(str(finish))}"
    )


def format_current_card(card):
    if card.get("placeholder"):
        return None

    name = card.get("name") or "?"
    overall = card.get("overall")

    if overall is None:
        overall_text = "?"
    else:
        overall_text = str(overall)

    finish = card.get("finish") or "UNKNOWN"

    return (
        f"<b>{escape(str(name))} "
        f"{escape(overall_text)}</b>"
        f"　·　"
        f"{escape(str(finish))}"
    )


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram_message(message):
    if not TELEGRAM_BOT_TOKEN:
        print("WARNING: TELEGRAM_BOT_TOKEN missing.")
        return False

    if not TELEGRAM_CHAT_ID:
        print("WARNING: TELEGRAM_CHAT_ID missing.")
        return False

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
        f"Telegram status: {response.status_code}"
    )

    if response.status_code != 200:
        print(response.text)

    return response.status_code == 200


# ============================================================
# BUILD TELEGRAM MESSAGE
# ============================================================

def build_telegram_message(previous_state, current_state):
    lines = []

    lines.append("<b>📋 FUT.GG Monitor</b>")

    categories = [
        "Heroes",
        "Holographics",
        "Season 1",
    ]

    for category_index, category in enumerate(categories):

        config = CATEGORY_CONFIG[category]

        if category_index > 0:
            lines.append("")
            lines.append("--------------------")
            lines.append("")

        lines.append(
            f"<b>{config['emoji']} {escape(category)}</b>"
        )

        old_category = previous_state.get(
            category,
            {}
        )

        old_current = old_category.get(
            "current",
            []
        )

        new_category = current_state.get(
            category,
            {}
        )

        new_current = new_category.get(
            "current",
            []
        )

        # ----------------------------------------------------
        # CHANGES
        # ----------------------------------------------------

        outs, ins = calculate_changes(
            old_current,
            new_current
        )

        # OUT first.
        for card in outs:

            lines.append(
                f"🔴 OUT — {format_card(card)}"
            )

        # IN second.
        for card in ins:

            lines.append(
                f"🟢 IN — {format_card(card)}"
            )

        # ----------------------------------------------------
        # CURRENT LINEUP
        # ----------------------------------------------------

        lines.append(
            "<b>📋 Current lineup 📋</b>"
        )

        for card in new_current:

            formatted = format_current_card(card)

            if formatted is None:
                continue

            # Current lineup should only mark newly entered
            # cards with green.
            identity = card_identity(card)

            is_new = any(
                card_identity(x) == identity
                for x in ins
            )

            if is_new:
                lines.append(
                    f"🟢 {formatted}"
                )
            else:
                lines.append(formatted)

    return "\n".join(lines)


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print("=" * 60)
    print("FUT.GG MONITOR")
    print(datetime.utcnow().isoformat())
    print("=" * 60)

    # --------------------------------------------------------
    # LOAD PREVIOUS STATE
    # --------------------------------------------------------

    previous_state = load_json(
        PLAYERS_FILE,
        {}
    )

    if not isinstance(previous_state, dict):
        previous_state = {}

    # --------------------------------------------------------
    # LOAD DATABASE
    # --------------------------------------------------------

    database = load_card_database()

    # --------------------------------------------------------
    # UPDATE HOLOGRAPHIC DATABASE
    # --------------------------------------------------------

    database = update_holographic_database(
        database
    )

    # --------------------------------------------------------
    # PARSE CURRENT CATEGORIES
    # --------------------------------------------------------

    current_state = {}

    for category, config in CATEGORY_CONFIG.items():

        result = parse_category(
            category,
            config,
            database,
            previous_state
        )

        if result is None:

            # Preserve previous state if the page cannot
            # be safely parsed.
            if category in previous_state:

                current_state[category] = previous_state[
                    category
                ]

            else:

                current_state[category] = {
                    "current": []
                }

        else:

            current_state[category] = {
                "current": result
            }

    # --------------------------------------------------------
    # TELEGRAM
    # --------------------------------------------------------

    message = build_telegram_message(
        previous_state,
        current_state
    )

    print()
    print("=" * 60)
    print("TELEGRAM MESSAGE")
    print("=" * 60)
    print(message)
    print("=" * 60)

    send_telegram_message(message)

    # --------------------------------------------------------
    # SAVE STATE
    # --------------------------------------------------------

    save_json(
        PLAYERS_FILE,
        current_state
    )

    print()
    print("DONE")


if __name__ == "__main__":
    main()