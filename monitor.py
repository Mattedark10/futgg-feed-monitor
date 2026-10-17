import re
import requests
from bs4 import BeautifulSoup


PAGES = {
    "Heroes": "https://www.fut.gg/fut-gallery/rarities/heroes/",
    "Holographics": "https://www.fut.gg/fut-gallery/rarities/holographics/",
    "Season 1": "https://www.fut.gg/fut-gallery/rarities/season-1/",
}


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/xml;q=0.9,image/avif,"
        "image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


session = requests.Session()
session.headers.update(HEADERS)


# ============================================================
# FETCH
# ============================================================

def fetch(url):
    print()
    print("=" * 80)
    print("FETCHING")
    print(url)
    print("=" * 80)

    r = session.get(
        url,
        timeout=45
    )

    r.raise_for_status()

    print(
        f"HTTP {r.status_code}"
    )

    print(
        f"HTML length: {len(r.text)}"
    )

    return r.text


# ============================================================
# FIND LINEUP
# ============================================================

def get_lineup_section(html):
    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    headings = soup.find_all(
        string=re.compile(
            r"Cheapest grade",
            re.I
        )
    )

    print(
        f"Cheapest grade headings found: "
        f"{len(headings)}"
    )

    if not headings:
        raise RuntimeError(
            "Cheapest grade heading not found"
        )

    heading = headings[-1]

    print(
        "Heading:",
        repr(
            heading.strip()
        )
    )

    # Try several parent levels.
    node = heading.parent

    for level in range(1, 12):

        if node is None:
            break

        text = node.get_text(
            " ",
            strip=True
        )

        html_length = len(
            str(node)
        )

        print(
            f"Parent level {level}: "
            f"text={len(text)} chars, "
            f"html={html_length} chars"
        )

        if (
            "Add players" in text
            and html_length > 1000
        ):

            section = str(node)

            marker = re.search(
                r"Add players",
                section,
                re.I
            )

            if marker:
                section = section[
                    :marker.start()
                ]

            print(
                f"Selected parent level: "
                f"{level}"
            )

            return section

        node = node.parent

    raise RuntimeError(
        "Could not isolate lineup"
    )


# ============================================================
# DIAGNOSTIC
# ============================================================

def diagnostic(section):
    soup = BeautifulSoup(
        section,
        "html.parser"
    )

    print()
    print("=" * 80)
    print("DIAGNOSTIC")
    print("=" * 80)

    # --------------------------------------------------------
    # IMG
    # --------------------------------------------------------

    images = soup.find_all("img")

    print()
    print(
        f"IMG elements: {len(images)}"
    )

    for index, img in enumerate(
        images,
        1
    ):

        print()
        print(
            "-" * 80
        )

        print(
            f"IMAGE #{index}"
        )

        attrs = dict(
            img.attrs
        )

        print(
            "ATTRIBUTES:"
        )

        for key, value in attrs.items():

            print(
                f"  {key}: {value}"
            )

        print(
            "PARENT ATTRIBUTES:"
        )

        parent = img.parent

        for level in range(1, 5):

            if parent is None:
                break

            print(
                f"  PARENT {level}:"
            )

            for key, value in parent.attrs.items():

                print(
                    f"    {key}: {value}"
                )

            parent = parent.parent

        print(
            "TEXT:"
        )

        print(
            " ",
            img.get_text(
                " ",
                strip=True
            )
        )

        print(
            "PARENT TEXT:"
        )

        parent = img.parent

        for level in range(1, 4):

            if parent is None:
                break

            text = parent.get_text(
                " ",
                strip=True
            )

            if text:
                print(
                    f"  PARENT {level}: "
                    f"{text[:500]}"
                )

            parent = parent.parent

        print(
            "OUTER HTML:"
        )

        outer = str(img)

        print(
            outer[:3000]
        )

    # --------------------------------------------------------
    # LINKS
    # --------------------------------------------------------

    print()
    print("=" * 80)
    print("LINK DIAGNOSTIC")
    print("=" * 80)

    links = soup.find_all("a")

    print(
        f"A elements: {len(links)}"
    )

    shown = 0

    for index, link in enumerate(
        links,
        1
    ):

        text = link.get_text(
            " ",
            strip=True
        )

        href = link.get(
            "href"
        )

        html = str(link)

        interesting = (
            "Šašić" in html
            or "Zamorano" in html
            or "Milito" in html
            or "Angerer" in html
            or "Prinz" in html
            or "Baresi" in html
            or "Cucurella" in html
            or "Harder" in html
            or "Mora" in html
            or "Bonny" in html
            or "Undav" in html
            or "Bischof" in html
            or "Yohannes" in html
        )

        if not interesting:
            continue

        shown += 1

        print()
        print(
            "-" * 80
        )

        print(
            f"LINK #{index}"
        )

        print(
            "TEXT:",
            text
        )

        print(
            "HREF:",
            href
        )

        print(
            "ATTRIBUTES:"
        )

        for key, value in link.attrs.items():

            print(
                f"  {key}: {value}"
            )

        print(
            "OUTER HTML:"
        )

        print(
            html[:5000]
        )

    print()
    print(
        f"Interesting links shown: "
        f"{shown}"
    )


