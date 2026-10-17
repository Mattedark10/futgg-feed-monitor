import re
import requests


PAGES = {
    "🦸 HEROES": {
        "url": "https://www.fut.gg/fut-gallery/rarities/heroes/",
        "expected": 5,
    },
    "🌈 HOLOGRAPHICS": {
        "url": "https://www.fut.gg/fut-gallery/rarities/holographics/",
        "expected": 5,
    },
    "🏆 SEASON 1": {
        "url": "https://www.fut.gg/fut-gallery/rarities/season-1/",
        "expected": 10,
    },
}


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def get_page(url):

    response = requests.get(
        url,
        headers=HEADERS,
        timeout=40
    )

    response.raise_for_status()

    return response.text


def show_solution_occurrences(source):

    print()
    print("SEARCHING RAW HTML FOR 'solution'")
    print("-" * 60)

    positions = []

    start = 0

    while True:

        pos = source.find(
            "solution",
            start
        )

        if pos == -1:
            break

        positions.append(pos)

        start = pos + 8

        if len(positions) >= 30:
            break

    print(
        f"Found {len(positions)} occurrences "
        f"(showing max 30)"
    )

    if not positions:

        print()
        print(
            "❌ The word 'solution' does not "
            "appear in the downloaded HTML."
        )

        # Try alternative words
        for word in [
            "solutions",
            "requiredCards",
            "totalScore",
            "baseGrade",
            "items",
            "setId",
        ]:

            count = source.count(word)

            print(
                f"'{word}' -> {count} occurrences"
            )

        return

    for number, pos in enumerate(
        positions,
        start=1
    ):

        start = max(
            0,
            pos - 250
        )

        end = min(
            len(source),
            pos + 600
        )

        chunk = source[start:end]

        print()
        print(
            f"--- OCCURRENCE {number} "
            f"at position {pos} ---"
        )

        print(chunk)


def search_solution_patterns(source):

    print()
    print("=" * 60)
    print("TESTING POSSIBLE SOLUTION PATTERNS")
    print("=" * 60)

    patterns = [

        r"solution:\$R\[(\d+)\]",

        r"solution\s*:\s*\$R\[(\d+)\]",

        r'"solution":\$R\[(\d+)\]',

        r'"solution"\s*:\s*\$R\[(\d+)\]',

        r"solution.{0,100}\$R\[(\d+)\]",

        r"solution.{0,200}requiredCards",

        r"solution.{0,200}totalScore",

        r"requiredCards.{0,500}totalScore",

        r"setId.{0,500}requiredCards",
    ]

    for pattern in patterns:

        try:

            matches = re.findall(
                pattern,
                source,
                flags=re.DOTALL
            )

            print()
            print(
                f"PATTERN: {pattern}"
            )

            print(
                f"MATCHES: {len(matches)}"
            )

            if matches:

                print(
                    "FIRST MATCHES:"
                )

                for match in matches[:10]:

                    print(
                        repr(match)
                    )

        except Exception as error:

            print(
                f"Pattern error: {error}"
            )


def search_card_data(source):

    print()
    print("=" * 60)
    print("SEARCHING CARD DATA")
    print("=" * 60)

    terms = [
        "requiredCards",
        "poolSize",
        "totalScore",
        "baseGrade",
        "bonusGrade",
        "pointsToNextGrade",
        "nextGrade",
        "playerEaId",
        "eaId",
    ]

    for term in terms:

        count = source.count(
            term
        )

        print(
            f"{term}: {count}"
        )


def main():

    print()
    print("=" * 60)
    print("FUT.GG RAW DEBUG")
    print("=" * 60)

    for page_name, config in PAGES.items():

        print()
        print("=" * 60)

        print(
            f"SCANNING {page_name}"
        )

        print(
            config["url"]
        )

        print("=" * 60)

        try:

            source = get_page(
                config["url"]
            )

            print()
            print(
                f"Downloaded "
                f"{len(source):,} characters."
            )

            search_card_data(
                source
            )

            search_solution_patterns(
                source
            )

            show_solution_occurrences(
                source
            )

        except Exception as error:

            print()
            print(
                f"❌ ERROR: {error}"
            )

    print()
    print("=" * 60)
    print("RAW DEBUG FINISHED")
    print("=" * 60)


if __name__ == "__main__":
    main()