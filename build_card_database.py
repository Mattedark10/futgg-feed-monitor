import json
import re
import time
from pathlib import Path
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup


# ============================================================
# CONFIGURATION
# ============================================================

BASE_URL = "https://www.fut.gg"
PLAYERS_URL = f"{BASE_URL}/players/"

# SOLO queste rarità fanno parte del database
RARITY_IDS = [3, 71, 22, 8, 72, 12]

OUTPUT_FILE = Path("card_database.json")

MAX_PAGES = 100
REQUEST_DELAY = 0.25

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
}


session = requests.Session()
session.headers.update(HEADERS)


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


RARITY_ID_PATTERNS = [
    re.compile(
        r'"rarityId"\s*:\s*(\d+)',
        re.IGNORECASE,
    ),
    re.compile(
        r'"rarity_id"\s*:\s*(\d+)',
        re.IGNORECASE,
    ),
    re.compile(
        r'"rarityID"\s*:\s*(\d+)',
        re.IGNORECASE,
    ),
    re.compile(
        r'data-rarity-id=["\'](\d+)',
        re.IGNORECASE,
    ),
]


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


def build_url(page):
    rarity_json = json.dumps(
        RARITY_IDS,
        separators=(",", ":"),
    )

    encoded = quote(
        rarity_json,
        safe="",
    )

    return (
        f"{PLAYERS_URL}"
        f"?page={page}"
        f"&rarity_id={encoded}"
    )


def extract_item_ids(text):
    if not text:
        return set()

    results = set()

    for pattern in ITEM_ID_PATTERNS:
        for match in pattern.findall(text):
            results.add(str(match))

    return results


def extract_rarity_ids(text):
    if not text:
        return set()

    results = set()

    for pattern in RARITY_ID_PATTERNS:
        for match in pattern.findall(text):
            try:
                rarity_id = int(match)
            except Exception:
                continue

            if rarity_id in RARITY_IDS:
                results.add(rarity_id)

    return results


def parse_player_alt(alt):
    alt = clean_text(alt)

    if not alt:
        return None

    if alt.lower() == "player card":
        return None

    match = ALT_PATTERN.match(alt)

    if not match:
        return None

    player = clean_text(match.group(1))

    try:
        overall = int(match.group(2))
    except Exception:
        return None

    version = clean_text(match.group(3))

    if not player:
        return None

    return {
        "player": player,
        "overall": overall,
        "version": version,
    }


def detect_finish(version):
    text = version.lower()

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


def find_rarity_id(element):
    """
    Cerca il rarity_id vicino alla carta.
    """

    current = element

    for _ in range(8):

        if current is None:
            break

        try:
            html = str(current)
        except Exception:
            html = ""

        ids = extract_rarity_ids(html)

        if len(ids) == 1:
            return next(iter(ids))

        current = current.parent

    return None


def find_item_ids_near_image(img):
    """
    Cerca l'Item ID sull'immagine e nei suoi
    contenitori HTML.
    """

    item_ids = set()

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

        item_ids.update(
            extract_item_ids(
                str(value)
            )
        )

    current = img

    for _ in range(8):

        if current is None:
            break

        try:
            html = str(current)
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
# PARSE PAGE
# ============================================================

def parse_page(html):
    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    database = {}

    images = soup.find_all("img")

    print(
        f"Images found: {len(images)}"
    )

    for img in images:

        alt = clean_text(
            img.get("alt", "")
        )

        parsed = parse_player_alt(
            alt
        )

        if not parsed:
            continue

        item_ids = find_item_ids_near_image(
            img
        )

        if not item_ids:
            continue

        rarity_id = find_rarity_id(
            img
        )

        # Se FUT.GG non ci ha dato il rarity_id
        # vicino alla carta, non inventiamo nulla.
        #
        # La pagina è comunque filtrata esclusivamente
        # con i 6 rarity_id richiesti.

        finish = detect_finish(
            parsed["version"]
        )

        for item_id in item_ids:

            item_id = str(item_id)

            database[item_id] = {
                "item_id": item_id,
                "player": parsed["player"],
                "overall": parsed["overall"],
                "rarity_id": rarity_id,
                "rarity": parsed["version"],
                "version": parsed["version"],
                "finish": finish,
            }

    return database


# ============================================================
# FETCH
# ============================================================

def fetch_page(page):
    url = build_url(page)

    print()
    print(
        f"Fetching page {page}:"
    )
    print(url)

    response = session.get(
        url,
        timeout=45,
    )

    response.raise_for_status()

    print(
        f"HTTP status: "
        f"{response.status_code}"
    )

    print(
        f"Downloaded: "
        f"{len(response.text)} characters"
    )

    return response.text


# ============================================================
# SAVE
# ============================================================

def save_database(database):
    ordered = {}

    def sort_key(item):
        value = str(item)

        if value.isdigit():
            return (
                0,
                int(value),
            )

        return (
            1,
            value,
        )

    for item_id in sorted(
        database,
        key=sort_key,
    ):
        ordered[item_id] = database[item_id]

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
        f"Cards: {len(ordered)}"
    )
    print(
        f"File: {OUTPUT_FILE}"
    )
    print("=" * 60)


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print("=" * 60)
    print("FC 27 SPECIAL CARD DATABASE BUILDER")
    print("=" * 60)

    print()
    print(
        "ONLY RARITY IDS:"
    )

    print(
        RARITY_IDS
    )

    print()
    print(
        "This builder scans ONLY:"
    )

    print(
        "https://www.fut.gg/players/"
    )

    print(
        "It does NOT scan /rarities/"
    )

    print(
        "It does NOT scan FC26."
    )

    print()

    # IMPORTANT:
    # partiamo da zero.
    # NON utilizziamo il vecchio database perché
    # potrebbe contenere FC26 o dati precedenti.

    database = {}

    empty_pages = 0

    for page in range(
        1,
        MAX_PAGES + 1,
    ):

        try:
            html = fetch_page(
                page
            )

        except Exception as error:

            print()
            print(
                f"ERROR on page {page}:"
            )
            print(error)

            break

        page_database = parse_page(
            html
        )

        print(
            f"Cards found on page: "
            f"{len(page_database)}"
        )

        before = len(
            database
        )

        for item_id, card in page_database.items():
            database[item_id] = card

        added = (
            len(database)
            - before
        )

        print(
            f"New unique cards: "
            f"+{added}"
        )

        if len(page_database) == 0:

            empty_pages += 1

        else:

            empty_pages = 0

        if empty_pages >= 2:

            print()
            print(
                "Two empty pages."
            )

            print(
                "Stopping."
            )

            break

        time.sleep(
            REQUEST_DELAY
        )

    save_database(
        database
    )

    print()
    print("=" * 60)
    print("BUILD COMPLETE")
    print("=" * 60)
    print(
        f"Total cards: "
        f"{len(database)}"
    )
    print("=" * 60)


if __name__ == "__main__":
    main()