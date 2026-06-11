#!/usr/bin/env python3
"""Enrich Fantapazz listone with Transfermarkt club and national-team stats."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

from transfermarkt_team_map import (
    BASE_URL,
    SEASON_ID,
    TEAM_MAP,
    TMAPI_URL,
    national_performance_url,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = PROJECT_ROOT / "data" / "raw" / "fantapazz_listone.csv"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "raw" / "fantapazz_listone_enriched.csv"
DEFAULT_UNMATCHED = PROJECT_ROOT / "data" / "raw" / "transfermarkt_unmatched_players.csv"
CACHE_DIR = PROJECT_ROOT / "data" / "cache" / "transfermarkt"

ENRICH_ROLES = {"cb", "m", "st"}
FUZZY_THRESHOLD = 0.82
REQUEST_DELAY = 1.2
MAX_RETRIES = 3

MANUAL_PLAYER_OVERRIDES: dict[tuple[str, str, str], int] = {
    ("ARG", "st", "lopez j m"): 618303,  # José Manuel López
    ("ARG", "st", "martinez la"): 406625,  # Lautaro Martínez
    ("BRA", "m", "danilo dos santos"): 808509,
    ("CAN", "st", "david"): 533738,  # Jonathan David
    ("CAN", "st", "oluwasei"): 972465,  # Tani Oluwaseyi
    ("ECU", "m", "caicedo"): 687626,  # Moisés Caicedo
    ("GER", "m", "grob"): 82873,  # Pascal Groß; Fantapazz exports ß as b
    ("JAP", "st", "shiogay"): 1144627,  # Kento Shiogai
    ("TUR", "st", "yildiz"): 845654,  # Kenan Yıldız
    ("TUR", "st", "yilmaz b a"): 541537,  # Barış Alper Yılmaz
    ("USA", "m", "tillman"): 467437,  # Malik Tillman
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/json",
}

OUTPUT_FIELDS = [
    "fanta_role",
    "name",
    "team_name",
    "value",
    "club_goals_current_season",
    "national_goals_current_season",
    "national_appearances_current_season",
    "national_team_matches_current_season",
    "national_presence_ratio_current_season",
    "transfermarkt_player_url",
    "transfermarkt_match_status",
]


@dataclass
class NationalPlayer:
    name: str
    normalized_name: str
    player_id: int
    player_url: str
    position: str
    appearances: int | None
    goals: int | None


@dataclass
class NationalTeamData:
    team_code: str
    total_matches: int | None
    players: list[NationalPlayer]


def normalize_name(name: str) -> str:
    text = name.translate(
        str.maketrans(
            {
                "ø": "o",
                "Ø": "o",
                "æ": "ae",
                "Æ": "ae",
                "ö": "o",
                "Ö": "o",
                "ü": "u",
                "Ü": "u",
                "ä": "a",
                "Ä": "a",
                "ß": "ss",
                "ñ": "n",
                "Ñ": "n",
                "ı": "i",
                "İ": "i",
                "ş": "s",
                "Ş": "s",
                "ğ": "g",
                "Ğ": "g",
                "ç": "c",
                "Ç": "c",
            }
        )
    )
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def parse_int(value: str | None) -> int | None:
    if value is None:
        return None
    value = value.strip()
    if not value or value == "-":
        return 0
    lowered = value.lower()
    if lowered.startswith("non utilizzato") or "non faceva mai parte" in lowered:
        return 0
    if value.endswith("'"):
        return None
    try:
        return int(value)
    except ValueError:
        return None


def fuzzy_score(left: str, right: str) -> float:
    return SequenceMatcher(None, left, right).ratio()


def match_score(query: str, candidate: str) -> float:
    normalized_query = normalize_name(query)
    normalized_candidate = normalize_name(candidate)
    query_parts = normalized_query.split()
    candidate_parts = normalized_candidate.split()

    if not normalized_query or not normalized_candidate:
        return 0.0
    if normalized_query == normalized_candidate:
        return 1.0
    if len(query_parts) == 1 and query_parts[-1] == candidate_parts[-1]:
        return 0.96
    if normalized_query in candidate_parts:
        return 0.94
    if all(part in candidate_parts for part in query_parts):
        return 0.93
    if len(query_parts) >= 2 and candidate_parts[-len(query_parts) :] == query_parts:
        return 0.95
    if len(query_parts) >= 2 and len(query_parts[-1]) == 1:
        surname = " ".join(query_parts[:-1])
        initial = query_parts[-1]
        candidate_surnames = {candidate_parts[-1], candidate_parts[0]}
        if surname in candidate_surnames or surname.split()[-1] in candidate_surnames:
            if any(part.startswith(initial) for part in candidate_parts):
                return 0.97
    if len(query_parts) >= 2 and len(query_parts[0]) == 1:
        initial = query_parts[0]
        surname = " ".join(query_parts[1:])
        candidate_surnames = {candidate_parts[-1], candidate_parts[0]}
        if surname in candidate_surnames or surname.split()[-1] in candidate_surnames:
            if any(part.startswith(initial) for part in candidate_parts):
                return 0.97
    return fuzzy_score(normalized_query, normalized_candidate)


def player_aliases(player: NationalPlayer) -> set[str]:
    parts = player.normalized_name.split()
    aliases = {player.normalized_name}
    if not parts:
        return aliases

    first = parts[0]
    last = parts[-1]
    aliases.add(last)
    for prefix_len in range(1, min(3, len(first)) + 1):
        aliases.add(f"{last} {first[:prefix_len]}")
    aliases.add(f"{first[0]} {last}")
    if len(parts) >= 3:
        initials = " ".join(part[0] for part in parts[:-1] if part)
        aliases.add(f"{last} {initials}")

    if len(parts) >= 3:
        last_two = " ".join(parts[-2:])
        aliases.add(last_two)
        for prefix_len in range(1, min(3, len(first)) + 1):
            aliases.add(f"{last_two} {first[:prefix_len]}")
        aliases.add(f"{first[0]} {last_two}")

    return aliases


def is_position_compatible(fanta_role: str | None, position: str) -> bool:
    normalized_position = normalize_name(position)
    if not normalized_position:
        return True
    if fanta_role == "cb":
        included = ("difensore", "terzino")
        return any(term in normalized_position for term in included)
    if fanta_role == "m":
        excluded = ("portiere", "difensore", "terzino", "punta centrale")
        return not any(term in normalized_position for term in excluded)
    if fanta_role == "st":
        included = ("punta", "ala", "attaccante")
        return any(term in normalized_position for term in included)
    return True


class TransfermarktClient:
    def __init__(self, cache_dir: Path, delay: float = REQUEST_DELAY) -> None:
        self.cache_dir = cache_dir
        self.delay = delay
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._last_request = 0.0

    def _cache_path(self, kind: str, key: str, ext: str) -> Path:
        digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
        return self.cache_dir / f"{kind}_{digest}.{ext}"

    def _throttle(self) -> None:
        elapsed = time.time() - self._last_request
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)

    def _request(self, url: str) -> str:
        last_error: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            self._throttle()
            request = urllib.request.Request(url, headers=HEADERS)
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    self._last_request = time.time()
                    return response.read().decode("utf-8", errors="replace")
            except (urllib.error.URLError, TimeoutError) as exc:
                last_error = exc
                time.sleep(self.delay * attempt)
        assert last_error is not None
        raise last_error

    def fetch(self, url: str, kind: str, ext: str = "html") -> str:
        cache_file = self._cache_path(kind, url, ext)
        if cache_file.exists():
            return cache_file.read_text(encoding="utf-8")
        content = self._request(url)
        cache_file.write_text(content, encoding="utf-8")
        return content

    def fetch_json(self, url: str, kind: str) -> dict[str, Any]:
        cache_file = self._cache_path(kind, url, "json")
        if cache_file.exists():
            return json.loads(cache_file.read_text(encoding="utf-8"))
        content = self._request(url)
        payload = json.loads(content)
        cache_file.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return payload


def parse_total_team_matches(html: str) -> int | None:
    match = re.search(
        r"In totale la societ[aà]\s+.+?\s+ha giocato\s+(\d+)\s+partite",
        html,
        flags=re.IGNORECASE,
    )
    return int(match.group(1)) if match else None


def _column_index_by_metric(table) -> dict[str, int]:
    indexes: dict[str, int] = {}
    header_row = table.find("thead")
    if not header_row:
        return indexes
    for idx, header in enumerate(header_row.find_all("th")):
        header_html = str(header)
        if "sort/einsaetze" in header_html:
            indexes["appearances"] = idx
        elif "sort/tore" in header_html:
            indexes["goals"] = idx
    return indexes


def _cell_value(row, column_index: int | None) -> str | None:
    if column_index is None:
        return None
    cells = row.find_all("td", recursive=False)
    if column_index >= len(cells):
        return None
    return cells[column_index].get_text(strip=True)


def parse_national_team_page(html: str, team_code: str) -> NationalTeamData:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", class_="items")
    players: list[NationalPlayer] = []

    if table and table.find("tbody"):
        column_indexes = _column_index_by_metric(table)
        appearances_idx = column_indexes.get("appearances")
        goals_idx = column_indexes.get("goals")

        for row in table.find("tbody").find_all("tr", recursive=False):
            name_cell = row.find("td", class_="hauptlink")
            if not name_cell:
                continue
            link = name_cell.find("a", href=True)
            if not link:
                continue

            name = link.get("title") or link.get_text(strip=True)
            href = link["href"]
            player_id_match = re.search(r"/spieler/(\d+)", href)
            if not player_id_match:
                continue
            player_id = int(player_id_match.group(1))
            position = ""
            inline_table = name_cell.find_parent("table")
            if inline_table:
                inline_rows = inline_table.find_all("tr")
                if len(inline_rows) > 1:
                    position = inline_rows[1].get_text(strip=True)

            appearances_text = _cell_value(row, appearances_idx)
            goals_text = _cell_value(row, goals_idx)
            appearances = parse_int(appearances_text)
            goals = 0 if appearances_text and appearances_text.lower().startswith("non utilizzato") else parse_int(goals_text)

            players.append(
                NationalPlayer(
                    name=name,
                    normalized_name=normalize_name(name),
                    player_id=player_id,
                    player_url=f"{BASE_URL}{href}",
                    position=position,
                    appearances=appearances,
                    goals=goals,
                )
            )

    deduped: dict[int, NationalPlayer] = {}
    for player in players:
        deduped[player.player_id] = player

    return NationalTeamData(
        team_code=team_code,
        total_matches=parse_total_team_matches(html),
        players=list(deduped.values()),
    )


def match_player(
    fantapazz_name: str,
    roster: list[NationalPlayer],
    fanta_role: str | None = None,
    team_code: str | None = None,
) -> tuple[NationalPlayer | None, str]:
    if not roster:
        return None, "empty_roster"

    normalized_query = normalize_name(fantapazz_name)
    override_id = MANUAL_PLAYER_OVERRIDES.get(
        (team_code or "", fanta_role or "", normalized_query)
    )
    if override_id is not None:
        for player in roster:
            if player.player_id == override_id:
                return player, "matched_manual"

    alias_matches = [
        player for player in roster if normalized_query in player_aliases(player)
    ]
    if len(alias_matches) == 1:
        return alias_matches[0], "matched_alias"
    if len(alias_matches) > 1:
        unique_ids = {player.player_id for player in alias_matches}
        if len(unique_ids) == 1:
            return alias_matches[0], "matched_alias"
        compatible = [
            player
            for player in alias_matches
            if is_position_compatible(fanta_role, player.position)
        ]
        if len(compatible) == 1:
            return compatible[0], "matched_alias_position"
        return None, "ambiguous_alias"

    scored = [(player, match_score(fantapazz_name, player.name)) for player in roster]
    scored.sort(key=lambda item: item[1], reverse=True)
    best_player, best_score = scored[0]
    if not is_position_compatible(fanta_role, best_player.position):
        compatible_scored = [
            (player, score)
            for player, score in scored
            if is_position_compatible(fanta_role, player.position)
        ]
        if compatible_scored:
            best_player, best_score = compatible_scored[0]

    if best_score < FUZZY_THRESHOLD:
        return None, f"unmatched_fuzzy_{int(best_score * 100)}"

    close = [
        player
        for player, score in scored
        if score >= FUZZY_THRESHOLD and score >= best_score - 0.02
    ]
    if len(close) > 1:
        unique_ids = {player.player_id for player in close}
        if len(unique_ids) == 1:
            return close[0], (
                "matched_exact" if best_score >= 0.99 else f"matched_fuzzy_{int(best_score * 100)}"
            )
        compatible = [
            player for player in close if is_position_compatible(fanta_role, player.position)
        ]
        if len(compatible) == 1:
            return compatible[0], f"matched_fuzzy_position_{int(best_score * 100)}"
        return None, f"ambiguous_fuzzy_{int(best_score * 100)}"

    status = "matched_exact" if best_score >= 0.99 else f"matched_fuzzy_{int(best_score * 100)}"
    return best_player, status


def aggregate_club_goals(performance_payload: dict[str, Any], season_id: int) -> int:
    try:
        games = performance_payload["data"]["performance"]
    except (KeyError, TypeError):
        return 0

    total = 0
    for game in games:
        info = game.get("gameInformation", {})
        if info.get("seasonId") != season_id:
            continue
        if info.get("isNationalGame"):
            continue
        stats = game.get("statistics", {})
        general = stats.get("generalStatistics", {})
        if general.get("participationState") != "played":
            continue
        goals = stats.get("goalStatistics", {}).get("goalsScoredTotal")
        total += int(goals or 0)
    return total


def load_national_teams(client: TransfermarktClient) -> dict[str, NationalTeamData]:
    teams: dict[str, NationalTeamData] = {}
    for code, (slug, team_id) in TEAM_MAP.items():
        url = national_performance_url(slug, team_id)
        try:
            html = client.fetch(url, kind=f"national_{code}")
            teams[code] = parse_national_team_page(html, code)
            print(
                f"[national] {code}: {len(teams[code].players)} players, "
                f"{teams[code].total_matches} team matches"
            )
        except (urllib.error.URLError, TimeoutError) as exc:
            print(f"[national] {code}: FAILED ({exc})", file=sys.stderr)
            teams[code] = NationalTeamData(team_code=code, total_matches=None, players=[])
    return teams


def enrich_rows(
    rows: list[dict[str, str]],
    client: TransfermarktClient,
    national_teams: dict[str, NationalTeamData],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    enriched: list[dict[str, str]] = []
    unmatched: list[dict[str, str]] = []
    club_goal_cache: dict[int, int] = {}
    enrich_targets = [row for row in rows if row.get("fanta_role") in ENRICH_ROLES]
    processed_targets = 0

    for row in rows:
        out = {field: "" for field in OUTPUT_FIELDS}
        out.update({k: row.get(k, "") for k in ("fanta_role", "name", "team_name", "value")})

        if row.get("fanta_role") not in ENRICH_ROLES:
            out["transfermarkt_match_status"] = "skipped_role"
            enriched.append(out)
            continue

        team_code = row.get("team_name", "")
        team_data = national_teams.get(team_code)
        if not team_data:
            out["transfermarkt_match_status"] = "unknown_team"
            unmatched.append(
                {
                    "name": row["name"],
                    "team_name": team_code,
                    "fanta_role": row["fanta_role"],
                    "status": "unknown_team",
                }
            )
            enriched.append(out)
            continue

        player, status = match_player(
            row["name"],
            team_data.players,
            row.get("fanta_role"),
            team_code,
        )
        out["transfermarkt_match_status"] = status
        out["national_team_matches_current_season"] = (
            str(team_data.total_matches) if team_data.total_matches is not None else ""
        )

        if player is None:
            unmatched.append(
                {
                    "name": row["name"],
                    "team_name": team_code,
                    "fanta_role": row["fanta_role"],
                    "status": status,
                }
            )
            enriched.append(out)
            continue

        out["transfermarkt_player_url"] = player.player_url
        out["national_goals_current_season"] = (
            str(player.goals) if player.goals is not None else ""
        )
        out["national_appearances_current_season"] = (
            str(player.appearances) if player.appearances is not None else ""
        )

        if team_data.total_matches and player.appearances is not None:
            ratio = round(player.appearances / team_data.total_matches, 3)
            out["national_presence_ratio_current_season"] = str(ratio)

        if player.player_id not in club_goal_cache:
            api_url = f"{TMAPI_URL}/player/{player.player_id}/performance-game"
            try:
                payload = client.fetch_json(api_url, kind=f"player_perf_{player.player_id}")
                club_goal_cache[player.player_id] = aggregate_club_goals(payload, SEASON_ID)
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                print(
                    f"[club] {row['name']} ({player.player_id}): FAILED ({exc})",
                    file=sys.stderr,
                )
                club_goal_cache[player.player_id] = 0

        out["club_goals_current_season"] = str(club_goal_cache[player.player_id])
        processed_targets += 1
        if processed_targets % 50 == 0:
            print(
                f"[progress] processed {processed_targets}/{len(enrich_targets)} CB/M/ST players",
                flush=True,
            )
        enriched.append(out)

    return enriched, unmatched


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def print_summary(rows: list[dict[str, str]], unmatched: list[dict[str, str]]) -> None:
    enrichable = [r for r in rows if r["fanta_role"] in ENRICH_ROLES]
    matched = [
        r for r in enrichable if r["transfermarkt_match_status"].startswith("matched")
    ]
    failed = [r for r in enrichable if not r["transfermarkt_match_status"].startswith("matched")]

    print("\n=== Summary ===")
    print(f"Total rows: {len(rows)}")
    print(f"CB/M/ST rows: {len(enrichable)}")
    print(f"Matched: {len(matched)}")
    print(f"Unmatched/ambiguous: {len(failed)}")
    print(f"Unmatched report rows: {len(unmatched)}")

    status_counts: dict[str, int] = {}
    for row in enrichable:
        status = row["transfermarkt_match_status"]
        status_counts[status] = status_counts.get(status, 0) + 1
    print("\nStatus breakdown:")
    for status, count in sorted(status_counts.items(), key=lambda item: (-item[1], item[0])):
        print(f"  {status}: {count}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--unmatched", type=Path, default=DEFAULT_UNMATCHED)
    parser.add_argument("--delay", type=float, default=REQUEST_DELAY)
    args = parser.parse_args()

    rows = read_csv(args.input)
    client = TransfermarktClient(CACHE_DIR, delay=args.delay)
    national_teams = load_national_teams(client)
    enriched, unmatched = enrich_rows(rows, client, national_teams)
    write_csv(args.output, enriched, OUTPUT_FIELDS)
    write_csv(
        args.unmatched,
        unmatched,
        ["name", "team_name", "fanta_role", "status"],
    )
    print_summary(enriched, unmatched)
    print(f"\nWrote {args.output}")
    print(f"Wrote {args.unmatched}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
