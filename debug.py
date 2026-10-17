import requests
from bs4 import BeautifulSoup
import re


PAGES = {
    "HEROES": "https://www.fut.gg/fut-gallery/rarities/heroes/",
    "SEASON 1": "https://www.fut.gg/fut-gallery/rarities/season-1/",
    "HOLOGRAPHICS": "https://www.fut.gg/fut-gallery/rarities/holographics/",
}


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/xml;q=0.9,image/avif,image/webp,"
        "image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


CARD_PATTERN = re.compile(
    r"^(.*?)\s*-\s*(\d{2,3})\s*-\s*(.+)$"
)


def parse_card_alt(alt):

    if not alt:
        return None

    match = CARD_PATTERN.match(alt.strip())

    if not match:
        return None

    return {
        "name": match.group(1).strip(),
        "rating": int(match.group(2)),
        "type": match.group(3).strip(),
    }


def inspect_card(img, number):

    parsed = parse_card_alt(img.get("alt"))

    print()
    print("=" * 100)
    print(f"CARD #{number}")
    print("=" * 100)

    print("PARSED:")
    print(parsed)

    print()
    print("ALT:")
    print(repr(img.get("alt")))

    print()
    print("SRC:")
    print(repr(img.get("src")))

    print()
    print("ALL IMG ATTRIBUTES:")

    for key, value in img.attrs.items():
        print(f"{key} = {value!r}")

    print()
    print("PARENT CHAIN:")

    current = img

    for level in range(1, 7):

        current = current.parent

        if not current:
            break

        print()
        print(f"--- LEVEL {level}: <{current.name}> ---")
        print("ATTRIBUTES:")
        print(current.attrs)

        html = str(current)

        if len(html) > 6000:
            html = html[:6000] + "\n...[TRUNCATED]..."

        print("HTML:")
        print(html)


def debug_page(page_name, url):

    print()
    print("#" * 110)
    print(page_name)
    print(url)
    print("#" * 110)

    try:

        response = requests.get(
            url,
            headers=HEADERS,
            timeout=30
        )

        print("HTTP STATUS:", response.status_code)
        print("HTML LENGTH:", len(response.text))

        response.raise_for_status()

    except Exception as e:

        print("REQUEST ERROR:")
        print(repr(e))
        return

    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )

    # ============================================================
    # FIND LINEUP
    # ============================================================

    print()
    print("=" * 110)
    print("FINDING LINEUP")
    print("=" * 110)

    lineup = soup.find(
        attrs={
            "aria-label": "Lineup"
        }
    )

    if not lineup:

        print("❌ LINEUP NOT FOUND")

        return

    print("✅ LINEUP FOUND")

    print()
    print("LINEUP TAG:")
    print(lineup.name)

    print()
    print("LINEUP ATTRIBUTES:")
    print(lineup.attrs)

    # ============================================================
    # ALL IMAGES INSIDE LINEUP
    # ============================================================

    images = lineup.find_all("img")

    print()
    print("=" * 110)
    print("IMAGES INSIDE LINEUP")
    print("=" * 110)

    print("TOTAL IMAGES:", len(images))

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

    print()
    print("CARD-LIKE IMAGES:", len(cards))

    for number, (img, parsed) in enumerate(
        cards,
        start=1
    ):

        print()
        print(
            f"{number}. "
            f"{parsed['name']} | "
            f"{parsed['rating']} | "
            f"{parsed['type']}"
        )

        print(
            "ALT:",
            repr(img.get("alt"))
        )

        print(
            "SRC:",
            repr(img.get("src"))
        )

    # ============================================================
    # EXPECTED NUMBER
    # ============================================================

    expected = {
        "HEROES": 5,
        "SEASON 1": 10,
        "HOLOGRAPHICS": 5,
    }

    wanted = expected.get(page_name)

    print()
    print("=" * 110)
    print("COUNT CHECK")
    print("=" * 110)

    print("EXPECTED:", wanted)
    print("FOUND:", len(cards))

    if wanted == len(cards):

        print("✅ CORRECT NUMBER")

    else:

        print("❌ WRONG NUMBER")

    # ============================================================
    # SEARCH NAMES IN WHOLE HTML
    # ============================================================

    print()
    print("=" * 110)
    print("SEARCHING IMPORTANT PLAYERS IN RAW HTML")
    print("=" * 110)

    important_names = [
        "Jacobo Ramón",
        "Nico Paz",
        "Cucurella",
        "Harder",
        "Mora",
        "Bonny",
        "Undav",
        "Bischof",
        "Yohannes",
        "Šašić",
        "Litmanen",
        "Mascherano",
        "Milito",
        "Angerer",
        "Prinz",
        "Baresi",
        "Foudy",
        "Moore",
    ]

    raw = response.text

    for name in important_names:

        if name.lower() in raw.lower():

            print("FOUND:", name)

        else:

            print("NOT FOUND:", name)

    # ============================================================
    # HOLOGRAPHIC DATA
    # ============================================================

    print()
    print("=" * 110)
    print("HOLOGRAPHIC / HOLO DATA")
    print("=" * 110)

    patterns = [
        "holographic",
        "holo",
        "pristine",
        "regular",
        "rarity",
        "itemType",
        "cardType",
        "version",
    ]

    for pattern in patterns:

        matches = list(
            re.finditer(
                re.escape(pattern),
                raw,
                re.IGNORECASE
            )
        )

        print(
            f"{pattern}: {len(matches)} occurrences"
        )

        for match in matches[:3]:

            start = max(
                0,
                match.start() - 250
            )

            end = min(
                len(raw),
                match.end() + 500
            )

            print()
            print(
                raw[start:end]
            )

    # ============================================================
    # FULL LINEUP HTML
    # ============================================================

    print()
    print("=" * 110)
    print("LINEUP HTML")
    print("=" * 110)

    lineup_html = str(lineup)

    print(
        "LINEUP HTML LENGTH:",
        len(lineup_html)
    )

    if len(lineup_html) > 30000:

        print(
            lineup_html[:30000]
        )

        print()
        print("...[LINEUP HTML TRUNCATED]...")

    else:

        print(lineup_html)

    # ============================================================
    # DEEP INSPECTION
    # ============================================================

    print()
    print("=" * 110)
    print("DEEP CARD INSPECTION")
    print("=" * 110)

    for number, (img, parsed) in enumerate(
        cards,
        start=1
    ):

        inspect_card(
            img,
            number
        )


def main():

    print()
    print("FUT.GG LINEUP DEBUGGER")
    print("======================")

    for page_name, url in PAGES.items():

        debug_page(
            page_name,
            url
        )


if __name__ == "__main__":
    main()