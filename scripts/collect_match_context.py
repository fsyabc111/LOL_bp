#!/usr/bin/env python3
"""Reproduce source-record context joins. Requires pyarrow==21.0.0 (or pandas + fastparquet).

GPTilt is a Leaguepedia-derived snapshot; this does not verify broadcast truth.
No champion array in this source is draft order. No fuzzy team-name join is used.
"""
import argparse, csv, hashlib, json, urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REVISION = '04787d28f0661cff22568c3abc5f39a406906b6d'
BASE = 'https://huggingface.co/datasets/gptilt/lol-esports-matches/resolve/' + REVISION + '/'

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def download(raw):
    acquisitions = []
    for filename, remote in [('games.parquet','games/games.parquet'), ('matches.parquet','matches/matches.parquet'), ('README.md','README.md')]:
        url = BASE + remote
        with urllib.request.urlopen(url, timeout=90) as response:
            content = response.read()
            (raw / filename).write_bytes(content)
            acquisitions.append(dict(path=str((raw/filename).relative_to(ROOT)),source_url=url,
                retrieved_at=datetime.now(timezone.utc).isoformat(),http_status=response.status,
                sha256=hashlib.sha256(content).hexdigest(),bytes=len(content)))
    (raw/'acquisitions.json').write_text(json.dumps(acquisitions,indent=2)+'\n')

def load_oe(year):
    groups = defaultdict(list)
    with (ROOT / f'data/{year}_LoL_esports_match_data_from_OraclesElixir.csv').open() as stream:
        for row in csv.DictReader(stream):
            if row['position'] == 'team' and row['league'] in {'LCK','LPL','WLDs'}:
                groups[row['gameid']].append(row)
    return groups

def identity(rows):
    return rows[0]['date'][:10], frozenset(r['teamname'] for r in rows)

def source_identity(game):
    return str(game['datetime_utc'])[:10], frozenset([game['team_blue'],game['team_red']])

def compatible(game, rows):
    if not rows or identity(rows) != source_identity(game): return False
    oe_champs = {r['teamname']: {r[f'pick{i}'] for i in range(1,6)} for r in rows}
    return (oe_champs.get(game['team_blue']) == set(game['picks_blue']) and
            oe_champs.get(game['team_red']) == set(game['picks_red']))

def join_game(gameid, rows, by_riot, by_identity):
    exact = by_riot.get(gameid, [])
    if len(exact) == 1:
        if compatible(exact[0],rows): return exact[0], 'exact_riot_game_id_cross_checked'
        return None, 'exact_riot_game_id_conflict'
    candidates = by_identity.get(identity(rows), [])
    matches = [g for g in candidates if compatible(g,rows)]
    if len(matches) == 1:
        return matches[0], 'unique_calendar_date_exact_teams_and_both_champion_sets'
    return None, 'unmatched_or_ambiguous'

