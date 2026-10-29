"""Point-in-time draft history for next-action prediction.

Statistics for a game come only from games on earlier dates (OE date string, compared as text), so same-day
games, including earlier games of the same series, are left out; series state enters through the Fearless
rules and the series features instead. Counts are forward-decayed: a game on day t weighs exp(t / tau), so a
ratio of two sums is already the decayed rate, and a sum times exp(-T / tau) is the decayed count at day T.
"""
from array import array
from bisect import bisect_left
from collections import defaultdict
import datetime
import json
import math
import sqlite3

from .patches import PatchNotes
from .soloq import SoloQueue
from .repository import DB, parse_time

# Team id prefix of a simulated side with no particular team (lolbp/simulate.py): it has no history of its own.
GENERIC_TEAM = 'generic:'
ROLES = ('top', 'jng', 'mid', 'bot', 'sup')
LANE_STATS = ('golddiffat15', 'xpdiffat15', 'csdiffat15')
EPOCH = datetime.datetime(2023, 1, 1)


def day(value):
    """Days since EPOCH for an OE date string ('YYYY-MM-DD' or 'YYYY-MM-DD HH:MM:SS')."""
    return (parse_time(value if len(value) > 10 else value + ' 00:00:00') - EPOCH).total_seconds() / 86400


def other(side):
    return 'Red' if side == 'Blue' else 'Blue'


