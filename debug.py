import re
import requests


PAGES = {
    "🦸 HEROES": {
        "url": "https://www.fut.gg/fut-gallery/rarities/heroes/",
        "players": 5,
        "best_grade": "A",
    },
    "🌈 HOLOGRAPHICS": {
        "url": "https://www.fut.gg/fut-gallery/rarities/holographics/",
        "players": 5,
        "best_grade": "S",
    },
    "🏆 SEASON 1": {
        "url": "https://www.fut.gg/fut-gallery/rarities/season-1/",
        "players": 10,
        "best_grade": "S",
    },
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


# ============================================================
# BALANCED EXTRACTION
# ============================================================

def extract_balanced(text, start, opening="{", closing="}"):
    if start < 0 or start >= len(text):
        return None

    if text[start] != opening:
        return None

    depth = 0
    in_string = False
    escaped = False

    for i in range(start, len(text)):
        c = text[i]

        if in_string:
            if escaped:
                escaped = False
            elif c == "\\":
                escaped = True
            elif c == '"':
                in_string = False
            continue

        if c == '"':
            in_string = True
            continue

        if c == opening:
            depth += 1

        elif c == closing:
            depth -= 1

            if depth == 0:
                return text[start:i + 1]

    return None


def extract_object_after(text, position):
    start = text.find("{", position)

    if start == -1:
        return None

    return extract_balanced(text, start, "{", "}")


def extract_array_after(text, position):
    start = text.find("[", position)

    if start == -1:
        return None

    return extract_balanced(text, start, "[", "]")


# ============================================================
# SIMPLE VALUE PARSER
# ============================================================

def parse_value(value):
    value = value.strip().rstrip(",")

    if value == "null":
        return None

    if value == "true":
        return True

    if value == "false":
        return False

    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]

    try:
        if "." in value:
            return float(value)

        return int(value)

    except Exception:
        return value


def get_field(obj, field):
    """
    Extracts simple fields such as:

    eaId:67276289
    overall:89
    rarityEaId:72
    price:null
    """

    pattern = rf"(?:^|[{{,])\s*{re.escape(field)}\s*:\s*"

    match = re.search(pattern, obj)

    if not match:
        return None

    start = match.end()

    # quoted value
    if start < len(obj) and obj[start] == '"':
        end = start + 1

        while end < len(obj):
            if obj[end] == '"' and obj[end - 1] != "\\":
                return parse_value(obj[start:end + 1])

            end += 1

        return None

    # normal value
    end = start

    while end < len(obj) and obj[end] not in ",}":
        end += 1

    return parse_value(obj[start:end])


# ============================================================
# RSC ARRAY RESOLVER
# ============================================================

def find_rsc_array(html, ref_id):
    """
    Finds:

    $R[241]=[
        $R[242]={...},
        $R[243]={...}
    ]

    and returns the complete array text.
    """

    patterns = [
        rf"\$R\[{ref_id}\]\s*=\s*\[",
        rf"\$R\[{ref_id}\]\s*=\s*\n\s*\[",
    ]

    start = -1

    for pattern in patterns:
        match = re.search(pattern, html)

        if match:
            start = html.find("[", match.start())
            break

    if start == -1:
        return None

    return extract_balanced(html, start, "[", "]")


def find_rsc_object(html, ref_id):
    """
    Finds:

    $R[241]={...}
    """

    pattern = rf"\$R\[{ref_id}\]\s*=\s*\{{"

    match = re.search(pattern, html)

    if not match:
        return None

    start = html.find("{", match.start())

    return extract_balanced(html, start, "{", "}")


# ============================================================
# SOLUTION FINDER
# ============================================================

def find_solutions(html, page_name):
    """
    Finds solution objects like:

    solution:$R[240]={
        setId:102,
        name:"Heroes",
        requiredCards:5,
        ...
        items:$R[241],
        ...
        grade:"A"
    }
    """

    solutions = []

    pattern = r"solution:\$R\[(\d+)\]\s*=\s*\{"

    for match in re.finditer(pattern, html):

        ref_id = int(match.group(1))

        start = html.find("{", match.start())

        if start == -1:
            continue

        obj = extract_balanced(
            html,
            start,
            "{",
            "}"
        )

        if not obj:
            continue

        # Check page name
        name = get_field(obj, "name")

        if name != page_name.replace("🦸 ", "").replace("🌈 ", "").replace("🏆 ", ""):
            continue

        grade = get_field(obj, "grade")
        required_cards = get_field(obj, "requiredCards")

        # items:$R[xxx]
        items_match = re.search(
            r"items\s*:\s*\$R\[(\d+)\]",
            obj
        )

        items_ref = None

        if items_match:
            items_ref = int(items_match.group(1))

        solutions.append({
            "ref": ref_id,
            "object": obj,
            "grade": grade,
            "requiredCards": required_cards,
            "items_ref": items_ref,
        })

    return solutions


