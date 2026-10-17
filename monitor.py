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
        "emoji": "🦸",
    },

    "Holographics": {
        "url": "https://www.fut.gg/fut-gallery/rarities/holographics/",
        "expected": 5,
        "emoji": "🌈",
    },

    "Season 1": {
        "url": "https://www.fut.gg/fut-gallery/rarities/season-1/",
        "expected": 10,
        "emoji": "🏆",
    },
}


STATE_FILE = "players.json"
TRENDING_FILE = "docs/trending.json"

TELEGRAM_BOT_TOKEN = os.environ.get(
    "TELEGRAM_BOT_TOKEN"
)

TELEGRAM_CHAT_ID = os.environ.get(
    "TELEGRAM_CHAT_ID"
)


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


# ============================================================
# DOWNLOAD PAGE
# ============================================================

def get_page(url):

    response = requests.get(
        url,
        headers=HEADERS,
        timeout=40,
    )

    response.raise_for_status()

    return response.text


# ============================================================
# GENERIC RSC VALUE PARSER
# ============================================================

def split_top_level(text):

    parts = []

    start = 0
    depth = 0

    in_string = False
    escaped = False

    for i, char in enumerate(text):

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

        elif char in "[{":
            depth += 1

        elif char in "]}":
            depth -= 1

        elif char == "," and depth == 0:

            parts.append(
                text[start:i]
            )

            start = i + 1

    parts.append(
        text[start:]
    )

    return parts


def parse_value(value):

    value = value.strip()

    # --------------------------------------------------------
    # NULL
    # --------------------------------------------------------

    if value == "null":
        return None

    # --------------------------------------------------------
    # BOOLEAN
    # --------------------------------------------------------

    if value == "true":
        return True

    if value == "false":
        return False

    # --------------------------------------------------------
    # STRING
    # --------------------------------------------------------

    if (
        len(value) >= 2
        and value[0] == '"'
        and value[-1] == '"'
    ):

        try:
            return json.loads(value)

        except Exception:
            return value[1:-1]

    # --------------------------------------------------------
    # NUMBER
    # --------------------------------------------------------

    if re.fullmatch(
        r"-?\d+(?:\.\d+)?",
        value
    ):

        if "." in value:
            return float(value)

        return int(value)

    # --------------------------------------------------------
    # RSC REFERENCE
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
    # ARRAY
    # --------------------------------------------------------

    if (
        value.startswith("[")
        and value.endswith("]")
    ):

        inner = value[1:-1].strip()

        if not inner:
            return []

        result = []

        for part in split_top_level(inner):

            result.append(
                parse_value(part)
            )

        return result

    # --------------------------------------------------------
    # OBJECT
    # --------------------------------------------------------

    if (
        value.startswith("{")
        and value.endswith("}")
    ):

        return parse_object(value)

    return value


def parse_object(raw):

    raw = raw.strip()

    if (
        raw.startswith("{")
        and raw.endswith("}")
    ):

        raw = raw[1:-1]

    result = {}

    for part in split_top_level(raw):

        if ":" not in part:
            continue

        key, value = part.split(
            ":",
            1
        )

        key = key.strip()
        value = value.strip()

        result[key] = parse_value(value)

    return result


# ============================================================
# EXTRACT ALL $R ASSIGNMENTS
# ============================================================

def extract_rsc_assignments(source):

    """
    FUT.GG uses structures such as:

        $R[240]={...}

    and

        $R[241]=[$R[242]={...},$R[243]={...}]

    We need BOTH.

    This function finds the assignment and captures
    the complete value after '='.
    """

    assignments = {}

    pattern = re.compile(
        r"\$R\[(\d+)\]="
    )

    matches = list(
        pattern.finditer(source)
    )

    for index, match in enumerate(matches):

        ref_id = int(
            match.group(1)
        )

        value_start = match.end()

        # End is normally the next $R assignment.
        if index + 1 < len(matches):

            value_end = matches[
                index + 1
            ].start()

        else:

            value_end = len(source)

        raw_value = source[
            value_start:value_end
        ]

        # Remove separators / trailing data
        raw_value = raw_value.strip()

        # ----------------------------------------------------
        # Find the actual value boundary.
        # ----------------------------------------------------

        if raw_value.startswith("{"):

            depth = 0
            in_string = False
            escaped = False
            end = None

            for pos, char in enumerate(
                raw_value
            ):

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

                        end = pos + 1
                        break

            if end:
                raw_value = raw_value[:end]

        elif raw_value.startswith("["):

            depth = 0
            in_string = False
            escaped = False
            end = None

            for pos, char in enumerate(
                raw_value
            ):

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

                        end = pos + 1
                        break

            if end:
                raw_value = raw_value[:end]

        else:

            # Primitive/reference
            raw_value = raw_value.split(
                ",",
                1
            )[0].strip()

        assignments[
            ref_id
        ] = raw_value

    return assignments


