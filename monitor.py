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

BASE_DIR = Path(__file__).resolve().parent

DATABASE_FILE = BASE_DIR / "card_database.json"
STATE_FILE = BASE_DIR / "players.json"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


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


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


SESSION = requests.Session()
SESSION.headers.update(HEADERS)


# ============================================================
# VERIFIED ITEM IDS
# ============================================================

KNOWN_FINISHES = {
    # PRISTINE HOLO
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
    "67382990": "PRISTINE HOLO",   # Paris Brunner

    "67301045": "PRISTINE HOLO",   # van Basten
    "67119128": "PRISTINE HOLO",   # van Nistelrooy

    # HOLO
    "67179830": "HOLO",             # Jacobo Ramón
    "67188263": "HOLO",             # Mora
    "67368429": "HOLO",             # Bonny
    "67353040": "HOLO",             # Undav
    "67372629": "HOLO",             # Bischof
    "67386815": "HOLO",             # Yohannes
    "67374557": "HOLO",
    "67383677": "HOLO",             # Gisele Thompson

    # BASE
    "226306": "BASE",               # Šašić
    "233700": "BASE",               # Vialli
    "5673": "BASE",                 # Litmanen
    "50590935": "BASE",             # Harder
    "50590026": "BASE",             # Godts
    "50570879": "BASE",             # Cucurella
    "50606461": "BASE",             # Gisele Thompson
    "50605774": "BASE",             # Paris Brunner
}


KNOWN_PLAYER_FINISHES = {
    "Mascherano": "BASE",
    "van Basten": "PRISTINE HOLO",
    "van Nistelrooy": "PRISTINE HOLO",
}


# ============================================================
# FETCH
# ============================================================

def fetch_page(url):
    print(f"Fetching: {url}")

    response = SESSION.get(
        url,
        timeout=30,
    )

    print(f"HTTP status: {response.status_code}")

    response.raise_for_status()

    print(f"Downloaded: {len(response.text)} characters")

    return response.text


# ============================================================
# DATABASE
# ============================================================

def load_database():
    if not DATABASE_FILE.exists():
        print("Database file not found.")
        return {}

    try:
        with open(
            DATABASE_FILE,
            "r",
            encoding="utf-8",
        ) as f:
            data = json.load(f)

        if not isinstance(data, dict):
            return {}

        print(f"Database items: {len(data)}")

        return data

    except Exception as e:
        print(f"Database load error: {e}")
        return {}


# ============================================================
# TEXT
# ============================================================

def normalize_text(value):
    if value is None:
        return ""

    return re.sub(
        r"\s+",
        " ",
        str(value).strip(),
    )


def clean_player_name(value):
    return normalize_text(value)


# ============================================================
# CARD ALT
# ============================================================

def parse_card_alt(alt):
    alt = normalize_text(alt)

    if not alt:
        return None

    if alt.lower() == "player card":
        return None

    parts = [
        normalize_text(x)
        for x in alt.split(" - ")
    ]

    if len(parts) < 2:
        return None

    player = parts[0]

    overall = None

    for part in parts[1:]:
        match = re.search(
            r"\b(\d{2,3})\b",
            part,
        )

        if match:
            overall = int(
                match.group(1)
            )
            break

    if not player or overall is None:
        return None

    version = ""

    if len(parts) >= 3:
        version = " - ".join(
            parts[2:]
        )

    return {
        "player": clean_player_name(player),
        "overall": overall,
        "version": version,
        "alt": alt,
    }


# ============================================================
# ITEM ID
# ============================================================

def extract_item_id_from_value(value):
    if not value:
        return None

    value = str(value)

    # FUT.GG example:
    # .../2027/futgg-player-item-card/27-67335157.hash.webp
    #
    # Prende SOLO 67335157, mai 2027.

    match = re.search(
        r"(?:^|[/_-])27-(\d{4,10})(?=[./?_-]|$)",
        value,
        re.IGNORECASE,
    )

    if match:
        return match.group(1)

    patterns = [
        r'item[_-]?id\s*=\s*["\']?(\d{4,10})',
        r'itemId\s*=\s*["\']?(\d{4,10})',
        r'item_id\s*=\s*["\']?(\d{4,10})',
        r'"itemId"\s*:\s*(\d{4,10})',
        r'"item_id"\s*:\s*(\d{4,10})',
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            value,
            re.IGNORECASE,
        )

        if match:
            return match.group(1)

    return None


