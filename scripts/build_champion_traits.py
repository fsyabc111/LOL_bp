#!/usr/bin/env python3
"""Derive coarse champion traits for composition profiles from the pinned Data Dragon champion list.

Reads the raw 16.20.1 en_US champion.json recorded in data/manifests/static-data.json, refuses to run if its
SHA-256 differs from the manifest, and writes data/curated/champion_traits.json: tags, the info ratings
(attack/defense/magic/difficulty, 0-10), resource type and attack range per champion id. The ratings are Riot's
coarse descriptors, not measured damage splits, and are not necessarily maintained per patch.
Offline and deterministic (no timestamps).
"""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from assemble_sample import ROOT, digest, read_json  # noqa: E402

VERSION = '16.20.1'
MANIFEST = 'data/manifests/static-data.json'
OUTPUT = 'data/curated/champion_traits.json'


def main():
    manifest = read_json(ROOT / MANIFEST)
    url = f'https://ddragon.leagueoflegends.com/cdn/{VERSION}/data/en_US/champion.json'
    record = next(r for r in manifest['responses'] if r.get('url') == url and r.get('status') == 'success')
    raw = ROOT / record['raw_path']
    if digest(raw) != record['sha256']: sys.exit(f'{raw} 与 manifest 记录的 SHA-256 不一致，拒绝生成')
    data = read_json(raw)['data']
    champions = []
    for key, entity in sorted(data.items(), key=lambda kv: int(kv[1]['key'])):
        champions.append({'id': str(entity['key']), 'source_key': key, 'tags': entity.get('tags', []), 'info': entity['info'],
                          'resource_type': entity.get('partype'), 'attack_range': entity['stats']['attackrange']})
    out = {'schema_version': 1, 'version': VERSION, 'source_url': url, 'raw_sha256': record['sha256'],
           'evidence_type': 'riot_static_descriptor',
           'note': 'info 评分与 tags 是 Riot 的粗粒度描述（0–10），不是实测伤害构成，且不一定随补丁更新。',
           'champions': champions}
    (ROOT / OUTPUT).write_text(json.dumps(out, ensure_ascii=False, indent=1) + '\n')
    print(f'wrote {OUTPUT}: {len(champions)} champions')


if __name__ == '__main__': main()
