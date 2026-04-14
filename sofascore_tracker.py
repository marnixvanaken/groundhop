#!/usr/bin/env python3
"""
Sofascore Match Tracker v2
Bijhouden welke voetbalwedstrijden je hebt bezocht, met rijke statistieken.
"""

import json
import os
import sys
import time
import random
import argparse
from datetime import datetime, timezone
from pathlib import Path

from curl_cffi import requests
from rich.console import Console

# Windows UTF-8 fix voor emoji's in terminal
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn
from rich.prompt import Prompt, Confirm
from rich.text import Text
from rich import box
from rich.columns import Columns
from rich.align import Align

# ─── Configuratie ────────────────────────────────────────────────────────────

BASE_URL = "https://www.sofascore.com/api/v1"
DATA_DIR = Path("data")
MATCH_CACHE_DIR = DATA_DIR / "match_cache"
PLAYER_CACHE_DIR = DATA_DIR / "player_cache"
PLAYER_NATIONAL_CACHE_DIR = DATA_DIR / "player_national_cache"
PLAYER_TRANSFER_CACHE_DIR = DATA_DIR / "player_transfer_cache"
SELECTED_MATCHES_FILE = DATA_DIR / "selected_matches.json"
MATCH_DATA_FILE = DATA_DIR / "match_data.json"
DASHBOARD_FILE = DATA_DIR / "dashboard_data.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "nl-NL,nl;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://www.sofascore.com/",
    "Origin": "https://www.sofascore.com",
}

MIN_DELAY = 3.0
MAX_DELAY = 5.5
RETRY_DELAY_MIN = 30
RETRY_DELAY_MAX = 60
MAX_RETRIES = 3

console = Console(legacy_windows=False)


# ─── Hulpfuncties ────────────────────────────────────────────────────────────

def setup_dirs():
    """Maak benodigde directories aan."""
    DATA_DIR.mkdir(exist_ok=True)
    MATCH_CACHE_DIR.mkdir(exist_ok=True)
    PLAYER_CACHE_DIR.mkdir(exist_ok=True)
    PLAYER_NATIONAL_CACHE_DIR.mkdir(exist_ok=True)
    PLAYER_TRANSFER_CACHE_DIR.mkdir(exist_ok=True)


PROGRESS_FILE = DATA_DIR / "sync_progress.json"

