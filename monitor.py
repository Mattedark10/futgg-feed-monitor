import os
import re
import json
import time
import html as html_lib
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

    # --------------------------------------------------------
    # INLINE RSC ASSIGNMENT
    #
    # $R[242]={...}
    # $R[241]=[...]
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # RSC REFERENCE
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # OBJECT
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # ARRAY
    # --------------------------------------------------------

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
# FUT.GG ITEMS
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
# PLAYER PAGE DISCOVERY
# ============================================================

player_page_cache = {}
card_info_cache = {}


def find_player_page(
    player_ea_id,
):
    """
    Trova la pagina principale FUT.GG
    del giocatore usando il playerEaId.

    Esempio:
    /players/233700-gianluca-vialli/
    """

    if (
        player_ea_id
        in player_page_cache
    ):
        return player_page_cache[
            player_ea_id
        ]

    search_url = (
        f"https://www.fut.gg/players/"
        f"?search={player_ea_id}"
    )

    try:

        response = session.get(
            search_url,
            timeout=25,
        )

        response.raise_for_status()

        soup = BeautifulSoup(
            response.text,
            "html.parser",
        )

        pattern = re.compile(
            rf"^/players/"
            rf"{re.escape(str(player_ea_id))}"
            rf"(?:-[^/]+)?/?$"
        )

        for link in soup.find_all(
            "a",
            href=True,
        ):

            href = link.get(
                "href",
                "",
            )

            if pattern.match(href):

                full_url = urljoin(
                    BASE_URL,
                    href,
                )

                player_page_cache[
                    player_ea_id
                ] = full_url

                return full_url

        # ----------------------------------------------------
        # FALLBACK:
        # cerca direttamente nell'HTML
        # ----------------------------------------------------

        regex = re.compile(
            rf'["\']('
            rf'/players/'
            rf'{re.escape(str(player_ea_id))}'
            rf'-[^/"\']+/'
            rf')["\']'
        )

        match = regex.search(
            response.text
        )

        if match:

            full_url = urljoin(
                BASE_URL,
                match.group(1),
            )

            player_page_cache[
                player_ea_id
            ] = full_url

            return full_url

    except Exception as error:

        print(
            f"⚠️ Player page lookup "
            f"failed for "
            f"{player_ea_id}: "
            f"{error}"
        )

    return None


# ============================================================
# FIND EXACT CARD URL
# ============================================================

def find_exact_card_url(
    player_ea_id,
    ea_id,
):
    """
    Cerca il link della carta specifica
    usando contemporaneamente:

    playerEaId
    eaId

    Formato FUT.GG tipico:

    /players/233700-gianluca-vialli/
    27-67342564/
    """

    player_page = find_player_page(
        player_ea_id
    )

    if not player_page:
        return None

    try:

        response = session.get(
            player_page,
            timeout=25,
        )

        response.raise_for_status()

        soup = BeautifulSoup(
            response.text,
            "html.parser",
        )

        # ----------------------------------------------------
        # Cerca link che contenga:
        #
        # /27-{eaId}/
        # ----------------------------------------------------

        target = (
            f"/27-{ea_id}"
        )

        for link in soup.find_all(
            "a",
            href=True,
        ):

            href = link.get(
                "href",
                "",
            )

            if target in href:

                return urljoin(
                    BASE_URL,
                    href,
                )

        # ----------------------------------------------------
        # FALLBACK REGEX
        # ----------------------------------------------------

        regex = re.compile(
            rf'["\']([^"\']*'
            rf'/27-'
            rf'{re.escape(str(ea_id))}'
            rf'/?'
            rf')["\']'
        )

        match = regex.search(
            response.text
        )

        if match:

            return urljoin(
                player_page,
                match.group(1),
            )

        # ----------------------------------------------------
        # STANDARD CARD
        #
        # Spesso eaId == playerEaId
        # ----------------------------------------------------

        if (
            str(ea_id)
            == str(player_ea_id)
        ):

            return (
                player_page.rstrip("/")
                + f"/27-{ea_id}/"
            )

    except Exception as error:

        print(
            f"⚠️ Exact card lookup "
            f"failed for {ea_id}: "
            f"{error}"
        )

    return None


# ============================================================
# CARD INFORMATION
# ============================================================

def extract_name_and_version(
    page_html,
    player_ea_id,
    ea_id,
):
    soup = BeautifulSoup(
        page_html,
        "html.parser",
    )

    # --------------------------------------------------------
    # TITLE SOURCE
    # --------------------------------------------------------

    heading = soup.find("h1")

    heading_text = ""

    if heading:

        heading_text = (
            heading.get_text(
                " ",
                strip=True,
            )
        )

    # --------------------------------------------------------
    # FALLBACK TITLE
    # --------------------------------------------------------

    if not heading_text:

        title = soup.find("title")

        if title:

            heading_text = (
                title.get_text(
                    " ",
                    strip=True,
                )
            )

    heading_text = html_lib.unescape(
        heading_text
    ).strip()

    # --------------------------------------------------------
    # VERSION
    # --------------------------------------------------------

    upper = heading_text.upper()

    if (
        "PRISTINE HOLOGRAPHIC"
        in upper
    ):
        version = "PRISTINE HOLO"

    elif (
        "HOLOGRAPHIC"
        in upper
    ):
        version = "HOLO"

    else:
        version = "BASE"

    # --------------------------------------------------------
    # NAME
    #
    # FUT.GG:
    #
    # Gianluca Vialli -
    # Base Hero Pristine Holographic 89 OVR
    # --------------------------------------------------------

    name = None

    if " - " in heading_text:

        name = heading_text.split(
            " - ",
            1,
        )[0].strip()

    # --------------------------------------------------------
    # META FALLBACK
    # --------------------------------------------------------

    if not name:

        meta = soup.find(
            "meta",
            attrs={
                "property": "og:title"
            },
        )

        if meta:

            content = meta.get(
                "content",
                "",
            )

            if " - " in content:

                name = content.split(
                    " - ",
                    1,
                )[0].strip()

    if not name:

        name = (
            f"Player {player_ea_id}"
        )

    return (
        name,
        version,
    )


