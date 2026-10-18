import json
import re
import time
from pathlib import Path
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup


# ============================================================
# CONFIG
# ============================================================

BASE_URL = "https://www.fut.gg"

RARITY_IDS = [
    3,
    71,
    22,
    8,
    72,
    12,
]

OUTPUT_FILE = Path("card_database.json")

REQUEST_DELAY = 0.20
MAX_PAGES = 100

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


# ============================================================
# SESSION
# ============================================================

session = requests.Session()
session.headers.update(HEADERS)


# ============================================================
# HELPERS
# ============================================================

def clean_text(value):
    if value is None:
        return ""

    return re.sub(
        r"\s+",
        " ",
        str(value),
    ).strip()


def get_page(page_number):
    """
    Costruisce ESATTAMENTE il link che ci hai dato,
    cambiando solamente page=.
    """

    rarity_json = json.dumps(
        RARITY_IDS,
        separators=(",", ":"),
    )

    encoded_rarity = quote(
        rarity_json,
        safe="",
    )

    url = (
        f"{BASE_URL}/players/"
        f"?page={page_number}"
        f"&rarity_id={encoded_rarity}"
    )

    print()
    print(f"Fetching page {page_number}")
    print(url)

    response = session.get(
        url,
        timeout=40,
    )

    response.raise_for_status()

    print(
        f"HTTP status: {response.status_code}"
    )

    print(
        f"Downloaded: "
        f"{len(response.text)} characters"
    )

    return response.text


def extract_item_ids(text):
    """
    Cerca Item ID nei vari formati che FUT.GG
    può utilizzare nell'HTML.
    """

    if not text:
        return set()

    results = set()

    patterns = [
        # FUT.GG player card URL
        r"futgg-player-item-card/27-(\d+)",

        # generico 27-ID
        r"(?:^|[/_-])27-(\d+)",

        # JSON
        r'"itemId"\s*:\s*"?(\d+)',
        r'"item_id"\s*:\s*"?(\d+)',

        # HTML/data attributes
        r'item-id=["\'](\d+)',
        r'item_id=["\'](\d+)',
    ]

    for pattern in patterns:
        matches = re.findall(
            pattern,
            text,
            flags=re.IGNORECASE,
        )

        for value in matches:
            results.add(
                str(value)
            )

    return results


def parse_alt(alt):
    """
    FUT.GG normalmente utilizza alt del tipo:

        Player Name - 89 - Future Stars

    oppure:

        Player Name - 89 - Base Hero
    """

    alt = clean_text(alt)

    if not alt:
        return None

    match = re.match(
        r"^(.*?)\s*-\s*(\d{2})\s*-\s*(.*?)$",
        alt,
    )

    if not match:
        return None

    player = clean_text(
        match.group(1)
    )

    overall = int(
        match.group(2)
    )

    version = clean_text(
        match.group(3)
    )

    if not player:
        return None

    if player.lower() == "player card":
        return None

    return {
        "player": player,
        "overall": overall,
        "version": version,
    }


def looks_like_player_card(img):
    """
    Controlla che l'immagine sembri effettivamente
    una carta giocatore e non un'immagine del sito.
    """

    alt = clean_text(
        img.get("alt", "")
    )

    if parse_alt(alt):
        return True

    attributes = [
        img.get("src", ""),
        img.get("data-src", ""),
        img.get("data-lazy-src", ""),
        img.get("data-original", ""),
        img.get("srcset", ""),
        img.get("data-srcset", ""),
    ]

    combined = " ".join(
        str(x)
        for x in attributes
        if x
    )

    if "futgg-player-item-card" in combined.lower():
        return True

    return False


def extract_cards_from_html(
    html,
    rarity_id,
):
    """
    Estrae le carte dalla pagina.

    Importante:
    non legge FC26.
    La pagina viene generata esclusivamente tramite
    i 6 rarity_id FC27 definiti sopra.
    """

    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    cards = {}

    images = soup.find_all("img")

    print(
        f"Images found: {len(images)}"
    )

    for img in images:

        if not looks_like_player_card(img):
            continue

        alt = clean_text(
            img.get("alt", "")
        )

        parsed = parse_alt(alt)

        if not parsed:
            continue

        # ----------------------------------------------------
        # Cerca Item ID nell'immagine
        # ----------------------------------------------------

        item_ids = set()

        image_attributes = [
            img.get("src", ""),
            img.get("data-src", ""),
            img.get("data-lazy-src", ""),
            img.get("data-original", ""),
            img.get("srcset", ""),
            img.get("data-srcset", ""),
        ]

        for value in image_attributes:

            if not value:
                continue

            item_ids.update(
                extract_item_ids(
                    str(value)
                )
            )

        # ----------------------------------------------------
        # Cerca Item ID nei parent della card
        # ----------------------------------------------------

        parent = img

        for _ in range(6):

            if parent is None:
                break

            try:
                parent_html = str(
                    parent
                )
            except Exception:
                parent_html = ""

            item_ids.update(
                extract_item_ids(
                    parent_html
                )
            )

            parent = parent.parent

        # ----------------------------------------------------
        # Salva le carte
        # ----------------------------------------------------

        for item_id in item_ids:

            item_id = str(
                item_id
            )

            cards[item_id] = {
                "item_id": item_id,
                "player": parsed["player"],
                "overall": parsed["overall"],
                "rarity_id": rarity_id,
                "version": parsed["version"],
            }

    return cards


