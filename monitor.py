import os
import re
import json
import html
import requests
from bs4 import BeautifulSoup, Tag

# ============================================================
# CONFIG
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

PLAYERS_FILE = "players.json"
CARD_CACHE_FILE = "card_cache.json"
CARD_DATABASE_FILE = "card_database.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# ============================================================
# MONITORED CATEGORIES
# ============================================================

CATEGORIES = [
    {
        "key": "heroes",
        "name": "Heroes",
        "emoji": "🦸‍♂️",
        "url": "https://www.fut.gg/fut-gallery/rarities/heroes/",
        "slots": 5,
    },
    {
        "key": "holographics",
        "name": "Holographics",
        "emoji": "✨️",
        "url": "https://www.fut.gg/fut-gallery/rarities/holographics/",
        "slots": 5,
    },
    {
        "key": "season1",
        "name": "Season 1",
        "emoji": "1️⃣",
        "url": "https://www.fut.gg/fut-gallery/rarities/season-1/",
        "slots": 10,
    },
]

# ============================================================
# KNOWN FINISHES
# ============================================================

KNOWN_FINISHES = {
    # -------------------------
    # PRISTINE HOLO
    # -------------------------
    "67335170": "PRISTINE HOLO",
    "67114537": "PRISTINE HOLO",
    "67335237": "PRISTINE HOLO",
    "67371135": "PRISTINE HOLO",
    "67342564": "PRISTINE HOLO",
    "67186651": "PRISTINE HOLO",
    "67335573": "PRISTINE HOLO",
    "67135573": "PRISTINE HOLO",

    "67335157": "PRISTINE HOLO",
    "67384140": "PRISTINE HOLO",
    "67275770": "PRISTINE HOLO",
    "67180472": "PRISTINE HOLO",
    "67298908": "PRISTINE HOLO",

    "67348095": "PRISTINE HOLO",
    "67368151": "PRISTINE HOLO",

    # -------------------------
    # HOLO
    # -------------------------
    "67179830": "HOLO",
    "67188263": "HOLO",
    "67368429": "HOLO",
    "67353040": "HOLO",
    "67372629": "HOLO",
    "67386815": "HOLO",
    "67374557": "HOLO",

    # -------------------------
    # BASE
    # -------------------------
    "226306": "BASE",
    "233700": "BASE",
    "5673": "BASE",
    "50590935": "BASE",
    "50590026": "BASE",
    "50570879": "BASE",
}

# ============================================================
# GENERIC HELPERS
# ============================================================

UI_WORDS = {
    "gallery token",
    "grading score",
    "fc coin",
    "fc coins",
    "player card",
    "search",
    "filter",
    "sort",
    "load more",
    "login",
    "sign up",
    "sell",
    "buy",
}

def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, data):
    tmp = path + ".tmp"

    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    os.replace(tmp, path)


def clean_text(value):
    if not value:
        return ""

    value = html.unescape(str(value))
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def normalize_name(name):
    name = clean_text(name)

    # Remove eventual duplicated rating at the end
    name = re.sub(r"\s+\d{2,3}$", "", name)

    return name.strip()


def is_placeholder(name):
    if not name:
        return True

    n = clean_text(name).lower()

    return (
        n == "player card"
        or n.startswith("player card")
        or n in {"empty", "empty slot"}
    )


# ============================================================
# ITEM ID
# ============================================================

def extract_item_id_from_text(value):
    if not value:
        return None

    value = str(value)

    # FUT.GG assets:
    # .../2027/futgg-player-item-card/27-67335170....webp
    patterns = [
        r"/27-(\d{4,})(?:[./?_-]|$)",
        r"\b27-(\d{4,})\b",
    ]

    for pattern in patterns:
        match = re.search(pattern, value)

        if match:
            return match.group(1)

    return None


def extract_item_id(img):
    if not img:
        return None

    attributes = [
        "src",
        "data-src",
        "data-original",
        "data-lazy-src",
        "srcset",
        "data-srcset",
        "alt",
    ]

    for attr in attributes:
        value = img.get(attr)

        if not value:
            continue

        item_id = extract_item_id_from_text(value)

        if item_id:
            return item_id

    # Sometimes the URL is on the parent link
    parent = img.parent

    for _ in range(4):
        if not parent or not isinstance(parent, Tag):
            break

        for attr in ["href", "src", "data-href"]:
            value = parent.get(attr)

            if value:
                item_id = extract_item_id_from_text(value)

                if item_id:
                    return item_id

        parent = parent.parent

    return None


