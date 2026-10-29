"""KR solo queue aggregates: only days before the game count, previous-patch change, minimum sample."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

from lolbp.predict import Predictor
from lolbp.repository import Repository
from lolbp.soloq import SoloQueue

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import GAMES, build_fixture  # noqa: E402

AHRI, AZIR = '103', '268'


def write(root, patch, days):
    path = root / 'data/curated/kr_soloq' / f'{patch}.json'; path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'patch': patch, 'days': days}))


class SoloQueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        build_fixture(self.root, [{**g, 'patch': '15.11'} for g in GAMES], models=True)
        write(self.root, '25.10', {'2025-05-14': {'games': 100, 'champions': {AHRI: [10, 0], AZIR: [40, 10]}}})
        write(self.root, '25.11', {'2025-05-29': {'games': 40, 'champions': {AHRI: [20, 0]}},
                                   '2025-06-01': {'games': 60, 'champions': {AHRI: [60, 0], AZIR: [5, 0]}}})
        (self.root / 'data/curated/patch_mapping.json').write_text(json.dumps({'mapping': {'15.11': {'leaguepedia': '25.11'}}}))
        (self.root / 'data/curated/patch_changes.jsonl').write_text('')

    def tearDown(self): self.tmp.cleanup()

    def test_presence_uses_only_earlier_days(self):
        solo = SoloQueue(self.root)
        self.assertEqual(solo.presence('25.11', before='2025-06-01'), ({AHRI: 0.5}, 40))  # the game-day sample is excluded
        self.assertEqual(solo.presence('25.11')[1], 100)
        self.assertEqual(solo.previous('25.11'), '25.10'); self.assertIsNone(solo.previous('25.10'))
        self.assertEqual(solo.presence('99.99'), ({}, 0))

    def test_context_features_and_minimum_sample(self):
        predictor = Predictor(Repository(self.root)); stats = predictor.version('v1').spec['stats']
        context = predictor.context('S1_game_1', {**stats, 'soloq': {'fade_games': 20, 'min_games': 30}})
        col = predictor.history.column
        self.assertEqual(context.soloq_games, 40); self.assertAlmostEqual(context.soloq_presence[col[AHRI]], 0.5)
        self.assertAlmostEqual(context.soloq_change[col[AHRI]], 0.5 - 0.1)  # no same-patch pro games yet: no fade
        self.assertAlmostEqual(context.soloq_change[col[AZIR]], 0.0 - 0.5)
        thin = predictor.context('S1_game_1', {**stats, 'soloq': {'fade_games': 20, 'min_games': 50}})
        self.assertEqual((thin.soloq_presence, thin.soloq_change), ({}, {}))


if __name__ == '__main__': unittest.main()