class History:
    """Per-game draft facts (team ids, lineups, picks by role, bans, result, 15-minute lane differences) indexed by
    date, team, player, patch and champion-in-role.

    Champions are stored as columns into the sorted catalog ids; names outside the catalog are dropped. Lane
    differences are the player's own-perspective value against the opposing player in the same role, or None
    when the source has no 15-minute data (e.g. LPL before 2026) or the game ended earlier.
    """

    def __init__(self, repo):
        self.repo = repo
        self.champions = sorted(repo.champions)
        self.column = {cid: i for i, cid in enumerate(self.champions)}
        connection = sqlite3.connect(repo.root / DB)
        team_ids = {(g, side): team for g, side, team in connection.execute('SELECT gameid, side, team_id FROM team_drafts')}
        lineups, results, lanes = defaultdict(dict), {}, defaultdict(dict)
        for g, side, role, player, name, champion, result, stats in connection.execute(
                'SELECT gameid, side, final_role, player_id, player_name, champion_name_raw, result, stats_json FROM player_games'):
            if g not in repo.games or role not in ROLES: continue
            lineups[(g, side)][role] = (player or name, name, repo.champion_id(champion))
            if result is not None: results[(g, side)] = result
            values = json.loads(stats) if stats else {}
            if all(values.get(k) is not None for k in LANE_STATS): lanes[(g, side)][role] = tuple(values[k] for k in LANE_STATS)
        connection.close()
        self.games = {}
        for gameid, game in repo.games.items():
            if 'simulation' in game: self.add_simulation(game['simulation']); continue
            sides = {}
            for side, team in game['teams'].items():
                lineup = lineups.get((gameid, side), {})
                sides[side] = {'team': team_ids.get((gameid, side)) or team['name'], 'name': team['name'],
                               'players': {r: lineup[r][:2] for r in ROLES if r in lineup},
                               'picks': [(r, self.column[lineup[r][2]]) for r in ROLES if r in lineup and lineup[r][2] in self.column],
                               'bans': [self.column[c] for c in map(repo.champion_id, team['bans']) if c in self.column],
                               'win': results.get((gameid, side)), 'lanes': lanes.get((gameid, side), {})}
            self.games[gameid] = {'gameid': gameid, 'date': game['date'][:10], 't': day(game['date']), 'patch': game['patch'], 'sides': sides}
        self.order = sorted((g for g in self.games.values() if not g.get('simulated')), key=lambda g: (g['t'], g['gameid']))
        self.dates = sorted({g['date'] for g in self.order})
        self.by_team, self.by_player, self.by_patch, self.by_champion = defaultdict(list), defaultdict(list), defaultdict(list), defaultdict(list)
        for g in self.order:
            self.by_patch[g['patch']].append(g)
            for side, own in g['sides'].items():
                self.by_team[own['team']].append((g, own, g['sides'][other(side)]))
                for role, c in own['picks']:
                    self.by_player[(own['players'][role][0], role)].append((g, c)); self.by_champion[(c, role)].append((g, side))
        self._cumulative, self._patch_notes, self._soloq = {}, None, None

    def add_simulation(self, sim):
        """A simulated game (lolbp/simulate.py): teams and lineups only, kept out of every index so it is never history."""
        sides = {side: {'team': t['team'], 'name': t['name'], 'players': {r: tuple(p) for r, p in t['players'].items()},
                        'picks': [], 'bans': [], 'win': None, 'lanes': {}} for side, t in sim['sides'].items()}
        self.games[sim['gameid']] = {'gameid': sim['gameid'], 'date': sim['cutoff'], 't': day(sim['cutoff']), 'patch': sim['patch'],
                                     'sides': sides, 'simulated': True}

    @property
    def soloq(self):
        if self._soloq is None: self._soloq = SoloQueue(self.repo.root)
        return self._soloq

    @property
    def patch_notes(self):
        if self._patch_notes is None: self._patch_notes = PatchNotes(self.repo.root)
        return self._patch_notes

    def cumulative(self, tau):
        """Rows of global forward-decayed sums before each date: [games, picks[n], bans[n], picks by role[5][n]].

        rows[k] covers dates[:k], so bisect_left(dates, cutoff) selects every game before the cutoff date.
        """
        if tau not in self._cumulative:
            n = len(self.champions)
            row, rows, i = array('d', bytes(8 * (1 + n * (2 + len(ROLES))))), [], 0
            for date in self.dates:
                rows.append(array('d', row))
                while i < len(self.order) and self.order[i]['date'] == date:
                    g = self.order[i]; w = math.exp(g['t'] / tau); row[0] += w; i += 1
                    for s in g['sides'].values():
                        for role, c in s['picks']: row[1 + c] += w; row[1 + n * (2 + ROLES.index(role)) + c] += w
                        for c in s['bans']: row[1 + n + c] += w
            rows.append(array('d', row))
            self._cumulative[tau] = rows
        return self._cumulative[tau]

    def lane_averages(self, cutoff, tau, smoothing):
        """[role][column] decayed mean 15-minute gold difference before the cutoff date, shrunk toward 0 by
        `smoothing` pseudo-games; same estimate as the composition panel's champion part."""
        key = ('lane', tau)
        if key not in self._cumulative:
            n, R = len(self.champions), len(ROLES)
            row, rows, i = array('d', bytes(8 * 2 * R * n)), [], 0
            for date in self.dates:
                rows.append(array('d', row))
                while i < len(self.order) and self.order[i]['date'] == date:
                    g = self.order[i]; w = math.exp(g['t'] / tau); i += 1
                    for s in g['sides'].values():
                        for role, c in s['picks']:
                            lane = s['lanes'].get(role)
                            if lane: r = ROLES.index(role); row[r * n + c] += w; row[(R + r) * n + c] += w * lane[0]
            rows.append(array('d', row))
            self._cumulative[key] = rows
        n, R = len(self.champions), len(ROLES)
        row, scale = self._cumulative[key][bisect_left(self.dates, cutoff)], math.exp(-day(cutoff) / tau)
        return [[row[(R + r) * n + c] * scale / (row[r * n + c] * scale + smoothing) for c in range(n)] for r in range(R)]

    def role_prob(self, cutoff, tau):
        """Per champion column, the decayed share of its picks in each role before the cutoff date, with 0.2
        pseudo-picks per role so unseen champions are uniform."""
        n, row = len(self.champions), self.cumulative(tau)[bisect_left(self.dates, cutoff)]
        out = []
        for c in range(n):
            counts = [row[1 + n * (2 + r) + c] * math.exp(-day(cutoff) / tau) for r in range(len(ROLES))]
            out.append([(x + 0.2) / (sum(counts) + 1.0) for x in counts])
        return out

    def team(self, team, cutoff, tau, lineup=None):
        """(forward games, raw games, picks, bans, bans by opponents) for one team before the cutoff date. With a
        `lineup` (set of player ids), each past game also weighs by the share of its players still in that lineup,
        so habits follow the current roster rather than the organisation."""
        games, raw, picks, bans, against = 0.0, 0, defaultdict(float), defaultdict(float), defaultdict(float)
        for g, own, opponent in self.by_team.get(team, ()):
            if g['date'] >= cutoff: break
            w = math.exp(g['t'] / tau); raw += 1
            if lineup is not None: w *= len(lineup & {p for p, _ in own['players'].values()}) / len(ROLES)
            games += w
            for _, c in own['picks']: picks[c] += w
            for c in own['bans']: bans[c] += w
            for c in opponent['bans']: against[c] += w
        return games, raw, picks, bans, against

    def rest_days(self, team, date):
        """Days since the team's last game on an earlier date (None if it has none)."""
        last = None
        for g, _, _ in self.by_team.get(team, ()):
            if g['date'] >= date: break
            last = g
        return None if last is None else day(date) - day(last['date'])

    def player(self, player, role, cutoff, tau):
        """(forward games, raw games, picks) for one player in one role before the cutoff date."""
        games, raw, picks = 0.0, 0, defaultdict(float)
        for g, c in self.by_player.get((player, role), ()):
            if g['date'] >= cutoff: break
            w = math.exp(g['t'] / tau); games += w; raw += 1; picks[c] += w
        return games, raw, picks

    def patch(self, patch, cutoff, tau):
        """(forward games, raw games, picks, bans, picks by role) on one patch before the cutoff date."""
        games, raw, picks, bans, roles = 0.0, 0, defaultdict(float), defaultdict(float), [defaultdict(float) for _ in ROLES]
        for g in self.by_patch.get(patch, ()):
            if g['date'] >= cutoff: break
            w = math.exp(g['t'] / tau); games += w; raw += 1
            for s in g['sides'].values():
                for role, c in s['picks']: picks[c] += w; roles[ROLES.index(role)][c] += w
                for c in s['bans']: bans[c] += w
        return games, raw, picks, bans, roles

    def series_bans(self, gameid):
        """Champion columns banned by each team, and against it, in earlier games of the same series (by team id,
        since map sides change between games)."""
        by, against = defaultdict(set), defaultdict(set)
        for prior in self.repo.series_context(gameid)['prior_gameids']:
            for side, own in self.games[prior]['sides'].items():
                by[own['team']].update(own['bans']); against[own['team']].update(self.games[prior]['sides'][other(side)]['bans'])
        return by, against
