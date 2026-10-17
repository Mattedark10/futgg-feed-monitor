import os
import re
import json
import requests
from bs4 import BeautifulSoup
from collections import Counter
from html import escape

# ============================================================
# CONFIG
# ============================================================

PAGES = {
    "🦸 HEROES": {
        "url": "https://www.fut.gg/fut-gallery/rarities/heroes/",
        "players": 5,
        "page_type": "heroes",
    },
    "🌈 HOLOGRAPHICS": {
        "url": "https://www.fut.gg/fut-gallery/rarities/holographics/",
        "players": 5,
        "page_type": "holographics",
    },
    "🏆 SEASON 1": {
        "url": "https://www.fut.gg/fut-gallery/rarities/season-1/",
        "players": 10,
        "page_type": "season_1",
    },
}

STATE_FILE = "players.json"
APP_FILE = "docs/trending.json"

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

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
    r = requests.get(
        url,
        headers=HEADERS,
        timeout=30,
    )
    r.raise_for_status()
    return r.text


# ============================================================
# REACT / RSC PARSER
# ============================================================

def extract_balanced_object(text, start):
    if start >= len(text) or text[start] != "{":
        return None

    depth = 0
    in_string = False
    escape_next = False

    for i in range(start, len(text)):
        c = text[i]

        if in_string:
            if escape_next:
                escape_next = False
            elif c == "\\":
                escape_next = True
            elif c == '"':
                in_string = False
            continue

        if c == '"':
            in_string = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1

            if depth == 0:
                return text[start:i + 1]

    return None


def extract_balanced_array(text, start):
    if start >= len(text) or text[start] != "[":
        return None

    depth = 0
    in_string = False
    escape_next = False

    for i in range(start, len(text)):
        c = text[i]

        if in_string:
            if escape_next:
                escape_next = False
            elif c == "\\":
                escape_next = True
            elif c == '"':
                in_string = False
            continue

        if c == '"':
            in_string = True
        elif c == "[":
            depth += 1
        elif c == "]":
            depth -= 1

            if depth == 0:
                return text[start:i + 1]

    return None


def parse_simple_value(value):
    value = value.strip()

    if value == "null":
        return None

    if value == "true":
        return True

    if value == "false":
        return False

    if value.startswith('"') and value.endswith('"'):
        try:
            return json.loads(value)
        except Exception:
            return value[1:-1]

    if re.fullmatch(r"-?\d+(?:\.\d+)?", value):
        try:
            return int(value)
        except Exception:
            try:
                return float(value)
            except Exception:
                pass

    return value


def build_rsc_objects(source):
    """
    Builds the $R[index] object map used by FUT.GG's
    React Server Components payload.
    """

    objects = {}

    pattern = re.compile(
        r"\$R\[(\d+)\]\s*=\s*(\{|\[)"
    )

    for match in pattern.finditer(source):
        index = int(match.group(1))
        opening = match.group(2)
        start = match.start(2)

        if opening == "{":
            raw = extract_balanced_object(source, start)
        else:
            raw = extract_balanced_array(source, start)

        if raw:
            objects[index] = raw

    return objects


def parse_object_fields(raw):
    """
    Lightweight parser for fields such as:

    eaId:67276289
    playerEaId:167425
    overall:89
    price:null
    """

    result = {}

    if not raw or not raw.startswith("{"):
        return result

    body = raw[1:-1]

    pattern = re.compile(
        r'([A-Za-z_][A-Za-z0-9_]*)\s*:\s*'
        r'(".*?"|null|true|false|-?\d+(?:\.\d+)?)'
    )

    for match in pattern.finditer(body):
        key = match.group(1)
        value = match.group(2)

        result[key] = parse_simple_value(value)

    return result


def resolve_reference(value, objects):
    """
    Resolves values like:

    $R[241]

    into their actual object.
    """

    if not isinstance(value, str):
        return value

    match = re.fullmatch(r"\$R\[(\d+)\]", value.strip())

    if not match:
        return value

    index = int(match.group(1))

    raw = objects.get(index)

    if raw is None:
        return value

    return parse_object_fields(raw)


