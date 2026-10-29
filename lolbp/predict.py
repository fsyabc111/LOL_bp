"""Next-action prediction: rank the legal champions for the next draft slot.

A model version is a JSON file in models/next_action/ holding statistics settings, the feature list and
weights per draft phase (fitted by scripts/train_next_action.py, or fixed for baselines). Scores form a
conditional logit over the legal candidates, so probabilities sum to one within each decision. Features come
from history.py (earlier dates only) plus what is known at draft time: lineups, patch, the draft so far and
earlier games of the series.
"""
from bisect import bisect_left
from collections import OrderedDict, defaultdict
import hashlib
import itertools
import json
import math
from pathlib import Path
import threading

from . import draft
from .composition import assign_roles
from .history import ROLES, History, day, other

MODELS = 'models/next_action'
FEATURES = ('meta_pick', 'meta_ban', 'team_pick', 'team_ban', 'opp_pick', 'banned_vs_opp', 'banned_vs_self',
            'role_meta_self', 'player_pool_self', 'role_meta_opp', 'player_pool_opp', 'series_ban_self', 'series_banned_vs_self',
            'lane_edge_self', 'lane_strength_self', 'lane_threat_opp', 'lane_strength_opp', 'patch_buff', 'patch_nerf', 'patch_pro',
            'meta_pick_break', 'meta_ban_break', 'team_pick_break', 'team_ban_break', 'role_meta_self_break', 'player_pool_self_break',
            'role_meta_opp_break', 'player_pool_opp_break', 'soloq_presence', 'soloq_change')
BREAK_DAYS = 14
PHASES = ('ban1', 'pick1', 'ban2', 'pick2')
ROLE_ZH = {'top': '上单', 'jng': '打野', 'mid': '中单', 'bot': '下路', 'sup': '辅助'}
EPS = 1e-6
CONTEXT_CACHE = 64


class ModelError(ValueError):
    pass


class ModelVersion:
    """One versioned model file; its sha256 identifies exactly what produced a prediction."""

    def __init__(self, path):
        raw = Path(path).read_bytes()
        self.path, self.sha256, self.spec = Path(path), hashlib.sha256(raw).hexdigest(), json.loads(raw)
        self.version = self.spec.get('version')
        if self.version != self.path.stem: raise ModelError(f'{path}: version must equal the file name')
        features = self.spec.get('features') or []
        if not features or set(features) - set(FEATURES): raise ModelError(f'{path}: features must be a non-empty subset of {FEATURES}')
        if self.spec['stats']['half_life_days'] < 7: raise ModelError(f'{path}: half_life_days must be at least 7')
        self.weights = self.spec.get('weights') or {}
        for phase, weights in self.weights.items():
            if phase not in PHASES or set(weights) - set(features): raise ModelError(f'{path}: weights must use known phases and listed features')

    @property
    def ready(self):
        return set(self.weights) == set(PHASES)

    def summary(self):
        return {'version': self.version, 'description': self.spec.get('description', ''), 'sha256': self.sha256,
                'kind': 'fitted' if self.spec.get('fit') else 'fixed', 'ready': self.ready}


def load_versions(models_dir):
    paths = sorted(p for p in Path(models_dir).glob('*.json') if p.name != 'settings.json')
    return {v.version: v for v in map(ModelVersion, paths)}


def load_settings(models_dir):
    return json.loads((Path(models_dir) / 'settings.json').read_text())


def phases(template):
    """Step -> phase: consecutive runs of one action type (ban1, pick1, ban2, pick2 for snake_20)."""
    out, runs, previous = {}, defaultdict(int), None
    for a in template['actions']:
        if a['action'] != previous: runs[a['action']] += 1; previous = a['action']
        out[a['step']] = f"{a['action']}{runs[a['action']]}"
    return out


def pairs(template):
    """First step -> second step of same-team consecutive picks; sources do not fix their internal order."""
    acts = template['actions']
    return {a['step']: b['step'] for a, b in zip(acts, acts[1:]) if a['draft_team'] == b['draft_team'] and a['action'] == b['action'] == 'pick'}


