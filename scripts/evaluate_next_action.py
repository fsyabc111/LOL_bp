#!/usr/bin/env python3
"""Evaluate next-action model versions on a time split and re-check recorded feedback.

Default: every ready version on the validation split. The test split is held out for confirming a final
choice; use it sparingly, since tuning against it makes its numbers optimistic. Reports go to
models/next_action/reports/<version>.<split>.json (deterministic, no timestamps) and a comparison table is
printed, followed by each version's verdicts on the feedback cases in data/feedback/next_action.jsonl.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / 'scripts'))
from assemble_sample import digest  # noqa: E402
from lolbp.backtest import KS, evaluate, split_games  # noqa: E402
from lolbp.feedback import VERDICT_ZH, FeedbackStore, recheck  # noqa: E402
from lolbp.predict import MODELS, Predictor  # noqa: E402
from lolbp.repository import Repository  # noqa: E402

INPUTS = ['data/manifests/local-oe.json', 'data/curated/bp_sequences.jsonl', 'data/curated/rules.json',
          'data/curated/event_restrictions.jsonl', 'data/curated/match_context.jsonl']


def row(name, r):
    if not r.get('decisions'): return f'{name:<18} (no decisions)'
    return f"{name:<18} {r['decisions']:>7} " + ' '.join(f"{r[f'top{k}']:>6.1%}" for k in KS) + f" {r['mrr']:>6.3f} {r['log_loss']:>7.3f}"


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('versions', nargs='*', help='default: every version with weights')
    parser.add_argument('--split', default='validation', choices=['train', 'validation', 'test'])
    args = parser.parse_args()
    repo = Repository(); predictor = Predictor(repo, ROOT / MODELS)
    available = predictor.versions(); settings = predictor.settings()
    names = args.versions or [v for v, m in available.items() if m.ready]
    missing = [v for v in names if v not in available or not available[v].ready]
    if missing: sys.exit(f'没有可用权重的版本：{", ".join(missing)}（先运行 scripts/train_next_action.py）')
    models = [available[v] for v in names]
    if args.split == 'test': print('注意：正在使用保留测试集。只在最终确认时使用；反复对照它调参会让结果偏乐观。\n')
    gameids, disputed = split_games(repo, settings, args.split, predictor.pairs)
    results = evaluate(predictor, models, gameids)
    inputs = {p: digest(ROOT / p) for p in INPUTS if (ROOT / p).exists()}
    (ROOT / MODELS / 'reports').mkdir(parents=True, exist_ok=True)
    for m in models:
        report = {'schema_version': 1, 'version': m.version, 'model_sha256': m.sha256, 'split': args.split,
                  'range': settings['splits'][args.split], 'games': len(gameids), 'disputed_games_excluded': disputed,
                  'group_aware_pairs': {str(a): b for a, b in sorted(predictor.pairs.items())}, **results[m.version],
                  'input_sha256': inputs, 'settings_sha256': digest(ROOT / MODELS / 'settings.json')}
        (ROOT / MODELS / 'reports' / f'{m.version}.{args.split}.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + '\n')
    lo, hi = settings['splits'][args.split]
    print(f"{args.split}: {lo} – {hi or '至今'}，{len(gameids)} 局（另排除 {disputed} 局顺序有争议）")
    print(f"{'version':<18} {'steps':>7} " + ' '.join(f'{"top" + str(k):>6}' for k in KS) + f" {'MRR':>6} {'logloss':>7}")
    for m in models: print(row(m.version, results[m.version]['overall']))
    for m in models:
        print(f'\n{m.version} 按阶段：')
        for phase, r in results[m.version]['by_phase'].items(): print(row('  ' + phase, r))
    cases = FeedbackStore().list()
    if cases:
        print(f'\n反馈回归（{len(cases)} 条，达标标准见各条期望名次）：')
        for m in models:
            checks = [recheck(predictor, case, m) for case in cases]
            counts = Counter(c['verdict'] for c in checks)
            print(f"  {m.version}: " + '，'.join(f'{VERDICT_ZH[v]} {n}' for v, n in counts.most_common()))
            for case, c in zip(cases, checks):
                if c['verdict'] in ('worse', 'unchanged', 'improved'):
                    print(f"    #{case['id']} {case['gameid']} 第 {case['slot']['step']} 步 {case.get('champion')}: "
                          f"当时第 {case['rank']} → 现在第 {c['rank']}（{VERDICT_ZH[c['verdict']]}）")


if __name__ == '__main__': main()
