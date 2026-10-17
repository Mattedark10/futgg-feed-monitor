import os
import re
import json
import html
import requests
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
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


# ============================================================
# FILE HELPERS
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
            indent=2,
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
            "finishes": {},
        }

    if "finishes" not in cache:
        cache["finishes"] = {}

    return cache


def save_cache(cache):
    save_json(CACHE_FILE, cache)


# ============================================================
# DOWNLOAD PAGE
# ============================================================

def fetch_page(url):
    response = requests.get(
        url,
        headers=HEADERS,
        timeout=30,
    )

    response.raise_for_status()

    return response.text


# ============================================================
# FIND LINEUP SECTION
# ============================================================

def get_lineup_html(page_html):
    """
    Tries to isolate the visible 'Cheapest grade X lineup'
    section from the page.

    We intentionally avoid the internal 'solution:' RSC object.
    """

    # First try the exact visible text
    patterns = [
        r"Cheapest\s+grade\s+[^<]{0,100}lineup",
        r"cheapest\s+grade\s+[^<]{0,100}lineup",
    ]

    match = None

    for pattern in patterns:
        match = re.search(
            pattern,
            page_html,
            re.IGNORECASE,
        )

        if match:
            break

    if match:
        start = max(0, match.start() - 3000)

        # The lineup normally ends before "Add players"
        add_players = re.search(
            r"Add\s+players",
            page_html[match.end():],
            re.IGNORECASE,
        )

        if add_players:
            end = (
                match.end()
                + add_players.start()
            )
        else:
            end = min(
                len(page_html),
                match.end() + 250000,
            )

        return page_html[start:end]

    # Fallback: search for the lineup container
    lineup_match = re.search(
        r"lineup",
        page_html,
        re.IGNORECASE,
    )

    if lineup_match:
        start = max(0, lineup_match.start() - 3000)
        end = min(
            len(page_html),
            lineup_match.start() + 250000,
        )

        return page_html[start:end]

    raise ValueError(
        "Could not find 'Cheapest grade X lineup'"
    )


# ============================================================
# CARD URL
# ============================================================

def find_card_urls(section_html):
    """
    Extract FUT.GG player/card URLs.
    """

    urls = re.findall(
        r'https://www\.fut\.gg/[A-Za-z0-9_\-./%]+',
        section_html,
        re.IGNORECASE,
    )

    cleaned = []

    for url in urls:
        url = url.rstrip(
            "\"'<>),.;"
        )

        if "/fut/player/" not in url:
            continue

        if url not in cleaned:
            cleaned.append(url)

    return cleaned


# ============================================================
# ITEM IDS
# ============================================================

def extract_item_ids(section_html):
    """
    Extract item IDs while preserving order and duplicates.
    """

    patterns = [
        r'"itemId"\s*:\s*(\d+)',
        r'"item_id"\s*:\s*(\d+)',
        r'"ItemID"\s*:\s*(\d+)',
        r'itemId=(\d+)',
        r'item_id=(\d+)',
    ]

    ids = []

    for pattern in patterns:
        found = re.findall(
            pattern,
            section_html,
            re.IGNORECASE,
        )

        for item_id in found:
            if item_id not in ids:
                ids.append(item_id)

    return ids


# ============================================================
# CARD INFORMATION
# ============================================================

def clean_name(name):
    name = html.unescape(name)
    name = re.sub(r"\s+", " ", name)
    return name.strip()


def parse_card_url(url):
    """
    Attempts to extract player name / version / overall
    from the FUT.GG URL/title information.
    """

    clean_url = url.rstrip("/")

    slug = clean_url.split("/")[-1]

    slug = slug.replace(
        "-",
        " ",
    )

    slug = re.sub(
        r"\b\d{2}\b$",
        "",
        slug,
    )

    slug = re.sub(
        r"\b\d{2}\s+OVR\b",
        "",
        slug,
        flags=re.IGNORECASE,
    )

    slug = re.sub(
        r"\s+",
        " ",
        slug,
    ).strip()

    overall_match = re.search(
        r"\b(\d{2})\b",
        clean_url,
    )

    overall = (
        overall_match.group(1)
        if overall_match
        else "?"
    )

    return {
        "name": clean_name(slug),
        "overall": overall,
        "url": url,
    }


