import copy
import importlib.util
import unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('validate_bp',Path(__file__).resolve().parents[1]/'scripts/validate_bp.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

TEMPLATE={'id':'snake_20','actions':[{'step':i+1,'action':'ban' if c=='b' else 'pick','draft_team':t}
    for i,(c,t) in enumerate(['bA','bB','bA','bB','bA','bB','pA','pB','pB','pA','pA','pB','bB','bA','bB','bA','pB','pA','pA','pB'])]}
def observed(value): return {'value':value,'status':'observed'}
def rules(team_a='blue',fearless=None):
    rule={'rule_id':'r','competition':'LCK','year':2026,'applicability_status':'observed',
          'draft_template':observed('snake_20'),'draft_team_A':observed(team_a)}
    if fearless: rule['cross_game_ban_scope']=observed(fearless)
    return {'templates':[TEMPLATE],'rules':[rule]}
def game(gameid='g2',blue_first='1',prefix=''):
    teams=[]
    for side,first in (('Blue',blue_first),('Red','0' if blue_first=='1' else '1')):
        teams.append({'side':side,'first_pick_raw':first,'picks_source_columns':[f'{prefix}{side}P{i}' for i in range(5)],
                      'bans_source_columns':[f'{prefix}{side}B{i}' for i in range(5)]})
    return {'oe_gameid':gameid,'date_raw':'2026-09-01','league_raw':'LCK','teams':teams,'quality':{'structural_valid':True}}
CONTEXT={'series_id':'s','game_number':'2'}
SOURCE={'source_type':'vod_manual','locator':'vod t=1:02:03','url':'https://example.invalid/vod'}

def evidence(g,team_a='Blue'):
    side={'A':team_a,'B':'Red' if team_a=='Blue' else 'Blue'}
    return {'oe_gameid':g['oe_gameid'],'source':dict(SOURCE),'steps':m.oe_hypothesis(g,TEMPLATE,side)}

class BPValidatorTests(unittest.TestCase):
    def run_one(self,g,ev,rule_set=None,prior=()):
        return m.validate_game(g,CONTEXT,rule_set or rules(),[],list(prior),ev)
    def test_independent_consistent_sequence_verified(self):
        g=game();r=self.run_one(g,[evidence(g)])
        self.assertEqual(r['status'],'verified');self.assertTrue(r['evidence']['oe_column_order_agreement']['all_steps_equal'])
    def test_order_disagreement_with_oe_columns_reported_not_rejected(self):
        g=game();ev=evidence(g);steps=ev['steps']
        steps[6]['champion'],steps[9]['champion']=steps[9]['champion'],steps[6]['champion']
        r=self.run_one(g,[ev])
        self.assertEqual(r['status'],'verified');self.assertEqual(r['evidence']['oe_column_order_agreement']['differing_steps'],[7,10])
    def test_oe_columns_never_self_verify(self):
        g=game();r=self.run_one(g,[])
        self.assertEqual(r['status'],'no_independent_sequence');self.assertEqual(r['oe_column_hypothesis']['status'],'hypothesis_unverified')
        ev=evidence(g);ev['source']['source_type']='oe_columns'
        r=self.run_one(g,[ev]);self.assertEqual(r['status'],'rejected')
        self.assertIn('source_not_independent',[e['code'] for e in r['evidence']['errors']])
    def test_missing_locator_rejected(self):
        g=game();ev=evidence(g);del ev['source']['locator']
        self.assertIn('source_locator_missing',[e['code'] for e in self.run_one(g,[ev])['evidence']['errors']])
    def test_wrong_acting_team_rejected(self):
        g=game();ev=evidence(g);ev['steps'][0]['side']='Red'
        r=self.run_one(g,[ev]);self.assertEqual(r['status'],'rejected')
        self.assertIn('template_mismatch',[e['code'] for e in r['evidence']['errors']])
    def test_step_count_and_empty_pick_rejected(self):
        g=game();ev=evidence(g);ev['steps']=ev['steps'][:19]
        self.assertEqual(self.run_one(g,[ev])['evidence']['errors'][0]['code'],'step_count_mismatch')
        ev=evidence(g);ev['steps'][6]['champion']=None
        self.assertIn('empty_pick',[e['code'] for e in self.run_one(g,[ev])['evidence']['errors']])
    def test_duplicate_and_set_mismatch_rejected(self):
        g=game();ev=evidence(g);ev['steps'][1]['champion']=ev['steps'][0]['champion']
        codes=[e['code'] for e in self.run_one(g,[ev])['evidence']['errors']]
        self.assertIn('duplicate_champion_in_draft',codes);self.assertIn('ban_set_differs_from_oe',codes)
    def test_empty_ban_must_match_oe_empty_slot(self):
        g=game();g['teams'][0]['bans_source_columns'][4]=None
        ev=evidence(g);self.assertEqual(self.run_one(g,[ev])['status'],'verified')
        ev['steps'][4]['champion']='Something'
        self.assertEqual(self.run_one(g,[ev])['status'],'rejected')
    def test_first_pick_team_mapping_from_rule(self):
        g=game(blue_first='0');rule_set=rules('first_pick')
        self.assertEqual(m.draft_setup(g,{},rule_set)[1],{'A':'Red','B':'Blue'})
        self.assertEqual(self.run_one(g,[evidence(g,'Red')],rule_set)['status'],'verified')
        self.assertEqual(self.run_one(g,[evidence(g,'Blue')],rule_set)['status'],'rejected')
        g['teams'][1]['first_pick_raw']='0'
        self.assertEqual(m.draft_setup(g,{},rule_set)[3],['first_pick_team_unknown'])
    def test_unknown_or_inapplicable_template_blocks(self):
        g=game();rule_set=rules();rule_set['rules'][0]['draft_template']={'value':None,'status':'unknown'}
        r=self.run_one(g,[evidence(g)],rule_set)
        self.assertEqual(r['status'],'blocked');self.assertIn('draft_template_unknown',r['blockers']);self.assertIsNone(r['oe_column_hypothesis'])
        rule_set=rules();rule_set['rules'][0]['applicability_status']='unknown'
        self.assertEqual(self.run_one(g,[evidence(g)],rule_set)['status'],'blocked')
    def test_conflicting_evidence_not_resolved(self):
        g=game();self.assertEqual(self.run_one(g,[evidence(g),evidence(g)])['status'],'conflicting_evidence_records')
    def test_fearless_violation_and_consumed_ban(self):
        g=game();prior=game('g1');prior['teams'][0]['picks_source_columns'][0]='RedP0'
        prior['teams'][1]['picks_source_columns'][0]='BlueB0'
        r=self.run_one(g,[evidence(g)],rules(fearless='picks_by_both_teams_for_remainder_of_match'),[(1,prior)])
        self.assertEqual(r['cross_game']['status'],'violation');self.assertEqual(r['status'],'rejected')
        self.assertEqual(r['cross_game']['bans_on_consumed'],['name:blueb0'])
    def test_fearless_requires_all_prior_games(self):
        g=game();r=self.run_one(g,[evidence(g)],rules(fearless='picks_by_both_teams_for_remainder_of_match'))
        self.assertEqual(r['cross_game'],{'status':'prior_games_missing','missing_game_numbers':[1]})
    def test_unknown_cross_game_rule_only_describes_repeats(self):
        g=game();prior=copy.deepcopy(g)
        r=self.run_one(g,[evidence(g)],rules(),[(1,prior)])
        self.assertEqual(r['cross_game']['status'],'rule_unknown');self.assertEqual(len(r['cross_game']['observed_pick_repeats']),10)
        self.assertEqual(r['status'],'verified')
    def test_champion_alias_resolution_matches_static_identity(self):
        champions=[{'id':62,'name':'Wukong','aliases':['MonkeyKing']}]
        self.assertEqual(m.champion_key('MonkeyKing',champions),m.champion_key('wukong',champions))
        self.assertEqual(m.champion_key('Xin Zhao',[]),m.champion_key('XinZhao',[]))
if __name__=='__main__':unittest.main()