# ============================================================
# ALT / PLAYER PARSING
# ============================================================

def parse_player_alt(alt):
    """
    Examples:

    Šašić - 89 - Base Hero
    Litmanen - 88 - Base Hero
    Cucurella - 88 - Destined for Glory
    Player Card
    """

    alt = clean_text(alt)

    if not alt:
        return None

    if is_placeholder(alt):
        return {
            "player": "Player Card",
            "overall": None,
            "version": None,
        }

    parts = [clean_text(x) for x in alt.split(" - ")]

    if len(parts) >= 2:
        player = parts[0]

        rating_match = re.search(r"\b(\d{2,3})\b", parts[1])

        if rating_match:
            overall = int(rating_match.group(1))

            version = ""

            if len(parts) >= 3:
                version = " - ".join(parts[2:]).strip()

            return {
                "player": normalize_name(player),
                "overall": overall,
                "version": version,
            }

    # Fallback:
    rating_match = re.search(r"\b(\d{2,3})\b", alt)

    if rating_match:
        overall = int(rating_match.group(1))

        player = alt[:rating_match.start()].strip(" -")

        return {
            "player": normalize_name(player),
            "overall": overall,
            "version": "",
        }

    return None


# ============================================================
# VALID PLAYER IMAGE
# ============================================================

def image_to_card(img):
    if not img or not isinstance(img, Tag):
        return None

    alt = clean_text(img.get("alt", ""))

    if not alt:
        return None

    parsed = parse_player_alt(alt)

    if not parsed:
        return None

    player = parsed["player"]

    # Placeholder
    if is_placeholder(player):
        return {
            "player": "Player Card",
            "overall": None,
            "version": None,
            "item_id": None,
            "finish": None,
            "empty": True,
        }

    # Reject obvious UI images
    if player.lower() in UI_WORDS:
        return None

    overall = parsed["overall"]

    # A valid FUT card needs player + rating
    if not player or overall is None:
        return None

    item_id = extract_item_id(img)

    finish = None

    if item_id:
        finish = KNOWN_FINISHES.get(str(item_id))

    return {
        "player": player,
        "overall": overall,
        "version": parsed["version"],
        "item_id": item_id,
        "finish": finish or "UNKNOWN",
        "empty": False,
    }


# ============================================================
# FETCH PAGE
# ============================================================

def fetch_page(url):
    print(f"Fetching: {url}")

    response = requests.get(
        url,
        headers=HEADERS,
        timeout=30,
    )

    print(f"HTTP status: {response.status_code}")

    response.raise_for_status()

    print(f"Downloaded: {len(response.text)} characters")

    return response.text


# ============================================================
# FIND CHEAPEST GRADE HEADING
# ============================================================

def find_cheapest_heading(soup, category_key):
    headings = soup.find_all(
        string=re.compile(
            r"Cheapest\s+grade",
            re.I,
        )
    )

    if not headings:
        print("Cheapest grade heading NOT found.")
        return None

    # Holographics specifically needs the S lineup.
    if category_key == "holographics":
        for text_node in headings:
            text = clean_text(text_node)

            if re.search(r"Cheapest\s+grade\s+S\s+lineup", text, re.I):
                print("Cheapest grade S heading found.")
                return text_node

    # Heroes / Season 1: any Cheapest grade lineup
    for text_node in headings:
        text = clean_text(text_node)

        if re.search(r"Cheapest\s+grade", text, re.I):
            print("Cheapest grade heading found.")
            return text_node

    return headings[0]


# ============================================================
# GET IMAGES FROM THE CORRECT LINEUP
# ============================================================

