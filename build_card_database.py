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

# SOLO queste 6 rarity
RARITY_IDS = [3, 71, 22, 8, 72, 12]

OUTPUT_FILE = Path("card_database.json")

MAX_PAGES = 100

# Pausa tra le pagine della lista
REQUEST_DELAY = 0.35

# Pausa tra le pagine individuali dei giocatori
DETAIL_DELAY = 0.20

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
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
        r"/27-(\d{4,})(?:[./?_-]|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b27-(\d{4,})\b",
        re.IGNORECASE,
    ),
    re.compile(
        r'futgg-player-item-card/27-(\d+)',
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
        r'"itemID"\s*:\s*"?(\d+)',
        re.IGNORECASE,
    ),
    re.compile(
        r'data-item-id=["\'](\d+)',
        re.IGNORECASE,
    ),
]


ALT_PATTERN = re.compile(
    r"^\s*(.*?)\s*-\s*(\d{2,3})\s*-\s*(.*?)\s*$"
)


# URL di una carta FC27
PLAYER_CARD_URL_PATTERN = re.compile(
    r"https?://(?:www\.)?fut\.gg/players/"
    r"[^\"'\s<>]+/27-(\d+)",
    re.IGNORECASE,
)


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

    text = str(text)

    for pattern in ITEM_ID_PATTERNS:
        for match in pattern.findall(text):
            results.add(str(match))

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


# ============================================================
# FINISH DETECTION
# ============================================================

def detect_finish(text):
    text = clean_text(text).lower()

    # PRISTINE HOLO deve essere controllato prima
    if (
        "pristine holographic" in text
        or "pristine holo" in text
        or "pristine" in text
    ):
        return "PRISTINE HOLO"

    if (
        "standard holographic" in text
        or "holographic" in text
        or " holo" in text
        or text.endswith("holo")
    ):
        return "HOLO"

    return "BASE"


# ============================================================
# RARITY / VERSION CLEANUP
# ============================================================

def clean_rarity_name(version):
    version = clean_text(version)

    # Rimuove eventuali indicazioni di finish
    version = re.sub(
        r"\s*Pristine\s+Holographic\s*$",
        "",
        version,
        flags=re.IGNORECASE,
    )

    version = re.sub(
        r"\s*Standard\s+Holographic\s*$",
        "",
        version,
        flags=re.IGNORECASE,
    )

    version = re.sub(
        r"\s*Holographic\s*$",
        "",
        version,
        flags=re.IGNORECASE,
    )

    return version.strip()


# ============================================================
# CARD FROM IMAGE
# ============================================================

def parse_image(img):
    alt = clean_text(
        img.get("alt", "")
    )

    parsed = parse_player_alt(alt)

    if not parsed:
        return None

    item_ids = set()

    attributes = [
        "src",
        "data-src",
        "data-lazy-src",
        "data-original",
        "srcset",
        "data-srcset",
    ]

    for attribute in attributes:
        value = img.get(attribute)

        if value:
            item_ids.update(
                extract_item_ids(value)
            )

    # Cerca anche nell'HTML vicino all'immagine
    current = img

    for _ in range(5):
        if current is None:
            break

        try:
            source = str(current)
        except Exception:
            source = ""

        item_ids.update(
            extract_item_ids(source)
        )

        current = current.parent

    return {
        "player": parsed["player"],
        "overall": parsed["overall"],
        "version": parsed["version"],
        "item_ids": item_ids,
    }


# ============================================================
# FIND CARD LINKS
# ============================================================

def find_card_links(soup):
    """
    Recupera tutti i link alle pagine individuali
    delle carte FC27 presenti nella pagina filtrata.
    """

    links = {}

    for a in soup.find_all("a"):
        href = a.get("href")

        if not href:
            continue

        href = str(href)

        if href.startswith("/"):
            full_url = BASE_URL + href
        elif href.startswith("http"):
            full_url = href
        else:
            continue

        if "/players/" not in full_url:
            continue

        match = re.search(
            r"/27-(\d+)",
            full_url,
            re.IGNORECASE,
        )

        if not match:
            continue

        item_id = match.group(1)

        # Normalizza URL
        full_url = full_url.split("?")[0]

        links[item_id] = full_url

    return links


# ============================================================
# PARSE LIST PAGE
# ============================================================

