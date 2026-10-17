import json
import os
import re
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
    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/xml;q=0.9,image/avif,"
        "image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


session = requests.Session()
session.headers.update(HEADERS)


# ============================================================
# KNOWN FINISHES
# ============================================================
#
# Questi sono Item ID già verificati.
#
# Se un Item ID non è ancora conosciuto e FUT.GG non espone
# il finish direttamente nella gallery, NON lo inventiamo.
#
# In quel caso il monitor conserva lo stato precedente e
# impedisce falsi OUT/IN.
#
# ============================================================

KNOWN_FINISHES = {

    # --------------------------------------------------------
    # HEROES
    # --------------------------------------------------------

    "67335170": "PRISTINE HOLO",
    "67114537": "PRISTINE HOLO",
    "67335237": "PRISTINE HOLO",
    "67371135": "PRISTINE HOLO",

    # Šašić / Vialli base
    "226306": "BASE",
    "233700": "BASE",

    # Zamorano verificato da FUT.GG
    "67186651": "PRISTINE HOLO",

    # --------------------------------------------------------
    # HOLOGRAPHICS
    # --------------------------------------------------------

    "67335157": "PRISTINE HOLO",
    "67384140": "PRISTINE HOLO",
    "67275770": "PRISTINE HOLO",
    "67180472": "PRISTINE HOLO",
    "67298908": "PRISTINE HOLO",

    # --------------------------------------------------------
    # SEASON 1
    # --------------------------------------------------------

    "67348095": "PRISTINE HOLO",
    "67368151": "PRISTINE HOLO",
    "67179830": "HOLO",
    "67188263": "HOLO",
    "67368429": "HOLO",
    "67353040": "HOLO",
    "67372629": "HOLO",
    "67386815": "HOLO",
    "67374557": "HOLO",

    # Harder seconda versione
    # Il card page non riporta "Holographic" nel titolo,
    # quindi questa versione è trattata come BASE.
    "50590935": "BASE",
}


# ============================================================
# BASIC HELPERS
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
    name = clean(name)

    return name.lower()


# ============================================================
# LOAD / SAVE
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
            f"WARNING: impossibile leggere {path}"
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
            "Cheapest grade lineup non trovato"
        )

    # L'ultimo è quello che ci interessa
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

            # Tagliamo eventuale parte successiva
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
        "Impossibile isolare il lineup"
    )


# ============================================================
# ITEM ID
# ============================================================

def extract_item_id(src):

    if not src:
        return None

    # Esempio:
    #
    # .../27-67335170.7c559...
    #
    match = re.search(
        r"/27-(\d+)(?:\.|/)",
        src
    )

    if match:
        return match.group(1)

    return None


# ============================================================
# CARD VERSION
# ============================================================

def parse_alt(alt):

    alt = clean(alt)

    if not alt:
        return None

    # Placeholder
    if alt.lower() == "player card":
        return None

    # Nome - 88 - Destined for Glory
    match = re.match(
        r"^(.+?)\s*-\s*(\d{2})\s*-\s*(.+?)$",
        alt
    )

    if not match:
        return None

    name = clean(
        match.group(1)
    )

    overall = int(
        match.group(2)
    )

    version = clean(
        match.group(3)
    )

    return {
        "name": name,
        "overall": overall,
        "version": version,
    }


# ============================================================
# FINISH FROM CACHE
# ============================================================

def get_cached_finish(
    item_id,
    cache
):

    if not item_id:
        return None

    value = cache.get(
        str(item_id)
    )

    if isinstance(value, dict):
        value = value.get(
            "finish"
        )

    if value in (
        "BASE",
        "HOLO",
        "PRISTINE HOLO"
    ):
        return value

    return None


# ============================================================
# FINISH RESOLUTION
# ============================================================

