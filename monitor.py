import os
import re
import json
import time
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
#
# Questi sono gli ID che abbiamo già verificato.
#
# IMPORTANTE:
# Non usiamo più "UNKNOWN -> BASE".
# Se un ID non è nel database, rimane UNKNOWN.
#
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


# ============================================================
# BASIC FILE HELPERS
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
    temp_path = path + ".tmp"

    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )

    os.replace(temp_path, path)


# ============================================================
# PLAYERS
# ============================================================

def load_players():
    data = load_json(
        PLAYERS_FILE,
        {}
    )

    # Vecchia struttura:
    #
    # "Heroes": [...]
    #
    # viene convertita in:
    #
    # "Heroes": {
    #   "current": [...],
    #   "previous": [...]
    # }

    if isinstance(data, list):
        data = {}

    if not isinstance(data, dict):
        data = {}

    for category in CATEGORIES:
        value = data.get(category)

        if isinstance(value, list):
            data[category] = {
                "current": value,
                "previous": []
            }

        elif not isinstance(value, dict):
            data[category] = {
                "current": [],
                "previous": []
            }

        else:
            if not isinstance(value.get("current"), list):
                value["current"] = []

            if not isinstance(value.get("previous"), list):
                value["previous"] = []

    return data


# ============================================================
# CARD DATABASE
# ============================================================

def load_database():
    data = load_json(
        DATABASE_FILE,
        {}
    )

    if not isinstance(data, dict):
        data = {}

    if not isinstance(data.get("items"), dict):
        data["items"] = {}

    if not isinstance(data.get("players"), dict):
        data["players"] = {}

    if not isinstance(data.get("meta"), dict):
        data["meta"] = {}

    return data


def save_database(database):
    database.setdefault("meta", {})
    database["meta"]["last_update"] = datetime.utcnow().isoformat()

    save_json(
        DATABASE_FILE,
        database
    )


def seed_known_finishes(database):
    """
    Inserisce gli ID già conosciuti.

    NON sovrascrive un finish già presente.
    """

    database.setdefault("items", {})

    added = 0

    for item_id, finish in KNOWN_FINISHES.items():

        item_id = str(item_id)

        if item_id not in database["items"]:
            database["items"][item_id] = {
                "finish": finish,
                "source": "known"
            }
            added += 1

    if added:
        print(
            f"Known card finishes added to database: {added}"
        )
    else:
        print("Known card finishes already in database.")


# ============================================================
# HTTP
# ============================================================

def fetch_page(url):
    print(f"Fetching: {url}")

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
# ITEM ID EXTRACTION
# ============================================================

def extract_item_ids_from_text(text):
    """
    Estrae esclusivamente gli Item ID dagli URL FUT.GG.

    Esempio:

    .../futgg-player-item-card/27-67335170....

    -> 67335170

    Accettiamo anche ID corti come:

    .../27-5673....

    -> 5673
    """

    if not text:
        return set()

    pattern = re.compile(
        r"futgg-player-item-card/27-(\d+)",
        re.IGNORECASE
    )

    return set(
        pattern.findall(text)
    )


def extract_item_id_from_image(img):
    """
    Cerca l'Item ID in tutti gli attributi dell'immagine.
    """

    if not img:
        return None

    values = []

    for key, value in img.attrs.items():

        if isinstance(value, list):
            values.extend(
                str(x) for x in value
            )
        else:
            values.append(
                str(value)
            )

    pattern = re.compile(
        r"futgg-player-item-card/27-(\d+)",
        re.IGNORECASE
    )

    for value in values:

        match = pattern.search(value)

        if match:
            return match.group(1)

    # Fallback sull'intero tag

    raw = str(img)

    match = pattern.search(raw)

    if match:
        return match.group(1)

    return None


# ============================================================
# PLAYER KEY
# ============================================================

def normalize_text(value):
    if value is None:
        return ""

    return str(value).strip().lower()


def player_key(name, overall, version):
    return "|".join([
        normalize_text(name),
        normalize_text(overall),
        normalize_text(version),
    ])


# ============================================================
# CARD KEY
# ============================================================

