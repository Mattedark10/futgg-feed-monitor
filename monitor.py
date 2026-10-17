import os
import re
import json
import html
import time
import requests
from bs4 import BeautifulSoup
from collections import Counter


# ============================================================
# CONFIG
# ============================================================

PAGES = {
    "Heroes": {
        "url": "https://www.fut.gg/fut-gallery/rarities/heroes/",
        "expected": 5,
        "emoji": "🦸‍♂️",
    },
    "Holographics": {
        "url": "https://www.fut.gg/fut-gallery/rarities/holographics/",
        "expected": 5,
        "emoji": "✨️",
    },
    "Season 1": {
        "url": "https://www.fut.gg/fut-gallery/rarities/season-1/",
        "expected": 9,
        "emoji": "1️⃣",
    },
}

PLAYERS_FILE = "players.json"
TRENDING_FILE = "docs/trending.json"
CACHE_FILE = "card_cache.json"

CACHE_VERSION = 3

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/xml;q=0.9,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


# ============================================================
# JSON
# ============================================================

def load_json(path, default):
    if not os.path.exists(path):
        return default

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
            indent=2
        )


# ============================================================
# CACHE
# ============================================================

def load_cache():

    cache = load_json(
        CACHE_FILE,
        {}
    )

    if cache.get("cache_version") != CACHE_VERSION:

        print(
            "Cache version mismatch. "
            "Resetting finish cache."
        )

        return {
            "cache_version": CACHE_VERSION,
            "finishes": {}
        }

    if "finishes" not in cache:
        cache["finishes"] = {}

    return cache


def save_cache(cache):
    save_json(
        CACHE_FILE,
        cache
    )


# ============================================================
# FETCH
# ============================================================

def fetch_page(url):

    response = requests.get(
        url,
        headers=HEADERS,
        timeout=30
    )

    response.raise_for_status()

    return response.text


# ============================================================
# NORMALIZE
# ============================================================

def normalize_text(value):

    value = html.unescape(
        value or ""
    )

    value = value.replace(
        "\u00a0",
        " "
    )

    value = re.sub(
        r"\s+",
        " ",
        value
    )

    return value.strip()


# ============================================================
# FIND LINEUP
# ============================================================

def get_lineup_html(page_html):

    normalized = re.sub(
        r"\s+",
        " ",
        page_html
    )

    matches = list(
        re.finditer(
            r"Cheapest\s+grade\s+.{0,300}?lineup",
            normalized,
            re.IGNORECASE
        )
    )

    if not matches:

        raise ValueError(
            "Could not find 'Cheapest grade X lineup'"
        )

    # --------------------------------------------------------
    # Troviamo tutte le occorrenze nel vero HTML
    # --------------------------------------------------------

    positions = [
        m.start()
        for m in re.finditer(
            r"Cheapest\s+grade",
            page_html,
            re.IGNORECASE
        )
    ]

    if not positions:
        raise ValueError(
            "Could not locate lineup position"
        )

    # L'ultima è normalmente quella renderizzata
    start = positions[-1]

    after = page_html[start:]

    # --------------------------------------------------------
    # Fine lineup
    # --------------------------------------------------------

    end_candidates = []

    for pattern in [
        r"Add\s+players",
        r"Add\s+Player",
        r"Bench",
        r"Substitutes",
    ]:

        match = re.search(
            pattern,
            after,
            re.IGNORECASE
        )

        if match:
            end_candidates.append(
                match.start()
            )

    if end_candidates:
        end = min(
            end_candidates
        )
    else:
        end = min(
            len(after),
            500000
        )

    section = after[:end]

    if len(section) < 300:

        raise ValueError(
            "Lineup section is too small"
        )

    return section


# ============================================================
# CARD PARSER
# ============================================================

# Versioni conosciute.
# La regex è volutamente più generica rispetto alla precedente.
KNOWN_VERSIONS = [
    "Base Hero",
    "Base Icon",
    "Future Stars",
    "Destined for Glory",
    "Ones to Watch",
    "Squad Foundations",
    "Team of the Week",
    "Rare",
]


