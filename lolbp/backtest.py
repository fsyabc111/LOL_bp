"""Time-split decisions for training and evaluating next-action models; shared by the train/evaluate scripts.

Games are assigned to a split by their series' first date, so a series never straddles two splits. Games whose
per-step order is disputed (Leaguepedia final sets differ from OE, or the two sources order steps differently
beyond same-team pick pairs) are excluded from training and evaluation alike.
"""
from collections import Counter, defaultdict
import json
import math

from . import draft
from .predict import FEATURES, candidates, probabilities

KS = (1, 3, 5, 10)
PATCH_PROGRESS = ((0, 9), (10, 29), (30, 59), (60, None))  # same-patch games before the decision's game
CALIBRATION_BINS = (0.0, 0.1, 0.2, 0.3, 0.5, 1.0)


def oe_order(repo, gameid, first_side):
    columns = {side: {'pick': list(t['picks']), 'ban': list(t['bans'])} for side, t in repo.games[gameid]['teams'].items()}
    return [repo.champion_id(columns[s.side][s.action].pop(0) or None) for s in draft.slots_from_template(repo.template, first_side)]


def order_disputed(repo, gameid, pair_steps):
    steps, first_side, source = repo.sequence(gameid)
    if source['type'] != 'leaguepedia': return bool(source.get('conflict'))
    ours, oe = [s['champion'] for s in steps], oe_order(repo, gameid, first_side)
    seconds = set(pair_steps.values())
    for step in range(1, len(steps) + 1):
        if step in seconds: continue
        mate = pair_steps.get(step)
        if mate: same = sorted(map(str, (ours[step - 1], ours[mate - 1]))) == sorted(map(str, (oe[step - 1], oe[mate - 1])))
        else: same = ours[step - 1] == oe[step - 1]
        if not same: return True
    return False


def split_games(repo, settings, split, pair_steps):
    """Gameids in a split ordered by date, and the number of disputed games left out."""
    lo, hi = settings['splits'][split]
    chosen, disputed = [], 0
    for series in repo.series.values():
        if series['date'] < lo or (hi and series['date'] > hi): continue
        for gameid in series['gameids']:
            if order_disputed(repo, gameid, pair_steps): disputed += 1
            else: chosen.append(gameid)
    return sorted(chosen, key=lambda g: (repo.games[g]['date'], g)), disputed


def decisions(predictor, gameids, stats, features):
    """One record per recorded step: phase, legal candidates, feature rows, the recorded champion and, for the
    first step of a same-team pick pair, the pair's other champion. Empty bans yield a record without rows."""
    for gameid in gameids:
        steps, _, _ = predictor.repo.sequence(gameid)
        rules, _, _ = predictor.repo.draft_rules(gameid)
        context = predictor.context(gameid, stats)
        actions = ()
        for step in steps:
            slot = draft.next_slot(rules, actions)
            if slot is None or (slot.side, slot.action) != (step['side'], step['action']): break
            record = {'gameid': gameid, 'step': slot.step, 'phase': predictor.phases[slot.step], 'actual': step['champion']}
            if step['champion'] is not None:
                pool = candidates(rules, actions, slot, predictor.history.champions)
                mate = predictor.pairs.get(slot.step)
                record.update(candidates=pool, rows=context.rows(slot.side, actions, pool, features)[0],
                              partner=steps[mate - 1]['champion'] if mate else None)
            yield record
            actions += (draft.Action(slot.step, slot.side, slot.action, step['champion']),)


def outcome(candidates_, probs, actual, partner=None):
    """(rank, probability) of the recorded action, or (None, None) if it was not a legal candidate. For the first
    step of a same-team pair either pick counts, since sources do not fix which of the two came first."""
    order = sorted(range(len(probs)), key=lambda i: (-probs[i], candidates_[i]))
    rank = {i: r + 1 for r, i in enumerate(order)}
    index = {c: i for i, c in enumerate(candidates_)}
    hits = [index[c] for c in (actual, partner) if c is not None and c in index]
    if not hits: return None, None
    return min(rank[i] for i in hits), sum(probs[i] for i in hits)


class Tally:
    def __init__(self):
        self.n = self.missing = self.scored = 0; self.hits = Counter(); self.rr = self.nll = 0.0

    def add(self, rank, prob):
        self.n += 1
        if rank is None: self.missing += 1; return
        for k in KS: self.hits[k] += rank <= k
        self.rr += 1 / rank; self.nll -= math.log(max(prob, 1e-12)); self.scored += 1

    def report(self):
        if not self.n: return {'decisions': 0}
        return {'decisions': self.n, **{f'top{k}': round(self.hits[k] / self.n, 4) for k in KS}, 'mrr': round(self.rr / self.n, 4),
                'log_loss': round(self.nll / self.scored, 4) if self.scored else None, 'actual_not_candidate': self.missing}


def evaluate(predictor, models, gameids):
    """Per model: overall, by phase and by league tallies, top-1 calibration bins and skipped empty bans.

    Features are computed once per distinct statistics setting (the union its models use) and sliced per model."""
    results = {m.version: {'overall': Tally(), 'by_phase': defaultdict(Tally), 'by_league': defaultdict(Tally), 'by_patch_progress': defaultdict(Tally),
                           'calibration': [[0, 0.0, 0] for _ in CALIBRATION_BINS[1:]], 'empty_bans': 0} for m in models}
    groups = defaultdict(list)
    for m in models: groups[json.dumps(m.spec['stats'], sort_keys=True)].append(m)
    for key, group in groups.items():
        features = [f for f in FEATURES if any(f in m.spec['features'] for m in group)]
        for record in decisions(predictor, gameids, json.loads(key), features):
            league = predictor.repo.games[record['gameid']]['league']
            seen = predictor.context(record['gameid'], json.loads(key)).patch_games
            progress = next(f"{lo}-{hi if hi is not None else ''}" for lo, hi in PATCH_PROGRESS if seen >= lo and (hi is None or seen <= hi))
            for m in group:
                result = results[m.version]
                if record['actual'] is None: result['empty_bans'] += 1; continue
                index = [features.index(f) for f in m.spec['features']]
                probs = probabilities(m.weights[record['phase']], m.spec['features'], [[row[i] for i in index] for row in record['rows']])
                rank, prob = outcome(record['candidates'], probs, record['actual'], record['partner'])
                for tally in (result['overall'], result['by_phase'][record['phase']], result['by_league'][league],
                              result['by_patch_progress'][progress]): tally.add(rank, prob)
                top = max(probs, default=0.0)
                b = next(i for i, edge in enumerate(CALIBRATION_BINS[1:]) if top <= edge)
                result['calibration'][b][0] += 1; result['calibration'][b][1] += top; result['calibration'][b][2] += rank == 1
    out = {}
    for version, r in results.items():
        bins = [{'top1_probability': f'{lo:.1f}-{hi:.1f}', 'decisions': n, 'mean_probability': round(s / n, 4), 'hit_rate': round(h / n, 4)}
                for (lo, hi), (n, s, h) in zip(zip(CALIBRATION_BINS, CALIBRATION_BINS[1:]), r['calibration']) if n]
        out[version] = {'overall': r['overall'].report(), 'by_phase': {k: v.report() for k, v in sorted(r['by_phase'].items())},
                        'by_league': {k: v.report() for k, v in sorted(r['by_league'].items())},
                        'by_patch_progress': {k: v.report() for k, v in sorted(r['by_patch_progress'].items(), key=lambda kv: int(kv[0].split('-')[0]))},
                        'calibration_top1': bins,
                        'empty_bans_skipped': r['empty_bans']}
    return out