def write_progress(phase, current=0, total=0, label="", done=False):
    try:
        PROGRESS_FILE.write_text(json.dumps({
            "phase": phase, "current": current, "total": total,
            "label": label, "done": done,
            "pct": round(current / total * 100) if total else 0,
        }, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass

def wait(min_s=MIN_DELAY, max_s=MAX_DELAY):
    """Wacht een willekeurige tijd tussen requests."""
    delay = random.uniform(min_s, max_s)
    time.sleep(delay)


def api_get(url: str, params: dict = None, retry_count: int = 0) -> dict | None:
    """Voer een API request uit met retry logica."""
    try:
        resp = requests.get(url, headers=HEADERS, params=params, timeout=30, impersonate="chrome124")
        if resp.status_code == 200:
            return resp.json()
        elif resp.status_code in (403, 429):
            if retry_count < MAX_RETRIES:
                wacht = random.randint(RETRY_DELAY_MIN, RETRY_DELAY_MAX)
                console.print(f"[yellow]⚠ HTTP {resp.status_code} — wacht {wacht}s en probeer opnieuw...[/yellow]")
                time.sleep(wacht)
                return api_get(url, params, retry_count + 1)
            else:
                console.print(f"[red]✗ HTTP {resp.status_code} na {MAX_RETRIES} pogingen: {url}[/red]")
                return None
        elif resp.status_code == 404:
            return None
        else:
            console.print(f"[yellow]⚠ HTTP {resp.status_code}: {url}[/yellow]")
            return None
    except requests.RequestsError as e:
        if "timed out" in str(e).lower() or "timeout" in str(e).lower():
            if retry_count < MAX_RETRIES:
                console.print("[yellow]Timeout — wacht 10s en probeer opnieuw...[/yellow]")
                time.sleep(10)
                return api_get(url, params, retry_count + 1)
            return None
        console.print(f"[red]Verbindingsfout: {e}[/red]")
        return None
    except Exception as e_fallback:
        console.print(f"[red]Onbekende fout: {e_fallback}[/red]")
        return None


def load_json(path: Path) -> list | dict | None:
    """Laad JSON bestand als het bestaat."""
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            return None
    return None


def save_json(path: Path, data):
    """Sla data op als JSON bestand."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def ts_to_date(timestamp: int | None) -> str:
    """Converteer Unix timestamp naar YYYY-MM-DD string."""
    if not timestamp:
        return ""
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%d")


def ts_to_year(timestamp: int | None) -> int:
    """Geef het jaar terug van een Unix timestamp."""
    if not timestamp:
        return 0
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).year


def calc_age_on_date(birth_ts: int, match_ts: int) -> tuple[int, int]:
    """
    Bereken de leeftijd (jaren, resterende dagen) op de dag van de wedstrijd.
    Geeft (jaren, extra_dagen) terug.
    """
    if not birth_ts or not match_ts:
        return (0, 0)
    birth = datetime.fromtimestamp(birth_ts, tz=timezone.utc)
    match = datetime.fromtimestamp(match_ts, tz=timezone.utc)
    years = match.year - birth.year - ((match.month, match.day) < (birth.month, birth.day))
    try:
        birthday_this_year = birth.replace(year=match.year)
        if birthday_this_year > match:
            birthday_this_year = birth.replace(year=match.year - 1)
        extra_days = (match - birthday_this_year).days
    except ValueError:
        extra_days = 0
    return (years, extra_days)


def format_match_label(match: dict) -> str:
    """Maak een leesbaar wedstrijdlabel."""
    home = match.get("home_team", {}).get("name", "?")
    away = match.get("away_team", {}).get("name", "?")
    hs = match.get("home_score", "?")
    as_ = match.get("away_score", "?")
    return f"{home} {hs}-{as_} {away}"


# ─── API Wrappers ────────────────────────────────────────────────────────────

def search_teams(query: str) -> list:
    """Zoek teams via Sofascore API."""
    url = f"{BASE_URL}/search/teams/{query}"
    data = api_get(url)
    if not data:
        return []
    return data.get("teams", [])


def get_team_info(team_id: int) -> dict | None:
    """Haal team informatie op."""
    data = api_get(f"{BASE_URL}/team/{team_id}")
    if data:
        return data.get("team", data)
    return None


def get_team_tournaments(team_id: int) -> list:
    """Haal unieke competities op voor een team."""
    data = api_get(f"{BASE_URL}/team/{team_id}/unique-tournaments")
    if not data:
        return []
    return data.get("uniqueTournaments", [])


def get_team_events(team_id: int, from_year: int = 2009) -> list:
    """
    Haal alle gespeelde wedstrijden op voor een team via paginering.
    Stopt als we voorbij het startjaar zijn.
    """
    all_events = []
    page = 0
    stop = False

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("Wedstrijden ophalen...", total=None)

        while not stop:
            url = f"{BASE_URL}/team/{team_id}/events/last/{page}"
            data = api_get(url)

            if not data:
                break

            events = data.get("events", [])
            if not events:
                break

            for event in events:
                ts = event.get("startTimestamp", 0)
                year = ts_to_year(ts)
                if year < from_year:
                    stop = True
                    break
                all_events.append(event)

            progress.update(task, description=f"Wedstrijden ophalen... pagina {page+1} ({len(all_events)} gevonden)")

            if not stop:
                page += 1
                wait(1.5, 3.0)

    return all_events


def get_event_detail(event_id: int) -> dict | None:
    """Haal wedstrijd details op."""
    return api_get(f"{BASE_URL}/event/{event_id}")


def get_event_lineups(event_id: int) -> dict | None:
    """Haal opstellingen op."""
    return api_get(f"{BASE_URL}/event/{event_id}/lineups")


def get_event_incidents(event_id: int) -> dict | None:
    """Haal wedstrijd incidenten op."""
    return api_get(f"{BASE_URL}/event/{event_id}/incidents")


def get_event_statistics(event_id: int) -> dict | None:
    """Haal wedstrijd statistieken op."""
    return api_get(f"{BASE_URL}/event/{event_id}/statistics")


def get_event_shotmap(event_id: int) -> dict | None:
    """Haal schotkaart op."""
    return api_get(f"{BASE_URL}/event/{event_id}/shotmap")


def get_player_detail(player_id: int) -> dict | None:
    """Haal speler profiel op."""
    data = api_get(f"{BASE_URL}/player/{player_id}")
    if data:
        return data.get("player", data)
    return None


def get_player_national_stats(player_id: int) -> dict | None:
    """Haal nationale team statistieken op (caps, goals, debuut, land)."""
    data = api_get(f"{BASE_URL}/player/{player_id}/national-team-statistics")
    if not data or "statistics" not in data:
        return None
    stats_list = data["statistics"]
    if not stats_list:
        return None
    # Neem de eerste entry (primaire nationale ploeg)
    s = stats_list[0]
    return {
        "caps": s.get("appearances", 0),
        "goals": s.get("goals", 0),
        "debut_timestamp": s.get("debutTimestamp"),
        "team_name": s.get("team", {}).get("name"),
        "team_id": s.get("team", {}).get("id"),
        "team_alpha2": (s.get("team", {}).get("country", {}) or {}).get("alpha2"),
    }


def get_player_transfer_fee(player_id: int) -> int | None:
    """Haal hoogste transfersom op uit transfergeschiedenis."""
    data = api_get(f"{BASE_URL}/player/{player_id}/transfer-history")
    if not data or "transferHistory" not in data:
        return None
    fees = [t.get("transferFee") or 0 for t in data["transferHistory"]]
    max_fee = max(fees, default=None)
    return max_fee if max_fee else None


# ─── Data aggregatie hulpfuncties ────────────────────────────────────────────

def parse_event_to_match(event: dict) -> dict:
    """Parseer een raw event naar ons match formaat."""
    home_team = event.get("homeTeam", {})
    away_team = event.get("awayTeam", {})
    home_score_obj = event.get("homeScore", {})
    away_score_obj = event.get("awayScore", {})
    tournament = event.get("tournament", {})
    unique_t = tournament.get("uniqueTournament", {})
    season = event.get("season", {})
    round_info = event.get("roundInfo", {})
    venue = event.get("venue", {})
    referee = event.get("referee", {})

    return {
        "id": event.get("id"),
        "date": ts_to_date(event.get("startTimestamp")),
        "startTimestamp": event.get("startTimestamp"),
        "home_team": {"name": home_team.get("name", ""), "id": home_team.get("id"), "slug": home_team.get("slug", ""), "gender": home_team.get("gender", "M")},
        "away_team": {"name": away_team.get("name", ""), "id": away_team.get("id"), "slug": away_team.get("slug", ""), "gender": away_team.get("gender", "M")},
        "home_score": home_score_obj.get("current"),
        "away_score": away_score_obj.get("current"),
        "half_time": {
            "home": home_score_obj.get("period1"),
            "away": away_score_obj.get("period1"),
        },
        "tournament": unique_t.get("name", tournament.get("name", "")),
        "tournament_id": unique_t.get("id", tournament.get("id")),
        "season": season.get("name", ""),
        "season_id": season.get("id"),
        "round": round_info.get("round"),
        "venue": {
            "name": venue.get("name", venue.get("stadium", {}).get("name", "")) if isinstance(venue, dict) else "",
            "city": venue.get("city", {}).get("name", "") if isinstance(venue.get("city"), dict) else venue.get("city", "") if isinstance(venue, dict) else "",
            "id": venue.get("id") if isinstance(venue, dict) else None,
        } if venue else {},
        "attendance": event.get("attendance"),
        "referee": {
            "name": referee.get("name", "") if isinstance(referee, dict) else "",
            "id": referee.get("id") if isinstance(referee, dict) else None,
        } if referee else {},
    }


# ─── Menu opties ────────────────────────────────────────────────────────────

def menu_zoek_team():
    """Optie 1: Zoek team en selecteer wedstrijden."""
    console.print()
    query = Prompt.ask("[cyan]Voer teamnaam in[/cyan]")
    if not query.strip():
        return

    console.print(f"\n[dim]Zoeken naar '{query}'...[/dim]")
    results = search_teams(query.strip())

    if not results:
        console.print("[red]Geen resultaten gevonden.[/red]")
        return

    # Toon zoekresultaten
    table = Table(title=f"Zoekresultaten voor '{query}'", box=box.ROUNDED)
    table.add_column("#", style="bold cyan", width=4)
    table.add_column("Teamnaam", style="bold white")
    table.add_column("Land", style="green")
    table.add_column("ID", style="dim")

    for i, team in enumerate(results[:20], 1):
        country = team.get("country", {})
        country_name = country.get("name", "") if isinstance(country, dict) else ""
        table.add_row(
            str(i),
            team.get("name", ""),
            country_name,
            str(team.get("id", "")),
        )

    console.print(table)

    choice = Prompt.ask("Kies een team (nummer)")
    try:
        idx = int(choice) - 1
        if idx < 0 or idx >= len(results):
            console.print("[red]Ongeldige keuze.[/red]")
            return
        team = results[idx]
    except ValueError:
        console.print("[red]Ongeldige keuze.[/red]")
        return

    team_id = team["id"]
    team_name = team.get("name", "")
    console.print(f"\n[green]✓ Team geselecteerd: {team_name} (ID: {team_id})[/green]")

    # Haal competities op
    wait(2, 3)
    console.print("[dim]Competities ophalen...[/dim]")
    tournaments = get_team_tournaments(team_id)

    if not tournaments:
        console.print("[yellow]⚠ Geen competities gevonden, ga toch door met alle wedstrijden.[/yellow]")
        chosen_tournament_ids = None
    else:
        t_table = Table(title=f"Competities voor {team_name}", box=box.SIMPLE)
        t_table.add_column("#", style="cyan", width=4)
        t_table.add_column("Competitie", style="white")
        t_table.add_column("ID", style="dim")

        for i, t in enumerate(tournaments, 1):
            t_table.add_row(str(i), t.get("name", ""), str(t.get("id", "")))

        console.print(t_table)
        console.print("[dim]Kies competitie(s) (komma-gescheiden nummers) of 'a' voor alle:[/dim]")
        t_choice = Prompt.ask("Keuze")

        chosen_tournament_ids = None
        if t_choice.strip().lower() != "a":
            try:
                chosen_nums = [int(x.strip()) - 1 for x in t_choice.split(",")]
                chosen_tournaments = [tournaments[n] for n in chosen_nums if 0 <= n < len(tournaments)]
                chosen_tournament_ids = {t["id"] for t in chosen_tournaments}
                chosen_names = [t.get("name", "") for t in chosen_tournaments]
                console.print(f"[green]✓ Geselecteerd: {', '.join(chosen_names)}[/green]")
            except (ValueError, IndexError):
                console.print("[yellow]⚠ Ongeldige invoer — alle competities worden gebruikt.[/yellow]")

    # Startjaar
    from_year_str = Prompt.ask("Vanaf welk jaar?", default="2009")
    try:
        from_year = int(from_year_str)
    except ValueError:
        from_year = 2009

    # Haal wedstrijden op
    console.print(f"\n[dim]Wedstrijden ophalen vanaf {from_year}...[/dim]")
    wait(2, 3)
    all_events = get_team_events(team_id, from_year)

    if not all_events:
        console.print("[red]Geen wedstrijden gevonden.[/red]")
        return

    # Filter op competities
    if chosen_tournament_ids:
        filtered = []
        for e in all_events:
            t_obj = e.get("tournament", {})
            ut = t_obj.get("uniqueTournament", {})
            tid = ut.get("id") or t_obj.get("id")
            if tid in chosen_tournament_ids:
                filtered.append(e)
        all_events = filtered

    if not all_events:
        console.print("[red]Geen wedstrijden gevonden na filtering.[/red]")
        return

    # Groepeer per seizoen
    seasons_map: dict[str, list] = {}
    for e in all_events:
        s = e.get("season", {}).get("name", "Onbekend")
        if s not in seasons_map:
            seasons_map[s] = []
        seasons_map[s].append(e)

    # Sorteer seizoenen recent → oud
    sorted_seasons = sorted(seasons_map.keys(), reverse=True)

    # Toon per seizoen + laat gebruiker kiezen
    all_numbered: list[dict] = []  # (nummer, event)

    for season_name in sorted_seasons:
        events_in_season = seasons_map[season_name]
        t_name = ""
        if events_in_season:
            t_obj = events_in_season[0].get("tournament", {})
            ut = t_obj.get("uniqueTournament", {})
            t_name = ut.get("name", t_obj.get("name", ""))

        console.print(f"\n[bold yellow]═══ Seizoen {season_name} — {t_name} ═══[/bold yellow]")

        for e in events_in_season:
            num = len(all_numbered) + 1
            date_str = ts_to_date(e.get("startTimestamp"))
            home = e.get("homeTeam", {}).get("name", "?")
            away = e.get("awayTeam", {}).get("name", "?")
            hs = e.get("homeScore", {}).get("current", "?")
            as_ = e.get("awayScore", {}).get("current", "?")
            console.print(f"  [dim]{num:3}.[/dim]  {date_str}  [white]{home} {hs}-{as_} {away}[/white]")
            all_numbered.append(e)

    console.print()
    console.print("[dim]Selecteer wedstrijden (nummers komma-gescheiden, 'all' voor alle, 'none' om over te slaan):[/dim]")
    sel_input = Prompt.ask("Selectie").strip().lower()

    selected_indices = []
    if sel_input == "all":
        selected_indices = list(range(len(all_numbered)))
    elif sel_input == "none" or sel_input == "":
        pass
    else:
        try:
            selected_indices = [int(x.strip()) - 1 for x in sel_input.split(",") if x.strip()]
        except ValueError:
            console.print("[red]Ongeldige invoer.[/red]")
            return

    if not selected_indices:
        console.print("[yellow]Geen wedstrijden geselecteerd.[/yellow]")
        return

    # Laad bestaande selectie
    existing = load_json(SELECTED_MATCHES_FILE) or []
    existing_ids = {m["id"] for m in existing if isinstance(m, dict) and "id" in m}

    added = 0
    skipped_dup = 0
    for idx in selected_indices:
        if idx < 0 or idx >= len(all_numbered):
            continue
        event = all_numbered[idx]
        event_id = event.get("id")
        if event_id in existing_ids:
            skipped_dup += 1
            continue
        parsed = parse_event_to_match(event)
        parsed["source_team"] = team_name
        existing.append(parsed)
        existing_ids.add(event_id)
        added += 1

    save_json(SELECTED_MATCHES_FILE, existing)
    console.print(f"\n[green]✓ {added} wedstrijden toegevoegd[/green]" +
                  (f" [dim]({skipped_dup} duplicaten overgeslagen)[/dim]" if skipped_dup else ""))


def menu_bekijk_selectie():
    """Optie 2: Bekijk geselecteerde wedstrijden."""
    data = load_json(SELECTED_MATCHES_FILE) or []
    if not data:
        console.print("[yellow]Nog geen wedstrijden geselecteerd.[/yellow]")
        return

    # Groepeer per seizoen
    seasons: dict[str, list] = {}
    for m in data:
        s = m.get("season", "Onbekend")
        if s not in seasons:
            seasons[s] = []
        seasons[s].append(m)

    console.print(f"\n[bold green]Totaal geselecteerd: {len(data)} wedstrijden[/bold green]\n")

    for season_name in sorted(seasons.keys(), reverse=True):
        matches = seasons[season_name]
        console.print(f"[bold yellow]{season_name}[/bold yellow] ({len(matches)} wedstrijden)")
        for m in matches:
            cached = (MATCH_CACHE_DIR / str(m["id"]) / "event.json").exists()
            cache_indicator = "[green]✓[/green]" if cached else "[dim]○[/dim]"
            console.print(f"  {cache_indicator} {m.get('date', '')}  {format_match_label(m)}")
        console.print()


def menu_download_data():
    """Optie 3: Download wedstrijddata."""
    selected = load_json(SELECTED_MATCHES_FILE) or []
    if not selected:
        console.print("[yellow]Geen wedstrijden geselecteerd. Gebruik optie 1 eerst.[/yellow]")
        return

    skipped_log = []
    total = len(selected)

    console.print(f"\n[bold]Wedstrijddata downloaden voor {total} wedstrijden...[/bold]")
    console.print("[dim]Cache-hits worden overgeslagen.[/dim]\n")

    for i, match in enumerate(selected, 1):
        event_id = match.get("id")
        if not event_id:
            continue

        cache_dir = MATCH_CACHE_DIR / str(event_id)
        label = format_match_label(match)
        date_str = match.get("date", "")

        # Controleer of alles al gecached is
        all_cached = all([
            (cache_dir / "event.json").exists(),
            (cache_dir / "lineups.json").exists(),
            (cache_dir / "incidents.json").exists(),
            (cache_dir / "statistics.json").exists(),
        ])

        write_progress("matches", i, total, label)

        if all_cached:
            console.print(f"[dim][{i}/{total}] {date_str} {label} — [green]cache ✓[/green][/dim]")
            continue

        cache_dir.mkdir(parents=True, exist_ok=True)
        status_parts = []

        console.print(f"[bold][{i}/{total}][/bold] [cyan]{date_str} {label}[/cyan]")

        # Event details
        event_file = cache_dir / "event.json"
        if not event_file.exists():
            wait()
            data = get_event_detail(event_id)
            if data:
                save_json(event_file, data)
                # Update match met extra velden uit detail
                event_obj = data.get("event", data)
                if event_obj:
                    ref = event_obj.get("referee", {})
                    if ref and isinstance(ref, dict):
                        match["referee"] = {"name": ref.get("name", ""), "id": ref.get("id")}
                    venue = event_obj.get("venue", {})
                    if venue and isinstance(venue, dict):
                        match["venue"] = {
                            "name": venue.get("stadium", {}).get("name", venue.get("name", "")) if isinstance(venue.get("stadium"), dict) else venue.get("name", ""),
                            "city": venue.get("city", {}).get("name", "") if isinstance(venue.get("city"), dict) else venue.get("city", ""),
                            "id": venue.get("id"),
                        }
                    att = event_obj.get("attendance")
                    if att:
                        match["attendance"] = att
                status_parts.append("[green]event ✓[/green]")
            else:
                status_parts.append("[red]event ✗[/red]")
                skipped_log.append(f"event — {label}")

        # Lineups
        lineups_file = cache_dir / "lineups.json"
        if not lineups_file.exists():
            wait()
            data = get_event_lineups(event_id)
            if data:
                save_json(lineups_file, data)
                status_parts.append("[green]lineups ✓[/green]")
            else:
                status_parts.append("[red]lineups ✗[/red]")
                skipped_log.append(f"lineups — {label}")

        # Incidents
        incidents_file = cache_dir / "incidents.json"
        if not incidents_file.exists():
            wait()
            data = get_event_incidents(event_id)
            if data:
                save_json(incidents_file, data)
                status_parts.append("[green]incidents ✓[/green]")
            else:
                status_parts.append("[red]incidents ✗[/red]")
                skipped_log.append(f"incidents — {label}")

        # Statistics
        stats_file = cache_dir / "statistics.json"
        if not stats_file.exists():
            wait()
            data = get_event_statistics(event_id)
            if data:
                save_json(stats_file, data)
                status_parts.append("[green]statistics ✓[/green]")
            else:
                status_parts.append("[red]statistics ✗[/red]")
                skipped_log.append(f"statistics — {label}")

        console.print("         " + "  ".join(status_parts))

    # Sla bijgewerkte selected_matches op (met extra velden)
    save_json(SELECTED_MATCHES_FILE, selected)

    if skipped_log:
        console.print(f"\n[yellow]⚠ Overgeslagen ({len(skipped_log)}):[/yellow]")
        for s in skipped_log[:20]:
            console.print(f"  [dim]- {s}[/dim]")

    console.print(f"\n[green]✓ Download compleet![/green]")


def menu_download_spelers():
    """Optie 4: Download spelerprofielen."""
    # Verzamel alle unieke speler IDs
    selected = load_json(SELECTED_MATCHES_FILE) or []
    if not selected:
        console.print("[yellow]Geen wedstrijden geselecteerd.[/yellow]")
        return

    player_ids = set()
    for match in selected:
        event_id = match.get("id")
        if not event_id:
            continue
        lineups_file = MATCH_CACHE_DIR / str(event_id) / "lineups.json"
        lineups = load_json(lineups_file)
        if not lineups:
            continue
        for side in ("home", "away"):
            side_data = lineups.get(side, {})
            for player_entry in side_data.get("players", []):
                pid = player_entry.get("player", {}).get("id")
                if pid:
                    player_ids.add(pid)

    if not player_ids:
        console.print("[yellow]Geen spelers gevonden in gecachte lineups. Download wedstrijddata eerst (optie 3).[/yellow]")
        return

    # Filter al gecachte spelers
    to_download = [pid for pid in player_ids if not (PLAYER_CACHE_DIR / f"{pid}.json").exists()]

    console.print(f"\n[bold]Spelerprofielen downloaden:[/bold]")
    console.print(f"  Totaal unieke spelers: {len(player_ids)}")
    console.print(f"  Al gecached: {len(player_ids) - len(to_download)}")
    console.print(f"  Te downloaden: {len(to_download)}")

    if not to_download:
        console.print("[green]✓ Alle spelers al gecached![/green]")
        return

    est_minutes = (len(to_download) * (MIN_DELAY + MAX_DELAY) / 2) / 60
    console.print(f"  Geschatte tijd: ~{est_minutes:.0f} minuten\n")

    try:
        if not Confirm.ask("Doorgaan?"):
            return
    except EOFError:
        pass  # non-interactief: gewoon doorgaan

    skipped_log = []

    for i, player_id in enumerate(to_download, 1):
        remaining = len(to_download) - i
        est_remaining = (remaining * (MIN_DELAY + MAX_DELAY) / 2) / 60

        write_progress("players", i, len(to_download), f"~{est_remaining:.0f} min resterend")

        wait()
        data = get_player_detail(player_id)

        if data:
            save_json(PLAYER_CACHE_DIR / f"{player_id}.json", data)
            name = data.get("name", str(player_id))
            console.print(f"[dim][{i}/{len(to_download)}][/dim] [white]{name}[/white] [green]✓[/green]  [dim]~{est_remaining:.0f} min resterend[/dim]")
        else:
            skipped_log.append(str(player_id))
            console.print(f"[dim][{i}/{len(to_download)}][/dim] [red]✗ Player {player_id}[/red]")

    if skipped_log:
        console.print(f"\n[yellow]⚠ Overgeslagen: {len(skipped_log)} spelers[/yellow]")

    write_progress("players", len(to_download), len(to_download), "Klaar", done=True)
    console.print(f"\n[green]✓ Download spelerprofielen compleet![/green]")

    # ─── Nationale team stats + transfergeschiedenis ─────────────────────────
    all_pids = list(player_ids)
    natl_todo = [pid for pid in all_pids if not (PLAYER_NATIONAL_CACHE_DIR / f"{pid}.json").exists()]
    transfer_todo = [pid for pid in all_pids if not (PLAYER_TRANSFER_CACHE_DIR / f"{pid}.json").exists()]
    extra_todo = list(set(natl_todo) | set(transfer_todo))

    if extra_todo:
        console.print(f"\n[bold]Nationale stats + transferdata downloaden:[/bold]")
        console.print(f"  Nationale stats: {len(natl_todo)} te downloaden")
        console.print(f"  Transferdata:    {len(transfer_todo)} te downloaden\n")
        for i, pid in enumerate(extra_todo, 1):
            wait()
            if pid in natl_todo:
                natl = get_player_national_stats(pid)
                save_json(PLAYER_NATIONAL_CACHE_DIR / f"{pid}.json", natl or {})
            if pid in transfer_todo:
                fee = get_player_transfer_fee(pid)
                save_json(PLAYER_TRANSFER_CACHE_DIR / f"{pid}.json", {"max_transfer_fee": fee})
            console.print(f"[dim][{i}/{len(extra_todo)}][/dim] pid {pid} [green]✓[/green]")
        console.print(f"\n[green]✓ Nationale stats + transferdata compleet![/green]")


def menu_stats_overzicht():
    """Optie 5: Bekijk stats overzicht."""
    selected = load_json(SELECTED_MATCHES_FILE) or []
    if not selected:
        console.print("[yellow]Geen wedstrijden geselecteerd.[/yellow]")
        return

    total = len(selected)
    cached = sum(1 for m in selected if (MATCH_CACHE_DIR / str(m.get("id", 0)) / "event.json").exists())
    player_cached = len(list(PLAYER_CACHE_DIR.glob("*.json")))

    t = Table(title="Stats Overzicht", box=box.ROUNDED)
    t.add_column("Categorie", style="cyan")
    t.add_column("Waarde", style="bold white", justify="right")

    t.add_row("Geselecteerde wedstrijden", str(total))
    t.add_row("Wedstrijden gecached", f"{cached}/{total}")
    t.add_row("Spelerprofielen gecached", str(player_cached))
    t.add_row("Dashboard JSON aanwezig", "[green]Ja[/green]" if DASHBOARD_FILE.exists() else "[red]Nee[/red]")

    if selected:
        dates = [m.get("date", "") for m in selected if m.get("date")]
        if dates:
            t.add_row("Eerste wedstrijd", min(dates))
            t.add_row("Laatste wedstrijd", max(dates))

    # Seizoenen
    seasons = set(m.get("season", "") for m in selected if m.get("season"))
    t.add_row("Aantal seizoenen", str(len(seasons)))

    # Competities
    tournaments = set(m.get("tournament", "") for m in selected if m.get("tournament"))
    t.add_row("Competities", str(len(tournaments)))

    console.print()
    console.print(t)

    if tournaments:
        console.print("\n[bold]Competities:[/bold]")
        for t_name in sorted(tournaments):
            count = sum(1 for m in selected if m.get("tournament") == t_name)
            console.print(f"  [cyan]{t_name}[/cyan]: {count}")


def menu_exporteer_dashboard():
    """Optie 6: Exporteer dashboard JSON."""
    selected = load_json(SELECTED_MATCHES_FILE) or []
    if not selected:
        console.print("[yellow]Geen wedstrijden geselecteerd.[/yellow]")
        return

    console.print("\n[bold]Dashboard JSON samenstellen...[/bold]")

    # ─── Matches verrijken met gecachte data ────────────────────────────────
    matches_out = []
    all_player_stats: dict[int, dict] = {}  # player_id → geaggregeerde stats
    all_referees: dict[int, dict] = {}
    all_venues: dict[int, dict] = {}
    all_teams_visited: dict[int, dict] = {}
    all_tournaments: dict[int, dict] = {}
    all_seasons: dict[str, int] = {}

    for match in selected:
        event_id = match.get("id")
        if not event_id:
            continue

        cache_dir = MATCH_CACHE_DIR / str(event_id)

        # Basisdata
        m_out = dict(match)

        # Verrijk met event detail
        event_detail = load_json(cache_dir / "event.json")
        if event_detail:
            ev = event_detail.get("event", event_detail)
            if ev:
                ref = ev.get("referee", {})
                if ref and isinstance(ref, dict):
                    m_out["referee"] = {
                        "name": ref.get("name", ""),
                        "id": ref.get("id"),
                        "country": ref.get("country", {}).get("name", "") if isinstance(ref.get("country"), dict) else "",
                    }
                venue = ev.get("venue", {})
                if venue and isinstance(venue, dict):
                    stadium = venue.get("stadium", {})
                    venue_name = stadium.get("name", venue.get("name", "")) if isinstance(stadium, dict) else venue.get("name", "")
                    city_obj = venue.get("city", {})
                    city_name = city_obj.get("name", "") if isinstance(city_obj, dict) else str(city_obj) if city_obj else ""
                    m_out["venue"] = {
                        "name": venue_name,
                        "city": city_name,
                        "id": venue.get("id"),
                    }
                if ev.get("attendance"):
                    m_out["attendance"] = ev["attendance"]

        # Goals, kaarten, wissels
        incidents_raw = load_json(cache_dir / "incidents.json")
        goals = []
        cards = []
        substitutions = []

        if incidents_raw:
            for inc in incidents_raw.get("incidents", []):
                inc_type = inc.get("incidentType", "")
                if inc_type == "goal":
                    player = inc.get("player", {}) or {}
                    assist = inc.get("assist1", {}) or {}
                    goals.append({
                        "player": player.get("name", ""),
                        "player_id": player.get("id"),
                        "team": match.get("home_team", {}).get("name", "") if inc.get("isHome") else match.get("away_team", {}).get("name", ""),
                        "minute": inc.get("time"),
                        "added_time": inc.get("addedTime"),
                        "assist": assist.get("name", "") if assist else None,
                        "assist_id": assist.get("id") if assist else None,
                        "type": inc.get("incidentClass", "regular"),
                    })
                elif inc_type == "card":
                    player = inc.get("player", {}) or {}
                    cards.append({
                        "player": player.get("name", ""),
                        "player_id": player.get("id"),
                        "team": match.get("home_team", {}).get("name", "") if inc.get("isHome") else match.get("away_team", {}).get("name", ""),
                        "minute": inc.get("time"),
                        "added_time": inc.get("addedTime"),
                        "type": inc.get("incidentClass", "yellow"),
                        "reason": inc.get("reason", ""),
                    })
                elif inc_type == "substitution":
                    pin = inc.get("playerIn", {}) or {}
                    pout = inc.get("playerOut", {}) or {}
                    substitutions.append({
                        "player_in": pin.get("name", ""),
                        "player_in_id": pin.get("id"),
                        "player_out": pout.get("name", ""),
                        "player_out_id": pout.get("id"),
                        "team": match.get("home_team", {}).get("name", "") if inc.get("isHome") else match.get("away_team", {}).get("name", ""),
                        "minute": inc.get("time"),
                        "added_time": inc.get("addedTime"),
                    })

        if incidents_raw:
            m_out["goals"] = goals
            m_out["cards"] = cards
            m_out["substitutions"] = substitutions
        # else: keep data already in m_out from selected_matches.json

        # Team statistieken
        stats_raw = load_json(cache_dir / "statistics.json")
        team_stats = {"home": {}, "away": {}}
        if stats_raw:
            periods = stats_raw.get("statistics", [])
            for period in periods:
                if period.get("period") != "ALL":
                    continue
                for group in period.get("groups", []):
                    for item in group.get("statisticsItems", []):
                        key = item.get("name", "").lower().replace(" ", "_")
                        if key:
                            try:
                                team_stats["home"][key] = float(item.get("home", 0) or 0)
                                team_stats["away"][key] = float(item.get("away", 0) or 0)
                            except (ValueError, TypeError):
                                pass
        m_out["team_stats"] = team_stats

        # Spelers uit lineups
        lineups_raw = load_json(cache_dir / "lineups.json")
        match_ts = match.get("startTimestamp", 0)

        if lineups_raw:
            for side in ("home", "away"):
                side_data = lineups_raw.get(side, {})
                team_name = match.get(f"{side}_team", {}).get("name", "")
                team_gender = match.get(f"{side}_team", {}).get("gender", "M")

                for pe in side_data.get("players", []):
                    player_obj = pe.get("player", {}) or {}
                    stats_obj = pe.get("statistics", {}) or {}

                    pid = player_obj.get("id")
                    if not pid:
                        continue

                    # Laad profiel uit cache
                    profile = load_json(PLAYER_CACHE_DIR / f"{pid}.json") or {}

                    dob_ts = player_obj.get("dateOfBirthTimestamp") or profile.get("dateOfBirthTimestamp")
                    age_years, age_days = calc_age_on_date(dob_ts, match_ts) if dob_ts and match_ts else (0, 0)

                    is_starter = not pe.get("substitute", stats_obj.get("substitute", False))
                    goals_scored = stats_obj.get("goals", 0) or 0
                    assists = stats_obj.get("goalAssist", 0) or 0
                    rating = stats_obj.get("rating")
                    minutes = stats_obj.get("minutesPlayed", 0) or 0
                    yellow = sum(1 for c in cards if c.get("player_id") == pid and c.get("type") == "yellow")
                    red = sum(1 for c in cards if c.get("player_id") == pid and c.get("type") in ("red", "yellowRed"))

                    match_detail = {
                        "match_id": event_id,
                        "date": match.get("date", ""),
                        "match_label": format_match_label(match),
                        "team": team_name,
                        "goals": goals_scored,
                        "assists": assists,
                        "yellow": yellow,
                        "red": red,
                        "minutes": minutes,
                        "rating": rating,
                        "starter": is_starter,
                        "xg": stats_obj.get("expectedGoals"),
                        "age_years": age_years,
                        "age_days": age_days,
                    }

                    if pid not in all_player_stats:
                        nationality = profile.get("country", {})
                        nat_name = nationality.get("name", "") if isinstance(nationality, dict) else ""
                        nat_a2 = nationality.get("alpha2", "") if isinstance(nationality, dict) else ""
                        preferred_foot = profile.get("preferredFoot", player_obj.get("preferredFoot", ""))

                        all_player_stats[pid] = {
                            "id": pid,
                            "name": player_obj.get("name", profile.get("name", "")),
                            "short_name": player_obj.get("shortName", profile.get("shortName", "")),
                            "photo_url": f"https://api.sofascore.app/api/v1/player/{pid}/image",
                            "date_of_birth": ts_to_date(dob_ts) if dob_ts else None,
                            "nationality": nat_name or (player_obj.get("country", {}) or {}).get("name", ""),
                            "nationality_alpha2": (nat_a2 or (player_obj.get("country", {}) or {}).get("alpha2", "")).lower(),
                            "height_cm": profile.get("height", player_obj.get("height")),
                            "weight_kg": profile.get("weight"),
                            "market_value": (profile.get("proposedMarketValueRaw") or {}).get("value") or profile.get("proposedMarketValue"),
                            "gender": team_gender,
                            "preferred_foot": preferred_foot,
                            "position": player_obj.get("position", profile.get("position", "")),
                            "teams_seen_for": [],
                            "matches_seen": 0,
                            "goals": 0,
                            "assists": 0,
                            "yellow_cards": 0,
                            "red_cards": 0,
                            "minutes_played": 0,
                            "sub_appearances": 0,
                            "starter_appearances": 0,
                            "bench_appearances": 0,
                            "rating_sum": 0.0,
                            "rating_count": 0,
                            "avg_rating": None,
                            "total_shots": 0,
                            "shots_on_target": 0,
                            "total_passes": 0,
                            "passes_accurate": 0,
                            "pass_accuracy_pct": None,
                            "key_passes": 0,
                            "tackles": 0,
                            "interceptions": 0,
                            "duels_won": 0,
                            "duels_lost": 0,
                            "fouls_committed": 0,
                            "fouls_drawn": 0,
                            "xg_total": 0.0,
                            "was_captain_count": 0,
                            "youngest_age_seen": None,
                            "oldest_age_seen": None,
                            "matches_detail": [],
                        }

                    ps = all_player_stats[pid]
                    if team_gender == "F":
                        ps["gender"] = "F"
                    ps["matches_seen"] += 1
                    ps["goals"] += goals_scored
                    ps["assists"] += assists
                    ps["yellow_cards"] += yellow
                    ps["red_cards"] += red
                    ps["minutes_played"] += minutes
                    ps["total_shots"] += stats_obj.get("totalShots", 0) or 0
                    ps["shots_on_target"] += stats_obj.get("shotsOnTarget", 0) or 0
                    ps["total_passes"] += stats_obj.get("totalPass", 0) or 0
                    ps["passes_accurate"] += stats_obj.get("accuratePass", 0) or 0
                    ps["key_passes"] += stats_obj.get("keyPass", 0) or 0
                    ps["tackles"] += stats_obj.get("tackles", 0) or 0
                    ps["interceptions"] += stats_obj.get("interceptions", 0) or 0
                    ps["duels_won"] += stats_obj.get("duelWon", 0) or 0
                    ps["duels_lost"] += stats_obj.get("duelLost", 0) or 0
                    ps["fouls_committed"] += stats_obj.get("fouls", 0) or 0
                    ps["fouls_drawn"] += stats_obj.get("wasFouled", 0) or 0
                    ps["xg_total"] += float(stats_obj.get("expectedGoals", 0) or 0)
                    if stats_obj.get("captain"):
                        ps["was_captain_count"] += 1
                    if is_starter:
                        ps["starter_appearances"] += 1
                    elif minutes > 0:
                        ps["sub_appearances"] += 1
                    else:
                        ps["bench_appearances"] += 1
                    if rating:
                        ps["rating_sum"] += float(rating)
                        ps["rating_count"] += 1
                    if team_name and team_name not in ps["teams_seen_for"]:
                        ps["teams_seen_for"].append(team_name)

                    # Leeftijd tracking
                    if age_years > 0 or age_days > 0:
                        age_entry = {"age_years": age_years, "age_days": age_days, "match_date": match.get("date", ""), "match": format_match_label(match)}
                        if ps["youngest_age_seen"] is None or (age_years, age_days) < (ps["youngest_age_seen"]["age_years"], ps["youngest_age_seen"]["age_days"]):
                            ps["youngest_age_seen"] = age_entry
                        if ps["oldest_age_seen"] is None or (age_years, age_days) > (ps["oldest_age_seen"]["age_years"], ps["oldest_age_seen"]["age_days"]):
                            ps["oldest_age_seen"] = age_entry

                    ps["matches_detail"].append(match_detail)

        # Spelers uit goals/cards/subs als er geen lineup-cache is (handmatige entries)
        if not lineups_raw:
            manual_players: dict[int, dict] = {}  # pid → {name, team, goals, assists, minutes, starter}

            # Seed met lineup veld indien aanwezig (starters + bank)
            manual_lineup = match.get("lineup", {})
            for side in ("home", "away"):
                team_name = match.get(f"{side}_team", {}).get("name", "")
                for pe in manual_lineup.get(side, []):
                    pid = pe.get("player_id")
                    if pid:
                        manual_players.setdefault(pid, {"name": pe.get("player", ""), "team": team_name, "goals": 0, "assists": 0})

            # Bouw minuten/starter op basis van wisseldata
            subbed_out: dict[int, int] = {}   # pid → minuut uit het veld
            subbed_in:  dict[int, int] = {}   # pid → minuut het veld op
            for s in m_out.get("substitutions", []):
                if s.get("player_out_id") and s.get("minute"):
                    subbed_out[s["player_out_id"]] = s["minute"]
                if s.get("player_in_id") and s.get("minute"):
                    subbed_in[s["player_in_id"]] = s["minute"]

            def get_minutes(pid):
                if pid in subbed_in:
                    return 90 - subbed_in[pid]
                if pid in subbed_out:
                    return subbed_out[pid]
                return 90

            # Bankspelers uit lineup: nooit ingevallen → bench, niet starter
            bench_ids = set()
            for side in ("home", "away"):
                for pe in manual_lineup.get(side, []):
                    if not pe.get("starter", True) and pe.get("player_id") not in subbed_in:
                        bench_ids.add(pe.get("player_id"))

            def is_starter(pid):
                if pid in bench_ids:
                    return None  # bench, geen minuten
                return pid not in subbed_in

            for g in m_out.get("goals", []):
                if g.get("player_id"):
                    manual_players.setdefault(g["player_id"], {"name": g["player"], "team": g["team"], "goals": 0, "assists": 0})
                if g.get("assist_id"):
                    manual_players.setdefault(g["assist_id"], {"name": g["assist"], "team": g["team"], "goals": 0, "assists": 0})
            for g in m_out.get("goals", []):
                if g.get("player_id") and g["player_id"] in manual_players:
                    manual_players[g["player_id"]]["goals"] += 1
                if g.get("assist_id") and g["assist_id"] in manual_players:
                    manual_players[g["assist_id"]]["assists"] += 1
            for c in m_out.get("cards", []):
                if c.get("player_id"):
                    manual_players.setdefault(c["player_id"], {"name": c["player"], "team": c["team"], "goals": 0, "assists": 0})
            for s in m_out.get("substitutions", []):
                if s.get("player_in_id"):
                    manual_players.setdefault(s["player_in_id"], {"name": s["player_in"], "team": s["team"], "goals": 0, "assists": 0})
                if s.get("player_out_id"):
                    manual_players.setdefault(s["player_out_id"], {"name": s["player_out"], "team": s["team"], "goals": 0, "assists": 0})

            for pid, info in manual_players.items():
                profile = load_json(PLAYER_CACHE_DIR / f"{pid}.json") or {}
                dob_ts = profile.get("dateOfBirthTimestamp")
                age_years, age_days = calc_age_on_date(dob_ts, match_ts) if dob_ts and match_ts else (0, 0)
                nationality = profile.get("country", {})
                nat_name = nationality.get("name", "") if isinstance(nationality, dict) else ""
                nat_a2 = nationality.get("alpha2", "") if isinstance(nationality, dict) else ""
                yellow = sum(1 for c in m_out.get("cards", []) if c.get("player_id") == pid and c.get("type") == "yellow")
                red = sum(1 for c in m_out.get("cards", []) if c.get("player_id") == pid and c.get("type") in ("red", "yellowRed"))

                p_starter = is_starter(pid)  # True=starter, False=sub, None=bench
                p_minutes = 0 if p_starter is None else get_minutes(pid)

                match_detail = {
                    "match_id": event_id,
                    "date": match.get("date", ""),
                    "match_label": format_match_label(match),
                    "team": info["team"],
                    "goals": info["goals"],
                    "assists": info["assists"],
                    "yellow": yellow,
                    "red": red,
                    "minutes": p_minutes,
                    "rating": None,
                    "starter": False if p_starter is None else p_starter,
                    "xg": None,
                    "age_years": age_years,
                    "age_days": age_days,
                }

                if pid not in all_player_stats:
                    all_player_stats[pid] = {
                        "id": pid,
                        "name": info["name"] or profile.get("name", ""),
                        "short_name": profile.get("shortName", ""),
                        "photo_url": f"https://api.sofascore.app/api/v1/player/{pid}/image",
                        "date_of_birth": ts_to_date(dob_ts) if dob_ts else None,
                        "nationality": nat_name,
                        "nationality_alpha2": nat_a2.lower(),
                        "height_cm": profile.get("height"),
                        "weight_kg": profile.get("weight"),
                        "market_value": (profile.get("proposedMarketValueRaw") or {}).get("value") or profile.get("proposedMarketValue"),
                        "gender": "M",
                        "preferred_foot": profile.get("preferredFoot", ""),
                        "position": profile.get("position", ""),
                        "teams_seen_for": [],
                        "matches_seen": 0,
                        "goals": 0,
                        "assists": 0,
                        "yellow_cards": 0,
                        "red_cards": 0,
                        "minutes_played": 0,
                        "sub_appearances": 0,
                        "starter_appearances": 0,
                        "bench_appearances": 0,
                        "rating_sum": 0.0,
                        "rating_count": 0,
                        "avg_rating": None,
                        "total_shots": 0,
                        "shots_on_target": 0,
                        "total_passes": 0,
                        "passes_accurate": 0,
                        "pass_accuracy_pct": None,
                        "key_passes": 0,
                        "tackles": 0,
                        "interceptions": 0,
                        "duels_won": 0,
                        "duels_lost": 0,
                        "fouls_committed": 0,
                        "fouls_drawn": 0,
                        "xg_total": 0.0,
                        "was_captain_count": 0,
                        "youngest_age_seen": None,
                        "oldest_age_seen": None,
                        "matches_detail": [],
                    }

                ps = all_player_stats[pid]
                ps["matches_seen"] += 1
                ps["goals"] += info["goals"]
                ps["assists"] += info["assists"]
                ps["yellow_cards"] += yellow
                ps["red_cards"] += red
                ps["minutes_played"] += p_minutes
                if p_starter is None:
                    ps["bench_appearances"] += 1
                elif p_starter:
                    ps["starter_appearances"] += 1
                else:
                    ps["sub_appearances"] += 1
                if info["team"] and info["team"] not in ps["teams_seen_for"]:
                    ps["teams_seen_for"].append(info["team"])
                if age_years > 0 or age_days > 0:
                    age_entry = {"age_years": age_years, "age_days": age_days, "match_date": match.get("date", ""), "match": format_match_label(match)}
                    if ps["youngest_age_seen"] is None or (age_years, age_days) < (ps["youngest_age_seen"]["age_years"], ps["youngest_age_seen"]["age_days"]):
                        ps["youngest_age_seen"] = age_entry
                    if ps["oldest_age_seen"] is None or (age_years, age_days) > (ps["oldest_age_seen"]["age_years"], ps["oldest_age_seen"]["age_days"]):
                        ps["oldest_age_seen"] = age_entry
                ps["matches_detail"].append(match_detail)

        # Scheidsrechter aggregatie
        ref = m_out.get("referee", {})
        if ref and ref.get("id"):
            rid = ref["id"]
            if rid not in all_referees:
                all_referees[rid] = {
                    "id": rid,
                    "name": ref.get("name", ""),
                    "country": ref.get("country", ""),
                    "matches_count": 0,
                    "total_yellows_in_matches": 0,
                    "total_reds_in_matches": 0,
                    "matches": [],
                }
            all_referees[rid]["matches_count"] += 1
            all_referees[rid]["total_yellows_in_matches"] += sum(1 for c in cards if c.get("type") == "yellow")
            all_referees[rid]["total_reds_in_matches"] += sum(1 for c in cards if c.get("type") in ("red", "yellowRed"))
            all_referees[rid]["matches"].append(event_id)

        # Stadion aggregatie
        venue = m_out.get("venue", {})
        if venue and venue.get("id"):
            vid = venue["id"]
            if vid not in all_venues:
                all_venues[vid] = {
                    "id": vid,
                    "name": venue.get("name", ""),
                    "city": venue.get("city", ""),
                    "matches_count": 0,
                    "first_visit": m_out.get("date", ""),
                    "last_visit": m_out.get("date", ""),
                    "max_attendance": None,
                }
            av = all_venues[vid]
            av["matches_count"] += 1
            if m_out.get("date", "") < av["first_visit"]:
                av["first_visit"] = m_out["date"]
            if m_out.get("date", "") > av["last_visit"]:
                av["last_visit"] = m_out["date"]
            att = m_out.get("attendance")
            if att and (av["max_attendance"] is None or att > av["max_attendance"]):
                av["max_attendance"] = att

        # Teams aggregatie
        for side, key in [("home_team", "home"), ("away_team", "away")]:
            t_obj = m_out.get(side, {})
            if t_obj and t_obj.get("id"):
                tid = t_obj["id"]
                if tid not in all_teams_visited:
                    all_teams_visited[tid] = {
                        "id": tid,
                        "name": t_obj.get("name", ""),
                        "slug": t_obj.get("slug", ""),
                        "gender": t_obj.get("gender", "M"),
                        "logo_url": f"https://api.sofascore.app/api/v1/team/{tid}/image",
                        "matches_count": 0,
                        "as_home": 0,
                        "as_away": 0,
                    }
                all_teams_visited[tid]["matches_count"] += 1
                if key == "home":
                    all_teams_visited[tid]["as_home"] += 1
                else:
                    all_teams_visited[tid]["as_away"] += 1

        # Competities aggregatie
        t_id = m_out.get("tournament_id")
        t_name = m_out.get("tournament", "")
        if t_id:
            if t_id not in all_tournaments:
                all_tournaments[t_id] = {"id": t_id, "name": t_name, "matches_count": 0}
            all_tournaments[t_id]["matches_count"] += 1

        # Seizoenen aggregatie
        s_name = m_out.get("season", "")
        if s_name:
            all_seasons[s_name] = all_seasons.get(s_name, 0) + 1

        matches_out.append(m_out)

    # ─── Finaliseer spelers ─────────────────────────────────────────────────
    players_out = []
    for ps in all_player_stats.values():
        if ps["rating_count"] > 0:
            ps["avg_rating"] = round(ps["rating_sum"] / ps["rating_count"], 2)
        del ps["rating_sum"], ps["rating_count"]

        if ps["total_passes"] > 0:
            ps["pass_accuracy_pct"] = round(ps["passes_accurate"] / ps["total_passes"] * 100, 1)
        del ps["passes_accurate"]

        ps["xg_total"] = round(ps["xg_total"], 2)

        # Nationale team stats
        natl = load_json(PLAYER_NATIONAL_CACHE_DIR / f"{ps['id']}.json") or {}
        ps["national_team_caps"] = natl.get("caps") or 0
        ps["national_team_goals"] = natl.get("goals") or 0
        ps["national_team_debut"] = (
            ts_to_date(natl["debut_timestamp"]) if natl.get("debut_timestamp") else None
        )
        ps["national_team_name"] = natl.get("team_name")
        ps["national_team_alpha2"] = natl.get("team_alpha2")

        # Hoogste transfersom
        tf = load_json(PLAYER_TRANSFER_CACHE_DIR / f"{ps['id']}.json") or {}
        ps["max_transfer_fee"] = tf.get("max_transfer_fee")

        players_out.append(ps)

    # ─── Scheidsrechters finaliseren ────────────────────────────────────────
    for ref in all_referees.values():
        if ref["matches_count"] > 0:
            ref["avg_yellows_per_match"] = round(ref["total_yellows_in_matches"] / ref["matches_count"], 2)
        else:
            ref["avg_yellows_per_match"] = 0.0

    # ─── Records berekenen ──────────────────────────────────────────────────
    youngest = None
    oldest = None
    for ps in players_out:
        ya = ps.get("youngest_age_seen")
        oa = ps.get("oldest_age_seen")
        if ya:
            if youngest is None or (ya["age_years"], ya["age_days"]) < (youngest[1]["age_years"], youngest[1]["age_days"]):
                youngest = (ps, ya)
        if oa:
            if oldest is None or (oa["age_years"], oa["age_days"]) > (oldest[1]["age_years"], oldest[1]["age_days"]):
                oldest = (ps, oa)

    most_goals_match = None
    if matches_out:
        mg = max(matches_out, key=lambda m: len(m.get("goals", [])), default=None)
        if mg:
            most_goals_match = {"count": len(mg["goals"]), "match": format_match_label(mg), "date": mg.get("date", "")}

    highest_xg = None
    for m in matches_out:
        ts = m.get("team_stats", {})
        h_xg = ts.get("home", {}).get("expected_goals", 0) or 0
        a_xg = ts.get("away", {}).get("expected_goals", 0) or 0
        total_xg = h_xg + a_xg
        if highest_xg is None or total_xg > highest_xg["xg_total"]:
            highest_xg = {"xg_total": round(total_xg, 2), "match": format_match_label(m), "date": m.get("date", "")}

    biggest_win = None
    for m in matches_out:
        hs = m.get("home_score")
        as_ = m.get("away_score")
        if hs is not None and as_ is not None:
            diff = abs(hs - as_)
            if biggest_win is None or diff > biggest_win["goal_diff"]:
                biggest_win = {"match": format_match_label(m), "date": m.get("date", ""), "goal_diff": diff}

    highest_att = None
    for m in matches_out:
        att = m.get("attendance")
        if att and (highest_att is None or att > highest_att["count"]):
            venue_name = m.get("venue", {}).get("name", "")
            highest_att = {"count": att, "match": format_match_label(m), "venue": venue_name, "date": m.get("date", "")}

    records = {}
    if youngest:
        ps, ya = youngest
        records["youngest_player"] = {
            "name": ps["name"],
            "age_years": ya["age_years"],
            "age_days": ya["age_days"],
            "date_of_birth": ps.get("date_of_birth"),
            "match_date": ya["match_date"],
            "match": ya["match"],
        }
    if oldest:
        ps, oa = oldest
        records["oldest_player"] = {
            "name": ps["name"],
            "age_years": oa["age_years"],
            "age_days": oa["age_days"],
            "date_of_birth": ps.get("date_of_birth"),
            "match_date": oa["match_date"],
            "match": oa["match"],
        }
    if most_goals_match:
        records["most_goals_single_match"] = most_goals_match
    if highest_xg:
        records["highest_xg_match"] = highest_xg
    if biggest_win:
        records["biggest_win"] = biggest_win
    if highest_att:
        records["highest_attendance"] = highest_att

    # ─── Samenvoegen ────────────────────────────────────────────────────────
    dates = [m.get("date", "") for m in matches_out if m.get("date")]
    total_goals = sum(len(m.get("goals", [])) for m in matches_out)

    dashboard = {
        "generated_at": datetime.now().isoformat(),
        "total_matches": len(matches_out),
        "total_goals_witnessed": total_goals,
        "date_range": {
            "first": min(dates) if dates else None,
            "last": max(dates) if dates else None,
        },
        "matches": sorted(matches_out, key=lambda m: m.get("date", ""), reverse=True),
        "players": sorted(players_out, key=lambda p: p["matches_seen"], reverse=True),
        "referees": sorted(all_referees.values(), key=lambda r: r["matches_count"], reverse=True),
        "venues": sorted(all_venues.values(), key=lambda v: v["matches_count"], reverse=True),
        "teams_visited": sorted(all_teams_visited.values(), key=lambda t: t["matches_count"], reverse=True),
        "tournaments": sorted(all_tournaments.values(), key=lambda t: t["matches_count"], reverse=True),
        "seasons": [{"name": k, "matches_count": v} for k, v in sorted(all_seasons.items(), reverse=True)],
        "records": records,
    }

    save_json(DASHBOARD_FILE, dashboard)

    console.print(f"\n[green]✓ Dashboard JSON opgeslagen: {DASHBOARD_FILE}[/green]")
    console.print(f"  Wedstrijden: {len(matches_out)}")
    console.print(f"  Spelers: {len(players_out)}")
    console.print(f"  Stadions: {len(all_venues)}")
    console.print(f"  Scheidsrechters: {len(all_referees)}")
    console.print(f"  Doelpunten: {total_goals}")


# ─── Hoofdmenu ───────────────────────────────────────────────────────────────

def toon_menu():
    """Toon het interactieve hoofdmenu."""
    console.print()
    console.print(Panel(
        Align.center(
            Text.from_markup(
                "[bold cyan]⚽ Sofascore Match Tracker v2[/bold cyan]\n\n"
                "[white]1.[/white] [green]🔍 Zoek team & selecteer wedstrijden[/green]\n"
                "[white]2.[/white] [green]📋 Bekijk geselecteerde wedstrijden[/green]\n"
                "[white]3.[/white] [green]📥 Download wedstrijddata[/green]\n"
                "[white]4.[/white] [green]👤 Download spelerprofielen[/green]\n"
                "[white]5.[/white] [green]📊 Bekijk stats overzicht[/green]\n"
                "[white]6.[/white] [green]💾 Exporteer dashboard JSON[/green]\n"
                "[white]0.[/white] [red]❌ Afsluiten[/red]"
            )
        ),
        title="[bold]Menu[/bold]",
        border_style="cyan",
        padding=(1, 4),
    ))


def main():
    setup_dirs()

    parser = argparse.ArgumentParser(description="Sofascore Match Tracker v2")
    parser.add_argument("--export", action="store_true", help="Direct exporteren zonder menu")
    parser.add_argument("--download", action="store_true", help="Download wedstrijddata + spelers zonder menu")
    args = parser.parse_args()

    if args.export:
        menu_exporteer_dashboard()
        return

    if args.download:
        menu_download_data()
        menu_download_spelers()
        menu_exporteer_dashboard()
        return

    while True:
        toon_menu()
        choice = Prompt.ask("\n[bold cyan]Keuze[/bold cyan]", choices=["0", "1", "2", "3", "4", "5", "6"])

        if choice == "0":
            console.print("[dim]Tot ziens![/dim]")
            break
        elif choice == "1":
            menu_zoek_team()
        elif choice == "2":
            menu_bekijk_selectie()
        elif choice == "3":
            menu_download_data()
        elif choice == "4":
            menu_download_spelers()
        elif choice == "5":
            menu_stats_overzicht()
        elif choice == "6":
            menu_exporteer_dashboard()

        console.print("\n[dim]Druk Enter om terug te gaan naar het menu...[/dim]")
        input()


if __name__ == "__main__":
    main()