# ============================================================
# SOLUTIONS
# ============================================================

def find_solutions(source, page_name, objects):
    """
    Finds every solution belonging to the requested page.

    We DO NOT use a hardcoded grade.

    FUT.GG already calculates the best lineup and exposes
    the solutions in the page data.
    """

    solutions = []

    pattern = re.compile(
        r'solution:\$R\[(\d+)\]\s*=\s*\{'
    )

    for match in pattern.finditer(source):

        ref_id = int(match.group(1))

        raw = objects.get(ref_id)

        if not raw:
            start = source.find("{", match.start())
            raw = extract_balanced_object(source, start)

        if not raw:
            continue

        solution = parse_object_fields(raw)

        if solution.get("name") != page_name:
            continue

        solution["_ref_id"] = ref_id

        solutions.append(solution)

    return solutions


def extract_solution_items(solution, source, objects):
    """
    Extracts the item references from:

    items:$R[241]=[
        $R[242],
        $R[243],
        ...
    ]

    and resolves them.
    """

    ref_id = solution.get("_ref_id")

    if ref_id is None:
        return []

    raw_solution = objects.get(ref_id)

    if not raw_solution:
        return []

    items_match = re.search(
        r'items:\$R\[(\d+)\]\s*=\s*\[',
        raw_solution
    )

    if not items_match:
        return []

    items_ref = int(items_match.group(1))

    raw_array = objects.get(items_ref)

    if not raw_array:
        return []

    refs = re.findall(
        r"\$R\[(\d+)\]",
        raw_array
    )

    items = []

    for ref in refs:
        ref_num = int(ref)
        raw_item = objects.get(ref_num)

        if not raw_item:
            continue

        item = parse_object_fields(raw_item)

        if item:
            items.append(item)

    return items


def get_default_solution(source, page_name, expected_players, objects):
    """
    FUT.GG opens the best lineup by default.

    We therefore DON'T specify A/S/etc.

    Among the solutions found in the page data we select
    the strongest one using the score information supplied
    by FUT.GG.
    """

    solutions = find_solutions(
        source,
        page_name,
        objects
    )

    if not solutions:
        raise RuntimeError(
            f"No solutions found for {page_name}"
        )

    candidates = []

    for solution in solutions:

        items = extract_solution_items(
            solution,
            source,
            objects
        )

        solution["_items"] = items

        if len(items) == expected_players:
            candidates.append(solution)

    if not candidates:
        counts = [
            len(s.get("_items", []))
            for s in solutions
        ]

        raise RuntimeError(
            f"Wrong lineup size for {page_name}. "
            f"Expected {expected_players}, found {counts}"
        )

    # --------------------------------------------------------
    # Pick the strongest lineup WITHOUT hardcoding a grade.
    #
    # FUT.GG supplies totalScore/baseGrade.
    # --------------------------------------------------------

    def solution_score(solution):
        total = solution.get("totalScore")

        if isinstance(total, (int, float)):
            return total

        base = solution.get("baseGrade")

        if isinstance(base, (int, float)):
            return base

        return 0

    candidates.sort(
        key=solution_score,
        reverse=True
    )

    best = candidates[0]

    return best


# ============================================================
# PLAYER / CARD DATA
# ============================================================

def build_image_map(source):
    """
    Maps numeric IDs appearing in image URLs to their alt text.
    """

    soup = BeautifulSoup(source, "html.parser")

    image_map = {}

    for img in soup.find_all("img"):

        alt = img.get("alt")
        src = img.get("src") or ""

        if not alt:
            continue

        numbers = re.findall(r"\d{4,}", src)

        for number in numbers:
            image_map[number] = alt

    return image_map


