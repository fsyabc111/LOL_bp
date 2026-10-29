#!/usr/bin/env python3
"""Do the candidate-comparison dimensions separate winners from losers? (shared time split, default validation)

For every game, each dimension is summed over a team's actual picks and the Blue-minus-Red difference is scored
against the result with AUC (0.5 = no information). Statistics use earlier dates only. Dimensions: habit (v1
log-probability of each pick when made), player comfort (log of the player's smoothed share on the champion),
lane strength (15-minute lane averages), no frontline, damage skew. Writes models/recommend/draft-factors.<split>.json.
"""
import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / 'scripts'))
from evaluate_composition import auc  # noqa: E402
from lolbp.backtest import decisions, split_games  # noqa: E402
from lolbp.composition import Composer  # noqa: E402
from lolbp.history import ROLES  # noqa: E402
from lolbp.predict import MODELS, Predictor, load_settings, probabilities  # noqa: E402
from lolbp.repository import Repository  # noqa: E402

LABELS = {'habit': '职业常见度', 'player_comfort': '选手熟练度', 'lane_strength': '对线强度', 'frontline': '有前排', 'damage_balance': '伤害均衡'}


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--split', default='validation', choices=['train', 'validation', 'test'])
    args = parser.parse_args()
    repo = Repository(); predictor = Predictor(repo); composer = Composer(repo, predictor); history = predictor.history
    model = predictor.version('v1'); features = model.spec['features']
    settings = load_settings(ROOT / MODELS)
    gameids, _ = split_games(repo, settings, args.split, predictor.pairs)
    habit = defaultdict(float)
    for record in decisions(predictor, gameids, model.spec['stats'], features):
        if record['actual'] is None or not record['phase'].startswith('pick') or record['actual'] not in record['candidates']: continue
        p = probabilities(model.weights[record['phase']], features, record['rows'])[record['candidates'].index(record['actual'])]
        habit[(record['gameid'], repo.sequence(record['gameid'])[0][record['step'] - 1]['side'])] += math.log(p)
    scored = defaultdict(list)
    for gameid in gameids:
        g = history.games[gameid]; context = predictor.context(gameid, model.spec['stats'])
        if g['sides']['Blue']['win'] is None: continue
        values = {}
        for side in ('Blue', 'Red'):
            picks = dict(g['sides'][side]['picks']); profile = composer.profile(list(picks.values()))
            values[side] = {'habit': habit[(gameid, side)],
                            'player_comfort': sum(math.log(context.sides[side]['players'][ROLES.index(r)]['share'][c]) for r, c in picks.items()),
                            'lane_strength': sum(composer.champion(c, r, g['date'])['lane'] for r, c in picks.items()),
                            'frontline': float(profile['frontline'] > 0), 'damage_balance': -abs(profile['magic_share'] - 0.5)}
        for k in values['Blue']: scored[k].append((values['Blue'][k] - values['Red'][k], g['sides']['Blue']['win']))
    report = {'schema_version': 1, 'split': args.split, 'range': settings['splits'][args.split], 'games': len(gameids), 'model': 'v1',
              'auc': {k: auc(v) for k, v in scored.items()}, 'labels': LABELS}
    out = ROOT / 'models/recommend' / f'draft-factors.{args.split}.json'
    out.parent.mkdir(parents=True, exist_ok=True); out.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + '\n')
    print(f"{args.split}：{len(gameids)} 局；区分胜负的 AUC（0.5 = 无信息）：" + '，'.join(f'{LABELS[k]} {v}' for k, v in report['auc'].items()))


if __name__ == '__main__': main()
