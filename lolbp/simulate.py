"""Simulated drafts: a chosen patch and two teams, with no recorded game behind them.

A simulation is a virtual game 'sim-<id>' dated the day after the patch's last professional game in the dataset, so
every game on that patch is history for it, with each team's lineup from its last game before that date. It is
registered in the Repository and the prediction History, so draft state, predictions, composition and candidate
comparison work unchanged; the draft itself is a branch forked at step 0. Rules (template, event-disabled list) are
those of the patch's last game in the blue team's league; there is no series, so no Fearless carry-over.
Either side may be left without a team ('generic'): it then has no team or player history, so predictions for it
rest on league-wide habits (patch popularity, role distribution). With a generic blue side, the rules come from a
chosen league (else the red team's, else the league with most games on the patch).
Simulations are stored next to the branches (data/app/branches.sqlite3) and never touch source data.
"""
import contextlib
import datetime
import json
from pathlib import Path
import sqlite3

from .history import GENERIC_TEAM, ROLES, day
from .branches import DEFAULT_PATH

PREFIX = 'sim-'


def patch_key(patch):
    return tuple(int(x) if x.isdigit() else 0 for x in patch.split('.'))


class SimulationNotFound(KeyError):
    pass


def patches(history):
    """Patches with professional games, newest first: games, first and last date."""
    out = [{'patch': p, 'games': len(games), 'first': games[0]['date'], 'last': games[-1]['date']}
           for p, games in history.by_patch.items() if games]
    return sorted(out, key=lambda r: patch_key(r['patch']), reverse=True)


def cutoff_of(history, patch):
    games = history.by_patch.get(patch)
    if not games: raise ValueError(f'no professional games on patch {patch}')
    return (datetime.date.fromisoformat(games[-1]['date']) + datetime.timedelta(days=1)).isoformat()


def teams(history, patch, window_days=180):
    """Teams that played in the `window_days` before the patch's cutoff, those on the patch first, each with its lineup
    and league from its last game before the cutoff."""
    cutoff = cutoff_of(history, patch)
    on_patch = {}
    for g in history.by_patch[patch]:
        for own in g['sides'].values(): on_patch[own['team']] = on_patch.get(own['team'], 0) + 1
    out = []
    for team, games in history.by_team.items():
        before = [x for x in games if x[0]['date'] < cutoff]
        if not before or day(cutoff) - before[-1][0]['t'] > window_days: continue
        g, own, _ = before[-1]
        out.append({'team': team, 'name': own['name'], 'league': history.repo.games[g['gameid']]['league'], 'last_date': g['date'],
                    'games_on_patch': on_patch.get(team, 0), 'players': {r: list(own['players'][r]) for r in ROLES if r in own['players']}})
    return cutoff, sorted(out, key=lambda t: (-bool(t['games_on_patch']), t['league'], t['name'].casefold()))


def leagues(history, patch):
    """Leagues with games on the patch, most games first."""
    counts = {}
    for g in history.by_patch.get(patch, ()):
        league = history.repo.games[g['gameid']]['league']; counts[league] = counts.get(league, 0) + 1
    return [{'league': l, 'games': n} for l, n in sorted(counts.items(), key=lambda x: (-x[1], x[0]))]


def generic_side(side, league):
    return {'team': GENERIC_TEAM + side, 'name': '蓝方' if side == 'Blue' else '红方', 'league': league, 'players': {}, 'generic': True}


def reference_game(history, patch, league):
    """Last game on the patch in this league (else on the patch at all), whose rules the simulation borrows."""
    games = history.by_patch[patch]
    same = [g for g in games if history.repo.games[g['gameid']]['league'] == league]
    return (same or games)[-1]['gameid']


def build_spec(history, patch, blue, red, league=''):
    """An empty team id leaves that side generic; `league` picks the rules when the blue side is generic."""
    if blue and blue == red: raise ValueError('two different teams are required')
    cutoff, options = teams(history, patch)
    by_team = {t['team']: t for t in options}
    missing = [t for t in (blue, red) if t and t not in by_team]
    if missing: raise ValueError(f'unknown or inactive team for patch {patch}: {", ".join(missing)}')
    named = {side: by_team[t] for side, t in (('Blue', blue), ('Red', red)) if t}
    played = [l['league'] for l in leagues(history, patch)]
    if league and league not in played: raise ValueError(f'no games in league {league} on patch {patch}')
    rules = named['Blue']['league'] if 'Blue' in named else league or named.get('Red', {}).get('league') or played[0]
    sides = {side: {k: named[side][k] for k in ('team', 'name', 'league', 'players')} if side in named else generic_side(side, rules)
             for side in ('Blue', 'Red')}
    return {'patch': patch, 'cutoff': cutoff, 'reference': reference_game(history, patch, rules), 'sides': sides}


class SimulationStore:
    def __init__(self, path=DEFAULT_PATH):
        self.path = Path(path); self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as c:
            c.execute('CREATE TABLE IF NOT EXISTS simulations (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, '
                      'created_at TEXT NOT NULL, spec_json TEXT NOT NULL)')

    @contextlib.contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path); connection.row_factory = sqlite3.Row
        try:
            with connection: yield connection
        finally: connection.close()

    @staticmethod
    def _record(row):
        return {'id': row['id'], 'gameid': PREFIX + str(row['id']), 'name': row['name'], 'created_at': row['created_at'],
                **json.loads(row['spec_json'])}

    def list(self):
        with self._connect() as c: return [self._record(r) for r in c.execute('SELECT * FROM simulations ORDER BY id DESC')]

    def get(self, sim_id):
        with self._connect() as c: row = c.execute('SELECT * FROM simulations WHERE id = ?', (sim_id,)).fetchone()
        if row is None: raise SimulationNotFound(sim_id)
        return self._record(row)

    def create(self, spec, name):
        now = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        with self._connect() as c:
            cursor = c.execute('INSERT INTO simulations (name, created_at, spec_json) VALUES (?, ?, ?)', (name, now, json.dumps(spec, ensure_ascii=False)))
        return self.get(cursor.lastrowid)

    def delete(self, sim_id):
        self.get(sim_id)
        with self._connect() as c: c.execute('DELETE FROM simulations WHERE id = ?', (sim_id,))
