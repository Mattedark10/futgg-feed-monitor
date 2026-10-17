import os
import re
import json
import html
import requests
from collections import Counter
from datetime import datetime, timezone
from urllib.parse import urljoin
from bs4 import BeautifulSoup


# ============================================================
# FUT.GG FEEDS
# ============================================================

PAGES = {
    "🦸 HEROES": {
        "url": "https://www.fut.gg/fut-gallery/rarities/heroes/",
        "players": 5,
        "best_grade": "A",
        "page_type": "heroes",
    },

    "🌈 HOLOGRAPHICS": {
        "url": "https://www.fut.gg/fut-gallery/rarities/holographics/",
        "players": 5,
        "best_grade": "S",
        "page_type": "holographics",
    },

    "🏆 SEASON 1": {
        "url": "https://www.fut.gg/fut-gallery/rarities/season-1/",
        "players": 10,
        "best_grade": "S",
        "page_type": "season_1",
    },
}


# ============================================================
# TELEGRAM
# ============================================================

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]


# ============================================================
# FILES
# ============================================================

STATE_FILE = "players.json"
APP_FILE = "docs/trending.json"

SITE = "https://www.fut.gg"


# ============================================================
# HTTP
# ============================================================

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


# ============================================================
# GRADE ORDER
# ============================================================

GRADE_ORDER = {
    "D": 1,
    "C": 2,
    "B": 3,
    "A": 4,
    "S": 5,
}


# ============================================================
# BALANCED OBJECT / ARRAY
# ============================================================

def extract_balanced_object(text, start):

    if start >= len(text) or text[start] != "{":
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
            continue

        if char == "{":
            depth += 1

        elif char == "}":

            depth -= 1

            if depth == 0:
                return text[start:i + 1]

    return None


def extract_balanced_array(text, start):

    if start >= len(text) or text[start] != "[":
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
            continue

        if char == "[":
            depth += 1

        elif char == "]":

            depth -= 1

            if depth == 0:
                return text[start:i + 1]

    return None


# ============================================================
# RSC OBJECTS
# ============================================================

def build_rsc_objects(source):

    objects = {}

    pattern = re.compile(
        r"\$R\[(\d+)\]\s*=\s*\{"
    )

    for match in pattern.finditer(source):

        ref_id = int(match.group(1))

        object_start = match.end() - 1

        object_text = extract_balanced_object(
            source,
            object_start
        )

        if object_text:
            objects[ref_id] = object_text

    return objects


def parse_simple_value(object_text, field):

    pattern = re.compile(
        rf"{re.escape(field)}\s*:\s*"
        r'(?:"([^"]*)"|([0-9]+(?:\.[0-9]+)?)|null|true|false)'
    )

    match = pattern.search(object_text)

    if not match:
        return None

    if match.group(1) is not None:
        return match.group(1)

    if match.group(2) is not None:

        number = match.group(2)

        if "." in number:
            return float(number)

        return int(number)

    if "null" in match.group(0):
        return None

    if "true" in match.group(0):
        return True

    return False


def extract_items_references(solution_text):

    match = re.search(
        r"items\s*:\s*(?:\$R\[\d+\]\s*=\s*)?\[",
        solution_text
    )

    if not match:
        return []

    array_start = solution_text.find(
        "[",
        match.start()
    )

    array_text = extract_balanced_array(
        solution_text,
        array_start
    )

    if not array_text:
        return []

    refs = []

    for ref in re.findall(
        r"\$R\[(\d+)\]",
        array_text
    ):
        refs.append(int(ref))

    return refs


# ============================================================
# IMAGE MAP
# ============================================================

def build_image_map(soup):

    result = {}

    for img in soup.find_all("img"):

        alt = (img.get("alt") or "").strip()
        src = img.get("src") or ""

        if not alt:
            continue

        id_match = re.search(
            r"27-(\d+)",
            src
        )

        if not id_match:
            continue

        item_id = id_match.group(1)

        match = re.match(
            r"(.+?)\s*-\s*(\d+)\s*-\s*(.+)",
            alt
        )

        if not match:
            continue

        result[item_id] = {
            "name": match.group(1).strip(),
            "rating": match.group(2).strip(),
            "card": match.group(3).strip(),
            "img": src,
        }

    return result


# ============================================================
# PLAYER NAME FALLBACK
# ============================================================

def search_player_name_in_source(
    source,
    player_ea_id
):

    pid = str(player_ea_id)

    patterns = [
        rf'playerEaId\s*:\s*{re.escape(pid)}.*?name\s*:\s*"([^"]+)"',
        rf'name\s*:\s*"([^"]+)".*?playerEaId\s*:\s*{re.escape(pid)}',
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            source,
            re.S
        )

        if match:

            value = match.group(1).strip()

            if value:
                return value

    return None


# ============================================================
# CARD VERSION
# ============================================================

