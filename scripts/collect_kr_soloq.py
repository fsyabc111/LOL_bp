#!/usr/bin/env python3
"""Sample high-elo Korean solo queue games in the first days of each patch and aggregate champion statistics.

Needs RIOT_API_KEY in the environment or in .env (never committed). Players are the current KR Challenger and
Grandmaster ladders (LEAGUE-V4), taken in LP order; their ranked solo games (queue 420) inside each patch's window
come from MATCH-V5 and are kept only when the game version matches the patch. Caveats recorded in the output: the
sample is today's top players, not the ladder as it was then, and players who played many games weigh more.

Requests are sequential and rate-limited below the development key limits (18/s, 95/120 s), with Retry-After on
429. Raw responses (which contain PUUIDs) stay under data/raw/riot/ and are reused, so runs can resume with a new
key. Only per-champion aggregates (overall and per UTC day, so a game can use only earlier days) are written to
data/curated/kr_soloq/<patch>.json, with no player identifiers.
"""
import argparse
from collections import Counter, defaultdict, deque
import datetime
import hashlib
import http.client
import json
import os
from pathlib import Path
import sys
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lolbp.patches import CHANGES, order_key  # noqa: E402

RAW = ROOT / 'data/raw/riot'
OUT = ROOT / 'data/curated/kr_soloq'
PLATFORM, REGION = 'https://kr.api.riotgames.com', 'https://asia.api.riotgames.com'
ROLES = {'TOP': 'top', 'JUNGLE': 'jng', 'MIDDLE': 'mid', 'BOTTOM': 'bot', 'UTILITY': 'sup'}


class Client:
    """Riot API client with a sliding-window rate limiter and an on-disk response cache."""

    def __init__(self, key, limits=((18, 1.0), (95, 120.0))):
        self.key, self.limits, self.calls, self.requests = key, limits, deque(), 0

    def _wait(self):
        while True:
            now = time.monotonic()
            while self.calls and now - self.calls[0] > max(w for _, w in self.limits): self.calls.popleft()
            delays = [w - (now - self.calls[-n]) for n, w in self.limits if len(self.calls) >= n]
            delay = max([d for d in delays if d > 0], default=0)
            if not delay: return
            time.sleep(delay + 0.05)

    def get(self, url, cache):
        path = RAW / cache
        if path.exists(): return json.loads(path.read_text())
        for attempt in range(5):
            self._wait(); self.calls.append(time.monotonic()); self.requests += 1
            request = urllib.request.Request(url, headers={'X-Riot-Token': self.key, 'User-Agent': 'LOL_bp research (self-use)'})
            try:
                with urllib.request.urlopen(request, timeout=30) as response: body = response.read()
            except urllib.error.HTTPError as error:
                if error.code == 429: time.sleep(int(error.headers.get('Retry-After') or 10) + 1); continue
                if error.code in (500, 502, 503, 504): time.sleep(5 * (attempt + 1)); continue
                if error.code in (401, 403): raise SystemExit(f'HTTP {error.code}: key missing, expired or not allowed for this endpoint')
                if error.code == 404: return None
                raise
            except (urllib.error.URLError, http.client.HTTPException, TimeoutError, OSError): time.sleep(5 * (attempt + 1)); continue
            path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(body)
            return json.loads(body)
        raise SystemExit(f'giving up after retries: {url.split("?")[0]}')


def load_key():
    if os.environ.get('RIOT_API_KEY'): return os.environ['RIOT_API_KEY']
    env = ROOT / '.env'
    for line in env.read_text().splitlines() if env.exists() else []:
        if line.startswith('RIOT_API_KEY='): return line.split('=', 1)[1].strip()
    raise SystemExit('RIOT_API_KEY not set (environment or .env)')


def patch_dates():
    """Leaguepedia patch name -> release date, the earliest change-block date on its page."""
    dates = {}
    for line in (ROOT / CHANGES).read_text().splitlines():
        r = json.loads(line)
        if r.get('date'): dates[r['patch']] = min(dates.get(r['patch'], r['date']), r['date'])
    return dates


def players(client, count):
    """Current Challenger then Grandmaster entries in LP order (PUUIDs stay in memory and the raw cache)."""
    today = datetime.date.today().isoformat()
    entries = []
    for tier in ('challengerleagues', 'grandmasterleagues'):
        league = client.get(f'{PLATFORM}/lol/league/v4/{tier}/by-queue/RANKED_SOLO_5x5', f'league/{today}-{tier}.json')
        entries += sorted(league['entries'], key=lambda e: -e['leaguePoints'])
    return [e['puuid'] for e in entries[:count]]