def find_name_in_source(source, item):
    """
    Tries to find the player name from image alt text or
    surrounding FUT.GG data.
    """

    soup = BeautifulSoup(source, "html.parser")

    ea_id = str(item.get("eaId", ""))
    player_ea_id = str(item.get("playerEaId", ""))

    # --------------------------------------------------------
    # 1. Search images
    # --------------------------------------------------------

    for img in soup.find_all("img"):

        alt = img.get("alt")
        src = img.get("src") or ""

        if not alt:
            continue

        if ea_id and ea_id in src:
            return alt

        if player_ea_id and player_ea_id in src:
            return alt

    # --------------------------------------------------------
    # 2. Search links
    # --------------------------------------------------------

    for a in soup.find_all("a"):

        href = a.get("href") or ""
        text = a.get_text(" ", strip=True)

        if not text:
            continue

        if ea_id and ea_id in href:
            return text

    # --------------------------------------------------------
    # 3. Search nearby text around IDs
    # --------------------------------------------------------

    for identifier in [ea_id, player_ea_id]:

        if not identifier:
            continue

        pos = source.find(identifier)

        if pos == -1:
            continue

        chunk = source[
            max(0, pos - 1000):
            min(len(source), pos + 1000)
        ]

        # Common quoted strings
        strings = re.findall(
            r'"([^"]{2,80})"',
            chunk
        )

        for value in strings:

            if (
                not value.startswith("http")
                and not value.startswith("/")
                and not value.startswith("$")
                and not value.isdigit()
            ):
                # Avoid obvious technical values
                if not any(
                    x in value.lower()
                    for x in [
                        "player",
                        "image",
                        "rarity",
                        "club",
                        "nation",
                        "position",
                        "price",
                        "https"
                    ]
                ):
                    return value

    return None


def find_card_link(source, item_id):
    """
    Attempts to find the FUT.GG player page associated
    with the EA card ID.
    """

    soup = BeautifulSoup(source, "html.parser")

    item_id = str(item_id)

    for a in soup.find_all("a", href=True):

        href = a["href"]

        if item_id in href and "/players/" in href:
            if href.startswith("http"):
                return href

            return "https://www.fut.gg" + href

    return None


def get_version(card_url):
    """
    Gets card version from the individual FUT.GG player page.
    """

    if not card_url:
        return "?"

    try:
        r = requests.get(
            card_url,
            headers=HEADERS,
            timeout=20
        )

        if r.status_code != 200:
            return "?"

        soup = BeautifulSoup(
            r.text,
            "html.parser"
        )

        h1 = soup.find("h1")

        if h1:
            title = h1.get_text(
                " ",
                strip=True
            ).lower()

            if "pristine holographic" in title:
                return "Pristine Holographic"

            if "holographic" in title:
                return "Holographic"

            if "base" in title:
                return "Base"

        return "?"

    except Exception:
        return "?"


def parse_player(item, source, image_map, page_type):
    ea_id = item.get("eaId")
    player_ea_id = item.get("playerEaId")

    overall = item.get("overall")

    # --------------------------------------------------------
    # NAME
    # --------------------------------------------------------

    name = find_name_in_source(
        source,
        item
    )

    if not name:
        name = f"Player {player_ea_id or ea_id}"

    # --------------------------------------------------------
    # CARD LINK
    # --------------------------------------------------------

    card_link = find_card_link(
        source,
        ea_id
    )

    # --------------------------------------------------------
    # VERSION
    # --------------------------------------------------------

    if page_type == "holographics":
        version = "Holographic"
    else:
        version = get_version(card_link)

    # --------------------------------------------------------
    # IMAGE
    # --------------------------------------------------------

    image = None

    if ea_id:
        image = image_map.get(
            str(ea_id)
        )

    # --------------------------------------------------------
    # PRICE
    # --------------------------------------------------------

    price = item.get("price")

    # --------------------------------------------------------
    # RARITY
    # --------------------------------------------------------

    rarity_id = item.get(
        "rarityEaId"
    )

    return {
        "name": name,
        "item_id": ea_id,
        "player_ea_id": player_ea_id,
        "overall": overall,
        "rarity_id": rarity_id,
        "price": price,
        "version": version,
        "link": card_link,
        "image": image,
    }


