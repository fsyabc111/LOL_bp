#!/usr/bin/env python3
"""Collect Leaguepedia per-step Picks and Bans tables and link rows to local OE games.

Each tournament page is rendered once through the public MediaWiki parse API, sequentially with
spacing and bounded back-off. Raw responses are content-addressed under data/raw/leaguepedia-pb/;
the manifest records title, revision, URL, times and hashes. Rows link to OE only when the
blue/red final pick sets match exactly one OE game. Output feeds scripts/validate_bp.py.
"""
import argparse
import datetime
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
API = 'https://lol.fandom.com/api.php'
USER_AGENT = 'LOL_bp-research/0.1 (personal research; github.com/fsyabc111/LOL_bp)'
RAW = 'data/raw/leaguepedia-pb'
MANIFEST = 'data/manifests/leaguepedia-pb.json'
OUTPUT = 'data/curated/bp_sequences.jsonl'
DB = 'data/processed/lol_bp.sqlite3'
CATALOGS = ['data/curated/static/16.20.1/en_US/champion.json', 'data/curated/static/14.16.1/en_US/champion.json']
PAGES = ['LCK/2024 Season/Summer Playoffs/Picks and Bans'] + [
    f'LCK/2025 Season/{s}/Picks and Bans' for s in ['Cup', 'Rounds 1-2', 'Road to MSI', 'Rounds 3-5', 'Season Play-In', 'Season Playoffs']] + [
    f'LCK/2026 Season/{s}/Picks and Bans' for s in ['Cup', 'Rounds 1-2', 'Road to MSI', 'Rounds 3-4', 'Season Play-In', 'Season Playoffs']] + [
    f'LPL/2025 Season/{s}/Picks and Bans' for s in ['Split 1', 'Split 1 Playoffs', 'Split 2 Placements', 'Split 2', 'Split 2 Playoffs', 'Split 3', 'Regional Finals', 'Grand Finals']] + [
    f'LPL/2026 Season/{s}/Picks and Bans' for s in ['Split 1', 'Split 1 Playoffs', 'Split 2', 'Split 2 Playoffs', 'Split 3', 'Regional Finals', 'Grand Finals']] + [
    f'{y} Season World Championship/{s}/Picks and Bans' for y in (2025, 2026) for s in ['Play-In', 'Main Event']]
# Table column -> (global step(s), draft team, action). Team1 is the first-selecting team (A).
COLUMNS = {'T1B1': ([1], 'A', 'ban'), 'T2B1': ([2], 'B', 'ban'), 'T1B2': ([3], 'A', 'ban'), 'T2B2': ([4], 'B', 'ban'),
           'T1B3': ([5], 'A', 'ban'), 'T2B3': ([6], 'B', 'ban'), 'T1P1': ([7], 'A', 'pick'), 'T2P1-2': ([8, 9], 'B', 'pick'),
           'T1P2-3': ([10, 11], 'A', 'pick'), 'T2P3': ([12], 'B', 'pick'), 'T2B4': ([13], 'B', 'ban'), 'T1B4': ([14], 'A', 'ban'),
           'T2B5': ([15], 'B', 'ban'), 'T1B5': ([16], 'A', 'ban'), 'T2P4': ([17], 'B', 'pick'), 'T1P4-5': ([18, 19], 'A', 'pick'),
           'T2P5': ([20], 'B', 'pick')}
# Same-team consecutive picks are entered as one cell; their internal order is not asserted.
UNORDERED_GROUPS = [[8, 9], [10, 11], [18, 19]]


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def page_url(title):
    return API + '?' + urllib.parse.urlencode({'action': 'parse', 'page': title, 'prop': 'text|revid', 'format': 'json'})


def save_raw(root, body):
    digest = hashlib.sha256(body).hexdigest()
    path = Path(RAW) / 'sha256' / f'{digest}.json'
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.read_bytes() != body: raise ValueError(f'content-addressed cache mismatch: {path}')
    if not target.exists(): target.write_bytes(body)
    return str(path), digest


def fetch(root, title, opener=urllib.request.urlopen, sleep=time.sleep, attempts=3, backoff=60):
    record = {'title': title, 'url': page_url(title), 'attempts': []}
    for attempt in range(attempts):
        started = utc_now()
        try:
            with opener(urllib.request.Request(record['url'], headers={'User-Agent': USER_AGENT}), timeout=60) as response:
                body = response.read(); status = response.status
        except urllib.error.HTTPError as error:
            record['attempts'].append({'attempted_at': started, 'http_status': error.code, 'error': 'http_error'})
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            record['attempts'].append({'attempted_at': started, 'error': type(error).__name__})
        else:
            try: payload = json.loads(body)
            except json.JSONDecodeError: payload = {'error': {'code': 'invalid_json'}}
            code = payload.get('error', {}).get('code')
            record['attempts'].append({'attempted_at': started, 'http_status': status, 'api_error': code})
            if not code:
                path, digest = save_raw(root, body)
                record.update(status='success', retrieved_at=utc_now(), raw_path=path, sha256=digest, bytes=len(body),
                              revid=payload['parse']['revid'])
                return record
            if code != 'ratelimited':
                record['status'] = 'failed'; return record
        if attempt + 1 < attempts: sleep(backoff * (attempt + 1))
    record['status'] = 'failed'
    return record


