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
# RSC PARSER
# ============================================================

def split_top_level(text, separator=","):
    """
    Divide un'espressione JS/RSC usando il separatore
    solo quando siamo al livello principale.

    Esempio:

        a:1,b:{x:2},c:[3,4]

    diventa:

        a:1
        b:{x:2}
        c:[3,4]
    """

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
    """
    Trova la parentesi di chiusura corrispondente.
    """

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

    # Boolean
    if value == "true":
        return True

    if value == "false":
        return False

    # Null
    if value == "null":
        return None

    if value == "undefined":
        return None

    # String
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

    # Integer
    if re.fullmatch(
        r"-?\d+",
        value
    ):

        try:
            return int(value)

        except Exception:
            pass

    # Float
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
    """
    Parser per valori RSC/JavaScript semplificati.

    Supporta:

        $R[123]

        {...}

        [...]

        stringhe

        numeri

        booleani

        null
    """

    value = value.strip()

    # --------------------------------------------------------
    # Reference
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

    # --------------------------------------------------------
    # Primitive
    # --------------------------------------------------------

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

        # Rimuove eventuali virgolette dal nome
        # della proprietà.
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
# EXTRACT RSC ASSIGNMENTS
# ============================================================

def extract_rsc_assignments(text):
    """
    Estrae entrambe le forme:

        $R[123]={...}

    e:

        $R[123]=[...]

    """

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

        # ----------------------------------------------------
        # Object
        # ----------------------------------------------------

        if first == "{":

            end = find_matching(
                text,
                start,
                "{",
                "}"
            )

        # ----------------------------------------------------
        # Array
        # ----------------------------------------------------

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
    """
    Risolve ricorsivamente i riferimenti RSC.

    FUT.GG usa riferimenti come:

        $R[240]
        $R[241]

    Un riferimento può puntare a:

        object
        array
        primitive
        altro riferimento
    """

    if depth > 100:
        return value

    # --------------------------------------------------------
    # Reference / Object
    # --------------------------------------------------------

    if isinstance(
        value,
        dict
    ):

        # Reference puro
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

        # Normal object
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

        result = []

        for item in value:

            resolved = resolve_reference(
                item,
                assignments,
                depth + 1
            )

            result.append(
                resolved
            )

        return result

    # --------------------------------------------------------
    # Primitive
    # --------------------------------------------------------

    return value


# ============================================================
# FIND SOLUTION
# ============================================================

def find_solution(
    text,
    page_name,
    expected_count
):
    """
    Trova la solution di FUT.GG e recupera
    l'array items associato.
    """

    # --------------------------------------------------------
    # 1. Trova la reference della solution
    # --------------------------------------------------------

    match = re.search(
        r"solution:\$R\[(\d+)\]=",
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
    # 2. Estrai tutte le assegnazioni
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
    # 3. Risolvi la solution
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
    # 4. Recupera items
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
    # 5. Risolvi eventuale reference
    # --------------------------------------------------------

    items = resolve_reference(
        raw_items,
        assignments
    )

    print(
        f"Resolved items type: "
        f"{type(items).__name__}"
    )

    # --------------------------------------------------------
    # 6. Validazione
    # --------------------------------------------------------

    if not isinstance(
        items,
        list
    ):

        print(
            "DEBUG raw_items:",
            repr(raw_items)[:500]
        )

        print(
            "DEBUG resolved_items:",
            repr(items)[:500]
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
    ea_id
):

    url = (
        f"https://www.fut.gg/players/"
        f"{ea_id}/fc-27-{ea_id}"
    )

    try:

        response = session.get(
            url,
            timeout=20
        )

        if response.status_code != 200:

            return "BASE"

        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )

        h1 = soup.find(
            "h1"
        )

        text = ""

        if h1:

            text = h1.get_text(
                " ",
                strip=True
            ).upper()

        if "PRISTINE" in text:

            return "PRISTINE HOLO"

        if "HOLO" in text:

            return "HOLO"

    except Exception:

        pass

    return "BASE"


def get_card_link(
    ea_id
):

    return (
        f"https://www.fut.gg/players/"
        f"{ea_id}/fc-27-{ea_id}"
    )


def parse_players(
    items,
    page_name
):

    players = []

    for item in items:

        if not isinstance(
            item,
            dict
        ):

            raise RuntimeError(
                f"Invalid card item "
                f"in {page_name}"
            )

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

        if ea_id is None:

            raise RuntimeError(
                f"Card without eaId "
                f"in {page_name}"
            )

        if player_ea_id is None:

            raise RuntimeError(
                f"Card without "
                f"playerEaId in {page_name}"
            )

        name = get_player_name(
            player_ea_id
        )

        # Holographics sono sempre HOLO
        if page_name == "Holographics":

            version = "HOLO"

        else:

            version = get_version(
                ea_id
            )

        card = {
            "ea_id": ea_id,
            "player_ea_id": player_ea_id,
            "name": name,
            "overall": overall,
            "rarity_id": rarity_id,
            "version": version,
            "url": get_card_link(
                ea_id
            ),
        }

        players.append(
            card
        )

        print(
            f"- {name} "
            f"{overall} "
            f"{version}"
        )

    return players