def clean_card_version(version):

    version = normalize_text(
        version
    )

    lower = version.lower()

    replacements = {
        "base hero": "Base Hero",
        "base icon": "Base Icon",
        "future stars": "Future Stars",
        "destined for glory": "Destined for Glory",
        "ones to watch": "Ones to Watch",
        "squad foundations": "Squad Foundations",
        "team of the week": "Team of the Week",
        "rare": "Rare",
    }

    return replacements.get(
        lower,
        version
    )


def parse_card_string(value):

    value = normalize_text(
        value
    )

    if not value:
        return None

    # --------------------------------------------------------
    # Formato principale:
    #
    # Nome - 89 - Base Hero
    # Nome – 89 – Future Stars
    # --------------------------------------------------------

    pattern = re.compile(
        r"^(.*?)\s*[-–—]\s*(\d{2})\s*[-–—]\s*(.+?)$",
        re.IGNORECASE
    )

    match = pattern.match(
        value
    )

    if not match:
        return None

    name = normalize_text(
        match.group(1)
    )

    overall = match.group(2)

    version = clean_card_version(
        match.group(3)
    )

    # --------------------------------------------------------
    # Scarta roba palesemente non-carta
    # --------------------------------------------------------

    if not name:
        return None

    if len(name) > 100:
        return None

    if not overall.isdigit():
        return None

    overall_int = int(
        overall
    )

    if overall_int < 50 or overall_int > 99:
        return None

    # --------------------------------------------------------
    # Controllo versione
    # --------------------------------------------------------

    version_lower = version.lower()

    valid = any(
        known.lower() in version_lower
        for known in KNOWN_VERSIONS
    )

    if not valid:
        return None

    return {
        "name": name,
        "overall": overall,
        "base_version": version,
        "version": "BASE",
        "url": "",
        "item_id": None,
    }


# ============================================================
# EXTRACT CARDS
# ============================================================

def extract_cards_from_section(
    section_html,
    expected
):

    soup = BeautifulSoup(
        section_html,
        "html.parser"
    )

    candidates = []

    # --------------------------------------------------------
    # 1. IMG ALT
    # --------------------------------------------------------

    for img in soup.find_all("img"):

        for attr in [
            "alt",
            "title",
            "aria-label",
        ]:

            value = img.get(
                attr
            )

            if value:
                candidates.append(
                    normalize_text(value)
                )

    # --------------------------------------------------------
    # 2. Qualunque elemento con aria-label/title
    # --------------------------------------------------------

    for tag in soup.find_all():

        for attr in [
            "aria-label",
            "title",
            "data-name",
            "data-player-name",
        ]:

            value = tag.get(
                attr
            )

            if value:
                candidates.append(
                    normalize_text(value)
                )

    # --------------------------------------------------------
    # 3. Testo dei singoli nodi
    # --------------------------------------------------------

    for tag in soup.find_all(
        ["div", "span", "p", "a"]
    ):

        text = normalize_text(
            tag.get_text(
                " ",
                strip=True
            )
        )

        if text:
            candidates.append(
                text
            )

    # --------------------------------------------------------
    # 4. HTML / testo completo come ultima possibilità
    # --------------------------------------------------------

    candidates.append(
        normalize_text(
            soup.get_text(
                " ",
                strip=True
            )
        )
    )

    cards = []

    # Conta quante volte abbiamo visto
    # esattamente la stessa carta.
    occurrence_counter = Counter()

    for value in candidates:

        # ----------------------------------------------------
        # Prima proviamo l'intera stringa
        # ----------------------------------------------------

        parsed = parse_card_string(
            value
        )

        if parsed:

            signature = (
                parsed["name"].lower(),
                parsed["overall"],
                parsed["base_version"].lower()
            )

            occurrence_counter[
                signature
            ] += 1

            # Limite: non aggiungiamo la stessa
            # carta all'infinito se compare in
            # alt + title + aria-label.
            #
            # Le vere duplicate della lineup
            # vengono gestite separatamente sotto.
            existing_count = sum(
                1
                for c in cards
                if (
                    c["name"].lower(),
                    c["overall"],
                    c["base_version"].lower()
                ) == signature
            )

            if existing_count < 2:
                cards.append(
                    parsed
                )

                if len(cards) >= expected:
                    return cards

            continue

        # ----------------------------------------------------
        # Se la stringa contiene più carte,
        # cerchiamo pattern multipli.
        # ----------------------------------------------------

        generic_pattern = re.compile(
            r"([^|]{1,100}?)\s*[-–—]\s*"
            r"(\d{2})\s*[-–—]\s*"
            r"([^|]{2,80}?)"
            r"(?=\s+[^|]{1,100}\s*[-–—]\s*\d{2}\s*[-–—]|$)",
            re.IGNORECASE
        )

        for match in generic_pattern.finditer(
            value
        ):

            candidate = (
                f"{match.group(1).strip()} - "
                f"{match.group(2)} - "
                f"{match.group(3).strip()}"
            )

            parsed = parse_card_string(
                candidate
            )

            if not parsed:
                continue

            signature = (
                parsed["name"].lower(),
                parsed["overall"],
                parsed["base_version"].lower()
            )

            existing_count = sum(
                1
                for c in cards
                if (
                    c["name"].lower(),
                    c["overall"],
                    c["base_version"].lower()
                ) == signature
            )

            if existing_count >= 2:
                continue

            cards.append(
                parsed
            )

            if len(cards) >= expected:
                return cards

    return cards