def candidates(rules, actions, slot, pool):
    """Legal champions for the slot. A ban on a champion Fearless already consumed is legal but wasted, so it is
    left out of ban candidates too."""
    restricted = draft.availability(rules, actions, pool)
    return [c for c in pool if not (c in restricted and (restricted[c]['reasons'] or slot.action == 'ban'))]


def open_roles(role_prob, picks):
    """Probability that each role is still open: assignments of the picks to distinct roles weighted by each
    champion's role distribution, so a flex pick keeps several roles possible."""
    if not picks: return [1.0] * len(ROLES)
    totals, mass = [0.0] * len(ROLES), 0.0
    for roles in itertools.permutations(range(len(ROLES)), len(picks)):
        w = 1.0
        for c, r in zip(picks, roles): w *= role_prob[c][r]
        mass += w
        for r in range(len(ROLES)):
            if r not in roles: totals[r] += w
    return [t / mass for t in totals]


def probabilities(weights, features, rows):
    w = [weights.get(f, 0.0) for f in features]
    scores = [sum(a * b for a, b in zip(w, row)) for row in rows]
    top = max(scores, default=0.0); exps = [math.exp(s - top) for s in scores]; total = sum(exps)
    return [e / total for e in exps]


def pct(rate):
    return f'{rate:.0%}' if rate >= 0.095 else f'{rate:.1%}'


