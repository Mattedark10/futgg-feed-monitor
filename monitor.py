import os
import re
import json
import time
from collections import Counter
from urllib.parse import urljoin

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
CACHE_FILE = "card_cache.json"

BASE_URL = "https://www.fut.gg"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

session = requests.Session()
session.headers.update(HEADERS)


# ============================================================
# HTTP
# ============================================================

def download_page(url):
    response = session.get(
        url,
        timeout=30,
    )

    response.raise_for_status()

    text = response.text

    print(
        f"Downloaded {len(text):,} characters."
    )

    return text


# ============================================================
# GENERIC RSC PARSER
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
    closing,
):
    depth = 0

    in_string = False
    quote = None
    escape = False

    for i in range(start, len(text)):

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

    if value in (
        "null",
        "undefined",
    ):
        return None

    if (
        len(value) >= 2
        and value[0] in ('"', "'", "`")
        and value[-1] == value[0]
    ):
        return value[1:-1]

    if re.fullmatch(
        r"-?\d+",
        value,
    ):
        try:
            return int(value)
        except Exception:
            pass

    if re.fullmatch(
        r"-?\d+\.\d+",
        value,
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
    # $R[242]={...}
    # $R[241]=[...]
    # ========================================================

    inline_assignment = re.match(
        r"^\$R\[(\d+)\]=(.*)$",
        value,
        re.DOTALL,
    )

    if inline_assignment:

        assigned_value = (
            inline_assignment
            .group(2)
            .strip()
        )

        return parse_value(
            assigned_value
        )

    # ========================================================
    # RSC REFERENCE
    # ========================================================

    ref_match = re.fullmatch(
        r"\$R\[(\d+)\]",
        value,
    )

    if ref_match:

        return {
            "__ref__": int(
                ref_match.group(1)
            )
        }

    # ========================================================
    # OBJECT
    # ========================================================

    if value.startswith("{"):

        end = find_matching(
            value,
            0,
            "{",
            "}",
        )

        if (
            end != -1
            and end == len(value) - 1
        ):
            return parse_object(
                value[1:end]
            )

    # ========================================================
    # ARRAY
    # ========================================================

    if value.startswith("["):

        end = find_matching(
            value,
            0,
            "[",
            "]",
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
                ",",
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
        ",",
    )

    for part in parts:

        if ":" not in part:
            continue

        key, value = part.split(
            ":",
            1,
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
        r"\$R\[(\d+)\]="
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
                "}",
            )

        elif first == "[":

            end = find_matching(
                text,
                start,
                "[",
                "]",
            )

        else:
            continue

        if end == -1:
            continue

        raw_value = text[
            start:end + 1
        ]

        try:

            assignments[index] = (
                parse_value(
                    raw_value
                )
            )

        except Exception:
            continue

    print(
        f"Found {len(assignments)} "
        f"RSC assignments."
    )

    return assignments


# ============================================================
# RESOLVE REFERENCES
# ============================================================

def resolve_reference(
    value,
    assignments,
    depth=0,
):
    if depth > 100:
        return value

    if isinstance(
        value,
        dict,
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
                depth + 1,
            )

        result = {}

        for key, val in value.items():

            result[key] = (
                resolve_reference(
                    val,
                    assignments,
                    depth + 1,
                )
            )

        return result

    if isinstance(
        value,
        list,
    ):

        return [
            resolve_reference(
                item,
                assignments,
                depth + 1,
            )
            for item in value
        ]

    return value


# ============================================================
# ITEMS
# ============================================================

def parse_items_assignment(
    raw_items,
    assignments,
):
    if not isinstance(
        raw_items,
        str,
    ):

        return resolve_reference(
            raw_items,
            assignments,
        )

    raw = raw_items.strip()

    match = re.match(
        r"^\$R\[(\d+)\]=(\[.*\])$",
        raw,
        re.DOTALL,
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
            assignments,
        )

    ref_match = re.fullmatch(
        r"\$R\[(\d+)\]",
        raw,
    )

    if ref_match:

        ref = int(
            ref_match.group(1)
        )

        if ref in assignments:

            return resolve_reference(
                assignments[ref],
                assignments,
            )

    parsed = parse_value(
        raw
    )

    return resolve_reference(
        parsed,
        assignments,
    )


# ============================================================
# FIND SOLUTION
# ============================================================

def find_solution(
    text,
    page_name,
    expected_count,
):
    match = re.search(
        r"solution:\$R\[(\d+)\]=",
        text,
    )

    if not match:

        raise RuntimeError(
            f"Solution reference not "
            f"found for {page_name}"
        )

    solution_index = int(
        match.group(1)
    )

    print(
        f"Solution RSC reference: "
        f"{solution_index}"
    )

    assignments = (
        extract_rsc_assignments(
            text
        )
    )

    if solution_index not in assignments:

        raise RuntimeError(
            f"Solution assignment "
            f"${solution_index} not found "
            f"for {page_name}"
        )

    solution = resolve_reference(
        assignments[
            solution_index
        ],
        assignments,
    )

    if not isinstance(
        solution,
        dict,
    ):

        raise RuntimeError(
            f"Invalid solution "
            f"for {page_name}"
        )

    solution_name = (
        solution.get("name")
    )

    required_cards = (
        solution.get(
            "requiredCards"
        )
    )

    status = (
        solution.get("status")
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

    items = parse_items_assignment(
        raw_items,
        assignments,
    )

    print(
        f"Resolved items type: "
        f"{type(items).__name__}"
    )

    if not isinstance(
        items,
        list,
    ):

        raise RuntimeError(
            f"Solution items are not "
            f"a list for {page_name}"
        )

    print(
        f"Solution contains "
        f"{len(items)}/"
        f"{expected_count} cards."
    )

    if len(items) != expected_count:

        raise RuntimeError(
            f"Wrong card count for "
            f"{page_name}: "
            f"{len(items)}/"
            f"{expected_count}"
        )

    for number, item in enumerate(
        items,
        start=1,
    ):

        if not isinstance(
            item,
            dict,
        ):

            raise RuntimeError(
                f"Invalid card item "
                f"#{number} in {page_name}"
            )

        if item.get("eaId") is None:

            raise RuntimeError(
                f"Card #{number} without "
                f"eaId in {page_name}"
            )

        if (
            item.get(
                "playerEaId"
            )
            is None
        ):

            raise RuntimeError(
                f"Card #{number} without "
                f"playerEaId in "
                f"{page_name}"
            )

    return items


# ============================================================
# CACHE
# ============================================================

def load_card_cache():
    if not os.path.exists(
        CACHE_FILE
    ):
        return {}

    try:

        with open(
            CACHE_FILE,
            "r",
            encoding="utf-8",
        ) as file:

            data = json.load(
                file
            )

        if isinstance(
            data,
            dict,
        ):
            return data

    except Exception as error:

        print(
            f"⚠️ Could not load "
            f"{CACHE_FILE}: {error}"
        )

    return {}


def save_card_cache(cache):
    with open(
        CACHE_FILE,
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            cache,
            file,
            ensure_ascii=False,
            indent=2,
        )


card_info_cache = load_card_cache()


# ============================================================
# VERSION
# ============================================================

def clean_version(text):
    upper = text.upper()

    if (
        "PRISTINE HOLOGRAPHIC"
        in upper
        or "PRISTINE HOLO"
        in upper
    ):
        return "PRISTINE HOLO"

    if (
        "REGULAR HOLOGRAPHIC"
        in upper
        or "HOLOGRAPHIC"
        in upper
        or " HOLO " in f" {upper} "
    ):
        return "HOLO"

    return "BASE"


# ============================================================
# EXTRACT CARD INFO
# ============================================================

def extract_card_from_html(
    page_html,
    player_ea_id,
    ea_id,
):
    soup = BeautifulSoup(
        page_html,
        "html.parser",
    )

    sources = []

    # --------------------------------------------------------
    # H1
    # --------------------------------------------------------

    h1 = soup.find("h1")

    if h1:

        text = h1.get_text(
            " ",
            strip=True,
        )

        if text:
            sources.append(text)

    # --------------------------------------------------------
    # OG TITLE
    # --------------------------------------------------------

    og_title = soup.find(
        "meta",
        attrs={
            "property": "og:title"
        },
    )

    if og_title:

        text = og_title.get(
            "content",
            "",
        ).strip()

        if text:
            sources.append(text)

    # --------------------------------------------------------
    # TITLE
    # --------------------------------------------------------

    title = soup.find(
        "title"
    )

    if title:

        text = title.get_text(
            " ",
            strip=True,
        )

        if text:
            sources.append(text)

    combined = " | ".join(
        sources
    )

    version = clean_version(
        combined
    )

    # --------------------------------------------------------
    # NAME
    # --------------------------------------------------------

    name = None

    for source in sources:

        if " - " in source:

            candidate = source.split(
                " - ",
                1,
            )[0].strip()

            if (
                candidate
                and "FUT.GG" not in candidate.upper()
            ):

                name = candidate
                break

    # --------------------------------------------------------
    # JSON / RSC FALLBACKS
    # --------------------------------------------------------

    if not name:

        patterns = [
            r'playerName:"([^"]+)"',
            r'"playerName":"([^"]+)"',
            r'fullName:"([^"]+)"',
            r'"fullName":"([^"]+)"',
        ]

        for pattern in patterns:

            match = re.search(
                pattern,
                page_html,
            )

            if match:

                candidate = (
                    match.group(1)
                    .strip()
                )

                if candidate:

                    name = candidate
                    break

    if not name:

        name = (
            f"Player {player_ea_id}"
        )

    return {
        "name": name,
        "version": version,
    }


# ============================================================
# FIND EXACT CARD IN GALLERY
# ============================================================

def find_card_in_gallery_html(
    gallery_html,
    ea_id,
):
    if not gallery_html:
        return None

    escaped_id = re.escape(
        str(ea_id)
    )

    patterns = [
        (
            rf'https://www\.fut\.gg/'
            rf'players/[^"\'\\\s]+/'
            rf'27-{escaped_id}/?'
        ),
        (
            rf'/players/[^"\'\\\s]+/'
            rf'27-{escaped_id}/?'
        ),
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            gallery_html,
            re.IGNORECASE,
        )

        if not match:
            continue

        url = match.group(0)

        url = (
            url
            .replace("\\u002F", "/")
            .replace("\\/", "/")
        )

        if url.startswith("/"):

            url = (
                BASE_URL
                + url
            )

        return url

    return None


# ============================================================
# FUT.GG SEARCH
# ============================================================

def search_futgg_card(
    player_ea_id,
    ea_id,
):
    """
    Cerca direttamente tramite eaId.
    Non assumiamo che playerEaId sia lo slug.
    """

    search_queries = [
        str(ea_id),
        str(player_ea_id),
    ]

    for query in search_queries:

        search_url = (
            "https://www.fut.gg/players/"
            f"?search={query}"
        )

        try:

            response = session.get(
                search_url,
                timeout=25,
            )

            if (
                response.status_code
                != 200
            ):
                continue

            text = response.text

            escaped_id = re.escape(
                str(ea_id)
            )

            patterns = [
                (
                    rf'https://www\.fut\.gg/'
                    rf'players/[^"\'\\\s]+/'
                    rf'27-{escaped_id}/?'
                ),
                (
                    rf'/players/[^"\'\\\s]+/'
                    rf'27-{escaped_id}/?'
                ),
            ]

            for pattern in patterns:

                match = re.search(
                    pattern,
                    text,
                    re.IGNORECASE,
                )

                if not match:
                    continue

                url = match.group(0)

                url = (
                    url
                    .replace(
                        "\\u002F",
                        "/",
                    )
                    .replace(
                        "\\/",
                        "/",
                    )
                )

                if url.startswith(
                    "/"
                ):

                    url = (
                        BASE_URL
                        + url
                    )

                return url

            # ------------------------------------------------
            # BEAUTIFULSOUP FALLBACK
            # ------------------------------------------------

            soup = BeautifulSoup(
                text,
                "html.parser",
            )

            for link in soup.find_all(
                "a",
                href=True,
            ):

                href = link.get(
                    "href",
                    "",
                )

                if (
                    f"27-{ea_id}"
                    in href
                ):

                    return urljoin(
                        BASE_URL,
                        href,
                    )

        except Exception as error:

            print(
                f"  ⚠️ Search failed "
                f"for {ea_id}: "
                f"{error}"
            )

    return None


# ============================================================
# EXTRACT NAME FROM GALLERY
# ============================================================

def find_name_near_card(
    gallery_html,
    player_ea_id,
    ea_id,
):
    """
    Prova a recuperare il nome direttamente
    dai dati RSC/HTML della Gallery.

    Non assegna mai una versione da questo metodo.
    """

    if not gallery_html:
        return None

    ids = [
        str(ea_id),
        str(player_ea_id),
    ]

    for target_id in ids:

        for match in re.finditer(
            re.escape(target_id),
            gallery_html,
        ):

            start = max(
                0,
                match.start() - 2000,
            )

            end = min(
                len(gallery_html),
                match.end() + 2000,
            )

            chunk = gallery_html[
                start:end
            ]

            patterns = [
                r'playerName:"([^"]+)"',
                r'"playerName":"([^"]+)"',
                r'fullName:"([^"]+)"',
                r'"fullName":"([^"]+)"',
                r'commonName:"([^"]+)"',
                r'"commonName":"([^"]+)"',
            ]

            for pattern in patterns:

                name_match = re.search(
                    pattern,
                    chunk,
                )

                if name_match:

                    name = (
                        name_match
                        .group(1)
                        .strip()
                    )

                    if name:
                        return name

    return None


# ============================================================
# CARD INFO
# ============================================================

def get_card_info(
    player_ea_id,
    ea_id,
    gallery_html=None,
):
    player_ea_id = int(
        player_ea_id
    )

    ea_id = int(
        ea_id
    )

    cache_key = str(
        ea_id
    )

    # ========================================================
    # CACHE
    # ========================================================

    cached = card_info_cache.get(
        cache_key
    )

    if isinstance(
        cached,
        dict,
    ):

        cached_name = cached.get(
            "name"
        )

        cached_version = cached.get(
            "version"
        )

        # Non riutilizziamo vecchi fallback sbagliati.

        if (
            cached_name
            and not cached_name.startswith(
                "Player "
            )
            and cached_version
            and cached_version
            != "UNKNOWN"
        ):

            print(
                f"  ✓ Cache: "
                f"{cached_name} "
                f"[{cached_version}]"
            )

            return cached

    print(
        f"  Resolving Item ID "
        f"{ea_id}..."
    )

    # ========================================================
    # NAME FROM GALLERY
    # ========================================================

    gallery_name = (
        find_name_near_card(
            gallery_html,
            player_ea_id,
            ea_id,
        )
    )

    # ========================================================
    # CARD URL FROM GALLERY
    # ========================================================

    card_url = (
        find_card_in_gallery_html(
            gallery_html,
            ea_id,
        )
    )

    if card_url:

        print(
            "  ✓ Exact URL found "
            "inside Gallery"
        )

    # ========================================================
    # SEARCH FALLBACK
    # ========================================================

    if not card_url:

        card_url = (
            search_futgg_card(
                player_ea_id,
                ea_id,
            )
        )

        if card_url:

            print(
                "  ✓ Exact URL found "
                "through FUT.GG search"
            )

    # ========================================================
    # EXACT PAGE
    # ========================================================

    if card_url:

        print(
            f"  → {card_url}"
        )

        try:

            response = session.get(
                card_url,
                timeout=25,
            )

            response.raise_for_status()

            info = (
                extract_card_from_html(
                    response.text,
                    player_ea_id,
                    ea_id,
                )
            )

            name = info.get(
                "name"
            )

            version = info.get(
                "version"
            )

            if (
                not name
                or name.startswith(
                    "Player "
                )
            ):

                if gallery_name:
                    name = gallery_name

            if not name:

                name = (
                    f"Player "
                    f"{player_ea_id}"
                )

            if not version:

                version = "UNKNOWN"

            result = {
                "name": name,
                "version": version,
                "url": card_url,
                "player_ea_id": (
                    player_ea_id
                ),
                "ea_id": ea_id,
            }

            print(
                f"  ✓ {name} "
                f"[{version}]"
            )

            # -----------------------------------------------
            # Salva solo risultati utili
            # -----------------------------------------------

            if (
                not name.startswith(
                    "Player "
                )
                and version
                != "UNKNOWN"
            ):

                card_info_cache[
                    cache_key
                ] = result

            return result

        except Exception as error:

            print(
                f"  ⚠️ Exact card page "
                f"failed: {error}"
            )

    # ========================================================
    # FALLBACK
    #
    # IMPORTANTISSIMO:
    # non inventiamo BASE.
    # ========================================================

    if gallery_name:

        name = gallery_name

    else:

        name = (
            f"Player "
            f"{player_ea_id}"
        )

    result = {
        "name": name,
        "version": "UNKNOWN",
        "url": card_url or BASE_URL,
        "player_ea_id": (
            player_ea_id
        ),
        "ea_id": ea_id,
    }

    print(
        f"  ⚠️ {name} "
        f"[UNKNOWN]"
    )

    return result


# ============================================================
# PARSE PLAYERS
# ============================================================

def parse_players(
    items,
    page_name,
    gallery_html,
):
    players = []

    print()
    print("Resolving cards...")

    for item in items:

        ea_id = item.get(
            "eaId"
        )

        player_ea_id = item.get(
            "playerEaId"
        )

        overall = item.get(
            "overall"
        )

        rarity_id = item.get(
            "rarityEaId"
        )

        info = get_card_info(
            player_ea_id,
            ea_id,
            gallery_html,
        )

        card = {
            "ea_id": ea_id,
            "player_ea_id": (
                player_ea_id
            ),
            "name": info.get(
                "name"
            ),
            "overall": overall,
            "rarity_id": rarity_id,
            "version": info.get(
                "version",
                "UNKNOWN",
            ),
            "url": info.get(
                "url",
                BASE_URL,
            ),
        }

        players.append(
            card
        )

        print(
            f"- {card['name']} "
            f"{overall} "
            f"{card['version']}"
        )

    return players


# ============================================================
# STATE
# ============================================================

def load_state():
    if not os.path.exists(
        STATE_FILE
    ):

        return {
            page: []
            for page in PAGES
        }

    try:

        with open(
            STATE_FILE,
            "r",
            encoding="utf-8",
        ) as file:

            data = json.load(
                file
            )

        if not isinstance(
            data,
            dict,
        ):

            raise ValueError(
                "players.json invalid"
            )

        for page in PAGES:

            if page not in data:
                data[page] = []

        return data

    except Exception as error:

        print(
            f"⚠️ Could not load "
            f"{STATE_FILE}: {error}"
        )

        return {
            page: []
            for page in PAGES
        }


def save_state(data):
    with open(
        STATE_FILE,
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=2,
        )


# ============================================================
# TRENDING
# ============================================================

def save_trending(data):
    directory = os.path.dirname(
        TRENDING_FILE
    )

    if directory:

        os.makedirs(
            directory,
            exist_ok=True,
        )

    output = {
        "updated_at": int(
            time.time()
        ),
        "pages": data,
    }

    with open(
        TRENDING_FILE,
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            output,
            file,
            ensure_ascii=False,
            indent=2,
        )


# ============================================================
# TELEGRAM
# ============================================================

def telegram_send(message):
    token = os.getenv(
        "TELEGRAM_BOT_TOKEN"
    )

    chat_id = os.getenv(
        "TELEGRAM_CHAT_ID"
    )

    if not token or not chat_id:

        print(
            "⚠️ TELEGRAM secrets missing"
        )

        return False

    url = (
        f"https://api.telegram.org/"
        f"bot{token}/sendMessage"
    )

    try:

        response = requests.post(
            url,
            json={
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=20,
        )

        response.raise_for_status()

        return True

    except Exception as error:

        print(
            f"⚠️ Telegram error: "
            f"{error}"
        )

        return False


# ============================================================
# CARD COMPARISON
# ============================================================

def card_key(card):
    """
    ea_id = carta specifica.

    Quindi:

    Maradona BASE
    Maradona HOLO
    Maradona PRISTINE

    sono carte diverse.
    """

    return card.get(
        "ea_id"
    )


def compare_cards(
    old_cards,
    new_cards,
):
    old_counter = Counter(
        card_key(card)
        for card in old_cards
    )

    new_counter = Counter(
        card_key(card)
        for card in new_cards
    )

    out_cards = []
    in_cards = []

    remaining_old = list(
        old_cards
    )

    for key, count in (
        old_counter
        - new_counter
    ).items():

        for _ in range(
            count
        ):

            for index, card in enumerate(
                remaining_old
            ):

                if (
                    card_key(card)
                    == key
                ):

                    out_cards.append(
                        card
                    )

                    remaining_old.pop(
                        index
                    )

                    break

    remaining_new = list(
        new_cards
    )

    for key, count in (
        new_counter
        - old_counter
    ).items():

        for _ in range(
            count
        ):

            for index, card in enumerate(
                remaining_new
            ):

                if (
                    card_key(card)
                    == key
                ):

                    in_cards.append(
                        card
                    )

                    remaining_new.pop(
                        index
                    )

                    break

    return (
        out_cards,
        in_cards,
    )


# ============================================================
# TELEGRAM FORMAT
# ============================================================

def escape_telegram_html(text):
    text = str(text)

    return (
        text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def format_card(card):
    name = escape_telegram_html(
        card.get(
            "name",
            "Unknown",
        )
    )

    overall = card.get(
        "overall",
        "?",
    )

    version = escape_telegram_html(
        card.get(
            "version",
            "UNKNOWN",
        )
    )

    return (
        f"{name} "
        f"{overall} "
        f"<b>{version}</b>"
    )


# ============================================================
# MAIN
# ============================================================

def main():
    print(
        "=" * 60
    )

    print(
        "FUT.GG MONITOR"
    )

    print(
        "=" * 60
    )

    state = load_state()

    successful_pages = 0

    for (
        page_name,
        config,
    ) in PAGES.items():

        print()

        print(
            "=" * 60
        )

        print(
            f"Scanning {page_name}"
        )

        print(
            config["url"]
        )

        print(
            "=" * 60
        )

        try:

            # =================================================
            # DOWNLOAD GALLERY
            # =================================================

            page_html = download_page(
                config["url"]
            )

            # =================================================
            # SOLUTION
            # =================================================

            items = find_solution(
                page_html,
                page_name,
                config[
                    "expected"
                ],
            )

            # =================================================
            # CARDS
            # =================================================

            players = parse_players(
                items,
                page_name,
                page_html,
            )

            old_players = state.get(
                page_name,
                [],
            )

            # =================================================
            # FIRST RUN
            # =================================================

            if not old_players:

                print(
                    f"🆕 First state saved "
                    f"for {page_name}."
                )

            # =================================================
            # COMPARE
            # =================================================

            else:

                (
                    out_cards,
                    in_cards,
                ) = compare_cards(
                    old_players,
                    players,
                )

                if (
                    out_cards
                    or in_cards
                ):

                    message = (
                        f"<b>{page_name}</b>"
                        f"\n\n"
                    )

                    if out_cards:

                        message += (
                            "🔴 <b>OUT</b>\n"
                        )

                        for card in out_cards:

                            message += (
                                "• "
                                + format_card(
                                    card
                                )
                                + "\n"
                            )

                        message += "\n"

                    if in_cards:

                        message += (
                            "🟢 <b>IN</b>\n"
                        )

                        for card in in_cards:

                            message += (
                                "• "
                                + format_card(
                                    card
                                )
                                + "\n"
                            )

                        message += "\n"

                    page_url = (
                        config["url"]
                    )

                    message += (
                        f'<a href="'
                        f'{page_url}'
                        f'">'
                        f"Open {page_name}"
                        f"</a>"
                    )

                    if telegram_send(
                        message
                    ):

                        print(
                            "📨 Telegram "
                            "notification sent."
                        )

                else:

                    print(
                        "No card changes."
                    )

            # =================================================
            # SAVE ONLY SUCCESSFUL PAGE
            # =================================================

            state[
                page_name
            ] = players

            successful_pages += 1

        except Exception as error:

            print(
                f"❌ ERROR "
                f"{page_name}: "
                f"{error}"
            )

            telegram_send(
                f"⚠️ <b>FUT.GG "
                f"Monitor Error</b>"
                f"\n\n"
                f"<b>{page_name}</b>"
                f"\n"
                f"{escape_telegram_html(error)}"
            )

            print(
                f"Previous state for "
                f"{page_name} "
                f"was preserved."
            )

    # ========================================================
    # NO SUCCESS
    # ========================================================

    if successful_pages == 0:

        print()

        print(
            "❌ No pages succeeded."
        )

        print()

        print(
            "=" * 60
        )

        print(
            "MONITOR FINISHED"
        )

        print(
            "=" * 60
        )

        return

    # ========================================================
    # SAVE FILES
    # ========================================================

    save_state(
        state
    )

    save_trending(
        state
    )

    save_card_cache(
        card_info_cache
    )

    print()

    print(
        f"✅ {successful_pages}/"
        f"{len(PAGES)} "
        f"pages succeeded."
    )

    print(
        f"Saved {STATE_FILE}"
    )

    print(
        f"Saved {TRENDING_FILE}"
    )

    print(
        f"Saved {CACHE_FILE}"
    )

    print()

    print(
        "=" * 60
    )

    print(
        "MONITOR FINISHED"
    )

    print(
        "=" * 60
    )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()