def card_key(card):
    """
    L'Item ID è la vera identità della carta.

    Questo permette di mantenere due Harder distinti,
    due Šašić distinti ecc.
    """

    item_id = str(
        card.get("item_id") or ""
    ).strip()

    if item_id:
        return f"item:{item_id}"

    return (
        "player:"
        + player_key(
            card.get("name"),
            card.get("overall"),
            card.get("version")
        )
    )


# ============================================================
# FINISH RESOLUTION
# ============================================================

def get_finish(
    item_id,
    name=None,
    overall=None,
    version=None,
    previous_card=None,
    database=None
):
    """
    Determina il finish.

    ORDINE:

    1. Item ID nel database
    2. Item ID nei known finishes
    3. finish della carta precedente
    4. player database
    5. UNKNOWN

    MAI:
        sconosciuto -> BASE
    """

    database = database or {}

    items = database.get(
        "items",
        {}
    )

    players = database.get(
        "players",
        {}
    )

    item_id = str(
        item_id or ""
    ).strip()

    # --------------------------------------------------------
    # 1. DATABASE ITEM ID
    # --------------------------------------------------------

    if item_id:

        record = items.get(item_id)

        if isinstance(record, dict):

            finish = record.get("finish")

            if finish in {
                "BASE",
                "HOLO",
                "PRISTINE HOLO"
            }:
                return finish

        # Known finishes fallback

        known = KNOWN_FINISHES.get(item_id)

        if known:
            return known

    # --------------------------------------------------------
    # 2. PREVIOUS CARD
    # --------------------------------------------------------

    if previous_card:

        previous_finish = previous_card.get(
            "finish"
        )

        if previous_finish in {
            "BASE",
            "HOLO",
            "PRISTINE HOLO"
        }:
            return previous_finish

    # --------------------------------------------------------
    # 3. PLAYER DATABASE
    # --------------------------------------------------------

    pkey = player_key(
        name,
        overall,
        version
    )

    record = players.get(pkey)

    if isinstance(record, dict):

        finish = record.get(
            "finish"
        )

        if finish in {
            "BASE",
            "HOLO",
            "PRISTINE HOLO"
        }:
            return finish

    # --------------------------------------------------------
    # 4. UNKNOWN
    # --------------------------------------------------------

    return "UNKNOWN"


# ============================================================
# HOLOGRAPHIC DATABASE
# ============================================================

def scan_holographic_database(database):
    """
    Aggiorna il database degli Item ID Holo.

    ATTENZIONE:

    La pagina FUT.GG può cambiare struttura.
    Se non troviamo ID, NON cancelliamo il database
    precedente e NON trasformiamo gli ID in BASE.
    """

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
            f"  Error scanning pristine: {e}"
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
            f"  Error scanning holo: {e}"
        )

    # --------------------------------------------------------
    # UPDATE DATABASE
    # --------------------------------------------------------

    database.setdefault(
        "items",
        {}
    )

    for item_id in pristine_ids:

        database["items"][
            str(item_id)
        ] = {
            "finish": "PRISTINE HOLO",
            "source": "FUT.GG"
        }

    for item_id in holo_ids:

        item_id = str(item_id)

        # Pristine ha precedenza
        if item_id in pristine_ids:
            continue

        database["items"][
            item_id
        ] = {
            "finish": "HOLO",
            "source": "FUT.GG"
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
        f"{len(database.get('players', {}))}"
    )

    return database


# ============================================================
# ALT PARSING
# ============================================================

def parse_image_info(img):
    """
    Cerca di ricavare nome / overall / version dall'immagine.
    """

    alt = (
        img.get("alt")
        or img.get("title")
        or ""
    ).strip()

    name = None
    overall = None
    version = None

    if alt:

        parts = [
            x.strip()
            for x in re.split(
                r"\s+-\s+",
                alt
            )
            if x.strip()
        ]

        if len(parts) >= 1:
            name = parts[0]

        if len(parts) >= 2:

            try:
                overall = int(
                    re.sub(
                        r"\D",
                        "",
                        parts[1]
                    )
                )

            except Exception:
                overall = None

        if len(parts) >= 3:

            version = " - ".join(
                parts[2:]
            )

    # Fallback: cerchiamo il nome dal testo vicino
    if not name:

        parent = img.parent

        if parent:

            text = parent.get_text(
                " ",
                strip=True
            )

            # Alcuni layout FUT.GG hanno:
            # Name 89 Version

            match = re.search(
                r"([A-Za-zÀ-ÿŠšŽžĆćĐđÄäÖöÜüß'’\-]+)"
                r"\s+(\d{2})",
                text
            )

            if match:

                name = match.group(1)

                try:
                    overall = int(
                        match.group(2)
                    )
                except Exception:
                    overall = None

    return name, overall, version


