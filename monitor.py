import os
import re
import json
import time
from collections import Counter

import requests
from bs4 import BeautifulSoup


# ============================================================
# CONFIG
# ============================================================

PAGES = {
    "Heroes": {
        "url": "https://www.fut.gg/fut-gallery/rarities/heroes/",
        "expected": 5,
    },
    "Holographics": {
        "url": "https://www.fut.gg/fut-gallery/rarities/holographics/",
        "expected": 5,
    },
    "Season 1": {
        "url": "https://www.fut.gg/fut-gallery/rarities/season-1/",
        "expected": 10,
    },
}

STATE_FILE = "players.json"
TRENDING_FILE = "docs/trending.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


# ============================================================
# HTTP
# ============================================================

session = requests.Session()
session.headers.update(HEADERS)


def download_page(url):
    response = session.get(
        url,
        timeout=30
    )

    response.raise_for_status()

    text = response.text

    print(
        f"Downloaded {len(text):,} characters."
    )

    return text


# ============================================================
# GENERIC PARSER
# ============================================================

def split_top_level(text, separator=","):
    parts = []

    start = 0

    depth_curly = 0
    depth_square = 0
    depth_paren = 0

    in_string = False
    quote = None
    escape = False

    for i, char in enumerate(text):

        if in_string:

            if escape:
                escape = False
                continue

            if char == "\\":
                escape = True
                continue

            if char == quote:
                in_string = False

            continue

        if char in ('"', "'", "`"):
            in_string = True
            quote = char
            continue

        if char == "{":
            depth_curly += 1

        elif char == "}":
            depth_curly -= 1

        elif char == "[":
            depth_square += 1

        elif char == "]":
            depth_square -= 1

        elif char == "(":
            depth_paren += 1

        elif char == ")":
            depth_paren -= 1

        elif (
            char == separator
            and depth_curly == 0
            and depth_square == 0
            and depth_paren == 0
        ):
            parts.append(
                text[start:i].strip()
            )

            start = i + 1

    final = text[start:].strip()

    if final:
        parts.append(final)

    return parts


def find_matching(
    text,
    start,
    opening,
    closing
):
    depth = 0

    in_string = False
    quote = None
    escape = False

    for i in range(
        start,
        len(text)
    ):
        char = text[i]

        if in_string:

            if escape:
                escape = False
                continue

            if char == "\\":
                escape = True
                continue

            if char == quote:
                in_string = False

            continue

        if char in ('"', "'", "`"):
            in_string = True
            quote = char
            continue

        if char == opening:
            depth += 1

        elif char == closing:
            depth -= 1

            if depth == 0:
                return i

    return -1


def parse_primitive(value):
    value = value.strip()

    if value == "true":
        return True

    if value == "false":
        return False

    if value == "null":
        return None

    if value == "undefined":
        return None

    if (
        len(value) >= 2
        and value[0] in ('"', "'", "`")
        and value[-1] == value[0]
    ):
        content = value[1:-1]

        try:
            return bytes(
                content,
                "utf-8"
            ).decode(
                "unicode_escape"
            )

        except Exception:
            return content

    if re.fullmatch(
        r"-?\d+",
        value
    ):
        try:
            return int(value)

        except Exception:
            pass

    if re.fullmatch(
        r"-?\d+\.\d+",
        value
    ):
        try:
            return float(value)

        except Exception:
            pass

    return value


def parse_value(value):
    value = value.strip()

    # ========================================================
    # INLINE RSC ASSIGNMENT
    #
    # FUT.GG può usare:
    #
    # $R[242]={eaId:123,...}
    #
    # oppure:
    #
    # $R[241]=[...]
    #
    # In questi casi ci interessa il valore dopo "=".
    # ========================================================

    inline_assignment = re.match(
        r"^\$R\[(\d+)\]=(.*)$",
        value,
        re.DOTALL
    )

    if inline_assignment:

        assigned_value = inline_assignment.group(
            2
        ).strip()

        return parse_value(
            assigned_value
        )

    # --------------------------------------------------------
    # RSC reference
    # --------------------------------------------------------

    match = re.fullmatch(
        r"\$R\[(\d+)\]",
        value
    )

    if match:
        return {
            "__ref__": int(
                match.group(1)
            )
        }

    # --------------------------------------------------------
    # Object
    # --------------------------------------------------------

    if value.startswith("{"):

        end = find_matching(
            value,
            0,
            "{",
            "}"
        )

        if (
            end != -1
            and end == len(value) - 1
        ):
            return parse_object(
                value[1:end]
            )

    # --------------------------------------------------------
    # Array
    # --------------------------------------------------------

    if value.startswith("["):

        end = find_matching(
            value,
            0,
            "[",
            "]"
        )

        if (
            end != -1
            and end == len(value) - 1
        ):
            inside = value[
                1:end
            ].strip()

            if not inside:
                return []

            parts = split_top_level(
                inside,
                ","
            )

            return [
                parse_value(part)
                for part in parts
            ]

    return parse_primitive(
        value
    )