class Context:
    """Rates as of one game's date for both sides, shared by every decision in that game.

    Each rate is shrunk toward a broader one with the version's pseudo-counts: patch toward recent meta, team
    toward patch meta, player toward the role's patch meta. Unseen therefore means "like the broader rate".
    """

    def __init__(self, history, gameid, stats):
        game = history.games[gameid]
        self.history, self.cutoff, self.patch = history, game['date'], game['patch']
        tau = stats['half_life_days'] / math.log(2); smooth = stats['smoothing']
        scale = math.exp(-day(self.cutoff) / tau)
        n = len(history.champions); every = range(n)
        row = history.cumulative(tau)[bisect_left(history.dates, self.cutoff)]
        games, k = row[0] * scale, smooth['meta']
        recent_pick = [(row[1 + c] * scale + k * 10 / n) / (games + k) for c in every]
        recent_ban = [(row[1 + n + c] * scale + k * 10 / n) / (games + k) for c in every]
        recent_role = [[(row[1 + n * (2 + r) + c] * scale + k / n) / (2 * games + k) for c in every] for r in range(len(ROLES))]
        self.role_prob = history.role_prob(self.cutoff, tau)
        p_games, self.patch_games, p_picks, p_bans, p_roles = history.patch(self.patch, self.cutoff, tau)
        p_games *= scale; k = smooth['patch']; ramp = stats.get('patch_ramp')
        if ramp:
            # Explicit schedule: minor patches change little, so earlier patches carry the estimate until this patch has
            # min_games; its weight then rises linearly to max_weight at full_games.
            a = 0.0 if self.patch_games < ramp['min_games'] else ramp['max_weight'] * min(
                1.0, (self.patch_games - ramp['min_games'] + 1) / max(1, ramp['full_games'] - ramp['min_games'] + 1))
            # The patch's own rate keeps one pseudo-game of the prior, so unseen champions never reach zero.
            blend = lambda count, total, prior: (1 - a) * prior + a * (count * scale + prior) / (total + 1)
            self.meta_pick = [blend(p_picks.get(c, 0.0), p_games, recent_pick[c]) for c in every]
            self.meta_ban = [blend(p_bans.get(c, 0.0), p_games, recent_ban[c]) for c in every]
            self.role_share = [[blend(p_roles[r].get(c, 0.0), 2 * p_games, recent_role[r][c]) for c in every] for r in range(len(ROLES))]
            self.patch_weight = a
        else:
            self.meta_pick = [(p_picks.get(c, 0.0) * scale + k * recent_pick[c]) / (p_games + k) for c in every]
            self.meta_ban = [(p_bans.get(c, 0.0) * scale + k * recent_ban[c]) / (p_games + k) for c in every]
            self.role_share = [[(p_roles[r].get(c, 0.0) * scale + k * recent_role[r][c]) / (2 * p_games + k) for c in every]
                               for r in range(len(ROLES))]
            self.patch_weight = p_games / (p_games + k)
        lane = stats.get('lane')  # 15-minute lane averages, in thousands of gold, when the version uses lane features
        self.lane = lane and [[x / 1000 for x in row] for row in
                              history.lane_averages(self.cutoff, lane['half_life_days'] / math.log(2), lane['smoothing'])]
        notes = stats.get('patch_notes')  # fresh patch-note changes, fading as same-patch games accumulate
        self.fresh, self.fresh_patches = history.patch_notes.fresh(history, gameid) if notes else ({}, [])
        self.freshness = notes['fade_games'] / (notes['fade_games'] + self.patch_games) if notes else 0.0
        self.uses_patch_notes = bool(notes)
        solo = stats.get('soloq')  # KR solo queue: presence on this patch's earlier days and change from the previous patch
        self.soloq_games, self.soloq_presence, self.soloq_change = 0, {}, {}
        if solo:
            name = history.patch_notes.mapping.get(self.patch)
            current, self.soloq_games = history.soloq.presence(name, before=self.cutoff) if name else ({}, 0)
            if self.soloq_games >= solo.get('min_games', 30):
                fade = solo['fade_games'] / (solo['fade_games'] + self.patch_games)
                earlier, _ = history.soloq.presence(history.soloq.previous(name)) if history.soloq.previous(name) else ({}, 0)
                for cid, col in history.column.items():
                    self.soloq_presence[col] = current.get(cid, 0.0)
                    if earlier: self.soloq_change[col] = fade * (current.get(cid, 0.0) - earlier.get(cid, 0.0))
        self.log_meta_pick, self.log_meta_ban = [math.log(x) for x in self.meta_pick], [math.log(x) for x in self.meta_ban]
        by, against = history.series_bans(gameid)
        self.series_status = history.repo.series_context(gameid)['prior_status']
        self.sides = {}
        rests = [history.rest_days(s['team'], self.cutoff) for s in game['sides'].values()]
        self.rest_days = max((r for r in rests if r is not None), default=None)
        self.after_break = float(self.rest_days is not None and self.rest_days >= stats.get('break_days', BREAK_DAYS))
        for side, own in game['sides'].items():
            lineup = {p for p, _ in own['players'].values()} if stats.get('lineup_weighting') else None
            t_games, t_raw, picks, bans, banned = history.team(own['team'], self.cutoff, tau, lineup)
            t_games *= scale; k = smooth['team']
            team = {'name': own['name'], 'games': t_games, 'raw': t_raw,
                    'team_pick': [(picks.get(c, 0.0) * scale + k * self.meta_pick[c] / 2) / (t_games + k) for c in every],
                    'team_ban': [(bans.get(c, 0.0) * scale + k * self.meta_ban[c] / 2) / (t_games + k) for c in every],
                    'banned_vs': [(banned.get(c, 0.0) * scale + k * self.meta_ban[c] / 2) / (t_games + k) for c in every],
                    'series_ban': by.get(own['team'], set()), 'series_banned_vs': against.get(own['team'], set()), 'players': []}
            for key in ('team_pick', 'team_ban', 'banned_vs'): team['log_' + key] = [math.log(x) for x in team[key]]
            for r, role in enumerate(ROLES):
                player, name = own['players'].get(role, (None, None))
                h_games, h_raw, h_picks = history.player(player, role, self.cutoff, tau) if player else (0.0, 0, {})
                h_games *= scale; kp = smooth['player']
                team['players'].append({'name': name, 'games': h_games, 'raw': h_raw,
                                        'share': [(h_picks.get(c, 0.0) * scale + kp * self.role_share[r][c]) / (h_games + kp) for c in every]})
            self.sides[side] = team

    def opens(self, side, actions):
        column = self.history.column
        return open_roles(self.role_prob, [column[a.champion] for a in actions if a.side == side and a.action == 'pick' and a.champion in column])

    def picks(self, side, actions):
        column = self.history.column
        return [column[a.champion] for a in actions if a.side == side and a.action == 'pick' and a.champion in column]

    def lane_terms(self, opens, facing, cols):
        """Per candidate (edge, strength): its expected lane gold against the champions in `facing` (role index -> column)
        and its own lane average, each averaged over the roles it would fill (open roles x its role history)."""
        out = []
        for c in cols:
            weights = [o * p for o, p in zip(opens, self.role_prob[c])]; total = sum(weights)
            if total <= 0: out.append((0.0, 0.0)); continue
            edge = sum(w * (self.lane[r][c] - self.lane[r][facing[r]]) for r, w in enumerate(weights) if r in facing)
            out.append((edge / total, sum(w * self.lane[r][c] for r, w in enumerate(weights)) / total))
        return out

    def rows(self, side, actions, champions, features):
        """Feature rows for each candidate when `side` acts next; also returns both sides' open-role vectors."""
        own, opp = self.sides[side], self.sides[other(side)]
        open_own, open_opp = self.opens(side, actions), self.opens(other(side), actions)
        cols = [self.history.column[c] for c in champions]

        lanes = {}

        def lane(kind, index):  # lazily computed: kind 'self' = our candidate pick, 'opp' = the opponent picking it
            if kind not in lanes:
                opens, facing = (open_own, opp_side) if kind == 'self' else (open_opp, own_side)
                lanes[kind] = self.lane_terms(opens, {ROLES.index(r): c for r, c in assign_roles(self.role_prob, facing)[0]}, cols)
            return [t[index] for t in lanes[kind]]
        own_side, opp_side = self.picks(side, actions), self.picks(other(side), actions)

        def mix(weights, shares):
            terms = [(w, s) for w, s in zip(weights, shares) if w > 1e-9]
            if not terms: return [math.log(EPS)] * len(cols)
            return [math.log(sum(w * s[c] for w, s in terms) + EPS) for c in cols]
        build = {
            'meta_pick': lambda: [self.log_meta_pick[c] for c in cols],
            'meta_ban': lambda: [self.log_meta_ban[c] for c in cols],
            'team_pick': lambda: [own['log_team_pick'][c] for c in cols],
            'team_ban': lambda: [own['log_team_ban'][c] for c in cols],
            'opp_pick': lambda: [opp['log_team_pick'][c] for c in cols],
            'banned_vs_opp': lambda: [opp['log_banned_vs'][c] for c in cols],
            'banned_vs_self': lambda: [own['log_banned_vs'][c] for c in cols],
            'role_meta_self': lambda: mix(open_own, self.role_share),
            'player_pool_self': lambda: mix(open_own, [p['share'] for p in own['players']]),
            'role_meta_opp': lambda: mix(open_opp, self.role_share),
            'player_pool_opp': lambda: mix(open_opp, [p['share'] for p in opp['players']]),
            'series_ban_self': lambda: [1.0 if c in own['series_ban'] else 0.0 for c in cols],
            'series_banned_vs_self': lambda: [1.0 if c in own['series_banned_vs'] else 0.0 for c in cols],
            'lane_edge_self': lambda: lane('self', 0), 'lane_strength_self': lambda: lane('self', 1),
            'lane_threat_opp': lambda: lane('opp', 0), 'lane_strength_opp': lambda: lane('opp', 1),
            'patch_buff': lambda: [self.freshness if self.fresh.get(c, {}).get('net', 0) > 0 else 0.0 for c in cols],
            'patch_nerf': lambda: [self.freshness if self.fresh.get(c, {}).get('net', 0) < 0 else 0.0 for c in cols],
            'patch_pro': lambda: [self.freshness if self.fresh.get(c, {}).get('pro') else 0.0 for c in cols],
            'soloq_presence': lambda: [math.log(self.soloq_presence.get(c, 0.0) + 0.01) for c in cols],
            'soloq_change': lambda: [self.soloq_change.get(c, 0.0) for c in cols]}
        for base in ('meta_pick', 'meta_ban', 'team_pick', 'team_ban', 'role_meta_self', 'player_pool_self', 'role_meta_opp', 'player_pool_opp'):
            # Same values, switched on only after a break, so the model can learn how much to trust each signal then.
            build[base + '_break'] = (lambda b: lambda: [x * self.after_break for x in build[b]()])(base)
        return [list(r) for r in zip(*(build[f]() for f in features))], open_own, open_opp

    def describe(self, feature, side, champion, open_own, open_opp, actions=()):
        """One line of evidence behind a feature for a candidate, with the rate it rests on."""
        c = self.history.column[champion]; own, opp = self.sides[side], self.sides[other(side)]
        if feature in ('meta_pick', 'meta_ban'):
            rate = (self.meta_pick if feature == 'meta_pick' else self.meta_ban)[c]
            basis = f'补丁 {self.patch} 此前 {self.patch_games} 局' if self.patch_games else f'补丁 {self.patch} 此前无职业比赛，沿用近期'
            return f"版本热度：{'pick' if feature == 'meta_pick' else 'ban'} 率约 {pct(rate)}（{basis}）"
        if feature == 'team_pick': return f"{own['name']} 近期约 {pct(own['team_pick'][c])} 的比赛选过它"
        if feature == 'team_ban': return f"{own['name']} 近期约 {pct(own['team_ban'][c])} 的比赛 ban 过它"
        if feature == 'opp_pick': return f"对手 {opp['name']} 近期约 {pct(opp['team_pick'][c])} 的比赛选过它"
        if feature == 'banned_vs_opp': return f"各队对阵 {opp['name']} 时约 {pct(opp['banned_vs'][c])} 的比赛 ban 掉它"
        if feature == 'banned_vs_self': return f"各队对阵 {own['name']} 时约 {pct(own['banned_vs'][c])} 的比赛 ban 掉它"
        if feature in ('role_meta_self', 'role_meta_opp'):
            team, weights = (own, open_own) if feature == 'role_meta_self' else (opp, open_opp)
            r = max(range(len(ROLES)), key=lambda r: weights[r] * self.role_share[r][c])
            who = team['name'] if feature == 'role_meta_self' else f"对手 {team['name']}"
            return f"{who} 还缺{ROLE_ZH[ROLES[r]]}：本补丁该位置约 {pct(self.role_share[r][c])} 的选择是它"
        if feature in ('player_pool_self', 'player_pool_opp'):
            team, weights = (own, open_own) if feature == 'player_pool_self' else (opp, open_opp)
            r = max(range(len(ROLES)), key=lambda r: weights[r] * team['players'][r]['share'][c]); p = team['players'][r]
            who = ('' if feature == 'player_pool_self' else '对手 ') + (p['name'] or '未知选手')
            return f"{who}（{ROLE_ZH[ROLES[r]]}）近期约 {pct(p['share'][c])} 的比赛用它（加权 {p['games']:.1f} 局）"
        if feature in ('lane_edge_self', 'lane_strength_self', 'lane_threat_opp', 'lane_strength_opp'):
            mine = feature.endswith('_self')
            opens, facing = (open_own, self.picks(other(side), actions)) if mine else (open_opp, self.picks(side, actions))
            edge, strength = self.lane_terms(opens, {ROLES.index(r): f for r, f in assign_roles(self.role_prob, facing)[0]}, [c])[0]
            if feature == 'lane_edge_self': return f"对线对面已选英雄：15 分钟经济期望约 {edge * 1000:+.0f}"
            if feature == 'lane_threat_opp': return f"若对手拿到，对线我方已选英雄期望约 {edge * 1000:+.0f}"
            who = '' if mine else '对手使用时'
            return f"{who}对线强势：该位置 15 分钟经济平均约 {strength * 1000:+.0f}"
        if feature in ('patch_buff', 'patch_nerf', 'patch_pro'):
            entry = self.fresh.get(c, {'records': []}); latest = entry['records'][-1] if entry['records'] else {}
            word = {'patch_buff': '加强', 'patch_nerf': '削弱', 'patch_pro': '改动（说明提到职业赛场）'}[feature]
            return f"补丁 {latest.get('patch', '')} {word}：{latest.get('context', '')[:60]}{'…' if len(latest.get('context', '')) > 60 else ''}"
        if feature == 'soloq_presence':
            return f"韩服高分排位本补丁出场率约 {pct(self.soloq_presence.get(c, 0.0))}（{self.soloq_games} 局样本）"
        if feature == 'soloq_change':
            return f"韩服高分排位出场率较上个补丁变化约 {self.soloq_change.get(c, 0.0) * 100:+.0f} 个百分点"
        if feature.endswith('_break'):
            return f"休赛 {self.rest_days:.0f} 天后的调整：" + self.describe(feature.removesuffix('_break'), side, champion, open_own, open_opp, actions)
        if feature == 'series_ban_self': return f"{own['name']} 本系列赛前几局 ban 过它"
        return f"本系列赛前几局对手针对 {own['name']} ban 过它"

    def notes(self, side):
        """Data-sparsity caveats for the acting side and its opponent."""
        out = []
        if self.patch_games < 10: out.append(f'补丁 {self.patch} 在本局之前只有 {self.patch_games} 局职业比赛，版本热度主要参考此前补丁')
        for s in (side, other(side)):
            if self.sides[s]['raw'] < 5: out.append(f"{self.sides[s]['name']} 在本局之前只有 {self.sides[s]['raw']} 局记录，队伍习惯参考价值低")
        sparse = [f"{p['name']}（{ROLE_ZH[r]}）" for s in (side, other(side)) for r, p in zip(ROLES, self.sides[s]['players'])
                  if p['name'] and p['raw'] < 3]
        if sparse: out.append('当前位置历史少于 3 局：' + '、'.join(sparse))
        if self.after_break: out.append(f'距上一场已有 {self.rest_days:.0f} 天（休赛期后），队伍习惯可能已变，回测中这类比赛命中率明显偏低')
        if self.uses_patch_notes and not self.fresh_patches: out.append(f'补丁 {self.patch} 没有可用的补丁说明数据，补丁改动特征不生效')
        if self.series_status != 'complete': out.append('系列赛前序局不全，Fearless 已消耗英雄和系列赛内 ban 可能不全')
        return out


