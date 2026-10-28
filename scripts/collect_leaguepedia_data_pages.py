#!/usr/bin/env python3
"""Collect event-disabled champions and listed patches from Leaguepedia tournament Data pages.

Each Data page's wikitext is read once through the MediaWiki revisions API (sequential, spaced,
bounded back-off; raw responses content-addressed under data/raw/leaguepedia-data/). A
{{SetPatch|patch=..|disabled=..|hotfix=..}} line applies to the matches that follow it until the next
one. Games link to OE by riot_platform_game_id (LCK/Worlds) or the LPL qq series id
('<qq>-<qq>_game_<n>'); nothing is linked by team names. Leaguepedia is a community source: an empty
disabled list means none was listed there, not that the organiser confirmed none.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import time
import urllib.parse

from collect_leaguepedia_pb import API, USER_AGENT, fetch

ROOT = Path(__file__).resolve().parents[1]
RAW = 'data/raw/leaguepedia-data'
MANIFEST = 'data/manifests/leaguepedia-data.json'
OUTPUT = 'data/curated/event_restrictions.jsonl'
DB = 'data/processed/lol_bp.sqlite3'
PREFIXES = ['LCK/2024 Season/Summer Playoffs', 'LCK/2025 Season/', 'LCK/2026 Season/', 'LPL/2025 Season/', 'LPL/2026 Season/',
            '2025 Season World Championship/', '2026 Season World Championship/']
TOKEN = re.compile(r'\{\{SetPatch\|(?P<setpatch>[^}]*)\}\}'
                   r'|\{\{MatchSchedule\|(?P<match>.*?)(?=\|game\d+=\{\{|\n\}\})'
                   r'|\|game(?P<number>\d+)=\{\{MatchSchedule/Game(?P<game>.*?)\n\}\}', re.S)


def revisions_url(title):
    return API + '?' + urllib.parse.urlencode({'action': 'query', 'prop': 'revisions', 'rvprop': 'ids|timestamp|content',
                                               'rvslots': 'main', 'titles': title, 'format': 'json'})


def page_of(payload):
    return next(iter(payload['query']['pages'].values()))


def revision_id(payload):
    return page_of(payload)['revisions'][0]['revid']


def params(text):
    out = {}
    for part in text.split('|'):
        key, sep, value = part.partition('=')
        if sep: out[key.strip()] = value.strip()
    return out


def split_names(value):
    return [name.strip() for name in re.split(r'[,;]', value or '') if name.strip()]


def parse_data_page(wikitext):
    """Yield one record per game with the SetPatch block in force where the game appears."""
    current, match, games = None, {}, []
    for token in TOKEN.finditer(wikitext):
        if token.group('setpatch') is not None:
            p = params(token.group('setpatch'))
            current = {'patch': p.get('patch') or None, 'disabled': split_names(p.get('disabled')),
                       'hotfix': p.get('hotfix') or None, 'footnote': p.get('footnote') or None}
        elif token.group('match') is not None:
            match = params(token.group('match'))
        else:
            game = params(token.group('game'))
            games.append({'game_number': int(token.group('number')), 'setpatch': current,
                          'match': {k: match.get(k) for k in ('team1', 'team2', 'date', 'qq', 'bestof')},
                          'game': {k: game.get(k) for k in ('blue', 'red', 'first_sel', 'ssel', 'pick_sel', 'first_pick', 'ff', 'riot_platform_game_id')}})
    return games


def link(record, oe_gameids):
    riot = record['game'].get('riot_platform_game_id')
    if riot and riot in oe_gameids: return riot, 'riot_platform_game_id'
    qq = record['match'].get('qq')
    if qq and qq.isdigit():
        candidate = f"{qq}-{qq}_game_{record['game_number']}"
        if candidate in oe_gameids: return candidate, 'lpl_qq_series_id'
    return None, None


def list_pages(root, sleep=time.sleep, delay=5.0):
    titles = []
    for i, prefix in enumerate(PREFIXES):
        if i: sleep(delay)
        url = API + '?' + urllib.parse.urlencode({'action': 'query', 'list': 'allpages', 'apnamespace': 10008,
                                                  'apprefix': prefix, 'aplimit': 500, 'format': 'json'})
        record = fetch(root, 'allpages:' + prefix, url=url, raw=RAW, revid=lambda payload: None)
        if record['status'] != 'success': raise SystemExit(f'page listing failed: {prefix}')
        payload = json.loads((root / record['raw_path']).read_bytes())
        titles += [p['title'] for p in payload['query']['allpages'] if 'Showmatch' not in p['title']]
    return sorted(set(titles))


def build(root, pages):
    connection = sqlite3.connect(root / DB)
    oe = {gameid: date for gameid, date in connection.execute('SELECT gameid, date_raw FROM games')}
    connection.close()
    out, stats = [], []
    for page in pages:
        if page.get('status') != 'success': continue
        body = (root / page['raw_path']).read_bytes()
        if hashlib.sha256(body).hexdigest() != page['sha256']: raise ValueError(f"raw hash mismatch: {page['raw_path']}")
        content = page_of(json.loads(body))['revisions'][0]['slots']['main']['*']
        counts = {'games': 0, 'linked': 0, 'no_setpatch': 0}
        for record in parse_data_page(content):
            counts['games'] += 1
            gameid, method = link(record, oe)
            if not gameid: continue
            if record['setpatch'] is None: counts['no_setpatch'] += 1; continue
            counts['linked'] += 1
            out.append({'oe_gameid': gameid, 'link_method': method, 'source_status': 'community_listed',
                        'disabled': record['setpatch']['disabled'], 'listed_patch': record['setpatch']['patch'],
                        'hotfix': record['setpatch']['hotfix'], 'footnote': record['setpatch']['footnote'],
                        'selection': {k: record['game'][k] for k in ('blue', 'red', 'first_sel', 'ssel', 'pick_sel', 'first_pick')},
                        'source': {'source_type': 'leaguepedia_data_page', 'title': page['title'], 'revid': page['revid'],
                                   'retrieved_at': page['retrieved_at'], 'sha256': page['sha256'],
                                   'locator': f"{page['title']} rev {page['revid']} game{record['game_number']} of "
                                              f"{record['match']['team1']} vs {record['match']['team2']} ({record['match']['date']})"}})
        stats.append({'title': page['title'], **counts})
    by_game = {}
    for item in out: by_game.setdefault(item['oe_gameid'], []).append(item)
    duplicates = sorted(g for g, items in by_game.items() if len(items) > 1)
    return sorted(out, key=lambda e: (e['oe_gameid'], e['source']['title'])), stats, duplicates


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--offline', action='store_true', help='Rebuild from cached successful responses only')
    parser.add_argument('--delay', type=float, default=6.0)
    args = parser.parse_args(); root = args.root
    path = root / MANIFEST
    manifest = json.loads(path.read_text()) if path.exists() else {'schema_version': 1, 'pages': []}
    cached = {p['title']: p for p in manifest['pages'] if p.get('status') == 'success'}
    titles = sorted(cached) if args.offline else list_pages(root, delay=args.delay)
    pages = []
    for title in titles:
        if title in cached: pages.append(cached[title]); continue
        time.sleep(args.delay)
        record = fetch(root, title, url=revisions_url(title), raw=RAW, revid=revision_id)
        pages.append(record); print(title, record['status'], flush=True)
    evidence, stats, duplicates = build(root, pages)
    manifest = {'schema_version': 1, 'user_agent': USER_AGENT, 'pages': pages, 'link_stats': stats, 'duplicate_games': duplicates,
                'summary': {'pages': len(pages), 'success': sum(p.get('status') == 'success' for p in pages),
                            'games_linked': len(evidence), 'with_disabled': sum(bool(e['disabled']) for e in evidence)}}
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + '\n')
    (root / OUTPUT).write_text(''.join(json.dumps(e, ensure_ascii=False, sort_keys=True) + '\n' for e in evidence))
    print(json.dumps(manifest['summary']))
    if manifest['summary']['success'] != len(pages): raise SystemExit(1)


if __name__ == '__main__': main()