def resolve_finish(
    item_id,
    card,
    category,
    cache,
    previous
):

    # 1. Item ID già verificato
    if item_id in KNOWN_FINISHES:

        return KNOWN_FINISHES[
            item_id
        ]

    # 2. Cache
    cached = get_cached_finish(
        item_id,
        cache
    )

    if cached:
        return cached

    # 3. Cerca lo stesso Item ID nello stato precedente
    for old_card in previous:

        if str(
            old_card.get("item_id", "")
        ) == str(item_id):

            old_finish = old_card.get(
                "finish"
            )

            if old_finish in (
                "BASE",
                "HOLO",
                "PRISTINE HOLO"
            ):
                return old_finish

    # 4. Se FUT.GG ci ha messo un'indicazione
    # esplicita negli attributi, la utilizziamo.
    #
    # Questo viene gestito dal chiamante quando
    # abbiamo il metadata.
    return None


# ============================================================
# EXTRACT CARDS
# ============================================================

def extract_cards(
    soup,
    category,
    previous,
    cache
):

    cards = []
    placeholder_count = 0

    images = soup.find_all(
        "img"
    )

    seen_image_keys = set()

    for img in images:

        alt = clean(
            img.get("alt")
        )

        src = clean(
            img.get("src")
        )

        # ----------------------------------------------------
        # PLACEHOLDER
        # ----------------------------------------------------

        if alt.lower() == "player card":

            placeholder_count += 1

            continue

        # ----------------------------------------------------
        # REAL CARD
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

            print(
                f"WARNING: Item ID mancante "
                f"per {alt}"
            )

            continue

        # Una stessa immagine può apparire
        # più volte nel DOM.
        image_key = (
            item_id,
            parsed["name"],
            parsed["overall"],
            parsed["version"]
        )

        if image_key in seen_image_keys:
            continue

        seen_image_keys.add(
            image_key
        )

        finish = resolve_finish(
            item_id,
            parsed,
            category,
            cache,
            previous
        )

        card = {
            "name": parsed["name"],
            "overall": parsed["overall"],
            "version": parsed["version"],
            "finish": finish,
            "item_id": str(item_id),
        }

        cards.append(
            card
        )

    return cards, placeholder_count


# ============================================================
# CARD KEY
# ============================================================

def card_key(card):

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
# DISPLAY
# ============================================================

def card_label(card):

    name = card.get(
        "name",
        "Unknown"
    )

    overall = card.get(
        "overall",
        "?"
    )

    finish = card.get(
        "finish"
    )

    if finish:
        return (
            f"{name} {overall} — "
            f"{finish}"
        )

    return (
        f"{name} {overall} — UNKNOWN"
    )


# ============================================================
# COMPARE
# ============================================================

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

    out = []
    incoming = []

    # OUT
    for key, count in (
        old_counter - new_counter
    ).items():

        for _ in range(count):

            for card in old_cards:

                if card_key(card) == key:

                    out.append(
                        card
                    )
                    break

    # IN
    for key, count in (
        new_counter - old_counter
    ).items():

        for _ in range(count):

            for card in new_cards:

                if card_key(card) == key:

                    incoming.append(
                        card
                    )
                    break

    return out, incoming


# ============================================================
# SAFE STATE CHECK
# ============================================================

