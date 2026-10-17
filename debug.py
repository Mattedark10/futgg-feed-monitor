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

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


# ============================================================
# HTTP
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
# RSC PARSER
# ============================================================

def extract_rsc_objects(source):
    """
    Extracts objects of the form:

        $R[240]={...}

    from FUT.GG's React Server Components HTML.

    The object can contain nested arrays / objects, so we
    cannot simply use a normal JSON parser.
    """

    objects = {}

    pattern = re.compile(r"\$R\[(\d+)\]=\{")

    for match in pattern.finditer(source):

        index = int(match.group(1))
        start = match.end() - 1

        depth = 0
        in_string = False
        escaped = False

        end = None

        for pos in range(start, len(source)):

            char = source[pos]

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
                continue

            if char == "{":
                depth += 1

            elif char == "}":

                depth -= 1

                if depth == 0:
                    end = pos + 1
                    break

        if end is None:
            continue

        raw = source[start:end]

        objects[index] = raw

    return objects


# ============================================================
# RSC OBJECT VALUE PARSER
# ============================================================

def split_top_level(text):
    """
    Splits:

        a:1,b:2,c:{...}

    without splitting commas inside nested objects/arrays.
    """

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
            continue

        if char in "[{":
            depth += 1

        elif char in "]}":
            depth -= 1

        elif char == "," and depth == 0:
            parts.append(text[start:i])
            start = i + 1

    parts.append(text[start:])

    return parts


def parse_simple_value(value):
    value = value.strip()

    # null
    if value == "null":
        return None

    # booleans
    if value == "true":
        return True

    if value == "false":
        return False

    # quoted string
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        try:
            return json.loads(value)
        except Exception:
            return value[1:-1]

    # number
    if re.fullmatch(r"-?\d+(?:\.\d+)?", value):

        if "." in value:
            return float(value)

        return int(value)

    # RSC reference
    match = re.fullmatch(r"\$R\[(\d+)\]", value)

    if match:
        return {
            "__ref__": int(match.group(1))
        }

    # array
    if value.startswith("[") and value.endswith("]"):

        inner = value[1:-1].strip()

        if not inner:
            return []

        result = []

        for part in split_top_level(inner):

            parsed = parse_simple_value(part)

            result.append(parsed)

        return result

    # object
    if value.startswith("{") and value.endswith("}"):

        return parse_object(value)

    return value


def parse_object(raw):
    """
    Parses FUT.GG RSC object syntax:

        {name:"Heroes",requiredCards:5,items:$R[241]}
    """

    raw = raw.strip()

    if raw.startswith("{") and raw.endswith("}"):
        raw = raw[1:-1]

    result = {}

    for part in split_top_level(raw):

        if ":" not in part:
            continue

        key, value = part.split(":", 1)

        key = key.strip()
        value = value.strip()

        result[key] = parse_simple_value(value)

    return result


# ============================================================
# RESOLVE RSC REFERENCES
# ============================================================

def resolve_value(value, objects, cache=None):

    if cache is None:
        cache = {}

    if isinstance(value, dict):

        if "__ref__" in value:

            ref = value["__ref__"]

            if ref in cache:
                return cache[ref]

            if ref not in objects:
                return None

            parsed = parse_object(objects[ref])

            cache[ref] = parsed

            resolved = resolve_value(parsed, objects, cache)

            cache[ref] = resolved

            return resolved

        return {
            key: resolve_value(val, objects, cache)
            for key, val in value.items()
        }

    if isinstance(value, list):

        return [
            resolve_value(item, objects, cache)
            for item in value
        ]

    return value


# ============================================================
# FIND DEFAULT SOLUTION
# ============================================================