# ============================================================
# GET PLAYERS
# ============================================================

def get_players(page_name, config):
    print()
    print("=" * 60)
    print(f"Scanning {page_name}")
    print(config["url"])
    print("=" * 60)

    source = get_page(
        config["url"]
    )

    objects = build_rsc_objects(
        source
    )

    image_map = build_image_map(
        source
    )

    solution = get_default_solution(
        source,
        page_name.replace(
            "🦸 ",
            ""
        ).replace(
            "🌈 ",
            ""
        ).replace(
            "🏆 ",
            ""
        ),
        config["players"],
        objects
    )

    # --------------------------------------------------------
    # Better page names
    # --------------------------------------------------------

    page_names = {
        "heroes": "Heroes",
        "holographics": "Holographics",
        "season_1": "Season 1",
    }

    # Re-run using exact page name if necessary
    if solution is None:
        solution = get_default_solution(
            source,
            page_names[config["page_type"]],
            config["players"],
            objects
        )

    items = solution["_items"]

    if len(items) != config["players"]:
        raise RuntimeError(
            f"{page_name}: expected "
            f"{config['players']} players, "
            f"found {len(items)}"
        )

    print(
        f"Selected default/best lineup: "
        f"{len(items)}/{config['players']} cards"
    )

    grade = solution.get("grade")

    if grade:
        print(
            f"FUT.GG grade detected: {grade}"
        )

    players = []

    for item in items:

        player = parse_player(
            item,
            source,
            image_map,
            config["page_type"]
        )

        players.append(player)

        print(
            f"- {player['name']} "
            f"{player['overall']} "
            f"{player['version']}"
        )

    return players


# ============================================================
# STATE
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
        ) as f:
            return json.load(f)

    except Exception:
        return {}


def save_state(state):
    with open(
        STATE_FILE,
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            state,
            f,
            ensure_ascii=False,
            indent=2
        )


# ============================================================
# COMPARISON
# ============================================================

def player_key(player):
    """
    The card itself identifies the occurrence.

    Version is included so that:
    Base -> Holographic
    is considered a change.
    """

    return (
        str(player.get("item_id")),
        player.get("version", "?")
    )


def compare_players(old_players, new_players):

    old_counter = Counter(
        player_key(p)
        for p in old_players
    )

    new_counter = Counter(
        player_key(p)
        for p in new_players
    )

    outgoing = []
    incoming = []

    # --------------------------------------------------------
    # OUT
    # --------------------------------------------------------

    for key, count in (
        old_counter - new_counter
    ).items():

        for _ in range(count):

            player = next(
                (
                    p for p in old_players
                    if player_key(p) == key
                ),
                None
            )

            if player:
                outgoing.append(player)

    # --------------------------------------------------------
    # IN
    # --------------------------------------------------------

    for key, count in (
        new_counter - old_counter
    ).items():

        for _ in range(count):

            player = next(
                (
                    p for p in new_players
                    if player_key(p) == key
                ),
                None
            )

            if player:
                incoming.append(player)

    return outgoing, incoming


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):

    if not BOT_TOKEN or not CHAT_ID:
        print(
            "Telegram not configured."
        )
        return

    url = (
        f"https://api.telegram.org/bot"
        f"{BOT_TOKEN}/sendMessage"
    )

    data = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    try:
        r = requests.post(
            url,
            data=data,
            timeout=20
        )

        r.raise_for_status()

    except Exception as e:
        print(
            f"Telegram error: {e}"
        )


