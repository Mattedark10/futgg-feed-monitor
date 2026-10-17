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

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

PLAYERS_FILE = os.path.join(BASE_DIR, "players.json")
DATABASE_FILE = os.path.join(BASE_DIR, "card_database.json")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/140.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

TIMEOUT = 30


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


# ============================================================
# KNOWN FINISHES
# ============================================================

KNOWN_FINISHES = {
    # PRISTINE HOLO
    "67335170": "PRISTINE HOLO",
    "67114537": "PRISTINE HOLO",
    "67335237": "PRISTINE HOLO",
    "67371135": "PRISTINE HOLO",
    "67186651": "PRISTINE HOLO",
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
    "50590935": "BASE",
}


VALID_FINISHES = {
    "BASE",
    "HOLO",
    "PRISTINE HOLO",
}


# ============================================================
# JSON
# ============================================================

def load_json(path, default):
    try:
        if not os.path.exists(path):
            return default

        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    except Exception as e:
        print(f"Error loading {path}: {e}")
        return default


def save_json(path, data):
    tmp = path + ".tmp"

    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )

    os.replace(tmp, path)


# ============================================================
# PLAYERS
# ============================================================

def load_players():
    data = load_json(
        PLAYERS_FILE,
        {}
    )

    if not isinstance(data, dict):
        data = {}

    for category in CATEGORIES:

        if category not in data:
            data[category] = {
                "current": [],
                "previous": [],
            }

        elif isinstance(data[category], list):

            data[category] = {
                "current": data[category],
                "previous": [],
            }

        elif isinstance(data[category], dict):

            if not isinstance(
                data[category].get("current"),
                list
            ):
                data[category]["current"] = []

            if not isinstance(
                data[category].get("previous"),
                list
            ):
                data[category]["previous"] = []

        else:

            data[category] = {
                "current": [],
                "previous": [],
            }

    return data


# ============================================================
# DATABASE
# ============================================================

def load_database():
    data = load_json(
        DATABASE_FILE,
        {}
    )

    if not isinstance(data, dict):
        data = {}

    if not isinstance(
        data.get("items"),
        dict
    ):
        data["items"] = {}

    if not isinstance(
        data.get("players"),
        dict
    ):
        data["players"] = {}

    if not isinstance(
        data.get("meta"),
        dict
    ):
        data["meta"] = {}

    return data


def save_database(database):
    database.setdefault(
        "meta",
        {}
    )

    database["meta"][
        "last_update"
    ] = datetime.utcnow().isoformat()

    save_json(
        DATABASE_FILE,
        database
    )


def seed_known_finishes(database):
    added = 0

    for item_id, finish in KNOWN_FINISHES.items():

        item_id = str(item_id)

        if item_id not in database["items"]:

            database["items"][item_id] = {
                "finish": finish,
                "source": "known"
            }

            added += 1

    print(
        f"Known card finishes added to database: "
        f"{added}"
    )


# ============================================================
# HTTP
# ============================================================

