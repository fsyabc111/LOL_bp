import importlib.util
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
spec=importlib.util.spec_from_file_location('pb',Path(__file__).resolve().parents[1]/'scripts/collect_leaguepedia_pb.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

HEADER=['Phase','Team1','Team2','Score','Winner','Patch','T1B1','T2B1','T1B2','T2B2','T1B3','T2B3','T1P1','T2P1-2','T1P2-3','T2P3',
        'T2B4','T1B4','T2B5','T1B5','T2P4','T1P4-5','T2P5','SB','VOD']
def champ(name): return f'<span class="pbh-cn" data-champion="{name.lower()}"><span title="{name}" class="sprite champion-sprite"></span></span>'
def table(team1_side='red',overrides=None):
    other='blue' if team1_side=='red' else 'red'
    cells={'Phase':'<td>Finals</td>','Team1':f'<td title="Team A" class="pbh-{team1_side}">A</td>','Team2':f'<td title="Team B" class="pbh-{other}">B</td>',
           'Score':'<td>3 - 1</td>','Winner':'<td>A</td>','Patch':'<td>26.20</td>','SB':'<td><a href="/sb">SB</a></td>','VOD':'<td></td>'}
    for column,(steps,team,_) in m.COLUMNS.items():
        side=team1_side if team=='A' else other
        cells[column]=f'<td class="pbh-{side}">'+''.join(champ(f'C{s}') for s in steps)+'</td>'
    cells.update(overrides or {})
    return ('<table><tr>'+''.join(f'<th>{h}</th>' for h in HEADER)+'</tr><tr>'+''.join(cells[h] for h in HEADER)+'</tr></table>')

class Response(io.BytesIO):
    status=200
    def __enter__(self): return self
    def __exit__(self,*a): return False

class LeaguepediaTests(unittest.TestCase):
    def test_columns_follow_snake_template_with_team1_as_first_selection(self):
        game=m.parse_page(table('red'))[0]
        self.assertEqual(game['errors'],[]);self.assertEqual(game['team1_side'],'Red')
        self.assertEqual([s['step'] for s in game['steps']],list(range(1,21)))
        self.assertEqual([(s['side'],s['action']) for s in game['steps'][:2]],[('Red','ban'),('Blue','ban')])
        self.assertEqual([s['champion'] for s in game['steps'] if s['step'] in (8,9)],['C8','C9'])
        self.assertEqual(game['steps'][12],{'step':13,'side':'Blue','action':'ban','champion':'C13'})
    def test_empty_ban_kept_as_null_and_missing_pick_is_error(self):
        game=m.parse_page(table(overrides={'T1B1':'<td class="pbh-red"></td>'}))[0]
        self.assertIsNone(game['steps'][0]['champion']);self.assertEqual(game['errors'],[])
        game=m.parse_page(table(overrides={'T2P1-2':'<td class="pbh-blue">'+champ('X')+'</td>'}))[0]
        self.assertIn('pick_cell_count:T2P1-2',game['errors'])
    def test_none_placeholder_sprite_is_empty_ban(self):
        none='<span class="pbh-cn" data-champion="none"><span title="None" class="sprite champion-sprite"></span></span>'
        game=m.parse_page(table(overrides={'T1B2':'<td class="pbh-red">'+none+'</td>'}))[0]
        self.assertIsNone(game['steps'][2]['champion']);self.assertEqual(game['errors'],[])
        game=m.parse_page(table(overrides={'T1P1':'<td class="pbh-red">'+none+'</td>'}))[0]
        self.assertIn('empty_pick:T1P1',game['errors'])
    def test_unknown_team_side_is_error(self):
        game=m.parse_page(table(overrides={'Team1':'<td title="A">A</td>'}))[0]
        self.assertEqual(game['errors'],['team_side_unknown'])
    def test_ratelimit_backoff_then_success_records_attempts(self):
        with tempfile.TemporaryDirectory() as d:
            bodies=[json.dumps({'error':{'code':'ratelimited'}}).encode(),json.dumps({'parse':{'revid':7,'text':{'*':''}}}).encode()]
            waits=[]
            record=m.fetch(Path(d),'T',opener=lambda *a,**k:Response(bodies.pop(0)),sleep=waits.append,backoff=1)
            self.assertEqual(record['status'],'success');self.assertEqual(record['revid'],7);self.assertEqual(waits,[1])
            self.assertEqual([a.get('api_error') for a in record['attempts']],['ratelimited',None])
            self.assertTrue((Path(d)/record['raw_path']).is_file())
    def test_http_error_fails_after_bounded_attempts(self):
        def opener(*a,**k): raise urllib.error.HTTPError('u',403,'Forbidden',None,None)
        record=m.fetch(Path('.'),'T',opener=opener,sleep=lambda s:None,attempts=2)
        self.assertEqual(record['status'],'failed');self.assertEqual(len(record['attempts']),2)
    def test_non_ratelimit_api_error_fails_immediately(self):
        record=m.fetch(Path('.'),'T',opener=lambda *a,**k:Response(json.dumps({'error':{'code':'missingtitle'}}).encode()),sleep=lambda s:None)
        self.assertEqual(record['status'],'failed');self.assertEqual(len(record['attempts']),1)
    def test_alias_normalisation(self):
        aliases={'monkeyking':'62','wukong':'62'}
        self.assertEqual(m.name_key('MonkeyKing',aliases),m.name_key('Wukong',aliases))
        self.assertEqual(m.name_key("Kai'Sa",{}),m.name_key('KaiSa',{}))
if __name__=='__main__':unittest.main()
