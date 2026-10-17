import os
import re
import json
import html
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
# FILE HELPERS
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
        json.dump(data, f, ensure_ascii=False, indent=2)


# ============================================================
# HTML DOWNLOAD
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
# LINEUP EXTRACTION
# ============================================================

def get_lineup_html(page_html):
    """
    Isola solamente la parte della pagina relativa a:

        Cheapest grade X lineup

    fino a:

        Add players

    Questo evita di prendere giocatori presenti
    in altre sezioni della pagina.
    """

    lower = page_html.lower()

    start_candidates = [
        lower.find("cheapest grade 10 lineup"),
        lower.find("cheapest grade 9 lineup"),
        lower.find("cheapest grade 8 lineup"),
        lower.find("cheapest grade 7 lineup"),
        lower.find("cheapest grade 6 lineup"),
        lower.find("cheapest grade 5 lineup"),
        lower.find("cheapest grade 4 lineup"),
        lower.find("cheapest grade 3 lineup"),
        lower.find("cheapest grade 2 lineup"),
        lower.find("cheapest grade 1 lineup"),
        lower.find("cheapest grade lineup"),
    ]

    start_candidates = [
        x for x in start_candidates
        if x != -1
    ]

    if not start_candidates:
        raise RuntimeError(
            "Could not find 'Cheapest grade X lineup'"
        )

    start = min(start_candidates)

    end = lower.find("add players", start)

    if end == -1:
        # fallback: prendiamo una porzione abbastanza ampia
        end = min(start + 250000, len(page_html))

    return page_html[start:end]


# ============================================================
# PLAYER NAME / RATING / RARITY
# ============================================================

def parse_player_alt(alt):
    """
    Esempio:

        Celia Šašić - 89 - Base Hero

    oppure:

        Mora - 87 - Future Stars
    """

    if not alt:
        return None

    alt = " ".join(alt.split()).strip()

    match = re.match(
        r"^(.*?)\s*-\s*(\d{2})\s*-\s*(.+?)\s*$",
        alt,
    )

    if not match:
        return None

    name = match.group(1).strip()
    overall = int(match.group(2))
    rarity = match.group(3).strip()

    return {
        "name": name,
        "overall": overall,
        "rarity": rarity,
    }


# ============================================================
# ITEM ID
# ============================================================

def find_item_id_from_element(element):
    """
    Cerca l'Item ID direttamente nell'elemento
    o nei suoi attributi/link.
    """

    # --------------------------------------------------------
    # 1. Cerca URL del player
    # --------------------------------------------------------

    for a in element.find_all("a", href=True):
        href = a.get("href", "")

        match = re.search(
            r"/27-(\d+)/?",
            href,
            re.IGNORECASE,
        )

        if match:
            return match.group(1)

    # --------------------------------------------------------
    # 2. Cerca attributi comuni
    # --------------------------------------------------------

    possible_attributes = [
        "item_id",
        "itemid",
        "itemId",
        "eaid",
        "eaId",
        "player_id",
        "playerId",
    ]

    for node in [element] + element.find_all(True):
        for attr in possible_attributes:
            value = node.get(attr)

            if value is None:
                continue

            match = re.search(
                r"\d+",
                str(value),
            )

            if match:
                return match.group(0)

    # --------------------------------------------------------
    # 3. Cerca nel testo HTML dell'elemento
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
            return match.group(1).replace("\\", "")

    return None


# ============================================================
# EXACT CARD URL
# ============================================================

def find_exact_card_url(page_html, item_id):
    """
    Trova l'URL preciso della carta.

    Esempio:

    /players/226306-celia-sasic/27-67335170/
    """

    if not item_id:
        return None

    soup = BeautifulSoup(
        page_html,
        "html.parser",
    )

    pattern = re.compile(
        rf"/players/[^\"']*/27-{re.escape(str(item_id))}/?",
        re.IGNORECASE,
    )

    # Prima cerca negli href
    for a in soup.find_all("a", href=True):
        href = a.get("href", "")

        match = pattern.search(href)

        if match:
            return "https://www.fut.gg" + match.group(0)

    # Fallback sul raw HTML
    match = pattern.search(page_html)

    if match:
        return "https://www.fut.gg" + match.group(0)

    return None


# ============================================================
# CARD FINISH
# ============================================================

def detect_finish_from_card_page(card_html):
    """
    Determina:

        BASE
        HOLO
        PRISTINE HOLO

    usando solamente le informazioni della pagina
    della carta specifica.
    """

    soup = BeautifulSoup(
        card_html,
        "html.parser",
    )

    texts = []

    # H1
    h1 = soup.find("h1")

    if h1:
        texts.append(h1.get_text(" ", strip=True))

    # OG title
    meta = soup.find(
        "meta",
        attrs={
            "property": "og:title"
        },
    )

    if meta and meta.get("content"):
        texts.append(meta["content"])

    # HTML title
    if soup.title:
        texts.append(
            soup.title.get_text(
                " ",
                strip=True,
            )
        )

    combined = " ".join(texts).lower()

    # IMPORTANTISSIMO:
    # pristine holographic deve essere controllato
    # prima di holographic.
    if (
        "pristine holographic" in combined
        or "pristine holo" in combined
    ):
        return "PRISTINE HOLO"

    if (
        "holographic" in combined
        or " holo" in combined
    ):
        return "HOLO"

    return "BASE"