# ============================================================
# PLACEHOLDER
# ============================================================

def is_placeholder(img):
    """
    Determina se l'immagine è un Player Card vuoto.
    """

    raw = str(img).lower()

    if "player card" in raw:
        return True

    alt = (
        img.get("alt")
        or ""
    ).lower()

    if alt.strip() == "player card":
        return True

    return False


# ============================================================
# FIND CHEAPEST LINEUP
# ============================================================

def find_lineup_container(soup, expected_slots):
    """
    Trova il contenitore della sezione
    'Cheapest grade ... lineup'.

    Usiamo il testo per evitare di prendere immagini
    appartenenti alle altre sezioni della pagina.
    """

    candidates = []

    # Cerchiamo elementi che contengono "Cheapest grade"

    for element in soup.find_all(
        string=re.compile(
            r"Cheapest grade",
            re.IGNORECASE
        )
    ):

        parent = element.parent

        if not parent:
            continue

        # Proviamo vari livelli superiori

        current = parent

        for _ in range(7):

            if not current:
                break

            images = current.find_all(
                "img"
            )

            if len(images) >= expected_slots:

                candidates.append(
                    current
                )

            current = current.parent

    if not candidates:
        return None

    # Preferiamo il contenitore più piccolo
    # che contiene abbastanza immagini.

    candidates.sort(
        key=lambda x: (
            len(x.find_all("img")),
            len(str(x))
        )
    )

    return candidates[0]


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

    container = find_lineup_container(
        soup,
        expected_slots
    )

    if not container:

        print(
            "WARNING: Cheapest grade lineup "
            "container not found."
        )

        return []

    images = container.find_all(
        "img"
    )

    print(
        f"Images/cards detected in selected "
        f"container: {len(images)}"
    )

    cards = []

    previous_by_item = {}

    for card in previous:

        item_id = str(
            card.get("item_id") or ""
        ).strip()

        if item_id:
            previous_by_item[
                item_id
            ] = card

    for img in images:

        # ----------------------------------------------------
        # PLACEHOLDER
        # ----------------------------------------------------

        if is_placeholder(img):
            continue

        # ----------------------------------------------------
        # ITEM ID
        # ----------------------------------------------------

        item_id = extract_item_id_from_image(
            img
        )

        # ----------------------------------------------------
        # INFO
        # ----------------------------------------------------

        name, overall, version = parse_image_info(
            img
        )

        # Se non abbiamo nemmeno il nome,
        # probabilmente non è una card reale.

        if not name:
            continue

        # ----------------------------------------------------
        # PREVIOUS
        # ----------------------------------------------------

        previous_card = None

        if item_id:
            previous_card = previous_by_item.get(
                str(item_id)
            )

        # ----------------------------------------------------
        # FINISH
        # ----------------------------------------------------

        finish = get_finish(
            item_id=item_id,
            name=name,
            overall=overall,
            version=version,
            previous_card=previous_card,
            database=database
        )

        card = {
            "name": name,
            "overall": overall,
            "version": version,
            "item_id": item_id,
            "finish": finish,
            "placeholder": False
        }

        cards.append(card)

    # --------------------------------------------------------
    # LIMIT TO EXPECTED SLOTS
    # --------------------------------------------------------

    if len(cards) > expected_slots:
        cards = cards[:expected_slots]

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
    # CHEAPEST GRADE INFO
    # --------------------------------------------------------

    matches = re.findall(
        r"Cheapest grade",
        html,
        re.IGNORECASE
    )

    print(
        f"Cheapest grade matches found: "
        f"{len(matches)}"
    )

    previous = players[category].get(
        "current",
        []
    )

    lineup = extract_lineup(
        html,
        config["slots"],
        database,
        previous
    )

    # --------------------------------------------------------
    # SAFETY
    # --------------------------------------------------------

    if not lineup:

        print(
            "WARNING: No valid lineup detected."
        )

        print(
            "Previous state kept."
        )

        return previous, False

    # Se abbiamo trovato meno card del previsto,
    # non sovrascriviamo la lineup completa con dati
    # probabilmente incompleti.

    if len(lineup) < config["slots"]:

        print(
            f"WARNING: Only {len(lineup)}/"
            f"{config['slots']} cards detected."
        )

        # Season 1 può avere Player Card placeholder,
        # quindi una lineup incompleta può essere valida.
        #
        # Per Heroes/Holographics invece preferiamo
        # mantenere lo stato precedente se manca una card.

        if category != "Season 1" and previous:

            print(
                "Previous state kept."
            )

            return previous, False

    return lineup, True


