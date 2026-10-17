import json
import os
import re
from collections import Counter

import requests
from bs4 import BeautifulSoup


# ============================================================
# CONFIG
# ============================================================

PAGES = {
    "Heroes": {
        "url": "https://www.fut.gg/fut-gallery/rarities/heroes/",
        "slots": 5,
        "emoji": "🦸‍♂️",
    },
    "Holographics": {
        "url": "https://www.fut.gg/fut-gallery/rarities/holographics/",
        "slots": 5,
        "emoji": "✨️",
    },
    "Season 1": {
        "url": "https://www.fut.gg/fut-gallery/rarities/season-1/",
        "slots": 10,
        "emoji": "1️⃣",
    },
}


PLAYERS_FILE = "players.json"
CACHE_FILE = "card_cache.json"


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


session = requests.Session()
session.headers.update(HEADERS)


# ============================================================
# KNOWN FINISHES
# ============================================================

KNOWN_FINISHES = {

    # HEROES

    "67335170": "PRISTINE HOLO",
    "67114537": "PRISTINE HOLO",
    "67335237": "PRISTINE HOLO",
    "67371135": "PRISTINE HOLO",

    "226306": "BASE",
    "233700": "BASE",

    "67186651": "PRISTINE HOLO",

    # HOLOGRAPHICS

    "67335157": "PRISTINE HOLO",
    "67384140": "PRISTINE HOLO",
    "67275770": "PRISTINE HOLO",
    "67180472": "PRISTINE HOLO",
    "67298908": "PRISTINE HOLO",

    # SEASON 1

    "67348095": "PRISTINE HOLO",
    "67368151": "PRISTINE HOLO",
    "67179830": "HOLO",
    "67188263": "HOLO",
    "67368429": "HOLO",
    "67353040": "HOLO",
    "67372629": "HOLO",
    "67386815": "HOLO",
    "67374557": "HOLO",

    "50590935": "BASE",
}


# ============================================================
# HELPERS
# ============================================================

def clean(value):

    if value is None:
        return ""

    return re.sub(
        r"\s+",
        " ",
        str(value)
    ).strip()


def normalize_name(name):

    return clean(name).lower()


# ============================================================
# JSON
# ============================================================

def load_json(path, default):

    if not os.path.exists(path):
        return default

    try:

        with open(
            path,
            "r",
            encoding="utf-8"
        ) as f:

            return json.load(f)

    except Exception:

        print(
            f"WARNING: cannot read {path}"
        )

        return default


def save_json(path, data):

    temp = path + ".tmp"

    with open(
        temp,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )

    os.replace(
        temp,
        path
    )


# ============================================================
# FETCH
# ============================================================

def fetch(url):

    response = session.get(
        url,
        timeout=45
    )

    response.raise_for_status()

    return response.text


# ============================================================
# FIND LINEUP
# ============================================================

def find_lineup(html):

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    headings = soup.find_all(
        string=re.compile(
            r"Cheapest grade",
            re.I
        )
    )

    if not headings:
        raise RuntimeError(
            "Cheapest grade lineup not found"
        )

    heading = headings[-1]

    node = heading.parent

    for _ in range(12):

        if node is None:
            break

        text = clean(
            node.get_text(
                " ",
                strip=True
            )
        )

        html_text = str(node)

        if (
            "Add players" in text
            and len(html_text) > 1000
        ):

            marker = re.search(
                r"Add players",
                html_text,
                re.I
            )

            if marker:
                html_text = html_text[
                    :marker.start()
                ]

            return BeautifulSoup(
                html_text,
                "html.parser"
            )

        node = node.parent

    raise RuntimeError(
        "Could not isolate lineup"
    )


# ============================================================
# ITEM ID
# ============================================================

def extract_item_id(src):

    if not src:
        return None

    match = re.search(
        r"/27-(\d+)(?:\.|/)",
        src
    )

    if match:
        return match.group(1)

    return None


# ============================================================
# ALT PARSER
# ============================================================