def player_text(player):

    name = escape(
        str(player.get("name", "?"))
    )

    overall = player.get(
        "overall",
        "?"
    )

    version = player.get(
        "version",
        "?"
    )

    if version == "Base":
        version_text = "BASE"
    elif version == "Holographic":
        version_text = "HOLO"
    elif version == "Pristine Holographic":
        version_text = "PRISTINE HOLO"
    else:
        version_text = version.upper()

    return (
        f"<b>{name}</b> "
        f"{overall} "
        f"<i>{version_text}</i>"
    )


def build_change_message(
    page_name,
    outgoing,
    incoming,
    page_url
):

    lines = [
        f"<b>{escape(page_name)}</b>",
        ""
    ]

    for player in outgoing:
        lines.append(
            f"🔴 OUT — {player_text(player)}"
        )

    for player in incoming:
        lines.append(
            f"🟢 IN — {player_text(player)}"
        )

    lines.append("")
    lines.append(
        f'🔗 <a href="{page_url}">Open FUT.GG</a>'
    )

    return "\n".join(lines)


# ============================================================
# APP DATA
# ============================================================

def build_app_data(state):

    os.makedirs(
        os.path.dirname(APP_FILE),
        exist_ok=True
    )

    output = {
        "updated": __import__(
            "datetime"
        ).datetime.utcnow().isoformat() + "Z",
        "pages": {}
    }

    for page_name, players in state.items():

        output["pages"][page_name] = {
            "players": players
        }

    with open(
        APP_FILE,
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
# ERROR
# ============================================================

def send_page_error(
    page_name,
    error,
    url
):

    message = (
        f"⚠️ <b>FUT.GG ERROR</b>\n\n"
        f"<b>{escape(page_name)}</b>\n"
        f"{escape(str(error))}\n\n"
        f'🔗 <a href="{url}">Open FUT.GG</a>'
    )

    send_telegram(
        message
    )


# ============================================================
# MAIN
# ============================================================

def main():

    old_state = load_state()

    new_state = dict(
        old_state
    )

    any_change = False

    for page_name, config in PAGES.items():

        try:

            new_players = get_players(
                page_name,
                config
            )

            old_players = old_state.get(
                page_name
            )

            # ------------------------------------------------
            # FIRST RUN
            # ------------------------------------------------

            if old_players is None:

                print(
                    f"{page_name}: "
                    f"first run -> saving silently"
                )

                new_state[
                    page_name
                ] = new_players

                any_change = True
                continue

            # ------------------------------------------------
            # COMPARE
            # ------------------------------------------------

            outgoing, incoming = compare_players(
                old_players,
                new_players
            )

            # ------------------------------------------------
            # CHANGE
            # ------------------------------------------------

            if outgoing or incoming:

                print(
                    f"{page_name}: CHANGE DETECTED"
                )

                for player in outgoing:
                    print(
                        "OUT:",
                        player["name"]
                    )

                for player in incoming:
                    print(
                        "IN:",
                        player["name"]
                    )

                message = build_change_message(
                    page_name,
                    outgoing,
                    incoming,
                    config["url"]
                )

                send_telegram(
                    message
                )

                any_change = True

            else:

                print(
                    f"{page_name}: "
                    f"no changes"
                )

            # ------------------------------------------------
            # SAVE GOOD DATA
            # ------------------------------------------------

            new_state[
                page_name
            ] = new_players

        except Exception as e:

            print(
                f"{page_name}: ERROR -> {e}"
            )

            # IMPORTANT:
            # Do NOT overwrite previous good state.
            #
            # The old data remains in new_state.

            send_page_error(
                page_name,
                e,
                config["url"]
            )

    # ========================================================
    # SAVE
    # ========================================================

    if any_change:

        save_state(
            new_state
        )

        build_app_data(
            new_state
        )

    else:

        # Still make sure files exist
        if not os.path.exists(
            STATE_FILE
        ):
            save_state(
                new_state
            )

        build_app_data(
            new_state
        )

    print()
    print("=" * 60)
    print("MONITOR FINISHED")
    print("=" * 60)


if __name__ == "__main__":
    main()