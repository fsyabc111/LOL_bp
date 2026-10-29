"""Composition evaluation on the synthetic fixture: point-in-time lane, matchup and duo evidence, roles, profile."""
from pathlib import Path
import sys
import tempfile
import unittest

from lolbp import draft
from lolbp.composition import Composer, assign_roles
from lolbp.predict import Predictor
from lolbp.repository import Repository

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import CHAMPS, GAMES, build_fixture  # noqa: E402

try:
    from fastapi.testclient import TestClient
except ImportError:  # requirements/app.txt not installed
    TestClient = None

LANES = {'top': 600, 'jng': 0, 'mid': 0, 'bot': 0, 'sup': 0}
HISTORY = [{'gameid': f'H{i}_game_1', 'date': f'2025-05-0{i} 10:00:00', 'number': '1', 'champions': CHAMPS[:20], 'red': 'Team C',
            'lanes': LANES, 'winner': w} for i, w in ((1, 'Blue'), (2, 'Blue'), (3, 'Red'))]
SAME_DAY = {'gameid': 'H9_game_1', 'date': '2025-06-01 08:00:00', 'number': '1', 'champions': CHAMPS[:20], 'red': 'Team C',
            'lanes': {**LANES, 'top': -5000}}


class CompositionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); root = Path(self.tmp.name)
        build_fixture(root, HISTORY + [SAME_DAY] + GAMES, models=True)
        self.repo = Repository(root); self.predictor = Predictor(self.repo); self.composer = Composer(self.repo, self.predictor)
        self.col = lambda name: self.predictor.history.column[self.repo.champion_id(name)]
        steps, _, _ = self.repo.sequence('S1_game_1')
        self.actions = tuple(draft.Action(s['step'], s['side'], s['action'], s['champion']) for s in steps)

    def tearDown(self): self.tmp.cleanup()

    def test_assign_roles_takes_most_probable(self):
        prob = [[0.9, 0.025, 0.025, 0.025, 0.025], [0.5, 0.4, 0.05, 0.025, 0.025]]
        self.assertEqual(assign_roles(prob, [0, 1])[0], [('top', 0), ('jng', 1)])
        self.assertEqual(assign_roles(prob, []), ([], 1.0))

    def test_lane_evidence_is_point_in_time_and_shrunk(self):
        maokai, rell = self.col('Maokai'), self.col('Rell')  # Blue top vs Red top in every fixture game
        own = self.composer.champion(maokai, 'top', '2025-06-01')
        self.assertEqual(own['lane_games'], 3)  # the same-day -5000 game is excluded
        self.assertTrue(0 < own['lane'] < 600)  # shrunk toward 0 with 20 pseudo-games
        m = self.composer.matchup(maokai, rell, 'top', '2025-06-01')
        self.assertEqual((m['games'], m['lane_games'], m['wins']), (3, 3, 2))
        self.assertGreater(m['expected'], m['champion_part']); self.assertGreater(m['champion_part'], 0)
        self.assertEqual(self.composer.champion(maokai, 'top', '2025-05-01')['lane_games'], 0)

    def test_duo_counts_same_team_pairs(self):
        bot, sup = self.col(CHAMPS[17]), self.col(CHAMPS[18])  # Blue picks at steps 18 and 19
        d = self.composer.duo(bot, 'bot', sup, 'sup', '2025-06-01')
        self.assertEqual((d['games'], d['lane_games']), (3, 3)); self.assertTrue(0 < d['expected_win'] < 1)

    def test_evaluate_full_and_partial_drafts(self):
        out = self.composer.evaluate('S1_game_1', self.actions)
        self.assertEqual([l['role'] for l in out['lanes']], ['top', 'jng', 'mid', 'bot', 'sup'])
        top = out['lanes'][0]
        self.assertEqual((top['blue'], top['red']), (self.repo.champion_id('Maokai'), self.repo.champion_id('Rell')))
        self.assertFalse(top['enough'])  # 3 games < 5 minimum: no lane finding is made
        self.assertFalse([f for f in out['sides']['Blue']['flags'] if f['kind'] == 'lane'])
        profile = out['sides']['Blue']['profile']
        self.assertEqual(profile['champions'], 5); self.assertTrue(0 <= profile['magic_share'] <= 1)
        self.assertTrue(all(not d['enough'] for d in out['sides']['Blue']['duos']))
        partial = self.composer.evaluate('S1_game_1', self.actions[:7])  # one Blue pick, no Red pick yet
        self.assertEqual(partial['lanes'], []); self.assertEqual(len(partial['sides']['Blue']['assignment']), 1)
        self.assertEqual(partial['sides']['Red']['profile'], {'champions': 0})


@unittest.skipIf(TestClient is None, 'app requirements not installed')
class CompositionApiTests(unittest.TestCase):
    def test_game_and_branch_composition(self):
        from lolbp.api import create_app
        from lolbp.branches import BranchStore
        from lolbp.feedback import FeedbackStore
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); build_fixture(root, HISTORY + GAMES, models=True)
            client = TestClient(create_app(Repository(root), BranchStore(root / 'b.sqlite3'), feedback_store=FeedbackStore(root / 'f.jsonl')))
            out = client.get('/api/games/S1_game_1/composition', params={'step': 20}).json()
            self.assertEqual(len(out['lanes']), 5); self.assertIsNone(out['backtest'])
            self.assertEqual(client.get('/api/games/S1_game_1/composition', params={'step': 21}).status_code, 422)
            bid = client.post('/api/branches', json={'gameid': 'S1_game_1', 'fork_step': 9}).json()['branch']['id']
            out = client.get(f'/api/branches/{bid}/composition').json()
            self.assertEqual(len(out['sides']['Red']['assignment']), 2)


if __name__ == '__main__': unittest.main()
