import json
import re
import time
from pathlib import Path
from urllib.parse import quote, urljoin

import requests
from bs4 import BeautifulSoup


BASE_URL = "https://www.fut.gg"
PLAYERS_URL = f"{BASE_URL}/players/"
OUTPUT_FILE = Path("card_database.json")

# SOLO queste rarity
RARITY_IDS = [3, 71, 22, 8, 72, 12]

MAX_PAGES = 100

PAGE_DELAY = 0.4
DETAIL_DELAY = 0.25

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
# UTILS
# ============================================================

def clean_text(value):
    if value is None:
        return ""

    return re.sub(r"\s+", " ", str(value)).strip()


def build_url(page):
    rarity_json = json.dumps(
        RARITY_IDS,
        separators=(",", ":")
    )

    encoded = quote(
        rarity_json,
        safe=""
    )

    return (
        f"{PLAYERS_URL}"
        f"?page={page}"
        f"&rarity_id={encoded}"
    )


def normalize_url(url):
    if not url:
        return ""

    url = url.strip()

    if url.startswith("/"):
        url = urljoin(BASE_URL, url)

    if not url.startswith("http"):
        return ""

    return url.split("?")[0].rstrip("/")


def extract_item_id_from_url(url):
    if not url:
        return None

    match = re.search(
        r"/27-(\d+)",
        url,
        re.IGNORECASE
    )

    if not match:
        return None

    return match.group(1)


def extract_item_ids(text):
    if not text:
        return set()

    text = str(text)

    patterns = [
        r"/27-(\d+)",
        r"\b27-(\d+)\b",
        r'futgg-player-item-card/27-(\d+)',
        r'"itemId"\s*:\s*"?(\\?\d+)',
        r'"item_id"\s*:\s*"?(\\?\d+)',
        r'"itemID"\s*:\s*"?(\\?\d+)',
        r'data-item-id=["\'](\d+)',
    ]

    results = set()

    for pattern in patterns:
        for match in re.findall(pattern, text, re.IGNORECASE):
            value = str(match).replace("\\", "")

            if value.isdigit():
                results.add(value)

    return results


# ============================================================
# FINISH
# ============================================================

def detect_finish(text):
    text = clean_text(text).lower()

    if (
        "pristine holographic" in text
        or "pristine holo" in text
    ):
        return "PRISTINE HOLO"

    if (
        "standard holographic" in text
        or "holographic" in text
        or text.endswith(" holo")
        or text == "holo"
    ):
        return "HOLO"

    return "BASE"


# ============================================================
# PLAYER / OVERALL / RARITY
# ============================================================

def extract_player_from_html(soup, html):
    # 1. JSON name
    patterns = [
        r'"name"\s*:\s*"([^"]+)"',
        r'"playerName"\s*:\s*"([^"]+)"',
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            html,
            re.IGNORECASE
        )

        if match:
            name = clean_text(match.group(1))

            if (
                name
                and name.lower() != "players"
                and name.lower() != "player"
            ):
                return name

    # 2. title
    title = soup.title

    if title:
        title_text = clean_text(
            title.get_text()
        )

        match = re.match(
            r"(.+?)\s+(?:FC 27|EA FC 27)",
            title_text,
            re.IGNORECASE
        )

        if match:
            name = clean_text(match.group(1))

            if (
                name
                and name.lower() != "players"
            ):
                return name

    # 3. H1
    h1 = soup.find("h1")

    if h1:
        text = clean_text(
            h1.get_text(" ", strip=True)
        )

        text = re.sub(
            r"\s+-\s+.*$",
            "",
            text
        )

        if (
            text
            and text.lower() != "players"
        ):
            return text

    return ""


def extract_overall(text):
    patterns = [
        r"\b(\d{2,3})\s*OVR\b",
        r'"overall"\s*:\s*(\d{2,3})',
        r'"rating"\s*:\s*(\d{2,3})',
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.IGNORECASE
        )

        if match:

            try:
                value = int(match.group(1))

                if 40 <= value <= 99:
                    return value

            except Exception:
                pass

    return None