def fetch_page(url):
    print(
        f"Fetching: {url}"
    )

    response = requests.get(
        url,
        headers=HEADERS,
        timeout=TIMEOUT
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
# ITEM ID
# ============================================================

ITEM_ID_PATTERN = re.compile(
    r"futgg-player-item-card/27-(\d+)",
    re.IGNORECASE
)


def extract_item_ids_from_text(text):
    if not text:
        return set()

    return set(
        ITEM_ID_PATTERN.findall(text)
    )


def extract_item_id(img):
    if not img:
        return None

    # Cerca in tutti gli attributi
    for value in img.attrs.values():

        if isinstance(value, list):
            values = value
        else:
            values = [value]

        for v in values:

            match = ITEM_ID_PATTERN.search(
                str(v)
            )

            if match:
                return match.group(1)

    # Fallback
    match = ITEM_ID_PATTERN.search(
        str(img)
    )

    if match:
        return match.group(1)

    return None


def is_player_card_image(img):
    """
    TRUE solamente per le immagini delle vere card FUT.GG.

    Questo è fondamentale perché la pagina contiene anche:
      - FC Coin
      - Gallery Token
      - icone
      - immagini decorative
    """

    if not img:
        return False

    for value in img.attrs.values():

        if isinstance(value, list):
            values = value
        else:
            values = [value]

        for v in values:

            if ITEM_ID_PATTERN.search(
                str(v)
            ):
                return True

    return bool(
        ITEM_ID_PATTERN.search(
            str(img)
        )
    )


# ============================================================
# HOLOGRAPHIC DATABASE
# ============================================================

def scan_holographic_database(database):

    print("\n" + "=" * 60)
    print("Updating Holographic database")
    print("=" * 60)

    pristine_url = (
        "https://www.fut.gg/holographic-cards/?finish=pristine"
    )

    holo_url = (
        "https://www.fut.gg/holographic-cards/?finish=holographic"
    )

    pristine_ids = set()
    holo_ids = set()

    # --------------------------------------------------------
    # PRISTINE
    # --------------------------------------------------------

    print("\nScanning PRISTINE HOLO...")

    try:

        html = fetch_page(
            pristine_url
        )

        pristine_ids = extract_item_ids_from_text(
            html
        )

        print(
            f"  Records found on page: "
            f"{len(pristine_ids)}"
        )

    except Exception as e:

        print(
            f"  Error: {e}"
        )

    # --------------------------------------------------------
    # HOLO
    # --------------------------------------------------------

    print("\nScanning HOLO...")

    try:

        html = fetch_page(
            holo_url
        )

        holo_ids = extract_item_ids_from_text(
            html
        )

        print(
            f"  Records found on page: "
            f"{len(holo_ids)}"
        )

    except Exception as e:

        print(
            f"  Error: {e}"
        )

    # --------------------------------------------------------
    # UPDATE
    # --------------------------------------------------------

    for item_id in pristine_ids:

        database["items"][
            str(item_id)
        ] = {
            "finish": "PRISTINE HOLO",
            "source": "FUT.GG holographic database"
        }

    for item_id in holo_ids:

        item_id = str(item_id)

        if item_id in pristine_ids:
            continue

        database["items"][
            item_id
        ] = {
            "finish": "HOLO",
            "source": "FUT.GG holographic database"
        }

    print(
        f"\nHolographic records discovered: "
        f"{len(pristine_ids) + len(holo_ids)}"
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
# TEXT / CARD INFO
# ============================================================

def clean_text(text):
    if not text:
        return ""

    return re.sub(
        r"\s+",
        " ",
        text
    ).strip()


def extract_overall_from_text(text):
    if not text:
        return None

    # Cerchiamo un rating 80-99
    matches = re.findall(
        r"\b(8\d|9\d)\b",
        text
    )

    if matches:

        try:
            return int(matches[-1])
        except Exception:
            pass

    return None


def extract_name_from_text(
    text,
    overall=None
):
    """
    Cerca un nome plausibile nel testo della card.

    Evita:
      FC Coin
      Gallery Token
      Player Card
    """

    if not text:
        return None

    text = clean_text(text)

    banned = {
        "fc coin",
        "gallery token",
        "player card",
        "cheapest grade",
        "add players",
    }

    # --------------------------------------------------------
    # Se abbiamo overall, prova:
    #
    # Nome 89
    # --------------------------------------------------------

    if overall is not None:

        pattern = re.compile(
            r"([A-Za-zÀ-ÿŠšŽžĆćĐđÄäÖöÜüß'’\-]+"
            r"(?:\s+[A-Za-zÀ-ÿŠšŽžĆćĐđÄäÖöÜüß'’\-]+){0,3})"
            r"\s+"
            + str(overall)
            + r"\b"
        )

        matches = pattern.findall(
            text
        )

        if matches:

            for name in reversed(matches):

                name = clean_text(name)

                if name.lower() not in banned:
                    return name

    return None


# ============================================================
# CARD CONTAINER
# ============================================================

def get_card_container(img):
    """
    Risale dal <img> fino al contenitore della singola card.

    Cerchiamo il primo antenato che contiene:
      - una sola vera player-card image
      - testo utile
    """

    current = img

    for _ in range(10):

        if not current:
            break

        player_images = [
            x
            for x in current.find_all("img")
            if is_player_card_image(x)
        ]

        # Il contenitore ideale contiene una sola card.
        if len(player_images) == 1:

            text = clean_text(
                current.get_text(
                    " ",
                    strip=True
                )
            )

            if text:

                return current

        current = current.parent

    return img.parent


# ============================================================
# PARSE CARD
# ============================================================

def parse_card(img):
    """
    Estrae una singola vera card.
    """

    item_id = extract_item_id(
        img
    )

    if not item_id:
        return None

    container = get_card_container(
        img
    )

    text = ""

    if container:

        text = clean_text(
            container.get_text(
                " ",
                strip=True
            )
        )

    # --------------------------------------------------------
    # OVERALL
    # --------------------------------------------------------

    overall = extract_overall_from_text(
        text
    )

    # --------------------------------------------------------
    # NAME
    # --------------------------------------------------------

    name = extract_name_from_text(
        text,
        overall
    )

    # --------------------------------------------------------
    # VERSION
    # --------------------------------------------------------

    version = None

    # Proviamo a ricavare la versione dal testo.
    # Non la usiamo per determinare il finish.

    if name and overall:

        pattern = re.escape(
            name
        ) + r"\s+" + str(overall)

        match = re.search(
            pattern + r"\s+(.+)",
            text,
            re.IGNORECASE
        )

        if match:

            possible = clean_text(
                match.group(1)
            )

            if possible:
                version = possible

    # --------------------------------------------------------
    # FINISH
    # --------------------------------------------------------

    return {
        "name": name,
        "overall": overall,
        "version": version,
        "item_id": str(item_id),
    }


# ============================================================
# FINISH
# ============================================================

def get_finish(
    item_id,
    previous_card,
    database
):

    item_id = str(
        item_id or ""
    ).strip()

    # --------------------------------------------------------
    # DATABASE
    # --------------------------------------------------------

    record = database["items"].get(
        item_id
    )

    if isinstance(record, dict):

        finish = record.get(
            "finish"
        )

        if finish in VALID_FINISHES:
            return finish

    # --------------------------------------------------------
    # KNOWN
    # --------------------------------------------------------

    if item_id in KNOWN_FINISHES:
        return KNOWN_FINISHES[item_id]

    # --------------------------------------------------------
    # PREVIOUS
    # --------------------------------------------------------

    if previous_card:

        finish = previous_card.get(
            "finish"
        )

        if finish in VALID_FINISHES:
            return finish

    # --------------------------------------------------------
    # NEVER ASSUME BASE
    # --------------------------------------------------------

    return "UNKNOWN"


# ============================================================
# FIND LINEUP
# ============================================================

def find_lineup_container(
    soup,
    expected_slots
):
    """
    Trova il blocco del Cheapest Grade usando
    SOLO vere immagini delle player card.

    Non conta più:
      FC Coin
      Gallery Token
      immagini decorative
    """

    # --------------------------------------------------------
    # TUTTE LE VERE CARD
    # --------------------------------------------------------

    all_player_images = [
        img
        for img in soup.find_all("img")
        if is_player_card_image(img)
    ]

    print(
        f"Real player-card images found in page: "
        f"{len(all_player_images)}"
    )

    if not all_player_images:
        return None

    candidates = []

    # --------------------------------------------------------
    # TROVIAMO ELEMENTI CON "CHEAPEST GRADE"
    # --------------------------------------------------------

    cheapest_nodes = []

    for node in soup.find_all(
        string=re.compile(
            r"Cheapest\s+grade",
            re.IGNORECASE
        )
    ):

        if node.parent:
            cheapest_nodes.append(
                node.parent
            )

    # --------------------------------------------------------
    # RISALIAMO DAGLI ELEMENTI
    # --------------------------------------------------------

    for start in cheapest_nodes:

        current = start

        for depth in range(12):

            if not current:
                break

            cards = [
                img
                for img in current.find_all("img")
                if is_player_card_image(img)
            ]

            count = len(cards)

            # Il contenitore corretto deve avere almeno
            # gli slot richiesti.

            if count >= expected_slots:

                candidates.append(
                    (
                        abs(
                            count -
                            expected_slots
                        ),
                        len(
                            str(current)
                        ),
                        current,
                        cards
                    )
                )

            current = current.parent

    # --------------------------------------------------------
    # FALLBACK
    # --------------------------------------------------------

    if not candidates:

        # Proviamo finestre consecutive delle vere card.
        #
        # Questo è molto più sicuro che prendere
        # immagini generiche.

        for i in range(
            0,
            max(
                1,
                len(all_player_images)
                - expected_slots
                + 1
            )
        ):

            window = all_player_images[
                i:i + expected_slots
            ]

            if len(window) == expected_slots:

                candidates.append(
                    (
                        0,
                        0,
                        None,
                        window
                    )
                )

    if not candidates:
        return None

    # --------------------------------------------------------
    # SCORE
    # --------------------------------------------------------

    candidates.sort(
        key=lambda x: (
            x[0],
            x[1]
        )
    )

    _, _, container, cards = candidates[0]

    print(
        f"Selected lineup candidate: "
        f"{len(cards)} player-card images"
    )

    return container, cards


# ============================================================
# EXTRACT LINEUP
# ============================================================

def extract_lineup(
    html,
    expected_slots,
    database,
    previous
):

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    result = find_lineup_container(
        soup,
        expected_slots
    )

    if not result:

        print(
            "WARNING: Could not find a valid "
            "player-card lineup."
        )

        return []

    container, images = result

    print(
        f"Images/cards detected in selected "
        f"container: {len(images)}"
    )

    # --------------------------------------------------------
    # PREVIOUS BY ITEM ID
    # --------------------------------------------------------

    previous_by_id = {}

    for card in previous:

        item_id = str(
            card.get("item_id") or ""
        ).strip()

        if item_id:
            previous_by_id[
                item_id
            ] = card

    cards = []

    # --------------------------------------------------------
    # PARSE
    # --------------------------------------------------------

    for img in images:

        card = parse_card(
            img
        )

        if not card:
            continue

        item_id = card["item_id"]

        previous_card = previous_by_id.get(
            item_id
        )

        finish = get_finish(
            item_id,
            previous_card,
            database
        )

        card["finish"] = finish
        card["placeholder"] = False

        # ----------------------------------------------------
        # NAME FALLBACK DALLO STATO PRECEDENTE
        # ----------------------------------------------------

        if not card.get("name") and previous_card:

            card["name"] = previous_card.get(
                "name"
            )

        if card.get("overall") is None and previous_card:

            card["overall"] = previous_card.get(
                "overall"
            )

        if not card.get("version") and previous_card:

            card["version"] = previous_card.get(
                "version"
            )

        cards.append(
            card
        )

        if len(cards) >= expected_slots:
            break

    print(
        f"Rendered lineup: "
        f"{len(cards)}/{expected_slots} real cards"
    )

    for card in cards:

        print(
            f"- {card.get('name')} "
            f"{card.get('overall')} "
            f"{card.get('version')} "
            f"— ItemID {card.get('item_id')} "
            f"— {card.get('finish')}"
        )

    return cards


# ============================================================
# SCAN CATEGORY
# ============================================================

def scan_category(
    category,
    config,
    database,
    players
):

    print(
        f"\nChecking {config['emoji']} "
        f"{category.upper()} "
        f"({config['slots']} players)..."
    )

    print("=" * 60)

    html = fetch_page(
        config["url"]
    )

    # --------------------------------------------------------
    # MATCHES
    # --------------------------------------------------------

    cheapest_matches = re.findall(
        r"Cheapest\s+grade",
        html,
        re.IGNORECASE
    )

    print(
        f"Cheapest grade matches found: "
        f"{len(cheapest_matches)}"
    )

    previous = players[
        category
    ].get(
        "current",
        []
    )

    current = extract_lineup(
        html,
        config["slots"],
        database,
        previous
    )

    # --------------------------------------------------------
    # SAFETY
    # --------------------------------------------------------

    if not current:

        print(
            "WARNING: No valid lineup detected."
        )

        print(
            "Previous state kept."
        )

        return previous, False

    # Heroes / Holographics devono avere 5 card.
    # Season 1 può avere Player Card placeholder.

    if (
        category != "Season 1"
        and len(current) < config["slots"]
    ):

        print(
            f"WARNING: Only "
            f"{len(current)}/"
            f"{config['slots']} cards detected."
        )

        print(
            "Previous state kept."
        )

        return previous, False

    return current, True


# ============================================================
# IDENTITY
# ============================================================

def occurrence_identity(card):

    item_id = str(
        card.get("item_id") or ""
    ).strip()

    if item_id:
        return (
            f"item:{item_id}"
        )

    return (
        "fallback:"
        + "|".join([
            str(card.get("name") or ""),
            str(card.get("overall") or ""),
            str(card.get("version") or ""),
            str(card.get("finish") or ""),
        ])
    )


# ============================================================
# CHANGES
# ============================================================

def detect_changes(
    previous,
    current
):

    old_counter = Counter(
        occurrence_identity(card)
        for card in previous
    )

    new_counter = Counter(
        occurrence_identity(card)
        for card in current
    )

    out_cards = []
    in_cards = []

    # --------------------------------------------------------
    # OUT
    # --------------------------------------------------------

    for key, old_count in old_counter.items():

        new_count = new_counter.get(
            key,
            0
        )

        difference = (
            old_count -
            new_count
        )

        if difference <= 0:
            continue

        matches = [
            card
            for card in previous
            if occurrence_identity(card) == key
        ]

        out_cards.extend(
            matches[:difference]
        )

    # --------------------------------------------------------
    # IN
    # --------------------------------------------------------

    for key, new_count in new_counter.items():

        old_count = old_counter.get(
            key,
            0
        )

        difference = (
            new_count -
            old_count
        )

        if difference <= 0:
            continue

        matches = [
            card
            for card in current
            if occurrence_identity(card) == key
        ]

        in_cards.extend(
            matches[:difference]
        )

    return out_cards, in_cards


# ============================================================
# MARK NEW
# ============================================================

def mark_new_cards(
    current,
    incoming
):

    incoming_counter = Counter(
        occurrence_identity(card)
        for card in incoming
    )

    result = []

    for card in current:

        copy_card = dict(
            card
        )

        key = occurrence_identity(
            card
        )

        if incoming_counter[key] > 0:

            copy_card["new"] = True

            incoming_counter[key] -= 1

        else:

            copy_card["new"] = False

        result.append(
            copy_card
        )

    return result


# ============================================================
# DATABASE UPDATE
# ============================================================

def update_player_database(
    database,
    current
):

    for card in current:

        item_id = str(
            card.get("item_id") or ""
        ).strip()

        finish = card.get(
            "finish"
        )

        if (
            item_id
            and finish in VALID_FINISHES
        ):

            existing = database[
                "items"
            ].get(
                item_id
            )

            # Non sovrascrivere una classificazione
            # valida.

            if not isinstance(
                existing,
                dict
            ) or existing.get(
                "finish"
            ) == "UNKNOWN":

                database[
                    "items"
                ][item_id] = {
                    "finish": finish,
                    "name": card.get("name"),
                    "overall": card.get("overall"),
                    "version": card.get("version"),
                    "source": "FUT.GG lineup"
                }


# ============================================================
# TELEGRAM CARD
# ============================================================

def format_card(
    card,
    new=False
):

    name = card.get(
        "name"
    ) or "?"

    overall = card.get(
        "overall"
    )

    finish = card.get(
        "finish"
    ) or "UNKNOWN"

    prefix = (
        "🟢 "
        if new
        else ""
    )

    return (
        f"{prefix}"
        f"<b>{escape(str(name))} "
        f"{escape(str(overall or '?'))}</b>"
        f"　·　"
        f"{escape(str(finish))}"
    )


# ============================================================
# TELEGRAM
# ============================================================

def build_telegram_message(
    results
):

    lines = [
        "<b>📋 FUT.GG Monitor</b>",
        ""
    ]

    categories = list(
        results.keys()
    )

    for index, category in enumerate(
        categories
    ):

        config = CATEGORIES[
            category
        ]

        data = results[
            category
        ]

        lines.append(
            f"<b>{config['emoji']} "
            f"{escape(category)}</b>"
        )

        lines.append("")

        # OUT
        for card in data["out"]:

            lines.append(
                "🔴 OUT — "
                + format_card(
                    card
                )
            )

        # IN
        for card in data["in"]:

            lines.append(
                "🟢 IN — "
                + format_card(
                    card,
                    new=False
                )
            )

        lines.append(
            "<b>📋 Current lineup 📋</b>"
        )

        for card in data["current"]:

            lines.append(
                format_card(
                    card,
                    new=bool(
                        card.get("new")
                    )
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
# SEND TELEGRAM
# ============================================================

def send_telegram(
    message
):

    if not TELEGRAM_BOT_TOKEN:
        print(
            "ERROR: TELEGRAM_BOT_TOKEN missing."
        )
        return False

    if not TELEGRAM_CHAT_ID:
        print(
            "ERROR: TELEGRAM_CHAT_ID missing."
        )
        return False

    url = (
        "https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
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

    print(
        "FUT.GG MONITOR"
    )

    print(
        "=" * 60
    )

    players = load_players()

    database = load_database()

    # --------------------------------------------------------
    # KNOWN
    # --------------------------------------------------------

    seed_known_finishes(
        database
    )

    # --------------------------------------------------------
    # HOLO DATABASE
    # --------------------------------------------------------

    database = scan_holographic_database(
        database
    )

    # --------------------------------------------------------
    # CATEGORIES
    # --------------------------------------------------------

    results = {}

    for category, config in CATEGORIES.items():

        try:

            old_current = players[
                category
            ].get(
                "current",
                []
            )

            current, valid = scan_category(
                category,
                config,
                database,
                players
            )

            if not valid:

                current = old_current

            out_cards, in_cards = detect_changes(
                old_current,
                current
            )

            current_marked = mark_new_cards(
                current,
                in_cards
            )

            update_player_database(
                database,
                current
            )

            results[category] = {
                "current": current_marked,
                "out": out_cards,
                "in": in_cards,
            }

            players[
                category
            ][
                "previous"
            ] = old_current

            players[
                category
            ][
                "current"
            ] = current

        except Exception as e:

            print(
                f"\nERROR scanning "
                f"{category}: {e}"
            )

            old_current = players[
                category
            ].get(
                "current",
                []
            )

            results[category] = {
                "current": old_current,
                "out": [],
                "in": [],
            }

    # --------------------------------------------------------
    # SAVE
    # --------------------------------------------------------

    save_database(
        database
    )

    save_json(
        PLAYERS_FILE,
        players
    )

    # --------------------------------------------------------
    # TELEGRAM
    # --------------------------------------------------------

    message = build_telegram_message(
        results
    )

    print(
        "\n" + "=" * 60
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

    print(
        "\nDONE"
    )


if __name__ == "__main__":
    main()