def has_unknown_finish(cards):

    for card in cards:

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

    html = fetch(
        config["url"]
    )

    soup = find_lineup(
        html
    )

    cards, placeholders = extract_cards(
        soup,
        category,
        previous,
        cache
    )

    expected = config[
        "slots"
    ]

    print(
        f"Rendered lineup: "
        f"{len(cards)}/{expected} real cards"
    )

    if category == "Season 1":

        print(
            f"Unknown slots: "
            f"{placeholders}"
        )

    print(
        "Detected cards:"
    )

    for index, card in enumerate(
        cards,
        1
    ):

        print(
            f"  [{index}] "
            f"{card_label(card)} "
            f"ItemID={card['item_id']}"
        )

    # --------------------------------------------------------
    # VALIDATION
    # --------------------------------------------------------

    occupied_slots = (
        len(cards)
        + placeholders
    )

    if occupied_slots != expected:

        raise RuntimeError(
            f"Expected {expected} slots, "
            f"found {occupied_slots}"
        )

    # --------------------------------------------------------
    # UNKNOWN FINISH
    # --------------------------------------------------------

    unknown_finish = has_unknown_finish(
        cards
    )

    if unknown_finish:

        print()
        print(
            "WARNING:"
        )

        print(
            "One or more finishes could "
            "not be resolved."
        )

        print(
            "Previous state will be kept "
            "to avoid false OUT/IN."
        )

        return {
            "category": category,
            "cards": cards,
            "previous": previous,
            "out": [],
            "incoming": [],
            "safe": False,
            "placeholders": placeholders,
        }

    # --------------------------------------------------------
    # COMPARE
    # --------------------------------------------------------

    out, incoming = compare_cards(
        previous,
        cards
    )

    print(
        f"OUT: {len(out)}"
    )

    print(
        f"IN: {len(incoming)}"
    )

    # --------------------------------------------------------
    # UPDATE STATE
    # --------------------------------------------------------

    state[
        category
    ] = cards

    return {
        "category": category,
        "cards": cards,
        "previous": previous,
        "out": out,
        "incoming": incoming,
        "safe": True,
        "placeholders": placeholders,
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
# FORMAT TELEGRAM
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

    out = result[
        "out"
    ]

    incoming = result[
        "incoming"
    ]

    cards = result[
        "cards"
    ]

    safe = result[
        "safe"
    ]

    placeholders = result[
        "placeholders"
    ]

    # --------------------------------------------------------
    # UNKNOWN FINISH
    # --------------------------------------------------------

    if not safe:

        lines.append(
            "⚠️ Finish unresolved"
        )

        lines.append(
            "Previous state kept"
        )

        lines.append("")

        if category == "Season 1":

            lines.append(
                f"Empty/unknown slots: "
                f"{placeholders}"
            )

            lines.append("")

        return "\n".join(
            lines
        )

    # --------------------------------------------------------
    # OUT
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # IN
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # NO CHANGES
    # --------------------------------------------------------

    if not out and not incoming:

        lines.append(
            "No feed changes"
        )

        return "\n".join(
            lines
        )

    # --------------------------------------------------------
    # CURRENT LINEUP
    # --------------------------------------------------------

    lines.append(
        "Current lineup"
    )

    lines.append("")

    incoming_keys = Counter(
        card_key(card)
        for card in incoming
    )

    for card in cards:

        key = card_key(
            card
        )

        if incoming_keys[
            key
        ] > 0:

            lines.append(
                f"🟢 {card_label(card)}"
            )

            incoming_keys[
                key
            ] -= 1

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

    telegram_token = os.getenv(
        "TELEGRAM_BOT_TOKEN"
    )

    telegram_chat_id = os.getenv(
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
                f"ERROR on {category}: "
                f"{e}"
            )

            errors.append(
                (
                    category,
                    str(e)
                )
            )

    # --------------------------------------------------------
    # SAVE STATE
    # --------------------------------------------------------

    if not errors:

        save_json(
            PLAYERS_FILE,
            state
        )

    # --------------------------------------------------------
    # TELEGRAM MESSAGE
    # --------------------------------------------------------

    message_parts = []

    for result in results:

        message_parts.append(
            format_category(
                result
            )
        )

    # Errors
    for category, error in errors:

        emoji = PAGES[
            category
        ]["emoji"]

        message_parts.append(
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
            message_parts
        )
    )

    if telegram_token and telegram_chat_id:

        try:

            telegram_send(
                telegram_token,
                telegram_chat_id,
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

    else:

        print()
        print(
            "Telegram secrets not configured."
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

        cards = state.get(
            category,
            []
        )

        print(
            f"{category}: "
            f"{len(cards)} cards"
        )

        for card in cards:

            print(
                f"  - "
                f"{card_label(card)} "
                f"[{card.get('item_id')}]"
            )

    print()
    print(
        "Done."
    )


if __name__ == "__main__":
    main()