def find_solution(source, page_name, expected):

    objects = extract_rsc_objects(source)

    print(f"Found {len(objects)} RSC objects.")

    # Find:
    #
    # solution:$R[240]={...}
    #
    pattern = re.compile(
        r"solution:\$R\[(\d+)\]=\{"
    )

    match = pattern.search(source)

    if not match:
        raise RuntimeError(
            f"No solution object found for {page_name}"
        )

    solution_index = int(match.group(1))

    if solution_index not in objects:
        raise RuntimeError(
            f"Solution reference {solution_index} not found "
            f"for {page_name}"
        )

    raw_solution = objects[solution_index]

    solution = parse_object(raw_solution)

    solution = resolve_value(solution, objects)

    if not isinstance(solution, dict):
        raise RuntimeError(
            f"Invalid solution object for {page_name}"
        )

    print(
        f"Solution: {solution.get('name')} | "
        f"requiredCards={solution.get('requiredCards')} | "
        f"status={solution.get('status')}"
    )

    if solution.get("requiredCards") != expected:

        raise RuntimeError(
            f"Wrong card count in {page_name}: "
            f"expected {expected}, "
            f"got {solution.get('requiredCards')}"
        )

    if solution.get("status") != "optimal":

        print(
            f"⚠️ Solution status is "
            f"{solution.get('status')}"
        )

    items = solution.get("items")

    if not isinstance(items, list):
        raise RuntimeError(
            f"No solution items found for {page_name}"
        )

    if len(items) != expected:

        raise RuntimeError(
            f"Wrong number of items for {page_name}: "
            f"expected {expected}, "
            f"got {len(items)}"
        )

    return solution


# ============================================================
# PLAYER INFO
# ============================================================

def get_card_link(item_id):
    return (
        f"https://www.fut.gg/players/"
        f"{item_id}/fc-27-{item_id}"
    )


def get_version(item_id):

    try:

        url = get_card_link(item_id)

        response = requests.get(
            url,
            headers=HEADERS,
            timeout=20,
        )

        if response.status_code != 200:
            return "BASE"

        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )

        h1 = soup.find("h1")

        if not h1:
            return "BASE"

        text = h1.get_text(
            " ",
            strip=True
        ).lower()

        if "pristine holographic" in text:
            return "PRISTINE HOLO"

        if "holographic" in text:
            return "HOLO"

        return "BASE"

    except Exception:
        return "BASE"


# ============================================================
# PLAYER NAME FROM IMAGE
# ============================================================

def get_player_name(item):

    player_ea_id = item.get("playerEaId")

    ea_id = item.get("eaId")

    overall = item.get("overall")

    if player_ea_id is None:
        return f"Player {ea_id}"

    # Try the FUT.GG player page.
    try:

        url = (
            f"https://www.fut.gg/players/"
            f"{player_ea_id}/fc-27"
        )

        response = requests.get(
            url,
            headers=HEADERS,
            timeout=20,
        )

        if response.status_code == 200:

            soup = BeautifulSoup(
                response.text,
                "html.parser"
            )

            h1 = soup.find("h1")

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
# PLAYER PARSER
# ============================================================

def parse_players(solution, page_name):

    items = solution["items"]

    players = []

    for index, item in enumerate(items):

        if not isinstance(item, dict):
            continue

        ea_id = item.get("eaId")
        player_ea_id = item.get("playerEaId")
        overall = item.get("overall")
        rarity_id = item.get("rarityEaId")

        if ea_id is None:
            continue

        name = get_player_name(item)

        # Holographics page = guaranteed holographic cards.
        if page_name == "Holographics":
            version = "HOLO"

        else:
            version = get_version(ea_id)

        player = {
            "ea_id": ea_id,
            "player_ea_id": player_ea_id,
            "name": name,
            "overall": overall,
            "rarity_id": rarity_id,
            "version": version,
            "url": get_card_link(ea_id),
        }

        players.append(player)

        print(
            f"- {name} "
            f"{overall or ''} "
            f"{version} "
            f"(eaId={ea_id})"
        )

    if len(players) != len(items):

        raise RuntimeError(
            f"Could not parse all cards for "
            f"{page_name}: "
            f"{len(players)}/{len(items)}"
        )

    return players


# ============================================================
# STATE
# ============================================================

