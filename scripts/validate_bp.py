#!/usr/bin/env python3
"""Offline per-step BP sequence validator.

Checks independent per-step evidence (data/curated/bp_sequences.jsonl) against the applicable
draft template, OE final pick/ban sets, champion identity and observed cross-game rules. OE pick/ban
columns are only interleaved into a labelled hypothesis; they can never verify themselves.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from assemble_sample import ROOT, applicable_rules, choose_asset, digest, load_catalogs, read_json, read_jsonl, resolve_name

INPUTS = ['data/curated/replay_candidates.jsonl', 'data/curated/match_context.jsonl', 'data/curated/rules.json',
          'data/curated/patches.json', 'data/manifests/static-data.json']
SEQUENCES = 'data/curated/bp_sequences.jsonl'
OUTPUT = 'data/curated/bp-validation.json'
# Evidence types that do not derive from the OE columns under test. Shared-upstream pages still need a locator.
INDEPENDENT_SOURCE_TYPES = {'vod_manual', 'official_broadcast', 'leaguepedia_picks_and_bans'}
SIDES = ('Blue', 'Red')


def champion_key(name, champions):
    if name is None: return None
    resolved = resolve_name(name, champions)
    if resolved['champion_id'] is not None: return f"id:{resolved['champion_id']}"
    return 'name:' + ''.join(ch for ch in name.casefold() if ch.isalnum())


def draft_setup(game, context, rules):
    """Return (template, side_of_team, rule_id, blockers) from observed rule fields only."""
    by_id = {r['rule_id']: r for r in rules['rules']}
    usable = []
    for candidate in applicable_rules(game, context, rules):
        rule = by_id[candidate['rule_id']]
        if candidate['applicability_status'] not in ('observed', 'inferred'): continue
        if rule.get('draft_template', {}).get('status') != 'observed': continue
        if rule.get('draft_team_A', {}).get('status') != 'observed': continue
        usable.append(rule)
    if not usable: return None, None, None, ['draft_template_unknown']
    if len({(r['draft_template']['value'], r['draft_team_A']['value']) for r in usable}) > 1:
        return None, None, None, ['conflicting_draft_templates']
    rule = usable[0]
    template = next((t for t in rules['templates'] if t['id'] == rule['draft_template']['value']), None)
    if template is None: return None, None, rule['rule_id'], ['draft_template_missing']
    team_a = rule['draft_team_A']['value']
    if team_a == 'blue': a_side = 'Blue'
    elif team_a == 'first_pick':
        # firstPick is an OE column; independent sequences are cross-checked against it below.
        first = [t['side'] for t in game['teams'] if t.get('first_pick_raw') == '1']
        if len(first) != 1: return template, None, rule['rule_id'], ['first_pick_team_unknown']
        a_side = first[0]
    else: return template, None, rule['rule_id'], ['draft_team_mapping_unknown']
    b_side = SIDES[1 - SIDES.index(a_side)]
    return template, {'A': a_side, 'B': b_side}, rule['rule_id'], []


def oe_hypothesis(game, template, side_of):
    """Interleave per-team OE columns into template order. A labelled hypothesis, never evidence."""
    columns = {t['side']: {'pick': list(t['picks_source_columns']), 'ban': list(t['bans_source_columns'])} for t in game['teams']}
    steps = []
    for action in template['actions']:
        side = side_of[action['draft_team']]
        steps.append({'step': action['step'], 'side': side, 'action': action['action'], 'champion': columns[side][action['action']].pop(0)})
    return steps


def check_sequence(steps, game, template, side_of, champions):
    errors = []
    if len(steps) != len(template['actions']):
        return [{'code': 'step_count_mismatch', 'detail': {'expected': len(template['actions']), 'observed': len(steps)}}]
    for observed, expected in zip(sorted(steps, key=lambda s: s['step']), template['actions']):
        want = {'step': expected['step'], 'side': side_of[expected['draft_team']], 'action': expected['action']}
        got = {k: observed.get(k) for k in want}
        if got != want: errors.append({'code': 'template_mismatch', 'detail': {'expected': want, 'observed': got}})
        if observed.get('action') == 'pick' and observed.get('champion') is None:
            errors.append({'code': 'empty_pick', 'detail': observed['step']})
    keys = [champion_key(s.get('champion'), champions) for s in steps]
    duplicates = sorted(k for k, n in Counter(k for k in keys if k).items() if n > 1)
    if duplicates: errors.append({'code': 'duplicate_champion_in_draft', 'detail': duplicates})
    for team in game['teams']:
        for action, field in (('pick', 'picks_source_columns'), ('ban', 'bans_source_columns')):
            observed = Counter(champion_key(s.get('champion'), champions) for s in steps if s.get('side') == team['side'] and s.get('action') == action)
            final = Counter(champion_key(n, champions) for n in team[field])
            if observed != final:
                errors.append({'code': f'{action}_set_differs_from_oe', 'detail': {'side': team['side']}})
    return errors


def cross_game(game, context, rule, prior_games, champions):
    """Fearless consumption check; only enforced when the rule field is observed and all prior games are present."""
    scope = (rule or {}).get('cross_game_ban_scope', {})
    try: number = int(context.get('game_number'))
    except (TypeError, ValueError): return {'status': 'game_number_unknown'}
    missing = sorted(set(range(1, number)) - {n for n, _ in prior_games})
    consumed = {champion_key(c, champions) for _, g in prior_games for t in g['teams'] for c in t['picks_source_columns']}
    picks = {champion_key(c, champions) for t in game['teams'] for c in t['picks_source_columns']}
    repeats = sorted(picks & consumed)
    if scope.get('status') != 'observed': return {'status': 'rule_unknown', 'observed_pick_repeats': repeats}
    if scope.get('value') != 'picks_by_both_teams_for_remainder_of_match': return {'status': 'unsupported_rule_value', 'value': scope.get('value')}
    if missing: return {'status': 'prior_games_missing', 'missing_game_numbers': missing}
    banned = {champion_key(c, champions) for t in game['teams'] for c in t['bans_source_columns'] if c}
    result = {'status': 'violation' if repeats else 'pass', 'pick_repeats': repeats,
              # Rule: banning a consumed champion forfeits the ban, not a draft error.
              'bans_on_consumed': sorted(banned & consumed),
              'remake_status': 'unknown_not_recorded_in_sources'}
    return result


def order_agreement(evidence_steps, hypothesis_steps):
    if not hypothesis_steps: return None
    by_step = {s['step']: s for s in hypothesis_steps}
    differing = [s['step'] for s in evidence_steps if by_step.get(s['step'], {}).get('champion') != s.get('champion')]
    return {'all_steps_equal': not differing, 'differing_steps': differing}


def validate_game(game, context, rules, champions, prior_games, evidence):
    template, side_of, rule_id, blockers = draft_setup(game, context, rules)
    rule = next((r for r in rules['rules'] if r['rule_id'] == rule_id), None)
    record = {'oe_gameid': game['oe_gameid'], 'rule_id': rule_id, 'draft_sides': side_of,
              'cross_game': cross_game(game, context, rule, prior_games, champions), 'blockers': list(blockers)}
    hypothesis = oe_hypothesis(game, template, side_of) if template and side_of and game.get('quality', {}).get('structural_valid') else None
    record['oe_column_hypothesis'] = None if hypothesis is None else {
        'status': 'hypothesis_unverified', 'errors': check_sequence(hypothesis, game, template, side_of, champions), 'steps': hypothesis}
    if not evidence:
        record['status'] = 'no_independent_sequence'
        record['blockers'].append('independent_sequence_missing')
    elif len(evidence) > 1:
        record['status'] = 'conflicting_evidence_records'
    elif blockers:
        record['status'] = 'blocked'
    else:
        item = evidence[0]; source = item.get('source', {})
        errors = check_sequence(item.get('steps', []), game, template, side_of, champions)
        if source.get('source_type') not in INDEPENDENT_SOURCE_TYPES:
            errors.append({'code': 'source_not_independent', 'detail': source.get('source_type')})
        if not source.get('locator'): errors.append({'code': 'source_locator_missing'})
        if record['cross_game'].get('status') == 'violation': errors.append({'code': 'cross_game_rule_violation'})
        record['evidence'] = {'source': source, 'errors': errors,
                              'oe_column_order_agreement': order_agreement(item.get('steps', []), hypothesis) if not errors else None}
        record['status'] = 'rejected' if errors else 'verified'
    return record


def validate(root):
    for path in INPUTS:
        if not (root / path).is_file(): raise FileNotFoundError(f'required validator input absent: {path}')
    games = sorted(read_jsonl(root / INPUTS[0]), key=lambda g: g['oe_gameid'])
    contexts = {r['oe_gameid']: r for r in read_jsonl(root / INPUTS[1])}
    rules, patches = read_json(root / INPUTS[2]), read_json(root / INPUTS[3])
    catalogs, _ = load_catalogs(root, read_json(root / INPUTS[4]))
    sequences = read_jsonl(root / SEQUENCES) if (root / SEQUENCES).is_file() else []
    unknown = sorted({s['oe_gameid'] for s in sequences} - {g['oe_gameid'] for g in games})
    if unknown: raise ValueError(f'sequence evidence for games outside the sample: {unknown}')
    by_series = {}
    for game in games:
        context = contexts.get(game['oe_gameid'], {})
        if context.get('series_id') and str(context.get('game_number', '')).isdigit():
            by_series.setdefault(context['series_id'], []).append((int(context['game_number']), game))
    records = []
    for game in games:
        context = contexts.get(game['oe_gameid'], {})
        number = int(context['game_number']) if str(context.get('game_number', '')).isdigit() else None
        prior = [(n, g) for n, g in by_series.get(context.get('series_id'), []) if number and n < number]
        version, _ = choose_asset(game['patch_raw'], patches)
        evidence = [s for s in sequences if s['oe_gameid'] == game['oe_gameid']]
        records.append(validate_game(game, context, rules, catalogs.get(version, []), prior, evidence))
    hashed = INPUTS + ([SEQUENCES] if (root / SEQUENCES).is_file() else [])
    return {'schema_version': 1, 'input_sha256': {p: digest(root / p) for p in hashed},
            'independent_source_types': sorted(INDEPENDENT_SOURCE_TYPES), 'records': records,
            'summary': {'games': len(records), 'status_counts': dict(sorted(Counter(r['status'] for r in records).items())),
                        'cross_game_counts': dict(sorted(Counter(r['cross_game']['status'] for r in records).items())),
                        'oe_hypothesis_internal_errors': sum(bool(r['oe_column_hypothesis'] and r['oe_column_hypothesis']['errors']) for r in records)}}


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args()
    output = validate(args.root)
    (args.root / OUTPUT).write_text(json.dumps(output, ensure_ascii=False, sort_keys=True, indent=2) + '\n')
    print(json.dumps(output['summary']))


if __name__ == '__main__': main()