def parse_list_page(html):
    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    cards = {}

    # --------------------------------------------------------
    # 1. Immagini
    # --------------------------------------------------------

    images = soup.find_all("img")

    print(
        f"Images found: {len(images)}"
    )

    for img in images:
        parsed = parse_image(img)

        if not parsed:
            continue

        for item_id in parsed["item_ids"]:

            item_id = str(item_id)

            # Non sovrascrivere una card già buona
            if item_id not in cards:
                cards[item_id] = {
                    "item_id": item_id,
                    "player": parsed["player"],
                    "overall": parsed["overall"],
                    "rarity": parsed["version"],
                    "version": parsed["version"],
                    "finish": detect_finish(
                        parsed["version"]
                    ),
                    "source": "players_list",
                }

    # --------------------------------------------------------
    # 2. Link delle carte
    # --------------------------------------------------------

    links = find_card_links(soup)

    print(
        f"FC27 card links found: {len(links)}"
    )

    for item_id, url in links.items():

        if item_id in cards:
            cards[item_id]["detail_url"] = url
        else:
            cards[item_id] = {
                "item_id": item_id,
                "player": "",
                "overall": None,
                "rarity": "",
                "version": "",
                "finish": "BASE",
                "detail_url": url,
                "source": "players_link",
            }

    return cards


# ============================================================
# PARSE DETAIL PAGE
# ============================================================

def parse_detail_page(
    html,
    known_item_id=None,
    fallback=None,
):
    """
    Analizza la pagina individuale FUT.GG.

    Qui possiamo distinguere:

    BASE
    HOLO
    PRISTINE HOLO

    anche quando la lista principale mostra
    solo una delle varianti.
    """

    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    text = clean_text(
        soup.get_text(" ", strip=True)
    )

    # --------------------------------------------------------
    # Item ID
    # --------------------------------------------------------

    item_ids = extract_item_ids(
        html
    )

    item_id = None

    if known_item_id:
        item_id = str(known_item_id)

    elif item_ids:
        item_id = sorted(
            item_ids,
            key=lambda x: len(str(x)),
            reverse=True,
        )[0]

    # --------------------------------------------------------
    # Player
    # --------------------------------------------------------

    player = ""

    # Cerca "Name ..."
    match = re.search(
        r'"name"\s*:\s*"([^"]+)"',
        html,
        re.IGNORECASE,
    )

    if match:
        player = clean_text(
            match.group(1)
        )

    # Fallback dal titolo
    if not player:
        title = soup.title

        if title:
            title_text = clean_text(
                title.get_text()
            )

            match = re.match(
                r"(.+?)\s+FC 27",
                title_text,
                re.IGNORECASE,
            )

            if match:
                player = clean_text(
                    match.group(1)
                )

    if not player and fallback:
        player = fallback.get(
            "player",
            "",
        )

    # --------------------------------------------------------
    # Overall
    # --------------------------------------------------------

    overall = None

    # Prima cerca OVR vicino al testo
    match = re.search(
        r"\b(\d{2,3})\s*OVR\b",
        text,
        re.IGNORECASE,
    )

    if match:
        try:
            overall = int(
                match.group(1)
            )
        except Exception:
            pass

    if overall is None and fallback:
        overall = fallback.get(
            "overall"
        )

    # --------------------------------------------------------
    # Rarity
    # --------------------------------------------------------

    rarity = ""

    match = re.search(
        r'"rarity"\s*:\s*"([^"]+)"',
        html,
        re.IGNORECASE,
    )

    if match:
        rarity = clean_text(
            match.group(1)
        )

    if not rarity and fallback:
        rarity = fallback.get(
            "rarity",
            "",
        )

    # --------------------------------------------------------
    # Finish
    # --------------------------------------------------------

    # Il testo della pagina contiene normalmente:
    #
    # Standard Holographic
    # oppure
    # Pristine Holographic
    #
    finish = detect_finish(
        text
    )

    # --------------------------------------------------------
    # Version
    # --------------------------------------------------------

    version = clean_rarity_name(
        rarity
    )

    if not version and fallback:
        version = clean_rarity_name(
            fallback.get(
                "version",
                "",
            )
        )

    return {
        "item_id": item_id,
        "player": player,
        "overall": overall,
        "rarity": version,
        "version": version,
        "finish": finish,
    }


# ============================================================
# GET OTHER VERSIONS
# ============================================================