def load_state():

    if not os.path.exists(STATE_FILE):
        return {}

    try:

        with open(
            STATE_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            return json.load(file)

    except Exception:

        return {}


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
# TRENDING DATA
# ============================================================

def save_trending(all_players):

    os.makedirs(
        os.path.dirname(TRENDING_FILE),
        exist_ok=True
    )

    data = {
        "updated_at": int(time.time()),
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

def telegram_send(message):

    if not TELEGRAM_BOT_TOKEN:
        print("⚠️ TELEGRAM_BOT_TOKEN missing")
        return

    if not TELEGRAM_CHAT_ID:
        print("⚠️ TELEGRAM_CHAT_ID missing")
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
            timeout=20,
        )

        response.raise_for_status()

    except Exception as error:

        print(
            f"⚠️ Telegram error: {error}"
        )


# ============================================================
# CARD KEY
# ============================================================

def card_key(player):

    """
    We compare actual card occurrences.

    The same EA card appearing twice remains two occurrences.
    """

    return (
        player.get("ea_id"),
        player.get("version", "BASE"),
    )


# ============================================================
# DIFFERENCE
# ============================================================

def compare_players(old_players, new_players):

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
        set(old_counter.keys())
        |
        set(new_counter.keys())
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

        if new_count > old_count:

            difference = new_count - old_count

            for player in new_lookup[key][:difference]:
                added.append(player)

        elif old_count > new_count:

            difference = old_count - new_count

            for player in old_lookup[key][:difference]:
                removed.append(player)

    return removed, added


# ============================================================
# TELEGRAM CARD FORMAT
# ============================================================

def format_card(player):

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

    if overall:
        title = (
            f"{name} {overall} "
            f"({label})"
        )
    else:
        title = (
            f"{name} "
            f"({label})"
        )

    if url:
        return f'<a href="{url}">{title}</a>'

    return title


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

    config = PAGES[page_name]

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
                f"🔴 {format_card(player)}"
            )

        lines.append("")

    if added:

        lines.append(
            "<b>🟢 IN</b>"
        )

        for player in added:

            lines.append(
                f"🟢 {format_card(player)}"
            )

        lines.append("")

    lines.append(
        f'<a href="{config["url"]}">'
        f"Open FUT.GG"
        f"</a>"
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

    config = PAGES[page_name]

    message = (
        f"{config['emoji']} "
        f"<b>FUT.GG ERROR</b>\n\n"
        f"<b>{page_name}</b>\n"
        f"<code>{str(error)[:1000]}</code>\n\n"
        f'<a href="{config["url"]}">'
        f"Open FUT.GG"
        f"</a>"
    )

    telegram_send(message)


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
        f"Scanning {config['emoji']} "
        f"{page_name}"
    )
    print(config["url"])
    print("=" * 60)

    source = get_page(
        config["url"]
    )

    print(
        f"Downloaded {len(source):,} characters."
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

    old_players = previous_state.get(
        page_name,
        []
    )

    # First run:
    if not old_players:

        print(
            f"First run for {page_name}: "
            f"saving state silently."
        )

        return players, False

    removed, added = compare_players(
        old_players,
        players
    )

    print(
        f"Changes: "
        f"{len(removed)} OUT / "
        f"{len(added)} IN"
    )

    if removed or added:

        send_changes(
            page_name,
            removed,
            added
        )

        return players, True

    return players, False


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print("=" * 60)
    print("FUT.GG MONITOR")
    print("=" * 60)

    state = load_state()

    new_state = dict(state)

    any_success = False

    all_players = {}

    for page_name, config in PAGES.items():

        try:

            players, changed = process_page(
                page_name,
                config,
                state
            )

            # Only replace state after successful
            # complete parsing.
            new_state[page_name] = players

            all_players[page_name] = players

            any_success = True

        except Exception as error:

            print()
            print(
                f"❌ ERROR {page_name}: "
                f"{error}"
            )

            # IMPORTANT:
            # Keep old state untouched.
            if page_name in state:

                new_state[page_name] = (
                    state[page_name]
                )

                all_players[page_name] = (
                    state[page_name]
                )

            send_error(
                page_name,
                error
            )

    # Save state only for pages that succeeded.
    if any_success:

        save_state(
            new_state
        )

        save_trending(
            all_players
        )

    print()
    print("=" * 60)
    print("MONITOR FINISHED")
    print("=" * 60)


if __name__ == "__main__":
    main()