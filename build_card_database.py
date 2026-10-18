import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


BASE_URL = "https://www.fut.gg"
RARITIES_URL = f"{BASE_URL}/rarities/"

HOLO_URLS = {
    "HOLO": f"{BASE_URL}/holographic-cards/?finish=holographic",
    "PRISTINE HOLO": f"{BASE_URL}/holographic-cards/?finish=pristine",
}

OUTPUT_FILE = Path("card_database.json")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# Queste NON sono carte speciali.
EXCLUDED_RARITIES = {
    "Rare",
    "Common",
    "Concepts Rare",
    "Concepts Common",
    "Concepts Special",
    "VBL Power Item",
    "ICON Swaps",
}

# Parole indicative delle promo speciali FC 27.
SPECIAL_KEYWORDS = {
    "TOTW",
    "Team of the Week",
    "POTM",
    "Hero",
    "Icon",
    "Future Stars",
    "Destined for Glory",
    "Squad Foundations",
    "Ones to Watch",
    "Base Hall of FUT",
    "Partnerships",
    "Debut International Icon",
    "Star Performer",
    "FUT Champions",
    "Season",
    "Showdown",
    "Flashback",
    "Moments",
    "Ratings Reload",
    "Gallery Excellence",
}


def get(url):
    print(f"Fetching: {url}")

    response = requests.get(
        url,
        headers=HEADERS,
        timeout=30,
    )

    response.raise_for_status()

    print(
        f"HTTP status: {response.status_code}"
    )

    print(
        f"Downloaded: {len(response.text)} characters"
    )

    return response.text


def normalise(text):
    return re.sub(
        r"\s+",
        " ",
        text or "",
    ).strip()


def extract_item_ids(text):
    ids = set()

    if not text:
        return ids

    patterns = [
        r"futgg-player-item-card/27-(\d+)",
        r"(?:^|[/_-])27-(\d+)",
        r"item[_-]?id[\"':=\s]+(\d+)",
        r'"itemId"\s*:\s*"?(\d+)',
        r'"item_id"\s*:\s*"?(\d+)',
    ]

    for pattern in patterns:
        for match in re.findall(
            pattern,
            text,
            flags=re.IGNORECASE,
        ):
            ids.add(str(match))

    return ids


def parse_player_alt(alt):
    if not alt:
        return None

    alt = normalise(alt)

    match = re.match(
        r"^(.*?)\s*-\s*(\d{2})\s*-\s*(.*?)$",
        alt,
    )

    if not match:
        return None

    player = match.group(1).strip()
    overall = int(match.group(2))
    version = match.group(3).strip()

    if player.lower() == "player card":
        return None

    return {
        "player": player,
        "overall": overall,
        "version": version,
    }


def extract_card_from_image(
    img,
    rarity,
    finish,
):
    alt = normalise(
        img.get("alt", "")
    )

    parsed = parse_player_alt(alt)

    if not parsed:
        return {}

    attributes = [
        img.get("src", ""),
        img.get("data-src", ""),
        img.get("data-lazy-src", ""),
        img.get("data-original", ""),
        img.get("srcset", ""),
        img.get("data-srcset", ""),
    ]

    item_ids = set()

    for value in attributes:
        if value:
            item_ids.update(
                extract_item_ids(str(value))
            )

    parent = img

    for _ in range(6):
        if not parent:
            break

        try:
            parent_html = str(parent)
        except Exception:
            parent_html = ""

        item_ids.update(
            extract_item_ids(parent_html)
        )

        parent = parent.parent

    results = {}

    for item_id in item_ids:
        results[str(item_id)] = {
            "item_id": str(item_id),
            "player": parsed["player"],
            "overall": parsed["overall"],
            "rarity": rarity,
            "version": parsed["version"],
            "finish": finish,
        }

    return results


def find_cards(
    html,
    rarity,
    finish="BASE",
):
    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    results = {}

    for img in soup.find_all("img"):
        cards = extract_card_from_image(
            img,
            rarity,
            finish,
        )

        for item_id, card in cards.items():
            results[item_id] = card

    return results


def is_special_rarity(name):
    name = normalise(name)

    if not name:
        return False

    if name in EXCLUDED_RARITIES:
        return False

    lowered = name.lower()

    if lowered.startswith("concept"):
        return False

    if "fc 26" in lowered:
        return False

    if "archive" in lowered:
        return False

    for keyword in SPECIAL_KEYWORDS:
        if keyword.lower() in lowered:
            return True

    return False


def extract_fc27_rarities(html):
    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    rarities = {}

    for link in soup.find_all(
        "a",
        href=True,
    ):
        href = link.get("href", "")

        match = re.match(
            r"^/rarities/([^/?#]+)/?$",
            href,
            flags=re.IGNORECASE,
        )

        if not match:
            continue

        name = normalise(
            link.get_text(
                " ",
                strip=True,
            )
        )

        if not name:
            continue

        if not is_special_rarity(name):
            continue

        url = urljoin(
            BASE_URL,
            href,
        )

        rarities[url] = {
            "name": name,
            "url": url,
        }

    return list(
        rarities.values()
    )