def extract_other_version_urls(
    html,
    current_url,
):
    """
    Cerca i link delle altre versioni dello stesso giocatore.

    Esempio:
    BASE -> HOLO
    BASE -> PRISTINE HOLO
    """

    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    urls = {}

    for a in soup.find_all("a"):
        href = a.get("href")

        if not href:
            continue

        href = str(href)

        if href.startswith("/"):
            url = BASE_URL + href
        elif href.startswith("http"):
            url = href
        else:
            continue

        if "/players/" not in url:
            continue

        match = re.search(
            r"/27-(\d+)",
            url,
            re.IGNORECASE,
        )

        if not match:
            continue

        item_id = match.group(1)

        url = url.split("?")[0]

        urls[item_id] = url

    return urls


# ============================================================
# FETCH DETAIL
# ============================================================

def fetch_detail(
    url,
    item_id,
    fallback=None,
):
    print(
        f"  Detail: {url}"
    )

    try:
        response = session.get(
            url,
            timeout=45,
        )

        response.raise_for_status()

        result = parse_detail_page(
            response.text,
            known_item_id=item_id,
            fallback=fallback,
        )

        # Recupera eventuali altre versioni
        other_urls = extract_other_version_urls(
            response.text,
            url,
        )

        result["_other_urls"] = other_urls

        return result

    except Exception as error:

        print(
            f"  Detail error: {error}"
        )

        return None


# ============================================================
# MAIN DATABASE BUILDER
# ============================================================