def parse_alt(alt):

    alt = clean(alt)

    if not alt:
        return None

    if alt.lower() == "player card":
        return None

    match = re.match(
        r"^(.+?)\s*-\s*(\d{2})\s*-\s*(.+?)$",
        alt
    )

    if not match:
        return None

    return {
        "name": clean(match.group(1)),
        "overall": int(match.group(2)),
        "version": clean(match.group(3)),
    }


# ============================================================
# FINISH
# ============================================================

def resolve_finish(
    item_id,
    previous,
    cache
):

    item_id = str(item_id)

    # Known database
    if item_id in KNOWN_FINISHES:

        return KNOWN_FINISHES[
            item_id
        ]

    # Cache
    cached = cache.get(
        item_id
    )

    if isinstance(cached, dict):

        finish = cached.get(
            "finish"
        )

        if finish in (
            "BASE",
            "HOLO",
            "PRISTINE HOLO"
        ):

            return finish

    # Previous state
    for card in previous:

        if not isinstance(card, dict):
            continue

        if str(
            card.get("item_id", "")
        ) == item_id:

            finish = card.get(
                "finish"
            )

            if finish in (
                "BASE",
                "HOLO",
                "PRISTINE HOLO"
            ):

                return finish

    return None


# ============================================================
# EXTRACT LINEUP
# ============================================================

def extract_lineup(
    soup,
    category,
    previous,
    cache
):

    slots = []

    images = soup.find_all(
        "img"
    )

    seen = set()

    for img in images:

        alt = clean(
            img.get("alt")
        )

        src = clean(
            img.get("src")
        )

        # ----------------------------------------------------
        # EMPTY SLOT
        # ----------------------------------------------------

        if alt.lower() == "player card":

            slots.append(
                None
            )

            continue

        # ----------------------------------------------------
        # CARD
        # ----------------------------------------------------

        parsed = parse_alt(
            alt
        )

        if not parsed:
            continue

        item_id = extract_item_id(
            src
        )

        if not item_id:
            continue

        key = (
            str(item_id),
            parsed["name"],
            parsed["overall"],
            parsed["version"],
        )

        if key in seen:
            continue

        seen.add(key)

        finish = resolve_finish(
            item_id,
            previous,
            cache
        )

        slots.append({
            "name": parsed["name"],
            "overall": parsed["overall"],
            "version": parsed["version"],
            "finish": finish,
            "item_id": str(item_id),
        })

    return slots


# ============================================================
# CARD KEY
# ============================================================

def card_key(card):

    if card is None:
        return None

    return (
        normalize_name(
            card.get("name", "")
        ),
        int(
            card.get("overall", 0)
        ),
        clean(
            card.get("version", "")
        ).lower(),
        clean(
            card.get("finish", "")
        ).upper(),
        str(
            card.get("item_id", "")
        ),
    )


# ============================================================
# LABEL
# ============================================================

def card_label(card):

    if card is None:
        return "Player Card"

    finish = card.get(
        "finish"
    )

    if finish:

        return (
            f"{card['name']} "
            f"{card['overall']} — "
            f"{finish}"
        )

    return (
        f"{card['name']} "
        f"{card['overall']} — UNKNOWN"
    )


# ============================================================
# REAL CARDS ONLY
# ============================================================

def real_cards(slots):

    return [
        card
        for card in slots
        if card is not None
    ]


# ============================================================
# COMPARE
# ============================================================

def compare_cards(
    old_slots,
    new_slots
):

    old_cards = real_cards(
        old_slots
    )

    new_cards = real_cards(
        new_slots
    )

    old_counter = Counter(
        card_key(card)
        for card in old_cards
    )

    new_counter = Counter(
        card_key(card)
        for card in new_cards
    )

    out = []
    incoming = []

    # OUT
    difference = (
        old_counter - new_counter
    )

    for key, count in difference.items():

        for _ in range(count):

            for card in old_cards:

                if card_key(card) == key:

                    out.append(
                        card
                    )

                    break

    # IN
    difference = (
        new_counter - old_counter
    )

    for key, count in difference.items():

        for _ in range(count):

            for card in new_cards:

                if card_key(card) == key:

                    incoming.append(
                        card
                    )

                    break

    return out, incoming


