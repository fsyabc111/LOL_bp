import unittest

from lolbp import draft

TEMPLATE={'actions':[{'step':i+1,'action':'ban' if c=='b' else 'pick','draft_team':t}
    for i,(c,t) in enumerate(['bA','bB','bA','bB','bA','bB','pA','pB','pB','pA','pA','pB','bB','bA','bB','bA','pB','pA','pA','pB'])]}

def rules(**kw):
    return draft.DraftRules(slots=draft.slots_from_template(TEMPLATE,kw.pop('first','Blue')),**kw)

def fill(r,champions):
    actions=()
    for c in champions: actions=draft.apply(r,actions,c)
    return actions

class DraftEngineTests(unittest.TestCase):
    def test_first_selection_side_maps_team_a(self):
        r=rules(first='Red')
        self.assertEqual(draft.next_slot(r,()),draft.Slot(1,'Red','ban'))
        self.assertEqual([s.side for s in r.slots[6:9]],['Red','Blue','Blue'])
    def test_full_draft_completes_and_summarises(self):
        r=rules();actions=fill(r,[str(i) for i in range(1,21)])
        s=draft.summary(r,actions)
        self.assertTrue(s['complete']);self.assertIsNone(s['next'])
        self.assertEqual([p['champion'] for p in s['board']['Blue']['picks']],['7','10','11','18','19'])
        with self.assertRaises(draft.IllegalAction) as e:draft.apply(r,actions,'99')
        self.assertEqual(e.exception.reasons,['draft_complete'])
    def test_reuse_in_same_game_blocked(self):
        r=rules();actions=fill(r,['1'])
        self.assertEqual(draft.check(r,actions,'1'),(['already_used_this_game'],[]))
    def test_empty_ban_allowed_empty_pick_blocked(self):
        r=rules();actions=fill(r,[None,None,None,None,None,None])
        self.assertEqual(draft.check(r,actions,None),(['empty_pick'],[]))
        self.assertEqual(draft.check(r,actions,'5'),([],[]))
    def test_fearless_blocks_pick_but_only_warns_ban(self):
        r=rules(fearless=draft.FEARLESS_PICKS_BOTH,consumed=frozenset({'9'}))
        self.assertEqual(draft.check(r,(),'9'),([],['ban_wasted_on_consumed']))
        actions=fill(r,['1','2','3','4','5','6'])
        self.assertEqual(draft.check(r,actions,'9'),(['fearless_consumed'],[]))
        self.assertEqual(draft.check(rules(consumed=frozenset({'9'})),actions,'9'),([],[]))
    def test_disabled_and_unknown_champions_blocked(self):
        r=rules(disabled=frozenset({'7'}),known=frozenset({'7','8'}))
        self.assertEqual(draft.check(r,(),'7')[0],['event_disabled'])
        self.assertEqual(draft.check(r,(),'99')[0],['unknown_champion'])
    def test_replay_reports_but_keeps_illegal_history(self):
        r=rules(fearless=draft.FEARLESS_PICKS_BOTH,consumed=frozenset({'7'}))
        steps=[{'step':s.step,'side':s.side,'action':s.action,'champion':str(s.step)} for s in r.slots]
        actions,findings=draft.replay(r,steps)
        self.assertEqual(len(actions),20);self.assertEqual(findings,[{'step':7,'reasons':['fearless_consumed'],'warnings':[]}])
    def test_replay_stops_on_template_mismatch(self):
        r=rules();steps=[{'step':1,'side':'Red','action':'ban','champion':'1'}]
        actions,findings=draft.replay(r,steps)
        self.assertEqual(actions,());self.assertEqual(findings[0]['reasons'],['template_mismatch'])
    def test_availability_lists_only_restricted(self):
        r=rules();actions=fill(r,['1'])
        self.assertEqual(draft.availability(r,actions,['1','2']),{'1':{'reasons':['already_used_this_game'],'warnings':[]}})
if __name__=='__main__':unittest.main()
