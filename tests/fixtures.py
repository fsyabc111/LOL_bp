"""Small synthetic dataset shared by the app, prediction and feedback tests.

Each game lists its 20 champions in step order (snake_20 with Blue first: bans 1,3,5,14,16 / 2,4,6,13,15, picks
7,10,11,18,19 / 8,9,12,17,20); each side's picks map to top, jng, mid, bot, sup in pick order.
"""
import json
from pathlib import Path
import shutil
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
CHAMPS = ['Ahri', 'Azir', 'Corki', 'Gnar', 'KSante', 'LeeSin', 'Maokai', 'Rell', 'Tristana', 'Vi', 'Ziggs', 'Annie', 'Ashe', 'Braum',
          'Caitlyn', 'Darius', 'Ezreal', 'Fiora', 'Galio', 'Garen', 'Jinx', 'Karma']
STEPS = {'Blue': {'ban': (1, 3, 5, 14, 16), 'pick': (7, 10, 11, 18, 19)}, 'Red': {'ban': (2, 4, 6, 13, 15), 'pick': (8, 9, 12, 17, 20)}}
ROLES = ('top', 'jng', 'mid', 'bot', 'sup')
GAMES = [{'gameid': 'S1_game_1', 'date': '2025-06-01 10:00:00', 'number': '1', 'champions': CHAMPS[:20]},
         {'gameid': 'S1_game_2', 'date': '2025-06-01 11:00:00', 'number': '2', 'champions': CHAMPS[2:22]}]
MODEL_FILES = ['settings.json', 'baseline-meta.json', 'baseline-player.json', 'v1.json']


def build_fixture(root, games=GAMES, models=False):
    for path in ['data/curated/rules.json', 'data/curated/champion_traits.json', 'data/curated/static/16.20.1/en_US/champion.json', 'data/curated/static/16.20.1/zh_CN/champion.json']:
        (root / path).parent.mkdir(parents=True, exist_ok=True); shutil.copy(ROOT / path, root / path)
    if models:
        (root / 'models/next_action').mkdir(parents=True, exist_ok=True)
        for name in MODEL_FILES: shutil.copy(ROOT / 'models/next_action' / name, root / 'models/next_action' / name)
        (root / 'models/composition').mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / 'models/composition/settings.json', root / 'models/composition/settings.json')
    (root / 'data/processed').mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(root / 'data/processed/lol_bp.sqlite3')
    c.execute('CREATE TABLE games (gameid TEXT, league_raw TEXT, date_raw TEXT, patch_raw TEXT, game_number_raw TEXT, structural_valid INTEGER, winner_side TEXT)')
    c.execute('CREATE TABLE team_drafts (gameid TEXT, side TEXT, team_id TEXT, team_name TEXT, first_pick_raw TEXT, result REAL, picks_raw_json TEXT, bans_raw_json TEXT)')
    c.execute('CREATE TABLE player_games (gameid TEXT, side TEXT, final_role TEXT, player_id TEXT, player_name TEXT, champion_name_raw TEXT, result REAL, stats_json TEXT)')
    for g in games:
        teams = {'Blue': g.get('blue', 'Team A'), 'Red': g.get('red', 'Team B')}
        c.execute('INSERT INTO games VALUES (?,?,?,?,?,1,?)', (g['gameid'], g.get('league', 'LCK'), g['date'], g.get('patch', '25.11'), g['number'], g.get('winner', 'Blue')))
        for side, team in teams.items():
            picks = [g['champions'][i - 1] for i in STEPS[side]['pick']]; bans = [g['champions'][i - 1] for i in STEPS[side]['ban']]
            won = side == g.get('winner', 'Blue')
            c.execute('INSERT INTO team_drafts VALUES (?,?,?,?,?,?,?,?)', (g['gameid'], side, 'id:' + team, team, '1' if side == 'Blue' else '0',
                                                                         1.0 if won else 0.0, json.dumps(picks), json.dumps(bans)))
            sign = 1 if side == g.get('winner', 'Blue') else -1
            for role, champion in zip(ROLES, picks):
                lane = g.get('lanes', {}).get(role)  # Blue-perspective golddiffat15 for this role, if given
                stats = {} if lane is None else {'golddiffat15': lane * (1 if side == 'Blue' else -1), 'xpdiffat15': 0.0, 'csdiffat15': 0.0}
                c.execute('INSERT INTO player_games VALUES (?,?,?,?,?,?,?,?)', (g['gameid'], side, role, f'pid:{team}:{role}', f'{team} {role}',
                                                                               champion, 1.0 if sign > 0 else 0.0, json.dumps(stats)))
    c.commit(); c.close()
