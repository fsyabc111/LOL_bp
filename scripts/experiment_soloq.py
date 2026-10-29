#!/usr/bin/env python3
"""Does KR solo queue add to v1? Fit only the solo queue weights on top of frozen v1 scores, then test later.

KR solo queue history is only reachable for 2026, so the regular train split (mostly 2025) cannot be used. Inside
the validation period, v1's score is a fixed offset and per-phase weights for soloq_presence and soloq_change are
fitted on April-May 2026 (series start dates), then v1 and v1 + solo queue are compared on June-July 2026.
Needs numpy. Writes models/next_action/reports/soloq-experiment.json (deterministic). With --write v7 it also freezes
v1 plus the fitted solo queue weights as models/next_action/v7.json.
"""
import argparse
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / 'scripts'))
from lolbp.backtest import KS, decisions, outcome, split_games  # noqa: E402
from lolbp.predict import MODELS, PHASES, Predictor, load_settings, probabilities  # noqa: E402
from lolbp.repository import Repository  # noqa: E402

EXTRA = ['soloq_presence', 'soloq_change']
FIT, TEST = ('2026-04-01', '2026-05-31'), ('2026-06-01', '2026-07-31')
SOLOQ = {'fade_games': 20, 'min_games': 30}


def fit_offset(base, extra, sizes, chosen, l2=1.0, iterations=50):
    """Conditional logit with a fixed per-row offset (the base model's score); returns raw-scale weights."""
    X = np.asarray(extra, dtype=float); mu, sd = X.mean(0), X.std(0); sd[sd < 1e-9] = 1.0; Z = (X - mu) / sd
    off = np.asarray(base, dtype=float); sizes = np.asarray(sizes)
    starts = np.concatenate([[0], np.cumsum(sizes)[:-1]]); seg = np.repeat(np.arange(len(sizes)), sizes); picked = starts + np.asarray(chosen)

    def objective(w):
        s = off + Z @ w; top = np.maximum.reduceat(s, starts); e = np.exp(s - top[seg]); total = np.add.reduceat(e, starts)
        return (s[picked] - top - np.log(total)).sum() - 0.5 * l2 * w @ w, e / total[seg]
    w = np.zeros(Z.shape[1]); value, p = objective(w)
    for _ in range(iterations):
        Zp = Z * p[:, None]; expected = np.add.reduceat(Zp, starts)
        grad = Z[picked].sum(0) - expected.sum(0) - l2 * w
        step = np.linalg.solve(Zp.T @ Z - expected.T @ expected + l2 * np.eye(len(w)), grad); t = 1.0
        while True:
            new, new_p = objective(w + t * step)
            if new >= value or t < 1e-4: break
            t /= 2
        w, value, p = w + t * step, new, new_p
        if np.abs(t * step).max() < 1e-7: break
    return w / sd


def collect(predictor, model, window):
    settings = {'splits': {'x': list(window)}}
    gameids, _ = split_games(predictor.repo, settings, 'x', predictor.pairs)
    stats = {**model.spec['stats'], 'soloq': SOLOQ}
    features = model.spec['features'] + EXTRA
    out = []
    for r in decisions(predictor, gameids, stats, features):
        if r['actual'] is None: continue
        base_rows = [row[:len(model.spec['features'])] for row in r['rows']]
        weights = model.weights[r['phase']]
        base = [sum(weights.get(f, 0.0) * x for f, x in zip(model.spec['features'], row)) for row in base_rows]
        context = predictor.context(r['gameid'], stats)
        out.append({**r, 'base': base, 'extra': [row[len(model.spec['features']):] for row in r['rows']],
                    'signal': bool(context.soloq_presence), 'progress': context.patch_games, 'after_break': context.after_break})
    return gameids, out