# ============================================================
# UNKNOWN FINISH
# ============================================================

def has_unknown_finish(slots):

    for card in real_cards(slots):

        if card.get(
            "finish"
        ) not in (
            "BASE",
            "HOLO",
            "PRISTINE HOLO"
        ):

            return True

    return False


# ============================================================
# PROCESS CATEGORY
# ============================================================

def process_category(
    category,
    config,
    state,
    cache
):

    print()
    print("=" * 60)
    print(
        f"Checking {category}..."
    )
    print(
        config["url"]
    )

    previous = state.get(
        category,
        []
    )

    if not isinstance(
        previous,
        list
    ):
        previous = []

    html = fetch(
        config["url"]
    )

    soup = find_lineup(
        html
    )

    slots = extract_lineup(
        soup,
        category,
        previous,
        cache
    )

    expected = config[
        "slots"
    ]

    # --------------------------------------------------------
    # VALIDATE SLOT COUNT
    # --------------------------------------------------------

    if len(slots) != expected:

        raise RuntimeError(
            f"Expected {expected} slots, "
            f"detected {len(slots)}"
        )

    cards = real_cards(
        slots
    )

    empty = slots.count(
        None
    )

    print(
        f"Rendered lineup: "
        f"{len(cards)}/{expected} real cards"
    )

    if category == "Season 1":

        print(
            f"Unknown slots: {empty}"
        )

    print(
        "Detected cards:"
    )

    for index, card in enumerate(
        slots,
        1
    ):

        if card is None:

            print(
                f"  [{index}] "
                f"Player Card"
            )

        else:

            print(
                f"  [{index}] "
                f"{card_label(card)} "
                f"ItemID={card['item_id']}"
            )

    # --------------------------------------------------------
    # UNKNOWN FINISH PROTECTION
    # --------------------------------------------------------

    if has_unknown_finish(
        slots
    ):

        print()
        print(
            "WARNING: finish unresolved."
        )

        print(
            "Previous state kept."
        )

        return {
            "category": category,
            "slots": previous,
            "previous": previous,
            "out": [],
            "incoming": [],
            "safe": False,
        }

    # --------------------------------------------------------
    # FIRST RUN
    # --------------------------------------------------------

    if not previous:

        print(
            "No previous state."
        )

        print(
            "Initializing current lineup."
        )

        state[
            category
        ] = slots

        return {
            "category": category,
            "slots": slots,
            "previous": [],
            "out": [],
            "incoming": [],
            "safe": True,
            "initializing": True,
        }

    # --------------------------------------------------------
    # COMPARE
    # --------------------------------------------------------

    out, incoming = compare_cards(
        previous,
        slots
    )

    print(
        f"OUT: {len(out)}"
    )

    print(
        f"IN: {len(incoming)}"
    )

    state[
        category
    ] = slots

    return {
        "category": category,
        "slots": slots,
        "previous": previous,
        "out": out,
        "incoming": incoming,
        "safe": True,
        "initializing": False,
    }


# ============================================================
# TELEGRAM
# ============================================================

def telegram_send(
    token,
    chat_id,
    message
):

    url = (
        f"https://api.telegram.org/bot"
        f"{token}/sendMessage"
    )

    response = session.post(
        url,
        json={
            "chat_id": chat_id,
            "text": message,
        },
        timeout=30
    )

    response.raise_for_status()


# ============================================================
# TELEGRAM FORMAT
# ============================================================