def extract_all_possible_cards(
    html,
    rarity_id,
):
    """
    Secondo metodo di sicurezza.

    Se l'Item ID non è direttamente vicino
    all'immagine, cerchiamo nei blocchi JSON/HTML.
    """

    cards = extract_cards_from_html(
        html,
        rarity_id,
    )

    if cards:
        return cards

    # --------------------------------------------------------
    # Fallback: cerca blocchi che contengono
    # player card + Item ID
    # --------------------------------------------------------

    item_ids = extract_item_ids(
        html
    )

    if not item_ids:
        return {}

    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    images = soup.find_all("img")

    parsed_players = []

    for img in images:

        alt = clean_text(
            img.get("alt", "")
        )

        parsed = parse_alt(
            alt
        )

        if parsed:
            parsed_players.append(
                parsed
            )

    if not parsed_players:
        return {}

    # Nel fallback utilizziamo solamente
    # dati trovati nella stessa pagina.
    #
    # Non inventiamo Item ID o giocatori.

    return cards


def load_database():
    if not OUTPUT_FILE.exists():
        return {}

    try:

        with OUTPUT_FILE.open(
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
            "Could not read existing "
            f"database: {error}"
        )

    return {}


def save_database(database):
    def sort_key(item):
        text = str(item)

        if text.isdigit():
            return (
                0,
                int(text),
            )

        return (
            1,
            text,
        )

    ordered = {}

    for item_id in sorted(
        database.keys(),
        key=sort_key,
    ):
        ordered[str(item_id)] = (
            database[item_id]
        )

    with OUTPUT_FILE.open(
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            ordered,
            file,
            ensure_ascii=False,
            indent=2,
        )

    print()
    print("=" * 60)
    print("DATABASE SAVED")
    print("=" * 60)
    print(
        f"Total cards: "
        f"{len(ordered)}"
    )
    print(
        f"File: {OUTPUT_FILE}"
    )
    print("=" * 60)


def main():

    print()
    print("=" * 60)
    print("FC 27 SPECIAL CARD DATABASE")
    print("=" * 60)

    print()
    print(
        "Rarity IDs:"
    )

    for rarity_id in RARITY_IDS:
        print(
            f"  - {rarity_id}"
        )

    print()
    print(
        "IMPORTANT:"
    )
    print(
        "Only the six supplied rarity IDs "
        "will be requested."
    )
    print(
        "No /rarities/ archive scanning."
    )
    print(
        "No FC26 scanning."
    )

    database = load_database()

    print()
    print(
        f"Existing database cards: "
        f"{len(database)}"
    )

    total_new = 0

    empty_pages = 0

    # ========================================================
    # SCAN PAGES
    # ========================================================

    for page_number in range(
        1,
        MAX_PAGES + 1,
    ):

        try:

            html = get_page(
                page_number
            )

        except Exception as error:

            print()
            print(
                f"ERROR on page "
                f"{page_number}: "
                f"{error}"
            )

            break

        cards = extract_all_possible_cards(
            html,
            rarity_id=",".join(
                str(x)
                for x in RARITY_IDS
            ),
        )

        print(
            f"Cards detected: "
            f"{len(cards)}"
        )

        before = len(
            database
        )

        for item_id, card in cards.items():

            database[
                str(item_id)
            ] = card

        added = (
            len(database)
            - before
        )

        total_new += added

        print(
            f"New cards: +{added}"
        )

        # ----------------------------------------------------
        # Se una pagina non contiene carte,
        # consideriamo terminata la paginazione.
        # ----------------------------------------------------

        if not cards:

            empty_pages += 1

        else:

            empty_pages = 0

        if empty_pages >= 2:

            print()
            print(
                "Two consecutive empty "
                "pages detected."
            )

            print(
                "Stopping pagination."
            )

            break

        time.sleep(
            REQUEST_DELAY
        )

    # ========================================================
    # SAVE
    # ========================================================

    save_database(
        database
    )

    print()
    print("=" * 60)
    print("BUILD COMPLETE")
    print("=" * 60)
    print(
        f"New cards this run: "
        f"{total_new}"
    )
    print(
        f"Total cards: "
        f"{len(database)}"
    )
    print("=" * 60)


if __name__ == "__main__":
    main()