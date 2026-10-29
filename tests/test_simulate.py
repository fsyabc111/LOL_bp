from pathlib import Path
import sys
import tempfile
import unittest

from lolbp import simulate
from lolbp.feedback import FeedbackStore
from lolbp.predict import Predictor
from lolbp.repository import Repository

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import GAMES, build_fixture  # noqa: E402
from test_composition import HISTORY  # noqa: E402

try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover
    TestClient = None


class SimulationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); root = Path(self.tmp.name)
        build_fixture(root, HISTORY + GAMES, models=True)
        self.repo = Repository(root); self.history = Predictor(self.repo).history

    def tearDown(self): self.tmp.cleanup()

    def test_patch_cutoff_and_teams(self):
        self.assertEqual([p['patch'] for p in simulate.patches(self.history)], ['25.11'])
        cutoff, teams = simulate.teams(self.history, '25.11')
        self.assertEqual(cutoff, '2025-06-02')  # day after the patch's last game, so every game on it is history
        self.assertEqual({t['name'] for t in teams}, {'Team A', 'Team B', 'Team C'})
        a = next(t for t in teams if t['name'] == 'Team A')
        self.assertEqual(a['players']['mid'], ['pid:Team A:mid', 'Team A mid'])
        with self.assertRaises(ValueError): simulate.build_spec(self.history, '25.11', 'id:Team A', 'id:Team A')
        with self.assertRaises(ValueError): simulate.cutoff_of(self.history, '99.99')

    def test_generic_sides(self):
        both = simulate.build_spec(self.history, '25.11', '', '')
        self.assertEqual([both['sides'][s]['name'] for s in ('Blue', 'Red')], ['蓝方', '红方'])
        self.assertTrue(all(both['sides'][s]['generic'] and both['sides'][s]['players'] == {} for s in ('Blue', 'Red')))
        top = simulate.leagues(self.history, '25.11')[0]['league']
        self.assertEqual(both['sides']['Blue']['league'], top)  # rules default to the league with most games on the patch
        mixed = simulate.build_spec(self.history, '25.11', '', 'id:Team A')
        self.assertEqual(mixed['sides']['Red']['name'], 'Team A')
        self.assertEqual(mixed['sides']['Blue']['league'], mixed['sides']['Red']['league'])  # generic blue borrows the red team's rules
        with self.assertRaises(ValueError): simulate.build_spec(self.history, '25.11', '', '', league='NOPE')

    def test_simulation_is_never_history(self):
        spec = simulate.build_spec(self.history, '25.11', 'id:Team C', 'id:Team A')
        sim = {**spec, 'id': 1, 'gameid': 'sim-1', 'name': 'x', 'created_at': ''}
        before = len(self.history.order)
        self.repo.add_simulation(sim); self.history.add_simulation(sim)
        self.assertEqual(len(self.history.order), before)
        self.assertEqual(self.repo.sequence('sim-1')[0], [])
        self.assertFalse(any(s.get('simulated') for s in self.repo.list_series()))
        self.assertEqual(self.repo.series_context('sim-1')['prior_gameids'], [])
        self.assertEqual(self.history.games['sim-1']['sides']['Blue']['team'], 'id:Team C')


@unittest.skipIf(TestClient is None, 'app requirements not installed')
class SimulationApiTests(unittest.TestCase):
    def setUp(self):
        from lolbp.api import create_app
        from lolbp.branches import BranchStore
        self.tmp = tempfile.TemporaryDirectory(); self.root = root = Path(self.tmp.name)
        build_fixture(root, HISTORY + GAMES, models=True)
        self.make = lambda: TestClient(create_app(Repository(root), BranchStore(root / 'branches.sqlite3'), None, FeedbackStore(root / 'feedback.jsonl')))
        self.client = self.make()

    def tearDown(self): self.tmp.cleanup()

    def test_create_play_reload_delete(self):
        c = self.client
        self.assertEqual(c.get('/api/simulations/teams', params={'patch': '25.11'}).json()['cutoff'], '2025-06-02')
        self.assertEqual(c.post('/api/simulations', json={'patch': '25.11', 'blue': 'id:Team A', 'red': 'nope'}).status_code, 422)
        sim = c.post('/api/simulations', json={'patch': '25.11', 'blue': 'id:Team C', 'red': 'id:Team B'}).json()
        self.assertEqual((sim['gameid'], sim['name']), ('sim-1', 'Team C vs Team B · 25.11'))
        branch = sim['branch_id']
        p = c.get(f'/api/branches/{branch}/predictions').json()
        self.assertEqual((p['slot']['step'], p['slot']['team'], p['cutoff']), (1, 'Team C', '2025-06-02'))
        self.assertEqual(c.post(f'/api/branches/{branch}/actions', json={'champion': p['candidates'][0]['champion']}).status_code, 200)
        self.assertEqual(c.get(f'/api/branches/{branch}/recommendations').status_code, 200)
        self.assertEqual(c.get(f'/api/branches/{branch}/composition').status_code, 200)
        self.assertEqual(c.post('/api/feedback', json={'gameid': 'sim-1', 'branch_id': branch, 'kind': 'other'}).status_code, 422)
        self.assertEqual(c.get('/api/meta').json()['games'], len(HISTORY + GAMES))
        reloaded = self.make()  # a restarted app registers stored simulations again
        self.assertEqual(len(reloaded.get(f'/api/branches/{branch}').json()['branch']['actions']), 1)
        self.assertEqual(reloaded.get('/api/games/sim-1').json()['sequence_source']['type'], 'simulation')
        self.assertEqual(reloaded.delete(f"/api/simulations/{sim['id']}").status_code, 204)
        self.assertEqual(reloaded.get('/api/games/sim-1').status_code, 404)
        self.assertEqual(reloaded.get('/api/branches', params={'gameid': 'sim-1'}).json(), [])

    def test_generic_simulation(self):
        c = self.client
        self.assertTrue(c.get('/api/simulations/teams', params={'patch': '25.11'}).json()['leagues'])
        sim = c.post('/api/simulations', json={'patch': '25.11', 'red': 'id:Team B'}).json()
        self.assertEqual(sim['name'], '蓝方 vs Team B · 25.11')
        branch = sim['branch_id']
        p = c.get(f'/api/branches/{branch}/predictions').json()
        self.assertEqual(p['slot']['team'], '蓝方')
        self.assertTrue(any('未指定队伍' in n for n in p['notes']))
        r = c.get(f'/api/branches/{branch}/recommendations').json()
        self.assertTrue(r['candidates'] and not any('player' in x or x['listed_for'] == 'player' for x in r['candidates']))
        self.assertEqual(c.post(f'/api/branches/{branch}/actions', json={'champion': p['candidates'][0]['champion']}).status_code, 200)
        r = c.get(f'/api/branches/{branch}/recommendations').json()  # red bans: the generic blue side has no player to target
        self.assertEqual(r['slot']['action'], 'ban')
        self.assertTrue(r['candidates'] and not any('opponent_player' in x for x in r['candidates']))
        while r['slot']['action'] != 'pick':
            self.assertEqual(c.post(f'/api/branches/{branch}/actions', json={'champion': r['candidates'][0]['champion']}).status_code, 200)
            r = c.get(f'/api/branches/{branch}/recommendations').json()
        self.assertFalse(any(x['fearless_cost'] for x in r['candidates']))  # a single game: no series to carry picks into
        self.assertEqual(c.get(f'/api/branches/{branch}/composition').status_code, 200)


if __name__ == '__main__': unittest.main()
