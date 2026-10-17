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
        "expected": 10,
    },
}

STATE_FILE = "players.json"
TRENDING_FILE = "docs/trending.json"

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
# FIND CHEAPEST LINEUP CONTAINER
# ============================================================

def find_cheapest_heading(soup):
    """
    Cerca:

    Cheapest grade A lineup
    Cheapest grade S lineup
    ecc.
    """

    pattern = re.compile(
        r"Cheapest\s+grade\s+.+?\s+lineup",
        re.IGNORECASE,
    )

    for tag in soup.find_all(
        ["h1", "h2", "h3", "h4", "h5", "div", "span"]
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
        ["h1", "h2", "h3", "h4", "h5"]
    ):

        text = tag.get_text(
            " ",
            strip=True,
        )

        if text.lower() == "add players":
            return tag

    return None


# ============================================================
# GET HTML BETWEEN HEADINGS
# ============================================================

def get_lineup_html(page_html):
    """
    Isola la parte HTML compresa tra:

        Cheapest grade X lineup

    e:

        Add players

    È questa la lineup che FUT.GG mostra realmente.
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
            "Could not find 'Cheapest grade ... lineup'"
        )

    heading_text = cheapest.get_text(
        " ",
        strip=True,
    )

    print(
        f"Found section: {heading_text}"
    )

    # --------------------------------------------------------
    # Prima proviamo con la posizione nell'HTML originale.
    # --------------------------------------------------------

    raw_patterns = [
        re.compile(
            r"Cheapest\s+grade\s+[^<]{1,30}\s+lineup",
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
            "Could not locate cheapest lineup "
            "inside raw HTML"
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

    # --------------------------------------------------------
    # Fallback: usa il secondo heading.
    # --------------------------------------------------------

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
    FUT.GG usa alt del tipo:

    Šašić - 89 - Base Hero
    Angerer - 92 - Base Icon

    Restituisce:

    name
    overall
    rarity
    """

    alt = clean_text(
        alt
    )

    if not alt:
        return None

    if alt.lower() == "player card":
        return None

    match = re.match(
        r"^(.+?)\s+-\s+(\d{2})\s+-\s+(.+?)$",
        alt,
    )

    if not match:
        return None

    name = normalize_name(
        match.group(1)
    )

    overall = int(
        match.group(2)
    )

    rarity = clean_text(
        match.group(3)
    )

    return {
        "name": name,
        "overall": overall,
        "rarity": rarity,
    }


# ============================================================
# FIND ITEM ID
# ============================================================