class TableParser(HTMLParser):
    """Extract rows of Picks and Bans tables whose header names the per-step columns."""
    def __init__(self):
        super().__init__(); self.tables = []; self.stack = []; self.cell = None; self.row = None; self.header = None
        self.champion = None
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'table': self.stack.append({'header': None, 'rows': []})
        elif not self.stack: return
        elif tag == 'tr': self.row = []
        elif tag in ('td', 'th') and self.row is not None:
            self.cell = {'tag': tag, 'class': attrs.get('class', ''), 'title': attrs.get('title'), 'text': '', 'champions': [], 'links': []}
        elif self.cell is not None:
            if tag == 'span' and 'pbh-cn' in (attrs.get('class') or ''): self.champion = {'slug': attrs.get('data-champion')}
            elif tag == 'span' and 'champion-sprite' in (attrs.get('class') or '') and self.champion is not None:
                # An empty ban renders as a placeholder sprite titled "None"; keep it as an empty slot.
                name = attrs.get('title')
                self.champion['name'] = None if (name or '').casefold() == 'none' or self.champion['slug'] == 'none' else name
                self.cell['champions'].append(self.champion); self.champion = None
            elif tag == 'a' and attrs.get('href'): self.cell['links'].append(attrs['href'])
    def handle_data(self, data):
        if self.cell is not None: self.cell['text'] += data
    def handle_endtag(self, tag):
        if not self.stack: return
        if tag in ('td', 'th') and self.cell is not None:
            self.cell['text'] = self.cell['text'].replace('⁠', '').strip(); self.row.append(self.cell); self.cell = None
        elif tag == 'tr' and self.row is not None:
            table = self.stack[-1]
            if all(c['tag'] == 'th' for c in self.row) and any(c['text'] == 'T1B1' for c in self.row): table['header'] = [c['text'] for c in self.row]
            elif table['header'] and len(self.row) == len(table['header']): table['rows'].append(self.row)
            self.row = None
        elif tag == 'table':
            table = self.stack.pop()
            if table['header']: self.tables.append(table)


def side_of_cell(cell):
    classes = cell['class'].split()
    return 'Blue' if 'pbh-blue' in classes else 'Red' if 'pbh-red' in classes else None


def parse_page(html):
    parser = TableParser(); parser.feed(html)
    games = []
    for table in parser.tables:
        header = table['header']
        for row in table['rows']:
            cells = dict(zip(header, row))
            team1_side = side_of_cell(cells['Team1'])
            parsed = {'phase': cells['Phase']['text'], 'team1': cells['Team1']['title'], 'team2': cells['Team2']['title'],
                      'patch': cells['Patch']['text'], 'links': cells.get('SB', {}).get('links', []) + cells.get('VOD', {}).get('links', []),
                      'errors': [], 'steps': []}
            if team1_side is None or side_of_cell(cells['Team2']) not in ('Blue', 'Red') or side_of_cell(cells['Team2']) == team1_side:
                parsed['errors'].append('team_side_unknown'); games.append(parsed); continue
            sides = {'A': team1_side, 'B': 'Red' if team1_side == 'Blue' else 'Blue'}
            for column, (steps, team, action) in COLUMNS.items():
                champions = cells[column]['champions'] if column in cells else []
                if action == 'pick' and len(champions) != len(steps): parsed['errors'].append(f'pick_cell_count:{column}')
                if action == 'ban' and len(champions) > 1: parsed['errors'].append(f'ban_cell_count:{column}')
                if action == 'pick' and any(c['name'] is None for c in champions): parsed['errors'].append(f'empty_pick:{column}')
                for i, step in enumerate(steps):
                    champion = champions[i]['name'] if i < len(champions) else None
                    parsed['steps'].append({'step': step, 'side': sides[team], 'action': action, 'champion': champion})
            parsed['steps'].sort(key=lambda s: s['step'])
            parsed['team1_side'] = team1_side
            games.append(parsed)
    return games


def name_key(name, aliases):
    plain = ''.join(ch for ch in (name or '').casefold() if ch.isalnum())
    return aliases.get(plain, plain)


