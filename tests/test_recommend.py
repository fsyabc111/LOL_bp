"""Candidate comparison on the synthetic fixture: listing, dimensions per action type, hypothetical rankings, API."""
from pathlib import Path
import sys
import tempfile
import unittest

from lolbp import draft
from lolbp.composition import Composer
from lolbp.predict import Predictor
from lolbp.recommend import Recommender
from lolbp.repository import Repository

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import GAMES, build_fixture  # noqa: E402
from test_composition import HISTORY  # noqa: E402

try:
    from fastapi.testclient import TestClient
except ImportError:  # requirements/app.txt not installed
    TestClient = None


class RecommendTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); root = Path(self.tmp.name)
        build_fixture(root, HISTORY + GAMES, models=True)
        self.repo = Repository(root); self.predictor = Predictor(self.repo)
        self.recommender = Recommender(self.predictor, Composer(self.repo, self.predictor))
        steps, _, _ = self.repo.sequence('S1_game_1')
        self.steps = tuple(draft.Action(s['step'], s['side'], s['action'], s['champion']) for s in steps)

    def tearDown(self): self.tmp.cleanup()

    def test_pick_slot_lists_model_choices_then_player_comfort(self):
        out = self.recommender.recommend('S1_game_1', self.steps[:6], top=5, extra=2)
        self.assertEqual(out['slot']['action'], 'pick')
        kinds = [c['listed_for'] for c in out['candidates']]
        self.assertEqual(kinds, ['model'] * 5 + ['player'] * 2)
        self.assertEqual([c['habit']['rank'] for c in out['candidates'][:5]], [1, 2, 3, 4, 5])
        first = out['candidates'][0]
        self.assertEqual(set(first) >= {'player', 'lane', 'profile', 'responses', 'fearless_cost'}, True)
        self.assertEqual(first['responses']['step'], 8); self.assertEqual(first['profile']['frontline'][0], 0)
        self.assertTrue(first['fearless_cost'])  # 2025 LCK: Fearless inferred from the rulebook

    def test_ban_slot_reports_denial_threat_and_own_interest(self):
        out = self.recommender.recommend('S1_game_1', self.steps[:12], top=4, extra=2)
        self.assertEqual((out['slot']['step'], out['slot']['action']), (13, 'ban'))
        for c in out['candidates']:
            self.assertIn('deny', c); self.assertIn('own_interest', c); self.assertIn('threat', c)
            self.assertNotIn(c['champion'], {a.champion for a in self.steps[:12]})
        self.assertTrue(all(c['listed_for'] in ('model', 'deny') for c in out['candidates']))

    def test_rank_as_scores_a_side_that_is_not_acting(self):
        model = self.predictor.version('v1')
        ranking = self.predictor.rank_as('S1_game_1', self.steps[:3], model, 'Red', 'pick')
        self.assertEqual((ranking.slot.side, ranking.slot.action, ranking.phase), ('Red', 'pick', 'pick1'))
        self.assertAlmostEqual(sum(ranking.probabilities), 1.0)
        self.assertIsNone(self.predictor.rank_as('S1_game_1', self.steps[:19], model, 'Blue', 'pick'))  # Blue has no picks left
        self.assertIsNone(self.recommender.recommend('S1_game_1', self.steps))


@unittest.skipIf(TestClient is None, 'app requirements not installed')
class RecommendApiTests(unittest.TestCase):
    def test_game_and_branch_recommendations(self):
        from lolbp.api import create_app
        from lolbp.branches import BranchStore
        from lolbp.feedback import FeedbackStore
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); build_fixture(root, HISTORY + GAMES, models=True)
            client = TestClient(create_app(Repository(root), BranchStore(root / 'b.sqlite3'), feedback_store=FeedbackStore(root / 'f.jsonl')))
            out = client.get('/api/games/S1_game_1/recommendations', params={'step': 6}).json()
            self.assertEqual(out['slot']['step'], 7); self.assertIsNone(out['evidence'])
            self.assertIsNone(client.get('/api/games/S1_game_1/recommendations', params={'step': 20}).json())
            self.assertEqual(client.get('/api/games/S1_game_1/recommendations', params={'step': 6, 'version': 'x'}).status_code, 422)
            bid = client.post('/api/branches', json={'gameid': 'S1_game_1', 'fork_step': 12}).json()['branch']['id']
            self.assertEqual(client.get(f'/api/branches/{bid}/recommendations').json()['slot']['action'], 'ban')


if __name__ == '__main__': unittest.main()