# ============================================================
# RESOLVE RSC REFERENCES
# ============================================================

def resolve_reference(
    ref_id,
    assignments,
    cache=None
):

    if cache is None:
        cache = {}

    if ref_id in cache:
        return cache[ref_id]

    if ref_id not in assignments:
        return None

    raw = assignments[
        ref_id
    ]

    value = parse_value(
        raw
    )

    resolved = resolve_value(
        value,
        assignments,
        cache
    )

    cache[ref_id] = resolved

    return resolved


def resolve_value(
    value,
    assignments,
    cache=None
):

    if cache is None:
        cache = {}

    # --------------------------------------------------------
    # REFERENCE
    # --------------------------------------------------------

    if isinstance(value, dict):

        if "__ref__" in value:

            ref_id = value[
                "__ref__"
            ]

            return resolve_reference(
                ref_id,
                assignments,
                cache
            )

        return {
            key: resolve_value(
                val,
                assignments,
                cache
            )
            for key, val in value.items()
        }

    # --------------------------------------------------------
    # ARRAY
    # --------------------------------------------------------

    if isinstance(value, list):

        return [
            resolve_value(
                item,
                assignments,
                cache
            )
            for item in value
        ]

    return value


# ============================================================
# FIND SOLUTION
# ============================================================

def find_solution(
    source,
    page_name,
    expected
):

    assignments = extract_rsc_assignments(
        source
    )

    print(
        f"Found {len(assignments)} RSC objects."
    )

    # FUT.GG currently exposes:
    #
    # solution:$R[240]={...}

    solution_match = re.search(
        r"solution:\$R\[(\d+)\]=",
        source
    )

    if not solution_match:

        raise RuntimeError(
            f"No solution found for {page_name}"
        )

    solution_ref = int(
        solution_match.group(1)
    )

    solution = resolve_reference(
        solution_ref,
        assignments
    )

    if not isinstance(
        solution,
        dict
    ):

        raise RuntimeError(
            f"Invalid solution for {page_name}"
        )

    print(
        f"Solution: "
        f"{solution.get('name')} | "
        f"requiredCards="
        f"{solution.get('requiredCards')} | "
        f"status="
        f"{solution.get('status')}"
    )

    # --------------------------------------------------------
    # VERIFY CARD COUNT
    # --------------------------------------------------------

    required_cards = solution.get(
        "requiredCards"
    )

    if required_cards != expected:

        raise RuntimeError(
            f"Wrong requiredCards for "
            f"{page_name}: "
            f"expected {expected}, "
            f"got {required_cards}"
        )

    # --------------------------------------------------------
    # GET ITEMS
    # --------------------------------------------------------

    items = solution.get(
        "items"
    )

    if not isinstance(
        items,
        list
    ):

        raise RuntimeError(
            f"Could not resolve solution "
            f"items for {page_name}"
        )

    # --------------------------------------------------------
    # REMOVE NONE
    # --------------------------------------------------------

    items = [
        item
        for item in items
        if isinstance(
            item,
            dict
        )
    ]

    print(
        f"Solution contains "
        f"{len(items)}/{expected} cards."
    )

    if len(items) != expected:

        raise RuntimeError(
            f"Wrong solution item count "
            f"for {page_name}: "
            f"expected {expected}, "
            f"got {len(items)}"
        )

    return solution


# ============================================================
# CARD LINK
# ============================================================

def get_card_link(ea_id):

    return (
        "https://www.fut.gg/players/"
        f"{ea_id}/fc-27-{ea_id}"
    )


# ============================================================
# GET CARD VERSION
# ============================================================

