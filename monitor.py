import os
import re
import json
import html
import requests
from bs4 import BeautifulSoup
from collections import Counter
from datetime import datetime, timezone


# ============================================================
# CONFIG
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

CATEGORIES = {
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
DATABASE_FILE = "card_database.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


# ============================================================
# KNOWN FINISHES
# ============================================================
#
# Questi sono finish già identificati in precedenza.
#
# IMPORTANTE:
# Non vengono usati per inventare nuovi finish.
# Servono solo come base iniziale del database.
#

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
# HELPERS
# ============================================================

def safe_int(value):
    try:
        return int(str(value))
    except Exception:
        return None


def normalize_text(value):
    if value is None:
        return ""

    value = html.unescape(str(value))
    value = value.replace("\xa0", " ")
    value = re.sub(r"\s+", " ", value)

    return value.strip()


def normalize_name(value):
    return normalize_text(value).casefold()


def player_key(name, overall, version):
    return (
        f"{normalize_name(name)}|"
        f"{safe_int(overall) or 0}|"
        f"{normalize_text(version).casefold()}"
    )


# ============================================================
# JSON
# ============================================================

def save_json(path, data):
    with open(
        path,
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )


def load_players():

    default_data = {
        "Heroes": {
            "current": [],
            "previous": [],
        },
        "Holographics": {
            "current": [],
            "previous": [],
        },
        "Season 1": {
            "current": [],
            "previous": [],
        },
    }

    if not os.path.exists(
        PLAYERS_FILE
    ):
        return default_data

    try:
        with open(
            PLAYERS_FILE,
            "r",
            encoding="utf-8"
        ) as f:
            data = json.load(f)

    except Exception as e:

        print(
            f"WARNING: Could not read "
            f"{PLAYERS_FILE}: {e}"
        )

        return default_data

    # --------------------------------------------------------
    # NORMAL DICT
    # --------------------------------------------------------

    if isinstance(data, dict):

        for category in default_data:

            if category not in data:

                data[category] = {
                    "current": [],
                    "previous": [],
                }

                continue

            # Old format:
            #
            # "Heroes": [...]
            #
            if isinstance(
                data[category],
                list
            ):

                data[category] = {
                    "current": data[category],
                    "previous": [],
                }

            elif not isinstance(
                data[category],
                dict
            ):

                data[category] = {
                    "current": [],
                    "previous": [],
                }

            data[category].setdefault(
                "current",
                []
            )

            data[category].setdefault(
                "previous",
                []
            )

        return data

    # --------------------------------------------------------
    # ENTIRE FILE IS A LIST
    # --------------------------------------------------------

    if isinstance(data, list):

        print(
            "WARNING: players.json is "
            "a list."
        )

        print(
            "Migrating to new structure..."
        )

        return {
            "Heroes": {
                "current": data,
                "previous": [],
            },
            "Holographics": {
                "current": [],
                "previous": [],
            },
            "Season 1": {
                "current": [],
                "previous": [],
            },
        }

    print(
        "WARNING: Invalid players.json."
    )

    return default_data


def load_database():

    default_database = {
        "items": {},
        "players": {},
        "meta": {
            "version": 1,
            "source": "FUT.GG",
            "last_update": None,
        },
    }

    if not os.path.exists(
        DATABASE_FILE
    ):
        return default_database

    try:

        with open(
            DATABASE_FILE,
            "r",
            encoding="utf-8"
        ) as f:
            database = json.load(f)

    except Exception as e:

        print(
            f"WARNING: Could not read "
            f"{DATABASE_FILE}: {e}"
        )

        return default_database

    if not isinstance(
        database,
        dict
    ):
        return default_database

    database.setdefault(
        "items",
        {}
    )

    database.setdefault(
        "players",
        {}
    )

    database.setdefault(
        "meta",
        {}
    )

    return database


# ============================================================
# HTTP
# ============================================================

def fetch(url):

    print(
        f"Fetching: {url}"
    )

    try:

        response = requests.get(
            url,
            headers=HEADERS,
            timeout=30
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

    except Exception as e:

        print(
            f"ERROR fetching {url}: {e}"
        )

        return None


# ============================================================
# PARSE CARD ALT
# ============================================================

def parse_card_alt(alt):

    alt = normalize_text(alt)

    if not alt:
        return None

    # Player Card = empty slot
    if alt.casefold() == "player card":

        return {
            "placeholder": True
        }

    match = re.match(
        r"^(.*?)\s*-\s*(\d+)\s*-\s*(.+)$",
        alt
    )

    if not match:
        return None

    name = normalize_text(
        match.group(1)
    )

    overall = safe_int(
        match.group(2)
    )

    version = normalize_text(
        match.group(3)
    )

    if not name:
        return None

    if overall is None:
        return None

    if not version:
        return None

    return {
        "name": name,
        "overall": overall,
        "version": version,
        "placeholder": False,
    }


# ============================================================
# ITEM ID
# ============================================================

def extract_item_id_from_text(text):

    if not text:
        return None

    text = str(text)

    patterns = [

        r"item[_-]?id[=/:\-_]+(\d+)",

        r"itemId[=/:\-_]+(\d+)",

        r"item%5[Ff]id[=/:\-_]+(\d+)",

        r"/(\d{5,8})(?:[/?#]|$)",

    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.I
        )

        if match:

            value = match.group(1)

            # Avoid obvious non-item IDs
            if len(value) >= 5:
                return value

    return None


def extract_item_id(img):

    if not img:
        return None

    attributes = [
        "src",
        "data-src",
        "data-original",
        "data-image",
        "data-url",
        "alt",
        "title",
        "id",
        "class",
    ]

    # Image attributes
    for attribute in attributes:

        value = img.get(
            attribute
        )

        if isinstance(
            value,
            list
        ):
            value = " ".join(
                value
            )

        item_id = (
            extract_item_id_from_text(
                value
            )
        )

        if item_id:
            return item_id

    # Parent attributes
    parent = img.parent

    for _ in range(5):

        if not parent:
            break

        for attribute in parent.attrs:

            value = parent.get(
                attribute
            )

            if isinstance(
                value,
                list
            ):
                value = " ".join(
                    value
                )

            item_id = (
                extract_item_id_from_text(
                    value
                )
            )

            if item_id:
                return item_id

        parent = parent.parent

    return None


# ============================================================
# DATABASE SEED
# ============================================================

def seed_known_finishes(
    database
):

    changed = False

    for item_id, finish in (
        KNOWN_FINISHES.items()
    ):

        existing = database[
            "items"
        ].get(
            item_id
        )

        if not existing:

            database[
                "items"
            ][item_id] = {
                "item_id": item_id,
                "finish": finish,
                "source": "known",
            }

            changed = True

        elif not existing.get(
            "finish"
        ):

            existing[
                "finish"
            ] = finish

            changed = True

    if changed:

        print(
            "Known card finishes "
            "added to database."
        )

    return database


# ============================================================
# HOLOGRAPHIC DATABASE
# ============================================================
#
# FUT.GG's Holographic page is dynamic and
# does not expose all cards as simple <img> elements.
#
# Therefore:
# - we attempt to read explicit card data;
# - if nothing is found, we DO NOT destroy the database;
# - we never convert UNKNOWN into BASE.
#

def scan_holographic_database(
    database
):

    print()
    print("=" * 60)
    print(
        "Updating Holographic database"
    )
    print("=" * 60)

    pages = [
        (
            "PRISTINE HOLO",
            "https://www.fut.gg/"
            "holographic-cards/"
            "?finish=pristine",
        ),
        (
            "HOLO",
            "https://www.fut.gg/"
            "holographic-cards/"
            "?finish=holographic",
        ),
    ]

    discovered = 0

    for finish, url in pages:

        print()
        print(
            f"Scanning {finish}..."
        )

        page = fetch(
            url
        )

        if not page:
            continue

        soup = BeautifulSoup(
            page,
            "html.parser"
        )

        page_found = 0

        # ----------------------------------------------------
        # 1. Images with card-like ALT
        # ----------------------------------------------------

        for img in soup.find_all(
            "img"
        ):

            parsed = parse_card_alt(
                img.get("alt")
            )

            if not parsed:
                continue

            if parsed.get(
                "placeholder"
            ):
                continue

            item_id = extract_item_id(
                img
            )

            key = player_key(
                parsed["name"],
                parsed["overall"],
                parsed["version"]
            )

            entry = {
                "name": parsed["name"],
                "overall": parsed["overall"],
                "version": parsed["version"],
                "finish": finish,
                "source": "FUT.GG",
            }

            database[
                "players"
            ][key] = entry

            if item_id:

                database[
                    "items"
                ][str(item_id)] = {
                    **entry,
                    "item_id": str(item_id),
                }

            page_found += 1

        # ----------------------------------------------------
        # 2. Links containing card-like text
        # ----------------------------------------------------

        for link in soup.find_all(
            "a"
        ):

            text = normalize_text(
                link.get_text(
                    " ",
                    strip=True
                )
            )

            if not text:
                continue

            # We only try short player-like strings
            # to avoid processing the whole page.
            if len(text) > 250:
                continue

            match = re.search(
                r"([A-Za-zÀ-ÿŠšŽžÄäÖöÜüß'’\-]+)"
                r"\s+(\d{2})\b",
                text
            )

            if not match:
                continue

            # This is supplemental only.
            # We do NOT overwrite an exact item record.
            name = normalize_text(
                match.group(1)
            )

            overall = safe_int(
                match.group(2)
            )

            if not name or overall is None:
                continue

            # We don't know the exact version from
            # this text reliably, so skip it.
            # This prevents false database entries.

        discovered += page_found

        print(
            f"  Records found on page: "
            f"{page_found}"
        )

    print()
    print(
        f"Holographic records discovered: "
        f"{discovered}"
    )

    print(
        f"Database items: "
        f"{len(database['items'])}"
    )

    print(
        f"Database players: "
        f"{len(database['players'])}"
    )

    return database


# ============================================================
# FINISH RESOLUTION
# ============================================================

def get_finish(
    card,
    database,
    previous_card=None
):

    item_id = str(
        card.get("item_id") or ""
    ).strip()

    # --------------------------------------------------------
    # 1. EXACT ITEM ID
    # --------------------------------------------------------

    if item_id:

        item = database[
            "items"
        ].get(
            item_id
        )

        if item:

            finish = item.get(
                "finish"
            )

            if finish:
                return finish

    # --------------------------------------------------------
    # 2. PLAYER KEY
    # --------------------------------------------------------

    key = player_key(
        card.get("name"),
        card.get("overall"),
        card.get("version")
    )

    player = database[
        "players"
    ].get(
        key
    )

    if player:

        finish = player.get(
            "finish"
        )

        if finish:
            return finish

    # --------------------------------------------------------
    # 3. PREVIOUS STATE
    # --------------------------------------------------------

    if previous_card:

        previous_finish = (
            previous_card.get(
                "finish"
            )
        )

        if (
            previous_finish
            and previous_finish != "UNKNOWN"
        ):
            return previous_finish

    # --------------------------------------------------------
    # 4. UNKNOWN
    # --------------------------------------------------------

    return "UNKNOWN"


# ============================================================
# FIND CHEAPEST GRADE
# ============================================================

def find_lineup_container(
    soup,
    expected_slots
):

    candidates = []

    nodes = soup.find_all(
        string=re.compile(
            r"Cheapest\s+grade",
            re.I
        )
    )

    for node in nodes:

        current = node.parent

        for depth in range(8):

            if not current:
                break

            images = current.find_all(
                "img"
            )

            cards = []

            for img in images:

                parsed = parse_card_alt(
                    img.get("alt")
                )

                if parsed:

                    cards.append(
                        (
                            img,
                            parsed
                        )
                    )

            # Exact expected number is best
            if len(cards) >= expected_slots:

                candidates.append(
                    {
                        "container": current,
                        "cards": cards,
                        "depth": depth,
                    }
                )

            current = current.parent

    if not candidates:
        return None

    scored = []

    for candidate in candidates:

        cards = candidate[
            "cards"
        ]

        distance = abs(
            len(cards)
            - expected_slots
        )

        extra = max(
            0,
            len(cards)
            - expected_slots
        )

        real_cards = sum(
            1
            for _, card in cards
            if not card.get(
                "placeholder"
            )
        )

        score = (
            10000
            - distance * 1000
            - extra * 100
            + real_cards * 10
        )

        scored.append(
            (
                score,
                candidate
            )
        )

    scored.sort(
        key=lambda x: x[0],
        reverse=True
    )

    best_score, best = scored[0]

    print(
        f"Cheapest grade matches found: "
        f"{len(candidates)}"
    )

    print(
        f"Selected lineup candidate: "
        f"{len(best['cards'])} cards "
        f"(score {best_score})"
    )

    return best[
        "container"
    ]


# ============================================================
# CARD IDENTITY
# ============================================================

def same_card_identity(
    a,
    b
):

    if not a or not b:
        return False

    item_a = str(
        a.get("item_id") or ""
    ).strip()

    item_b = str(
        b.get("item_id") or ""
    ).strip()

    # Exact Item ID
    if item_a and item_b:
        return item_a == item_b

    # Fallback
    return (
        normalize_name(
            a.get("name")
        )
        == normalize_name(
            b.get("name")
        )
        and safe_int(
            a.get("overall")
        )
        == safe_int(
            b.get("overall")
        )
        and normalize_text(
            a.get("version")
        ).casefold()
        == normalize_text(
            b.get("version")
        ).casefold()
    )


def find_previous_matching_card(
    card,
    previous_cards
):

    for previous in previous_cards:

        if previous.get(
            "placeholder"
        ):
            continue

        if same_card_identity(
            card,
            previous
        ):
            return previous

    return None


def occurrence_identity(
    card
):

    item_id = str(
        card.get("item_id") or ""
    ).strip()

    if item_id:
        return (
            f"item:{item_id}"
        )

    return (
        "fallback:"
        f"{normalize_name(card.get('name'))}|"
        f"{card.get('overall')}|"
        f"{normalize_text(card.get('version')).casefold()}|"
        f"{card.get('finish')}"
    )


# ============================================================
# EXTRACT LINEUP
# ============================================================

def extract_lineup(
    soup,
    expected_slots,
    database,
    previous
):

    container = find_lineup_container(
        soup,
        expected_slots
    )

    if not container:

        print(
            "ERROR: Cheapest grade "
            "lineup not found."
        )

        return None

    parsed_cards = []

    for img in container.find_all(
        "img"
    ):

        parsed = parse_card_alt(
            img.get("alt")
        )

        if not parsed:
            continue

        if parsed.get(
            "placeholder"
        ):

            parsed_cards.append(
                {
                    "placeholder": True
                }
            )

            continue

        parsed[
            "item_id"
        ] = extract_item_id(
            img
        )

        previous_card = (
            find_previous_matching_card(
                parsed,
                previous
            )
        )

        parsed[
            "finish"
        ] = get_finish(
            parsed,
            database,
            previous_card
        )

        parsed[
            "placeholder"
        ] = False

        parsed_cards.append(
            parsed
        )

    print(
        "Images/cards detected in "
        "selected container: "
        f"{len(parsed_cards)}"
    )

    # --------------------------------------------------------
    # Take only expected slots
    # --------------------------------------------------------

    lineup = parsed_cards[
        :expected_slots
    ]

    # --------------------------------------------------------
    # Logging
    # --------------------------------------------------------

    real_count = sum(
        1
        for card in lineup
        if not card.get(
            "placeholder"
        )
    )

    print(
        f"Rendered lineup: "
        f"{real_count}/"
        f"{expected_slots} real cards"
    )

    for card in lineup:

        if card.get(
            "placeholder"
        ):
            continue

        print(
            f"- {card.get('name')} "
            f"{card.get('overall')} "
            f"{card.get('version')} "
            f"— ItemID "
            f"{card.get('item_id')} "
            f"— "
            f"{card.get('finish')}"
        )

    return lineup


# ============================================================
# CHANGE DETECTION
# ============================================================

def counter_for(
    cards
):

    counter = Counter()

    for card in cards:

        if card.get(
            "placeholder"
        ):
            continue

        counter[
            occurrence_identity(
                card
            )
        ] += 1

    return counter


def detect_changes(
    previous,
    current
):

    old = counter_for(
        previous
    )

    new = counter_for(
        current
    )

    changes = {
        "in": Counter(),
        "out": Counter(),
    }

    for key in (
        set(old) | set(new)
    ):

        old_count = old.get(
            key,
            0
        )

        new_count = new.get(
            key,
            0
        )

        if new_count > old_count:

            changes[
                "in"
            ][key] = (
                new_count
                - old_count
            )

        elif old_count > new_count:

            changes[
                "out"
            ][key] = (
                old_count
                - new_count
            )

    return changes


# ============================================================
# MARK NEW
# ============================================================

def mark_new_cards(
    current,
    changes
):

    remaining = changes[
        "in"
    ].copy()

    result = []

    for card in current:

        card = dict(
            card
        )

        if card.get(
            "placeholder"
        ):

            card[
                "_new"
            ] = False

            result.append(
                card
            )

            continue

        key = occurrence_identity(
            card
        )

        if remaining.get(
            key,
            0
        ) > 0:

            card[
                "_new"
            ] = True

            remaining[
                key
            ] -= 1

        else:

            card[
                "_new"
            ] = False

        result.append(
            card
        )

    return result


# ============================================================
# TELEGRAM FORMAT
# ============================================================

def format_card(
    card
):

    name = html.escape(
        str(
            card.get(
                "name",
                "Unknown"
            )
        )
    )

    overall = card.get(
        "overall",
        "?"
    )

    finish = card.get(
        "finish",
        "UNKNOWN"
    )

    marker = ""

    if card.get(
        "_new"
    ):
        marker = "🟢 "

    return (
        f"{marker}"
        f"<b>{name} {overall}</b>"
        f"　·　"
        f"{finish}"
    )


def build_telegram_message(
    results
):

    lines = []

    lines.append(
        "<b>📋 FUT.GG Monitor</b>"
    )

    lines.append("")

    for index, result in enumerate(
        results
    ):

        category = result[
            "category"
        ]

        emoji = result[
            "emoji"
        ]

        previous = result[
            "previous"
        ]

        current = result[
            "current"
        ]

        changes = result[
            "changes"
        ]

        lines.append(
            f"<b>{emoji} "
            f"{html.escape(category)}"
            f"</b>"
        )

        lines.append("")

        # ----------------------------------------------------
        # OUT
        # ----------------------------------------------------

        remaining_out = (
            changes["out"].copy()
        )

        for card in previous:

            if card.get(
                "placeholder"
            ):
                continue

            key = occurrence_identity(
                card
            )

            if remaining_out.get(
                key,
                0
            ) > 0:

                name = html.escape(
                    str(
                        card.get(
                            "name",
                            "Unknown"
                        )
                    )
                )

                overall = card.get(
                    "overall",
                    "?"
                )

                finish = card.get(
                    "finish",
                    "UNKNOWN"
                )

                lines.append(
                    f"🔴 OUT — "
                    f"<b>{name} {overall}</b>"
                    f"　·　{finish}"
                )

                remaining_out[
                    key
                ] -= 1

        # ----------------------------------------------------
        # IN
        # ----------------------------------------------------

        remaining_in = (
            changes["in"].copy()
        )

        for card in current:

            if card.get(
                "placeholder"
            ):
                continue

            key = occurrence_identity(
                card
            )

            if remaining_in.get(
                key,
                0
            ) > 0:

                lines.append(
                    "🟢 IN — "
                    + format_card(
                        card
                    )
                )

                remaining_in[
                    key
                ] -= 1

        # ----------------------------------------------------
        # CURRENT LINEUP
        # ----------------------------------------------------

        lines.append(
            "<b>📋 Current lineup 📋</b>"
        )

        for card in current:

            if card.get(
                "placeholder"
            ):
                continue

            lines.append(
                format_card(
                    card
                )
            )

        # ----------------------------------------------------
        # SEPARATOR
        # ----------------------------------------------------

        if index < (
            len(results) - 1
        ):

            lines.append("")
            lines.append(
                "--------------------"
            )
            lines.append("")

    return "\n".join(
        lines
    )


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(
    message
):

    if not TELEGRAM_BOT_TOKEN:

        print(
            "WARNING: "
            "TELEGRAM_BOT_TOKEN missing"
        )

        return False

    if not TELEGRAM_CHAT_ID:

        print(
            "WARNING: "
            "TELEGRAM_CHAT_ID missing"
        )

        return False

    url = (
        "https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}"
        "/sendMessage"
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

        print(
            f"Telegram status: "
            f"{response.status_code}"
        )

        if not response.ok:

            print(
                response.text
            )

        return response.ok

    except Exception as e:

        print(
            f"Telegram error: {e}"
        )

        return False


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 60)
    print(
        "FUT.GG MONITOR"
    )
    print("=" * 60)

    players = load_players()

    database = load_database()

    # Add known finishes without
    # deleting anything already learned.
    database = seed_known_finishes(
        database
    )

    # Try to update Holographic DB.
    # If FUT.GG doesn't expose cards,
    # the existing database is preserved.
    database = (
        scan_holographic_database(
            database
        )
    )

    results = []

    # ========================================================
    # CATEGORIES
    # ========================================================

    for category, config in (
        CATEGORIES.items()
    ):

        print()

        print(
            f"Checking "
            f"{config['emoji']} "
            f"{category.upper()} "
            f"({config['slots']} players)..."
        )

        print(
            "=" * 60
        )

        # ----------------------------------------------------
        # PREVIOUS
        # ----------------------------------------------------

        category_data = players.get(
            category,
            {}
        )

        if isinstance(
            category_data,
            list
        ):

            previous = (
                category_data
            )

        elif isinstance(
            category_data,
            dict
        ):

            previous = (
                category_data.get(
                    "current",
                    []
                )
            )

        else:

            previous = []

        if not isinstance(
            previous,
            list
        ):
            previous = []

        # ----------------------------------------------------
        # FETCH
        # ----------------------------------------------------

        page = fetch(
            config["url"]
        )

        if not page:

            print(
                "Could not download "
                f"{category}. "
                "Keeping previous state."
            )

            current = previous

        else:

            soup = BeautifulSoup(
                page,
                "html.parser"
            )

            current = extract_lineup(
                soup,
                config["slots"],
                database,
                previous
            )

            if current is None:

                print(
                    "Could not parse "
                    f"{category}. "
                    "Keeping previous state."
                )

                current = previous

        # ----------------------------------------------------
        # CHANGES
        # ----------------------------------------------------

        changes = detect_changes(
            previous,
            current
        )

        marked_current = (
            mark_new_cards(
                current,
                changes
            )
        )

        # ----------------------------------------------------
        # UNKNOWN WARNING
        # ----------------------------------------------------

        unknowns = [
            card
            for card in current
            if not card.get(
                "placeholder"
            )
            and card.get(
                "finish"
            ) == "UNKNOWN"
        ]

        if unknowns:

            print()

            print(
                "WARNING: Unknown finish "
                "detected:"
            )

            for card in unknowns:

                print(
                    f"  "
                    f"{card.get('name')} "
                    f"{card.get('overall')} "
                    f"{card.get('version')} "
                    f"ItemID="
                    f"{card.get('item_id')}"
                )

        # ----------------------------------------------------
        # SAVE STATE
        # ----------------------------------------------------

        players[
            category
        ] = {
            "previous": previous,
            "current": current,
        }

        # ----------------------------------------------------
        # RESULT
        # ----------------------------------------------------

        results.append(
            {
                "category": category,
                "emoji": config["emoji"],
                "previous": previous,
                "current": marked_current,
                "changes": changes,
            }
        )

    # ========================================================
    # SAVE
    # ========================================================

    database[
        "meta"
    ][
        "last_update"
    ] = datetime.now(
        timezone.utc
    ).isoformat()

    save_json(
        PLAYERS_FILE,
        players
    )

    save_json(
        DATABASE_FILE,
        database
    )

    # ========================================================
    # TELEGRAM
    # ========================================================

    message = build_telegram_message(
        results
    )

    print()
    print("=" * 60)
    print(
        "TELEGRAM MESSAGE"
    )
    print("=" * 60)

    print(message)

    print("=" * 60)

    send_telegram(
        message
    )

    print()
    print(
        "DONE"
    )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()