def format_category(result):

    category = result[
        "category"
    ]

    emoji = PAGES[
        category
    ]["emoji"]

    lines = [
        f"{emoji} {category}",
        ""
    ]

    # ========================================================
    # FINISH UNRESOLVED
    # ========================================================

    if not result["safe"]:

        lines.append(
            "⚠️ Finish unresolved"
        )

        lines.append(
            "Previous state kept"
        )

        lines.append("")

        lines.append(
            "Current lineup"
        )

        lines.append("")

        for card in result["slots"]:

            if card is None:
                continue

            lines.append(
                card_label(card)
            )

        return "\n".join(
            lines
        )

    # ========================================================
    # FIRST RUN
    # ========================================================

    if result.get(
        "initializing"
    ):

        lines.append(
            "Initial lineup saved"
        )

        lines.append("")

        lines.append(
            "Current lineup"
        )

        lines.append("")

        for card in result["slots"]:

            if card is None:
                continue

            lines.append(
                card_label(card)
            )

        return "\n".join(
            lines
        )

    # ========================================================
    # CHANGES
    # ========================================================

    out = result[
        "out"
    ]

    incoming = result[
        "incoming"
    ]

    slots = result[
        "slots"
    ]

    if out:

        lines.append(
            "🔴 OUT"
        )

        lines.append("")

        for card in out:

            lines.append(
                f"• {card_label(card)}"
            )

        lines.append("")

    if incoming:

        lines.append(
            "🟢 IN"
        )

        lines.append("")

        for card in incoming:

            lines.append(
                f"• {card_label(card)}"
            )

        lines.append("")

    # ========================================================
    # NO CHANGES
    # ========================================================

    if not out and not incoming:

        lines.append(
            "No feed changes"
        )

        lines.append("")

    # ========================================================
    # CURRENT LINEUP
    # ========================================================

    lines.append(
        "Current lineup"
    )

    lines.append("")

    incoming_counter = Counter(
        card_key(card)
        for card in incoming
    )

    for card in slots:

        # Player Card non viene mostrato su Telegram
        if card is None:
            continue

        key = card_key(
            card
        )

        if incoming_counter[key] > 0:

            lines.append(
                f"🟢 {card_label(card)}"
            )

            incoming_counter[key] -= 1

        else:

            lines.append(
                card_label(card)
            )

    return "\n".join(
        lines
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print(
        "FUT.GG MONITOR"
    )
    print(
        "=" * 60
    )

    token = os.getenv(
        "TELEGRAM_BOT_TOKEN"
    )

    chat_id = os.getenv(
        "TELEGRAM_CHAT_ID"
    )

    state = load_json(
        PLAYERS_FILE,
        {
            "Heroes": [],
            "Holographics": [],
            "Season 1": [],
        }
    )

    cache = load_json(
        CACHE_FILE,
        {}
    )

    results = []
    errors = []

    for category, config in PAGES.items():

        try:

            result = process_category(
                category,
                config,
                state,
                cache
            )

            results.append(
                result
            )

        except Exception as e:

            print()
            print(
                f"ERROR on {category}: {e}"
            )

            errors.append(
                (
                    category,
                    str(e)
                )
            )

    # --------------------------------------------------------
    # SAVE
    # --------------------------------------------------------

    save_json(
        PLAYERS_FILE,
        state
    )

    # --------------------------------------------------------
    # TELEGRAM
    # --------------------------------------------------------

    parts = []

    for result in results:

        parts.append(
            format_category(
                result
            )
        )

    for category, error in errors:

        emoji = PAGES[
            category
        ]["emoji"]

        parts.append(
            "\n".join([
                f"{emoji} {category}",
                "",
                "⚠️ Monitor error",
                "",
                error,
            ])
        )

    message = (
        "\n\n"
        + "\n\n".join(
            parts
        )
    )

    if token and chat_id:

        try:

            telegram_send(
                token,
                chat_id,
                message
            )

            print()
            print(
                "Telegram message sent."
            )

        except Exception as e:

            print()
            print(
                f"Telegram error: {e}"
            )

    # --------------------------------------------------------
    # FINAL STATE
    # --------------------------------------------------------

    print()
    print("=" * 60)
    print(
        "FINAL STATE"
    )
    print("=" * 60)

    for category in PAGES:

        slots = state.get(
            category,
            []
        )

        print(
            f"{category}: "
            f"{len(slots)} slots"
        )

        for index, card in enumerate(
            slots,
            1
        ):

            if card is None:

                print(
                    f"  [{index}] "
                    f"Player Card"
                )

            else:

                print(
                    f"  [{index}] "
                    f"{card_label(card)} "
                    f"[{card['item_id']}]"
                )

    print()
    print(
        "Done."
    )


if __name__ == "__main__":
    main()