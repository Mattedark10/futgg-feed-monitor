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
# LINEUP SECTION
# ============================================================

def get_lineup_html(page_html):
    """
    Isola esclusivamente il blocco della lineup visibile.

    Cerca:
        Cheapest grade X lineup

    e termina prima di:
        Add players
    """

    # Normalizziamo solo per la ricerca,
    # mantenendo però l'HTML originale.
    normalized = re.sub(
        r"\s+",
        " ",
        page_html
    )

    start_match = re.search(
        r"Cheapest\s+grade.*?lineup",
        normalized,
        re.IGNORECASE
    )

    if not start_match:
        # Secondo tentativo: alcune versioni della pagina
        # possono avere markup diverso.
        start_match = re.search(
            r"cheapest.{0,500}?lineup",
            normalized,
            re.IGNORECASE
        )

    if not start_match:
        raise ValueError(
            "Could not find 'Cheapest grade X lineup'"
        )

    start_text = start_match.group(0)

    # Troviamo la posizione equivalente nell'HTML originale.
    original_start = page_html.lower().find(
        start_text.lower()[:40]
    )

    if original_start < 0:
        original_start = max(
            0,
            start_match.start()
        )

    # Cerca Add players dopo l'inizio.
    after_start = page_html[original_start:]

    end_match = re.search(
        r"Add\s+players",
        after_start,
        re.IGNORECASE
    )

    if end_match:
        original_end = (
            original_start +
            end_match.start()
        )
    else:
        original_end = min(
            len(page_html),
            original_start + 300000
        )

    section = page_html[
        original_start:original_end
    ]

    if len(section) < 500:
        raise ValueError(
            "Lineup section is too small"
        )

    return section


# ============================================================
# ITEM IDS
# ============================================================

def extract_item_ids(section_html):
    """
    Estrae gli ItemID mantenendo l'ordine.
    """

    patterns = [
        r'"itemId"\s*:\s*"?(\d+)"?',
        r'"item_id"\s*:\s*"?(\d+)"?',
        r'"ItemID"\s*:\s*"?(\d+)"?',
        r'"itemID"\s*:\s*"?(\d+)"?',
        r'data-item-id=["\'](\d+)["\']',
        r'itemId=(\d+)',
        r'item_id=(\d+)',
    ]

    found_ids = []

    for pattern in patterns:
        matches = re.findall(
            pattern,
            section_html,
            re.IGNORECASE
        )

        for item_id in matches:
            if item_id not in found_ids:
                found_ids.append(item_id)

    return found_ids


# ============================================================
# CARD LINKS
# ============================================================

def extract_card_links(section_html):
    """
    Cerca sia URL assoluti che relativi.
    """

    soup = BeautifulSoup(
        section_html,
        "html.parser"
    )

    links = []

    for a in soup.find_all("a", href=True):
        href = a.get("href", "").strip()

        if not href:
            continue

        # Accettiamo sia:
        # /fut/player/...
        # https://www.fut.gg/fut/player/...
        if "/fut/player/" not in href:
            continue

        if href.startswith("/"):
            href = "https://www.fut.gg" + href

        elif href.startswith("www.fut.gg"):
            href = "https://" + href

        href = href.rstrip("/")

        if href not in links:
            links.append(href)

    return links


# ============================================================
# CARD TEXT
# ============================================================

def normalize_text(value):
    value = html.unescape(value or "")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def get_card_text_from_anchor(anchor):
    values = []

    text = anchor.get_text(
        " ",
        strip=True
    )

    if text:
        values.append(text)

    for attribute in [
        "title",
        "aria-label",
        "alt",
        "data-name",
        "data-player-name"
    ]:
        value = anchor.get(attribute)

        if value:
            values.append(value)

    return " ".join(values)


# ============================================================
# PARSE NAME / OVERALL
# ============================================================

def parse_card_info(anchor, url):
    text = normalize_text(
        get_card_text_from_anchor(anchor)
    )

    # --------------------------------------------------------
    # Overall
    # --------------------------------------------------------

    overall = "?"

    overall_patterns = [
        r"\b(\d{2})\s*OVR\b",
        r"\bOVR\s*(\d{2})\b",
        r"\b(\d{2})\b"
    ]

    for pattern in overall_patterns:
        match = re.search(
            pattern,
            text,
            re.IGNORECASE
        )

        if match:
            overall = match.group(1)
            break

    # --------------------------------------------------------
    # Name
    # --------------------------------------------------------

    name = text

    # Togliamo l'overall
    name = re.sub(
        r"\b\d{2}\s*OVR\b",
        "",
        name,
        flags=re.IGNORECASE
    )

    name = re.sub(
        r"\bOVR\s*\d{2}\b",
        "",
        name,
        flags=re.IGNORECASE
    )

    # Rimuoviamo alcuni testi UI
    name = re.sub(
        r"\b(base|hero|icon|future stars|"
        r"destined for glory|holographic|"
        r"pristine holographic)\b",
        "",
        name,
        flags=re.IGNORECASE
    )

    name = normalize_text(name)

    # Se il testo dell'anchor non è utile,
    # prendiamo lo slug dell'URL.
    if not name or len(name) < 2:
        slug = url.rstrip("/").split("/")[-1]

        name = re.sub(
            r"-\d{2}.*$",
            "",
            slug,
            flags=re.IGNORECASE
        )

        name = name.replace(
            "-",
            " "
        )

    return {
        "name": name,
        "overall": overall,
        "url": url
    }


