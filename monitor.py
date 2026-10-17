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
        "expected": 9,
    },
}

STATE_FILE = "players.json"
TRENDING_FILE = "docs/trending.json"
CARD_CACHE_FILE = "card_cache.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
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
# TEXT HELPERS
# ============================================================

def clean_text(value):
    if value is None:
        return ""

    value = str(value)

    value = (
        value
        .replace("\\u0026", "&")
        .replace("\\u002F", "/")
        .replace("\\/", "/")
        .replace("&amp;", "&")
    )

    return value.strip()


def normalize_name(name):
    return " ".join(
        clean_text(name).split()
    )


# ============================================================
# CARD CACHE
# ============================================================

def load_card_cache():
    if not os.path.exists(CARD_CACHE_FILE):
        return {}

    try:
        with open(
            CARD_CACHE_FILE,
            "r",
            encoding="utf-8",
        ) as file:
            data = json.load(file)

        if isinstance(data, dict):
            return data

    except Exception as error:
        print(
            f"⚠️ Could not load card cache: {error}"
        )

    return {}


def save_card_cache(cache):
    with open(
        CARD_CACHE_FILE,
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            cache,
            file,
            ensure_ascii=False,
            indent=2,
        )


CARD_CACHE = load_card_cache()


# ============================================================
# FIND CHEAPEST LINEUP
# ============================================================

def find_cheapest_heading(soup):
    pattern = re.compile(
        r"Cheapest\s+grade\s+.+?\s+lineup",
        re.IGNORECASE,
    )

    for tag in soup.find_all(
        [
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "div",
            "span",
        ]
    ):
        text = tag.get_text(
            " ",
            strip=True,
        )

        if pattern.fullmatch(text):
            return tag

    return None


def find_add_players_heading(soup):
    for tag in soup.find_all(
        [
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
        ]
    ):
        text = tag.get_text(
            " ",
            strip=True,
        )

        if text.lower() == "add players":
            return tag

    return None


def get_lineup_html(page_html):
    """
    Isola l'HTML compreso tra:

        Cheapest grade X lineup

    e:

        Add players

    Quindi NON usa solution.items.
    """

    soup = BeautifulSoup(
        page_html,
        "html.parser",
    )

    cheapest = find_cheapest_heading(
        soup
    )

    if cheapest is None:
        raise RuntimeError(
            "Could not find "
            "'Cheapest grade ... lineup'"
        )

    heading_text = cheapest.get_text(
        " ",
        strip=True,
    )

    print(
        f"Found section: {heading_text}"
    )

    raw_patterns = [
        re.compile(
            r"Cheapest\s+grade\s+"
            r"[^<]{1,30}\s+lineup",
            re.IGNORECASE,
        ),
        re.compile(
            re.escape(heading_text),
            re.IGNORECASE,
        ),
    ]

    start = None

    for pattern in raw_patterns:
        match = pattern.search(
            page_html
        )

        if match:
            start = match.start()
            break

    if start is None:
        raise RuntimeError(
            "Could not locate cheapest "
            "lineup inside raw HTML"
        )

    add_match = re.search(
        r">\s*Add players\s*<",
        page_html[start:],
        re.IGNORECASE,
    )

    if add_match:
        end = (
            start
            + add_match.start()
        )

        block = page_html[
            start:end
        ]

        print(
            f"Lineup HTML block: "
            f"{len(block):,} characters."
        )

        return block, heading_text

    add_heading = find_add_players_heading(
        soup
    )

    if add_heading is None:
        raise RuntimeError(
            "Could not find 'Add players'"
        )

    add_text = str(
        add_heading
    )

    add_position = page_html.find(
        add_text
    )

    if (
        add_position != -1
        and add_position > start
    ):
        block = page_html[
            start:add_position
        ]

        print(
            f"Lineup HTML block: "
            f"{len(block):,} characters."
        )

        return block, heading_text

    raise RuntimeError(
        "Could not isolate cheapest lineup HTML"
    )


# ============================================================
# PLAYER ALT
# ============================================================

