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

CACHE_VERSION = 2

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
    cache = load_json(CACHE_FILE, {})

    if cache.get("cache_version") != CACHE_VERSION:
        print("Cache version mismatch. Resetting finish cache.")

        return {
            "cache_version": CACHE_VERSION,
            "finishes": {}
        }

    if "finishes" not in cache:
        cache["finishes"] = {}

    return cache


def save_cache(cache):
    save_json(CACHE_FILE, cache)


# ============================================================
# FETCH PAGE
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
    value = html.unescape(value or "")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


# ============================================================
# FIND LINEUP SECTION
# ============================================================

def get_lineup_html(page_html):
    """
    Trova l'ultima occorrenza reale della lineup.

    FUT.GG può contenere il testo della lineup anche
    nei dati React/RSC prima della parte visibile.

    Per questo cerchiamo TUTTE le occorrenze e prendiamo
    quella più utile.
    """

    normalized = re.sub(
        r"\s+",
        " ",
        page_html
    )

    matches = list(
        re.finditer(
            r"Cheapest\s+grade\s+[^<]{0,200}?\s+lineup",
            normalized,
            re.IGNORECASE
        )
    )

    if not matches:
        matches = list(
            re.finditer(
                r"Cheapest\s+grade.{0,300}?lineup",
                normalized,
                re.IGNORECASE
            )
        )

    if not matches:
        raise ValueError(
            "Could not find 'Cheapest grade X lineup'"
        )

    # Usiamo l'ultima occorrenza.
    match = matches[-1]

    # La stringa normalizzata può avere spazi diversi
    # dall'HTML originale, quindi cerchiamo direttamente
    # il testo "Cheapest grade".
    positions = [
        m.start()
        for m in re.finditer(
            r"Cheapest\s+grade",
            page_html,
            re.IGNORECASE
        )
    ]

    if positions:
        start = positions[-1]
    else:
        start = max(
            0,
            match.start()
        )

    after = page_html[start:]

    end_match = re.search(
        r"Add\s+players",
        after,
        re.IGNORECASE
    )

    if end_match:
        end = end_match.start()
    else:
        end = min(
            len(after),
            400000
        )

    section = after[:end]

    if len(section) < 500:
        raise ValueError(
            "Lineup section is too small"
        )

    return section


# ============================================================
# FIND CARD DATA
# ============================================================

CARD_PATTERN = re.compile(
    r"""
    (?P<name>
        [A-Za-zÀ-ÖØ-öø-ÿĀ-žßẞ'’.\-]+
        (?:\s+[A-Za-zÀ-ÖØ-öø-ÿĀ-žßẞ'’.\-]+){0,5}
    )
    \s*[-–]\s*
    (?P<overall>\d{2})
    \s*[-–]\s*
    (?P<version>
        Base\s+Hero|
        Base\s+Icon|
        Future\s+Stars|
        Destined\s+for\s+Glory|
        Ones\s+to\s+Watch|
        Squad\s+Foundations|
        Rare|
        Team\s+of\s+the\s+Week
    )
    """,
    re.IGNORECASE | re.VERBOSE
)


def extract_cards_from_text(section_html, expected):
    """
    Estrae le carte direttamente dal testo/alt della lineup.

    Questo non dipende dagli <a href="/fut/player/...">.
    """

    soup = BeautifulSoup(
        section_html,
        "html.parser"
    )

    # --------------------------------------------------------
    # Tutto il testo utile
    # --------------------------------------------------------

    values = []

    # ALT delle immagini
    for img in soup.find_all("img"):
        alt = img.get("alt")

        if alt:
            values.append(
                normalize_text(alt)
            )

    # TITLE
    for tag in soup.find_all(
        attrs={"title": True}
    ):
        value = tag.get("title")

        if value:
            values.append(
                normalize_text(value)
            )

    # ARIA
    for tag in soup.find_all(
        attrs={"aria-label": True}
    ):
        value = tag.get("aria-label")

        if value:
            values.append(
                normalize_text(value)
            )

    # Testo completo come fallback
    values.append(
        normalize_text(
            soup.get_text(
                " ",
                strip=True
            )
        )
    )

    cards = []

    seen_occurrences = set()

    # --------------------------------------------------------
    # Cerca le carte
    # --------------------------------------------------------

    for value in values:

        matches = CARD_PATTERN.finditer(
            value
        )

        for match in matches:

            name = normalize_text(
                match.group("name")
            )

            overall = match.group(
                "overall"
            )

            version = normalize_text(
                match.group("version")
            )

            key = (
                name.lower(),
                overall,
                version.lower()
            )

            # NON eliminiamo completamente i duplicati:
            # usiamo il numero di occorrenze.
            occurrence_number = sum(
                1
                for c in cards
                if (
                    c["name"].lower(),
                    c["overall"],
                    c["base_version"].lower()
                ) == key
            )

            occurrence_key = (
                key,
                occurrence_number
            )

            if occurrence_key in seen_occurrences:
                continue

            seen_occurrences.add(
                occurrence_key
            )

            cards.append({
                "name": name,
                "overall": overall,
                "base_version": version,
                "version": "BASE",
                "url": "",
                "item_id": None
            })

            if len(cards) >= expected:
                return cards

    return cards