def find_item_id_for_image(img):
    attributes = [
        "src",
        "data-src",
        "data-lazy-src",
        "data-original",
        "srcset",
        "data-srcset",
        "data-item-id",
        "data-itemid",
        "item-id",
    ]

    # 1. Immagine
    for attr in attributes:
        value = img.get(attr)

        if not value:
            continue

        item_id = extract_item_id_from_value(
            value
        )

        if item_id:
            return item_id

    # 2. Parent immediato
    parent = img.parent

    if parent:
        for attr in [
            "href",
            "data-href",
            "data-item-id",
            "data-itemid",
            "item-id",
            "data-card-id",
        ]:
            item_id = extract_item_id_from_value(
                parent.get(attr)
            )

            if item_id:
                return item_id

    # 3. Link più vicino
    parent_link = img.find_parent("a")

    if parent_link:
        for attr in [
            "href",
            "data-href",
            "data-item-id",
            "data-itemid",
            "item-id",
            "data-card-id",
        ]:
            item_id = extract_item_id_from_value(
                parent_link.get(attr)
            )

            if item_id:
                return item_id

    # 4. Figli immediati del wrapper
    if parent:
        for child in parent.find_all(
            recursive=False
        ):
            if child is img:
                continue

            for attr in [
                "src",
                "data-src",
                "data-lazy-src",
                "data-original",
                "href",
                "data-href",
                "data-item-id",
                "data-itemid",
                "item-id",
            ]:
                item_id = extract_item_id_from_value(
                    child.get(attr)
                )

                if item_id:
                    return item_id

    return None


# ============================================================
# FINISH
# ============================================================

def finish_from_version(version):
    version = normalize_text(
        version
    ).lower()

    if not version:
        return None

    if "pristine" in version:
        return "PRISTINE HOLO"

    if "holographic" in version:
        return "HOLO"

    if re.search(
        r"\bholo\b",
        version,
    ):
        return "HOLO"

    return "BASE"


# ============================================================
# LINEUP CONTAINER
# ============================================================

def find_best_lineup_container(
    soup,
    target_slots,
):
    candidates = []

    text_nodes = soup.find_all(
        string=re.compile(
            r"Cheapest\s+grade",
            re.IGNORECASE,
        )
    )

    for text_node in text_nodes:
        element = text_node.parent

        if not element:
            continue

        current = element

        for _ in range(8):
            if current is None:
                break

            images = current.find_all("img")

            card_images = []

            for img in images:
                alt = normalize_text(
                    img.get("alt", "")
                )

                if not alt:
                    continue

                if alt.lower() == "player card":
                    card_images.append(img)
                    continue

                if parse_card_alt(alt):
                    card_images.append(img)

            if len(card_images) >= target_slots:
                candidates.append(
                    (
                        abs(
                            len(card_images)
                            - target_slots
                        ),
                        len(str(current)),
                        current,
                    )
                )

            current = current.parent

    if not candidates:
        return None

    candidates.sort(
        key=lambda x: (
            x[0],
            x[1],
        )
    )

    return candidates[0][2]


# ============================================================
# PARSE LINEUP
# ============================================================

def parse_lineup(
    html,
    category_name,
    target_slots,
    database,
):
    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    container = find_best_lineup_container(
        soup,
        target_slots,
    )

    if container is None:
        print(
            f"Could not find lineup container "
            f"for {category_name}."
        )
        return []

    images = container.find_all("img")

    slots = []

    for img in images:
        alt = normalize_text(
            img.get("alt", "")
        )

        if not alt:
            continue

        # Slot FUT.GG vuoto
        if alt.lower() == "player card":
            slots.append(None)

            if len(slots) >= target_slots:
                break

            continue

        parsed = parse_card_alt(alt)

        if not parsed:
            continue

        player = parsed["player"]
        overall = parsed["overall"]
        version = parsed["version"]

        item_id = find_item_id_for_image(
            img
        )

        finish = None

        # 1. Item ID verificato
        if item_id:
            finish = KNOWN_FINISHES.get(
                str(item_id)
            )

        # 2. Database
        if finish is None and item_id:
            db_item = database.get(
                str(item_id)
            )

            if isinstance(db_item, dict):
                db_finish = db_item.get(
                    "finish"
                )

                if db_finish:
                    finish = normalize_text(
                        db_finish
                    ).upper()

        # 3. Versione
        if finish is None:
            finish = finish_from_version(
                version
            )

        # 4. Fallback giocatore
        if finish is None:
            finish = KNOWN_PLAYER_FINISHES.get(
                player
            )

        # 5. Default
        if finish is None:
            finish = "BASE"

        card = {
            "player": player,
            "overall": overall,
            "item_id": (
                str(item_id)
                if item_id
                else None
            ),
            "finish": finish,
        }

        slots.append(card)

        if len(slots) >= target_slots:
            break

    slots = slots[:target_slots]

    while len(slots) < target_slots:
        slots.append(None)

    print(
        f"Lineup slot images found: "
        f"{len(slots)}/{target_slots}"
    )

    print(
        f"Rendered lineup: "
        f"{len(slots)}/{target_slots} slots"
    )

    for card in slots:
        if card is None:
            continue

        print(
            f"- {card['player']} "
            f"{card['overall']} — "
            f"ItemID {card['item_id']} — "
            f"{card['finish']}"
        )

    return slots