# ============================================================
# EXTRACT CARDS FROM ITEMS ARRAY
# ============================================================

def extract_cards_from_solution(html, solution):
    items_ref = solution.get("items_ref")

    if items_ref is None:
        print("❌ No items reference found")
        return []

    print(f"Items reference: $R[{items_ref}]")

    array = find_rsc_array(html, items_ref)

    if not array:
        print(f"❌ Could not find array $R[{items_ref}]")
        return []

    print(f"Items array size: {len(array)} characters")

    cards = []

    # Find every $R[number]={...} inside the array
    pattern = r"\$R\[(\d+)\]\s*=\s*\{"

    matches = list(re.finditer(pattern, array))

    print(f"Item objects found: {len(matches)}")

    for match in matches:

        item_ref = int(match.group(1))

        start = array.find("{", match.start())

        if start == -1:
            continue

        item = extract_balanced(
            array,
            start,
            "{",
            "}"
        )

        if not item:
            continue

        card = {
            "eaId": get_field(item, "eaId"),
            "playerEaId": get_field(item, "playerEaId"),
            "overall": get_field(item, "overall"),
            "rarityEaId": get_field(item, "rarityEaId"),
            "price": get_field(item, "price"),
            "score": get_field(item, "score"),
            "item_ref": item_ref,
        }

        cards.append(card)

    return cards


# ============================================================
# MAIN DEBUG
# ============================================================

def debug_page(page_name, config):

    print()
    print("=" * 70)
    print(page_name)
    print(config["url"])
    print("=" * 70)

    try:
        response = requests.get(
            config["url"],
            headers=HEADERS,
            timeout=30
        )

        response.raise_for_status()

    except Exception as e:
        print(f"❌ REQUEST ERROR: {e}")
        return False

    html = response.text

    print(f"HTML size: {len(html):,} characters")

    # Count RSC references
    rsc_refs = set(
        re.findall(r"\$R\[(\d+)\]", html)
    )

    print(f"RSC references found: {len(rsc_refs)}")

    # Remove emoji from page name
    clean_name = re.sub(
        r"^[^\w]+",
        "",
        page_name,
        flags=re.UNICODE
    )

    print()
    print("Searching solutions...")

    solutions = find_solutions(
        html,
        clean_name
    )

    print()

    if not solutions:
        print("❌ NO SOLUTIONS FOUND")
        return False

    print("SOLUTIONS FOUND:")

    for solution in solutions:
        print(
            f"  Grade {solution['grade']} "
            f"→ items ref {solution['items_ref']} "
            f"(required: {solution['requiredCards']})"
        )

    # Grade order
    grade_order = {
        "D": 1,
        "C": 2,
        "B": 3,
        "A": 4,
        "S": 5,
    }

    # Pick highest grade
    solutions.sort(
        key=lambda x: grade_order.get(
            x["grade"],
            0
        ),
        reverse=True
    )

    best = solutions[0]

    print()
    print("⭐ BEST SOLUTION")
    print(f"Grade: {best['grade']}")
    print(f"Expected: {config['best_grade']}")
    print(f"Items ref: {best['items_ref']}")
    print(f"Expected cards: {config['players']}")

    cards = extract_cards_from_solution(
        html,
        best
    )

    print()
    print("CARDS:")

    if not cards:
        print("  ❌ 0 cards extracted")

    for index, card in enumerate(cards, 1):

        print(
            f"  {index}. "
            f"eaId={card['eaId']} | "
            f"playerEaId={card['playerEaId']} | "
            f"overall={card['overall']} | "
            f"rarityEaId={card['rarityEaId']} | "
            f"price={card['price']} | "
            f"RSC={card['item_ref']}"
        )

    # Validation
    grade_ok = (
        best["grade"] == config["best_grade"]
    )

    count_ok = (
        len(cards) == config["players"]
    )

    print()

    if grade_ok and count_ok:

        print("✅ DEBUG PASSED")

        return True

    print("❌ DEBUG FAILED")

    if not grade_ok:
        print(
            f"   Wrong grade: "
            f"{best['grade']} "
            f"(expected {config['best_grade']})"
        )

    if not count_ok:
        print(
            f"   Wrong card count: "
            f"{len(cards)} "
            f"(expected {config['players']})"
        )

    return False


# ============================================================
# RUN ALL
# ============================================================

def main():

    results = []

    for page_name, config in PAGES.items():

        ok = debug_page(
            page_name,
            config
        )

        results.append(
            (page_name, ok)
        )

    print()
    print("=" * 70)
    print("FINAL RESULT")
    print("=" * 70)

    all_ok = True

    for page_name, ok in results:

        if ok:
            print(f"✅ {page_name}")
        else:
            print(f"❌ {page_name}")
            all_ok = False

    print()

    if all_ok:
        print("🎉 ALL DEBUG TESTS PASSED")
    else:
        print("⚠️ SOME DEBUG TESTS FAILED")


if __name__ == "__main__":
    main()