def get_version(item_url):

    response = requests.get(
        item_url,
        headers=HEADERS,
        timeout=30
    )

    response.raise_for_status()

    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )

    h1 = soup.find("h1")

    if not h1:
        raise Exception(
            f"Titolo carta non trovato: {item_url}"
        )

    title = h1.get_text(
        " ",
        strip=True
    )

    if re.search(
        r"pristine\s+holographic",
        title,
        re.I
    ):
        return "Pristine Holographic"

    if re.search(
        r"holographic",
        title,
        re.I
    ):
        return "Holographic"

    return "Base"


def find_card_link(
    img,
    soup,
    item_id
):

    if img is None:
        return None

    pattern = re.compile(
        rf"/players/.*27-{re.escape(item_id)}"
    )

    parent = img

    for _ in range(8):

        parent = parent.parent

        if parent is None:
            break

        if (
            parent.name == "a"
            and pattern.search(
                parent.get("href", "")
            )
        ):
            return parent["href"]

        link = parent.find(
            "a",
            href=pattern
        )

        if link:
            return link["href"]

    link = soup.find(
        "a",
        href=pattern
    )

    if link:
        return link["href"]

    return None


# ============================================================
# BEST SOLUTION
# ============================================================

def get_best_solution(
    source,
    page_name,
    expected_players,
    wanted_grade
):

    rsc_objects = build_rsc_objects(source)

    solutions = []

    pattern = re.compile(
        r"solution\s*:\s*\$R\[(\d+)\]\s*=\s*\{"
    )

    for match in pattern.finditer(source):

        ref_id = int(match.group(1))

        solution_text = rsc_objects.get(
            ref_id
        )

        if not solution_text:
            continue

        name = parse_simple_value(
            solution_text,
            "name"
        )

        grade = parse_simple_value(
            solution_text,
            "grade"
        )

        required_cards = parse_simple_value(
            solution_text,
            "requiredCards"
        )

        if not name:
            continue

        if name.lower() != page_name.lower():
            continue

        if not grade:
            continue

        item_refs = extract_items_references(
            solution_text
        )

        solutions.append({
            "ref_id": ref_id,
            "name": name,
            "grade": grade,
            "requiredCards": required_cards,
            "items": item_refs,
            "object": solution_text,
        })

    if not solutions:

        raise Exception(
            f"Nessuna solution trovata per "
            f"'{page_name}'."
        )

    solutions.sort(
        key=lambda x: GRADE_ORDER.get(
            str(x["grade"]).upper(),
            0
        ),
        reverse=True
    )

    best = solutions[0]

    if (
        wanted_grade
        and GRADE_ORDER.get(
            str(best["grade"]).upper(),
            0
        )
        < GRADE_ORDER.get(
            wanted_grade.upper(),
            0
        )
    ):

        raise Exception(
            f"Grade massimo trovato per "
            f"{page_name}: {best['grade']}."
        )

    if len(best["items"]) != expected_players:

        raise Exception(
            f"{page_name}: la solution "
            f"{best['grade']} contiene "
            f"{len(best['items'])} carte, "
            f"attese {expected_players}."
        )

    return best, rsc_objects


# ============================================================
# GET PLAYERS
# ============================================================

