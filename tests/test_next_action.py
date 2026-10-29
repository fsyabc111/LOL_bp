"""Next-action prediction, backtest helpers and feedback on the synthetic fixture."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

from lolbp import draft
from lolbp.backtest import evaluate, order_disputed, outcome, split_games
from lolbp.feedback import FeedbackStore, build, default_expect, recheck, verdict
from lolbp.predict import ModelError, Predictor, candidates, load_versions, open_roles
from lolbp.repository import Repository

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import CHAMPS, GAMES, build_fixture  # noqa: E402

try:
    from fastapi.testclient import TestClient
except ImportError:  # requirements/app.txt not installed
    TestClient = None
try:
    import numpy as np
except ImportError:  # requirements/model.txt not installed
    np = None

HISTORY = [{'gameid': 'H1_game_1', 'date': '2025-05-20 10:00:00', 'number': '1', 'champions': CHAMPS[:20], 'red': 'Team C'},
           {'gameid': 'H2_game_1', 'date': '2025-06-01 08:00:00', 'number': '1', 'champions': CHAMPS[1:21], 'red': 'Team C'}]


def actions_until(repo, gameid, step):
    steps, _, _ = repo.sequence(gameid)
    return tuple(draft.Action(s['step'], s['side'], s['action'], s['champion']) for s in steps[:step])


class PredictionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        build_fixture(self.root, HISTORY + GAMES, models=True)
        self.repo = Repository(self.root); self.predictor = Predictor(self.repo)
        self.cid = self.repo.champion_id

    def tearDown(self): self.tmp.cleanup()

    def test_statistics_use_only_earlier_dates(self):
        context = self.predictor.context('S1_game_1', self.predictor.version('baseline-meta').spec['stats'])
        # H2 is on the same date as S1_game_1, so only H1 counts; same-day series games are left out too.
        self.assertEqual(context.patch_games, 1)
        self.assertEqual(context.sides['Blue']['raw'], 1); self.assertEqual(context.sides['Red']['raw'], 0)
        mid = self.predictor.history.column[self.cid('Ziggs')]  # Team A mid in H1
        self.assertEqual(context.sides['Blue']['players'][2]['raw'], 1)
        self.assertGreater(context.sides['Blue']['players'][2]['share'][mid], context.role_share[2][mid])

    def test_patch_ramp_switches_from_earlier_patches_to_this_patch(self):
        stats = self.predictor.version('v1').spec['stats']
        plain = self.predictor.context('S1_game_1', stats)  # one same-patch game (H1) before S1_game_1
        held = self.predictor.context('S1_game_1', {**stats, 'patch_ramp': {'min_games': 5, 'full_games': 10, 'max_weight': 1.0}})
        full = self.predictor.context('S1_game_1', {**stats, 'patch_ramp': {'min_games': 1, 'full_games': 1, 'max_weight': 0.8}})
        ziggs = self.predictor.history.column[self.cid('Ziggs')]  # picked in H1
        self.assertEqual((held.patch_weight, full.patch_weight), (0.0, 0.8))
        self.assertLess(held.meta_pick[ziggs], plain.meta_pick[ziggs])  # below min_games: earlier patches only
        self.assertGreater(full.meta_pick[ziggs], 0.4)  # 0.8 x (1 pick + prior) / (1 game + 1) + 0.2 x prior
        self.assertGreater(full.meta_pick[ziggs], plain.meta_pick[ziggs])
        self.assertAlmostEqual(sum(full.role_share[2]), 1.0, places=6)

    def test_rest_days_and_lineup_weighting(self):
        history = self.predictor.history
        self.assertEqual(history.rest_days('id:Team A', '2025-06-01'), 12)  # H1 on 2025-05-20; same-day H2 does not count
        self.assertIsNone(history.rest_days('id:Team B', '2025-06-01'))
        stats = self.predictor.version('v1').spec['stats']
        self.assertEqual(self.predictor.context('S1_game_1', stats).after_break, 0.0)
        self.assertEqual(self.predictor.context('S1_game_1', {**stats, 'break_days': 10}).after_break, 1.0)
        tau = 60 / 0.6931471805599453
        full = history.team('id:Team A', '2025-06-01', tau)
        same = history.team('id:Team A', '2025-06-01', tau, {f'pid:Team A:{r}' for r in ('top', 'jng', 'mid', 'bot', 'sup')})
        two = history.team('id:Team A', '2025-06-01', tau, {'pid:Team A:top', 'pid:Team A:mid'})
        self.assertAlmostEqual(same[0], full[0]); self.assertAlmostEqual(two[0], 0.4 * full[0]); self.assertEqual(two[1], full[1])

    def test_open_roles_keep_flex_picks_ambiguous(self):
        mid_only, flex = [0.01, 0.01, 0.96, 0.01, 0.01], [0.495, 0.495, 0.0, 0.005, 0.005]
        self.assertEqual(open_roles([mid_only], []), [1.0] * 5)
        opened = open_roles([mid_only, flex], [0])
        self.assertLess(opened[2], 0.05); self.assertGreater(opened[0], 0.95)
        both = open_roles([mid_only, flex], [0, 1])
        self.assertAlmostEqual(both[0], both[1], places=2); self.assertLess(both[0], 0.6); self.assertAlmostEqual(sum(both), 3.0)

    def test_candidates_drop_illegal_and_wasted_bans(self):
        template = self.repo.template
        rules = draft.DraftRules(slots=draft.slots_from_template(template, 'Blue'), fearless=draft.FEARLESS_PICKS_BOTH, consumed=frozenset({'c'}))
        ban_slot = draft.next_slot(rules, ())
        self.assertEqual(candidates(rules, (), ban_slot, ['a', 'b', 'c']), ['a', 'b'])
        actions = draft.apply(rules, (), 'a')
        self.assertEqual(candidates(rules, actions, draft.next_slot(rules, actions), ['a', 'b', 'c']), ['b'])

    def test_ranking_is_a_distribution_with_reasons(self):
        for version in ('baseline-meta', 'baseline-player', 'v1', 'v2'):
            model = self.predictor.version(version)
            ranking = self.predictor.rank('S1_game_2', actions_until(self.repo, 'S1_game_2', 7), model)
            self.assertEqual(ranking.slot.step, 8); self.assertEqual(ranking.phase, 'pick1')
            self.assertAlmostEqual(sum(ranking.probabilities), 1.0)
            self.assertEqual(ranking.probabilities, sorted(ranking.probabilities, reverse=True))
            used = {a.champion for a in actions_until(self.repo, 'S1_game_2', 7)}
            consumed = {self.cid(CHAMPS[i - 1]) for i in (7, 8, 9, 10, 11, 12, 17, 18, 19, 20)}  # game-1 picks
            self.assertFalse(set(ranking.champions) & (used | consumed))  # Fearless (inferred for 2025 LCK) removes game-1 picks
            self.assertEqual(ranking.rank_of(ranking.champions[0]), (1, ranking.probabilities[0]))
            self.assertIsNone(ranking.rank_of('nope'))
            self.assertTrue(all(isinstance(r['text'], str) for r in ranking.reasons(0)))

    def test_predict_payload_reports_recorded_actions(self):
        steps, _, _ = self.repo.sequence('S1_game_1')
        recorded = {s['step']: s['champion'] for s in steps}
        out = self.predictor.predict('S1_game_1', actions_until(self.repo, 'S1_game_1', 7), version='v1', top=5, actual=recorded)
        self.assertEqual(out['slot'], {'step': 8, 'side': 'Red', 'action': 'pick', 'phase': 'pick1', 'team': 'Team B', 'opponent': 'Team A'})
        self.assertEqual(len(out['candidates']), 5); self.assertEqual(out['actual']['champion'], recorded[8])
        self.assertEqual(out['paired_actual']['step'], 9)
        self.assertIsNone(out['reliability'])  # no validation report in the fixture
        self.assertTrue(any('Team B' in n for n in out['notes']))  # no earlier games for Team B
        self.assertIsNone(self.predictor.predict('S1_game_1', actions_until(self.repo, 'S1_game_1', 20), version='v1'))

    def test_series_bans_follow_team_ids_across_side_swaps(self):
        swapped = [GAMES[0], {**GAMES[1], 'blue': 'Team B', 'red': 'Team A'}]
        root = self.root / 'swap'; build_fixture(root, swapped, models=True)
        predictor = Predictor(Repository(root))
        context = predictor.context('S1_game_2', predictor.version('v1').spec['stats'])
        column = predictor.history.column
        team_a_bans = {column[predictor.repo.champion_id(CHAMPS[i - 1])] for i in (1, 3, 5, 14, 16)}
        self.assertEqual(context.sides['Red']['series_ban'], team_a_bans)  # Team A is red in game 2
        self.assertEqual(context.sides['Blue']['series_banned_vs'], team_a_bans)

    def test_version_files_are_validated(self):
        models = self.root / 'models/next_action'
        spec = json.loads((models / 'v1.json').read_text()); spec.update(version='v9', weights=None)
        (models / 'v9.json').write_text(json.dumps(spec))
        with self.assertRaises(ModelError): self.predictor.version('v9')  # not trained yet
        with self.assertRaises(ModelError): self.predictor.version('missing')
        (models / 'v8.json').write_text(json.dumps({**spec, 'version': 'other'}))
        with self.assertRaises(ModelError): load_versions(models)

    def test_backtest_outcome_split_and_disputed_order(self):
        self.assertEqual(outcome(['a', 'b', 'c'], [0.2, 0.5, 0.3], 'c'), (2, 0.3))
        rank, prob = outcome(['a', 'b', 'c'], [0.2, 0.5, 0.3], 'c', 'b'); self.assertEqual(rank, 1); self.assertAlmostEqual(prob, 0.8)
        self.assertEqual(outcome(['a'], [1.0], 'z'), (None, None))
        settings = {'splits': {'validation': ['2025-06-01', '2025-06-30'], 'train': ['2025-01-01', '2025-05-31']}}
        self.assertEqual(split_games(self.repo, settings, 'validation', self.predictor.pairs), (['H2_game_1', 'S1_game_1', 'S1_game_2'], 0))
        self.assertEqual(split_games(self.repo, settings, 'train', self.predictor.pairs)[0], ['H1_game_1'])
        steps, _, _ = self.repo.sequence('S1_game_1')
        names = {self.cid(n): n for n in CHAMPS}

        def evidence(order):
            return {'oe_gameid': 'S1_game_1', 'first_selection_side': 'Blue', 'source': {'locator': 'x', 'revid': 1, 'title': 'T/Picks and Bans'},
                    'steps': [{**steps[i - 1], 'champion': names[steps[j - 1]['champion']]} for i, j in enumerate(order, 1)]}
        within_pair = list(range(1, 21)); within_pair[7:9] = [9, 8]
        across = list(range(1, 21)); across[0], across[2] = 3, 1
        for order, disputed in ((within_pair, False), (across, True)):
            (self.root / 'data/curated/bp_sequences.jsonl').write_text(json.dumps(evidence(order)) + '\n')
            repo = Repository(self.root)
            self.assertEqual(repo.sequence('S1_game_1')[2]['type'], 'leaguepedia')
            self.assertEqual(order_disputed(repo, 'S1_game_1', self.predictor.pairs), disputed)

    def test_evaluate_counts_every_recorded_step(self):
        models = [self.predictor.version('baseline-meta'), self.predictor.version('v1')]
        out = evaluate(self.predictor, models, ['S1_game_1', 'S1_game_2'])
        for version in ('baseline-meta', 'v1'):
            overall = out[version]['overall']
            self.assertEqual(overall['decisions'], 40)
            self.assertLessEqual(overall['top1'], overall['top3']); self.assertLessEqual(overall['top5'], overall['top10'])
            self.assertEqual(sum(r['decisions'] for r in out[version]['by_phase'].values()), 40)


class FeedbackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        build_fixture(self.root, HISTORY + GAMES, models=True)
        self.repo = Repository(self.root); self.predictor = Predictor(self.repo)
        self.store = FeedbackStore(self.root / 'feedback.jsonl')
        self.model = self.predictor.version('v1')
        self.actions = actions_until(self.repo, 'S1_game_1', 6)
        self.ranking = self.predictor.rank('S1_game_1', self.actions, self.model)

    def tearDown(self): self.tmp.cleanup()

    def record(self, kind, champion, **kw):
        return build(self.predictor, 'S1_game_1', self.actions, None, self.model, kind, champion, kw.get('expect'), kw.get('note', ''), 'replay')

    def test_expectations_and_verdicts(self):
        self.assertEqual(default_expect('too_high', 1, 5), 5); self.assertEqual(default_expect('too_high', 8, 5), 8)
        self.assertEqual(default_expect('too_low', 9, 5), 5); self.assertEqual(default_expect('too_low', 3, 5), 2)
        self.assertEqual(verdict('too_high', 1, 6, 5), 'met'); self.assertEqual(verdict('too_high', 1, 3, 5), 'improved')
        self.assertEqual(verdict('too_high', 2, 1, 5), 'worse'); self.assertEqual(verdict('too_high', 2, 2, 5), 'unchanged')
        self.assertEqual(verdict('too_low', 9, 4, 5), 'met'); self.assertEqual(verdict('too_low', 9, 12, 5), 'worse')
        self.assertEqual(verdict('too_low', 9, None, 5), 'unavailable'); self.assertEqual(verdict('other', None, None, None), 'review')

    def test_build_validates_and_snapshots_the_state(self):
        top, third = self.ranking.champions[0], self.ranking.champions[2]
        record = self.record('too_high', top, note=' 不合理 ')
        self.assertEqual((record['rank'], record['expect_rank'], record['note']), (1, 5, '不合理'))
        self.assertEqual(record['slot'], {'step': 7, 'side': 'Blue', 'action': 'pick', 'phase': 'pick1'})
        self.assertEqual(len(record['actions']), 6); self.assertEqual(record['model']['sha256'], self.model.sha256)
        self.assertEqual(self.record('too_low', third)['expect_rank'], 2)
        for kind, champion, expect in (('too_low', top, None), ('too_high', third, 1), ('too_low', third, 3), ('too_high', None, None)):
            with self.assertRaises(ValueError): self.record(kind, champion, expect=expect)
        used = self.actions[0].champion
        with self.assertRaises(ValueError): self.record('too_high', used)  # already banned: not a legal candidate
        self.assertIsNone(self.record('other', None)['expect_rank'])

    def test_store_and_recheck(self):
        first = self.store.add(self.record('too_high', self.ranking.champions[0]))
        second = self.store.add(self.record('other', None, note='整体偏向版本热门'))
        self.assertEqual((first['id'], second['id']), (1, 2)); self.assertEqual([r['id'] for r in self.store.list()], [1, 2])
        check = recheck(self.predictor, first, self.model)
        self.assertEqual((check['verdict'], check['rank'], check['model_file_changed']), ('unchanged', 1, False))
        self.assertTrue(recheck(self.predictor, {**first, 'model': {'version': 'v1', 'sha256': 'old'}}, self.model)['model_file_changed'])
        self.assertEqual(recheck(self.predictor, second, self.predictor.version('baseline-meta'))['verdict'], 'review')
        self.assertEqual(recheck(self.predictor, {**first, 'gameid': 'gone'}, self.model)['verdict'], 'unavailable')
        self.store.delete(1); self.assertEqual([r['id'] for r in self.store.list()], [2])
        with self.assertRaises(KeyError): self.store.delete(1)
        self.assertEqual(self.store.add(self.record('other', None))['id'], 3)


@unittest.skipIf(TestClient is None, 'app requirements not installed')
class PredictionApiTests(unittest.TestCase):
    def setUp(self):
        from lolbp.api import create_app
        from lolbp.branches import BranchStore
        self.tmp = tempfile.TemporaryDirectory(); root = Path(self.tmp.name)
        build_fixture(root, HISTORY + GAMES, models=True)
        self.repo = Repository(root)
        self.client = TestClient(create_app(self.repo, BranchStore(root / 'branches.sqlite3'), Predictor(self.repo), FeedbackStore(root / 'feedback.jsonl')))

    def tearDown(self): self.tmp.cleanup()

    def test_models_and_predictions(self):
        models = self.client.get('/api/models').json()
        self.assertEqual(models['default'], 'v7'); self.assertTrue(all(v['ready'] for v in models['versions']))
        out = self.client.get('/api/games/S1_game_1/predictions', params={'step': 6}).json()
        self.assertEqual(out['slot']['step'], 7); self.assertEqual(out['model']['version'], 'v7'); self.assertEqual(len(out['candidates']), 10)
        self.assertIsNotNone(out['actual'])
        self.assertIsNone(self.client.get('/api/games/S1_game_1/predictions', params={'step': 20}).json())
        self.assertEqual(self.client.get('/api/games/S1_game_1/predictions', params={'step': 6, 'version': 'nope'}).status_code, 422)
        self.assertEqual(self.client.get('/api/games/S1_game_1/predictions', params={'step': 21}).status_code, 422)
        bid = self.client.post('/api/branches', json={'gameid': 'S1_game_1', 'fork_step': 12}).json()['branch']['id']
        out = self.client.get(f'/api/branches/{bid}/predictions', params={'version': 'baseline-player'}).json()
        self.assertEqual((out['slot']['step'], out['model']['version']), (13, 'baseline-player'))

    def test_feedback_round_trip(self):
        top = self.client.get('/api/games/S1_game_1/predictions', params={'step': 6}).json()['candidates'][0]['champion']
        r = self.client.post('/api/feedback', json={'gameid': 'S1_game_1', 'step': 6, 'kind': 'too_high', 'champion': top, 'note': '太高'})
        self.assertEqual(r.status_code, 201); self.assertEqual((r.json()['id'], r.json()['source']), (1, 'replay'))
        self.assertEqual(self.client.post('/api/feedback', json={'gameid': 'S1_game_1', 'step': 6, 'kind': 'too_low', 'champion': top}).status_code, 422)
        self.assertEqual(self.client.post('/api/feedback', json={'gameid': 'S1_game_1', 'kind': 'other'}).status_code, 422)
        bid = self.client.post('/api/branches', json={'gameid': 'S1_game_1', 'fork_step': 12}).json()['branch']['id']
        r = self.client.post('/api/feedback', json={'gameid': 'S1_game_1', 'branch_id': bid, 'kind': 'other', 'note': '整体不对'})
        self.assertEqual((r.status_code, r.json()['branch']['id'], r.json()['slot']['step']), (201, bid, 13))
        items = self.client.get('/api/feedback', params={'version': 'v1'}).json()
        self.assertEqual([i['id'] for i in items], [2, 1]); self.assertEqual(items[1]['recheck']['verdict'], 'unchanged')
        self.assertTrue(items[0]['branch_exists']); self.assertEqual(items[1]['game']['blue'], 'Team A')
        self.client.delete(f'/api/branches/{bid}')
        self.assertFalse(self.client.get('/api/feedback').json()[0]['branch_exists'])
        self.assertEqual(self.client.delete('/api/feedback/1').status_code, 204)
        self.assertEqual(self.client.delete('/api/feedback/1').status_code, 404)


@unittest.skipIf(np is None, 'numpy (requirements/model.txt) not installed')
class TrainingTests(unittest.TestCase):
    def test_conditional_logit_recovers_weights_on_raw_scale(self):
        spec = importlib.util.spec_from_file_location('train', Path(__file__).resolve().parents[1] / 'scripts/train_next_action.py')
        train = importlib.util.module_from_spec(spec); spec.loader.exec_module(train)
        rng = np.random.default_rng(7); true = np.array([1.5, -0.07, 0.0])  # raw-scale weights; feature 2 varies 10x more
        rows, sizes, chosen = [], [], []
        for _ in range(1500):
            x = rng.standard_normal((8, 3)) * np.array([1.0, 10.0, 1.0])
            p = np.exp(x @ true); p /= p.sum()
            rows.extend(x.tolist()); sizes.append(8); chosen.append(int(rng.choice(8, p=p)))
        with np.errstate(all='ignore'): w, loglik, iterations = train.fit_phase(rows, sizes, chosen, l2=0.1)
        self.assertTrue(np.allclose(w, true, atol=np.array([0.15, 0.015, 0.1])), w)
        self.assertLess(iterations, 50); self.assertLess(loglik, 0)


if __name__ == '__main__': unittest.main()
