"""Composition evaluation for a (possibly partial) draft: lane expectations, duo synergy and a coarse profile.

Everything uses games on earlier dates only and weights them by recency (half-life from the settings file).
Three kinds of evidence stay separate in the output:

- Lane: expected 15-minute gold difference in a role, from each champion's average in that role (shrunk to 0)
  plus a shrunk head-to-head residual. Needs OE 15-minute data (LCK, Worlds; LPL only from 2026).
- Duo: same-team pairs (bot+sup, mid+jng, top+jng) whose results beat or trail what the two champions' own win
  rates predict; win-rate residuals are historical observations, not a predicted win probability.
- Profile: damage mix, frontline and range from Riot's coarse Data Dragon descriptors (champion_traits.json).

Roles of a draft in progress are inferred from champions' role history (most probable assignment), never from
the game's final positions. Claims below the sample minimums are reported as insufficient data.
"""
from collections import OrderedDict
import itertools
import json
import math
from pathlib import Path
import threading

from .history import LANE_STATS, ROLES, day, other

SETTINGS = 'models/composition/settings.json'
TRAITS = 'data/curated/champion_traits.json'
DUOS = (('bot', 'sup'), ('mid', 'jng'), ('top', 'jng'))
ROLE_ZH = {'top': '上单', 'jng': '打野', 'mid': '中单', 'bot': '下路', 'sup': '辅助'}
CACHE = 4096


def logit(p):
    return math.log(p / (1 - p))


def sigmoid(x):
    return 1 / (1 + math.exp(-x))


def assign_roles(role_prob, picks):
    """Most probable assignment of picked columns to distinct roles: ([(role, column)], share of probability mass)."""
    if not picks: return [], 1.0
    best, best_w, total = None, -1.0, 0.0
    for roles in itertools.permutations(range(len(ROLES)), len(picks)):
        w = 1.0
        for c, r in zip(picks, roles): w *= role_prob[c][r]
        total += w
        if w > best_w: best, best_w = roles, w
    return sorted(((ROLES[r], c) for c, r in zip(picks, best)), key=lambda x: ROLES.index(x[0])), best_w / total