def collect(client, patch, start, days, roster, max_matches):
    begin = int(datetime.datetime.fromisoformat(start).replace(tzinfo=datetime.timezone.utc).timestamp())
    end = begin + days * 86400
    ids, per_player = [], Counter()
    for puuid in roster:
        key = hashlib.sha256(puuid.encode()).hexdigest()[:16]
        found = client.get(f'{REGION}/lol/match/v5/matches/by-puuid/{puuid}/ids?queue=420&startTime={begin}&endTime={end}&count=100',
                           f'ids/{patch}/{key}.json') or []
        per_player[key] = len(found); ids += found
    unique = sorted(set(ids))
    version = patch.replace('S1.', '').split('.')  # 26.09 -> game version 16.9.x; 25.S1.2 -> 15.2.x
    expected = f"{int(version[0]) - 10}.{int(version[1])}."
    stats = defaultdict(lambda: {'games': 0, 'wins': 0, 'bans': 0, 'roles': Counter()})
    days_out = defaultdict(lambda: {'games': 0, 'champions': defaultdict(lambda: [0, 0])})  # UTC date -> games, champion -> [picks, bans]
    kept = Counter()
    for match_id in unique[:max_matches]:
        match = client.get(f'{REGION}/lol/match/v5/matches/{match_id}', f'match/{match_id}.json')
        if not match or match['info'].get('queueId') != 420: kept['skipped_other'] += 1; continue
        if not match['info']['gameVersion'].startswith(expected): kept['skipped_version'] += 1; continue
        if match['info'].get('gameDuration', 0) < 900: kept['skipped_short'] += 1; continue  # remakes / early surrenders
        kept['games'] += 1
        date = datetime.datetime.fromtimestamp(match['info']['gameStartTimestamp'] / 1000, datetime.timezone.utc).date().isoformat()
        day = days_out[date]; day['games'] += 1
        for p in match['info']['participants']:
            s = stats[str(p['championId'])]; s['games'] += 1; s['wins'] += bool(p['win'])
            s['roles'][ROLES.get(p.get('teamPosition'), 'unknown')] += 1; day['champions'][str(p['championId'])][0] += 1
        for team in match['info']['teams']:
            for ban in team['bans']:
                if ban['championId'] > 0: stats[str(ban['championId'])]['bans'] += 1; day['champions'][str(ban['championId'])][1] += 1
    return {'schema_version': 1, 'patch': patch, 'game_version_prefix': expected, 'window': {'start': start, 'days': days},
            'sample': {'ladder_players': len(roster), 'players_with_games': sum(1 for n in per_player.values() if n),
                       'match_ids': len(unique), 'matches_requested': min(len(unique), max_matches), **kept},
            'caveats': ['players are the current KR Challenger/Grandmaster ladder, not the ladder at the time',
                        'players with more games in the window weigh more'],
            'champions': {c: {**{k: v for k, v in s.items() if k != 'roles'}, 'roles': dict(s['roles'])}
                          for c, s in sorted(stats.items(), key=lambda kv: int(kv[0]))},
            'days': {d: {'games': v['games'], 'champions': {c: x for c, x in sorted(v['champions'].items(), key=lambda kv: int(kv[0]))}}
                     for d, v in sorted(days_out.items())}}


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('patches', nargs='+', help="Leaguepedia patch names, e.g. 26.09 26.10")
    parser.add_argument('--players', type=int, default=150)
    parser.add_argument('--days', type=int, default=7)
    parser.add_argument('--max-matches', type=int, default=300)
    args = parser.parse_args()
    client = Client(load_key()); dates = patch_dates()
    roster = players(client, args.players)
    OUT.mkdir(parents=True, exist_ok=True)
    for patch in sorted(args.patches, key=order_key):
        if patch not in dates: raise SystemExit(f'no release date for {patch} in {CHANGES}')
        result = collect(client, patch, dates[patch], args.days, roster, args.max_matches)
        (OUT / f'{patch}.json').write_text(json.dumps(result, ensure_ascii=False, indent=1, sort_keys=True) + '\n')
        print(patch, dates[patch], json.dumps(result['sample']), f'requests so far {client.requests}', flush=True)


if __name__ == '__main__': main()