class Ranking:
    """Legal candidates for one slot, most probable first, with the feature rows behind each."""

    def __init__(self, slot, phase, model, context, champions, probs, rows, open_own, open_opp, actions=()):
        self.slot, self.phase, self.model, self.context, self.actions = slot, phase, model, context, actions
        self.champions, self.probabilities, self.rows, self.open_own, self.open_opp = champions, probs, rows, open_own, open_opp
        self.position = {c: i for i, c in enumerate(champions)}
        self._means = None

    def rank_of(self, champion):
        """(1-based rank, probability), or None when the champion is not a legal candidate."""
        i = self.position.get(champion)
        return None if i is None else (i + 1, self.probabilities[i])

    def reasons(self, i, limit=3):
        """Largest positive feature contributions relative to the average candidate, as readable evidence."""
        weights, features = self.model.weights[self.phase], self.model.spec['features']
        if self._means is None: self._means = [sum(col) / len(col) for col in zip(*self.rows)]
        parts = sorted(((weights.get(f, 0.0) * (x - m), f) for f, x, m in zip(features, self.rows[i], self._means)), reverse=True)
        return [{'feature': f, 'contribution': round(v, 3),
                 'text': self.context.describe(f, self.slot.side, self.champions[i], self.open_own, self.open_opp, self.actions)}
                for v, f in parts[:limit] if v > 0.05]


