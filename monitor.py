import os
import re
import json
import html
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

PAGE_EMOJIS = {
    "Heroes": "🦸‍♂️",
    "Holographics": "✨️",
    "Season 1": "1️⃣",
}

PLAYERS_FILE = "players.json"
TRENDING_FILE = "docs/trending.json"
CACHE_FILE = "card_cache.json"

CACHE_VERSION = 2

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


# ============================================================
# JSON
# ============================================================

def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, data):
    directory = os.path.dirname(path)

    if directory:
        os.makedirs(directory, exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2,
        )


# ============================================================
# DOWNLOAD
# ============================================================

def download_page(url):
    response = requests.get(
        url,
        headers=HEADERS,
        timeout=30,
    )

    response.raise_for_status()

    return response.text


# ============================================================
# LINEUP HTML
# ============================================================

def get_lineup_html(page_html):
    """
    Manteniamo una ricerca molto più flessibile.

    FUT.GG può cambiare maiuscole/minuscole,
    spazi, HTML o testo attorno alla lineup.
    """

    soup = BeautifulSoup(
        page_html,
        "html.parser",
    )

    # --------------------------------------------------------
    # 1. Cerca direttamente il testo nella pagina
    # --------------------------------------------------------

    candidates = []

    for element in soup.find_all(
        string=re.compile(
            r"cheapest\s+grade.*lineup",
            re.IGNORECASE,
        )
    ):
        candidates.append(element)

    if candidates:
        target = candidates[0]

        # Risali fino a un contenitore abbastanza grande
        parent = target.parent

        for _ in range(8):
            if parent is None:
                break

            text = parent.get_text(
                " ",
                strip=True,
            )

            if (
                "Add players" in text
                or "add players" in text.lower()
            ):
                return str(parent)

            parent = parent.parent

        # Se non troviamo Add players,
        # prendiamo comunque il contenitore
        if target.parent:
            return str(target.parent)

    # --------------------------------------------------------
    # 2. Fallback sul raw HTML
    # --------------------------------------------------------

    lower = page_html.lower()

    patterns = [
        r"cheapest\s+grade\s+\d+\s+lineup",
        r"cheapest\s+grade\s+lineup",
        r"cheapest\s+grade.{0,100}lineup",
    ]

    start = -1

    for pattern in patterns:
        match = re.search(
            pattern,
            lower,
            re.IGNORECASE,
        )

        if match:
            start = match.start()
            break

    if start == -1:
        # Ultimo fallback:
        # cerca solamente "lineup"
        match = re.search(
            r"lineup",
            lower,
            re.IGNORECASE,
        )

        if match:
            start = max(
                0,
                match.start() - 5000,
            )

    if start == -1:
        raise RuntimeError(
            "Could not find lineup section"
        )

    end = lower.find(
        "add players",
        start,
    )

    if end == -1:
        end = min(
            start + 250000,
            len(page_html),
        )

    return page_html[start:end]


# ============================================================
# PLAYER ALT
# ============================================================

def parse_player_alt(alt):
    if not alt:
        return None

    alt = " ".join(
        alt.split()
    ).strip()

    match = re.match(
        r"^(.*?)\s*-\s*(\d{2})\s*-\s*(.+?)\s*$",
        alt,
    )

    if not match:
        return None

    return {
        "name": match.group(1).strip(),
        "overall": int(match.group(2)),
        "rarity": match.group(3).strip(),
    }


# ============================================================
# ITEM ID
# ============================================================

def find_item_id_from_element(element):
    if element is None:
        return None

    # --------------------------------------------------------
    # Cerca nei link
    # --------------------------------------------------------

    for a in element.find_all(
        "a",
        href=True,
    ):
        href = a.get("href", "")

        match = re.search(
            r"/27-(\d+)/?",
            href,
            re.IGNORECASE,
        )

        if match:
            return match.group(1)

    # --------------------------------------------------------
    # Cerca attributi
    # --------------------------------------------------------

    attributes = [
        "item_id",
        "itemid",
        "itemId",
        "eaId",
        "eaid",
        "player_id",
        "playerId",
    ]

    for node in [
        element,
        *element.find_all(True),
    ]:
        for attribute in attributes:
            value = node.get(
                attribute
            )

            if value is None:
                continue

            match = re.search(
                r"\d+",
                str(value),
            )

            if match:
                return match.group(0)

    # --------------------------------------------------------
    # Cerca nell'HTML
    # --------------------------------------------------------

    raw = str(element)

    patterns = [
        r"/27-(\d+)/?",
        r'"itemId"\s*:\s*"?(\\?\d+)',
        r'"item_id"\s*:\s*"?(\\?\d+)',
        r'"eaId"\s*:\s*"?(\\?\d+)',
        r'"ea_id"\s*:\s*"?(\\?\d+)',
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            raw,
            re.IGNORECASE,
        )

        if match:
            return match.group(1).replace(
                "\\",
                "",
            )

    return None