def extract_pagination_urls(
    html,
    base_url,
):
    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    urls = {
        base_url
    }

    for link in soup.find_all(
        "a",
        href=True,
    ):
        href = link.get("href", "")

        if "page=" not in href.lower():
            continue

        urls.add(
            urljoin(
                BASE_URL,
                href,
            )
        )

    return urls


def scan_rarity(
    rarity_name,
    rarity_url,
):
    print()
    print("=" * 60)
    print(
        f"Scanning SPECIAL RARITY: "
        f"{rarity_name}"
    )
    print(rarity_url)
    print("=" * 60)

    database = {}

    try:
        first_html = get(
            rarity_url
        )
    except Exception as error:
        print(
            f"ERROR loading rarity: "
            f"{error}"
        )
        return database

    pages = extract_pagination_urls(
        first_html,
        rarity_url,
    )

    # Proviamo le prime 20 pagine.
    for page in range(1, 21):
        separator = (
            "&"
            if "?" in rarity_url
            else "?"
        )

        pages.add(
            f"{rarity_url}"
            f"{separator}page={page}"
        )

    checked = set()

    for page_url in sorted(pages):

        if page_url in checked:
            continue

        checked.add(page_url)

        try:
            if page_url == rarity_url:
                html = first_html
            else:
                html = get(page_url)
        except Exception as error:
            print(
                f"Page error: {error}"
            )
            continue

        cards = find_cards(
            html,
            rarity=rarity_name,
            finish="BASE",
        )

        before = len(database)

        for item_id, card in cards.items():
            database[item_id] = card

        added = (
            len(database) - before
        )

        print(
            f"  Found: {len(cards)} | "
            f"New: +{added}"
        )

        time.sleep(0.15)

    print(
        f"Finished {rarity_name}: "
        f"{len(database)} unique cards"
    )

    return database


def scan_holographics():
    database = {}

    print()
    print("=" * 60)
    print("SCANNING HOLOGRAPHIC DATABASE")
    print("=" * 60)

    for finish, url in HOLO_URLS.items():

        print()
        print(
            f"Scanning {finish}..."
        )

        try:
            first_html = get(url)
        except Exception as error:
            print(
                f"ERROR: {error}"
            )
            continue

        pages = extract_pagination_urls(
            first_html,
            url,
        )

        for page in range(1, 30):
            separator = (
                "&"
                if "?" in url
                else "?"
            )

            pages.add(
                f"{url}"
                f"{separator}page={page}"
            )

        checked = set()

        for page_url in sorted(pages):

            if page_url in checked:
                continue

            checked.add(page_url)

            try:
                if page_url == url:
                    html = first_html
                else:
                    html = get(page_url)
            except Exception as error:
                print(
                    f"Page error: {error}"
                )
                continue

            cards = find_cards(
                html,
                rarity="Holographic",
                finish=finish,
            )

            for item_id, card in cards.items():
                database[item_id] = card

            print(
                f"  {finish}: "
                f"{len(cards)} cards"
            )

            time.sleep(0.15)

    print()
    print(
        f"Holographic records: "
        f"{len(database)}"
    )

    return database


def load_existing_database():
    if not OUTPUT_FILE.exists():
        return {}

    try:
        with OUTPUT_FILE.open(
            "r",
            encoding="utf-8",
        ) as file:
            data = json.load(file)

        if isinstance(data, dict):
            return data

    except Exception as error:
        print(
            f"Database read error: "
            f"{error}"
        )

    return {}


def merge_databases(
    old_database,
    new_database,
):
    merged = dict(
        old_database
    )

    for item_id, card in new_database.items():
        merged[str(item_id)] = card

    return merged


def save_database(database):
    def sort_key(item_id):
        text = str(item_id)

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
        ordered[str(item_id)] = database[
            item_id
        ]

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
    print(
        f"Saved {OUTPUT_FILE}"
    )
    print(
        f"Total unique Item IDs: "
        f"{len(ordered)}"
    )
    print("=" * 60)


def main():
    print()
    print("=" * 60)
    print(
        "FC 27 SPECIAL CARD DATABASE"
    )
    print("=" * 60)

    old_database = (
        load_existing_database()
    )

    print(
        f"Existing database: "
        f"{len(old_database)} cards"
    )

    try:
        rarities_html = get(
            RARITIES_URL
        )
    except Exception as error:
        print(
            f"Could not load rarities: "
            f"{error}"
        )
        rarities_html = ""

    rarities = []

    if rarities_html:
        rarities = (
            extract_fc27_rarities(
                rarities_html
            )
        )

    print()
    print(
        "FC 27 special rarities found: "
        f"{len(rarities)}"
    )

    for rarity in rarities:
        print(
            f"- {rarity['name']} "
            f"=> {rarity['url']}"
        )

    new_database = {}

    # Special FC 27 rarities
    for rarity in rarities:
        cards = scan_rarity(
            rarity["name"],
            rarity["url"],
        )

        new_database.update(
            cards
        )

    # Holographic cards
    holo_cards = (
        scan_holographics()
    )

    new_database.update(
        holo_cards
    )

    # Manteniamo le carte già conosciute
    # se FUT.GG temporaneamente non le mostra.
    final_database = (
        merge_databases(
            old_database,
            new_database,
        )
    )

    save_database(
        final_database
    )

    print()
    print(
        "DATABASE BUILD COMPLETE"
    )


if __name__ == "__main__":
    main()