import re
import requests
from bs4 import BeautifulSoup


PAGES = {
    "🦸 HEROES": {
        "url": "https://www.fut.gg/fut-gallery/rarities/heroes/",
        "name": "Heroes",
        "expected": 5,
        "grade": "A",
    },

    "🌈 HOLOGRAPHICS": {
        "url": "https://www.fut.gg/fut-gallery/rarities/holographics/",
        "name": "Holographics",
        "expected": 5,
        "grade": "S",
    },

    "🏆 SEASON 1": {
        "url": "https://www.fut.gg/fut-gallery/rarities/season-1/",
        "name": "Season 1",
        "expected": 10,
        "grade": "S",
    },
}


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    )
}


GRADE_ORDER = {
    "D": 1,
    "C": 2,
    "B": 3,
    "A": 4,
    "S": 5,
}


def extract_object(text, start):

    if start >= len(text) or text[start] != "{":
        return None

    depth = 0
    string = False
    escaped = False

    for i in range(start, len(text)):

        c = text[i]

        if string:

            if escaped:
                escaped = False

            elif c == "\\":
                escaped = True

            elif c == '"':
                string = False

            continue

        if c == '"':
            string = True

        elif c == "{":
            depth += 1

        elif c == "}":

            depth -= 1

            if depth == 0:
                return text[start:i + 1]

    return None


def extract_array(text, start):

    if start >= len(text) or text[start] != "[":
        return None

    depth = 0
    string = False
    escaped = False

    for i in range(start, len(text)):

        c = text[i]

        if string:

            if escaped:
                escaped = False

            elif c == "\\":
                escaped = True

            elif c == '"':
                string = False

            continue

        if c == '"':
            string = True

        elif c == "[":
            depth += 1

        elif c == "]":

            depth -= 1

            if depth == 0:
                return text[start:i + 1]

    return None


def get_value(text, field):

    pattern = re.compile(
        rf"{re.escape(field)}\s*:\s*"
        r'(?:"([^"]*)"|([0-9]+(?:\.[0-9]+)?)|null)'
    )

    match = pattern.search(text)

    if not match:
        return None

    if match.group(1) is not None:
        return match.group(1)

    if match.group(2) is not None:
        return match.group(2)

    return None


def main():

    for category, page in PAGES.items():

        print()
        print("=" * 70)
        print(category)
        print(page["url"])
        print("=" * 70)

        try:

            response = requests.get(
                page["url"],
                headers=HEADERS,
                timeout=40
            )

            response.raise_for_status()

        except Exception as error:

            print(
                "❌ REQUEST ERROR:",
                error
            )

            continue

        source = response.text

        print(
            f"HTML size: {len(source):,} characters"
        )

        # ----------------------------------------------------
        # FIND ALL $R OBJECTS
        # ----------------------------------------------------

        objects = {}

        pattern = re.compile(
            r"\$R\[(\d+)\]\s*=\s*\{"
        )

        for match in pattern.finditer(source):

            ref = int(match.group(1))

            obj = extract_object(
                source,
                match.end() - 1
            )

            if obj:
                objects[ref] = obj

        print(
            f"RSC objects found: {len(objects)}"
        )

        # ----------------------------------------------------
        # FIND SOLUTIONS
        # ----------------------------------------------------

        solutions = []

        solution_pattern = re.compile(
            r"solution\s*:\s*\$R\[(\d+)\]\s*=\s*\{"
        )

        for match in solution_pattern.finditer(
            source
        ):

            ref = int(match.group(1))

            obj = objects.get(ref)

            if not obj:
                continue

            name = get_value(
                obj,
                "name"
            )

            grade = get_value(
                obj,
                "grade"
            )

            required = get_value(
                obj,
                "requiredCards"
            )

            if name != page["name"]:
                continue

            items_match = re.search(
                r"items\s*:\s*"
                r"(?:\$R\[\d+\]\s*=\s*)?\[",
                obj
            )

            item_refs = []

            if items_match:

                array_start = obj.find(
                    "[",
                    items_match.start()
                )

                array = extract_array(
                    obj,
                    array_start
                )

                if array:

                    item_refs = [
                        int(x)
                        for x in re.findall(
                            r"\$R\[(\d+)\]",
                            array
                        )
                    ]

            solutions.append({
                "ref": ref,
                "name": name,
                "grade": grade,
                "required": required,
                "items": item_refs,
            })

        if not solutions:

            print(
                "❌ Nessuna solution trovata."
            )

            continue

        # ----------------------------------------------------
        # PRINT SOLUTIONS
        # ----------------------------------------------------

        print()
        print("SOLUTIONS FOUND:")

        for solution in solutions:

            print(
                f"  Grade {solution['grade']} "
                f"→ {len(solution['items'])} cards "
                f"(required: "
                f"{solution['required']})"
            )

        # ----------------------------------------------------
        # BEST
        # ----------------------------------------------------

        solutions.sort(
            key=lambda x: GRADE_ORDER.get(
                str(x["grade"]).upper(),
                0
            ),
            reverse=True
        )

        best = solutions[0]

        print()
        print(
            "⭐ BEST SOLUTION"
        )

        print(
            f"Grade: {best['grade']}"
        )

        print(
            f"Expected: {page['grade']}"
        )

        print(
            f"Cards: {len(best['items'])}"
        )

        print(
            f"Expected cards: {page['expected']}"
        )

        # ----------------------------------------------------
        # CARD DETAILS
        # ----------------------------------------------------

        print()
        print("CARDS:")

        for index, item_ref in enumerate(
            best["items"],
            start=1
        ):

            obj = objects.get(
                item_ref
            )

            if not obj:

                print(
                    f"{index}. ❌ "
                    f"$R[{item_ref}] not found"
                )

                continue

            ea_id = get_value(
                obj,
                "eaId"
            )

            player_ea_id = get_value(
                obj,
                "playerEaId"
            )

            overall = get_value(
                obj,
                "overall"
            )

            rarity = get_value(
                obj,
                "rarityEaId"
            )

            price = get_value(
                obj,
                "price"
            )

            print(
                f"{index}. "
                f"eaId={ea_id} | "
                f"playerEaId={player_ea_id} | "
                f"OVR={overall} | "
                f"rarityEaId={rarity} | "
                f"price={price}"
            )

        # ----------------------------------------------------
        # FINAL CHECK
        # ----------------------------------------------------

        print()

        if (
            best["grade"] == page["grade"]
            and
            len(best["items"]) == page["expected"]
        ):

            print(
                "✅ DEBUG PASSED"
            )

        else:

            print(
                "❌ DEBUG FAILED"
            )

        print()


if __name__ == "__main__":
    main()
