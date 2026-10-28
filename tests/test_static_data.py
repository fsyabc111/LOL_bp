import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import io

spec = importlib.util.spec_from_file_location('static_data', Path(__file__).resolve().parents[1] / 'scripts/collect_static_data.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class StaticDataTests(unittest.TestCase):
    def test_embedded_version_must_match_pinned_target(self):
        with self.assertRaisesRegex(ValueError, 'version mismatch'):
            m.validate({'version': '16.21.1', 'data': {'Ahri': {}}}, 'champion', '16.20.1')

    def test_skill_placeholders_and_zero_effects_are_not_invented_formulas(self):
        skill = {'tooltip': 'Deals {{ totaldamage }} and charms for {{ charmduration }}.', 'effectBurn': [None, '0'], 'cooldown': [12, 11], 'vars': []}
        row = m.normalize_spell(skill, 'E')
        self.assertEqual(row['tooltip'], skill['tooltip'])
        self.assertEqual(row['effectBurn'], [None, '0'])
        self.assertEqual(row['unresolved_placeholders'], ['charmduration', 'totaldamage'])
        self.assertEqual(row['formula_resolution'], 'unknown')
        self.assertEqual(row['cooldown'], [12, 11])

    def test_localized_names_join_by_numeric_identity(self):
        entities = []
        for name in ('Ahri', '九尾妖狐'):
            entities.append(m.normalize({'data': {'Ahri': {'key': '103', 'name': name, 'stats': {'hp': 590, 'hpperlevel': 104}}}}, 'champion', 'fixture')[0])
        self.assertEqual(entities[0]['id'], entities[1]['id'])
        self.assertEqual(entities[1]['source_key'], 'Ahri')
        self.assertIn('九尾妖狐', entities[1]['aliases'])
        self.assertEqual(entities[0]['stats']['hpperlevel'], 104)

    def test_native_item_and_summoner_effect_fields_survive_normalization(self):
        for kind, key, entity in [('item', '3152', {'name': 'Fixture item', 'effect': {'Effect1Amount': '135'}}), ('summoner', 'SummonerFlash', {'key': '4', 'name': 'Flash', 'effect': [None, [400]]})]:
            row = m.normalize({'data': {key: entity}}, kind, 'en_US')[0]
            self.assertEqual(row['effect'], entity['effect'])

    def test_detail_cannot_silently_return_another_champion(self):
        with self.assertRaisesRegex(ValueError, 'unexpected champion'):
            m.validate({'version': '14.16.1', 'data': {'Azir': {'key': '268', 'stats': {}, 'spells': [{}] * 4}}}, 'champion', '14.16.1', 'Ahri')

    def test_bad_cache_is_failed_without_network_success_claim(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / 'data/raw/static/versions.json'
            path.parent.mkdir(parents=True)
            path.write_text('["14.16.1"]')
            collector = m.Collector(root=root, attempts=1)
            self.assertIsNone(collector.fetch('versions.json', 'versions'))
            self.assertEqual(collector.records[0]['status'], 'failed')
            self.assertIn('provenance missing', collector.records[0]['error'])

    def test_offline_missing_cache_does_not_open_network(self):
        with tempfile.TemporaryDirectory() as folder:
            collector = m.Collector(root=Path(folder), offline=True)
            with patch.object(m, 'urlopen', side_effect=AssertionError('network forbidden')) as network:
                self.assertIsNone(collector.fetch('versions.json', 'versions'))
            network.assert_not_called()
            self.assertEqual(collector.records[0]['attempts'], 1)

    def test_failed_attempt_has_no_retrieved_timestamp(self):
        with tempfile.TemporaryDirectory() as folder:
            collector = m.Collector(root=Path(folder), offline=True)
            collector.fetch('versions.json', 'versions')
            self.assertIn('attempted_at', collector.records[0])
            self.assertNotIn('retrieved_at', collector.records[0])

    def test_failed_refresh_removes_previous_curated_and_manifest_excludes_it(self):
        class FailedCollector(m.Collector):
            def fetch(self, relative, kind, version=None, champion=None):
                if kind == 'versions':
                    return ['14.16.1']
                self.records.append({'status': 'failed', 'url': relative})
                return None
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            old = root / 'data/curated/static/14.16.1/en_US/champion.json'
            old.parent.mkdir(parents=True)
            old.write_text('{"old":true}')
            with patch.object(m, 'ROOT', root), patch.object(m, 'Collector', FailedCollector), patch('sys.argv', ['collector', '--refresh', '--versions', '14.16.1', '--champions', 'Ahri']):
                self.assertEqual(m.main(), 1)
            self.assertFalse(old.exists())
            self.assertEqual(__import__('json').loads((root / 'data/manifests/static-data.json').read_text())['outputs'], [])

    def test_output_fingerprint_binds_exact_raw_and_curated(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            target = Path('data/curated/static/test.json')
            m.write_json(root / target, {'entities': []})
            raw = root / 'data/raw/static/source.json'
            raw.parent.mkdir(parents=True)
            raw.write_bytes(b'{"data":[]}')
            record = m.output_record(root, target, [], 'source.json')
            self.assertEqual(record['sha256'], __import__('hashlib').sha256((root / target).read_bytes()).hexdigest())
            self.assertEqual(record['source_snapshot_sha256'], __import__('hashlib').sha256(raw.read_bytes()).hexdigest())

    def test_non_2xx_and_invalid_json_are_never_success(self):
        class Response(io.BytesIO):
            status = 503
            headers = {}
        with tempfile.TemporaryDirectory() as folder:
            collector = m.Collector(root=Path(folder), attempts=1)
            with patch.object(m, 'urlopen', return_value=Response(b'{"error":"unavailable"}')):
                self.assertIsNone(collector.fetch('versions.json', 'versions'))
            self.assertEqual(collector.records[0]['status'], 'failed')
            self.assertIn('non-2xx', collector.records[0]['error'])
        with tempfile.TemporaryDirectory() as folder:
            response = Response(b'{broken')
            response.status = 200
            collector = m.Collector(root=Path(folder), attempts=1)
            with patch.object(m, 'urlopen', return_value=response):
                self.assertIsNone(collector.fetch('versions.json', 'versions'))
            self.assertEqual(collector.records[0]['status'], 'failed')
            self.assertTrue((Path(folder) / 'data/raw/static/versions.json').exists())

    def test_runes_url_only_version_status_is_honest(self):
        with self.assertRaises(ValueError):
            m.validate({'error': 'not found'}, 'runesReforged', '14.16.1')


if __name__ == '__main__':
    unittest.main()