# ============================================================
# SEARCH FINISH WORDS
# ============================================================

def search_finish_words(section):
    print()
    print("=" * 80)
    print("FINISH WORD SEARCH")
    print("=" * 80)

    soup = BeautifulSoup(
        section,
        "html.parser"
    )

    words = [
        "holo",
        "holographic",
        "pristine",
        "base",
    ]

    full_html = str(
        soup
    )

    for word in words:

        matches = list(
            re.finditer(
                word,
                full_html,
                re.I
            )
        )

        print(
            f"{word}: "
            f"{len(matches)} matches"
        )

        for match in matches[:10]:

            start = max(
                0,
                match.start() - 250
            )

            end = min(
                len(full_html),
                match.end() + 500
            )

            snippet = full_html[
                start:end
            ]

            print()
            print(
                snippet
            )


# ============================================================
# CARD NAME SEARCH
# ============================================================

def search_card_names(section):

    print()
    print("=" * 80)
    print("CARD NAME SEARCH")
    print("=" * 80)

    names = [
        "Šašić",
        "Zamorano",
        "Milito",
        "Angerer",
        "Prinz",
        "Baresi",
        "Cucurella",
        "Harder",
        "Mora",
        "Bonny",
        "Undav",
        "Bischof",
        "Yohannes",
    ]

    for name in names:

        matches = list(
            re.finditer(
                re.escape(name),
                section,
                re.I
            )
        )

        print()
        print(
            f"{name}: "
            f"{len(matches)} matches"
        )

        for match in matches[:3]:

            start = max(
                0,
                match.start() - 500
            )

            end = min(
                len(section),
                match.end() + 1200
            )

            print(
                section[
                    start:end
                ]
            )


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print("=" * 80)
    print("FUT.GG CARD DIAGNOSTIC")
    print("=" * 80)

    for category, url in PAGES.items():

        try:

            print()
            print()
            print(
                "#" * 80
            )

            print(
                f"# {category}"
            )

            print(
                "#" * 80
            )

            html = fetch(
                url
            )

            section = get_lineup_section(
                html
            )

            print()
            print(
                f"Lineup section length: "
                f"{len(section)}"
            )

            diagnostic(
                section
            )

            search_finish_words(
                section
            )

            search_card_names(
                section
            )

        except Exception as e:

            print()
            print(
                f"ERROR on {category}: "
                f"{e}"
            )

    print()
    print("=" * 80)
    print("DIAGNOSTIC FINISHED")
    print("=" * 80)


if __name__ == "__main__":
    main()