# ============================================================
# CARD IDENTITY
# ============================================================

def card_key(card):
    if not isinstance(
        card,
        dict,
    ):
        return None

    player = card.get("player")

    if not player:
        return None

    item_id = card.get("item_id")

    # Item ID distingue perfettamente
    # BASE / HOLO / PRISTINE HOLO.
    if item_id:
        return f"item:{item_id}"

    return (
        f"{player}|"
        f"{card.get('overall', '')}|"
        f"{card.get('finish', '')}"
    )


def valid_card(card):
    if not isinstance(
        card,
        dict,
    ):
        return False

    player = card.get("player")

    if not player:
        return False

    if (
        str(player)
        .strip()
        .lower()
        == "player card"
    ):
        return False

    if card.get("overall") is None:
        return False

    return True


# ============================================================
# STATE
# ============================================================

def load_previous_state():
    if not STATE_FILE.exists():
        return {}

    try:
        with open(
            STATE_FILE,
            "r",
            encoding="utf-8",
        ) as f:
            data = json.load(f)

        if not isinstance(
            data,
            dict,
        ):
            return {}

        return data

    except Exception as e:
        print(
            f"State load error: {e}"
        )
        return {}


def clean_state(data):
    cleaned = {}

    if not isinstance(
        data,
        dict,
    ):
        return cleaned

    for category_name in CATEGORIES:
        cards = data.get(
            category_name,
            [],
        )

        if not isinstance(
            cards,
            list,
        ):
            cleaned[
                category_name
            ] = []

            continue

        cleaned[
            category_name
        ] = [
            card
            for card in cards
            if valid_card(card)
        ]

    return cleaned


def save_state(current_data):
    with open(
        STATE_FILE,
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            current_data,
            f,
            ensure_ascii=False,
            indent=2,
        )


# ============================================================
# FIND CHANGES
# ============================================================

def find_changes(
    current_cards,
    previous_cards,
):
    """
    Confronta le carte ignorando completamente l'ordine.

    Gestisce anche duplicati reali.

    Ritorna:
        new_cards
        removed_cards
    """

    current_counts = {}
    previous_counts = {}

    current_by_key = {}
    previous_by_key = {}

    # Current
    for card in current_cards:
        key = card_key(card)

        if key is None:
            continue

        current_counts[key] = (
            current_counts.get(
                key,
                0,
            ) + 1
        )

        current_by_key.setdefault(
            key,
            card,
        )

    # Previous
    for card in previous_cards:
        key = card_key(card)

        if key is None:
            continue

        previous_counts[key] = (
            previous_counts.get(
                key,
                0,
            ) + 1
        )

        previous_by_key.setdefault(
            key,
            card,
        )

    new_cards = []
    removed_cards = []

    # Nuove
    for key, count in current_counts.items():
        previous_count = previous_counts.get(
            key,
            0,
        )

        difference = (
            count - previous_count
        )

        if difference > 0:
            for _ in range(difference):
                new_cards.append(
                    current_by_key[key]
                )

    # Uscite
    for key, count in previous_counts.items():
        current_count = current_counts.get(
            key,
            0,
        )

        difference = (
            count - current_count
        )

        if difference > 0:
            for _ in range(difference):
                removed_cards.append(
                    previous_by_key[key]
                )

    return (
        new_cards,
        removed_cards,
    )


# ============================================================
# TELEGRAM
# ============================================================

def telegram_escape(value):
    if value is None:
        return ""

    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def card_display_name(card):
    player = telegram_escape(
        card.get(
            "player",
            "",
        )
    )

    overall = card.get(
        "overall",
        "",
    )

    finish = telegram_escape(
        card.get(
            "finish",
            "BASE",
        )
    )

    return (
        f"<b>{player} {overall}</b>"
        f"　·　"
        f"{finish}"
    )


