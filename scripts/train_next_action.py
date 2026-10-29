#!/usr/bin/env python3
"""Fit a next-action model version's per-phase weights on the train split.

Conditional logit over the legal candidates of each recorded step, maximised with Newton steps on standardised
features (L2 from the version's `fit.l2`); weights are stored on the raw feature scale. Needs numpy
(requirements/model.txt); the app and evaluation run on the standard library.

Writes the weights and a training summary into models/next_action/<version>.json. A version that already has
weights is frozen: copy it to a new version to change anything, or pass --force to overwrite deliberately.
"""
import argparse
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / 'scripts'))
from assemble_sample import digest  # noqa: E402
from lolbp.backtest import decisions, split_games  # noqa: E402
from lolbp.predict import MODELS, PHASES, ModelVersion, Predictor, load_settings  # noqa: E402
from lolbp.repository import Repository  # noqa: E402

INPUTS = ['data/manifests/local-oe.json', 'data/curated/bp_sequences.jsonl', 'data/curated/rules.json',
          'data/curated/event_restrictions.jsonl', 'data/curated/match_context.jsonl']


def fit_phase(rows, sizes, chosen, l2, max_iter=50, tol=1e-7):
    """Maximise sum_d log softmax(X_d w)[chosen_d] - l2/2 |w|^2 on standardised columns.

    rows stacks every decision's candidate rows; sizes gives rows per decision; chosen indexes the recorded
    candidate within its decision. Returns (raw-scale weights, mean log-likelihood, iterations)."""
    X = np.asarray(rows, dtype=np.float64)
    mu, sd = X.mean(0), X.std(0); sd[sd < 1e-9] = 1.0
    Z = (X - mu) / sd; del X
    sizes = np.asarray(sizes); starts = np.concatenate([[0], np.cumsum(sizes)[:-1]]); seg = np.repeat(np.arange(len(sizes)), sizes)
    picked = starts + np.asarray(chosen)

    def objective(w):
        s = Z @ w; top = np.maximum.reduceat(s, starts); e = np.exp(s - top[seg]); total = np.add.reduceat(e, starts)
        return (s[picked] - top - np.log(total)).sum() - 0.5 * l2 * w @ w, e / total[seg]
    w = np.zeros(Z.shape[1]); value, p = objective(w)
    for iteration in range(1, max_iter + 1):
        Zp = Z * p[:, None]; expected = np.add.reduceat(Zp, starts)
        grad = Z[picked].sum(0) - expected.sum(0) - l2 * w
        hessian = Zp.T @ Z - expected.T @ expected + l2 * np.eye(len(w))
        step, t = np.linalg.solve(hessian, grad), 1.0
        while True:
            new_value, new_p = objective(w + t * step)
            if new_value >= value or t < 1e-4: break
            t /= 2
        w, value, p = w + t * step, new_value, new_p
        if np.abs(t * step).max() < tol: break
    return w / sd, value / len(sizes), iteration


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('version'); parser.add_argument('--force', action='store_true', help='overwrite existing weights')
    args = parser.parse_args()
    models = ROOT / MODELS
    path = models / f'{args.version}.json'
    spec = json.loads(path.read_text())
    if spec.get('weights') and not args.force:
        sys.exit(f'{args.version} 已有权重，视为冻结版本。要改动请复制为新版本（例如 v2）再训练；确需覆盖请加 --force。')
    if not spec.get('fit'): sys.exit(f'{args.version} 是固定权重版本（fit 为空），不需要训练。')
    settings = load_settings(models); split = spec['fit'].get('split', 'train')
    repo = Repository(); predictor = Predictor(repo, models)
    gameids, disputed = split_games(repo, settings, split, predictor.pairs)
    features = spec['features']
    data = {phase: {'rows': [], 'sizes': [], 'chosen': []} for phase in PHASES}
    skipped = {'empty_ban': 0, 'actual_not_candidate': 0}
    for record in decisions(predictor, gameids, spec['stats'], features):
        if record['actual'] is None: skipped['empty_ban'] += 1; continue
        if record['actual'] not in record['candidates']: skipped['actual_not_candidate'] += 1; continue
        bucket = data[record['phase']]
        bucket['rows'].extend(record['rows']); bucket['sizes'].append(len(record['rows']))
        bucket['chosen'].append(record['candidates'].index(record['actual']))
    weights, summary = {}, {}
    for phase in PHASES:
        bucket = data[phase]
        # macOS Accelerate raises spurious floating-point flags in matmul even on clean input; results are checked below.
        with np.errstate(divide='ignore', over='ignore', invalid='ignore'):
            w, loglik, iterations = fit_phase(bucket['rows'], bucket['sizes'], bucket['chosen'], spec['fit']['l2'])
        if not (np.all(np.isfinite(w)) and np.isfinite(loglik)): sys.exit(f'{phase}: 拟合结果出现非有限值，未写入')
        weights[phase] = {f: round(float(x), 6) for f, x in zip(features, w)}
        summary[phase] = {'decisions': len(bucket['sizes']), 'mean_log_likelihood': round(float(loglik), 4), 'iterations': iterations}
        print(f"{phase}: {len(bucket['sizes'])} decisions, mean log-likelihood {loglik:.4f}, {iterations} Newton steps")
    spec['weights'] = weights
    spec['training'] = {'split': split, 'range': settings['splits'][split], 'games': len(gameids), 'disputed_games_excluded': disputed,
                        'skipped': skipped, 'by_phase': summary, 'input_sha256': {p: digest(ROOT / p) for p in INPUTS if (ROOT / p).exists()},
                        'settings_sha256': digest(models / 'settings.json')}
    path.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + '\n')
    ModelVersion(path)  # validate what was written
    print(f'wrote {path.relative_to(ROOT)}; next: python3 scripts/evaluate_next_action.py')


if __name__ == '__main__': main()