# ============================================================
# OCCURRENCE ID
# ============================================================

def occurrence_identity(card):
    """
    L'Item ID identifica la singola carta.

    Se manca, usiamo un fallback.
    """

    item_id = str(
        card.get("item_id") or ""
    ).strip()

    if item_id:
        return f"item:{item_id}"

    return (
        "fallback:"
        + player_key(
            card.get("name"),
            card.get("overall"),
            card.get("version")
        )
    )


# ============================================================
# CHANGE DETECTION
# ============================================================

def detect_changes(previous, current):
    """
    Confronta le OCCORRENZE.

    Importante:
    due Harder con Item ID diversi sono due carte diverse.
    """

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

        difference = old_count - new_count

        if difference <= 0:
            continue

        matches = [
            card
            for card in previous
            if occurrence_identity(card) == key
        ]

        for card in matches[:difference]:
            out_cards.append(card)

    # --------------------------------------------------------
    # IN
    # --------------------------------------------------------

    for key, new_count in new_counter.items():

        old_count = old_counter.get(
            key,
            0
        )

        difference = new_count - old_count

        if difference <= 0:
            continue

        matches = [
            card
            for card in current
            if occurrence_identity(card) == key
        ]

        for card in matches[:difference]:
            in_cards.append(card)

    return out_cards, in_cards


# ============================================================
# MARK NEW CARDS
# ============================================================

def mark_new_cards(
    current,
    incoming
):
    incoming_keys = Counter(
        occurrence_identity(card)
        for card in incoming
    )

    marked = []

    for card in current:

        key = occurrence_identity(
            card
        )

        if incoming_keys.get(key, 0) > 0:

            copy_card = dict(card)

            copy_card["new"] = True

            incoming_keys[key] -= 1

            marked.append(
                copy_card
            )

        else:

            copy_card = dict(card)

            copy_card["new"] = False

            marked.append(
                copy_card
            )

    return marked


# ============================================================
# UPDATE PLAYER DATABASE
# ============================================================

def update_player_database(
    database,
    current
):
    database.setdefault(
        "items",
        {}
    )

    database.setdefault(
        "players",
        {}
    )

    for card in current:

        item_id = str(
            card.get("item_id") or ""
        ).strip()

        finish = card.get(
            "finish"
        )

        # ----------------------------------------------------
        # ITEM
        # ----------------------------------------------------

        if item_id and finish in {
            "BASE",
            "HOLO",
            "PRISTINE HOLO"
        }:

            existing = database["items"].get(
                item_id
            )

            # Non sovrascriviamo una classificazione
            # valida con UNKNOWN.

            if (
                not isinstance(existing, dict)
                or existing.get("finish") == "UNKNOWN"
            ):

                database["items"][item_id] = {
                    "finish": finish,
                    "name": card.get("name"),
                    "overall": card.get("overall"),
                    "version": card.get("version"),
                    "source": "FUT.GG lineup"
                }

        # ----------------------------------------------------
        # PLAYER
        # ----------------------------------------------------

        if finish in {
            "BASE",
            "HOLO",
            "PRISTINE HOLO"
        }:

            pkey = player_key(
                card.get("name"),
                card.get("overall"),
                card.get("version")
            )

            # Salviamo solo se non esiste.
            #
            # Non possiamo usare il player key come
            # unica identità perché lo stesso giocatore
            # può avere BASE e HOLO.

            if pkey not in database["players"]:

                database["players"][pkey] = {
                    "name": card.get("name"),
                    "overall": card.get("overall"),
                    "version": card.get("version"),
                    "finish": finish
                }


