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

BASE_URL = "https://www.fut.gg"

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
# GENERIC HELPERS
# ============================================================

def safe_int(value):
    try:
        return int(str(value))
    except Exception:
        return None


def normalize_text(value):
    if not value:
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
# CORRECTED CARD KEY
# ============================================================

def card_key(card):
    item_id = str(
        card.get("item_id") or ""
    ).strip()

    if item_id:
        return f"item:{item_id}"

    key = player_key(
        card.get("name"),
        card.get("overall"),
        card.get("version")
    )

    return f"player:{key}"


# ============================================================
# JSON
# ============================================================

def load_json(path, default):
    if not os.path.exists(path):
        return default

    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    except Exception:
        print(f"WARNING: Could not read {path}")
        return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )


def load_players():
    return load_json(
        PLAYERS_FILE,
        {
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
        },
    )


def load_database():
    database = load_json(
        DATABASE_FILE,
        {
            "items": {},
            "players": {},
            "meta": {
                "version": 1,
                "source": "FUT.GG",
                "last_update": None,
            },
        },
    )

    database.setdefault("items", {})
    database.setdefault("players", {})
    database.setdefault("meta", {})

    return database


# ============================================================
# HTTP
# ============================================================

def fetch(url):
    print(f"Fetching: {url}")

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=30,
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
    """
    Example:

    Šašić - 89 - Base Hero
    Vialli - 89 - Base Hero
    Mora - 87 - Future Stars
    Player Card
    """

    alt = normalize_text(alt)

    if not alt:
        return None

    if alt.lower() == "player card":
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
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.I
        )

        if match:
            return match.group(1)

    return None