def get_lineup_images(soup, category):
    category_key = category["key"]
    slots = category["slots"]

    heading = find_cheapest_heading(soup, category_key)

    if not heading:
        return []

    # --------------------------------------------------------
    # IMPORTANT:
    # We do NOT simply search the whole page.
    #
    # We first locate the container belonging to the
    # "Cheapest grade ..." heading.
    # --------------------------------------------------------

    heading_tag = heading.parent

    candidates = []

    # Try progressively larger ancestors.
    ancestors = []

    current = heading_tag

    for _ in range(8):
        if not current:
            break

        if isinstance(current, Tag):
            ancestors.append(current)

        current = current.parent

    # Score containers according to how well they contain
    # the expected lineup.
    best_container = None
    best_score = -999999

    for container in ancestors:
        imgs = container.find_all("img")

        parsed = []

        for img in imgs:
            card = image_to_card(img)

            if card:
                parsed.append(card)

        if not parsed:
            continue

        players = [
            x for x in parsed
            if not x.get("empty")
        ]

        placeholders = [
            x for x in parsed
            if x.get("empty")
        ]

        # We want something close to the expected lineup size.
        count = len(parsed)

        distance = abs(count - slots)

        score = 0

        # Strong preference for exact lineup size.
        if count == slots:
            score += 1000

        score -= distance * 30

        # Player cards are much more useful than huge containers
        score += min(len(players), slots) * 100

        # Avoid enormous page containers.
        if count > slots + 10:
            score -= 500

        if score > best_score:
            best_score = score
            best_container = container

    # --------------------------------------------------------
    # If we found a good container, use it.
    # --------------------------------------------------------

    if best_container:
        imgs = best_container.find_all("img")

        parsed = []

        for img in imgs:
            card = image_to_card(img)

            if card:
                parsed.append(card)

        # Prefer an exact sequence of slots.
        if len(parsed) >= slots:
            # Find a contiguous window of exactly `slots`
            # that contains the best player lineup.
            best_window = None
            best_window_score = -999999

            for i in range(0, len(parsed) - slots + 1):
                window = parsed[i:i + slots]

                players = sum(
                    1 for x in window
                    if not x.get("empty")
                )

                empties = sum(
                    1 for x in window
                    if x.get("empty")
                )

                score = players * 100 + empties * 5

                # Exact number of slots is inherently valid.
                if score > best_window_score:
                    best_window_score = score
                    best_window = window

            if best_window:
                print(
                    f"Selected lineup candidate: "
                    f"{len(best_window)} lineup slots"
                )

                return best_window

        return parsed[:slots]

    # ========================================================
    # SPECIAL FALLBACK
    # ========================================================
    #
    # Search the HTML for sequences of valid player images.
    # This is especially useful if FUT.GG changes its wrapper
    # structure.
    # ========================================================

    all_imgs = soup.find_all("img")

    valid = []

    for img in all_imgs:
        card = image_to_card(img)

        if card:
            valid.append(card)

    print(
        f"Fallback valid lineup images: "
        f"{len(valid)}"
    )

    # Find best contiguous sequence.
    if len(valid) >= slots:
        best = None
        best_score = -999999

        for i in range(len(valid) - slots + 1):
            window = valid[i:i + slots]

            players = sum(
                1 for x in window
                if not x.get("empty")
            )

            score = players

            if category_key == "holographics":
                # Holographics should be player cards, not
                # empty "Player Card" placeholders.
                score += players * 10

            if score > best_score:
                best_score = score
                best = window

        if best:
            return best

    return valid[:slots]


# ============================================================
# DATABASE
# ============================================================

def load_database():
    data = load_json(
        CARD_DATABASE_FILE,
        [],
    )

    if not isinstance(data, list):
        return []

    return data


def database_finish(item_id, database):
    if not item_id:
        return None

    item_id = str(item_id)

    if item_id in KNOWN_FINISHES:
        return KNOWN_FINISHES[item_id]

    for item in database:
        if str(item.get("item_id", "")) == item_id:
            finish = item.get("finish")

            if finish:
                return finish

    return None


# ============================================================
# CARD IDENTITY
# ============================================================

def card_identity(card):
    """
    ItemID is the strongest identity.

    This preserves legitimate duplicates such as:
    Šašić BASE + Šašić PRISTINE HOLO.
    """

    item_id = card.get("item_id")

    if item_id:
        return f"ID:{item_id}"

    # UNKNOWN cards are only fallback identities.
    player = clean_text(card.get("player"))
    overall = card.get("overall")
    version = clean_text(card.get("version"))
    finish = clean_text(card.get("finish"))

    return (
        f"UNKNOWN:{player}|"
        f"{overall}|"
        f"{version}|"
        f"{finish}"
    )


def display_card(card):
    player = card.get("player", "Player Card")
    overall = card.get("overall")

    if overall:
        return f"{player} {overall}"

    return player


