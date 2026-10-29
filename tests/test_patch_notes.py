"""Patch-note parsing, direction votes and the point-in-time 'fresh changes' window."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

from lolbp.patches import PatchNotes, order_key
from lolbp.predict import Predictor
from lolbp.repository import Repository

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import CHAMPS, GAMES, build_fixture  # noqa: E402

spec = importlib.util.spec_from_file_location('patches', Path(__file__).resolve().parents[1] / 'scripts/collect_leaguepedia_patches.py')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
collector = importlib.util.module_from_spec(spec); spec.loader.exec_module(collector)

PAGE = """== Champions ==
{{pnb|date=2026-01-22|champion=Aatrox
|context=Aatrox has struggled to find a place on the Rift, so we're giving him additional power.
|changes={{pai|Deathbringer Stance|}}
* '''Damage''': 4-8% ⇒ '''4-10%'''
}}
{{pnb|date=2026-01-22|champion=Malphite
|context=Malphite is still overperforming.
|changes={{pai|Ground Slam|}}
* '''Damage''': 80 / 120 / 160 ⇒ '''60 / 95 / 130'''
* '''Cooldown''': 7 ⇒ '''8'''
}}
{{pnb|date=2026-01-22|item=Bandlepipes|changes=* x ⇒ y}}
"""


class ParsingTests(unittest.TestCase):
    def test_blocks_fields_and_votes(self):
        found = [collector.fields(b) for b in collector.blocks(PAGE)]
        self.assertEqual([f.get('champion') for f in found], ['Aatrox', 'Malphite', None])
        self.assertIn('{{pai|Ground Slam|}}', found[1]['changes'])
        self.assertEqual(collector.classify(found[0]['context'], found[0]['changes'])[:2], ('buff', 'context'))
        self.assertEqual(collector.classify(found[1]['context'], found[1]['changes'])[0], 'nerf')
        self.assertEqual(dict(collector.number_votes("* '''Cooldown''': 10 ⇒ '''8'''\n* '''Mana Cost''': 50 ⇒ '''60'''")), {'buff': 1, 'nerf': 1})
        self.assertEqual(collector.classify('', "* '''Damage''': 10 ⇒ 12")[:2], ('buff', 'numbers'))
        self.assertEqual(collector.classify('', '')[:2], ('adjust', 'none'))

    def test_patch_order(self):
        names = ['26.01', '25.04', '25.S1.3', '25.S1.1', '25.24']
        self.assertEqual(sorted(names, key=order_key), ['25.S1.1', '25.S1.3', '25.04', '25.24', '26.01'])


class FreshWindowTests(unittest.TestCase):
    def test_skipped_patches_count_and_later_mid_patch_updates_do_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            history = [{'gameid': 'H1_game_1', 'date': '2025-05-01 10:00:00', 'number': '1', 'champions': CHAMPS[:20], 'patch': '15.09'}]
            build_fixture(root, history + [{**g, 'patch': '15.11'} for g in GAMES], models=True)
            azir, ahri, corki = (str(i) for i in (268, 103, 42))
            records = [{'patch': '25.09', 'date': '2025-04-20', 'champion_id': ahri, 'direction': 'buff', 'context': ''},
                       {'patch': '25.10', 'date': '2025-05-10', 'champion_id': azir, 'direction': 'nerf', 'context': 'too strong in pro play'},
                       {'patch': '25.11', 'date': '2025-05-25', 'champion_id': azir, 'direction': 'nerf', 'context': ''},
                       {'patch': '25.11', 'date': '2025-07-01', 'champion_id': corki, 'direction': 'buff', 'context': ''}]
            (root / 'data/curated/patch_changes.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in records))
            (root / 'data/curated/patch_mapping.json').write_text(json.dumps({'mapping': {'15.09': {'leaguepedia': '25.09'}, '15.11': {'leaguepedia': '25.11'}}}))
            predictor = Predictor(Repository(root)); history_ = predictor.history
            fresh, covered = PatchNotes(root).fresh(history_, 'S1_game_1')
            self.assertEqual(covered, ['25.10', '25.11'])  # 25.10 was skipped by the league; 25.09 was already played
            col = history_.column
            self.assertEqual(fresh[col[azir]]['net'], -2); self.assertTrue(fresh[col[azir]]['pro'])
            self.assertNotIn(col[ahri], fresh); self.assertNotIn(col[corki], fresh)  # older patch; mid-patch block dated later
            context = predictor.context('S1_game_1', {**predictor.version('v1').spec['stats'], 'patch_notes': {'fade_games': 20}})
            self.assertAlmostEqual(context.freshness, 20 / 20)  # no earlier game on 15.11


if __name__ == '__main__': unittest.main()