# ============================================================
# EXACT CARD PAGE / FINISH
# ============================================================

def detect_finish_from_card_page(url):
    """
    Opens the exact card page and checks the title/name.

    BASE
    HOLO
    PRISTINE HOLO
    """

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=20,
        )

        response.raise_for_status()

        text = response.text

        # Prefer title
        title_match = re.search(
            r"<title[^>]*>(.*?)</title>",
            text,
            re.IGNORECASE | re.DOTALL,
        )

        if title_match:
            title = html.unescape(
                title_match.group(1)
            )

            title = re.sub(
                r"\s+",
                " ",
                title,
            ).strip()
        else:
            title = text[:5000]

        title_upper = title.upper()

        if "PRISTINE HOLOGRAPHIC" in title_upper:
            return "PRISTINE HOLO"

        if "HOLOGRAPHIC" in title_upper:
            return "HOLO"

        return "BASE"

    except Exception as e:
        print(
            f"  Finish error: {url} -> {e}"
        )

        return "BASE"


# ============================================================
# CARD KEY
# ============================================================

def card_key(card):
    """
    Item ID is the primary identity.

    This means changing BASE/HOLO/PRISTINE HOLO
    does NOT create a false OUT/IN.
    """

    item_id = card.get("item_id")

    if item_id:
        return f"item:{item_id}"

    return (
        f"{card.get('name', '')}|"
        f"{card.get('overall', '')}|"
        f"{card.get('version', '')}"
    )


# ============================================================
# BUILD LINEUP
# ============================================================

def build_lineup(page_html, expected, cache):
    section = get_lineup_html(page_html)

    urls = find_card_urls(section)
    item_ids = extract_item_ids(section)

    print(
        f"Found {len(urls)} card URLs."
    )

    cards = []

    # --------------------------------------------------------
    # Try to pair URLs and item IDs
    # --------------------------------------------------------

    count = max(
        len(urls),
        len(item_ids),
    )

    for i in range(count):
        url = urls[i] if i < len(urls) else None
        item_id = (
            item_ids[i]
            if i < len(item_ids)
            else None
        )

        if not url and not item_id:
            continue

        if url:
            info = parse_card_url(url)
        else:
            info = {
                "name": "Unknown",
                "overall": "?",
                "url": "",
            }

        info["item_id"] = item_id

        # ----------------------------------------------------
        # Finish cache
        # ----------------------------------------------------

        if item_id and item_id in cache["finishes"]:
            version = cache["finishes"][item_id]
        elif url:
            version = detect_finish_from_card_page(
                url
            )

            if item_id:
                cache["finishes"][item_id] = version

        else:
            version = "BASE"

        info["version"] = version

        cards.append(info)

    # --------------------------------------------------------
    # If parsing produced too many cards, trim to expected.
    # --------------------------------------------------------

    if len(cards) > expected:
        cards = cards[:expected]

    return cards


# ============================================================
# COMPARE LINEUPS
# ============================================================

def compare_lineups(old_cards, new_cards):
    """
    Order-independent comparison.

    Duplicate cards are preserved.
    """

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
            - new_counter.get(key, 0)
        )

        if difference <= 0:
            continue

        matching = [
            card
            for card in old_cards
            if card_key(card) == key
        ]

        for card in matching[:difference]:
            out.append(card)

    # --------------------------------------------------------
    # IN
    # --------------------------------------------------------

    for key, new_count in new_counter.items():
        difference = (
            new_count
            - old_counter.get(key, 0)
        )

        if difference <= 0:
            continue

        matching = [
            card
            for card in new_cards
            if card_key(card) == key
        ]

        for card in matching[:difference]:
            incoming.append(card)

    return out, incoming


# ============================================================
# FORMAT CARD
# ============================================================

def format_card(card):
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
        f"{name} {overall} — {version}"
    )


