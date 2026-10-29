#!/usr/bin/env python3
"""Which champions existed on each patch the dataset uses, from Data Dragon's champion list per version.

For every OE patch in the target leagues (13.01 ... 16.20) the matching Data Dragon version is '<major>.<minor>.1'
and must appear in versions.json. Each en_US champion.json is fetched once (sequential, raw bytes content-addressed
under data/raw/static-availability/) and reduced to its champion ids. Writes data/curated/champion_availability.json
(deterministic) and data/manifests/champion-availability.json. Data Dragon resource versions are not proof of the
tournament server build; a champion listed there was at least released to the game.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
RAW = 'data/raw/static-availability'
OUTPUT = 'data/curated/champion_availability.json'
MANIFEST = 'data/manifests/champion-availability.json'
BASE = 'https://ddragon.leagueoflegends.com'
LEAGUES = ('LCK', 'LPL', 'WLDs')


def fetch(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'LOL_bp research (self-use)'}), timeout=60) as r:
        return r.read()


def stored(root, body):
    digest = hashlib.sha256(body).hexdigest()
    path = root / RAW / f'{digest}.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists(): path.write_bytes(body)
    return path, digest


def version_of(patch):
    major, minor = patch.split('.')
    return f'{int(major)}.{int(minor)}.1'


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--offline', action='store_true', help='rebuild from the cached raw responses in the manifest')
    parser.add_argument('--delay', type=float, default=1.0)
    args = parser.parse_args(); root = ROOT
    connection = sqlite3.connect(root / 'data/processed/lol_bp.sqlite3')
    patches = sorted({p for (p,) in connection.execute(f"SELECT DISTINCT patch_raw FROM games WHERE league_raw IN ({','.join('?' * len(LEAGUES))})", LEAGUES) if p})
    connection.close()
    old = json.loads((root / MANIFEST).read_text()) if (root / MANIFEST).exists() else {'responses': {}}
    responses = dict(old['responses'])
    if not args.offline:
        versions = json.loads(fetch(BASE + '/api/versions.json'))
        missing = [p for p in patches if version_of(p) not in versions]
        if missing: sys.exit(f'no Data Dragon version for patches {missing}')
    out = {}
    for patch in patches:
        version = version_of(patch)
        if version not in responses or not (root / responses[version]['raw_path']).exists():
            if args.offline: sys.exit(f'{version} not cached')
            url = f'{BASE}/cdn/{version}/data/en_US/champion.json'
            time.sleep(args.delay); body = fetch(url); path, digest = stored(root, body)
            responses[version] = {'url': url, 'raw_path': str(path.relative_to(root)), 'sha256': digest, 'bytes': len(body)}
            print(version, 'fetched', flush=True)
        record = responses[version]; body = (root / record['raw_path']).read_bytes()
        if hashlib.sha256(body).hexdigest() != record['sha256']: sys.exit(f"hash mismatch for {record['raw_path']}")
        data = json.loads(body)
        if data['version'] != version: sys.exit(f"{version}: file reports version {data['version']}")
        out[patch] = {'version': version, 'champion_ids': sorted((e['key'] for e in data['data'].values()), key=int)}
    (root / OUTPUT).write_text(json.dumps({'schema_version': 1, 'source': BASE, 'evidence_type': 'riot_static_resource_version',
                                          'patches': out}, indent=1, sort_keys=True) + '\n')
    (root / MANIFEST).write_text(json.dumps({'schema_version': 1, 'responses': dict(sorted(responses.items()))}, indent=2, sort_keys=True) + '\n')
    counts = [len(v['champion_ids']) for v in out.values()]
    print(f'wrote {OUTPUT}: {len(out)} patches, {min(counts)}–{max(counts)} champions')


if __name__ == '__main__': main()
