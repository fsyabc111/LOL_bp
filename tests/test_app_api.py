"""API and repository tests on a small fixture dataset; skipped without the app requirements."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

try:
    from fastapi.testclient import TestClient
except ImportError:  # requirements/app.txt not installed
    TestClient = None

sys.path.insert(0,str(Path(__file__).resolve().parent))
from fixtures import CHAMPS,build_fixture  # noqa: E402

@unittest.skipIf(TestClient is None,'app requirements not installed')
class AppApiTests(unittest.TestCase):
    def setUp(self):
        from lolbp.api import create_app
        from lolbp.branches import BranchStore
        from lolbp.repository import Repository
        self.tmp=tempfile.TemporaryDirectory();root=Path(self.tmp.name);build_fixture(root)
        self.repo=Repository(root)
        self.client=TestClient(create_app(self.repo,BranchStore(root/'branches.sqlite3')))
    def tearDown(self): self.tmp.cleanup()
    def test_series_grouping_and_replay(self):
        series=self.client.get('/api/series').json()
        self.assertEqual(len(series),1);self.assertEqual([g['game_number'] for g in series[0]['games']],[1,2])
        detail=self.client.get('/api/games/S1_game_2').json()
        self.assertEqual(detail['sequence_source']['type'],'oe_columns')
        # A 2025-06 LCK game falls under the 2025 LCK rulebook (effective 2025-04-02).
        self.assertEqual(detail['rules']['fearless']['status'],'inferred')
        self.assertEqual(detail['rules']['template']['status'],'observed')
        self.assertEqual(detail['rules']['disabled_champions']['status'],'unknown')
        # Game 2 re-picks game-1 picks under the assumed Fearless rule: reported, not hidden.
        self.assertTrue(any('fearless_consumed' in f['reasons'] for f in detail['replay_findings']))
        state=self.client.get('/api/games/S1_game_1/state',params={'step':6}).json()
        self.assertEqual(state['next'],{'step':7,'side':'Blue','action':'pick'})
        ahri=self.repo.champion_id('Ahri')
        self.assertEqual(state['unavailable'][ahri]['reasons'],['already_used_this_game'])
    def test_branch_fork_actions_undo_and_history_untouched(self):
        before=self.client.get('/api/games/S1_game_1').json()['sequence']
        r=self.client.post('/api/branches',json={'gameid':'S1_game_1','fork_step':6})
        self.assertEqual(r.status_code,201);bid=r.json()['branch']['id']
        self.assertEqual(r.json()['state']['step'],6)
        jinx=self.repo.champion_id('Jinx')
        r=self.client.post(f'/api/branches/{bid}/actions',json={'champion':jinx})
        self.assertEqual(r.status_code,200);self.assertEqual(r.json()['state']['board']['Blue']['picks'][0]['champion'],jinx)
        r=self.client.post(f'/api/branches/{bid}/actions',json={'champion':jinx})
        self.assertEqual(r.status_code,409);self.assertEqual(r.json()['detail']['reasons'],['already_used_this_game'])
        r=self.client.post(f'/api/branches/{bid}/actions',json={'champion':None})
        self.assertEqual(r.status_code,409);self.assertEqual(r.json()['detail']['reasons'],['empty_pick'])
        self.assertEqual(self.client.post(f'/api/branches/{bid}/undo').json()['state']['step'],6)
        self.assertEqual(self.client.post(f'/api/branches/{bid}/undo').status_code,409)
        self.assertEqual(self.client.get('/api/games/S1_game_1').json()['sequence'],before)
    def test_community_listed_disabled_champion_blocked(self):
        from lolbp.api import create_app
        from lolbp.branches import BranchStore
        from lolbp.repository import Repository
        root=Path(self.tmp.name)
        (root/'data/curated/event_restrictions.jsonl').write_text(json.dumps({'oe_gameid':'S1_game_1','disabled':['Jinx'],'listed_patch':'25.11',
            'hotfix':None,'source':{'locator':'Data:X rev 1 game1'}})+'\n')
        repo=Repository(root);client=TestClient(create_app(repo,BranchStore(root/'b2.sqlite3')))
        detail=client.get('/api/games/S1_game_1').json()
        self.assertEqual(detail['rules']['disabled_champions']['status'],'community_listed')
        state=client.get('/api/games/S1_game_1/state',params={'step':6}).json()
        self.assertEqual(state['unavailable'][repo.champion_id('Jinx')]['reasons'],['event_disabled'])
        self.assertEqual(client.get('/api/games/S1_game_2').json()['rules']['disabled_champions']['status'],'unknown')
    def test_fearless_override_on_branch(self):
        game1_pick=self.repo.champion_id(CHAMPS[9])  # game 1 step 10; unused in game 2's first six steps
        r=self.client.post('/api/branches',json={'gameid':'S1_game_2','fork_step':6})
        bid=r.json()['branch']['id']
        self.assertIn('fearless_consumed',r.json()['state']['unavailable'][game1_pick]['reasons'])
        r=self.client.post('/api/branches',json={'gameid':'S1_game_2','fork_step':6,'fearless_override':'none'})
        self.assertNotIn(game1_pick,r.json()['state']['unavailable'])
        self.assertEqual(r.json()['rules']['fearless']['status'],'user_assumption')
        self.assertEqual(self.client.post('/api/branches',json={'gameid':'S1_game_2','fork_step':6,'fearless_override':'x'}).status_code,422)
        self.assertEqual(self.client.post('/api/branches',json={'gameid':'S1_game_2','fork_step':21}).status_code,422)
        self.assertEqual(self.client.get('/api/games/nope').status_code,404)
        self.client.delete(f'/api/branches/{bid}');self.assertEqual(self.client.get(f'/api/branches/{bid}').status_code,404)
if __name__=='__main__':unittest.main()
