import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('sample',Path(__file__).resolve().parents[1]/'scripts/assemble_sample.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class SampleIndexTests(unittest.TestCase):
    def fixture(self):
        return {'oe_gameid':'g','patch_raw':'16.16','date_raw':'2026-09-13','league_raw':'LPL','teams':[{'picks_source_columns':['Ahri']}], 'quality':{'structural_valid':True,'bp_order_status':'unverified_source_columns'}}
    def test_wrong_version_never_joined(self):
        r=m.assemble_record(self.fixture(),{}, {'rules':[]},{'patches':[]},{'16.20.1':[{'id':103,'name':'Ahri','aliases':['Ahri']}]})
        self.assertFalse(r['patches']['static_available']);self.assertIsNone(r['champion_entities'][0]['champion_id'])
    def test_manifest_hash_conflict_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'file.json').write_text('{}')
            with self.assertRaises(ValueError):m.checked_output(root,'file.json','bad')
    def test_success_manifest_output_corruption_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);path=root/'data/curated/static/14.16.1/en_US/champion.json';path.parent.mkdir(parents=True)
            path.write_text('{}')
            with self.assertRaises(ValueError):
                m.load_catalogs(root,{'outputs':[{'path':str(path.relative_to(root)),'sha256':'wrong'}],'responses':[]})
    def test_failed_manifest_response_not_joined(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);path=root/'champion.json';path.write_text(json.dumps({'source_url':'u'}))
            with self.assertRaises(ValueError):
                m.load_catalogs(root,{'outputs':[{'path':'champion.json','sha256':m.digest(path)}],'responses':[{'url':'u','status':'failed'}]})
    def test_context_cannot_promote_unverified_bp(self):
        r=m.assemble_record(self.fixture(),{'evidence_status':'source_record_verified','bp_order_status':'verified'},{'rules':[]},{'patches':[]},{})
        self.assertTrue(r['readiness']['context']);self.assertFalse(r['readiness']['bp_verified']);self.assertFalse(r['readiness']['replay_ready'])
    def test_worlds_tag_regional_qualifier_does_not_apply_worlds_rule(self):
        game=self.fixture();game['league_raw']='WLDs'
        rule={'rule_id':'worlds_2026','competition':'Worlds','year':2026,'applicability_status':'observed'}
        result=m.applicable_rules(game,{'evidence_status':'source_record_verified','tournament':'LPL/2026 Season/Regional Qualifier'},{'rules':[rule]})
        self.assertEqual(result,[])
    def test_worlds_context_unverified_does_not_apply_worlds_rule(self):
        game=self.fixture();game['league_raw']='WLDs'
        rule={'rule_id':'worlds_2026','competition':'Worlds','year':2026,'applicability_status':'observed'}
        self.assertEqual(m.applicable_rules(game,{'tournament':'2026 Season World Championship/Play-In'},{'rules':[rule]}),[])
    def test_verified_flags_without_sequence_never_pass(self):
        game=self.fixture();game['quality']['bp_order_status']='verified'
        r=m.assemble_record(game,{'evidence_status':'source_record_verified','bp_order_status':'verified'},{'rules':[]},{'patches':[]},{})
        self.assertFalse(r['readiness']['bp_verified']);self.assertEqual(r['readiness']['bp_validator_status'],'not_run')
    def test_only_validator_verified_status_grants_bp(self):
        for status,expected in [('verified',True),('rejected',False),('no_independent_sequence',False)]:
            r=m.assemble_record(self.fixture(),{},{'rules':[]},{'patches':[]},{},{'status':status})
            self.assertIs(r['readiness']['bp_verified'],expected);self.assertEqual(r['readiness']['bp_validator_status'],status)
            self.assertEqual('bp_order_not_verified' in r['blockers'],not expected)
    def test_stale_validation_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'in.json').write_text('{}')
            (root/'v.json').write_text(json.dumps({'input_sha256':{'in.json':'stale'},'records':[]}))
            with self.assertRaises(ValueError):m.load_validation(root,'v.json',['in.json'])
            (root/'v.json').write_text(json.dumps({'input_sha256':{},'records':[]}))
            with self.assertRaises(ValueError):m.load_validation(root,'v.json',['in.json'])
    def test_unknown_rules_preserved(self):
        rule={'rule_id':'lpl_2026_unverified','competition':'LPL','year':2026,'applicability_status':'unknown'}
        r=m.assemble_record(self.fixture(),{}, {'rules':[rule]},{'patches':[]},{})
        self.assertEqual(r['candidate_rules'][0]['applicability_status'],'unknown');self.assertFalse(r['readiness']['rules_complete'])
    def test_casefold_unique_returns_numeric_id(self):
        self.assertEqual(m.resolve_name('ahri',[{'id':103,'name':'Ahri','aliases':['Ahri']}])['champion_id'],103)
    def test_unknown_entity_preserved(self):
        self.assertIsNone(m.resolve_name('Other',[{'id':103,'name':'Ahri','aliases':['Ahri']}])['champion_id'])
if __name__=='__main__':unittest.main()
