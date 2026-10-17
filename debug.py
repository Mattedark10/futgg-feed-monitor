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


def parse_alt(alt):
    """
    Prova a leggere:
    
    Nome - Rating - Tipo carta
    """

    if not alt:
        return None

    alt = alt.strip()

    match = re.match(
        r"^(.*?)\s*-\s*(\d{2,3})\s*-\s*(.+)$",
        alt
    )

    if not match:
        return None

    name = match.group(1).strip()
    rating = int(match.group(2))
    card_type = match.group(3).strip()

    return {
        "name": name,
        "rating": rating,
        "type": card_type,
    }


def debug_page(page_name, url):

    print()
    print("=" * 80)
    print(page_name)
    print(url)
    print("=" * 80)

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=30
        )

        print("HTTP STATUS:", response.status_code)
        print("FINAL URL:", response.url)
        print("HTML LENGTH:", len(response.text))

        response.raise_for_status()

    except Exception as e:
        print("REQUEST ERROR:", repr(e))
        return

    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )

    images = soup.find_all("img")

    print()
    print("TOTAL IMG TAGS:", len(images))
    print()

    found = []

    for index, img in enumerate(images):

        alt = img.get("alt")

        parsed = parse_alt(alt)

        if not parsed:
            continue

        found.append(
            (
                index,
                img,
                parsed
            )
        )

    print(
        "CARDS RECOGNIZED FROM ALT:",
        len(found)
    )

    print()

    for number, (index, img, parsed) in enumerate(
        found,
        start=1
    ):

        print("-" * 80)

        print(
            f"CARD #{number}"
        )

        print(
            "IMG INDEX:",
            index
        )

        print()

        print("PARSED:")

        print(parsed)

        print()

        print("ALT:")

        print(
            repr(
                img.get("alt")
            )
        )

        print()

        print("CLASS:")

        print(
            repr(
                img.get("class")
            )
        )

        print()

        print("SRC:")

        print(
            repr(
                img.get("src")
            )
        )

        print()

        print("DATA ATTRIBUTES:")

        for key, value in img.attrs.items():

            if key.startswith("data-"):

                print(
                    f"  {key} = {value!r}"
                )

        print()

        print("ALL IMG ATTRIBUTES:")

        for key, value in img.attrs.items():

            print(
                f"  {key} = {value!r}"
            )

        print()

        parent = img.parent

        print("PARENT TAG:")

        if parent:

            print(
                parent.name
            )

            print(
                parent.attrs
            )

        print()

        print("PARENT OUTER HTML:")

        if parent:

            html = str(parent)

            if len(html) > 5000:

                html = (
                    html[:5000]
                    + "\n...[TRUNCATED]..."
                )

            print(html)

        print()

    print("=" * 80)

    print(
        f"END {page_name}"
    )

    print("=" * 80)


def main():

    print()

    print(
        "FUT.GG HTML DEBUGGER"
    )

    print(
        "===================="
    )

    for page_name, url in PAGES.items():

        debug_page(
            page_name,
            url
        )


if __name__ == "__main__":

    main()