# ============================================================
# ITEM IDS
# ============================================================

def extract_item_ids(page_html):

    patterns = [

        r'"itemId"\s*:\s*"?(\d+)"?',
        r'"item_id"\s*:\s*"?(\d+)"?',
        r'"ItemID"\s*:\s*"?(\d+)"?',
        r'"itemID"\s*:\s*"?(\d+)"?',

        r'"playerItemId"\s*:\s*"?(\d+)"?',
        r'"player_item_id"\s*:\s*"?(\d+)"?',

        r'data-item-id=["\'](\d+)["\']',

        r'itemId=(\d+)',
        r'item_id=(\d+)',

        r'itemId%22%3A%22?(\d+)',
        r'item_id%22%3A%22?(\d+)',
    ]

    ids = []

    for pattern in patterns:

        matches = re.findall(
            pattern,
            page_html,
            re.IGNORECASE
        )

        for item_id in matches:

            if item_id not in ids:
                ids.append(
                    item_id
                )

    return ids


# ============================================================
# CARD URLS
# ============================================================

def extract_card_urls(page_html):

    urls = []

    patterns = [

        r'https?://(?:www\.)?fut\.gg/[^"\'>\s]+',

        r'(?:"|\')'
        r'(/fut/player/[^"\']+)'
        r'(?:"|\')',

        r'(/fut/player/[^"\'>\s]+)',

    ]

    for pattern in patterns:

        matches = re.findall(
            pattern,
            page_html,
            re.IGNORECASE
        )

        for url in matches:

            url = html.unescape(
                url
            )

            url = url.rstrip(
                "\"'<>),.;"
            )

            if url.startswith("/"):
                url = (
                    "https://www.fut.gg"
                    + url
                )

            if "/fut/player/" not in url:
                continue

            if url not in urls:

                urls.append(
                    url
                )

    return urls


# ============================================================
# FIND OLD FINISH
# ============================================================