# ============================================================
# EXACT CARD URL
# ============================================================

def find_exact_card_url(
    page_html,
    item_id,
):
    if not item_id:
        return None

    pattern = re.compile(
        rf"/players/[^\"']*/27-{re.escape(str(item_id))}/?",
        re.IGNORECASE,
    )

    soup = BeautifulSoup(
        page_html,
        "html.parser",
    )

    for a in soup.find_all(
        "a",
        href=True,
    ):
        href = a.get("href", "")

        match = pattern.search(href)

        if match:
            url = match.group(0)

            if url.startswith("/"):
                url = (
                    "https://www.fut.gg"
                    + url
                )

            return url

    match = pattern.search(
        page_html
    )

    if match:
        return (
            "https://www.fut.gg"
            + match.group(0)
        )

    return None


# ============================================================
# FINISH DETECTION
# ============================================================

def detect_finish_from_card_page(
    card_html
):
    soup = BeautifulSoup(
        card_html,
        "html.parser",
    )

    texts = []

    # H1
    h1 = soup.find("h1")

    if h1:
        texts.append(
            h1.get_text(
                " ",
                strip=True,
            )
        )

    # OG title
    meta = soup.find(
        "meta",
        attrs={
            "property": "og:title"
        },
    )

    if meta and meta.get("content"):
        texts.append(
            meta.get("content")
        )

    # HTML title
    if soup.title:
        texts.append(
            soup.title.get_text(
                " ",
                strip=True,
            )
        )

    combined = " ".join(
        texts
    ).lower()

    # IMPORTANT:
    # PRISTINE prima di HOLO
    if (
        "pristine holographic" in combined
        or "pristine holo" in combined
    ):
        return "PRISTINE HOLO"

    if (
        "holographic" in combined
        or " holographic " in f" {combined} "
    ):
        return "HOLO"

    return "BASE"


def resolve_card_finish(
    card_url,
    cache,
):
    if not card_url:
        return "BASE"

    match = re.search(
        r"/27-(\d+)/?",
        card_url,
        re.IGNORECASE,
    )

    if not match:
        return "BASE"

    item_id = match.group(1)

    if (
        cache.get("cache_version")
        == CACHE_VERSION
    ):
        cached = (
            cache
            .get("cards", {})
            .get(item_id)
        )

        if cached in {
            "BASE",
            "HOLO",
            "PRISTINE HOLO",
        }:
            return cached

    try:
        response = requests.get(
            card_url,
            headers=HEADERS,
            timeout=30,
        )

        response.raise_for_status()

        finish = detect_finish_from_card_page(
            response.text
        )

        cache["cache_version"] = CACHE_VERSION
        cache.setdefault(
            "cards",
            {},
        )

        cache["cards"][item_id] = finish

        return finish

    except Exception as e:
        print(
            f"  Finish error: {e}"
        )

        return "BASE"


# ============================================================
# EXTRACT LINEUP
# ============================================================

def extract_cheapest_lineup(
    page_html,
    expected_count,
):
    lineup_html = get_lineup_html(
        page_html
    )

    soup = BeautifulSoup(
        lineup_html,
        "html.parser",
    )

    players = []

    # --------------------------------------------------------
    # IMG ALT
    # --------------------------------------------------------

    for img in soup.find_all("img"):
        alt = img.get("alt")

        parsed = parse_player_alt(
            alt
        )

        if not parsed:
            continue

        # Cerca l'ID partendo dal parent
        element = img

        item_id = None

        for _ in range(8):
            if element is None:
                break

            item_id = find_item_id_from_element(
                element
            )

            if item_id:
                break

            element = element.parent

        players.append(
            {
                **parsed,
                "item_id": item_id,
            }
        )

    # --------------------------------------------------------
    # NON rimuoviamo duplicati reali.
    #
    # Le carte duplicate devono rimanere.
    # --------------------------------------------------------

    if len(players) == expected_count:
        return players

    # --------------------------------------------------------
    # FALLBACK REGEX
    # --------------------------------------------------------

    pattern = re.compile(
        r'alt=["\']([^"\']+?)\s*-\s*(\d{2})\s*-\s*([^"\']+)["\']',
        re.IGNORECASE,
    )

    fallback = []

    for match in pattern.finditer(
        lineup_html
    ):
        name = match.group(1).strip()
        overall = int(
            match.group(2)
        )
        rarity = match.group(3).strip()

        nearby_start = max(
            0,
            match.start() - 8000,
        )

        nearby_end = min(
            len(lineup_html),
            match.end() + 8000,
        )

        nearby = lineup_html[
            nearby_start:nearby_end
        ]

        id_match = re.search(
            r"/27-(\d+)/?",
            nearby,
            re.IGNORECASE,
        )

        item_id = (
            id_match.group(1)
            if id_match
            else None
        )

        fallback.append(
            {
                "name": name,
                "overall": overall,
                "rarity": rarity,
                "item_id": item_id,
            }
        )

    if len(fallback) == expected_count:
        return fallback

    return players