# ============================================================
# FORMAT CARD
# ============================================================

def format_card(card, new=False):
    name = escape(
        str(card.get("name") or "?")
    )

    overall = card.get(
        "overall"
    )

    overall_text = (
        str(overall)
        if overall is not None
        else "?"
    )

    finish = escape(
        str(card.get("finish") or "UNKNOWN")
    )

    prefix = ""

    if new:
        prefix = "🟢 "

    return (
        f"{prefix}<b>{name} "
        f"{overall_text}</b>　·　"
        f"{finish}"
    )


# ============================================================
# TELEGRAM MESSAGE
# ============================================================

def build_telegram_message(results):
    lines = []

    lines.append(
        "<b>📋 FUT.GG Monitor</b>"
    )

    lines.append("")

    categories = list(
        results.keys()
    )

    for index, category in enumerate(categories):

        data = results[category]

        config = CATEGORIES[
            category
        ]

        current = data["current"]
        out_cards = data["out"]
        in_cards = data["in"]

        # ----------------------------------------------------
        # CATEGORY
        # ----------------------------------------------------

        lines.append(
            f"<b>{config['emoji']} "
            f"{escape(category)}</b>"
        )

        lines.append("")

        # ----------------------------------------------------
        # OUT
        # ----------------------------------------------------

        for card in out_cards:

            lines.append(
                "🔴 OUT — "
                + format_card(
                    card,
                    new=False
                )
            )

        # ----------------------------------------------------
        # IN
        # ----------------------------------------------------

        for card in in_cards:

            lines.append(
                "🟢 IN — "
                + format_card(
                    card,
                    new=True
                )
            )

        # ----------------------------------------------------
        # CURRENT
        # ----------------------------------------------------

        lines.append(
            "<b>📋 Current lineup 📋</b>"
        )

        for card in current:

            lines.append(
                format_card(
                    card,
                    new=bool(
                        card.get("new")
                    )
                )
            )

        # ----------------------------------------------------
        # SEPARATOR
        # ----------------------------------------------------

        if index < len(categories) - 1:

            lines.append("")
            lines.append(
                "--------------------"
            )
            lines.append("")

    return "\n".join(lines)


# ============================================================
# TELEGRAM SEND
# ============================================================

def send_telegram(message):
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

    # --------------------------------------------------------
    # LOAD
    # --------------------------------------------------------

    players = load_players()

    database = load_database()

    # --------------------------------------------------------
    # SEED KNOWN
    # --------------------------------------------------------

    seed_known_finishes(
        database
    )

    save_database(
        database
    )

    # --------------------------------------------------------
    # HOLOGRAPHIC DATABASE
    # --------------------------------------------------------

    database = scan_holographic_database(
        database
    )

    # --------------------------------------------------------
    # SCAN CATEGORIES
    # --------------------------------------------------------

    results = {}

    changed_anything = False

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

                # Manteniamo il precedente
                current = old_current

            # ------------------------------------------------
            # CHANGES
            # ------------------------------------------------

            out_cards, in_cards = detect_changes(
                old_current,
                current
            )

            # ------------------------------------------------
            # MARK NEW
            # ------------------------------------------------

            current_marked = mark_new_cards(
                current,
                in_cards
            )

            # ------------------------------------------------
            # UPDATE DATABASE
            # ------------------------------------------------

            update_player_database(
                database,
                current
            )

            # ------------------------------------------------
            # SAVE RESULT
            # ------------------------------------------------

            results[category] = {
                "current": current_marked,
                "out": out_cards,
                "in": in_cards,
            }

            # ------------------------------------------------
            # SAVE PLAYERS STATE
            # ------------------------------------------------

            players[category][
                "previous"
            ] = old_current

            players[category][
                "current"
            ] = current

            if out_cards or in_cards:
                changed_anything = True

        except Exception as e:

            print(
                f"\nERROR scanning "
                f"{category}: {e}"
            )

            # In caso di errore manteniamo
            # la vecchia lineup.

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
    # SAVE DATABASE
    # --------------------------------------------------------

    save_database(
        database
    )

    # --------------------------------------------------------
    # SAVE PLAYERS
    # --------------------------------------------------------

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


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()