def get_players(
    url,
    page_name,
    expected_players,
    wanted_grade,
    page_type,
    old_players=None
):

    response = requests.get(
        url,
        headers=HEADERS,
        timeout=40
    )

    response.raise_for_status()

    source = response.text

    soup = BeautifulSoup(
        source,
        "html.parser"
    )

    image_map = build_image_map(
        soup
    )

    best, rsc_objects = get_best_solution(
        source,
        page_name,
        expected_players,
        wanted_grade
    )

    print(
        f"BEST GRADE: {best['grade']}"
    )

    print(
        f"ITEMS: {len(best['items'])}"
    )

    known_versions = {}

    if old_players:

        for player in old_players:

            item_id = player.get(
                "item_id"
            )

            version = player.get(
                "version"
            )

            if (
                item_id
                and version
                and version != "?"
            ):
                known_versions[
                    str(item_id)
                ] = version

    players = []

    for item_ref in best["items"]:

        item_text = rsc_objects.get(
            item_ref
        )

        if not item_text:

            raise Exception(
                f"Impossibile risolvere "
                f"$R[{item_ref}]."
            )

        ea_id = parse_simple_value(
            item_text,
            "eaId"
        )

        player_ea_id = parse_simple_value(
            item_text,
            "playerEaId"
        )

        overall = parse_simple_value(
            item_text,
            "overall"
        )

        rarity_ea_id = parse_simple_value(
            item_text,
            "rarityEaId"
        )

        price = parse_simple_value(
            item_text,
            "price"
        )

        if ea_id is None:

            raise Exception(
                f"eaId mancante in "
                f"$R[{item_ref}]."
            )

        item_id = str(ea_id)

        visual = image_map.get(
            item_id,
            {}
        )

        name = visual.get(
            "name"
        )

        rating = visual.get(
            "rating"
        )

        card = visual.get(
            "card"
        )

        img = visual.get(
            "img",
            ""
        )

        if not name and player_ea_id:

            name = search_player_name_in_source(
                source,
                player_ea_id
            )

        if not name:
            name = f"Player {player_ea_id}"

        if rating is None and overall is not None:
            rating = str(overall)

        if card is None:

            if page_type == "heroes":
                card = "Base Hero"

            elif page_type == "holographics":
                card = "Holographic"

            else:
                card = "Season 1"

        # ----------------------------------------------------
        # VERSION
        # ----------------------------------------------------

        if page_type == "holographics":

            version = "Holographic"

        elif item_id in known_versions:

            version = known_versions[
                item_id
            ]

        else:

            image = soup.find(
                "img",
                src=re.compile(
                    rf"27-{re.escape(item_id)}"
                )
            )

            href = find_card_link(
                image,
                soup,
                item_id
            )

            if href:

                try:

                    version = get_version(
                        urljoin(
                            SITE,
                            href
                        )
                    )

                except Exception as error:

                    print(
                        f"Version error "
                        f"{name}: {error}"
                    )

                    version = "?"

            else:

                if "holographic" in card.lower():
                    version = "Holographic"
                else:
                    version = "Base"

        players.append({
            "name": name,
            "rating": str(rating),
            "card": card,
            "version": version,
            "item_id": item_id,
            "player_ea_id": player_ea_id,
            "rarity_ea_id": rarity_ea_id,
            "price": price,
            "img": img,
            "grade": best["grade"],
        })

    if len(players) != expected_players:

        raise Exception(
            f"Trovate {len(players)} carte "
            f"invece di {expected_players}."
        )

    return players


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):

    telegram_url = (
        f"https://api.telegram.org/"
        f"bot{BOT_TOKEN}/sendMessage"
    )

    response = requests.post(
        telegram_url,
        data={
            "chat_id": CHAT_ID,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=30,
    )

    response.raise_for_status()


# ============================================================
# COMPARISON
# ============================================================

def player_key(player):

    return (
        str(player.get("item_id", "")),
        str(player.get("version", "")),
    )


def counter_from_players(players):

    return Counter(
        player_key(player)
        for player in players
    )


def find_player_by_key(
    players,
    key
):

    for player in players:

        if player_key(player) == key:
            return player

    return None


def compare_players(
    old_players,
    new_players
):

    old_counter = counter_from_players(
        old_players
    )

    new_counter = counter_from_players(
        new_players
    )

    removed = []
    added = []

    for key, count in (
        old_counter - new_counter
    ).items():

        player = find_player_by_key(
            old_players,
            key
        )

        if player:

            for _ in range(count):
                removed.append(player)

    for key, count in (
        new_counter - old_counter
    ).items():

        player = find_player_by_key(
            new_players,
            key
        )

        if player:

            for _ in range(count):
                added.append(player)

    return removed, added


# ============================================================
# TELEGRAM PLAYER
# ============================================================

def player_text(player):

    version = player.get(
        "version",
        "?"
    )

    if version == "Base":

        tag = "⚪ <b>BASE</b> · "

    elif version == "Holographic":

        tag = "🌈 <b>HOLO</b> · "

    elif version == "Pristine Holographic":

        tag = "💎 <b>PRISTINE HOLO</b> · "

    else:

        tag = ""

    name = html.escape(
        str(player.get("name", "?"))
    )

    rating = html.escape(
        str(player.get("rating", "?"))
    )

    card = html.escape(
        str(player.get("card", "?"))
    )

    return (
        f"{tag}"
        f"<b>{name}</b> — "
        f"{rating} — "
        f"{card}"
    )


# ============================================================
# APP DATA
# ============================================================

def build_app_data(state):

    out = []
    seen = set()

    for category, players in state.items():

        for player in players:

            version = (
                player.get("version")
                or "Base"
            )

            lower_version = version.lower()

            if "pristine" in lower_version:

                ptype = "pristine"

            elif "holographic" in lower_version:

                ptype = "holo"

            elif category.endswith(
                "HEROES"
            ):

                ptype = "hero"

            else:

                ptype = "base"

            key = (
                player.get("item_id"),
                player.get("version"),
            )

            if key in seen:
                continue

            seen.add(key)

            out.append({
                "name": player.get(
                    "name",
                    ""
                ),
                "rating": player.get(
                    "rating",
                    ""
                ),
                "card": player.get(
                    "card",
                    ""
                ),
                "type": ptype,
                "version": version,
                "img": player.get(
                    "img",
                    ""
                ),
                "category": category,
                "grade": player.get(
                    "grade",
                    ""
                ),
                "ps5": None,
                "pc": None,
            })

    try:

        from zoneinfo import ZoneInfo

        now = datetime.now(
            ZoneInfo("Europe/Rome")
        ).strftime(
            "%H:%M"
        )

    except Exception:

        now = datetime.now(
            timezone.utc
        ).strftime(
            "%H:%M UTC"
        )

    return {
        "updated": now,
        "players": out,
    }


# ============================================================
# ERROR
# ============================================================

def send_page_error(
    category,
    url,
    error
):

    safe_category = html.escape(
        category
    )

    safe_error = html.escape(
        str(error)
    )

    safe_url = html.escape(
        url,
        quote=True
    )

    message = (
        "⚠️ <b>FUT.GG MONITOR ERROR</b>\n\n"
        f"{safe_category}\n\n"
        f"<b>Error:</b>\n"
        f"<code>{safe_error}</code>\n\n"
        f'<a href="{safe_url}">'
        "Open FUT.GG"
        "</a>"
    )

    try:
        send_telegram(
            message
        )
    except Exception as telegram_error:
        print(
            "Telegram error notification "
            f"failed: {telegram_error}"
        )


# ============================================================
# MAIN
# ============================================================

def main():

    if os.path.exists(
        STATE_FILE
    ):

        with open(
            STATE_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            old_state = json.load(
                file
            )

    else:

        old_state = {}

    new_state = dict(
        old_state
    )

    for category, config in PAGES.items():

        url = config["url"]

        expected_players = config[
            "players"
        ]

        wanted_grade = config[
            "best_grade"
        ]

        page_type = config[
            "page_type"
        ]

        page_name = (
            "Heroes"
            if page_type == "heroes"
            else
            "Holographics"
            if page_type == "holographics"
            else
            "Season 1"
        )

        print()
        print("=" * 60)
        print(
            f"Checking {category}"
        )
        print(
            f"Expected: "
            f"{wanted_grade} / "
            f"{expected_players} players"
        )

        old_players = old_state.get(
            category
        )

        try:

            players = get_players(
                url=url,
                page_name=page_name,
                expected_players=expected_players,
                wanted_grade=wanted_grade,
                page_type=page_type,
                old_players=old_players,
            )

        except Exception as error:

            print(
                f"ERROR: {error}"
            )

            if old_players is not None:
                new_state[
                    category
                ] = old_players

            send_page_error(
                category,
                url,
                error
            )

            continue

        print(
            f"Found {len(players)} players."
        )

        for i, player in enumerate(
            players,
            start=1
        ):

            print(
                f"{i}. "
                f"{player['name']} "
                f"{player['rating']} "
                f"{player['card']} "
                f"[{player['version']}]"
            )

        new_state[
            category
        ] = players

        # ----------------------------------------------------
        # FIRST RUN
        # ----------------------------------------------------

        if old_players is None:

            print(
                "First scan. "
                "Saving silently."
            )

            continue

        # ----------------------------------------------------
        # COMPARE
        # ----------------------------------------------------

        removed, added = compare_players(
            old_players,
            players
        )

        if not removed and not added:

            print(
                f"{category}: "
                "No changes."
            )

            continue

        # ----------------------------------------------------
        # TELEGRAM
        # ----------------------------------------------------

        message = (
            "🚨 <b>FUT.GG FEED UPDATE</b>\n\n"
            f"{html.escape(category)}\n"
            f"⭐ Best grade: "
            f"<b>{wanted_grade}</b>\n\n"
        )

        if removed:

            message += (
                "🔴 <b>OUT</b>\n"
            )

            for player in removed:

                message += (
                    f"🔴 "
                    f"{player_text(player)}\n"
                )

            message += "\n"

        if added:

            message += (
                "🟢 <b>IN</b>\n"
            )

            for player in added:

                message += (
                    f"🟢 "
                    f"{player_text(player)}\n"
                )

            message += "\n"

        safe_url = html.escape(
            url,
            quote=True
        )

        message += (
            "🕐 Change detected automatically\n"
            f'<a href="{safe_url}">'
            "View Feed on FUT.GG"
            "</a>"
        )

        try:

            send_telegram(
                message
            )

            print(
                "Telegram notification sent."
            )

        except Exception as error:

            print(
                f"Telegram error: {error}"
            )

    # --------------------------------------------------------
    # SAVE
    # --------------------------------------------------------

    with open(
        STATE_FILE,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            new_state,
            file,
            ensure_ascii=False,
            indent=2
        )

    os.makedirs(
        "docs",
        exist_ok=True
    )

    with open(
        APP_FILE,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            build_app_data(new_state),
            file,
            ensure_ascii=False,
            indent=2
        )

    print()
    print(
        "State saved."
    )
    print(
        "App data saved."
    )


if __name__ == "__main__":
    main()