class Composer:
    """Evaluates draft states for the app and the backtest; aggregates are cached per (cutoff, key)."""

    def __init__(self, repo, history_source, settings_path=None, traits_path=None):
        self.repo, self._source = repo, history_source  # history_source: object with a .history property (Predictor)
        self._paths = (Path(settings_path or repo.root / SETTINGS), Path(traits_path or repo.root / TRAITS))
        self._settings = self._traits = None
        self._cache, self._lock = OrderedDict(), threading.Lock()

    @property
    def settings(self):  # loaded on first use, so the app starts without composition files
        if self._settings is None: self._settings = json.loads(self._paths[0].read_text())
        return self._settings

    @property
    def traits(self):
        if self._traits is None: self._traits = {t['id']: t for t in json.loads(self._paths[1].read_text())['champions']}
        return self._traits

    @property
    def tau(self):
        return self.settings['half_life_days'] / math.log(2)

    @property
    def history(self):
        return self._source.history

    def _cached(self, key, compute):
        with self._lock:
            if key in self._cache: self._cache.move_to_end(key); return self._cache[key]
        value = compute()
        with self._lock:
            self._cache[key] = value
            while len(self._cache) > CACHE: self._cache.popitem(last=False)
        return value

    def _weight(self, g, cutoff):
        return math.exp((g['t'] - day(cutoff)) / self.tau)

    def champion(self, c, role, cutoff):
        """Decayed lane average (shrunk to 0) and win rate (shrunk to 50%) of a champion column in a role."""
        def compute():
            k = self.settings['smoothing']
            w_lane = gold = w_all = wins = 0.0; n_lane = n_all = 0
            for g, side in self.history.by_champion.get((c, role), ()):
                if g['date'] >= cutoff: break
                w = self._weight(g, cutoff); own = g['sides'][side]
                if own['win'] is not None: w_all += w; wins += w * own['win']; n_all += 1
                lane = own['lanes'].get(role)
                if lane: w_lane += w; gold += w * lane[0]; n_lane += 1
            return {'lane': gold / (w_lane + k['champion']), 'win': (wins + 0.5 * k['win']) / (w_all + k['win']),
                    'lane_games': n_lane, 'games': n_all}
        return self._cached(('champion', c, role, cutoff), compute)

    def matchup(self, a, b, role, cutoff):
        """Expected own-perspective 15-minute gold difference of column a against b in a role."""
        def compute():
            base = self.champion(a, role, cutoff)['lane'] - self.champion(b, role, cutoff)['lane']
            w_sum = residual = 0.0; n = n_lane = wins = 0
            for g, side in self.history.by_champion.get((a, role), ()):
                if g['date'] >= cutoff: break
                opponent = g['sides'][other(side)]
                if dict(opponent['picks']).get(role) != b: continue
                n += 1; wins += g['sides'][side]['win'] or 0
                lane = g['sides'][side]['lanes'].get(role)
                if lane: w = self._weight(g, cutoff); w_sum += w; residual += w * (lane[0] - base); n_lane += 1
            adjust = residual / (w_sum + self.settings['smoothing']['matchup'])
            return {'expected': base + adjust, 'champion_part': base, 'matchup_part': adjust, 'games': n, 'lane_games': n_lane, 'wins': wins}
        return self._cached(('matchup', a, b, role, cutoff), compute)

    def duo(self, a, role_a, b, role_b, cutoff):
        """Same-team pair: win-rate and combined-lane residuals against what the two champions predict alone."""
        def compute():
            ca, cb = self.champion(a, role_a, cutoff), self.champion(b, role_b, cutoff)
            p = sigmoid(logit(ca['win']) + logit(cb['win']))
            w_win = win_res = w_lane = lane_res = 0.0; n = n_lane = 0
            for g, side in self.history.by_champion.get((a, role_a), ()):
                if g['date'] >= cutoff: break
                own = g['sides'][side]
                if dict(own['picks']).get(role_b) != b or own['win'] is None: continue
                w = self._weight(g, cutoff); n += 1; w_win += w; win_res += w * (own['win'] - p)
                la, lb = own['lanes'].get(role_a), own['lanes'].get(role_b)
                if la and lb: w_lane += w; lane_res += w * (la[0] + lb[0] - ca['lane'] - cb['lane']); n_lane += 1
            k = self.settings['smoothing']['duo']
            return {'expected_win': p, 'win_delta': win_res / (w_win + k), 'gold_delta': lane_res / (w_lane + k), 'games': n, 'lane_games': n_lane}
        return self._cached(('duo', a, role_a, b, role_b, cutoff), compute)

    def profile(self, columns):
        """Damage mix, frontline and range from coarse static descriptors."""
        traits = [self.traits.get(self.history.champions[c]) for c in columns]
        traits = [t for t in traits if t]
        if not traits: return {'champions': 0}
        magic = [t['info']['magic'] / max(1, t['info']['magic'] + t['info']['attack']) for t in traits]
        return {'champions': len(traits), 'magic_share': round(sum(magic) / len(magic), 3),
                'frontline': sum('Tank' in t['tags'] or t['info']['defense'] >= 7 for t in traits),
                'ranged': sum(t['attack_range'] >= 300 for t in traits),
                'tags': {tag: sum(tag in t['tags'] for t in traits) for tag in ('Tank', 'Fighter', 'Assassin', 'Mage', 'Marksman', 'Support')}}

    def evaluate(self, gameid, actions):
        """Payload for the draft after `actions` (both sides' picks so far)."""
        history, game = self.history, self.history.games[gameid]
        cutoff, column = game['date'], history.column
        role_prob = self._cached(('roles', cutoff), lambda: history.role_prob(cutoff, self.tau))
        minimum, notes = self.settings['min_games'], []
        sides = {}
        for side in ('Blue', 'Red'):
            picks = [column[a.champion] for a in actions if a.side == side and a.action == 'pick' and a.champion in column]
            assignment, confidence = assign_roles(role_prob, picks)
            roles = dict(assignment)
            duos = []
            for ra, rb in DUOS:
                if ra in roles and rb in roles:
                    d = self.duo(roles[ra], ra, roles[rb], rb, cutoff)
                    duos.append({'roles': [ra, rb], 'champions': [history.champions[roles[ra]], history.champions[roles[rb]]],
                                 'win_delta': round(d['win_delta'], 4), 'gold_delta': round(d['gold_delta']), 'games': d['games'],
                                 'lane_games': d['lane_games'], 'enough': d['games'] >= minimum['duo']})
            sides[side] = {'team': game['sides'][side]['name'], 'roles': roles, 'confidence': confidence, 'duos': duos,
                           'profile': self.profile(picks),
                           'assignment': [{'role': r, 'champion': history.champions[c]} for r, c in assignment]}
        lanes = []
        for role in ROLES:
            blue, red = sides['Blue']['roles'].get(role), sides['Red']['roles'].get(role)
            if blue is None or red is None: continue
            m = self.matchup(blue, red, role, cutoff)
            cb, cr = self.champion(blue, role, cutoff), self.champion(red, role, cutoff)
            lanes.append({'role': role, 'blue': history.champions[blue], 'red': history.champions[red], 'expected': round(m['expected']),
                          'champion_part': round(m['champion_part']), 'matchup_part': round(m['matchup_part']),
                          'matchup_games': m['games'], 'matchup_lane_games': m['lane_games'], 'matchup_blue_wins': m['wins'],
                          'blue_lane_games': cb['lane_games'], 'red_lane_games': cr['lane_games'],
                          'enough': min(cb['lane_games'], cr['lane_games']) >= minimum['champion']})
        for side, s in sides.items():
            s['flags'] = self._flags(side, s, lanes)
            if s['assignment'] and s['confidence'] < 0.6:
                notes.append(f"{s['team']} 的分路按英雄历史推断，最可能的分配只占 {s['confidence']:.0%}，摇摆位可能不同")
            del s['roles']
        if game['patch'] and not any(l['blue_lane_games'] or l['red_lane_games'] for l in lanes) and lanes:
            notes.append('这些英雄在本局之前没有带 15 分钟数据的比赛（LPL 2026 年前缺这部分数据），对线期望无法估计')
        total = sum(l['expected'] for l in lanes if l['enough'])
        return {'cutoff': cutoff, 'settings_version': self.settings['version'], 'half_life_days': self.settings['half_life_days'],
                'sides': sides, 'lanes': lanes, 'early_gold_total': round(total) if lanes else None, 'notes': notes,
                'traits_note': '阵容画像来自 Data Dragon 的粗粒度评分与标签，不是实测伤害构成。'}

    def _flags(self, side, s, lanes):
        """Short readable findings with their basis; only claims meeting the thresholds are made. Duo residuals stay out
        of the findings: the backtest found no information about results in them (they are listed, not flagged)."""
        t, out, profile = self.settings['flags'], [], s['profile']
        n = profile.get('champions', 0)
        if n >= 3:
            share = profile['magic_share']
            if share < t['magic_share_low']: out.append({'tone': 'warn', 'kind': 'profile', 'text': f'伤害偏物理（魔法占比约 {share:.0%}），对手堆护甲收益大'})
            if share > 1 - t['magic_share_low']: out.append({'tone': 'warn', 'kind': 'profile', 'text': f'伤害偏魔法（魔法占比约 {share:.0%}），对手堆魔抗收益大'})
        if n >= 4 and profile['frontline'] == 0: out.append({'tone': 'warn', 'kind': 'profile', 'text': '没有前排（无坦克标签或高防御评分的英雄）'})
        sign = 1 if side == 'Blue' else -1
        for lane in lanes:
            value = sign * lane['expected']
            if lane['enough'] and abs(value) >= t['lane_gold']:
                word = '优势' if value > 0 else '劣势'
                basis = f"直接交手 {lane['matchup_lane_games']} 局" if lane['matchup_lane_games'] else '无直接交手，按两边英雄各自的平均'
                out.append({'tone': 'ok' if value > 0 else 'warn', 'kind': 'lane',
                            'text': f"{ROLE_ZH[lane['role']]}对线{word}：15 分钟经济约 {value:+d}（{basis}）"})
        return out