def get_card_info(
    player_ea_id,
    ea_id,
):
    """
    Restituisce:

    {
        name,
        version,
        url
    }
    """

    cache_key = (
        int(player_ea_id),
        int(ea_id),
    )

    if cache_key in card_info_cache:

        return card_info_cache[
            cache_key
        ]

    # --------------------------------------------------------
    # FIND EXACT CARD
    # --------------------------------------------------------

    card_url = find_exact_card_url(
        player_ea_id,
        ea_id,
    )

    # --------------------------------------------------------
    # FALLBACK
    # --------------------------------------------------------

    if not card_url:

        player_page = find_player_page(
            player_ea_id
        )

        result = {
            "name": (
                f"Player "
                f"{player_ea_id}"
            ),
            "version": "BASE",
            "url": (
                player_page
                if player_page
                else BASE_URL
            ),
        }

        card_info_cache[
            cache_key
        ] = result

        return result

    # --------------------------------------------------------
    # DOWNLOAD EXACT CARD PAGE
    # --------------------------------------------------------

    try:

        response = session.get(
            card_url,
            timeout=25,
        )

        response.raise_for_status()

        name, version = (
            extract_name_and_version(
                response.text,
                player_ea_id,
                ea_id,
            )
        )

        result = {
            "name": name,
            "version": version,
            "url": card_url,
        }

        card_info_cache[
            cache_key
        ] = result

        return result

    except Exception as error:

        print(
            f"⚠️ Card info lookup "
            f"failed for {ea_id}: "
            f"{error}"
        )

        result = {
            "name": (
                f"Player "
                f"{player_ea_id}"
            ),
            "version": "BASE",
            "url": card_url,
        }

        card_info_cache[
            cache_key
        ] = result

        return result


# ============================================================
# PARSE PLAYERS
# ============================================================

def parse_players(
    items,
    page_name,
):
    players = []

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

        # ----------------------------------------------------
        # GET REAL CARD INFO
        # ----------------------------------------------------

        info = get_card_info(
            player_ea_id,
            ea_id,
        )

        card = {
            "ea_id": ea_id,
            "player_ea_id": (
                player_ea_id
            ),
            "name": info[
                "name"
            ],
            "overall": overall,
            "rarity_id": rarity_id,
            "version": info[
                "version"
            ],
            "url": info[
                "url"
            ],
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
# COMPARISON
# ============================================================

def card_key(card):
    """
    ea_id identifica la carta specifica.

    Questo permette di distinguere:

    BASE
    HOLO
    PRISTINE HOLO

    anche dello stesso giocatore.
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

        for _ in range(count):

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

        for _ in range(count):

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
# FORMAT TELEGRAM
# ============================================================

def format_card(card):
    name = card.get(
        "name",
        "Unknown",
    )

    overall = card.get(
        "overall",
        "?",
    )

    version = card.get(
        "version",
        "BASE",
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

            # ------------------------------------------------
            # DOWNLOAD
            # ------------------------------------------------

            page_html = download_page(
                config["url"]
            )

            # ------------------------------------------------
            # SOLUTION
            # ------------------------------------------------

            items = find_solution(
                page_html,
                page_name,
                config["expected"],
            )

            # ------------------------------------------------
            # PLAYERS
            # ------------------------------------------------

            players = parse_players(
                items,
                page_name,
            )

            old_players = state.get(
                page_name,
                [],
            )

            # ------------------------------------------------
            # FIRST STATE
            # ------------------------------------------------

            if not old_players:

                print(
                    f"🆕 First state saved "
                    f"for {page_name}."
                )

            # ------------------------------------------------
            # COMPARE
            # ------------------------------------------------

            else:

                out_cards, in_cards = (
                    compare_cards(
                        old_players,
                        players,
                    )
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
                                f"• "
                                f"{format_card(card)}"
                                f"\n"
                            )

                        message += "\n"

                    if in_cards:

                        message += (
                            "🟢 <b>IN</b>\n"
                        )

                        for card in in_cards:

                            message += (
                                f"• "
                                f"{format_card(card)}"
                                f"\n"
                            )

                        message += "\n"

                    message += (
                        f'<a href="'
                        f'{config["url"]}'
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

            # ------------------------------------------------
            # SAVE SUCCESSFUL PAGE
            # ------------------------------------------------

            state[
                page_name
            ] = players

            successful_pages += 1

        except Exception as error:

            print(
                f"❌ ERROR {page_name}: "
                f"{error}"
            )

            telegram_send(
                f"⚠️ <b>FUT.GG Monitor "
                f"Error</b>\n\n"
                f"<b>{page_name}</b>\n"
                f"{str(error)}"
            )

            print(
                f"Previous state for "
                f"{page_name} was preserved."
            )

    # ========================================================
    # NOTHING SUCCEEDED
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
    # SAVE
    # ========================================================

    save_state(
        state
    )

    save_trending(
        state
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