# ============================================================
# CARD KEY
# ============================================================

def card_key(card):
    item_id = card.get(
        "item_id"
    )

    if item_id:
        return (
            f"item:{item_id}"
        )

    return (
        f"name:{card.get('name', '')}"
        f"|overall:{card.get('overall', '')}"
        f"|rarity:{card.get('rarity', '')}"
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

    old_by_key = {}

    for card in old_cards:
        key = card_key(card)

        old_by_key.setdefault(
            key,
            [],
        ).append(card)

    new_by_key = {}

    for card in new_cards:
        key = card_key(card)

        new_by_key.setdefault(
            key,
            [],
        ).append(card)

    out_cards = []
    in_cards = []

    # OUT
    for key, count in old_counter.items():
        difference = (
            count
            - new_counter.get(
                key,
                0,
            )
        )

        if difference > 0:
            out_cards.extend(
                old_by_key[key][
                    :difference
                ]
            )

    # IN
    for key, count in new_counter.items():
        difference = (
            count
            - old_counter.get(
                key,
                0,
            )
        )

        if difference > 0:
            in_cards.extend(
                new_by_key[key][
                    :difference
                ]
            )

    return (
        out_cards,
        in_cards,
    )


# ============================================================
# CARD FORMAT
# ============================================================

def format_card_vertical(card):
    name = html.escape(
        str(
            card.get(
                "name",
                "Unknown",
            )
        )
    )

    overall = html.escape(
        str(
            card.get(
                "overall",
                "?",
            )
        )
    )

    version = html.escape(
        str(
            card.get(
                "version",
                "BASE",
            )
        )
    )

    return (
        f"{name} {overall}\n"
        f"{version}"
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
            "Telegram credentials not configured."
        )
        return False

    url = (
        "https://api.telegram.org/"
        f"bot{token}/sendMessage"
    )

    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    try:
        response = requests.post(
            url,
            json=payload,
            timeout=30,
        )

        response.raise_for_status()

        print(
            "Telegram notification sent."
        )

        return True

    except Exception as e:
        print(
            f"Telegram error: {e}"
        )

        return False


# ============================================================
# TELEGRAM CATEGORY
# ============================================================

def build_category_section(
    page_name,
    config,
    players,
    out_cards,
    in_cards,
    error=None,
):
    emoji = PAGE_EMOJIS[
        page_name
    ]

    title = (
        f"{emoji} "
        f"<b>{html.escape(page_name)}</b>"
    )

    # --------------------------------------------------------
    # ERROR
    # --------------------------------------------------------

    if error:
        return (
            f"{title}\n\n"
            f"⚠️ <b>Feed error</b>\n"
            f"{html.escape(str(error))}"
        )

    parts = [
        title
    ]

    # --------------------------------------------------------
    # OUT
    # --------------------------------------------------------

    if out_cards:
        parts.append(
            "🔴 <b>OUT</b>\n\n"
            + "\n\n".join(
                "• "
                + format_card_vertical(card)
                for card in out_cards
            )
        )

    # --------------------------------------------------------
    # IN
    # --------------------------------------------------------

    if in_cards:
        parts.append(
            "🟢 <b>IN</b>\n\n"
            + "\n\n".join(
                "• "
                + format_card_vertical(card)
                for card in in_cards
            )
        )

    # --------------------------------------------------------
    # NO CHANGE
    # --------------------------------------------------------

    if not out_cards and not in_cards:
        parts.append(
            "No feed changes"
        )

        if players:
            parts.append(
                "\n\n".join(
                    format_card_vertical(
                        card
                    )
                    for card in players
                )
            )

    # --------------------------------------------------------
    # LINK
    # --------------------------------------------------------

    parts.append(
        f'<a href="{html.escape(config["url"])}">'
        f"Open FUT.GG"
        f"</a>"
    )

    return "\n\n".join(
        parts
    )


# ============================================================
# MAIN
# ============================================================

def main():
    print(
        "FUT.GG MONITOR"
    )

    print(
        "=" * 60
    )

    players_state = load_json(
        PLAYERS_FILE,
        {
            "Heroes": [],
            "Holographics": [],
            "Season 1": [],
        },
    )

    trending_state = load_json(
        TRENDING_FILE,
        {
            "updated_at": 0,
            "pages": {
                "Heroes": [],
                "Holographics": [],
                "Season 1": [],
            },
        },
    )

    cache = load_json(
        CACHE_FILE,
        {},
    )

    # --------------------------------------------------------
    # CACHE
    # --------------------------------------------------------

    if (
        cache.get("cache_version")
        != CACHE_VERSION
    ):
        print(
            "Cache version mismatch. "
            "Resetting finish cache."
        )

        cache = {
            "cache_version": CACHE_VERSION,
            "cards": {},
        }

    telegram_sections = []

    successful_updates = {}

    any_real_change = False

    # ========================================================
    # SCAN
    # ========================================================

    for page_name, config in PAGES.items():

        print()
        print(
            f"Scanning 🏆 "
            f"{page_name.upper()}"
        )

        print(
            config["url"]
        )

        print(
            "=" * 60
        )

        old_players = players_state.get(
            page_name,
            [],
        )

        try:
            # ------------------------------------------------
            # DOWNLOAD
            # ------------------------------------------------

            page_html = download_page(
                config["url"]
            )

            # ------------------------------------------------
            # EXTRACT
            # ------------------------------------------------

            players = extract_cheapest_lineup(
                page_html,
                config["expected"],
            )

            print(
                f"Found {len(players)} "
                f"unique players."
            )

            # ------------------------------------------------
            # CHECK COUNT
            # ------------------------------------------------

            if len(players) != config["expected"]:
                raise RuntimeError(
                    f"Expected "
                    f"{config['expected']} cards, "
                    f"found {len(players)}"
                )

            # ------------------------------------------------
            # FINISH
            # ------------------------------------------------

            for index, player in enumerate(
                players,
                start=1,
            ):
                item_id = player.get(
                    "item_id"
                )

                card_url = find_exact_card_url(
                    page_html,
                    item_id,
                )

                finish = resolve_card_finish(
                    card_url,
                    cache,
                )

                player["version"] = finish

                print(
                    f"{index}. "
                    f"{player['name']} "
                    f"{player['overall']} "
                    f"{player['rarity']} "
                    f"[{finish}] "
                    f"ItemID={item_id}"
                )

            # ------------------------------------------------
            # COMPARE
            # ------------------------------------------------

            out_cards, in_cards = compare_cards(
                old_players,
                players,
            )

            if out_cards or in_cards:
                any_real_change = True

            # ------------------------------------------------
            # SAVE IN MEMORY
            # ------------------------------------------------

            successful_updates[
                page_name
            ] = players

            # ------------------------------------------------
            # TELEGRAM
            # ------------------------------------------------

            section = build_category_section(
                page_name,
                config,
                players,
                out_cards,
                in_cards,
            )

            telegram_sections.append(
                section
            )

            # ------------------------------------------------
            # LOG
            # ------------------------------------------------

            if out_cards:
                print()
                print(
                    "OUT:"
                )

                for card in out_cards:
                    print(
                        "- "
                        f"{card.get('name')} "
                        f"{card.get('overall')} "
                        f"["
                        f"{card.get('version', 'BASE')}"
                        f"]"
                    )

            if in_cards:
                print()
                print(
                    "IN:"
                )

                for card in in_cards:
                    print(
                        "+ "
                        f"{card.get('name')} "
                        f"{card.get('overall')} "
                        f"["
                        f"{card.get('version', 'BASE')}"
                        f"]"
                    )

            if (
                not out_cards
                and not in_cards
            ):
                print(
                    "No feed changes."
                )

        except Exception as e:

            print(
                f"ERROR on "
                f"{page_name}: {e}"
            )

            # IMPORTANTE:
            # manteniamo il vecchio stato.

            section = build_category_section(
                page_name,
                config,
                [],
                [],
                [],
                error=e,
            )

            telegram_sections.append(
                section
            )

    # ========================================================
    # UPDATE STATE
    # ========================================================

    for page_name, players in (
        successful_updates.items()
    ):
        players_state[
            page_name
        ] = players

        trending_state.setdefault(
            "pages",
            {},
        )

        trending_state[
            "pages"
        ][page_name] = players

    trending_state[
        "updated_at"
    ] = int(time.time())

    # ========================================================
    # SAVE
    # ========================================================

    save_json(
        PLAYERS_FILE,
        players_state,
    )

    save_json(
        TRENDING_FILE,
        trending_state,
    )

    save_json(
        CACHE_FILE,
        cache,
    )

    # ========================================================
    # ONE TELEGRAM MESSAGE
    # ========================================================

    separator = (
        "\n\n"
        "------------------------------"
        "\n\n"
    )

    message = separator.join(
        telegram_sections
    )

    telegram_send(
        message
    )

    # ========================================================
    # RESULT
    # ========================================================

    print()
    print(
        "=" * 60
    )

    if any_real_change:
        print(
            "RESULT: FEED CHANGED"
        )
    else:
        print(
            "RESULT: NO FEED CHANGES"
        )

    print(
        "Telegram: 1 combined message"
    )

    print(
        "=" * 60
    )


if __name__ == "__main__":
    main()