def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--download', action='store_true'); args = parser.parse_args()
    try:
        import pyarrow.parquet as pq
        def read_records(path): return pq.read_table(path).to_pylist()
    except ImportError:
        import fastparquet
        def read_records(path): return fastparquet.ParquetFile(path).to_pandas().to_dict('records')
    raw = ROOT / 'data/raw/match-context'; raw.mkdir(parents=True, exist_ok=True)
    if args.download: download(raw)
    expected_hashes = {
        'games.parquet':'71b9c84e140f213cdda57ceb65807137ea8281bf56ac580c8459ae9c59d32cac',
        'matches.parquet':'2eab5d78107c70dba6d9f8f548a83b2bd4bc1c929e2355883f717be90a796191',
    }
    for name, expected in expected_hashes.items():
        if sha(raw/name) != expected:
            raise ValueError(f'{name}: cache does not match pinned Hugging Face LFS SHA-256')
    games = read_records(raw/'games.parquet')
    series = {r['match_id']:r for r in read_records(raw/'matches.parquet')}
    by_riot, by_identity = defaultdict(list), defaultdict(list)
    for game in games:
        if game['riot_game_id']: by_riot[str(game['riot_game_id'])].append(game)
        by_identity[source_identity(game)].append(game)
    oe24, oe26 = load_oe(2024), load_oe(2026)
    selected = [(gid, rows) for gid,rows in oe24.items() if rows[0]['league']=='LCK' and rows[0]['playoffs']=='1' and '2024-08-23' <= rows[0]['date'][:10] <= '2024-09-08']
    # Select one latest completely represented source series per OE league label.
    joined26 = [(gid, rows, *join_game(gid,rows,by_riot,by_identity)) for gid,rows in oe26.items()]
    chosen = {}
    for league in ['LPL','LCK','WLDs']:
        candidates = defaultdict(list)
        for gid,rows,g,method in joined26:
            if rows[0]['league']==league and g: candidates[g['match_id']].append((gid,rows))
        complete = []
        for mid, members in candidates.items():
            expected = [g for g in games if g['match_id']==mid]
            if len(members)==len(expected) and mid in series and int(series[mid].get('best_of') or 0) > 1: complete.append((max(r[0]['date'] for _,r in members),mid,members))
        if complete:
            _,mid,members=max(complete);selected.extend(members);chosen[league]=mid
    records = []
    for gid, rows in selected:
        game, method = join_game(gid,rows,by_riot,by_identity)
        match = series.get(game['match_id'],{}) if game else {}
        record = dict(oe_gameid=gid, oe_league=rows[0]['league'], mapping_method=method,
            evidence_status='source_record_verified' if game else ('conflict' if method=='exact_riot_game_id_conflict' else 'unmatched'),
            evidence_scope='GPTilt published record and deterministic OE linkage; Leaguepedia shared upstream; not independent VOD verification',
            bp_order_status='unknown', bp_order=None)
        if game:
            record.update(series_id=game['match_id'], source_game_id=game['game_id'], tournament=game['tournament'],
                stage=match.get('tab'),best_of=match.get('best_of'),game_number=game['game_number'],
                datetime_utc=str(game['datetime_utc']),teams={'blue':game['team_blue'],'red':game['team_red']},
                patch=game['patch'],oe_patch=rows[0]['patch'],patch_comparison='exact' if rows[0]['patch']==game['patch'] else 'different_source_notation_unresolved',source_url=game['source_url'],vod=game['vod'],
                source_locator={'revision':REVISION,'games_key':game['game_id'],'matches_key':game['match_id']},
                source_snapshot_sha256={'games':sha(raw/'games.parquet'),'matches':sha(raw/'matches.parquet')},date_comparison='OE calendar-date compared to source datetime_utc date without timezone conversion; OE timezone not confirmed')
        records.append(record)
    output=ROOT/'data/curated/match_context.jsonl';output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(''.join(json.dumps(r,ensure_ascii=False,sort_keys=True)+'\n' for r in records))
    selected_keys = {r.get('source_game_id') for r in records}
    selected_series = {r.get('series_id') for r in records}
    (raw/'selected-source-records.json').write_text(json.dumps(dict(
        source_revision=REVISION,
        games=[g for g in games if g['game_id'] in selected_keys],
        matches=[m for key,m in series.items() if key in selected_series]),ensure_ascii=False,indent=2)+'\n')
    manifest = dict(schema_version=1, generated_at=datetime.now(timezone.utc).isoformat(), source_revision=REVISION,
        source='GPTilt / Leaguepedia-derived',license='CC-BY-SA-3.0 per publisher data card', selected_2026_series=chosen,
        records=len(records),matched=sum(r['evidence_status']=='source_record_verified' for r in records),
        source_game_rows=len(games), latest_source_datetime=max(str(g['datetime_utc']) for g in games),
        snapshots=[dict(path=str(p.relative_to(ROOT)),sha256=sha(p),bytes=p.stat().st_size) for p in sorted(raw.iterdir()) if p.is_file()],
        acquisitions=json.loads((raw/'acquisitions.json').read_text()) if (raw/'acquisitions.json').exists() else [],
        bp_order_verified=0, limitations=['GPTilt picks are role ordered, never draft order','Source snapshots share Leaguepedia upstream; linkage is not independent truth verification'])
    (ROOT/'data/manifests/match-context.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:manifest[k] for k in ['records','matched','latest_source_datetime','selected_2026_series']},ensure_ascii=False))
if __name__=='__main__':main()