def get_version(ea_id):

    try:

        url = get_card_link(
            ea_id
        )

        response = requests.get(
            url,
            headers=HEADERS,
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

        if not h1:
            return "BASE"

        text = h1.get_text(
            " ",
            strip=True
        ).lower()

        if (
            "pristine holographic"
            in text
        ):

            return "PRISTINE HOLO"

        if "holographic" in text:

            return "HOLO"

        return "BASE"

    except Exception:

        return "BASE"


# ============================================================
# GET PLAYER NAME
# ============================================================

def get_player_name(
    player_ea_id
):

    if not player_ea_id:
        return "Unknown Player"

    try:

        url = (
            "https://www.fut.gg/players/"
            f"{player_ea_id}/fc-27"
        )

        response = requests.get(
            url,
            headers=HEADERS,
            timeout=20
        )

        if response.status_code != 200:
            return f"Player {player_ea_id}"

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

    return f"Player {player_ea_id}"


# ============================================================
# PARSE PLAYERS
# ============================================================

def parse_players(
    solution,
    page_name
):

    items = solution[
        "items"
    ]

    players = []

    print()

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

        if ea_id is None:

            raise RuntimeError(
                f"Card without eaId "
                f"in {page_name}"
            )

        name = get_player_name(
            player_ea_id
        )

        # Holographics page consists
        # of holographic cards.
        if page_name == "Holographics":

            version = "HOLO"

        else:

            version = get_version(
                ea_id
            )

        player = {
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
            player
        )

        print(
            f"- {name} "
            f"{overall} "
            f"{version} "
            f"(eaId={ea_id})"
        )

    return players


# ============================================================
# LOAD STATE
# ============================================================

def load_state():

    if not os.path.exists(
        STATE_FILE
    ):

        return {}

    try:

        with open(
            STATE_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            return json.load(
                file
            )

    except Exception as error:

        print(
            f"⚠️ Could not read "
            f"{STATE_FILE}: {error}"
        )

        return {}


# ============================================================
# SAVE STATE
# ============================================================

def save_state(state):

    with open(
        STATE_FILE,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            state,
            file,
            ensure_ascii=False,
            indent=2
        )


# ============================================================
# SAVE TRENDING
# ============================================================

def save_trending(
    all_players
):

    folder = os.path.dirname(
        TRENDING_FILE
    )

    if folder:
        os.makedirs(
            folder,
            exist_ok=True
        )

    data = {
        "updated_at": int(
            time.time()
        ),
        "pages": all_players,
    }

    with open(
        TRENDING_FILE,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=2
        )


# ============================================================
# TELEGRAM
# ============================================================

def telegram_send(
    message
):

    if not TELEGRAM_BOT_TOKEN:

        print(
            "⚠️ TELEGRAM_BOT_TOKEN missing"
        )

        return

    if not TELEGRAM_CHAT_ID:

        print(
            "⚠️ TELEGRAM_CHAT_ID missing"
        )

        return

    url = (
        "https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    try:

        response = requests.post(
            url,
            data=payload,
            timeout=20
        )

        response.raise_for_status()

    except Exception as error:

        print(
            f"⚠️ Telegram error: "
            f"{error}"
        )


# ============================================================
# CARD KEY
# ============================================================

def card_key(
    player
):

    return (
        player.get("ea_id"),
        player.get(
            "version",
            "BASE"
        )
    )


# ============================================================
# COMPARE
# ============================================================

def compare_players(
    old_players,
    new_players
):

    old_counter = Counter(
        card_key(player)
        for player in old_players
    )

    new_counter = Counter(
        card_key(player)
        for player in new_players
    )

    old_lookup = {}

    for player in old_players:

        old_lookup.setdefault(
            card_key(player),
            []
        ).append(player)

    new_lookup = {}

    for player in new_players:

        new_lookup.setdefault(
            card_key(player),
            []
        ).append(player)

    removed = []
    added = []

    all_keys = (
        set(old_counter)
        |
        set(new_counter)
    )

    for key in all_keys:

        old_count = old_counter.get(
            key,
            0
        )

        new_count = new_counter.get(
            key,
            0
        )

        # IN
        if new_count > old_count:

            amount = (
                new_count
                -
                old_count
            )

            added.extend(
                new_lookup[key][
                    :amount
                ]
            )

        # OUT
        elif old_count > new_count:

            amount = (
                old_count
                -
                new_count
            )

            removed.extend(
                old_lookup[key][
                    :amount
                ]
            )

    return removed, added


# ============================================================
# FORMAT TELEGRAM CARD
# ============================================================

def format_card(
    player
):

    name = player.get(
        "name",
        "Unknown"
    )

    overall = player.get(
        "overall"
    )

    version = player.get(
        "version",
        "BASE"
    )

    url = player.get(
        "url"
    )

    if version == "HOLO":

        label = "HOLO"

    elif version == "PRISTINE HOLO":

        label = "PRISTINE HOLO"

    else:

        label = "BASE"

    text = (
        f"{name} "
        f"{overall} "
        f"({label})"
    )

    if url:

        return (
            f'<a href="{url}">'
            f"{text}"
            f"</a>"
        )

    return text


# ============================================================
# SEND CHANGES
# ============================================================

def send_changes(
    page_name,
    removed,
    added
):

    if not removed and not added:
        return

    config = PAGES[
        page_name
    ]

    lines = [
        f"{config['emoji']} "
        f"<b>{page_name}</b>",
        "",
    ]

    if removed:

        lines.append(
            "<b>🔴 OUT</b>"
        )

        for player in removed:

            lines.append(
                "🔴 "
                + format_card(
                    player
                )
            )

        lines.append("")

    if added:

        lines.append(
            "<b>🟢 IN</b>"
        )

        for player in added:

            lines.append(
                "🟢 "
                + format_card(
                    player
                )
            )

        lines.append("")

    lines.append(
        f'<a href="{config["url"]}">'
        "Open FUT.GG"
        "</a>"
    )

    telegram_send(
        "\n".join(lines)
    )


# ============================================================
# SEND ERROR
# ============================================================

def send_error(
    page_name,
    error
):

    config = PAGES[
        page_name
    ]

    message = (
        f"{config['emoji']} "
        f"<b>FUT.GG ERROR</b>\n\n"
        f"<b>{page_name}</b>\n"
        f"<code>"
        f"{str(error)[:1000]}"
        f"</code>\n\n"
        f'<a href="{config["url"]}">'
        "Open FUT.GG"
        "</a>"
    )

    telegram_send(
        message
    )


# ============================================================
# PROCESS PAGE
# ============================================================

def process_page(
    page_name,
    config,
    previous_state
):

    print()
    print("=" * 60)

    print(
        f"Scanning "
        f"{config['emoji']} "
        f"{page_name}"
    )

    print(
        config["url"]
    )

    print("=" * 60)

    source = get_page(
        config["url"]
    )

    print(
        f"Downloaded "
        f"{len(source):,} characters."
    )

    solution = find_solution(
        source,
        page_name,
        config["expected"]
    )

    players = parse_players(
        solution,
        page_name
    )

    if len(players) != config["expected"]:

        raise RuntimeError(
            f"Expected "
            f"{config['expected']} "
            f"players, got "
            f"{len(players)}"
        )

    old_players = previous_state.get(
        page_name,
        []
    )

    # --------------------------------------------------------
    # FIRST RUN
    # --------------------------------------------------------

    if not old_players:

        print(
            f"First run for "
            f"{page_name}: "
            f"saving state silently."
        )

        return players

    # --------------------------------------------------------
    # COMPARE
    # --------------------------------------------------------

    removed, added = compare_players(
        old_players,
        players
    )

    print(
        f"Changes: "
        f"{len(removed)} OUT / "
        f"{len(added)} IN"
    )

    if removed:

        print(
            "OUT:"
        )

        for player in removed:

            print(
                f"  - "
                f"{player['name']} "
                f"{player['overall']}"
            )

    if added:

        print(
            "IN:"
        )

        for player in added:

            print(
                f"  + "
                f"{player['name']} "
                f"{player['overall']}"
            )

    if removed or added:

        send_changes(
            page_name,
            removed,
            added
        )

    return players


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print("=" * 60)
    print("FUT.GG MONITOR")
    print("=" * 60)

    state = load_state()

    new_state = dict(
        state
    )

    all_players = {}

    success_count = 0

    for page_name, config in PAGES.items():

        try:

            players = process_page(
                page_name,
                config,
                state
            )

            # Only overwrite this page after
            # successful parsing.
            new_state[
                page_name
            ] = players

            all_players[
                page_name
            ] = players

            success_count += 1

        except Exception as error:

            print()
            print(
                f"❌ ERROR "
                f"{page_name}: "
                f"{error}"
            )

            # Keep previous valid state.
            if page_name in state:

                new_state[
                    page_name
                ] = state[
                    page_name
                ]

                all_players[
                    page_name
                ] = state[
                    page_name
                ]

            send_error(
                page_name,
                error
            )

    # --------------------------------------------------------
    # SAVE
    # --------------------------------------------------------

    if success_count > 0:

        save_state(
            new_state
        )

        save_trending(
            all_players
        )

        print()
        print(
            "✅ State saved."
        )

        print(
            f"✅ Successful pages: "
            f"{success_count}/"
            f"{len(PAGES)}"
        )

    else:

        print()
        print(
            "❌ No pages succeeded."
        )

    print()
    print("=" * 60)
    print("MONITOR FINISHED")
    print("=" * 60)


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    main()