# ============================================================
# REMOVE OLD UNKNOWN FALSE OUTS
# ============================================================

def old_card_matches_current_unknown(old_card, current_cards):
    """
    If an old card has no ItemID but the same player + overall
    now exists with a real ItemID, it is NOT an OUT.

    This fixes old states like:

    Šašić - 89 - Base Hero 89 — UNKNOWN

    when current state contains:

    Šašić 89 — 67335170 — PRISTINE HOLO
    Šašić 89 — 226306 — BASE
    """

    old_id = old_card.get("item_id")

    if old_id:
        return False

    old_player = normalize_name(
        old_card.get("player", "")
    )

    old_overall = old_card.get("overall")

    if not old_player:
        # Try parsing old malformed player field
        parsed = parse_player_alt(
            old_card.get("name", "")
        )

        if parsed:
            old_player = parsed["player"]
            old_overall = parsed["overall"]

    for current in current_cards:
        if current.get("empty"):
            continue

        if not current.get("item_id"):
            continue

        current_player = normalize_name(
            current.get("player", "")
        )

        current_overall = current.get("overall")

        if (
            old_player.lower() == current_player.lower()
            and old_overall == current_overall
        ):
            return True

    return False


# ============================================================
# LOAD / SAVE MONITOR STATE
# ============================================================

def load_state():
    data = load_json(
        PLAYERS_FILE,
        {},
    )

    if not isinstance(data, dict):
        return {}

    return data


def save_state(state):
    save_json(
        PLAYERS_FILE,
        state,
    )


# ============================================================
# TELEGRAM
# ============================================================