def resolve_card_finish(
    card_url,
    cache,
):
    """
    Usa la cache solamente per il finish.

    La cache NON viene usata per decidere
    se una carta è IN o OUT.
    """

    if not card_url:
        return "BASE"

    item_id_match = re.search(
        r"/27-(\d+)/?",
        card_url,
        re.IGNORECASE,
    )

    if not item_id_match:
        return "BASE"

    item_id = item_id_match.group(1)

    cache_version = cache.get("cache_version")

    if cache_version == CACHE_VERSION:
        cached = cache.get("cards", {}).get(item_id)

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

        if "cache_version" not in cache:
            cache.clear()

        cache["cache_version"] = CACHE_VERSION
        cache.setdefault("cards", {})
        cache["cards"][item_id] = finish

        return finish

    except Exception as e:
        print(
            f"  Finish error for {card_url}: {e}"
        )

        return "BASE"


# ============================================================
# EXTRACT CHEAPEST LINEUP
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
    # Prima scelta: immagini con alt
    # --------------------------------------------------------

    for img in soup.find_all("img"):
        alt = img.get("alt")

        parsed = parse_player_alt(alt)

        if not parsed:
            continue

        item_id = find_item_id_from_element(
            img.parent if img.parent else img
        )

        if not item_id:
            item_id = find_item_id_from_element(
                img
            )

        players.append(
            {
                **parsed,
                "item_id": item_id,
            }
        )

    # --------------------------------------------------------
    # Rimuovi duplicati IDENTICI solo se il parser
    # ha trovato esattamente gli stessi nodi.
    #
    # Le carte duplicate reali devono invece rimanere.
    # --------------------------------------------------------

    cleaned = []

    seen_signatures = set()

    for player in players:
        signature = (
            player.get("name"),
            player.get("overall"),
            player.get("rarity"),
            player.get("item_id"),
        )

        if signature in seen_signatures:
            continue

        seen_signatures.add(signature)
        cleaned.append(player)

    players = cleaned

    # --------------------------------------------------------
    # Se abbiamo trovato il numero corretto, usiamo questo.
    # --------------------------------------------------------

    if len(players) == expected_count:
        return players

    # --------------------------------------------------------
    # FALLBACK regex
    # --------------------------------------------------------

    fallback_pattern = re.compile(
        r'alt=["\']([^"\']+?)\s*-\s*(\d{2})\s*-\s*([^"\']+)["\']',
        re.IGNORECASE,
    )

    fallback = []

    for match in fallback_pattern.finditer(
        lineup_html
    ):
        name = match.group(1).strip()
        overall = int(match.group(2))
        rarity = match.group(3).strip()

        # Cerchiamo l'ID vicino al match
        surrounding_start = max(
            0,
            match.start() - 5000,
        )

        surrounding_end = min(
            len(lineup_html),
            match.end() + 5000,
        )

        surrounding = lineup_html[
            surrounding_start:surrounding_end
        ]

        id_match = re.search(
            r"/27-(\d+)/?",
            surrounding,
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

    # Se il fallback ha il numero giusto, usalo
    if len(fallback) == expected_count:
        return fallback

    # --------------------------------------------------------
    # Se nessuno dei due coincide, restituiamo comunque
    # il risultato principale: il chiamante farà fallire
    # la pagina invece di sovrascrivere dati buoni.
    # --------------------------------------------------------

    return players


# ============================================================
# CARD IDENTITY
# ============================================================

def card_key(card):
    """
    L'Item ID è l'identità principale della carta.

    Questo significa che un semplice cambio di label
    BASE/HOLO non genera falsi OUT/IN.
    """

    item_id = card.get("item_id")

    if item_id:
        return f"item:{item_id}"

    return (
        f"name:{card.get('name', '')}"
        f"|overall:{card.get('overall', '')}"
        f"|rarity:{card.get('rarity', '')}"
    )


# ============================================================
# COMPARE
# ============================================================

def compare_cards(old_cards, new_cards):
    """
    Confronto che:

    - ignora l'ordine
    - mantiene i duplicati
    - trova OUT
    - trova IN
    """

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
        old_by_key.setdefault(
            card_key(card),
            []
        ).append(card)

    new_by_key = {}

    for card in new_cards:
        new_by_key.setdefault(
            card_key(card),
            []
        ).append(card)

    out_cards = []
    in_cards = []

    # OUT
    for key, count in old_counter.items():
        difference = count - new_counter.get(
            key,
            0,
        )

        if difference > 0:
            out_cards.extend(
                old_by_key[key][:difference]
            )

    # IN
    for key, count in new_counter.items():
        difference = count - old_counter.get(
            key,
            0,
        )

        if difference > 0:
            in_cards.extend(
                new_by_key[key][:difference]
            )

    return out_cards, in_cards


# ============================================================
# CARD FORMAT
# ============================================================

def format_card_vertical(card):
    """
    Formato:

    Nome Overall
    VERSIONE
    """

    name = html.escape(
        str(card.get("name", "Unknown"))
    )

    overall = html.escape(
        str(card.get("overall", "?"))
    )

    version = html.escape(
        str(card.get("version", "BASE"))
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
        f"https://api.telegram.org/"
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

        print("Telegram notification sent.")

        return True

    except Exception as e:
        print(
            f"Telegram error: {e}"
        )

        return False


# ============================================================
# TELEGRAM SECTION
# ============================================================

def build_category_section(
    page_name,
    config,
    players,
    out_cards,
    in_cards,
    error=None,
):
    emoji = PAGE_EMOJIS.get(
        page_name,
        "",
    )

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

    # --------------------------------------------------------
    # CHANGED
    # --------------------------------------------------------

    parts = [title]

    if out_cards:
        parts.append(
            "🔴 <b>OUT</b>\n\n"
            + "\n\n".join(
                "• " + format_card_vertical(card)
                for card in out_cards
            )
        )

    if in_cards:
        parts.append(
            "🟢 <b>IN</b>\n\n"
            + "\n\n".join(
                "• " + format_card_vertical(card)
                for card in in_cards
            )
        )

    # --------------------------------------------------------
    # NO CHANGE
    # --------------------------------------------------------

    if not out_cards and not in_cards:
        parts.append(
            "No feed changes."
        )

        if players:
            parts.append(
                "\n\n".join(
                    format_card_vertical(card)
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

    return "\n\n".join(parts)


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 60)
    print("FUT.GG MONITOR")
    print("=" * 60)

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

    if cache.get("cache_version") != CACHE_VERSION:
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
    # SCAN ALL PAGES
    # ========================================================

    for page_name, config in PAGES.items():
        print()
        print(
            f"Scanning 🏆 {page_name.upper()}"
        )

        print(config["url"])
        print("=" * 60)

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
                f"players."
            )

            # ------------------------------------------------
            # VALIDATE COUNT
            # ------------------------------------------------

            if len(players) != config["expected"]:
                raise RuntimeError(
                    f"Expected "
                    f"{config['expected']} cards, "
                    f"found {len(players)}."
                )

            # ------------------------------------------------
            # RESOLVE FINISH
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
            # SAVE SUCCESSFUL STATE
            # ------------------------------------------------

            successful_updates[page_name] = players

            # ------------------------------------------------
            # TELEGRAM SECTION
            # ------------------------------------------------

            section = build_category_section(
                page_name=page_name,
                config=config,
                players=players,
                out_cards=out_cards,
                in_cards=in_cards,
            )

            telegram_sections.append(
                section
            )

            # ------------------------------------------------
            # LOG CHANGES
            # ------------------------------------------------

            if out_cards:
                print()
                print("OUT:")

                for card in out_cards:
                    print(
                        f"- "
                        f"{card['name']} "
                        f"{card['overall']} "
                        f"[{card.get('version', 'BASE')}]"
                    )

            if in_cards:
                print()
                print("IN:")

                for card in in_cards:
                    print(
                        f"+ "
                        f"{card['name']} "
                        f"{card['overall']} "
                        f"[{card.get('version', 'BASE')}]"
                    )

            if not out_cards and not in_cards:
                print(
                    "No feed changes."
                )

        except Exception as e:
            # ------------------------------------------------
            # ERROR
            # ------------------------------------------------

            print(
                f"ERROR on {page_name}: {e}"
            )

            # IMPORTANT:
            # Non sovrascriviamo il vecchio stato
            # quando una pagina ha un errore.

            section = build_category_section(
                page_name=page_name,
                config=config,
                players=[],
                out_cards=[],
                in_cards=[],
                error=e,
            )

            telegram_sections.append(
                section
            )

    # ========================================================
    # UPDATE STATE
    # ========================================================

    for page_name, players in successful_updates.items():
        players_state[page_name] = players
        trending_state.setdefault(
            "pages",
            {}
        )
        trending_state["pages"][page_name] = players

    # timestamp
    import time

    trending_state["updated_at"] = int(
        time.time()
    )

    # ========================================================
    # SAVE FILES
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

    message = (
        "\n\n"
        "------------------------------"
        "\n\n"
    ).join(
        telegram_sections
    )

    telegram_send(
        message
    )

    # ========================================================
    # FINAL LOG
    # ========================================================

    print()
    print("=" * 60)

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

    print("=" * 60)


if __name__ == "__main__":
    main()