import re
import requests


PAGES = {
    "HEROES": "https://www.fut.gg/fut-gallery/rarities/heroes/",
    "HOLOGRAPHICS": "https://www.fut.gg/fut-gallery/rarities/holographics/",
    "SEASON 1": "https://www.fut.gg/fut-gallery/rarities/season-1/",
}


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def show_context(html, term, amount=3, chars=800):
    print()
    print("-" * 70)
    print(f"SEARCH: {term}")

    positions = [
        m.start()
        for m in re.finditer(
            re.escape(term),
            html,
            re.IGNORECASE
        )
    ]

    print(f"Occurrences: {len(positions)}")

    for i, pos in enumerate(positions[:amount], 1):
        print()
        print(f"--- occurrence {i} ---")

        start = max(0, pos - 300)
        end = min(len(html), pos + chars)

        snippet = html[start:end]

        print(snippet)


def debug_page(name, url):

    print()
    print("=" * 70)
    print(name)
    print(url)
    print("=" * 70)

    try:
        r = requests.get(
            url,
            headers=HEADERS,
            timeout=30
        )

        r.raise_for_status()

    except Exception as e:
        print(f"REQUEST ERROR: {e}")
        return

    html = r.text

    print(f"HTML size: {len(html):,}")

    print()
    print("Basic checks:")

    checks = [
        "solution",
        "requiredCards",
        "setId",
        "items",
        "grade",
        "$R[",
        "Heroes",
        "Holographics",
        "Season 1",
    ]

    for term in checks:
        count = len(
            re.findall(
                re.escape(term),
                html,
                re.IGNORECASE
            )
        )

        print(f"{term:20} -> {count}")

    # ---------------------------------------------------------
    # SHOW SOLUTION CONTEXT
    # ---------------------------------------------------------

    show_context(
        html,
        "solution",
        amount=5,
        chars=1000
    )

    # ---------------------------------------------------------
    # SHOW requiredCards
    # ---------------------------------------------------------

    show_context(
        html,
        "requiredCards",
        amount=3,
        chars=1000
    )

    # ---------------------------------------------------------
    # SHOW grade
    # ---------------------------------------------------------

    show_context(
        html,
        "grade",
        amount=5,
        chars=700
    )

    # ---------------------------------------------------------
    # SHOW items
    # ---------------------------------------------------------

    show_context(
        html,
        "items",
        amount=5,
        chars=700
    )

    # ---------------------------------------------------------
    # SHOW setId
    # ---------------------------------------------------------

    show_context(
        html,
        "setId",
        amount=3,
        chars=700
    )


def main():

    for name, url in PAGES.items():
        debug_page(name, url)

    print()
    print("=" * 70)
    print("DIAGNOSTIC COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()