def extract_rarity(text):
    patterns = [
        r'"rarity"\s*:\s*"([^"]+)"',
        r'"rarityName"\s*:\s*"([^"]+)"',
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.IGNORECASE
        )

        if match:
            rarity = clean_text(
                match.group(1)
            )

            if (
                rarity
                and rarity.lower() != "players"
            ):
                return rarity

    # fallback: known names
    known = [
        "Future Stars",
        "Base Hero",
        "Base Icon",
        "Destined for Glory",
    ]

    lower = text.lower()

    for rarity in known:

        if rarity.lower() in lower:
            return rarity

    return ""


# ============================================================
# RARITY ID
# ============================================================

def extract_rarity_id(text):
    patterns = [
        r'"rarityId"\s*:\s*(\d+)',
        r'"rarity_id"\s*:\s*(\d+)',
        r'"rarityID"\s*:\s*(\d+)',
        r'data-rarity-id=["\'](\d+)',
    ]

    found = []

    for pattern in patterns:

        for match in re.findall(
            pattern,
            text,
            re.IGNORECASE
        ):

            try:
                value = int(match)

                if value in RARITY_IDS:
                    found.append(value)

            except Exception:
                pass

    if found:
        return found[0]

    return None


# ============================================================
# CARD LINKS
# ============================================================

def find_fc27_card_links(soup):
    links = {}

    for a in soup.find_all("a"):

        href = a.get("href")

        if not href:
            continue

        url = normalize_url(href)

        if not url:
            continue

        if "/players/" not in url:
            continue

        item_id = extract_item_id_from_url(url)

        if not item_id:
            continue

        links[item_id] = url

    return links


# ============================================================
# LIST PAGE
# ============================================================

def parse_list_page(html):

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    cards = {}

    # --------------------------------------------------------
    # LINKS
    # --------------------------------------------------------

    links = find_fc27_card_links(soup)

    print(
        f"FC27 card links found: {len(links)}"
    )

    # --------------------------------------------------------
    # IMAGES
    # --------------------------------------------------------

    images = soup.find_all("img")

    print(
        f"Images found: {len(images)}"
    )

    for img in images:

        alt = clean_text(
            img.get("alt", "")
        )

        if not alt:
            continue

        if alt.lower() == "player card":
            continue

        # Example:
        # Gisele Thompson - 87 - Future Stars

        match = re.match(
            r"(.+?)\s*-\s*(\d{2,3})\s*-\s*(.+)",
            alt
        )

        if not match:
            continue

        player = clean_text(
            match.group(1)
        )

        if player.lower() == "players":
            continue

        try:
            overall = int(
                match.group(2)
            )
        except Exception:
            continue

        version = clean_text(
            match.group(3)
        )

        item_ids = set()

        # image attributes
        for attr in [
            "src",
            "data-src",
            "data-lazy-src",
            "data-original",
            "srcset",
            "data-srcset",
        ]:

            value = img.get(attr)

            if value:
                item_ids.update(
                    extract_item_ids(value)
                )

        # parent HTML
        current = img

        for _ in range(8):

            if current is None:
                break

            try:
                current_html = str(
                    current
                )
            except Exception:
                current_html = ""

            item_ids.update(
                extract_item_ids(
                    current_html
                )
            )

            current = current.parent

        for item_id in item_ids:

            if item_id not in cards:

                cards[item_id] = {
                    "item_id": item_id,
                    "player": player,
                    "overall": overall,
                    "rarity": version,
                    "version": version,
                    "finish": detect_finish(
                        version
                    ),
                    "detail_url": None,
                }

    # --------------------------------------------------------
    # MERGE LINKS
    # --------------------------------------------------------

    for item_id, url in links.items():

        if item_id in cards:

            cards[item_id][
                "detail_url"
            ] = url

        else:

            cards[item_id] = {
                "item_id": item_id,
                "player": "",
                "overall": None,
                "rarity": "",
                "version": "",
                "finish": "BASE",
                "detail_url": url,
            }

    return cards


# ============================================================
# DETAIL PAGE
# ============================================================