def main():

    print()
    print("=" * 70)
    print("FC 27 SPECIAL CARD DATABASE BUILDER")
    print("=" * 70)

    print()
    print(
        "RARITY IDS:"
    )
    print(
        RARITY_IDS
    )

    print()
    print(
        "Source:"
    )
    print(
        build_url(1)
    )

    print()
    print(
        "Database mode:"
    )
    print(
        "FULL FC27 CARD CATALOG"
    )

    print()
    print(
        "Variants:"
    )
    print(
        "BASE + HOLO + PRISTINE HOLO"
    )

    print()
    print(
        "FC26:"
    )
    print(
        "DISABLED"
    )

    # --------------------------------------------------------
    # DATABASE COMPLETAMENTE NUOVO
    # --------------------------------------------------------

    database = {}

    # URL già visitati
    detail_urls = {}

    empty_pages = 0

    # ========================================================
    # STEP 1
    # SCANSIONE LISTA FILTRATA
    # ========================================================

    for page in range(
        1,
        MAX_PAGES + 1,
    ):

        try:
            url = build_url(page)

            print()
            print("-" * 70)
            print(
                f"PAGE {page}"
            )
            print("-" * 70)

            print(
                f"Fetching: {url}"
            )

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

            page_cards = parse_list_page(
                response.text
            )

            print(
                f"Cards detected: "
                f"{len(page_cards)}"
            )

            before = len(database)

            for item_id, card in page_cards.items():

                item_id = str(item_id)

                if item_id not in database:
                    database[item_id] = card

                else:
                    # Completa eventuali dati mancanti
                    existing = database[item_id]

                    for key in [
                        "player",
                        "overall",
                        "rarity",
                        "version",
                        "detail_url",
                    ]:
                        if not existing.get(key):
                            if card.get(key):
                                existing[key] = card[key]

                detail_url = card.get(
                    "detail_url"
                )

                if detail_url:
                    detail_urls[item_id] = detail_url

            added = (
                len(database)
                - before
            )

            print(
                f"New database cards: "
                f"+{added}"
            )

            if len(page_cards) == 0:
                empty_pages += 1
            else:
                empty_pages = 0

            # Due pagine vuote consecutive
            if empty_pages >= 2:
                print()
                print(
                    "Two empty pages."
                )
                print(
                    "Stopping pagination."
                )
                break

            time.sleep(
                REQUEST_DELAY
            )

        except Exception as error:

            print()
            print(
                f"ERROR page {page}:"
            )
            print(error)

            break

    # ========================================================
    # STEP 2
    # SCANSIONE PAGINE INDIVIDUALI
    # PER RECUPERARE LE VARIANTI
    # ========================================================

    print()
    print("=" * 70)
    print("SCANNING CARD DETAIL PAGES")
    print("=" * 70)

    # Prima passata:
    # tutte le URL già trovate dalla lista
    queue = dict(detail_urls)

    processed = set()

    while queue:

        item_id, url = queue.popitem()

        item_id = str(item_id)

        if item_id in processed:
            continue

        processed.add(item_id)

        fallback = database.get(
            item_id,
            {},
        )

        print()
        print(
            f"[{len(processed)}] "
            f"{fallback.get('player', '')} "
            f"ID {item_id}"
        )

        result = fetch_detail(
            url,
            item_id,
            fallback,
        )

        if not result:
            continue

        # ----------------------------------------------------
        # Aggiorna carta corrente
        # ----------------------------------------------------

        current = database.setdefault(
            item_id,
            {
                "item_id": item_id
            },
        )

        if result.get("player"):
            current["player"] = result["player"]

        if result.get("overall") is not None:
            current["overall"] = result["overall"]

        if result.get("rarity"):
            current["rarity"] = result["rarity"]

        if result.get("version"):
            current["version"] = result["version"]

        current["finish"] = result.get(
            "finish",
            current.get("finish", "BASE"),
        )

        current["detail_url"] = url

        current["source"] = "futgg_detail"

        # ----------------------------------------------------
        # ALTRE VERSIONI
        # ----------------------------------------------------

        other_urls = result.get(
            "_other_urls",
            {},
        )

        for other_id, other_url in other_urls.items():

            other_id = str(other_id)

            if other_id not in queue and other_id not in processed:
                queue[other_id] = other_url

            if other_id not in database:
                database[other_id] = {
                    "item_id": other_id,
                    "player": current.get(
                        "player",
                        "",
                    ),
                    "overall": current.get(
                        "overall"
                    ),
                    "rarity": current.get(
                        "rarity",
                        "",
                    ),
                    "version": current.get(
                        "version",
                        "",
                    ),
                    "finish": "BASE",
                    "detail_url": other_url,
                    "source": "other_version",
                }
            else:
                if not database[other_id].get(
                    "detail_url"
                ):
                    database[other_id][
                        "detail_url"
                    ] = other_url

        time.sleep(
            DETAIL_DELAY
        )

    # ========================================================
    # STEP 3
    # DEDUZIONE FINISH FINALE
    # ========================================================

    print()
    print("=" * 70)
    print("FINALIZING FINISH DATA")
    print("=" * 70)

    for item_id, card in database.items():

        text = " ".join(
            [
                str(card.get("rarity", "")),
                str(card.get("version", "")),
            ]
        )

        finish = card.get(
            "finish"
        )

        if not finish or finish == "UNKNOWN":
            finish = detect_finish(
                text
            )

        card["finish"] = finish

        # Pulisci eventuali campi interni
        card.pop(
            "_other_urls",
            None,
        )

    # ========================================================
    # STEP 4
    # FILTRO FINALE
    # ========================================================

    # Elimina record palesemente incompleti
    cleaned = {}

    for item_id, card in database.items():

        player = clean_text(
            card.get("player", "")
        )

        overall = card.get(
            "overall"
        )

        if not player:
            continue

        if overall is None:
            continue

        # Solo FC27 item IDs
        if not str(item_id).isdigit():
            continue

        cleaned[str(item_id)] = {
            "item_id": str(item_id),
            "player": player,
            "overall": int(overall),
            "rarity_id": card.get(
                "rarity_id"
            ),
            "rarity": clean_text(
                card.get("rarity", "")
            ),
            "version": clean_text(
                card.get("version", "")
            ),
            "finish": card.get(
                "finish",
                "BASE",
            ),
        }

    database = cleaned

    # ========================================================
    # SAVE
    # ========================================================

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

    # ========================================================
    # SUMMARY
    # ========================================================

    players = set()
    finishes = {
        "BASE": 0,
        "HOLO": 0,
        "PRISTINE HOLO": 0,
        "UNKNOWN": 0,
    }

    for card in ordered.values():

        players.add(
            card["player"]
        )

        finish = card.get(
            "finish",
            "UNKNOWN",
        )

        if finish not in finishes:
            finishes[finish] = 0

        finishes[finish] += 1

    print()
    print("=" * 70)
    print("DATABASE SAVED")
    print("=" * 70)

    print(
        f"Database items: "
        f"{len(ordered)}"
    )

    print(
        f"Database players: "
        f"{len(players)}"
    )

    print()
    print(
        "FINISHES:"
    )

    print(
        f"BASE: "
        f"{finishes.get('BASE', 0)}"
    )

    print(
        f"HOLO: "
        f"{finishes.get('HOLO', 0)}"
    )

    print(
        f"PRISTINE HOLO: "
        f"{finishes.get('PRISTINE HOLO', 0)}"
    )

    print(
        f"UNKNOWN: "
        f"{finishes.get('UNKNOWN', 0)}"
    )

    print()
    print(
        f"File: "
        f"{OUTPUT_FILE}"
    )

    print("=" * 70)
    print("BUILD COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()