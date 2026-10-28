#!/usr/bin/env python3
"""Fetch explicit public rules sources once, preserving successes and HTTP failures."""
import urllib.request, urllib.error, hashlib, json, datetime
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SOURCES={
'riot_library':'https://competitiveops.riotgames.com/en-US/library?SPIEL=lol',
'season_start_2026':'https://lolesports.com/en-AU/news/season-start-2026-lol-esports',
'fearless_2025':'https://lolesports.com/en-PH/news/fearless-draft-takes-over-2025',
'fearless_explained_2025':'https://lolesports.com/en-US/news/lol-esports-in-2025',
'worlds_2026_primer':'https://lolesports.com/en-GB/news/worlds-2026-primer',
'international_2026':'https://cdn.sanity.io/files/dsfx7636/news_live/d29e446e0a0d0813a8caaae1d2817dd82cfe79c6.pdf',
'worlds_2026_rules':'https://cdn.sanity.io/files/dsfx7636/news_live/faa5ce974e58615911fbee931c6123e2785a8b46.pdf',
'lck_2026_rules':'https://cdn.sanity.io/files/dsfx7636/news_live/4b72bb20244653d0d7dbe162e929d1c07b1f936f.pdf',
'lck_2026_event':'https://cdn.sanity.io/files/dsfx7636/news_live/b5e4819daa2793425433910ca02b1c479b2f15a3.pdf',
'lck_2024_mirror':'https://static.wikia.nocookie.net/lolesports_gamepedia_en/images/7/74/LCK_2024_Rulebook.pdf/revision/latest?cb=20240413022358',
'patch_14_16':'https://www.leagueoflegends.com/en-us/news/game-updates/patch-14-16-notes/',
'patch_26_20':'https://www.leagueoflegends.com/en-us/news/game-updates/league-of-legends-patch-26-20-notes/',
'ddragon_14_16_1':'https://ddragon.leagueoflegends.com/cdn/14.16.1/data/en_US/champion/Ahri.json',
'ddragon_16_20_1':'https://ddragon.leagueoflegends.com/cdn/16.20.1/data/en_US/champion/Ahri.json',
'riot_ddragon_docs':'https://developer.riotgames.com/docs/lol#data-dragon',
}
def save_bytes(root, body, suffix):
 digest = hashlib.sha256(body).hexdigest()
 path = Path('data/raw/rules/sha256') / (digest + suffix)
 target = root / path
 target.parent.mkdir(parents=True, exist_ok=True)
 if target.exists() and target.read_bytes() != body:
  raise ValueError('Content-addressed cache mismatch: ' + str(path))
 if not target.exists():
  target.write_bytes(body)
 return str(path), digest


def migrate_manifest(root, manifest):
 """Pin legacy source IDs; preserve observations and bind reviews to exact bytes."""
 if manifest.get('schema_version') == 2:
  return manifest
 manifest['schema_version'] = 2
 manifest.setdefault('snapshots', [])
 manifest.setdefault('semantic_reviews', [])
 manifest.setdefault('collections', [])
 for source in manifest.get('sources', []):
  body = (root / source['path']).read_bytes()
  if hashlib.sha256(body).hexdigest() != source['sha256']:
   raise ValueError('Legacy source hash mismatch: ' + source['source_id'])
  source['legacy_path'] = source['path']
  path, digest = save_bytes(root, body, Path(source['path']).suffix)
  source['path'] = path
  source['semantic_status'] = 'unreviewed'
  snapshot = {k: v for k, v in source.items() if k not in ('content_status', 'publisher')}
  manifest['snapshots'].append(snapshot)
  if source.get('content_status') or source.get('publisher'):
   manifest['semantic_reviews'].append({
    'source_id': source['source_id'], 'sha256': digest,
    'review_kind': 'legacy_observation',
    **{k: source[k] for k in ('content_status', 'publisher') if k in source}})
 return manifest


def collect_source(root, key, url, opener=urllib.request.urlopen):
 record = {'source_id': key, 'url': url,
           'attempted_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
           'semantic_status': 'unreviewed'}
 try:
  response = opener(urllib.request.Request(url, headers={
      'User-Agent': 'LOL-bp-research/0.1 (public source audit)'}), timeout=40)
  body = response.read()
  record['retrieved_at_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
  record.update(status=response.status, final_url=response.url,
                content_type=response.headers.get('Content-Type'),
                last_modified=response.headers.get('Last-Modified'))
 except urllib.error.HTTPError as error:
  body = error.read()
  record['retrieved_at_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
  record.update(status=error.code, error=str(error))
 except Exception as error:
  body = b''
  record.update(status='fetch_error', error=str(error))
 suffix = '.pdf' if body.startswith(b'%PDF') else '.json' if key.startswith('ddragon_') else '.html'
 path, digest = save_bytes(root, body, suffix)
 record.update(path=path, sha256=digest, bytes=len(body))
 return record


def add_collection(manifest, records):
 # New attempts are never promoted by a prior review, even for identical bytes.
 for record in records:
  record['semantic_status'] = 'unreviewed'
  manifest['snapshots'].append(record)
 manifest['collections'].append({
  'collected_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
  'results': records})
 # sources remains the original pinned source_id -> hash mapping used by curated.
 return manifest


def main():
 import argparse
 parser = argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--migrate-only', action='store_true', help='Migrate existing bytes without network')
 args = parser.parse_args()
 path = ROOT / 'data/manifests/rules-evidence.json'
 manifest = json.loads(path.read_text()) if path.exists() else {
     'schema_version': 2, 'sources': [], 'snapshots': [], 'semantic_reviews': [], 'collections': []}
 manifest = migrate_manifest(ROOT, manifest)
 if not args.migrate_only:
  records = []
  for key, url in SOURCES.items():
   record = collect_source(ROOT, key, url)
   records.append(record)
   print(key, record['status'], record['bytes'], flush=True)
  add_collection(manifest, records)
 temporary = path.with_suffix('.json.tmp')
 temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
 temporary.replace(path)


if __name__ == '__main__':
 main()