def parse_detail_page(
    html,
    item_id,
    fallback
):

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    full_text = clean_text(
        soup.get_text(
            " ",
            strip=True
        )
    )

    # --------------------------------------------------------
    # PLAYER
    # --------------------------------------------------------

    player = extract_player_from_html(
        soup,
        html
    )

    if (
        not player
        or player.lower() == "players"
    ):
        player = fallback.get(
            "player",
            ""
        )

    # --------------------------------------------------------
    # OVERALL
    # --------------------------------------------------------

    overall = extract_overall(
        full_text
    )

    if overall is None:
        overall = fallback.get(
            "overall"
        )

    # --------------------------------------------------------
    # RARITY
    # --------------------------------------------------------

    rarity = extract_rarity(
        html
    )

    if not rarity:
        rarity = fallback.get(
            "rarity",
            ""
        )

    # --------------------------------------------------------
    # RARITY ID
    # --------------------------------------------------------

    rarity_id = extract_rarity_id(
        html
    )

    if rarity_id is None:
        rarity_id = fallback.get(
            "rarity_id"
        )

    # --------------------------------------------------------
    # FINISH
    #
    # IMPORTANT:
    # Don't classify from the entire page.
    # FUT.GG pages can mention other versions.
    # --------------------------------------------------------

    finish_text = ""

    if soup.title:
        finish_text += " " + clean_text(
            soup.title.get_text()
        )

    h1 = soup.find("h1")

    if h1:
        finish_text += " " + clean_text(
            h1.get_text(
                " ",
                strip=True
            )
        )

    # Search headings near current card
    for tag in soup.find_all(
        ["h1", "h2", "h3"]
    ):

        txt = clean_text(
            tag.get_text(
                " ",
                strip=True
            )
        )

        if (
            "Holographic" in txt
            or "Holo" in txt
            or "Future Stars" in txt
            or "Base Hero" in txt
            or "Base Icon" in txt
        ):
            finish_text += " " + txt

    finish = detect_finish(
        finish_text
    )

    # --------------------------------------------------------
    # VERSION
    # --------------------------------------------------------

    version = rarity

    return {
        "item_id": str(item_id),
        "player": player,
        "overall": overall,
        "rarity_id": rarity_id,
        "rarity": rarity,
        "version": version,
        "finish": finish,
    }


# ============================================================
# OTHER VERSIONS
# ============================================================

def extract_other_version_urls(
    html
):

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    results = {}

    for a in soup.find_all("a"):

        href = a.get("href")

        if not href:
            continue

        url = normalize_url(
            href
        )

        if not url:
            continue

        # ONLY FUT.GG player cards
        if "/players/" not in url:
            continue

        # ONLY FC27
        item_id = extract_item_id_from_url(
            url
        )

        if not item_id:
            continue

        # Only FC27 card URLs
        if "/27-" not in url:
            continue

        results[item_id] = url

    return results


# ============================================================
# DETAIL FETCH
# ============================================================

