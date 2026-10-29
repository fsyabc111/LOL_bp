#!/usr/bin/env python3
"""Collect champion changes from Leaguepedia patch-note pages (2025–2026) and the OE <-> patch-name mapping.

Each 'Patch 25.*' / 'Patch 26.*' page is read once through the MediaWiki revisions API (sequential, spaced,
bounded back-off; raw responses content-addressed under data/raw/leaguepedia-patches/). Every
{{pnb|date=..|champion=..|context=..|changes=..}} block becomes one record with a direction:

- context: designer-intent keywords in the context text ("too strong", "underperforming", ...)
- numbers: 'old => new' lines, where lower is better for cooldowns, costs and cast times
The direction is 'buff' or 'nerf' when the votes agree in sign (context counts double), else 'adjust'. Both vote
counts are kept so the classification can be audited. Block dates are kept, so mid-patch updates only apply from
their own date. Leaguepedia content is CC BY-SA 3.0 (see data/SOURCES.md).

The OE patch names (15.01, 16.20, ...) map to Leaguepedia names (25.S1.1, 26.20, ...) by the per-game evidence in
data/curated/event_restrictions.jsonl; the mapping is written with its game counts and fails on any conflict.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import sys
import time
import urllib.parse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from collect_leaguepedia_pb import API, USER_AGENT, fetch  # noqa: E402
from collect_leaguepedia_data_pages import page_of, revision_id, revisions_url  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RAW = 'data/raw/leaguepedia-patches'
MANIFEST = 'data/manifests/leaguepedia-patches.json'
OUTPUT = 'data/curated/patch_changes.jsonl'
MAPPING = 'data/curated/patch_mapping.json'
RESTRICTIONS = 'data/curated/event_restrictions.jsonl'
CATALOG = 'data/curated/static/16.20.1/en_US/champion.json'
PREFIXES = ['Patch 25.', 'Patch 26.']
TITLE = re.compile(r'^Patch (25|26)\.(S1\.\d|\d{2})$')
BUFF_WORDS = ('underperform', 'struggl', 'buff', 'help out', 'helping', 'more power', 'additional power', 'back up',
              'boost', 'lacking', 'not strong enough', 'too weak', 'falling behind', 'give her', 'give him', 'give them')
NERF_WORDS = ('overperform', 'too strong', 'nerf', 'tone down', 'toning down', 'dominat', 'skyrocket', 'oppressive', 'too much',
              'weaker', 'down a notch', 'pull back', 'pulling back', 'rein in', 'too good', 'bring down', 'bringing down', 'bring him down',
              'bring her down', 'bring them down')
LOWER_IS_BETTER = ('cooldown', 'cost', 'cast time', 'delay', 'recharge', 'windup', 'lockout', 'channel')
ARROW = '⇒'


def blocks(wikitext, name='pnb'):
    """Top-level {{name|...}} templates with balanced braces, as raw inner text."""
    out, start = [], 0
    while True:
        i = wikitext.find('{{' + name + '|', start)
        if i < 0: return out
        depth, j = 0, i
        while j < len(wikitext):
            if wikitext.startswith('{{', j): depth += 1; j += 2
            elif wikitext.startswith('}}', j):
                depth -= 1; j += 2
                if depth == 0: break
            else: j += 1
        out.append(wikitext[i + len(name) + 3:j - 2]); start = j


def fields(inner):
    """Split a template body into top-level |key=value fields (nested templates kept intact)."""
    parts, depth, current = [], 0, ''
    for k, ch in enumerate(inner):
        if inner.startswith('{{', k): depth += 1
        elif inner.startswith('}}', k): depth -= 1
        if ch == '|' and depth == 0: parts.append(current); current = ''
        else: current += ch
    parts.append(current)
    out = {}
    for part in parts:
        key, sep, value = part.partition('=')
        if sep and re.fullmatch(r'\s*\w+\s*', key): out[key.strip()] = value.strip()
    return out


def first_number(text):
    values = [float(x) for x in re.findall(r'-?\d+(?:\.\d+)?', text.replace(',', ''))]
    return sum(values) / len(values) if values else None


def number_votes(changes):
    """(+1 per line that improves the champion, -1 per line that weakens it) over parsable 'old => new' lines."""
    votes = Counter()
    for line in changes.splitlines():
        if ARROW not in line: continue
        label, _, rest = line.partition(':')
        old, _, new = (rest if rest else label).partition(ARROW)
        a, b = first_number(re.sub(r"'''", '', old)), first_number(re.sub(r"'''", '', new))
        if a is None or b is None or a == b: continue
        better = (b < a) if any(w in label.lower() for w in LOWER_IS_BETTER) else (b > a)
        votes['buff' if better else 'nerf'] += 1
    return votes


def classify(context, changes):
    text = context.lower()
    c = Counter(buff=sum(text.count(w) for w in BUFF_WORDS), nerf=sum(text.count(w) for w in NERF_WORDS))
    n = number_votes(changes)
    score = 2 * (c['buff'] - c['nerf']) + (n['buff'] - n['nerf'])
    direction = 'buff' if score > 0 else 'nerf' if score < 0 else 'adjust'
    basis = 'context' if c['buff'] != c['nerf'] else 'numbers' if n['buff'] != n['nerf'] else 'none'
    return direction, basis, dict(c), dict(n)


def clean(text):
    text = re.sub(r'<[^>]+>', ' ', text); text = re.sub(r"'{2,}", '', text)
    text = re.sub(r'\[\[(?:[^|\]]*\|)?([^\]]*)\]\]', r'\1', text)
    return re.sub(r'\s+', ' ', text).strip()


def patch_name(title):
    return title.removeprefix('Patch ')


def order_key(name):
    year, _, rest = name.partition('.')
    if rest.startswith('S1.'): return (int(year), 0, int(rest[3:]))
    return (int(year), 1, int(rest))


def list_pages(root, delay):
    titles = []
    for i, prefix in enumerate(PREFIXES):
        if i: time.sleep(delay)
        url = API + '?' + urllib.parse.urlencode({'action': 'query', 'list': 'allpages', 'apnamespace': 0, 'apprefix': prefix,
                                                  'aplimit': 500, 'format': 'json'})
        record = fetch(root, 'allpages:' + prefix, url=url, raw=RAW, revid=lambda payload: None)
        if record['status'] != 'success': raise SystemExit(f'page listing failed: {prefix}')
        payload = json.loads((root / record['raw_path']).read_bytes())
        titles += [p['title'] for p in payload['query']['allpages'] if TITLE.match(p['title'])]
    return sorted(set(titles), key=lambda t: order_key(patch_name(t)))


def champion_ids(root):
    entities = json.loads((root / CATALOG).read_text())['entities']
    out = {}
    for e in entities:
        for alias in [e['name'], e['source_key']] + e.get('aliases', []): out[re.sub(r'\W', '', alias).lower()] = str(e['id'])
    return out


def build(root, pages):
    ids, records, unknown = champion_ids(root), [], Counter()
    for page in pages:
        if page.get('status') != 'success': continue
        body = (root / page['raw_path']).read_bytes()
        if hashlib.sha256(body).hexdigest() != page['sha256']: raise ValueError(f"raw hash mismatch: {page['raw_path']}")
        content = page_of(json.loads(body))['revisions'][0]['slots']['main']['*']
        for inner in blocks(content):
            f = fields(inner)
            if not f.get('champion'): continue
            cid = ids.get(re.sub(r'\W', '', f['champion']).lower())
            if cid is None: unknown[f['champion']] += 1; continue
            direction, basis, context_votes, number_votes_ = classify(f.get('context', ''), f.get('changes', ''))
            records.append({'patch': patch_name(page['title']), 'date': f.get('date') or None, 'champion_id': cid, 'champion': f['champion'],
                            'direction': direction, 'direction_basis': basis, 'context_votes': context_votes, 'number_votes': number_votes_,
                            'change_lines': sum(1 for line in f.get('changes', '').splitlines() if line.strip().startswith('*')),
                            'context': clean(f.get('context', ''))[:600],
                            'source': {'title': page['title'], 'revid': page['revid'], 'retrieved_at': page['retrieved_at'], 'sha256': page['sha256']}})
    return sorted(records, key=lambda r: (order_key(r['patch']), r['date'] or '', r['champion_id'])), dict(unknown)


def mapping(root):
    """OE patch -> Leaguepedia patch name, from games that carry both; any OE patch with two names is an error."""
    import sqlite3
    connection = sqlite3.connect(root / 'data/processed/lol_bp.sqlite3')
    oe = dict(connection.execute('SELECT gameid, patch_raw FROM games')); connection.close()
    pairs = defaultdict(Counter)
    for line in (root / RESTRICTIONS).read_text().splitlines():
        if not line.strip(): continue
        r = json.loads(line)
        if r['oe_gameid'] in oe and r.get('listed_patch'): pairs[oe[r['oe_gameid']]][r['listed_patch']] += 1
    conflicts = {k: dict(v) for k, v in pairs.items() if len(v) > 1}
    if conflicts: raise SystemExit(f'conflicting patch names: {conflicts}')
    return {k: {'leaguepedia': next(iter(v)), 'games': sum(v.values())} for k, v in sorted(pairs.items())}


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--offline', action='store_true', help='rebuild from cached successful responses only')
    parser.add_argument('--delay', type=float, default=7.0)
    args = parser.parse_args(); root = args.root
    path = root / MANIFEST
    manifest = json.loads(path.read_text()) if path.exists() else {'pages': []}
    cached = {p['title']: p for p in manifest['pages'] if p.get('status') == 'success'}
    titles = sorted(cached, key=lambda t: order_key(patch_name(t))) if args.offline else list_pages(root, args.delay)
    pages = []
    for title in titles:
        if title in cached: pages.append(cached[title]); continue
        time.sleep(args.delay)
        record = fetch(root, title, url=revisions_url(title), raw=RAW, revid=revision_id)
        pages.append(record); print(title, record['status'], flush=True)
    records, unknown = build(root, pages)
    counts = Counter(r['direction'] for r in records); bases = Counter(r['direction_basis'] for r in records)
    manifest = {'schema_version': 1, 'user_agent': USER_AGENT, 'pages': pages, 'unknown_champions': unknown,
                'summary': {'pages': len(pages), 'success': sum(p.get('status') == 'success' for p in pages), 'changes': len(records),
                            'directions': dict(counts), 'direction_basis': dict(bases)}}
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + '\n')
    (root / OUTPUT).write_text(''.join(json.dumps(r, ensure_ascii=False, sort_keys=True) + '\n' for r in records))
    (root / MAPPING).write_text(json.dumps({'schema_version': 1, 'evidence': RESTRICTIONS, 'evidence_status': 'community_listed_per_game',
                                            'mapping': mapping(root)}, ensure_ascii=False, indent=2, sort_keys=True) + '\n')
    print(json.dumps(manifest['summary'], ensure_ascii=False))
    if manifest['summary']['success'] != len(pages): raise SystemExit(1)


if __name__ == '__main__': main()