def scores(records, weights=None):
    tally = {}
    for r in records:
        s = np.asarray(r['base']) + (np.asarray(r['extra']) @ weights[r['phase']] if weights is not None else 0)
        probs = list(np.exp(s - s.max()) / np.exp(s - s.max()).sum())
        rank, prob = outcome(r['candidates'], probs, r['actual'], r['partner'])
        for key in ('all', 'with_soloq_signal' if r['signal'] else 'without_signal', 'patch_0-9' if r['progress'] < 10 else 'patch_10+',
                    'after_break' if r['after_break'] else 'regular'):
            t = tally.setdefault(key, {'n': 0, 'hits': {k: 0 for k in KS}, 'nll': 0.0, 'scored': 0})
            t['n'] += 1
            if rank is None: continue
            for k in KS: t['hits'][k] += rank <= k
            t['nll'] -= np.log(max(prob, 1e-12)); t['scored'] += 1
    return {k: {'decisions': t['n'], **{f'top{k2}': round(t['hits'][k2] / t['n'], 4) for k2 in KS},
                'log_loss': round(t['nll'] / t['scored'], 4)} for k, t in sorted(tally.items())}


def freeze(model, weights, name, fit_games):
    spec = json.loads(model.path.read_text()); spec.pop('training', None)  # v1's own training record stays in v1.json
    spec.update({'version': name, 'description': 'v1 加韩服高分排位：本补丁排位出场率、相对上补丁的变化（随本补丁职业局数淡出）',
                 'stats': {**spec['stats'], 'soloq': SOLOQ}, 'features': spec['features'] + EXTRA,
                 'fit': {'method': 'conditional_logit_newton_offset', 'l2': 1.0, 'base': model.version, 'base_sha256': model.sha256,
                         'range': list(FIT), 'games': fit_games, 'script': 'scripts/experiment_soloq.py'},
                 'weights': {p: {**spec['weights'][p], **{f: round(float(x), 6) for f, x in zip(EXTRA, weights[p])}} for p in PHASES}})
    (ROOT / MODELS / f'{name}.json').write_text(json.dumps(spec, ensure_ascii=False, indent=2, sort_keys=True) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--write', metavar='VERSION', help='freeze v1 + the fitted weights under this version name')
    args = parser.parse_args()
    repo = Repository(); predictor = Predictor(repo, ROOT / MODELS); model = predictor.version('v1')
    fit_games, fit_records = collect(predictor, model, FIT)
    test_games, test_records = collect(predictor, model, TEST)
    weights, summary = {}, {}
    for phase in PHASES:
        rows = [r for r in fit_records if r['phase'] == phase and r['actual'] in r['candidates']]
        with np.errstate(all='ignore'):
            w = fit_offset([x for r in rows for x in r['base']], [x for r in rows for x in r['extra']],
                           [len(r['candidates']) for r in rows], [r['candidates'].index(r['actual']) for r in rows])
        weights[phase] = w; summary[phase] = {f: round(float(x), 4) for f, x in zip(EXTRA, w)}
    report = {'schema_version': 1, 'base': 'v1', 'base_sha256': model.sha256, 'extra_features': EXTRA, 'soloq_settings': SOLOQ,
              'fit_window': FIT, 'test_window': TEST, 'fit_games': len(fit_games), 'test_games': len(test_games),
              'fitted_weights': summary, 'soloq_patches': predictor.history.soloq.order,
              'test': {'v1': scores(test_records), 'v1+soloq': scores(test_records, weights)},
              'fit_in_sample': {'v1': scores(fit_records), 'v1+soloq': scores(fit_records, weights)}}
    if args.write: freeze(model, weights, args.write, len(fit_games))
    path = ROOT / MODELS / 'reports/soloq-experiment.json'
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + '\n')
    print('weights', json.dumps(summary))
    for part in ('test', 'fit_in_sample'):
        print(part)
        for key in report[part]['v1']:
            a, b = report[part]['v1'][key], report[part]['v1+soloq'][key]
            print(f"  {key:<18} n={a['decisions']:<6} top1 {a['top1']:.3f}->{b['top1']:.3f}  top5 {a['top5']:.3f}->{b['top5']:.3f}  "
                  f"logloss {a['log_loss']:.3f}->{b['log_loss']:.3f}")


if __name__ == '__main__': main()
