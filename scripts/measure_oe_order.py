#!/usr/bin/env python3
"""Measure how well OE per-team pick/ban columns reproduce per-step draft order.

Reads Leaguepedia per-step evidence (data/curated/bp_sequences.jsonl) for every linked OE game,
checks each sequence against the snake_20 template and OE final sets, interleaves the OE columns
under the evidence's first-selection side, and reports agreement by year and league.
Offline and deterministic.
"""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from assemble_sample import ROOT, digest, read_json, read_jsonl
from validate_bp import check_sequence, oe_hypothesis, order_agreement

SEQUENCES = 'data/curated/bp_sequences.jsonl'
RULES = 'data/curated/rules.json'
CATALOGS = ['data/curated/static/16.20.1/en_US/champion.json', 'data/curated/static/14.16.1/en_US/champion.json']
DB = 'data/processed/lol_bp.sqlite3'
OUTPUT = 'data/curated/oe-order-accuracy.json'
EXAMPLES_PER_GROUP = 5


def load_champions(root):
    seen, champions = set(), []
    for path in CATALOGS:
        for entity in read_json(root / path)['entities']:
            if entity['id'] not in seen: seen.add(entity['id']); champions.append(entity)
    return champions


def load_oe_games(root, gameids):
    connection = sqlite3.connect(root / DB)
    games = {}
    for gameid, league, date, patch, structural in connection.execute(
            'SELECT gameid, league_raw, date_raw, patch_raw, structural_valid FROM games'):
        if gameid in gameids:
            games[gameid] = {'oe_gameid': gameid, 'league_raw': league, 'date_raw': date, 'patch_raw': patch,
                             'quality': {'structural_valid': bool(structural)}, 'teams': []}
    for gameid, side, first, picks, bans in connection.execute(
            'SELECT gameid, side, first_pick_raw, picks_raw_json, bans_raw_json FROM team_drafts ORDER BY gameid, side'):
        if gameid in games:
            games[gameid]['teams'].append({'side': side, 'first_pick_raw': first, 'picks_source_columns': json.loads(picks),
                                           'bans_source_columns': [b or None for b in json.loads(bans)]})
    connection.close()
    return games


def rate(numerator, denominator):
    return None if not denominator else round(numerator / denominator, 4)


def measure(root):
    sequences = read_jsonl(root / SEQUENCES)
    rules = read_json(root / RULES)
    template = next(t for t in rules['templates'] if t['id'] == 'snake_20')
    champions = load_champions(root)
    by_game = defaultdict(list)
    for item in sequences: by_game[item['oe_gameid']].append(item)
    games = load_oe_games(root, set(by_game))
    groups = defaultdict(lambda: {'games': 0, 'evidence_rejected': 0, 'first_pick_side_agree': 0, 'compared': 0,
                                  'all_steps_equal': 0, 'equal_modulo_unordered_groups': 0, 'ban_order_equal': 0,
                                  'pick_order_equal_modulo_groups': 0, 'step_disagreements': Counter(), 'examples': []})
    skipped = Counter()
    for gameid in sorted(by_game):
        if len(by_game[gameid]) != 1: skipped['conflicting_evidence_records'] += 1; continue
        game = games.get(gameid)
        if not game or not game['quality']['structural_valid']: skipped['oe_game_missing_or_invalid'] += 1; continue
        item = by_game[gameid][0]
        group = groups[(game['date_raw'][:4], game['league_raw'])]
        group['games'] += 1
        side_of = {'A': item['first_selection_side'], 'B': 'Red' if item['first_selection_side'] == 'Blue' else 'Blue'}
        if check_sequence(item['steps'], game, template, side_of, champions):
            group['evidence_rejected'] += 1; continue
        first = [t['side'] for t in game['teams'] if t['first_pick_raw'] == '1']
        group['first_pick_side_agree'] += first == [side_of['A']]
        agreement = order_agreement(item['steps'], oe_hypothesis(game, template, side_of), item.get('unordered_step_groups', []))
        group['compared'] += 1
        group['all_steps_equal'] += agreement['all_steps_equal']
        group['equal_modulo_unordered_groups'] += agreement['equal_modulo_unordered_groups']
        bans = [s['step'] for s in template['actions'] if s['action'] == 'ban']
        group['ban_order_equal'] += not set(agreement['differing_steps']) & set(bans)
        group['pick_order_equal_modulo_groups'] += not set(agreement['differing_steps_modulo_groups']) - set(bans)
        group['step_disagreements'].update(agreement['differing_steps_modulo_groups'])
        if agreement['differing_steps_modulo_groups'] and len(group['examples']) < EXAMPLES_PER_GROUP:
            group['examples'].append({'oe_gameid': gameid, 'locator': item['source']['locator'],
                                      'differing_steps_modulo_groups': agreement['differing_steps_modulo_groups']})
    report = []
    for (year, league), g in sorted(groups.items()):
        report.append({'year': year, 'league_raw': league, 'games': g['games'], 'evidence_rejected': g['evidence_rejected'],
                       'compared': g['compared'],
                       'first_pick_side_agree_rate': rate(g['first_pick_side_agree'], g['compared']),
                       'all_steps_equal_rate': rate(g['all_steps_equal'], g['compared']),
                       'equal_modulo_unordered_groups_rate': rate(g['equal_modulo_unordered_groups'], g['compared']),
                       'ban_order_equal_rate': rate(g['ban_order_equal'], g['compared']),
                       'pick_order_equal_modulo_groups_rate': rate(g['pick_order_equal_modulo_groups'], g['compared']),
                       'step_disagreements': {str(k): v for k, v in sorted(g['step_disagreements'].items())},
                       'examples': g['examples']})
    totals = {key: sum(g[key] for g in groups.values()) for key in
              ['games', 'evidence_rejected', 'compared', 'first_pick_side_agree', 'all_steps_equal', 'equal_modulo_unordered_groups']}
    return {'schema_version': 1, 'input_sha256': {p: digest(root / p) for p in [SEQUENCES, RULES] + CATALOGS},
            'evidence_independence_note': 'Leaguepedia tables are community-entered and not proven independent of OE upstreams; VOD spot checks remain advisable.',
            'skipped': dict(sorted(skipped.items())), 'by_year_league': report,
            'overall': {**totals, 'equal_modulo_unordered_groups_rate': rate(totals['equal_modulo_unordered_groups'], totals['compared']),
                        'all_steps_equal_rate': rate(totals['all_steps_equal'], totals['compared']),
                        'first_pick_side_agree_rate': rate(totals['first_pick_side_agree'], totals['compared'])}}


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args()
    report = measure(args.root)
    (args.root / OUTPUT).write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + '\n')
    print(json.dumps(report['overall']))


if __name__ == '__main__': main()