def find_item_id_from_element(img):
    """
    Cerca l'Item ID in:

    src
    srcset
    data-src
    data-nimg
    parent href
    HTML del parent

    Gli URL FUT.GG possono contenere per esempio:

    /27-67335170/
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

    # --------------------------------------------------------
    # Cerca anche nei parent
    # --------------------------------------------------------

    current = img

    for _ in range(6):

        if current is None:
            break

        if hasattr(
            current,
            "get"
        ):

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
        r"item[_-]?id[=:\"']+(\d{5,12})",
        r"eaId[=:\"']+(\d{5,12})",
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
# DETECT HOLOGRAPHIC FINISH
# ============================================================

def get_context_html(img):
    """
    Recupera un piccolo blocco HTML attorno alla carta.
    Serve per cercare eventuali informazioni sulla finitura.
    """

    current = img

    candidates = []

    for _ in range(7):

        if current is None:
            break

        try:

            html = str(
                current
            )

            candidates.append(
                html
            )

            # Evitiamo container enormi.
            if (
                len(html) >= 500
                and len(html) <= 20000
            ):
                return html

        except Exception:
            pass

        current = getattr(
            current,
            "parent",
            None,
        )

    if candidates:
        return candidates[-1]

    return ""


def detect_finish(img, page_name):
    """
    Cerca di distinguere:

    BASE
    HOLO
    PRISTINE HOLO

    senza assumere che tutte le carte della pagina
    abbiano la stessa finitura.
    """

    context = get_context_html(
        img
    )

    text = clean_text(
        context
    ).upper()

    # --------------------------------------------------------
    # PRISTINE
    # --------------------------------------------------------

    pristine_markers = [
        "PRISTINE HOLOGRAPHIC",
        "PRISTINE_HOLOGRAPHIC",
        "PRISTINE-HOLOGRAPHIC",
        "PRISTINE HOLO",
        "PRISTINE_HOLO",
        "PRISTINE-HOLO",
        "PRISTINE",
    ]

    for marker in pristine_markers:

        if marker in text:
            return "PRISTINE HOLO"

    # --------------------------------------------------------
    # REGULAR HOLOGRAPHIC
    # --------------------------------------------------------

    holo_markers = [
        "REGULAR HOLOGRAPHIC",
        "REGULAR_HOLOGRAPHIC",
        "REGULAR-HOLOGRAPHIC",
        "HOLOGRAPHIC",
        "HOLOGRAPHIC-CARD",
        "HOLOGRAPHIC_CARD",
        "HOLOGRAPHIC CARD",
    ]

    for marker in holo_markers:

        if marker in text:
            return "HOLO"

    # --------------------------------------------------------
    # Non inventiamo la finitura.
    #
    # L'alt "Base Hero"/"Base Icon" descrive la rarità
    # della carta, non necessariamente la finitura.
    # --------------------------------------------------------

    return "BASE"


# ============================================================
# EXTRACT EXACT DISPLAYED LINEUP
# ============================================================

def extract_cheapest_lineup(
    page_html,
    page_name,
    expected,
):
    """
    Estrae ESCLUSIVAMENTE le card visualizzate nella:

        Cheapest grade X lineup

    Non usa solution.items.
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

    # --------------------------------------------------------
    # Cerchiamo tutte le immagini con alt giocatore.
    # --------------------------------------------------------

    for img in soup.find_all(
        "img"
    ):

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

        finish = detect_finish(
            img,
            page_name,
        )

        card = {
            "name": info[
                "name"
            ],
            "overall": info[
                "overall"
            ],
            "rarity": info[
                "rarity"
            ],
            "version": finish,
            "ea_id": item_id,
        }

        players.append(
            card
        )

    # --------------------------------------------------------
    # FALLBACK:
    #
    # alcuni HTML Next.js possono avere gli alt escaped
    # nei dati RSC ma non come <img> normale.
    # --------------------------------------------------------

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

            # Piccolo contesto attorno all'alt.
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
                r"eaId[=:\"']+(\d{5,12})",
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

            upper_context = (
                clean_text(
                    context
                ).upper()
            )

            if "PRISTINE" in upper_context:
                version = (
                    "PRISTINE HOLO"
                )

            elif "HOLOGRAPHIC" in upper_context:
                version = "HOLO"

            else:
                version = "BASE"

            raw_players.append(
                {
                    "name": name,
                    "overall": overall,
                    "rarity": rarity,
                    "version": version,
                    "ea_id": item_id,
                }
            )

        # Usa fallback soltanto se migliora il risultato.
        if len(raw_players) > len(
            players
        ):

            players = raw_players

    # --------------------------------------------------------
    # IMPORTANTISSIMO:
    #
    # NON deduplichiamo.
    #
    # Se Šašić appare 2 volte, devono restare 2 slot.
    # --------------------------------------------------------

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
            if card["ea_id"]
            is not None
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

    # --------------------------------------------------------
    # SAFETY
    # --------------------------------------------------------

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
            f"⚠️ Telegram error: "
            f"{error}"
        )

        return False


# ============================================================
# CARD IDENTITY
# ============================================================

def card_key(card):
    """
    Identità della singola occorrenza.

    Preferiamo ea_id quando disponibile.

    Se FUT.GG non lo espone nel DOM, usiamo:
    nome + overall + rarity + version.

    Counter permette comunque i duplicati.
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

    out_cards = []
    in_cards = []

    remaining_old = list(
        old_cards
    )

    remaining_new = list(
        new_cards
    )

    removed = (
        old_counter
        - new_counter
    )

    added = (
        new_counter
        - old_counter
    )

    for key, count in (
        removed.items()
    ):

        for _ in range(
            count
        ):

            for index, card in enumerate(
                remaining_old
            ):

                if card_key(
                    card
                ) == key:

                    out_cards.append(
                        card
                    )

                    remaining_old.pop(
                        index
                    )

                    break

    for key, count in (
        added.items()
    ):

        for _ in range(
            count
        ):

            for index, card in enumerate(
                remaining_new
            ):

                if card_key(
                    card
                ) == key:

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
# FORMAT
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

    # Non scriviamo due volte BASE.
    if version == "BASE":

        return (
            f"{name} "
            f"{overall} "
            f"<b>{rarity}</b>"
        )

    return (
        f"{name} "
        f"{overall} "
        f"<b>{rarity}</b> "
        f"— {escape_html(version)}"
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
            # DOWNLOAD
            # =================================================

            page_html = download_page(
                config["url"]
            )

            # =================================================
            # IMPORTANT:
            #
            # Legge SOLO la lineup visualizzata sotto:
            #
            # Cheapest grade X lineup
            #
            # e NON solution.items.
            # =================================================

            players = (
                extract_cheapest_lineup(
                    page_html,
                    page_name,
                    config[
                        "expected"
                    ],
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
                        f"⚡ <b>{escape_html(page_name)}</b>"
                        f"\n"
                        f"Cheapest lineup changed"
                        f"\n\n"
                    )

                    if out_cards:

                        message += (
                            "🔴 <b>OUT</b>\n"
                        )

                        for card in (
                            out_cards
                        ):

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

                        for card in (
                            in_cards
                        ):

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
            # ONLY UPDATE A SUCCESSFUL PAGE
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
                f"<b>{escape_html(page_name)}</b>"
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