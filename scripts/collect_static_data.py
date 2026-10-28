#!/usr/bin/env python3
"""Version-pinned Data Dragon snapshots; Python standard library only."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import time
from datetime import datetime, timezone
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
BASE = 'https://ddragon.leagueoflegends.com'
DEFAULT_CHAMPIONS = ['Ahri', 'Azir', 'Corki', 'Gnar', 'KSante', 'LeeSin', 'Maokai', 'Rell', 'Tristana', 'Vi', 'Ziggs']


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n', encoding='utf-8')


def validate(payload, kind, version=None, champion=None):
    if kind == 'versions':
        if not isinstance(payload, list) or not payload or not all(isinstance(v, str) for v in payload):
            raise ValueError('invalid versions list')
        return
    if kind == 'runesReforged':
        if not isinstance(payload, list) or not payload or not all(isinstance(x, dict) and isinstance(x.get('id'), int) and isinstance(x.get('slots'), list) for x in payload):
            raise ValueError('invalid rune tree')
        return  # This endpoint carries no embedded version: URL pin only.
    if not isinstance(payload, dict) or payload.get('version') != version:
        raise ValueError('embedded version mismatch')
    data = payload.get('data')
    if not isinstance(data, dict) or not data:
        raise ValueError('missing entity data')
    if kind == 'champion' and not all(isinstance(x, dict) and str(x.get('key', '')).isdigit() and isinstance(x.get('stats'), dict) for x in data.values()):
        raise ValueError('invalid champion identity/stats')
    if champion and (list(data) != [champion] or len(data[champion].get('spells', [])) != 4):
        raise ValueError('unexpected champion or incomplete spells')


class Collector:
    def __init__(self, root=ROOT, refresh=False, attempts=3, offline=False):
        self.root, self.refresh, self.attempts = root, refresh, attempts
        self.offline = offline
        self.records = []

    def fetch(self, relative, kind, version=None, champion=None):
        path = self.root / 'data/raw/static' / relative
        url = BASE + ('/api/versions.json' if kind == 'versions' else '/cdn/' + relative)
        record = {'url': url, 'raw_path': str(path.relative_to(self.root)), 'requested_version': version, 'status': 'failed', 'attempted_at': datetime.now(timezone.utc).isoformat()}
        self.records.append(record)
        for attempt in range(self.attempts):
            try:
                cached = path.exists() and not self.refresh
                if cached:
                    raw = path.read_bytes()
                    meta_path = path.with_suffix('.meta.json')
                    if not meta_path.exists():
                        raise ValueError('cache provenance missing; rerun --refresh')
                    meta = json.loads(meta_path.read_text())
                    if meta['sha256'] != hashlib.sha256(raw).hexdigest():
                        raise ValueError('cache hash mismatch; rerun --refresh')
                else:
                    if self.offline:
                        raise ValueError('offline cache missing')
                    with urlopen(Request(url, headers={'User-Agent': 'LOL-BP-static-research/0.1'}), timeout=45) as response:
                        if not 200 <= response.status < 300:
                            raise ValueError('non-2xx response')
                        raw = response.read()
                        meta = {'retrieved_at': datetime.now(timezone.utc).isoformat(), 'http_status': response.status, 'last_modified': response.headers.get('Last-Modified')}
                        size = response.headers.get('Content-Length')
                        if size is not None and len(raw) != int(size):
                            raise ValueError('truncated response')
                record.update(meta)
                record.update(sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw), cached=cached, attempts=attempt + 1)
                # Save even invalid responses as evidence; never normalize them.
                if not cached:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(raw)
                    write_json(path.with_suffix('.meta.json'), {**meta, 'sha256': record['sha256']})
                payload = json.loads(raw)
                validate(payload, kind, version, champion)
                record.pop('error', None)
                record.update(status='success', version_verification='url_only' if kind == 'runesReforged' else ('list' if kind == 'versions' else 'embedded_exact'))
                print(f"OK {relative} ({len(raw)} bytes)", flush=True)
                return payload
            except Exception as error:
                record['error'] = f'{type(error).__name__}: {error}'
                record['attempts'] = attempt + 1
                if cached or self.offline:
                    break
                if attempt + 1 < self.attempts:
                    time.sleep(attempt + 1)
        print(f"FAILED {relative}: {record.get('error', 'unknown')}", flush=True)
        return None


def normalize_spell(spell, slot):
    fields = ('id', 'name', 'description', 'tooltip', 'maxrank', 'cooldown', 'cooldownBurn', 'cost', 'costBurn', 'costType', 'range', 'rangeBurn', 'effect', 'effectBurn', 'vars', 'resource', 'leveltip')
    result = {k: spell[k] for k in fields if k in spell}
    result['slot'] = slot
    result['unresolved_placeholders'] = sorted(set(re.findall(r'\{\{\s*([^}]+?)\s*\}\}', json.dumps(result, ensure_ascii=False))))
    result['formula_resolution'] = 'unknown'
    result['evidence_type'] = 'observed'
    return result


def normalize(payload, kind, locale):
    if kind == 'runesReforged':
        return payload
    result = []
    for key, entity in payload['data'].items():
        if kind == 'champion':
            row = {'id': int(entity['key']), 'source_key': key, 'aliases': [key, entity['name']], 'name': entity['name'], 'title': entity.get('title'), 'stats': entity['stats'], 'tags': entity.get('tags', []), 'resource_type': entity.get('partype'), 'locale': locale}
            if 'spells' in entity:
                row['spells'] = [normalize_spell(spell, slot) for spell, slot in zip(entity['spells'], 'QWER')]
                row['passive'] = {k: v for k, v in entity.get('passive', {}).items() if k != 'image'}
        else:
            row = {k: v for k, v in entity.items() if k != 'image'}
            row['id'] = int(key) if kind == 'item' else int(entity['key'])
            row['source_key'] = key
        result.append(row)
    return sorted(result, key=lambda x: x['id'])


def output_record(root, target, rows, source_relative):
    return {'path': str(target), 'count': len(rows),
            'sha256': hashlib.sha256((root / target).read_bytes()).hexdigest(),
            'source_snapshot_sha256': hashlib.sha256((root / 'data/raw/static' / source_relative).read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--versions', nargs='+', default=['14.16.1', '16.16.1', '16.17.1', '16.20.1'])
    parser.add_argument('--detail-versions', nargs='+', default=['14.16.1', '16.20.1'])
    parser.add_argument('--champions', nargs='+', default=DEFAULT_CHAMPIONS)
    parser.add_argument('--refresh', action='store_true')
    parser.add_argument('--offline', action='store_true', help='Require existing validated raw caches; never open network')
    args = parser.parse_args()
    if args.refresh and args.offline:
        parser.error('--refresh and --offline cannot be combined')
    collector = Collector(refresh=args.refresh, offline=args.offline)
    versions = collector.fetch('versions.json', 'versions')
    outputs = []
    for version in args.versions:
        if versions is None or version not in versions:
            collector.records.append({'requested_version': version, 'status': 'failed', 'attempted_at': datetime.now(timezone.utc).isoformat(), 'error': 'target version absent or versions endpoint unavailable'})
            for locale in ('en_US', 'zh_CN'):
                targets = [f'{kind}.json' for kind in ('champion', 'item', 'runesReforged', 'summoner')]
                if version in args.detail_versions:
                    targets += [f'details/{champion}.json' for champion in args.champions]
                for filename in targets:
                    (ROOT / 'data/curated/static' / version / locale / filename).unlink(missing_ok=True)
            continue
        jobs = [(locale, kind, None) for locale in ('en_US', 'zh_CN') for kind in ('champion', 'item', 'runesReforged', 'summoner')]
        if version in args.detail_versions:
            jobs += [(locale, 'champion', champion) for locale in ('en_US', 'zh_CN') for champion in args.champions]
        def collect_job(job):
            locale, kind, champion = job
            suffix = f'/{champion}' if champion else ''
            relative = f'{version}/data/{locale}/{kind}{suffix}.json'
            filename = f'details/{champion}.json' if champion else f'{kind}.json'
            target = Path('data/curated/static') / version / locale / filename
            payload = collector.fetch(relative, kind, version, champion)
            if payload is None:
                (ROOT / target).unlink(missing_ok=True)
                return None
            rows = normalize(payload, kind, locale)
            write_json(ROOT / target, {'version': version, 'locale': locale, 'evidence_type': 'observed', 'source_url': BASE + '/cdn/' + relative, 'entities': rows})
            return output_record(ROOT, target, rows, relative)
        with ThreadPoolExecutor(max_workers=4) as executor:
            outputs.extend(output for output in executor.map(collect_job, jobs) if output is not None)
    collector.records.sort(key=lambda r: (r.get('requested_version') or '', r.get('url', '')))
    outputs.sort(key=lambda output: output['path'])
    manifest = {'schema_version': 1, 'generated_at': datetime.now(timezone.utc).isoformat(), 'source': 'Riot Data Dragon', 'patch_mapping': {'14.16.1': {'patch': '14.16', 'status': 'numeric_patch_mapping; event_binding_requires_match_evidence'}, '16.16.1': {'patch': '26.16', 'status': 'pending_official_patch_to_ddragon_mapping'}, '16.17.1': {'patch': '26.17', 'status': 'pending_official_patch_to_ddragon_mapping'}, '16.20.1': {'patch': '26.20', 'status': 'pending_official_patch_to_ddragon_mapping'}}, 'requested_versions': args.versions, 'requested_detail_champions': args.champions, 'detail_versions': args.detail_versions, 'responses': collector.records, 'outputs': outputs}
    manifest['summary'] = {'success': sum(r['status'] == 'success' for r in collector.records), 'failed': sum(r['status'] != 'success' for r in collector.records), 'curated_files': len(outputs)}
    write_json(ROOT / 'data/manifests/static-data.json', manifest)
    print(json.dumps(manifest['summary']))
    return int(manifest['summary']['failed'] > 0)


if __name__ == '__main__':
    raise SystemExit(main())