def send_telegram_message(message):
    if not TELEGRAM_BOT_TOKEN:
        print(
            "TELEGRAM_BOT_TOKEN is missing."
        )
        return False

    if not TELEGRAM_CHAT_ID:
        print(
            "TELEGRAM_CHAT_ID is missing."
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

    try:
        response = SESSION.post(
            url,
            json=payload,
            timeout=30,
        )

        print(
            f"Telegram status: "
            f"{response.status_code}"
        )

        if not response.ok:
            print(
                "Telegram error:",
                response.text,
            )

        return response.ok

    except Exception as e:
        print(
            f"Telegram send error: {e}"
        )
        return False


# ============================================================
# BUILD TELEGRAM MESSAGE
# ============================================================

def build_telegram_message(
    current_data,
    previous_data,
):
    """
    Il messaggio viene SEMPRE inviato.

    Carta già presente:
        Nome 88 · FINISH

    Carta appena entrata:
        🟢 Nome 88 · FINISH

    Carta appena uscita:
        🔴 OUT — Nome 88 · FINISH

    Il semplice cambio d'ordine NON genera
    pallini verdi o OUT.
    """

    lines = [
        "📋 <b>Current lineup</b> 📋",
        "",
    ]

    category_names = list(
        CATEGORIES.keys()
    )

    for category_index, category_name in enumerate(
        category_names
    ):
        emoji = CATEGORIES[
            category_name
        ]["emoji"]

        current_slots = current_data.get(
            category_name,
            [],
        )

        previous_slots = previous_data.get(
            category_name,
            [],
        )

        current_cards = [
            card
            for card in current_slots
            if valid_card(card)
        ]

        previous_cards = [
            card
            for card in previous_slots
            if valid_card(card)
        ]

        # Trova cambi reali
        new_cards, removed_cards = find_changes(
            current_cards,
            previous_cards,
        )

        # Conteggio carte nuove.
        # Serve per gestire correttamente
        # anche eventuali duplicati.
        new_counts = {}

        for card in new_cards:
            key = card_key(card)

            new_counts[key] = (
                new_counts.get(
                    key,
                    0,
                ) + 1
            )

        # ----------------------------------------------------
        # CATEGORY
        # ----------------------------------------------------

        lines.append(
            f"{emoji} "
            f"<b>{category_name.upper()}</b>"
        )

        # ----------------------------------------------------
        # CURRENT LINEUP
        # ----------------------------------------------------

        for card in current_cards:
            key = card_key(card)

            # Nuova carta
            if new_counts.get(
                key,
                0,
            ) > 0:
                lines.append(
                    "🟢 "
                    + card_display_name(card)
                )

                new_counts[key] -= 1

            # Carta già presente
            else:
                lines.append(
                    card_display_name(card)
                )

        # ----------------------------------------------------
        # OUT
        # ----------------------------------------------------

        for card in removed_cards:
            lines.append(
                "🔴 OUT — "
                + card_display_name(card)
            )

        # ----------------------------------------------------
        # SEPARATOR
        # ----------------------------------------------------

        if category_index < (
            len(category_names) - 1
        ):
            lines.append(
                "--------------------"
            )

    return "\n".join(lines)


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 60)
    print("FUT.GG MONITOR")
    print("=" * 60)

    database = load_database()

    # Stato della precedente esecuzione
    previous_data = clean_state(
        load_previous_state()
    )

    current_data = {}

    # ========================================================
    # SCAN FUT.GG
    # ========================================================

    for category_name, config in CATEGORIES.items():
        emoji = config["emoji"]
        url = config["url"]
        target_slots = config["slots"]

        print()

        print(
            f"Checking {emoji} "
            f"{category_name.upper()} "
            f"({target_slots} players)..."
        )

        try:
            html = fetch_page(
                url
            )

            lineup = parse_lineup(
                html=html,
                category_name=category_name,
                target_slots=target_slots,
                database=database,
            )

            current_data[
                category_name
            ] = lineup

        except Exception as e:
            print(
                f"ERROR while checking "
                f"{category_name}: {e}"
            )

            # Se FUT.GG ha un errore temporaneo,
            # manteniamo la lineup precedente.
            #
            # In questo modo non genera falsi OUT.
            current_data[
                category_name
            ] = previous_data.get(
                category_name,
                [],
            )

    # ========================================================
    # TELEGRAM
    # ========================================================

    message = build_telegram_message(
        current_data,
        previous_data,
    )

    print()
    print("=" * 60)
    print("TELEGRAM MESSAGE")
    print("=" * 60)

    print(message)

    print("=" * 60)

    # Il messaggio viene inviato SEMPRE,
    # anche quando non è cambiato niente.
    send_telegram_message(
        message
    )

    # ========================================================
    # SAVE STATE
    # ========================================================

    save_state(
        current_data
    )

    print()
    print(
        "State saved successfully."
    )

    print(
        "Finished at:",
        datetime.now(
            timezone.utc
        ).isoformat(),
    )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()