# ============================================================
# FILES
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
            encoding="utf-8"
        ) as f:

            data = json.load(
                f
            )

        for page in PAGES:

            if page not in data:

                data[page] = []

        return data

    except Exception:

        return {
            page: []
            for page in PAGES
        }


def save_state(
    data
):

    with open(
        STATE_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )


def save_trending(
    data
):

    directory = os.path.dirname(
        TRENDING_FILE
    )

    if directory:

        os.makedirs(
            directory,
            exist_ok=True
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
        encoding="utf-8"
    ) as f:

        json.dump(
            output,
            f,
            ensure_ascii=False,
            indent=2
        )


# ============================================================
# TELEGRAM
# ============================================================

def telegram_send(
    message
):

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

        return

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
            timeout=20
        )

        response.raise_for_status()

    except Exception as e:

        print(
            f"⚠️ Telegram error: {e}"
        )


# ============================================================
# COMPARISON
# ============================================================

def card_key(
    card
):

    return (
        card.get("ea_id"),
        card.get(
            "version",
            "BASE"
        ),
    )


def compare_cards(
    old_cards,
    new_cards
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

    # --------------------------------------------------------
    # OUT
    # --------------------------------------------------------

    for key, count in (
        old_counter - new_counter
    ).items():

        for _ in range(count):

            for card in old_cards:

                if card_key(card) == key:

                    out_cards.append(
                        card
                    )

                    break

    # --------------------------------------------------------
    # IN
    # --------------------------------------------------------

    for key, count in (
        new_counter - old_counter
    ).items():

        for _ in range(count):

            for card in new_cards:

                if card_key(card) == key:

                    in_cards.append(
                        card
                    )

                    break

    return (
        out_cards,
        in_cards
    )


def format_card(
    card
):

    name = card.get(
        "name",
        "Unknown"
    )

    overall = card.get(
        "overall",
        "?"
    )

    version = card.get(
        "version",
        "BASE"
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

    # --------------------------------------------------------
    # SCAN PAGES
    # --------------------------------------------------------

    for page_name, config in PAGES.items():

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
            # Download
            # ------------------------------------------------

            html = download_page(
                config["url"]
            )

            # ------------------------------------------------
            # Parse solution
            # ------------------------------------------------

            items = find_solution(
                html,
                page_name,
                config["expected"]
            )

            # ------------------------------------------------
            # Parse players
            # ------------------------------------------------

            players = parse_players(
                items,
                page_name
            )

            old_players = state.get(
                page_name,
                []
            )

            # ------------------------------------------------
            # FIRST RUN
            # ------------------------------------------------

            if not old_players:

                print(
                    f"🆕 First state saved "
                    f"for {page_name}."
                )

            # ------------------------------------------------
            # EXISTING STATE
            # ------------------------------------------------

            else:

                out_cards, in_cards = compare_cards(
                    old_players,
                    players
                )

                # ------------------------------------------------
                # CHANGES
                # ------------------------------------------------

                if (
                    out_cards
                    or in_cards
                ):

                    message = (
                        f"<b>{page_name}</b>\n\n"
                    )

                    # OUT
                    if out_cards:

                        message += (
                            "🔴 <b>OUT</b>\n"
                        )

                        for card in out_cards:

                            message += (
                                f"• "
                                f"{format_card(card)}\n"
                            )

                        message += "\n"

                    # IN
                    if in_cards:

                        message += (
                            "🟢 <b>IN</b>\n"
                        )

                        for card in in_cards:

                            message += (
                                f"• "
                                f"{format_card(card)}\n"
                            )

                        message += "\n"

                    message += (
                        f'<a href="{config["url"]}">'
                        f"Open {page_name}"
                        f"</a>"
                    )

                    telegram_send(
                        message
                    )

                    print(
                        "📨 Telegram notification sent."
                    )

                else:

                    print(
                        "No card changes."
                    )

            # ------------------------------------------------
            # SAVE ONLY AFTER SUCCESS
            # ------------------------------------------------

            state[page_name] = players

            successful_pages += 1

        except Exception as e:

            print(
                f"❌ ERROR {page_name}: {e}"
            )

            telegram_send(
                f"⚠️ <b>FUT.GG Monitor Error</b>\n\n"
                f"<b>{page_name}</b>\n"
                f"{str(e)}"
            )

            print(
                f"Previous state for "
                f"{page_name} was preserved."
            )

    # ========================================================
    # NOTHING WORKED
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
        f"{len(PAGES)} pages succeeded."
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