def parse_object(text):
    result = {}

    parts = split_top_level(
        text,
        ","
    )

    for part in parts:

        if ":" not in part:
            continue

        key, value = part.split(
            ":",
            1
        )

        key = key.strip()
        value = value.strip()

        if (
            len(key) >= 2
            and key[0] in ('"', "'", "`")
            and key[-1] == key[0]
        ):
            key = key[1:-1]

        result[key] = parse_value(
            value
        )

    return result


# ============================================================
# RSC ASSIGNMENTS
# ============================================================

def extract_rsc_assignments(text):
    assignments = {}

    pattern = re.compile(
        r"\$R(\d+)="
    )

    matches = list(
        pattern.finditer(text)
    )

    for match in matches:

        index = int(
            match.group(1)
        )

        start = match.end()

        while (
            start < len(text)
            and text[start].isspace()
        ):
            start += 1

        if start >= len(text):
            continue

        first = text[start]

        if first == "{":

            end = find_matching(
                text,
                start,
                "{",
                "}"
            )

        elif first == "[":

            end = find_matching(
                text,
                start,
                "[",
                "]"
            )

        else:
            continue

        if end == -1:
            continue

        raw_value = text[
            start:end + 1
        ]

        try:
            assignments[index] = parse_value(
                raw_value
            )

        except Exception:
            continue

    print(
        f"Found {len(assignments)} RSC assignments."
    )

    return assignments


# ============================================================
# RESOLVE REFERENCES
# ============================================================

def resolve_reference(
    value,
    assignments,
    depth=0
):
    if depth > 100:
        return value

    # --------------------------------------------------------
    # Reference / Object
    # --------------------------------------------------------

    if isinstance(
        value,
        dict
    ):

        if (
            "__ref__" in value
            and len(value) == 1
        ):
            ref = value[
                "__ref__"
            ]

            if ref not in assignments:
                return None

            return resolve_reference(
                assignments[ref],
                assignments,
                depth + 1
            )

        result = {}

        for key, val in value.items():

            result[key] = resolve_reference(
                val,
                assignments,
                depth + 1
            )

        return result

    # --------------------------------------------------------
    # Array
    # --------------------------------------------------------

    if isinstance(
        value,
        list
    ):
        return [
            resolve_reference(
                item,
                assignments,
                depth + 1
            )
            for item in value
        ]

    return value


# ============================================================
# SPECIAL FUT.GG ITEMS PARSER
# ============================================================

def parse_items_assignment(
    raw_items,
    assignments
):
    """
    FUT.GG può usare:

        items:$R[241]=[
            $R[242]={...},
            $R[243]={...},
            ...
        ]

    Il parser deve quindi gestire sia l'assegnazione
    dell'array sia le assegnazioni inline delle singole carte.
    """

    if not isinstance(
        raw_items,
        str
    ):
        return resolve_reference(
            raw_items,
            assignments
        )

    raw = raw_items.strip()

    # --------------------------------------------------------
    # $R[241]=[ ... ]
    # --------------------------------------------------------

    match = re.match(
        r"^\$R(\d+)=(.*)$",
        raw,
        re.DOTALL
    )

    if match:

        array_text = match.group(
            2
        )

        parsed = parse_value(
            array_text
        )

        return resolve_reference(
            parsed,
            assignments
        )

    # --------------------------------------------------------
    # $R[241]
    # --------------------------------------------------------

    ref_match = re.fullmatch(
        r"\$R(\d+)",
        raw
    )

    if ref_match:

        ref = int(
            ref_match.group(1)
        )

        if ref in assignments:

            return resolve_reference(
                assignments[ref],
                assignments
            )

    # --------------------------------------------------------
    # Ultimo tentativo:
    # prova direttamente parse_value()
    # --------------------------------------------------------

    parsed = parse_value(
        raw
    )

    return resolve_reference(
        parsed,
        assignments
    )