def find_cached_finish(
    card,
    old_cards,
    cache
):

    # --------------------------------------------------------
    # 1. Item ID cache
    # --------------------------------------------------------

    item_id = card.get(
        "item_id"
    )

    if item_id:

        cached = cache[
            "finishes"
        ].get(
            item_id
        )

        if cached:
            return cached

    # --------------------------------------------------------
    # 2. Cerca stessa carta nello stato precedente
    # --------------------------------------------------------

    name = card.get(
        "name",
        ""
    ).lower()

    overall = str(
        card.get(
            "overall",
            ""
        )
    )

    base_version = card.get(
        "base_version",
        ""
    ).lower()

    for old in old_cards:

        if (
            old.get(
                "name",
                ""
            ).lower() == name
            and str(
                old.get(
                    "overall",
                    ""
                )
            ) == overall
            and old.get(
                "base_version",
                ""
            ).lower() == base_version
        ):

            old_finish = old.get(
                "version"
            )

            if old_finish:
                return old_finish

    return None


# ============================================================
# DETECT FINISH
# ============================================================

def detect_finish_from_card_page(
    url
):

    if not url:
        return "BASE"

    try:

        response = requests.get(
            url,
            headers=HEADERS,
            timeout=20
        )

        response.raise_for_status()

        page = response.text

        title_match = re.search(
            r"<title[^>]*>(.*?)</title>",
            page,
            re.IGNORECASE | re.DOTALL
        )

        title = ""

        if title_match:

            title = html.unescape(
                title_match.group(1)
            )

        title = normalize_text(
            title
        )

        upper = title.upper()

        if (
            "PRISTINE HOLOGRAPHIC"
            in upper
        ):
            return "PRISTINE HOLO"

        if (
            "HOLOGRAPHIC"
            in upper
        ):
            return "HOLO"

        first_part = page[
            :50000
        ].upper()

        if (
            "PRISTINE HOLOGRAPHIC"
            in first_part
        ):
            return "PRISTINE HOLO"

        if "HOLOGRAPHIC" in first_part:
            return "HOLO"

        return "BASE"

    except Exception as e:

        print(
            f"  Finish error: {url} -> {e}"
        )

        return "BASE"


# ============================================================
# RESOLVE CARDS
# ============================================================

def resolve_cards(
    section_html,
    full_page_html,
    expected,
    cache,
    old_cards
):

    # --------------------------------------------------------
    # CARDS
    # --------------------------------------------------------

    cards = extract_cards_from_section(
        section_html,
        expected
    )

    print(
        f"Rendered lineup: "
        f"{len(cards)}/{expected} real cards"
    )

    # --------------------------------------------------------
    # ITEM IDS
    # --------------------------------------------------------

    item_ids = extract_item_ids(
        full_page_html
    )

    print(
        f"Found {len(item_ids)} ItemIDs."
    )

    # --------------------------------------------------------
    # URLS
    # --------------------------------------------------------

    urls = extract_card_urls(
        full_page_html
    )

    print(
        f"Found {len(urls)} card URLs."
    )

    # --------------------------------------------------------
    # VALIDATION
    # --------------------------------------------------------

    if len(cards) != expected:

        raise ValueError(
            f"Expected {expected} cards, "
            f"found {len(cards)}"
        )

    # --------------------------------------------------------
    # ATTACH IDENTIFIERS
    # --------------------------------------------------------

    for index, card in enumerate(
        cards
    ):

        if index < len(item_ids):

            card["item_id"] = (
                item_ids[index]
            )

        if index < len(urls):

            card["url"] = (
                urls[index]
            )

    # --------------------------------------------------------
    # FINISH
    # --------------------------------------------------------

    for card in cards:

        item_id = card.get(
            "item_id"
        )

        url = card.get(
            "url"
        )

        # ----------------------------------------------------
        # Cache per ItemID
        # ----------------------------------------------------

        if (
            item_id
            and item_id in cache["finishes"]
        ):

            card["version"] = (
                cache["finishes"][item_id]
            )

            continue

        # ----------------------------------------------------
        # Stato precedente
        # ----------------------------------------------------

        old_finish = find_cached_finish(
            card,
            old_cards,
            cache
        )

        if old_finish:

            card["version"] = old_finish

            if item_id:

                cache[
                    "finishes"
                ][item_id] = old_finish

            continue

        # ----------------------------------------------------
        # URL carta
        # ----------------------------------------------------

        if url:

            version = detect_finish_from_card_page(
                url
            )

            card["version"] = version

            if item_id:

                cache[
                    "finishes"
                ][item_id] = version

        else:

            card["version"] = "BASE"

    return cards


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
        f"{card.get('name', '')}|"
        f"{card.get('overall', '')}|"
        f"{card.get('base_version', '')}|"
        f"{card.get('version', '')}"
    )


