#!/usr/bin/env python3
"""Backtest composition evidence on the next-action time split (default: validation).

Lane: for every role of every game with 15-minute data, compare the Blue-perspective gold difference predicted by
(a) zero, (b) the two champions' role averages and (c) averages plus the head-to-head residual, using the
game's recorded roles so the estimator itself is tested. Team: does the summed lane expectation, and the duo
win-rate residuals, separate winners from losers (AUC; 0.5 = no information)? The AUC of the actual 15-minute gold
difference is reported as a reference for how much any early-game signal could carry. Statistics use earlier dates only.
Writes models/composition/reports/<version>.<split>.json (deterministic) and prints a summary.
"""
import argparse
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / 'scripts'))
from assemble_sample import digest  # noqa: E402
from lolbp.backtest import split_games  # noqa: E402
from lolbp.composition import DUOS, SETTINGS, Composer  # noqa: E402
from lolbp.history import ROLES  # noqa: E402
from lolbp.predict import MODELS, Predictor, load_settings  # noqa: E402
from lolbp.repository import Repository  # noqa: E402


def errors(pairs):
    n = len(pairs)
    if not n: return {'n': 0}
    mae = sum(abs(p - a) for p, a in pairs) / n; rmse = math.sqrt(sum((p - a) ** 2 for p, a in pairs) / n)
    mp, ma = sum(p for p, _ in pairs) / n, sum(a for _, a in pairs) / n
    cov = sum((p - mp) * (a - ma) for p, a in pairs); vp = sum((p - mp) ** 2 for p, _ in pairs); va = sum((a - ma) ** 2 for _, a in pairs)
    return {'n': n, 'mae': round(mae, 1), 'rmse': round(rmse, 1), 'pearson_r': round(cov / math.sqrt(vp * va), 4) if vp and va else None}


def auc(scored):
    """Probability that a random winner scores above a random loser (ties count half)."""
    wins = [s for s, y in scored if y == 1]; losses = [s for s, y in scored if y == 0]
    if not wins or not losses: return None
    ranked = sorted((s, y) for s, y in scored)
    rank_sum, i = 0.0, 0
    while i < len(ranked):
        j = i
        while j < len(ranked) and ranked[j][0] == ranked[i][0]: j += 1
        rank_sum += sum(1 for k in range(i, j) if ranked[k][1] == 1) * (i + j + 1) / 2; i = j
    return round((rank_sum - len(wins) * (len(wins) + 1) / 2) / (len(wins) * len(losses)), 4)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--split', default='validation', choices=['train', 'validation', 'test'])
    args = parser.parse_args()
    repo = Repository(); predictor = Predictor(repo); composer = Composer(repo, predictor)
    settings = load_settings(ROOT / MODELS)
    gameids, disputed = split_games(repo, settings, args.split, predictor.pairs)
    lanes = {'zero': [], 'champion': [], 'matchup': []}; by_role = {r: [] for r in ROLES}
    team_gold, team_duo, team_actual, reference = [], [], [], []
    for gameid in gameids:
        g = predictor.history.games[gameid]; blue, red = g['sides']['Blue'], g['sides']['Red']
        if blue['win'] is None: continue
        b_roles, r_roles = dict(blue['picks']), dict(red['picks'])
        expected_total, actual_total, complete = 0.0, 0.0, True
        for role in ROLES:
            if role not in b_roles or role not in r_roles: complete = False; continue
            m = composer.matchup(b_roles[role], r_roles[role], role, g['date'])
            lane = blue['lanes'].get(role)
            expected_total += m['expected']
            if lane is None: complete = False; continue
            actual_total += lane[0]
            lanes['zero'].append((0.0, lane[0])); lanes['champion'].append((m['champion_part'], lane[0]))
            lanes['matchup'].append((m['expected'], lane[0])); by_role[role].append((m['expected'], lane[0]))
        if complete: team_actual.append((expected_total, actual_total)); reference.append((actual_total, blue['win']))
        team_gold.append((expected_total, blue['win']))
        duo = 0.0
        for side, sign in ((blue, 1), (red, -1)):
            roles = dict(side['picks'])
            for ra, rb in DUOS:
                if ra in roles and rb in roles: duo += sign * composer.duo(roles[ra], ra, roles[rb], rb, g['date'])['win_delta']
        team_duo.append((duo, blue['win']))
    report = {'schema_version': 1, 'version': composer.settings['version'], 'split': args.split, 'range': settings['splits'][args.split],
              'games': len(gameids), 'disputed_games_excluded': disputed,
              'lane_gold15': {k: errors(v) for k, v in lanes.items()}, 'lane_gold15_by_role': {r: errors(v) for r, v in by_role.items()},
              'team_gold15_sum': errors(team_actual),
              'win_auc': {'early_gold_expectation': auc(team_gold), 'duo_win_residuals': auc(team_duo),
                          'combined_rank_sum': auc([(a[0] / 1000 + b[0] * 10, a[1]) for a, b in zip(team_gold, team_duo)]),
                          'reference_actual_gold15': auc(reference)},
              'settings_sha256': digest(ROOT / SETTINGS), 'traits_sha256': digest(ROOT / 'data/curated/champion_traits.json')}
    out = ROOT / 'models/composition/reports' / f"{report['version']}.{args.split}.json"
    out.parent.mkdir(parents=True, exist_ok=True); out.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + '\n')
    lo, hi = settings['splits'][args.split]
    print(f"{args.split}: {lo} – {hi or '至今'}，{len(gameids)} 局")
    print('对线 15 分钟经济差（蓝方视角）：')
    for k, label in (('zero', '恒为 0'), ('champion', '英雄位置均值'), ('matchup', '均值 + 直接交手修正')):
        e = report['lane_gold15'][k]; print(f"  {label:<14} n={e['n']}  MAE {e['mae']}  RMSE {e['rmse']}  r={e['pearson_r']}")
    print('  按位置 r：' + '，'.join(f"{r} {report['lane_gold15_by_role'][r]['pearson_r']}" for r in ROLES))
    t = report['team_gold15_sum']; print(f"全队 15 分钟经济合计：n={t['n']}  MAE {t['mae']}  r={t['pearson_r']}")
    print('区分胜负的 AUC（0.5 = 无信息）：' + '，'.join(f'{k} {v}' for k, v in report['win_auc'].items()))
    print(f'wrote {out.relative_to(ROOT)}')


if __name__ == '__main__': main()