# ============================================================
# BUILD CARDS FROM HTML
# ============================================================

def extract_cards_from_section(section_html):
    """
    Prima prova a ricavare le carte dagli <a>.
    Se necessario usa ItemID come struttura di backup.
    """

    soup = BeautifulSoup(
        section_html,
        "html.parser"
    )

    cards = []

    # --------------------------------------------------------
    # Metodo principale
    # --------------------------------------------------------

    for a in soup.find_all("a", href=True):

        href = a.get(
            "href",
            ""
        ).strip()

        if "/fut/player/" not in href:
            continue

        if href.startswith("/"):
            url = "https://www.fut.gg" + href
        elif href.startswith("www.fut.gg"):
            url = "https://" + href
        else:
            url = href

        url = url.rstrip("/")

        info = parse_card_info(
            a,
            url
        )

        # Cerchiamo ItemID dentro l'anchor
        anchor_html = str(a)

        item_match = re.search(
            r'(?:itemId|item_id|ItemID|itemID)'
            r'\s*[=:]\s*["\']?(\d+)',
            anchor_html,
            re.IGNORECASE
        )

        if item_match:
            info["item_id"] = (
                item_match.group(1)
            )
        else:
            info["item_id"] = None

        cards.append(info)

    # --------------------------------------------------------
    # Deduplica mantenendo ordine
    # --------------------------------------------------------

    unique = []

    seen = set()

    for card in cards:

        key = (
            card.get("item_id")
            or card.get("url")
        )

        if key in seen:
            continue

        seen.add(key)
        unique.append(card)

    return unique


# ============================================================
# FINISH
# ============================================================

def detect_finish_from_card_page(url):
    """
    Controlla la pagina della singola carta.

    Possibili risultati:
        BASE
        HOLO
        PRISTINE HOLO
    """

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=20
        )

        response.raise_for_status()

        page = response.text

        # ----------------------------------------------------
        # TITLE
        # ----------------------------------------------------

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

        title = normalize_text(title)

        title_upper = title.upper()

        if "PRISTINE HOLOGRAPHIC" in title_upper:
            return "PRISTINE HOLO"

        if "HOLOGRAPHIC" in title_upper:
            return "HOLO"

        # ----------------------------------------------------
        # FALLBACK
        # ----------------------------------------------------

        first_part = page[:20000].upper()

        if "PRISTINE HOLOGRAPHIC" in first_part:
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

def resolve_cards(section_html, expected, cache):

    # --------------------------------------------------------
    # Extract cards
    # --------------------------------------------------------

    cards = extract_cards_from_section(
        section_html
    )

    print(
        f"Found {len(cards)} card URLs."
    )

    # --------------------------------------------------------
    # If anchor parser fails, try ItemID data
    # --------------------------------------------------------

    if len(cards) < expected:

        item_ids = extract_item_ids(
            section_html
        )

        print(
            f"Found {len(item_ids)} ItemIDs."
        )

        # Debug utile nei log GitHub
        if item_ids:
            print(
                "ItemIDs:"
            )

            for item_id in item_ids:
                print(
                    f"- {item_id}"
                )

    # --------------------------------------------------------
    # Validate
    # --------------------------------------------------------

    if len(cards) != expected:

        raise ValueError(
            f"Expected {expected} cards, "
            f"found {len(cards)}"
        )

    # --------------------------------------------------------
    # Finish resolution
    # --------------------------------------------------------

    for card in cards:

        item_id = card.get(
            "item_id"
        )

        url = card.get(
            "url"
        )

        if (
            item_id
            and item_id in cache["finishes"]
        ):
            version = cache[
                "finishes"
            ][item_id]

        else:
            version = detect_finish_from_card_page(
                url
            )

            if item_id:
                cache[
                    "finishes"
                ][item_id] = version

        card["version"] = version

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
        f"{card.get('version', '')}"
    )


# ============================================================
# COMPARE
# ============================================================

def compare_lineups(old_cards, new_cards):

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

    # ========================================================
    # NO CHANGES
    # ========================================================

    if not incoming and not out:

        lines.append(
            "No feed changes"
        )

        return "\n".join(lines)

    # ========================================================
    # OUT
    # ========================================================

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

    # ========================================================
    # IN
    # ========================================================

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

    # ========================================================
    # CURRENT LINEUP
    # ========================================================

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

            incoming_counter[
                key
            ] -= 1

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

        # IMPORTANT:
        # Se una pagina dà errore NON tocchiamo
        # il vecchio stato.

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
# RUN
# ============================================================

if __name__ == "__main__":
    main()