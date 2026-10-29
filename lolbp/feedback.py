"""Prediction feedback: cases flagged as wrong, kept as regression checks for later model versions.

A record stores the full draft state (game, Fearless setting, actions before the slot), the model version and
file hash that produced the ranking, the top of what was shown, and an expectation: a champion that should rank
below `expect_rank` (too_high) or within it (too_low), or a free-text case for manual review (other). Records
live in data/feedback/next_action.jsonl, tracked in git so the cases travel with the repository.
"""
import datetime
import json
from pathlib import Path
import threading

from . import draft

DEFAULT_PATH = Path(__file__).resolve().parents[1] / 'data/feedback/next_action.jsonl'
KINDS = ('too_high', 'too_low', 'other')
VERDICT_ZH = {'met': '达标', 'improved': '改善但未达标', 'unchanged': '未变', 'worse': '变差', 'review': '待人工复查', 'unavailable': '无法复现'}


class FeedbackStore:
    def __init__(self, path=DEFAULT_PATH):
        self.path, self._lock = Path(path), threading.Lock()

    def list(self):
        if not self.path.exists(): return []
        return [json.loads(line) for line in self.path.read_text().splitlines() if line.strip()]

    def add(self, record):
        with self._lock:
            record = {'id': max((r['id'] for r in self.list()), default=0) + 1, **record}
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open('a') as f: f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + '\n')
        return record

    def delete(self, feedback_id):
        with self._lock:
            records = self.list(); kept = [r for r in records if r['id'] != feedback_id]
            if len(kept) == len(records): raise KeyError(feedback_id)
            tmp = self.path.with_suffix('.tmp')
            tmp.write_text(''.join(json.dumps(r, ensure_ascii=False, sort_keys=True) + '\n' for r in kept)); tmp.replace(self.path)


def default_expect(kind, rank, top_k):
    """too_high: should fall below max(top_k, current rank); too_low: should reach min(top_k, rank - 1)."""
    if kind == 'too_high': return max(top_k, rank)
    if kind == 'too_low': return max(1, min(top_k, rank - 1))
    return None


def verdict(kind, then, now, expect):
    if kind == 'other': return 'review'
    if now is None: return 'unavailable'
    if kind == 'too_high': met, better, worse = now > expect, now > then, now < then
    else: met, better, worse = now <= expect, now < then, now > then
    return 'met' if met else 'improved' if better else 'worse' if worse else 'unchanged'


def actions_of(record):
    return tuple(draft.Action(a['step'], a['side'], a['action'], a['champion']) for a in record['actions'])


def build(predictor, gameid, actions, fearless_override, model, kind, champion, expect_rank, note, source, branch=None, top_k=5):
    """Record for the ranking shown after `actions`; the champion must be a legal candidate at that slot."""
    if kind not in KINDS: raise ValueError('kind must be too_high, too_low or other')
    ranking = predictor.rank(gameid, actions, model, fearless_override)
    if ranking is None: raise ValueError('BP 已完成，没有可反馈的预测')
    if kind != 'other' and not champion: raise ValueError('“排太高”和“应更靠前”需要指定英雄')
    found = ranking.rank_of(champion) if champion else None
    if champion and found is None: raise ValueError('该英雄此时不是合法候选')
    rank = found and found[0]
    if kind == 'too_low' and rank == 1: raise ValueError('该英雄已排第 1')
    expect = expect_rank or default_expect(kind, rank, top_k)
    if kind == 'too_high' and expect < rank: raise ValueError(f'期望名次应不早于当前的第 {rank} 名')
    if kind == 'too_low' and expect >= rank: raise ValueError(f'期望名次应早于当前的第 {rank} 名')
    return {'created_at': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            'gameid': gameid, 'fearless_override': fearless_override, 'source': source, 'branch': branch,
            'actions': [{'step': a.step, 'side': a.side, 'action': a.action, 'champion': a.champion} for a in actions],
            'slot': {'step': ranking.slot.step, 'side': ranking.slot.side, 'action': ranking.slot.action, 'phase': ranking.phase},
            'model': {'version': model.version, 'sha256': model.sha256}, 'kind': kind, 'champion': champion,
            'rank': rank, 'probability': found and round(found[1], 4), 'expect_rank': expect if kind != 'other' else None,
            'top': [{'champion': c, 'probability': round(p, 4)} for c, p in zip(ranking.champions[:10], ranking.probabilities[:10])],
            'note': (note or '').strip()}


def recheck(predictor, record, model):
    """Re-rank a feedback state with `model`: rank and probability now, the verdict, and the current top 5."""
    base = {'version': model.version,
            'model_file_changed': record['model']['version'] == model.version and record['model']['sha256'] != model.sha256}
    try: ranking = predictor.rank(record['gameid'], actions_of(record), model, record.get('fearless_override'))
    except (KeyError, ValueError): ranking = None
    if ranking is None or (ranking.slot.step, ranking.slot.side) != (record['slot']['step'], record['slot']['side']):
        return {**base, 'verdict': 'unavailable', 'rank': None, 'probability': None, 'top': []}
    found = ranking.rank_of(record['champion']) if record.get('champion') else None
    return {**base, 'rank': found and found[0], 'probability': found and round(found[1], 4),
            'verdict': verdict(record['kind'], record['rank'], found and found[0], record.get('expect_rank')),
            'top': [{'champion': c, 'probability': round(p, 4)} for c, p in zip(ranking.champions[:5], ranking.probabilities[:5])]}