def extract_item_id(img):

    if not img:
        return None

    attributes_to_check = [
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

    for attribute in attributes_to_check:

        value = img.get(attribute)

        if isinstance(value, list):
            value = " ".join(value)

        item_id = extract_item_id_from_text(
            value
        )

        if item_id:
            return item_id

    parent = img.parent

    for _ in range(4):

        if not parent:
            break

        for attribute in parent.attrs:

            value = parent.get(
                attribute
            )

            if isinstance(value, list):
                value = " ".join(value)

            item_id = extract_item_id_from_text(
                value
            )

            if item_id:
                return item_id

        parent = parent.parent

    return None


# ============================================================
# HOLOGRAPHIC DATABASE
# ============================================================

def scan_holographic_database(database):

    print()
    print("=" * 60)
    print("Updating Holographic card database")
    print("=" * 60)

    pages = [
        (
            "PRISTINE HOLO",
            "https://www.fut.gg/holographic-cards/?finish=pristine",
        ),
        (
            "HOLO",
            "https://www.fut.gg/holographic-cards/?finish=holographic",
        ),
    ]

    discovered = 0

    for finish, url in pages:

        print()
        print(
            f"Scanning {finish}..."
        )

        html_text = fetch(url)

        if not html_text:
            continue

        soup = BeautifulSoup(
            html_text,
            "html.parser"
        )

        for img in soup.find_all("img"):

            alt = normalize_text(
                img.get("alt")
            )

            parsed = parse_card_alt(
                alt
            )

            if not parsed:
                continue

            if parsed.get("placeholder"):
                continue

            name = parsed["name"]
            overall = parsed["overall"]
            version = parsed["version"]

            item_id = extract_item_id(
                img
            )

            key = player_key(
                name,
                overall,
                version
            )

            entry = {
                "name": name,
                "overall": overall,
                "version": version,
                "finish": finish,
            }

            database["players"][key] = entry

            if item_id:

                database["items"][
                    str(item_id)
                ] = {
                    **entry,
                    "item_id": str(item_id),
                }

            discovered += 1

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

def get_finish_from_database(
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

        item_entry = database[
            "items"
        ].get(item_id)

        if item_entry:

            finish = item_entry.get(
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
        card.get("version"),
    )

    player_entry = database[
        "players"
    ].get(key)

    if player_entry:

        finish = player_entry.get(
            "finish"
        )

        if finish:
            return finish

    # --------------------------------------------------------
    # 3. PREVIOUS STATE
    # --------------------------------------------------------

    if previous_card:

        previous_finish = (
            previous_card.get("finish")
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

    text_nodes = soup.find_all(
        string=re.compile(
            r"Cheapest\s+grade",
            re.I
        )
    )

    for node in text_nodes:

        parent = node.parent

        if not parent:
            continue

        current = parent

        for depth in range(7):

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

        cards = candidate["cards"]

        real_cards = [
            parsed
            for _, parsed in cards
            if not parsed.get(
                "placeholder"
            )
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

        score = (
            10000
            - distance * 1000
            - extra * 100
            + len(real_cards) * 10
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

    return best["container"]


# ============================================================
# PREVIOUS CARD MATCH
# ============================================================

def same_card_identity(a, b):

    if not a or not b:
        return False

    item_a = str(
        a.get("item_id") or ""
    ).strip()

    item_b = str(
        b.get("item_id") or ""
    ).strip()

    if item_a and item_b:
        return item_a == item_b

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


# ============================================================
# EXTRACT LINEUP
# ============================================================

def extract_lineup(
    soup,
    expected_slots,
    database,
    previous_cards
):

    container = find_lineup_container(
        soup,
        expected_slots
    )

    if not container:

        print(
            "ERROR: Could not find "
            "Cheapest grade lineup"
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

        item_id = extract_item_id(
            img
        )

        parsed["item_id"] = item_id

        parsed_cards.append(
            parsed
        )

    print(
        "Images/cards detected in "
        "selected container: "
        f"{len(parsed_cards)}"
    )

    lineup = []

    for card in parsed_cards:

        if card.get(
            "placeholder"
        ):

            lineup.append(card)

        else:

            previous_card = (
                find_previous_matching_card(
                    card,
                    previous_cards
                )
            )

            finish = (
                get_finish_from_database(
                    card,
                    database,
                    previous_card
                )
            )

            card["finish"] = finish
            card["placeholder"] = False

            lineup.append(card)

        if len(lineup) >= expected_slots:
            break

    lineup = lineup[:expected_slots]

    real_cards = [
        card
        for card in lineup
        if not card.get(
            "placeholder"
        )
    ]

    print(
        f"Rendered lineup: "
        f"{len(real_cards)}/"
        f"{expected_slots} real cards"
    )

    for card in real_cards:

        print(
            f"- {card['name']} "
            f"{card['overall']} "
            f"{card['version']} "
            f"— ItemID "
            f"{card.get('item_id')} "
            f"— "
            f"{card.get('finish')}"
        )

    return lineup


# ============================================================
# OCCURRENCE IDENTITY
# ============================================================

def card_identity_for_occurrence(
    card
):

    item_id = str(
        card.get("item_id") or ""
    ).strip()

    if item_id:
        return f"item:{item_id}"

    return (
        f"fallback:"
        f"{normalize_name(card.get('name'))}|"
        f"{card.get('overall')}|"
        f"{normalize_text(card.get('version')).casefold()}|"
        f"{card.get('finish')}"
    )


def build_occurrence_counter(
    cards
):

    counter = Counter()

    for card in cards:

        if card.get(
            "placeholder"
        ):
            continue

        counter[
            card_identity_for_occurrence(
                card
            )
        ] += 1

    return counter


# ============================================================
# CHANGE DETECTION
# ============================================================

def detect_changes(
    previous,
    current
):

    previous_counter = (
        build_occurrence_counter(
            previous
        )
    )

    current_counter = (
        build_occurrence_counter(
            current
        )
    )

    changes = {
        "in": Counter(),
        "out": Counter(),
    }

    all_keys = (
        set(previous_counter)
        | set(current_counter)
    )

    for key in all_keys:

        old_count = (
            previous_counter.get(
                key,
                0
            )
        )

        new_count = (
            current_counter.get(
                key,
                0
            )
        )

        if new_count > old_count:

            changes["in"][key] = (
                new_count - old_count
            )

        elif old_count > new_count:

            changes["out"][key] = (
                old_count - new_count
            )

    return changes


# ============================================================
# MARK NEW CARDS
# ============================================================

def mark_current_lineup(
    current,
    changes
):

    in_counter = changes[
        "in"
    ].copy()

    result = []

    for card in current:

        if card.get(
            "placeholder"
        ):

            result.append(card)

            continue

        key = (
            card_identity_for_occurrence(
                card
            )
        )

        new_card = dict(card)

        if in_counter.get(
            key,
            0
        ) > 0:

            new_card["_new"] = True

            in_counter[key] -= 1

        else:

            new_card["_new"] = False

        result.append(
            new_card
        )

    return result


# ============================================================
# TELEGRAM CARD FORMAT
# ============================================================

def format_card(card):

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

    if finish == "PRISTINE HOLO":
        finish_text = "PRISTINE HOLO"

    elif finish == "HOLO":
        finish_text = "HOLO"

    elif finish == "BASE":
        finish_text = "BASE"

    else:
        finish_text = "UNKNOWN"

    new_marker = ""

    if card.get(
        "_new"
    ):
        new_marker = "🟢 "

    return (
        f"{new_marker}"
        f"<b>{name} {overall}</b>"
        f"　·　"
        f"{finish_text}"
    )


# ============================================================
# TELEGRAM MESSAGE
# ============================================================

def build_telegram_message(
    category_results
):

    lines = []

    lines.append(
        "<b>📋 FUT.GG Monitor</b>"
    )

    lines.append("")

    for index, result in enumerate(
        category_results
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

        out_cards = []

        remaining_out = (
            changes["out"].copy()
        )

        for old_card in previous:

            if old_card.get(
                "placeholder"
            ):
                continue

            key = (
                card_identity_for_occurrence(
                    old_card
                )
            )

            if remaining_out.get(
                key,
                0
            ) > 0:

                out_cards.append(
                    old_card
                )

                remaining_out[key] -= 1

        for card in out_cards:

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

        # ----------------------------------------------------
        # IN
        # ----------------------------------------------------

        in_cards = []

        remaining_in = (
            changes["in"].copy()
        )

        for new_card in current:

            if new_card.get(
                "placeholder"
            ):
                continue

            key = (
                card_identity_for_occurrence(
                    new_card
                )
            )

            if remaining_in.get(
                key,
                0
            ) > 0:

                in_cards.append(
                    new_card
                )

                remaining_in[key] -= 1

        for card in in_cards:

            lines.append(
                "🟢 IN — "
                + format_card(card)
            )

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
                format_card(card)
            )

        # ----------------------------------------------------
        # SEPARATOR
        # ----------------------------------------------------

        if index < (
            len(category_results) - 1
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
# SEND TELEGRAM
# ============================================================

def send_telegram(message):

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
    print("FUT.GG MONITOR")
    print("=" * 60)

    players = load_players()
    database = load_database()

    # --------------------------------------------------------
    # UPDATE DATABASE
    # --------------------------------------------------------

    database = (
        scan_holographic_database(
            database
        )
    )

    category_results = []

    # --------------------------------------------------------
    # SCAN CATEGORIES
    # --------------------------------------------------------

    for category, config in CATEGORIES.items():

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

        previous = (
            players.get(
                category,
                {}
            ).get(
                "current",
                []
            )
        )

        html_text = fetch(
            config["url"]
        )

        if not html_text:

            print(
                f"ERROR: Could not fetch "
                f"{category}"
            )

            current = previous

            changes = {
                "in": Counter(),
                "out": Counter(),
            }

            category_results.append(
                {
                    "category": category,
                    "emoji": config["emoji"],
                    "previous": previous,
                    "current": current,
                    "changes": changes,
                }
            )

            continue

        soup = BeautifulSoup(
            html_text,
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
                f"WARNING: Could not parse "
                f"{category}. "
                f"Previous state kept."
            )

            current = previous

        # ----------------------------------------------------
        # UNKNOWN FINISH
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
                "detected inside "
                "selected lineup."
            )

            for card in unknowns:

                print(
                    f"  UNKNOWN: "
                    f"{card.get('name')} "
                    f"{card.get('overall')} "
                    f"{card.get('version')} "
                    f"ItemID="
                    f"{card.get('item_id')}"
                )

        # ----------------------------------------------------
        # CHANGES
        # ----------------------------------------------------

        changes = detect_changes(
            previous,
            current
        )

        marked_current = (
            mark_current_lineup(
                current,
                changes
            )
        )

        # ----------------------------------------------------
        # SAVE CURRENT STATE
        # ----------------------------------------------------

        players.setdefault(
            category,
            {}
        )

        players[category][
            "previous"
        ] = previous

        players[category][
            "current"
        ] = current

        # ----------------------------------------------------
        # TELEGRAM RESULT
        # ----------------------------------------------------

        category_results.append(
            {
                "category": category,
                "emoji": config["emoji"],
                "previous": previous,
                "current": marked_current,
                "changes": changes,
            }
        )

    # --------------------------------------------------------
    # SAVE DATABASE
    # --------------------------------------------------------

    database["meta"][
        "last_update"
    ] = datetime.now(
        timezone.utc
    ).isoformat()

    save_json(
        DATABASE_FILE,
        database
    )

    save_json(
        PLAYERS_FILE,
        players
    )

    # --------------------------------------------------------
    # TELEGRAM
    # --------------------------------------------------------

    message = (
        build_telegram_message(
            category_results
        )
    )

    print()
    print("=" * 60)
    print("TELEGRAM MESSAGE")
    print("=" * 60)

    print(message)

    print("=" * 60)

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