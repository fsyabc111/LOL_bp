#!/usr/bin/env python3
"""Deterministic, offline sample integration. No model training; BP readiness comes only from validate_bp.py."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def read_json(path): return json.loads(path.read_text())
def read_jsonl(path): return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]

def checked_output(root, path, expected):
    target=root/path
    if not expected: raise ValueError(f'output lacks sha256: {path}')
    if not target.is_file() or digest(target)!=expected: raise ValueError(f'output sha256 conflict or missing file: {path}')
    return target

def resolve_name(name, champions):
    exact=[c for c in champions if name in [c.get('name'),c.get('id')] + c.get('aliases',[])]
    if len(exact)==1: return {'source_name':name,'champion_id':int(exact[0]['id']),'method':'exact_alias'}
    matches=[c for c in champions if name.casefold() in [str(a).casefold() for a in [c.get('name'),c.get('id')]+c.get('aliases',[]) if a]]
    if len(matches)==1: return {'source_name':name,'champion_id':int(matches[0]['id']),'method':'unique_casefold'}
    return {'source_name':name,'champion_id':None,'method':'unknown'}

def choose_asset(patch, patches):
    # Only declared candidate mappings, never nearest/latest version fallback.
    for item in patches.get('patches',[]):
        if patch==item['id']:
            return item.get('ddragon_version',{}).get('value'),item.get('display_to_asset_mapping_status','unknown')
    if patch in {'16.16','16.17','16.20'}: return patch+'.1','numeric_candidate_event_build_unverified'
    return None,'missing_patch_mapping'

def competition_for_rules(game, context):
    league=game['league_raw']
    if league=='WLDs':
        tournament=context.get('tournament','').casefold()
        league='Worlds' if (context.get('evidence_status')=='source_record_verified' and
            ('world championship' in tournament or 'worlds' in tournament) and
            'regional qualifier' not in tournament) else 'unknown_pending'
    return league

def applicable_rules(game, context, rules):
    league=competition_for_rules(game,context)
    year=int(game['date_raw'][:4]); output=[]
    for rule in rules['rules']:
        competitions=rule.get('competition',[])
        if isinstance(competitions,str): competitions=[competitions]
        if league not in competitions or rule.get('year')!=year: continue
        status=rule.get('applicability_status','unknown')
        if rule.get('effective_from') and game['date_raw'][:10]<rule['effective_from']: status='not_applicable_before_effective_date'
        if rule['rule_id']=='lck_2024_summer_playoffs_candidate' and 'Summer Playoffs' not in context.get('tournament',''): status='unknown_stage'
        if rule['rule_id']=='lck_2026_from_2026_07_29' and 'Season Playoffs' not in context.get('tournament',''): status='unknown_scope'
        unknown=[key for key in ['draft_template','cross_game_ban_scope','event_disabled_champions'] if rule.get(key,{}).get('status','unknown')=='unknown']
        output.append({'rule_id':rule['rule_id'],'applicability_status':status,'unknown_fields':unknown})
    return output

def assemble_record(game, context, rules, patches, catalogs, validation=None):
    version,mapping=choose_asset(game['patch_raw'],patches)
    champions=catalogs.get(version,[]) if version else []
    names=sorted({n for team in game.get('teams',[]) for field in ['picks_source_columns','bans_source_columns'] for n in team.get(field,[]) if n})
    entities=[resolve_name(name,champions) for name in names]
    rule_candidates=applicable_rules(game,context,rules)
    # Only the per-step validator result can grant BP readiness; source flags never do.
    validation=validation or {'status':'not_run'}
    bp=validation['status']=='verified'
    context_ok=context.get('evidence_status')=='source_record_verified'
    source_ok=game.get('quality',{}).get('structural_valid',False)
    entity_ok=bool(champions) and all(x['champion_id'] is not None for x in entities)
    rule_complete=any(r['applicability_status']=='observed' and not r['unknown_fields'] for r in rule_candidates)
    blockers=[]
    if not context_ok:blockers.append('context_unverified')
    if not source_ok:blockers.append('source_structure_invalid')
    if not champions:blockers.append('same_patch_static_assets_missing')
    elif not entity_ok:blockers.append('champion_identity_unknown')
    if mapping!='observed':blockers.append('static_version_mapping_'+mapping)
    if not rule_complete:blockers.append('applicable_rules_incomplete_or_inferred')
    if not bp:blockers.append('bp_order_not_verified')
    return dict(oe_gameid=game['oe_gameid'],competition_for_rules=competition_for_rules(game,context),series_id=context.get('series_id'),source_game_id=context.get('source_game_id'),
        sources={'oe_source_id':game.get('source_id'),'context_source_url':context.get('source_url'),'source_locator':context.get('source_locator')},
        patches={'oe_raw':game['patch_raw'],'context_raw':context.get('patch'),'context_comparison':context.get('patch_comparison'),
            'candidate_static_version':version,'mapping_status':mapping,'static_available':bool(champions)},
        champion_entities=entities,candidate_rules=rule_candidates,
        readiness={'context':context_ok,'source_data':source_ok,'entities_same_candidate_version':entity_ok,
            'rules_complete':rule_complete,'bp_verified':bp,'bp_validator_status':validation['status'],'replay_ready':not blockers},blockers=blockers)

def load_catalogs(root,manifest):
    responses={r.get('url'):r for r in manifest.get('responses',[]) if r.get('status')=='success'}
    catalogs={}; checked=[]
    for output in manifest.get('outputs',[]):
        path=checked_output(root,output['path'],output.get('sha256'))
        payload=read_json(path)
        source=responses.get(payload.get('source_url'))
        if not source: raise ValueError(f'output lacks successful source response: {path}')
        source_hash=output.get('source_snapshot_sha256')
        if source_hash!=source.get('sha256'): raise ValueError(f'source sha256 conflict: {path}')
        checked_output(root,source['raw_path'],source_hash)
        checked.append({'path':output['path'],'sha256':output['sha256'],'source_snapshot_sha256':source_hash})
        if path.name=='champion.json' and payload.get('locale')=='en_US':
            version=payload['version']
            if path.parent.parent.name!=version or source.get('requested_version')!=version:
                raise ValueError(f'static version mismatch: {path}')
            catalogs[version]=payload['entities']
    return catalogs,checked

def load_validation(root, path, inputs):
    validation=read_json(root/path)
    for key,expected in validation.get('input_sha256',{}).items():
        if not (root/key).is_file() or digest(root/key)!=expected: raise ValueError(f'stale BP validation; rerun validate_bp.py: {key}')
    missing=[p for p in inputs if p not in validation.get('input_sha256',{})]
    if missing: raise ValueError(f'BP validation lacks input hashes: {missing}')
    return {r['oe_gameid']:r for r in validation['records']}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,default=ROOT);args=parser.parse_args();root=args.root
    paths=['data/curated/replay_candidates.jsonl','data/curated/match_context.jsonl','data/curated/rules.json','data/curated/patches.json','data/manifests/static-data.json','data/curated/bp-validation.json']
    for path in paths:
        if not (root/path).is_file():raise FileNotFoundError(f'required integration input absent: {path}')
    games=read_jsonl(root/paths[0]);contexts={r['oe_gameid']:r for r in read_jsonl(root/paths[1])}
    catalogs,assets=load_catalogs(root,read_json(root/paths[4]))
    validations=load_validation(root,paths[5],paths[:5])
    records=[assemble_record(g,contexts.get(g['oe_gameid'],{}),read_json(root/paths[2]),read_json(root/paths[3]),catalogs,validations.get(g['oe_gameid'])) for g in sorted(games,key=lambda x:x['oe_gameid'])]
    output={'schema_version':1,'input_sha256':{p:digest(root/p) for p in paths},'validated_static_outputs':assets,'records':records,
        'summary':{'games':len(records),'replay_ready':sum(r['readiness']['replay_ready'] for r in records),
            'readiness_counts':{key:sum(bool(r['readiness'][key]) for r in records) for key in ['context','source_data','entities_same_candidate_version','rules_complete','bp_verified']},
            'bp_validator_status_counts':dict(sorted(Counter(r['readiness']['bp_validator_status'] for r in records).items())),
            'blocker_counts':dict(sorted(Counter(blocker for r in records for blocker in r['blockers']).items()))}}
    (root/'data/curated/sample-index.json').write_text(json.dumps(output,ensure_ascii=False,sort_keys=True,indent=2)+'\n')
    print(json.dumps(output['summary']))
if __name__=='__main__':main()