def load_aliases(root):
    aliases = {}
    for path in CATALOGS:
        for entity in json.loads((root / path).read_text())['entities']:
            for alias in [entity.get('name'), entity.get('source_key')] + entity.get('aliases', []):
                if alias: aliases[''.join(ch for ch in alias.casefold() if ch.isalnum())] = str(entity['id'])
    return aliases


def load_oe_index(root, aliases):
    connection = sqlite3.connect(root / DB)
    index = {}
    rows = connection.execute("SELECT d.gameid, d.side, d.picks_raw_json FROM team_drafts d JOIN games g USING(gameid) "
                              "WHERE substr(g.date_raw,1,4) IN ('2024','2025','2026') AND g.league_raw IN ('LCK','LPL','WLDs')").fetchall()
    connection.close()
    by_game = {}
    for gameid, side, picks in rows: by_game.setdefault(gameid, {})[side] = frozenset(name_key(n, aliases) for n in json.loads(picks))
    for gameid, sides in by_game.items():
        if set(sides) == {'Blue', 'Red'}: index.setdefault((sides['Blue'], sides['Red']), []).append(gameid)
    return index


def link_games(manifest_pages, root):
    aliases = load_aliases(root); index = load_oe_index(root, aliases)
    evidence, stats = [], []
    for page in manifest_pages:
        if page.get('status') != 'success': continue
        body = (root / page['raw_path']).read_bytes()
        if hashlib.sha256(body).hexdigest() != page['sha256']: raise ValueError(f"raw hash mismatch: {page['raw_path']}")
        counts = {'rows': 0, 'parse_errors': 0, 'linked': 0, 'unmatched': 0, 'ambiguous': 0}
        for n, game in enumerate(parse_page(json.loads(body)['parse']['text']['*']), 1):
            counts['rows'] += 1
            if game['errors']: counts['parse_errors'] += 1; continue
            picks = {side: frozenset(name_key(s['champion'], aliases) for s in game['steps'] if s['side'] == side and s['action'] == 'pick') for side in ('Blue', 'Red')}
            matches = index.get((picks['Blue'], picks['Red']), [])
            if len(matches) != 1: counts['unmatched' if not matches else 'ambiguous'] += 1; continue
            counts['linked'] += 1
            evidence.append({'oe_gameid': matches[0], 'link_method': 'unique_final_pick_sets_by_side',
                             'source': {'source_type': 'leaguepedia_picks_and_bans', 'title': page['title'], 'url': page['url'],
                                        'revid': page['revid'], 'retrieved_at': page['retrieved_at'], 'sha256': page['sha256'],
                                        'locator': f"{page['title']} rev {page['revid']} table row {n} ({game['phase']}: {game['team1']} vs {game['team2']})",
                                        'row_links': game['links']},
                             'source_patch': game['patch'], 'first_selection_side': game['team1_side'],
                             'unordered_step_groups': UNORDERED_GROUPS, 'steps': game['steps']})
        stats.append({'title': page['title'], **counts})
    return sorted(evidence, key=lambda e: (e['oe_gameid'], e['source']['title'])), stats


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--pages', nargs='+', default=PAGES)
    parser.add_argument('--offline', action='store_true', help='Use cached successful responses only; never open network')
    parser.add_argument('--refresh', action='store_true', help='Refetch pages even when cached')
    parser.add_argument('--delay', type=float, default=8.0, help='Seconds between page requests')
    args = parser.parse_args(); root = args.root
    path = root / MANIFEST
    manifest = json.loads(path.read_text()) if path.exists() else {'schema_version': 1, 'pages': []}
    cached = {p['title']: p for p in manifest['pages'] if p.get('status') == 'success'}
    pages = []
    for i, title in enumerate(args.pages):
        if title in cached and not args.refresh: pages.append(cached[title]); continue
        if args.offline: pages.append({'title': title, 'status': 'failed', 'attempts': [{'error': 'offline_cache_missing'}]}); continue
        if i and args.delay: time.sleep(args.delay)
        record = fetch(root, title); pages.append(record)
        print(title, record['status'], flush=True)
    evidence, stats = link_games(pages, root)
    manifest = {'schema_version': 1, 'user_agent': USER_AGENT, 'pages': pages, 'link_stats': stats,
                'summary': {'pages': len(pages), 'success': sum(p.get('status') == 'success' for p in pages),
                            'rows': sum(s['rows'] for s in stats), 'linked': len(evidence)}}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + '\n')
    (root / OUTPUT).write_text(''.join(json.dumps(e, ensure_ascii=False, sort_keys=True) + '\n' for e in evidence))
    print(json.dumps(manifest['summary']))
    if manifest['summary']['success'] != len(pages): raise SystemExit(1)


if __name__ == '__main__': main()