def parse_player_alt(alt):
    """
    Esempi:

    Šašić - 89 - Base Hero
    Angerer - 92 - Base Icon
    Mora - 87 - Future Stars
    """

    alt = clean_text(
        alt
    )

    if not alt:
        return None

    if alt.lower() == "player card":
        return None

    match = re.match(
        r"^(.+?)\s+-\s+"
        r"(\d{2})\s+-\s+"
        r"(.+?)$",
        alt,
    )

    if not match:
        return None

    return {
        "name": normalize_name(
            match.group(1)
        ),
        "overall": int(
            match.group(2)
        ),
        "rarity": clean_text(
            match.group(3)
        ),
    }


# ============================================================
# ITEM ID
# ============================================================

def find_item_id_from_element(img):
    """
    Cerca l'Item ID della carta.

    Esempio:

    /27-67335170/
        ↓
    67335170
    """

    values = []

    for attribute in [
        "src",
        "srcset",
        "data-src",
        "data-original",
    ]:
        value = img.get(
            attribute
        )

        if value:
            values.append(
                str(value)
            )

    current = img

    for _ in range(6):
        if current is None:
            break

        if hasattr(current, "get"):
            href = current.get(
                "href"
            )

            if href:
                values.append(
                    str(href)
                )

        try:
            values.append(
                str(current)
            )
        except Exception:
            pass

        current = getattr(
            current,
            "parent",
            None,
        )

    patterns = [
        r"/27-(\d{5,12})/?",
        r"27-(\d{5,12})",
        r'item[_-]?id[=:"\']+(\d{5,12})',
        r'eaId[=:"\']+(\d{5,12})',
    ]

    for value in values:
        value = clean_text(
            value
        )

        for pattern in patterns:
            match = re.search(
                pattern,
                value,
                re.IGNORECASE,
            )

            if match:
                try:
                    return int(
                        match.group(1)
                    )
                except Exception:
                    pass

    return None


# ============================================================
# EXACT CARD URL
# ============================================================