def telegram_send(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram credentials missing.")
        return

    url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    response = requests.post(
        url,
        json=payload,
        timeout=30,
    )

    print(
        f"Telegram status: "
        f"{response.status_code}"
    )

    if response.status_code != 200:
        print(response.text)


# ============================================================
# CATEGORY CHECK
# ============================================================

def check_category(category, state, database):
    name = category["name"]
    key = category["key"]
    slots = category["slots"]

    print()
    print("=" * 60)
    print(
        f"Checking {category['emoji']} "
        f"{name.upper()} ({slots} players)..."
    )
    print("=" * 60)

    page = fetch_page(category["url"])

    soup = BeautifulSoup(
        page,
        "html.parser",
    )

    lineup = get_lineup_images(
        soup,
        category,
    )

    print(
        f"Lineup slot images found: "
        f"{len(lineup)}/{slots}"
    )

    # Ensure exact slot count
    lineup = lineup[:slots]

    print(
        f"Images/cards detected in selected container: "
        f"{len(lineup)}"
    )

    print(
        f"Rendered lineup: "
        f"{len(lineup)}/{slots} slots"
    )

    current = []

    for card in lineup:
        # ----------------------------------------------------
        # EMPTY SLOT
        # ----------------------------------------------------
        if card.get("empty"):
            print(
                "- Player Card — EMPTY SLOT"
            )

            current.append({
                "player": "Player Card",
                "overall": None,
                "version": None,
                "item_id": None,
                "finish": None,
                "empty": True,
            })

            continue

        item_id = card.get("item_id")

        finish = (
            KNOWN_FINISHES.get(str(item_id))
            if item_id
            else None
        )

        if not finish:
            finish = database_finish(
                item_id,
                database,
            )

        if not finish:
            finish = "UNKNOWN"

        card["finish"] = finish

        print(
            f"- {display_card(card)} — "
            f"ItemID {item_id} — {finish}"
        )

        current.append(card)

    # --------------------------------------------------------
    # Previous state
    # --------------------------------------------------------

    previous = state.get(key, [])

    if not isinstance(previous, list):
        previous = []

    # --------------------------------------------------------
    # Current real cards only
    # --------------------------------------------------------

    current_real = [
        c for c in current
        if not c.get("empty")
    ]

    # --------------------------------------------------------
    # Current identities
    # --------------------------------------------------------

    current_ids = {
        card_identity(c)
        for c in current_real
    }

    # --------------------------------------------------------
    # IN cards
    #
    # A card is IN only if its ItemID is new.
    # Unknown cards are not treated as new if there is
    # already a matching old/current identity.
    # --------------------------------------------------------

    previous_ids = {
        card_identity(c)
        for c in previous
        if not c.get("empty")
    }

    incoming = []

    for card in current_real:
        identity = card_identity(card)

        if identity not in previous_ids:
            incoming.append(card)

    # --------------------------------------------------------
    # OUT cards
    # --------------------------------------------------------

    outgoing = []

    for old in previous:
        if old.get("empty"):
            continue

        old_identity = card_identity(old)

        # Already present
        if old_identity in current_ids:
            continue

        # ----------------------------------------------------
        # CRITICAL:
        # Old UNKNOWN cards from the old broken parser must
        # never create fake OUT messages when the same player
        # is now correctly identified.
        # ----------------------------------------------------
        if old.get("item_id") in (None, "", "None"):
            if old_card_matches_current_unknown(
                old,
                current_real,
            ):
                continue

        outgoing.append(old)

    # --------------------------------------------------------
    # Save current state
    # --------------------------------------------------------

    state[key] = current

    return {
        "category": category,
        "current": current,
        "incoming": incoming,
        "outgoing": outgoing,
    }


# ============================================================
# TELEGRAM MESSAGE
# ============================================================

def build_category_message(result):
    category = result["category"]
    current = result["current"]
    incoming = result["incoming"]
    outgoing = result["outgoing"]

    lines = []

    lines.append(
        f"<b>{category['emoji']} "
        f"{html.escape(category['name'])}</b>"
    )

    lines.append(
        "<b>📋 Current lineup 📋</b>"
    )

    # --------------------------------------------------------
    # CURRENT LINEUP
    # --------------------------------------------------------

    for card in current:
        if card.get("empty"):
            continue

        player = html.escape(
            str(card.get("player", ""))
        )

        overall = card.get("overall")

        if overall:
            title = f"{player} {overall}"
        else:
            title = player

        finish = html.escape(
            str(card.get("finish") or "UNKNOWN")
        )

        lines.append(
            f"🟢 <b>{title}</b>　·　{finish}"
        )

    # --------------------------------------------------------
    # OUT
    # --------------------------------------------------------

    for card in outgoing:
        player = card.get("player", "")
        overall = card.get("overall")
        version = card.get("version", "")
        finish = card.get("finish") or "UNKNOWN"

        if overall:
            title = f"{player} {overall}"
        else:
            title = str(player)

        # If the old parser stored malformed names such as:
        # "Šašić - 89 - Base Hero 89"
        # clean them.
        parsed = parse_player_alt(str(player))

        if parsed:
            clean_player = parsed["player"]
            clean_overall = (
                parsed["overall"]
                if parsed["overall"] is not None
                else overall
            )

            if clean_overall:
                title = f"{clean_player} {clean_overall}"
            else:
                title = clean_player

        lines.append(
            f"🔴 OUT — <b>{html.escape(title)}</b>"
            f"　·　{html.escape(str(finish))}"
        )

    return "\n".join(lines)


# ============================================================
# MAIN
# ============================================================

def main():
    print()
    print("FUT.GG MONITOR")
    print(
        __import__("datetime")
        .datetime.now()
        .isoformat(timespec="seconds")
    )
    print("=" * 60)

    database = load_database()

    print(
        f"Known card finishes added to database: "
        f"{len(KNOWN_FINISHES)}"
    )

    print()
    print(
        f"Database items: "
        f"{len(database)}"
    )

    players = set()

    for item in database:
        player = item.get("player")

        if player:
            players.add(
                clean_text(player)
            )

    print(
        f"Database players: "
        f"{len(players)}"
    )

    state = load_state()

    results = []

    for category in CATEGORIES:
        try:
            result = check_category(
                category,
                state,
                database,
            )

            results.append(result)

        except Exception as e:
            print()
            print(
                f"ERROR in {category['name']}: "
                f"{type(e).__name__}: {e}"
            )

    # Save state BEFORE Telegram
    save_state(state)

    # ========================================================
    # TELEGRAM
    # ========================================================

    print()
    print("=" * 60)
    print("TELEGRAM MESSAGE")
    print("=" * 60)

    message_lines = [
        "<b>📋 FUT.GG Monitor</b>"
    ]

    for index, result in enumerate(results):

        if index > 0:
            message_lines.append("")
            message_lines.append(
                "--------------------"
            )
            message_lines.append("")

        message_lines.append(
            build_category_message(result)
        )

    message = "\n".join(message_lines)

    print(message)

    telegram_send(message)

    print()
    print("DONE")


if __name__ == "__main__":
    main()