def fetch_detail(
    item_id,
    url,
    fallback
):

    print(
        f"  Detail {item_id}: {url}"
    )

    try:

        response = session.get(
            url,
            timeout=45
        )

        response.raise_for_status()

        result = parse_detail_page(
            response.text,
            item_id,
            fallback
        )

        other_urls = (
            extract_other_version_urls(
                response.text
            )
        )

        result["_other_urls"] = (
            other_urls
        )

        return result

    except Exception as error:

        print(
            f"  ERROR: {error}"
        )

        return None


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print("=" * 70)
    print("FC 27 SPECIAL CARD DATABASE BUILDER")
    print("=" * 70)

    print()
    print("RARITY IDS:")
    print(RARITY_IDS)

    print()
    print("SOURCE:")
    print(build_url(1))

    print()
    print("ONLY FC27")
    print("ONLY selected rarity IDs")
    print("BASE + HOLO + PRISTINE HOLO")

    # --------------------------------------------------------
    # DATABASE
    # --------------------------------------------------------

    database = {}

    detail_queue = {}

    empty_pages = 0

    # ========================================================
    # STEP 1
    # SCAN FILTERED PLAYER PAGES
    # ========================================================

    for page in range(
        1,
        MAX_PAGES + 1
    ):

        print()
        print("-" * 70)
        print(
            f"PAGE {page}"
        )
        print("-" * 70)

        url = build_url(page)

        print(
            f"Fetching: {url}"
        )

        try:

            response = session.get(
                url,
                timeout=45
            )

            response.raise_for_status()

        except Exception as error:

            print(
                f"ERROR: {error}"
            )

            break

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

                existing = database[
                    item_id
                ]

                for key in [
                    "player",
                    "overall",
                    "rarity",
                    "version",
                    "detail_url",
                ]:

                    if (
                        not existing.get(key)
                        and card.get(key)
                    ):
                        existing[key] = (
                            card[key]
                        )

            if card.get(
                "detail_url"
            ):

                detail_queue[
                    item_id
                ] = card[
                    "detail_url"
                ]

        added = (
            len(database) - before
        )

        print(
            f"New cards: +{added}"
        )

        if len(page_cards) == 0:

            empty_pages += 1

        else:

            empty_pages = 0

        if empty_pages >= 2:

            print()
            print(
                "Two empty pages."
            )

            break

        time.sleep(
            PAGE_DELAY
        )

    # ========================================================
    # STEP 2
    # SCAN DETAIL PAGES
    # ========================================================

    print()
    print("=" * 70)
    print("SCANNING CARD DETAILS")
    print("=" * 70)

    processed = set()

    while detail_queue:

        item_id, url = (
            detail_queue.popitem()
        )

        item_id = str(item_id)

        if item_id in processed:
            continue

        processed.add(
            item_id
        )

        fallback = database.get(
            item_id,
            {}
        )

        print()
        print(
            f"[{len(processed)}] "
            f"{fallback.get('player', '')} "
            f"ID {item_id}"
        )

        result = fetch_detail(
            item_id,
            url,
            fallback
        )

        if not result:
            continue

        # ----------------------------------------------------
        # UPDATE CURRENT CARD
        # ----------------------------------------------------

        current = database.setdefault(
            item_id,
            {
                "item_id": item_id
            }
        )

        if result.get(
            "player"
        ):
            current["player"] = (
                result["player"]
            )

        if result.get(
            "overall"
        ) is not None:
            current["overall"] = (
                result["overall"]
            )

        if result.get(
            "rarity"
        ):
            current["rarity"] = (
                result["rarity"]
            )

        if result.get(
            "version"
        ):
            current["version"] = (
                result["version"]
            )

        if result.get(
            "rarity_id"
        ) is not None:
            current["rarity_id"] = (
                result["rarity_id"]
            )

        current["finish"] = (
            result["finish"]
        )

        # ----------------------------------------------------
        # OTHER VERSIONS
        # ----------------------------------------------------

        other_urls = result.get(
            "_other_urls",
            {}
        )

        for other_id, other_url in (
            other_urls.items()
        ):

            other_id = str(
                other_id
            )

            # Already processed
            if other_id in processed:
                continue

            # Don't crawl the same URL twice
            if other_id not in detail_queue:

                detail_queue[
                    other_id
                ] = other_url

            # Create placeholder
            if other_id not in database:

                database[other_id] = {
                    "item_id": other_id,
                    "player": current.get(
                        "player",
                        ""
                    ),
                    "overall": current.get(
                        "overall"
                    ),
                    "rarity_id": current.get(
                        "rarity_id"
                    ),
                    "rarity": current.get(
                        "rarity",
                        ""
                    ),
                    "version": current.get(
                        "version",
                        ""
                    ),
                    "finish": "BASE",
                }

        time.sleep(
            DETAIL_DELAY
        )

    # ========================================================
    # STEP 3
    # CLEAN
    # ========================================================

    print()
    print("=" * 70)
    print("CLEANING DATABASE")
    print("=" * 70)

    cleaned = {}

    for item_id, card in database.items():

        item_id = str(
            item_id
        )

        if not item_id.isdigit():
            continue

        player = clean_text(
            card.get(
                "player",
                ""
            )
        )

        # NEVER allow "Players"
        if (
            not player
            or player.lower() == "players"
            or player.lower() == "player"
        ):
            continue

        overall = card.get(
            "overall"
        )

        if overall is None:
            continue

        try:
            overall = int(
                overall
            )
        except Exception:
            continue

        if not (
            40 <= overall <= 99
        ):
            continue

        rarity_id = card.get(
            "rarity_id"
        )

        # IMPORTANT:
        # Only selected rarity IDs
        if rarity_id is not None:

            try:
                rarity_id = int(
                    rarity_id
                )
            except Exception:
                rarity_id = None

        rarity = clean_text(
            card.get(
                "rarity",
                ""
            )
        )

        version = clean_text(
            card.get(
                "version",
                ""
            )
        )

        finish = card.get(
            "finish",
            "BASE"
        )

        if finish not in [
            "BASE",
            "HOLO",
            "PRISTINE HOLO",
        ]:
            finish = "BASE"

        cleaned[item_id] = {
            "item_id": item_id,
            "player": player,
            "overall": overall,
            "rarity_id": rarity_id,
            "rarity": rarity,
            "version": version,
            "finish": finish,
        }

    database = cleaned

    # ========================================================
    # MANUAL VERIFIED CARDS
    #
    # These are cards we explicitly verified.
    # ========================================================

    verified_cards = {

        # ----------------------------------------------------
        # GISELE THOMPSON
        # ----------------------------------------------------

        "50606461": {
            "item_id": "50606461",
            "player": "Gisele Thompson",
            "overall": 87,
            "rarity_id": 12,
            "rarity": "Future Stars",
            "version": "Future Stars",
            "finish": "BASE",
        },

        "67383677": {
            "item_id": "67383677",
            "player": "Gisele Thompson",
            "overall": 87,
            "rarity_id": 12,
            "rarity": "Future Stars",
            "version": "Future Stars",
            "finish": "HOLO",
        },

        # ----------------------------------------------------
        # PARIS BRUNNER
        # ----------------------------------------------------

        "50605774": {
            "item_id": "50605774",
            "player": "Paris Brunner",
            "overall": 88,
            "rarity_id": 12,
            "rarity": "Future Stars",
            "version": "Future Stars",
            "finish": "BASE",
        },

        "67382990": {
            "item_id": "67382990",
            "player": "Paris Brunner",
            "overall": 88,
            "rarity_id": 12,
            "rarity": "Future Stars",
            "version": "Future Stars",
            "finish": "PRISTINE HOLO",
        },
    }

    for item_id, card in (
        verified_cards.items()
    ):
        database[item_id] = card

    # ========================================================
    # SORT
    # ========================================================

    ordered = {}

    def sort_key(value):
        value = str(value)

        if value.isdigit():
            return (
                0,
                int(value)
            )

        return (
            1,
            value
        )

    for item_id in sorted(
        database,
        key=sort_key
    ):

        ordered[item_id] = (
            database[item_id]
        )

    # ========================================================
    # SAVE
    # ========================================================

    with OUTPUT_FILE.open(
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            ordered,
            file,
            ensure_ascii=False,
            indent=2
        )

    # ========================================================
    # STATS
    # ========================================================

    players = set()

    finishes = {
        "BASE": 0,
        "HOLO": 0,
        "PRISTINE HOLO": 0,
    }

    rarity_counts = {}

    for card in ordered.values():

        players.add(
            card["player"]
        )

        finish = card.get(
            "finish",
            "BASE"
        )

        if finish in finishes:
            finishes[finish] += 1

        rarity_id = card.get(
            "rarity_id"
        )

        if rarity_id is not None:

            rarity_counts[
                rarity_id
            ] = (
                rarity_counts.get(
                    rarity_id,
                    0
                ) + 1
            )

    # ========================================================
    # OUTPUT
    # ========================================================

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
    print("FINISHES")

    print(
        f"BASE: "
        f"{finishes['BASE']}"
    )

    print(
        f"HOLO: "
        f"{finishes['HOLO']}"
    )

    print(
        f"PRISTINE HOLO: "
        f"{finishes['PRISTINE HOLO']}"
    )

    print()
    print("RARITY IDS")

    for rarity_id in sorted(
        rarity_counts
    ):

        print(
            f"{rarity_id}: "
            f"{rarity_counts[rarity_id]}"
        )

    print()
    print("VERIFIED NEW CARDS")

    for item_id in [
        "50606461",
        "67383677",
        "50605774",
        "67382990",
    ]:

        if item_id in ordered:

            card = ordered[
                item_id
            ]

            print(
                f"- "
                f"{card['player']} "
                f"{card['overall']} "
                f"{card['finish']} "
                f"ID {item_id}"
            )

    print()
    print(
        f"File: {OUTPUT_FILE}"
    )

    print("=" * 70)
    print("BUILD COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()