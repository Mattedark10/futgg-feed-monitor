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
    )
}


def clean(value):
    if not value:
        return ""

    return re.sub(
        r"\s+",
        " ",
        str(value)
    ).strip()


def fetch(url):
    response = requests.get(
        url,
        headers=HEADERS,
        timeout=45
    )

    response.raise_for_status()

    return response.text


def find_lineup(html):

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    heading = soup.find(
        string=re.compile(
            r"Cheapest grade",
            re.I
        )
    )

    if not heading:
        raise RuntimeError(
            "Cheapest grade non trovato"
        )

    node = heading.parent

    for _ in range(12):

        if node is None:
            break

        text = clean(
            node.get_text(
                " ",
                strip=True
            )
        )

        if (
            "Add players" in text
            and len(str(node)) > 1000
        ):
            return BeautifulSoup(
                str(node),
                "html.parser"
            )

        node = node.parent

    raise RuntimeError(
        "Lineup non trovato"
    )


def diagnostic(category, soup):

    print()
    print("=" * 70)
    print(category)
    print("=" * 70)

    images = soup.find_all("img")

    interesting = []

    for img in images:

        attrs = img.attrs

        alt = clean(
            attrs.get("alt")
        )

        title = clean(
            attrs.get("title")
        )

        aria = clean(
            attrs.get("aria-label")
        )

        src = clean(
            attrs.get("src")
        )

        srcset = clean(
            attrs.get("srcset")
        )

        combined = " | ".join(
            x
            for x in [
                alt,
                title,
                aria,
                src,
                srcset
            ]
            if x
        )

        # Ignora immagini chiaramente non relative
        # alle carte
        if not combined:
            continue

        if (
            "Player Card" in combined
            or re.search(
                r"\b\d{2}\b",
                alt
            )
            or re.search(
                r"\b\d{2}\b",
                title
            )
            or re.search(
                r"\b\d{2}\b",
                aria
            )
        ):
            interesting.append(
                img
            )

    print(
        f"IMG interessanti: {len(interesting)}"
    )

    for i, img in enumerate(
        interesting,
        1
    ):

        attrs = img.attrs

        alt = clean(
            attrs.get("alt")
        )

        title = clean(
            attrs.get("title")
        )

        aria = clean(
            attrs.get("aria-label")
        )

        src = clean(
            attrs.get("src")
        )

        print()
        print(
            f"[{i}]"
        )

        if alt:
            print(
                f"ALT: {alt}"
            )

        if title:
            print(
                f"TITLE: {title}"
            )

        if aria:
            print(
                f"ARIA: {aria}"
            )

        if src:
            print(
                f"SRC: {src[:500]}"
            )

        # Cerca eventuale link della carta
        parent = img.parent

        for level in range(4):

            if parent is None:
                break

            if parent.name == "a":

                href = clean(
                    parent.get(
                        "href"
                    )
                )

                if href:
                    print(
                        f"LINK: {href}"
                    )

                break

            parent = parent.parent

        # Cerca SOLO parole di finish
        # nei parent vicini
        finish_found = []

        parent = img.parent

        for level in range(4):

            if parent is None:
                break

            parent_text = clean(
                parent.get_text(
                    " ",
                    strip=True
                )
            )

            for word in [
                "Pristine Holographic",
                "Holographic",
                "Holo",
                "Base Hero",
                "Base Icon",
                "Base",
            ]:

                if re.search(
                    re.escape(word),
                    parent_text,
                    re.I
                ):
                    finish_found.append(
                        word
                    )

            parent = parent.parent

        if finish_found:

            print(
                "FINISH CANDIDATE:",
                ", ".join(
                    dict.fromkeys(
                        finish_found
                    )
                )
            )


def main():

    print()
    print(
        "FUT.GG FINISH DIAGNOSTIC"
    )

    for category, url in PAGES.items():

        print()
        print(
            f"Scanning {category}..."
        )

        try:

            html = fetch(
                url
            )

            soup = find_lineup(
                html
            )

            diagnostic(
                category,
                soup
            )

        except Exception as e:

            print(
                f"ERROR {category}: {e}"
            )

    print()
    print(
        "DIAGNOSTIC COMPLETE"
    )


if __name__ == "__main__":
    main()