# ============================================================
# CATEGORY TELEGRAM SECTION
# ============================================================

def build_category_section(
    category,
    old_cards,
    new_cards,
    incoming,
    out,
):
    config = PAGES[category]

    emoji = config["emoji"]

    lines = [
        f"{emoji} <b>{html.escape(category)}</b>",
        "",
    ]

    # --------------------------------------------------------
    # NO CHANGES
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
        lines.extend(
            [
                "🔴 <b>OUT</b>",
                "",
            ]
        )

        for card in out:
            lines.append(
                f"• {format_card(card)}"
            )

        lines.append("")

    # --------------------------------------------------------
    # IN
    # --------------------------------------------------------

    if incoming:
        lines.extend(
            [
                "🟢 <b>IN</b>",
                "",
            ]
        )

        for card in incoming:
            lines.append(
                f"• {format_card(card)}"
            )

        lines.append("")

    # --------------------------------------------------------
    # CURRENT LINEUP
    # --------------------------------------------------------

    lines.extend(
        [
            "<b>Current lineup</b>",
            "",
        ]
    )

    incoming_keys = Counter(
        card_key(card)
        for card in incoming
    )

    for card in new_cards:
        key = card_key(card)

        if incoming_keys.get(key, 0) > 0:
            lines.append(
                f"🟢 {format_card(card)}"
            )

            incoming_keys[key] -= 1

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
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    try:
        response = requests.post(
            url,
            json=payload,
            timeout=20,
        )

        response.raise_for_status()

        return True

    except Exception as e:
        print(
            f"Telegram error: {e}"
        )

        return False


# ============================================================
# TRENDING DATA
# ============================================================

def update_trending(results):
    data = load_json(
        TRENDING_FILE,
        {
            "updated_at": 0,
            "pages": {},
        },
    )

    import time

    data["updated_at"] = int(
        time.time()
    )

    for category, result in results.items():
        if not result.get("success"):
            continue

        data["pages"][category] = (
            result["new_cards"]
        )

    save_json(
        TRENDING_FILE,
        data,
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
            "Season 1": [],
        },
    )

    cache = load_cache()

    results = {}

    telegram_sections = []

    total_changes = False

    # ========================================================
    # SCAN EACH PAGE
    # ========================================================

    for category, config in PAGES.items():

        print()
        print(
            f"Scanning {config['emoji']} "
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

            new_cards = build_lineup(
                page_html,
                config["expected"],
                cache,
            )

            # ------------------------------------------------
            # Validate card count
            # ------------------------------------------------

            if len(new_cards) != config["expected"]:
                raise ValueError(
                    f"Expected "
                    f"{config['expected']} cards, "
                    f"found {len(new_cards)}"
                )

            old_cards = old_state.get(
                category,
                [],
            )

            out, incoming = compare_lineups(
                old_cards,
                new_cards,
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
                "incoming": incoming,
            }

            print(
                f"Found {len(new_cards)} "
                f"valid cards."
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
                    category=category,
                    old_cards=old_cards,
                    new_cards=new_cards,
                    incoming=incoming,
                    out=out,
                )
            )

        except Exception as e:

            print(
                f"ERROR on {category}: {e}"
            )

            results[category] = {
                "success": False,
                "error": str(e),
            }

            telegram_sections.append(
                "\n".join(
                    [
                        (
                            f"{config['emoji']} "
                            f"<b>{html.escape(category)}</b>"
                        ),
                        "",
                        "⚠️ Error scanning feed",
                    ]
                )
            )

    # ========================================================
    # SAVE ONLY SUCCESSFUL PAGES
    # ========================================================

    new_state = dict(old_state)

    for category, result in results.items():
        if not result.get("success"):
            continue

        new_state[category] = (
            result["new_cards"]
        )

    save_json(
        PLAYERS_FILE,
        new_state,
    )

    save_cache(cache)

    update_trending(results)

    # ========================================================
    # TELEGRAM MESSAGE
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
    # SUMMARY
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


if __name__ == "__main__":
    main()