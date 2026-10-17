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


def print_card(img, number):

    print()
    print("=" * 100)
    print(f"CARD {number}")
    print("=" * 100)

    print("ALT:")
    print(repr(img.get("alt")))

    print()
    print("SRC:")
    print(repr(img.get("src")))

    print()
    print("IMG ATTRIBUTES:")

    for key, value in img.attrs.items():
        print(f"  {key} = {value!r}")

    print()
    print("PARENT:")

    parent = img.parent

    if parent:
        print(parent.name)
        print(parent.attrs)

    print()
    print("ANCESTORS:")

    current = img.parent

    level = 1

    while current and level <= 8:

        print()
        print(f"--- LEVEL {level}: <{current.name}> ---")
        print("ATTRIBUTES:")
        print(current.attrs)

        html = str(current)

        if len(html) > 8000:
            html = html[:8000] + "\n...[TRUNCATED]..."

        print("HTML:")
        print(html)

        current = current.parent
        level += 1


def debug_page(name, url):

    print()
    print("#" * 100)
    print(name)
    print(url)
    print("#" * 100)

    try:

        response = requests.get(
            url,
            headers=HEADERS,
            timeout=30
        )

        print("STATUS:", response.status_code)
        print("HTML LENGTH:", len(response.text))

        response.raise_for_status()

    except Exception as e:

        print("REQUEST ERROR:", repr(e))
        return

    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )

    # ------------------------------------------------------------------
    # 1. Cerchiamo il testo "Cheapest grade"
    # ------------------------------------------------------------------

    print()
    print("=" * 100)
    print("SEARCHING FOR 'CHEAPEST GRADE'")
    print("=" * 100)

    cheapest_nodes = []

    for element in soup.find_all(string=re.compile(
        r"Cheapest grade",
        re.IGNORECASE
    )):

        cheapest_nodes.append(element)

    print(
        "Cheapest grade occurrences:",
        len(cheapest_nodes)
    )

    # ------------------------------------------------------------------
    # 2. Per ogni occorrenza analizziamo i parent
    # ------------------------------------------------------------------

    for i, text_node in enumerate(
        cheapest_nodes,
        start=1
    ):

        print()
        print("-" * 100)
        print(
            f"CHEAPEST GRADE OCCURRENCE #{i}"
        )
        print("-" * 100)

        element = text_node.parent

        if not element:
            continue

        print(
            "TEXT:",
            repr(text_node.strip())
        )

        current = element

        for level in range(1, 8):

            if not current:
                break

            print()
            print(
                f"LEVEL {level}: <{current.name}>"
            )

            print(
                "ATTRS:",
                current.attrs
            )

            html = str(current)

            if len(html) > 12000:
                html = (
                    html[:12000]
                    + "\n...[TRUNCATED]..."
                )

            print(html)

            current = current.parent

    # ------------------------------------------------------------------
    # 3. Tutte le immagini con ALT da carta
    # ------------------------------------------------------------------

    print()
    print("=" * 100)
    print("ALL CARD-LIKE IMAGES")
    print("=" * 100)

    cards = []

    for img in soup.find_all("img"):

        alt = img.get("alt")

        parsed = parse_card_alt(alt)

        if parsed:

            cards.append(
                (
                    img,
                    parsed
                )
            )

    print(
        "CARD-LIKE IMAGES:",
        len(cards)
    )

    for number, (img, parsed) in enumerate(
        cards,
        start=1
    ):

        print()
        print(
            f"{number}.",
            parsed
        )

        print(
            "ALT:",
            repr(img.get("alt"))
        )

        print(
            "SRC:",
            repr(img.get("src"))
        )

    # ------------------------------------------------------------------
    # 4. Cerchiamo nel RAW HTML la parola Holographic
    # ------------------------------------------------------------------

    print()
    print("=" * 100)
    print("HOLOGRAPHIC SEARCH")
    print("=" * 100)

    raw = response.text

    matches = list(
        re.finditer(
            r"holographic",
            raw,
            re.IGNORECASE
        )
    )

    print(
        "Occurrences of 'holographic':",
        len(matches)
    )

    for i, match in enumerate(
        matches[:20],
        start=1
    ):

        start = max(
            0,
            match.start() - 500
        )

        end = min(
            len(raw),
            match.end() + 1000
        )

        print()
        print(
            f"--- Holographic occurrence {i} ---"
        )

        print(
            raw[start:end]
        )


def main():

    print()
    print(
        "FUT.GG DEEP HTML DEBUGGER"
    )
    print(
        "========================="
    )

    for name, url in PAGES.items():

        debug_page(
            name,
            url
        )


if __name__ == "__main__":

    main()