def find_exact_card_url(
    gallery_html,
    item_id,
):
    """
    Cerca nella Gallery il link esatto della carta.

    Esempio:

    /players/226306-celia-sasic/27-67335170/
    """

    if not item_id:
        return None

    item_id = str(
        item_id
    )

    patterns = [
        (
            rf'https://www\.fut\.gg/'
            rf'players/[^"\']+/'
            rf'27-{re.escape(item_id)}/?'
        ),
        (
            rf'/players/[^"\']+/'
            rf'27-{re.escape(item_id)}/?'
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

        url = clean_text(
            match.group(0)
        )

        if url.startswith("/"):
            url = (
                "https://www.fut.gg"
                + url
            )

        if not url.endswith("/"):
            url += "/"

        return url

    return None


# ============================================================
# FINISH DETECTION
# ============================================================

def detect_finish_from_html(html):
    """
    Riconosce:

    PRISTINE HOLO
    HOLO
    BASE

    dalla pagina della carta specifica.
    """

    if not html:
        return "BASE"

    text = clean_text(
        html
    ).lower()

    # ========================================================
    # PRISTINE
    # ========================================================

    pristine_patterns = [
        "pristine holographic",
        "pristine-holographic",
        "pristine_holographic",
        "pristine holo",
        "pristine-holo",
        "pristine_holo",
    ]

    for pattern in pristine_patterns:
        if pattern in text:
            return "PRISTINE HOLO"

    # ========================================================
    # REGULAR HOLOGRAPHIC
    # ========================================================

    regular_patterns = [
        "regular holographic",
        "regular-holographic",
        "regular_holographic",
    ]

    for pattern in regular_patterns:
        if pattern in text:
            return "HOLO"

    return "BASE"


def resolve_card_finish(
    gallery_html,
    item_id,
):
    """
    Determina la finitura della carta.

    Prima controlla la cache.
    Se non presente:
      Item ID
        ↓
      URL carta
        ↓
      pagina FUT.GG
        ↓
      BASE / HOLO / PRISTINE HOLO
    """

    if not item_id:
        return "BASE"

    cache_key = str(
        item_id
    )

    # ========================================================
    # CACHE
    # ========================================================

    cached = CARD_CACHE.get(
        cache_key
    )

    if isinstance(
        cached,
        dict,
    ):
        finish = cached.get(
            "finish"
        )

        if finish in {
            "BASE",
            "HOLO",
            "PRISTINE HOLO",
        }:
            print(
                f"    ↳ finish cache: {finish}"
            )

            return finish

    elif cached in {
        "BASE",
        "HOLO",
        "PRISTINE HOLO",
    }:
        print(
            f"    ↳ finish cache: {cached}"
        )

        return cached

    # ========================================================
    # EXACT URL
    # ========================================================

    exact_url = find_exact_card_url(
        gallery_html,
        item_id,
    )

    if not exact_url:
        print(
            f"    ⚠️ Exact URL not found "
            f"for ItemID {item_id}"
        )

        return "BASE"

    print(
        f"    ↳ checking finish "
        f"ItemID={item_id}"
    )

    try:
        response = session.get(
            exact_url,
            timeout=30,
        )

        response.raise_for_status()

        finish = detect_finish_from_html(
            response.text
        )

        print(
            f"    ✓ finish: {finish}"
        )

        CARD_CACHE[
            cache_key
        ] = {
            "finish": finish,
            "url": exact_url,
        }

        return finish

    except Exception as error:
        print(
            f"    ⚠️ Finish lookup failed: "
            f"{error}"
        )

        return "BASE"


# ============================================================
# EXTRACT CHEAPEST LINEUP
# ============================================================

def extract_cheapest_lineup(
    page_html,
    page_name,
    expected,
):
    """
    Legge SOLO le carte visualizzate sotto:

        Cheapest grade X lineup

    NON legge solution.items.
    """

    block_html, heading = (
        get_lineup_html(
            page_html
        )
    )

    soup = BeautifulSoup(
        block_html,
        "html.parser",
    )

    players = []

    # ========================================================
    # NORMAL IMG EXTRACTION
    # ========================================================

    for img in soup.find_all("img"):
        alt = img.get(
            "alt",
            "",
        )

        info = parse_player_alt(
            alt
        )

        if not info:
            continue

        item_id = (
            find_item_id_from_element(
                img
            )
        )

        print(
            f"Resolving "
            f"{info['name']} "
            f"ItemID={item_id}..."
        )

        finish = resolve_card_finish(
            page_html,
            item_id,
        )

        card = {
            "name": info["name"],
            "overall": info["overall"],
            "rarity": info["rarity"],
            "version": finish,
            "ea_id": item_id,
        }

        players.append(
            card
        )

    # ========================================================
    # FALLBACK
    # ========================================================

    if len(players) < expected:
        print(
            "Normal IMG extraction returned "
            f"{len(players)}/{expected} cards."
        )

        print(
            "Trying raw HTML fallback..."
        )

        raw_pattern = re.compile(
            r'alt=["\']'
            r'([^"\']+?)\s+-\s+'
            r'(\d{2})\s+-\s+'
            r'([^"\']+?)'
            r'["\']',
            re.IGNORECASE,
        )

        raw_players = []

        for match in raw_pattern.finditer(
            block_html
        ):
            name = normalize_name(
                match.group(1)
            )

            overall = int(
                match.group(2)
            )

            rarity = clean_text(
                match.group(3)
            )

            start = max(
                0,
                match.start() - 2500,
            )

            end = min(
                len(block_html),
                match.end() + 2500,
            )

            context = block_html[
                start:end
            ]

            item_id = None

            id_patterns = [
                r"/27-(\d{5,12})/?",
                r"27-(\d{5,12})",
                r'eaId[=:"\']+(\d{5,12})',
            ]

            for id_pattern in id_patterns:
                id_match = re.search(
                    id_pattern,
                    context,
                    re.IGNORECASE,
                )

                if id_match:
                    item_id = int(
                        id_match.group(1)
                    )

                    break

            print(
                f"Resolving "
                f"{name} "
                f"ItemID={item_id}..."
            )

            finish = resolve_card_finish(
                page_html,
                item_id,
            )

            raw_players.append(
                {
                    "name": name,
                    "overall": overall,
                    "rarity": rarity,
                    "version": finish,
                    "ea_id": item_id,
                }
            )

        if len(raw_players) > len(players):
            players = raw_players

    # ========================================================
    # RESULT
    # ========================================================

    print(
        f"{heading}: "
        f"{len(players)}/{expected} cards."
    )

    for index, card in enumerate(
        players,
        start=1,
    ):
        item_text = (
            str(card["ea_id"])
            if card["ea_id"] is not None
            else "?"
        )

        print(
            f"{index}. "
            f"{card['name']} "
            f"{card['overall']} "
            f"{card['rarity']} "
            f"[{card['version']}] "
            f"ItemID={item_text}"
        )

    # ========================================================
    # SAFETY
    # ========================================================

    if len(players) != expected:
        raise RuntimeError(
            f"Wrong displayed lineup count "
            f"for {page_name}: "
            f"{len(players)}/{expected}"
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
                "players.json is invalid"
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

def escape_html(value):
    value = str(
        value
    )

    return (
        value
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


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
        "https://api.telegram.org/"
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
            f"⚠️ Telegram error: {error}"
        )

        return False


# ============================================================
# CARD IDENTITY
# ============================================================

def card_key(card):
    """
    L'Item ID distingue anche due versioni
    dello stesso giocatore.
    """

    ea_id = card.get(
        "ea_id"
    )

    if ea_id is not None:
        return (
            "EA",
            str(ea_id),
        )

    return (
        "CARD",
        normalize_name(
            card.get(
                "name",
                ""
            )
        ).casefold(),
        str(
            card.get(
                "overall",
                ""
            )
        ),
        str(
            card.get(
                "rarity",
                ""
            )
        ).casefold(),
        str(
            card.get(
                "version",
                ""
            )
        ).casefold(),
    )


# ============================================================
# COMPARE
# ============================================================

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

    removed = (
        old_counter
        - new_counter
    )

    added = (
        new_counter
        - old_counter
    )

    out_cards = []
    in_cards = []

    remaining_old = list(
        old_cards
    )

    remaining_new = list(
        new_cards
    )

    for key, count in removed.items():
        for _ in range(count):
            for index, card in enumerate(
                remaining_old
            ):
                if card_key(card) == key:
                    out_cards.append(
                        card
                    )

                    remaining_old.pop(
                        index
                    )

                    break

    for key, count in added.items():
        for _ in range(count):
            for index, card in enumerate(
                remaining_new
            ):
                if card_key(card) == key:
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
# FORMAT CARD
# ============================================================

def format_card(card):
    name = escape_html(
        card.get(
            "name",
            "Unknown",
        )
    )

    overall = card.get(
        "overall",
        "?",
    )

    rarity = escape_html(
        card.get(
            "rarity",
            "",
        )
    )

    version = card.get(
        "version",
        "BASE",
    )

    if version == "PRISTINE HOLO":
        finish = "✨ PRISTINE HOLO"

    elif version == "HOLO":
        finish = "🌈 HOLO"

    else:
        finish = "BASE"

    return (
        f"{name} "
        f"{overall} "
        f"<b>{rarity}</b> "
        f"— {finish}"
    )


# ============================================================
# MAIN
# ============================================================

def main():
    print(
        "=" * 60
    )

    print(
        "FUT.GG CHEAPEST LINEUP MONITOR"
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
            # CHEAPEST DISPLAYED LINEUP
            # =================================================

            players = (
                extract_cheapest_lineup(
                    page_html,
                    page_name,
                    config["expected"],
                )
            )

            old_players = state.get(
                page_name,
                [],
            )

            # =================================================
            # FIRST STATE
            # =================================================

            if not old_players:
                print(
                    f"🆕 First state saved "
                    f"for {page_name}."
                )

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
                        f"⚡ <b>"
                        f"{escape_html(page_name)}"
                        f"</b>\n"
                        f"Cheapest lineup changed"
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

                    message += (
                        '<a href="'
                        + config["url"]
                        + '">'
                        + "Open FUT.GG lineup"
                        + "</a>"
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
                        "No lineup changes."
                    )

            # =================================================
            # UPDATE ONLY SUCCESSFUL PAGE
            # =================================================

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
                "⚠️ <b>FUT.GG Monitor Error</b>"
                "\n\n"
                f"<b>"
                f"{escape_html(page_name)}"
                f"</b>"
                "\n"
                f"{escape_html(error)}"
            )

            print(
                f"Previous state for "
                f"{page_name} preserved."
            )

    # ========================================================
    # SAVE
    # ========================================================

    if successful_pages == 0:
        print()

        print(
            "❌ 0 pages succeeded."
        )

        print(
            "players.json NOT overwritten."
        )

        return

    save_state(
        state
    )

    save_trending(
        state
    )

    save_card_cache(
        CARD_CACHE
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
        f"Saved {CARD_CACHE_FILE}"
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