# ============================================================
# ITEM IDS
# ============================================================

def extract_item_ids(section_html):
    """
    Cerca tutti i possibili formati di ItemID.
    """

    patterns = [
        r'"itemId"\s*:\s*"?(\d+)"?',
        r'"item_id"\s*:\s*"?(\d+)"?',
        r'"ItemID"\s*:\s*"?(\d+)"?',
        r'"itemID"\s*:\s*"?(\d+)"?',
        r'"id"\s*:\s*"?(\d+)"?',
        r'data-item-id=["\'](\d+)["\']',
        r'itemId=(\d+)',
        r'item_id=(\d+)',
    ]

    ids = []

    for pattern in patterns:

        matches = re.findall(
            pattern,
            section_html,
            re.IGNORECASE
        )

        for item_id in matches:

            if item_id not in ids:
                ids.append(item_id)

    return ids


# ============================================================
# TRY TO FIND CARD URL
# ============================================================

def extract_card_urls(section_html):
    """
    Cerca URL carta in qualunque formato.
    """

    urls = []

    patterns = [
        r'https?://(?:www\.)?fut\.gg/[^"\']+',
        r'(?:"|\')(/fut/player/[^"\']+)(?:"|\')',
        r'(/fut/player/[^"\']+)'
    ]

    for pattern in patterns:

        matches = re.findall(
            pattern,
            section_html,
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
                urls.append(url)

    return urls


# ============================================================
# FINISH
# ============================================================

def detect_finish_from_card_page(url):

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

        if "HOLOGRAPHIC" in upper:
            return "HOLO"

        first_part = page[
            :30000
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
    expected,
    cache
):

    # --------------------------------------------------------
    # Cards from visible lineup text
    # --------------------------------------------------------

    cards = extract_cards_from_text(
        section_html,
        expected
    )

    print(
        f"Rendered lineup: "
        f"{len(cards)}/{expected} real cards"
    )

    # --------------------------------------------------------
    # Item IDs
    # --------------------------------------------------------

    item_ids = extract_item_ids(
        section_html
    )

    print(
        f"Found {len(item_ids)} ItemIDs."
    )

    # --------------------------------------------------------
    # URLs
    # --------------------------------------------------------

    urls = extract_card_urls(
        section_html
    )

    print(
        f"Found {len(urls)} card URLs."
    )

    # --------------------------------------------------------
    # Must have correct number
    # --------------------------------------------------------

    if len(cards) != expected:

        raise ValueError(
            f"Expected {expected} cards, "
            f"found {len(cards)}"
        )

    # --------------------------------------------------------
    # Attach IDs where possible
    # --------------------------------------------------------

    for index, card in enumerate(cards):

        if index < len(item_ids):
            card["item_id"] = (
                item_ids[index]
            )

        if index < len(urls):
            card["url"] = urls[index]

    # --------------------------------------------------------
    # Resolve finish
    # --------------------------------------------------------

    for card in cards:

        item_id = card.get(
            "item_id"
        )

        url = card.get(
            "url"
        )

        # Cache
        if (
            item_id
            and item_id in cache["finishes"]
        ):

            card["version"] = (
                cache["finishes"][item_id]
            )

        elif url:

            version = detect_finish_from_card_page(
                url
            )

            card["version"] = version

            if item_id:
                cache[
                    "finishes"
                ][item_id] = version

        else:
            # Se non abbiamo URL/ID,
            # manteniamo BASE come fallback.
            #
            # L'identità viene comunque
            # costruita con nome/overall/versione.
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
        return f"item:{item_id}"

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
# FORMAT
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

        return "\n".join(lines)

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
    # CURRENT LINEUP
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

        key = card_key(card)

        if incoming_counter.get(
            key,
            0
        ) > 0:

            lines.append(
                f"🟢 {format_card(card)}"
            )

            incoming_counter[key] -= 1

        else:

            lines.append(
                format_card(card)
            )

    return "\n".join(lines)


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

def update_trending(results):

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
    # SCAN PAGES
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

            page_html = fetch_page(
                config["url"]
            )

            section_html = get_lineup_html(
                page_html
            )

            new_cards = resolve_cards(
                section_html,
                config["expected"],
                cache
            )

            old_cards = old_state.get(
                category,
                []
            )

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

            if changed:

                print(
                    f"OUT: {len(out)}"
                )

                print(
                    f"IN: {len(incoming)}"
                )

            else:

                print(
                    "No feed changes."
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