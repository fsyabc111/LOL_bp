"""Point-in-time draft history for next-action prediction.

Statistics for a game come only from games on earlier dates (OE date string, compared as text), so same-day
games, including earlier games of the same series, are left out; series state enters through the Fearless
rules and the series features instead. Counts are forward-decayed: a game on day t weighs exp(t / tau), so a
ratio of two sums is already the decayed rate, and a sum times exp(-T / tau) is the decayed count at day T.
"""
from array import array
from collections import defaultdict
import datetime
import math
import sqlite3

from .repository import DB, parse_time

ROLES = ('top', 'jng', 'mid', 'bot', 'sup')
EPOCH = datetime.datetime(2023, 1, 1)


def day(value):
    """Days since EPOCH for an OE date string ('YYYY-MM-DD' or 'YYYY-MM-DD HH:MM:SS')."""
    return (parse_time(value if len(value) > 10 else value + ' 00:00:00') - EPOCH).total_seconds() / 86400


def other(side):
    return 'Red' if side == 'Blue' else 'Blue'


class History:
    """Per-game draft facts (team ids, lineups, picks by role, bans) indexed by date, team, player and patch.

    Champions are stored as columns into the sorted catalog ids; names outside the catalog are dropped.
    """

    def __init__(self, repo):
        self.repo = repo
        self.champions = sorted(repo.champions)
        self.column = {cid: i for i, cid in enumerate(self.champions)}
        connection = sqlite3.connect(repo.root / DB)
        team_ids = {(g, side): team for g, side, team in connection.execute('SELECT gameid, side, team_id FROM team_drafts')}
        lineups = defaultdict(dict)
        for g, side, role, player, name, champion in connection.execute(
                'SELECT gameid, side, final_role, player_id, player_name, champion_name_raw FROM player_games'):
            if g in repo.games and role in ROLES: lineups[(g, side)][role] = (player or name, name, repo.champion_id(champion))
        connection.close()
        self.games = {}
        for gameid, game in repo.games.items():
            sides = {}
            for side, team in game['teams'].items():
                lineup = lineups.get((gameid, side), {})
                sides[side] = {'team': team_ids.get((gameid, side)) or team['name'], 'name': team['name'],
                               'players': {r: lineup[r][:2] for r in ROLES if r in lineup},
                               'picks': [(r, self.column[lineup[r][2]]) for r in ROLES if r in lineup and lineup[r][2] in self.column],
                               'bans': [self.column[c] for c in map(repo.champion_id, team['bans']) if c in self.column]}
            self.games[gameid] = {'gameid': gameid, 'date': game['date'][:10], 't': day(game['date']), 'patch': game['patch'], 'sides': sides}
        self.order = sorted(self.games.values(), key=lambda g: (g['t'], g['gameid']))
        self.dates = sorted({g['date'] for g in self.order})
        self.by_team, self.by_player, self.by_patch = defaultdict(list), defaultdict(list), defaultdict(list)
        for g in self.order:
            self.by_patch[g['patch']].append(g)
            for side, own in g['sides'].items():
                self.by_team[own['team']].append((g, own, g['sides'][other(side)]))
                for role, c in own['picks']: self.by_player[(own['players'][role][0], role)].append((g, c))
        self._cumulative = {}

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

    def team(self, team, cutoff, tau):
        """(forward games, raw games, picks, bans, bans by opponents) for one team before the cutoff date."""
        games, raw, picks, bans, against = 0.0, 0, defaultdict(float), defaultdict(float), defaultdict(float)
        for g, own, opponent in self.by_team.get(team, ()):
            if g['date'] >= cutoff: break
            w = math.exp(g['t'] / tau); games += w; raw += 1
            for _, c in own['picks']: picks[c] += w
            for c in own['bans']: bans[c] += w
            for c in opponent['bans']: against[c] += w
        return games, raw, picks, bans, against

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
