import re
import requests
from bs4 import BeautifulSoup


PAGES = {
    "🦸 HEROES": {
        "url": "https://www.fut.gg/fut-gallery/rarities/heroes/",
        "players": 5,
        "internal_name": "Heroes",
    },

    "🌈 HOLOGRAPHICS": {
        "url": "https://www.fut.gg/fut-gallery/rarities/holographics/",
        "players": 5,
        "internal_name": "Holographics",
    },

    "🏆 SEASON 1": {
        "url": "https://www.fut.gg/fut-gallery/rarities/season-1/",
        "players": 10,
        "internal_name": "Season 1",
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


# ============================================================
# DOWNLOAD
# ============================================================

def get_page(url):

    response = requests.get(
        url,
        headers=HEADERS,
        timeout=40
    )

    response.raise_for_status()

    return response.text


# ============================================================
# BALANCED OBJECT
# ============================================================

def extract_object(text, start):

    if start < 0 or start >= len(text):
        return None

    if text[start] != "{":
        return None

    depth = 0
    in_string = False
    escaped = False

    for i in range(start, len(text)):

        char = text[i]

        if in_string:

            if escaped:
                escaped = False

            elif char == "\\":
                escaped = True

            elif char == '"':
                in_string = False

            continue

        if char == '"':
            in_string = True

        elif char == "{":
            depth += 1

        elif char == "}":

            depth -= 1

            if depth == 0:
                return text[start:i + 1]

    return None


def extract_array(text, start):

    if start < 0 or start >= len(text):
        return None

    if text[start] != "[":
        return None

    depth = 0
    in_string = False
    escaped = False

    for i in range(start, len(text)):

        char = text[i]

        if in_string:

            if escaped:
                escaped = False

            elif char == "\\":
                escaped = True

            elif char == '"':
                in_string = False

            continue

        if char == '"':
            in_string = True

        elif char == "[":
            depth += 1

        elif char == "]":

            depth -= 1

            if depth == 0:
                return text[start:i + 1]

    return None


# ============================================================
# BUILD $R OBJECTS
# ============================================================

def build_rsc_objects(source):

    objects = {}

    pattern = re.compile(
        r"\$R\[(\d+)\]\s*=\s*(\{|\[)"
    )

    for match in pattern.finditer(source):

        index = int(match.group(1))
        opening = match.group(2)

        start = match.start(2)

        if opening == "{":

            raw = extract_object(
                source,
                start
            )

        else:

            raw = extract_array(
                source,
                start
            )

        if raw:

            objects[index] = raw

    return objects


# ============================================================
# PARSE SIMPLE VALUES
# ============================================================

def parse_value(value):

    value = value.strip()

    if value == "null":
        return None

    if value == "true":
        return True

    if value == "false":
        return False

    if value.startswith('"') and value.endswith('"'):

        return value[1:-1]

    if re.fullmatch(
        r"-?\d+",
        value
    ):

        return int(value)

    if re.fullmatch(
        r"-?\d+\.\d+",
        value
    ):

        return float(value)

    return value


# ============================================================
# PARSE OBJECT
# ============================================================

def parse_object(raw):

    result = {}

    if not raw:
        return result

    if not raw.startswith("{"):
        return result

    body = raw[1:-1]

    pattern = re.compile(
        r'([A-Za-z_][A-Za-z0-9_]*)\s*:\s*'
        r'(".*?"|null|true|false|-?\d+(?:\.\d+)?)'
    )

    for match in pattern.finditer(body):

        key = match.group(1)
        value = match.group(2)

        result[key] = parse_value(
            value
        )

    return result


# ============================================================
# FIND SOLUTIONS
# ============================================================

def find_solutions(
    source,
    objects,
    internal_name
):

    solutions = []

    pattern = re.compile(
        r"solution:\$R\[(\d+)\]\s*=\s*\{"
    )

    for match in pattern.finditer(source):

        ref_id = int(
            match.group(1)
        )

        raw = objects.get(
            ref_id
        )

        if not raw:
            continue

        solution = parse_object(
            raw
        )

        if solution.get("name") != internal_name:
            continue

        solution["_ref_id"] = ref_id

        solutions.append(
            solution
        )

    return solutions


# ============================================================
# GET ITEMS FROM SOLUTION
# ============================================================

def get_solution_items(
    solution,
    objects
):

    ref_id = solution.get(
        "_ref_id"
    )

    raw_solution = objects.get(
        ref_id
    )

    if not raw_solution:
        return []

    match = re.search(
        r"items:\$R\[(\d+)\]\s*=\s*\[",
        raw_solution
    )

    if not match:
        return []

    array_ref = int(
        match.group(1)
    )

    raw_array = objects.get(
        array_ref
    )

    if not raw_array:
        return []

    references = re.findall(
        r"\$R\[(\d+)\]",
        raw_array
    )

    items = []

    for reference in references:

        item_ref = int(
            reference
        )

        raw_item = objects.get(
            item_ref
        )

        if not raw_item:
            continue

        item = parse_object(
            raw_item
        )

        if item:
            items.append(
                item
            )

    return items


# ============================================================
# FIND BEST LINEUP
# ============================================================

def find_best_solution(
    source,
    objects,
    internal_name,
    expected_players
):

    solutions = find_solutions(
        source,
        objects,
        internal_name
    )

    if not solutions:

        raise RuntimeError(
            f"No solutions found for "
            f"{internal_name}"
        )

    print(
        f"Found {len(solutions)} "
        f"solutions."
    )

    valid = []

    for solution in solutions:

        items = get_solution_items(
            solution,
            objects
        )

        solution["_items"] = items

        grade = solution.get(
            "grade",
            "?"
        )

        total_score = solution.get(
            "totalScore",
            0
        )

        print(
            f"  Solution: "
            f"grade={grade}, "
            f"cards={len(items)}, "
            f"score={total_score}"
        )

        if len(items) == expected_players:

            valid.append(
                solution
            )

    if not valid:

        raise RuntimeError(
            f"No valid solution with "
            f"{expected_players} cards found."
        )

    # --------------------------------------------------------
    # NON USIAMO IL GRADO.
    #
    # Prendiamo semplicemente la solution
    # con il punteggio più alto.
    # --------------------------------------------------------

    valid.sort(
        key=lambda x: (
            x.get("totalScore", 0)
            if isinstance(
                x.get("totalScore"),
                (int, float)
            )
            else 0
        ),
        reverse=True
    )

    return valid[0]


# ============================================================
# MAIN DEBUG
# ============================================================

def main():

    print()
    print("=" * 60)
    print("FUT.GG DEBUG")
    print("=" * 60)

    all_passed = True

    for page_name, config in PAGES.items():

        print()
        print("=" * 60)
        print(
            f"Scanning {page_name}"
        )
        print(
            config["url"]
        )
        print("=" * 60)

        try:

            source = get_page(
                config["url"]
            )

            print(
                f"Downloaded "
                f"{len(source):,} characters."
            )

            objects = build_rsc_objects(
                source
            )

            print(
                f"Found "
                f"{len(objects)} RSC objects."
            )

            solution = find_best_solution(
                source,
                objects,
                config["internal_name"],
                config["players"]
            )

            items = solution[
                "_items"
            ]

            print()
            print(
                "BEST / DEFAULT SOLUTION"
            )

            print(
                f"Internal name: "
                f"{solution.get('name')}"
            )

            print(
                f"Grade detected: "
                f"{solution.get('grade', '?')}"
            )

            print(
                f"Total score: "
                f"{solution.get('totalScore', '?')}"
            )

            print(
                f"Cards: "
                f"{len(items)}/"
                f"{config['players']}"
            )

            print()
            print("PLAYERS:")

            for number, item in enumerate(
                items,
                start=1
            ):

                print(
                    f"{number}. "
                    f"EA ID: {item.get('eaId')} | "
                    f"Player EA ID: "
                    f"{item.get('playerEaId')} | "
                    f"Overall: "
                    f"{item.get('overall')} | "
                    f"Rarity: "
                    f"{item.get('rarityEaId')} | "
                    f"Price: "
                    f"{item.get('price')}"
                )

            if len(items) != config["players"]:

                print()
                print(
                    "❌ WRONG CARD COUNT"
                )

                all_passed = False

            else:

                print()
                print(
                    "✅ CARD COUNT OK"
                )

        except Exception as error:

            print()
            print(
                f"❌ ERROR: {error}"
            )

            all_passed = False

    print()
    print("=" * 60)

    if all_passed:

        print(
            "✅ DEBUG PASSED"
        )

    else:

        print(
            "❌ DEBUG FAILED"
        )

    print("=" * 60)


if __name__ == "__main__":
    main()