# ============================================================
# FIND SOLUTION
# ============================================================

def find_solution(
    text,
    page_name,
    expected_count
):
    match = re.search(
        r"solution:\$R(\d+)=",
        text
    )

    if not match:
        raise RuntimeError(
            f"Solution reference not found "
            f"for {page_name}"
        )

    solution_index = int(
        match.group(1)
    )

    print(
        f"Solution RSC reference: "
        f"{solution_index}"
    )

    # --------------------------------------------------------
    # Extract assignments
    # --------------------------------------------------------

    assignments = extract_rsc_assignments(
        text
    )

    if solution_index not in assignments:

        raise RuntimeError(
            f"Solution assignment "
            f"${solution_index} not found "
            f"for {page_name}"
        )

    # --------------------------------------------------------
    # Resolve solution
    # --------------------------------------------------------

    solution = resolve_reference(
        assignments[solution_index],
        assignments
    )

    if not isinstance(
        solution,
        dict
    ):
        raise RuntimeError(
            f"Invalid solution "
            f"for {page_name}"
        )

    solution_name = solution.get(
        "name"
    )

    required_cards = solution.get(
        "requiredCards"
    )

    status = solution.get(
        "status"
    )

    print(
        f"Solution: {solution_name} | "
        f"requiredCards={required_cards} | "
        f"status={status}"
    )

    if required_cards != expected_count:

        raise RuntimeError(
            f"Unexpected requiredCards="
            f"{required_cards} for "
            f"{page_name}, expected "
            f"{expected_count}"
        )

    # --------------------------------------------------------
    # Raw items
    # --------------------------------------------------------

    raw_items = solution.get(
        "items"
    )

    if raw_items is None:

        raise RuntimeError(
            f"No solution items found "
            f"for {page_name}"
        )

    print(
        f"Raw items type: "
        f"{type(raw_items).__name__}"
    )

    # --------------------------------------------------------
    # FUT.GG parsing
    # --------------------------------------------------------

    items = parse_items_assignment(
        raw_items,
        assignments
    )

    print(
        f"Resolved items type: "
        f"{type(items).__name__}"
    )

    if not isinstance(
        items,
        list
    ):

        print(
            "DEBUG raw_items:",
            repr(raw_items)[:1000]
        )

        print(
            "DEBUG resolved_items:",
            repr(items)[:1000]
        )

        raise RuntimeError(
            f"Solution items are not "
            f"a list for {page_name}"
        )

    print(
        f"Solution contains "
        f"{len(items)}/{expected_count} cards."
    )

    if len(items) != expected_count:

        raise RuntimeError(
            f"Wrong card count for "
            f"{page_name}: "
            f"{len(items)}/{expected_count}"
        )

    # --------------------------------------------------------
    # Extra validation / debug
    # --------------------------------------------------------

    for i, item in enumerate(
        items,
        start=1
    ):

        if not isinstance(
            item,
            dict
        ):

            print(
                f"DEBUG card #{i}: "
                f"{repr(item)[:500]}"
            )

            raise RuntimeError(
                f"Invalid card item #{i} "
                f"in {page_name}"
            )

    return items


# ============================================================
# PLAYER DATA
# ============================================================

def get_player_name(
    player_ea_id
):
    url = (
        f"https://www.fut.gg/players/"
        f"{player_ea_id}/fc-27"
    )

    try:

        response = session.get(
            url,
            timeout=20
        )

        if response.status_code != 200:

            return (
                f"Player {player_ea_id}"
            )

        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )

        h1 = soup.find(
            "h1"
        )

        if h1:

            name = h1.get_text(
                " ",
                strip=True
            )

            if name:
                return name

    except Exception:
        pass

    return (
        f"Player {player_ea_id}"
    )


def get_version(
    ea