# ============================================================
# COMPARE
# ============================================================

def compare_lineups(
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

    # --------------------------------------------------------
    # OUT
    # --------------------------------------------------------

    for key, old_count in old_counter.items():

        difference = (
            old_count
            - new_counter.get(
                key,
                0
            )
        )

        if difference <= 0:
            continue

        matching = [
            card
            for card in old_cards
            if card_key(card) == key
        ]

        out.extend(
            matching[:difference]
        )

    # --------------------------------------------------------
    # IN
    # --------------------------------------------------------

    for key, new_count in new_counter.items():

        difference = (
            new_count
            - old_counter.get(
                key,
                0
            )
        )

        if difference <= 0:
            continue

        matching = [
            card
            for card in new_cards
            if card_key(card) == key
        ]

        incoming.extend(
            matching[:difference]
        )

    return out, incoming


# ============================================================
# FORMAT CARD
# ============================================================

def format_card(card):

    name = html.escape(
        str(
            card.get(
                "name",
                "Unknown"
            )
        )
    )

    overall = html.escape(
        str(
            card.get(
                "overall",
                "?"
            )
        )
    )

    version = html.escape(
        str(
            card.get(
                "version",
                "BASE"
            )
        )
    )

    return (
        f"{name} {overall} — {version}"
    )


# ============================================================
# TELEGRAM CATEGORY
# ============================================================

def build_category_section(
    category,
    new_cards,
    incoming,
    out
):

    emoji = PAGES[
        category
    ]["emoji"]

    lines = [
        (
            f"{emoji} "
            f"<b>{html.escape(category)}</b>"
        ),
        ""
    ]

    # --------------------------------------------------------
    # NO CHANGE
    # --------------------------------------------------------

    if not incoming and not out:

        lines.append(
            "No feed changes"
        )

        return "\n".join(
            lines
        )

    # --------------------------------------------------------
    # OUT
    # --------------------------------------------------------

    if out:

        lines.extend([
            "🔴 <b>OUT</b>",
            ""
        ])

        for card in out:

            lines.append(
                f"• {format_card(card)}"
            )

        lines.append("")

    # --------------------------------------------------------
    # IN
    # --------------------------------------------------------

    if incoming:

        lines.extend([
            "🟢 <b>IN</b>",
            ""
        ])

        for card in incoming:

            lines.append(
                f"• {format_card(card)}"
            )

        lines.append("")

    # --------------------------------------------------------
    # CURRENT
    # --------------------------------------------------------

    lines.extend([
        "<b>Current lineup</b>",
        ""
    ])

    incoming_counter = Counter(
        card_key(card)
        for card in incoming
    )

    for card in new_cards:

        key = card_key(
            card
        )

        if incoming_counter.get(
            key,
            0
        ) > 0:

            lines.append(
                f"🟢 {format_card(card)}"
            )

            incoming_counter[
                key
            ] -= 1

        else:

            lines.append(
                format_card(card)
            )

    return "\n".join(
        lines
    )


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):

    if not TELEGRAM_BOT_TOKEN:

        print(
            "Telegram token missing."
        )

        return False

    if not TELEGRAM_CHAT_ID:

        print(
            "Telegram chat ID missing."
        )

        return False

    url = (
        "https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }

    try:

        response = requests.post(
            url,
            json=payload,
            timeout=20
        )

        response.raise_for_status()

        return True

    except Exception as e:

        print(
            f"Telegram error: {e}"
        )

        return False


# ============================================================
# TRENDING
# ============================================================

def update_trending(
    results
):

    data = load_json(
        TRENDING_FILE,
        {
            "updated_at": 0,
            "pages": {
                "Heroes": [],
                "Holographics": [],
                "Season 1": []
            }
        }
    )

    data["updated_at"] = int(
        time.time()
    )

    for category, result in results.items():

        if not result.get(
            "success"
        ):
            continue

        data[
            "pages"
        ][category] = result[
            "new_cards"
        ]

    save_json(
        TRENDING_FILE,
        data
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

    old_state = load_json(
        PLAYERS_FILE,
        {
            "Heroes": [],
            "Holographics": [],
            "Season 1": []
        }
    )

    cache = load_cache()

    results = {}
    telegram_sections = []

    total_changes = False

    # ========================================================
    # SCAN
    # ========================================================

    for category, config in PAGES.items():

        print()
        print(
            f"Scanning "
            f"{config['emoji']} "
            f"{category}"
        )

        print(
            config["url"]
        )

        print(
            "=" * 60
        )

        try:

            # ------------------------------------------------
            # DOWNLOAD
            # ------------------------------------------------

            page_html = fetch_page(
                config["url"]
            )

            # ------------------------------------------------
            # LINEUP
            # ------------------------------------------------

            section_html = get_lineup_html(
                page_html
            )

            # ------------------------------------------------
            # OLD CARDS
            # ------------------------------------------------

            old_cards = old_state.get(
                category,
                []
            )

            # ------------------------------------------------
            # RESOLVE
            # ------------------------------------------------

            new_cards = resolve_cards(
                section_html,
                page_html,
                config["expected"],
                cache,
                old_cards
            )

            # ------------------------------------------------
            # COMPARE
            # ------------------------------------------------

            out, incoming = compare_lineups(
                old_cards,
                new_cards
            )

            changed = bool(
                out or incoming
            )

            if changed:

                total_changes = True

            results[category] = {
                "success": True,
                "changed": changed,
                "old_cards": old_cards,
                "new_cards": new_cards,
                "out": out,
                "incoming": incoming
            }

            print(
                f"Valid lineup: "
                f"{len(new_cards)}/"
                f"{config['expected']}"
            )

            print(
                f"OUT: {len(out)}"
            )

            print(
                f"IN: {len(incoming)}"
            )

            telegram_sections.append(
                build_category_section(
                    category,
                    new_cards,
                    incoming,
                    out
                )
            )

        except Exception as e:

            print(
                f"ERROR on {category}: {e}"
            )

            results[category] = {
                "success": False,
                "error": str(e)
            }

            telegram_sections.append(
                "\n".join([
                    (
                        f"{config['emoji']} "
                        f"<b>{html.escape(category)}</b>"
                    ),
                    "",
                    "⚠️ Error scanning feed"
                ])
            )

    # ========================================================
    # SAVE STATE
    # ========================================================

    new_state = dict(
        old_state
    )

    for category, result in results.items():

        if not result.get(
            "success"
        ):
            continue

        new_state[
            category
        ] = result[
            "new_cards"
        ]

    save_json(
        PLAYERS_FILE,
        new_state
    )

    save_cache(
        cache
    )

    update_trending(
        results
    )

    # ========================================================
    # TELEGRAM
    # ========================================================

    message = (
        "\n\n"
        "------------------------------"
        "\n\n"
    ).join(
        telegram_sections
    )

    telegram_ok = send_telegram(
        message
    )

    if telegram_ok:

        print(
            "Telegram notification sent."
        )

    else:

        print(
            "Telegram notification failed."
        )

    # ========================================================
    # RESULT
    # ========================================================

    print()
    print(
        "=" * 60
    )

    if total_changes:

        print(
            "RESULT: FEED CHANGES DETECTED"
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


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()