class Predictor:
    """Rankings for replay states and branches; per-game contexts are cached per statistics settings."""

    def __init__(self, repo, models_dir=None):
        self.repo, self.models_dir = repo, Path(models_dir or repo.root / MODELS)
        self.phases, self.pairs = phases(repo.template), pairs(repo.template)
        self._history, self._contexts, self._lock = None, OrderedDict(), threading.Lock()

    @property
    def history(self):
        with self._lock:
            if self._history is None: self._history = History(self.repo)
        return self._history

    def settings(self):
        return load_settings(self.models_dir)

    def versions(self):
        return load_versions(self.models_dir)

    def version(self, name=None):
        versions = self.versions()
        name = name or self.settings().get('default')
        if name not in versions: raise ModelError(f'unknown model version {name}')
        if not versions[name].ready: raise ModelError(f'model version {name} has no weights yet; run scripts/train_next_action.py {name}')
        return versions[name]

    def context(self, gameid, stats):
        key = (gameid, json.dumps(stats, sort_keys=True))
        with self._lock:
            if key in self._contexts: self._contexts.move_to_end(key); return self._contexts[key]
        context = Context(self.history, gameid, stats)
        with self._lock:
            self._contexts[key] = context
            while len(self._contexts) > CONTEXT_CACHE: self._contexts.popitem(last=False)
        return context

    def rank(self, gameid, actions, model, fearless_override=None):
        """Ranking for the slot after `actions`, or None when the draft is complete."""
        rules, _, _ = self.repo.draft_rules(gameid, fearless_override)
        slot = draft.next_slot(rules, actions)
        if slot is None: return None
        context = self.context(gameid, model.spec['stats'])
        pool = candidates(rules, actions, slot, self.history.champions)
        features = model.spec['features']; phase = self.phases[slot.step]
        rows, open_own, open_opp = context.rows(slot.side, actions, pool, features)
        probs = probabilities(model.weights[phase], features, rows)
        order = sorted(range(len(pool)), key=lambda i: (-probs[i], pool[i]))
        return Ranking(slot, phase, model, context, [pool[i] for i in order], [probs[i] for i in order],
                       [rows[i] for i in order], open_own, open_opp, actions)

    def rank_as(self, gameid, actions, model, side, action, fearless_override=None):
        """Ranking for a hypothetical `side` taking `action` now (e.g. what the opponent would pick if it were their
        turn), weighted with the phase of that side's next real slot of this action."""
        rules, _, _ = self.repo.draft_rules(gameid, fearless_override)
        current = draft.next_slot(rules, actions)
        if current is None: return None
        later = [s for s in rules.slots[len(actions):] if s.side == side and s.action == action]
        if not later: return None
        slot = draft.Slot(current.step, side, action); phase = self.phases[later[0].step]
        context = self.context(gameid, model.spec['stats']); features = model.spec['features']
        pool = candidates(rules, actions, slot, self.history.champions)
        rows, open_own, open_opp = context.rows(side, actions, pool, features)
        probs = probabilities(model.weights[phase], features, rows)
        order = sorted(range(len(pool)), key=lambda i: (-probs[i], pool[i]))
        return Ranking(slot, phase, model, context, [pool[i] for i in order], [probs[i] for i in order],
                       [rows[i] for i in order], open_own, open_opp, actions)

    def reliability(self, model, phase):
        """Validation hit rates for this version and phase, if a current report exists."""
        path = self.models_dir / 'reports' / f'{model.version}.validation.json'
        if not path.exists(): return None
        report = json.loads(path.read_text())
        if report.get('model_sha256') != model.sha256: return {'stale': True}
        group = report['by_phase'].get(phase)
        return group and {'split': 'validation', **{k: group[k] for k in ('decisions', 'top1', 'top3', 'top5', 'top10')}}

    def predict(self, gameid, actions, fearless_override=None, version=None, top=10, actual=None):
        """API payload for the next slot. `actual` maps step -> recorded champion for replay comparison."""
        model = self.version(version)
        ranking = self.rank(gameid, actions, model, fearless_override)
        if ranking is None: return None
        game, slot = self.history.games[gameid], ranking.slot
        listed = [{'champion': c, 'rank': i + 1, 'probability': round(p, 4), 'reasons': ranking.reasons(i)}
                  for i, (c, p) in enumerate(zip(ranking.champions[:top], ranking.probabilities[:top]))]

        def recorded(step):
            champion = (actual or {}).get(step)
            if champion is None: return None
            found = ranking.rank_of(champion)
            return {'step': step, 'champion': champion, 'rank': found and found[0], 'probability': found and round(found[1], 4)}
        partner = self.pairs.get(slot.step)
        return {'model': model.summary(), 'slot': {'step': slot.step, 'side': slot.side, 'action': slot.action, 'phase': ranking.phase,
                                                   'team': game['sides'][slot.side]['name'], 'opponent': game['sides'][other(slot.side)]['name']},
                'cutoff': ranking.context.cutoff, 'patch': ranking.context.patch, 'candidate_count': len(ranking.champions),
                'candidates': listed, 'actual': recorded(slot.step), 'paired_actual': recorded(partner) if partner else None,
                'reliability': self.reliability(model, ranking.phase), 'notes': ranking.context.notes(slot.side)}
