import importlib.util
import sys
import unittest
from pathlib import Path
SCRIPTS=Path(__file__).resolve().parents[1]/'scripts'
sys.path.insert(0,str(SCRIPTS))
spec=importlib.util.spec_from_file_location('data_pages',SCRIPTS/'collect_leaguepedia_data_pages.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

PAGE='''== Week 1 ==
{{SetPatch|patch=26.14 |disabled= |hotfix= |footnote=}}
{{MatchSchedule|bestof=3 |team1=LGD |team2=EDG |team1score=2
|date=2026-07-22 |time=02:00 |qq=13366  |stream=https://lpl.qq.com
|game1={{MatchSchedule/Game
|blue=EDG |red=LGD |winner=2 |first_sel=LGD |ssel=EDG |pick_sel=LGD |first_pick=EDG |ff=
|riot_platform_game_id=
}}
|game2={{MatchSchedule/Game
|blue=LGD |red=EDG |winner=1 |first_pick=EDG
|riot_platform_game_id=
}}
}}
== Week 2 ==
{{SetPatch|patch=26.15 |disabled=Maokai, Yunara |hotfix=Aug 1 |footnote=}}
{{MatchSchedule|bestof=5 |team1=T1 |team2=GEN |date=2026-07-29
|game1={{MatchSchedule/Game
|blue=T1 |red=GEN |first_pick=T1
|riot_platform_game_id=LOLTMNT02_1
}}
}}
'''

class DataPageTests(unittest.TestCase):
    def test_setpatch_applies_to_following_games_only(self):
        games=m.parse_data_page(PAGE)
        self.assertEqual([g['game_number'] for g in games],[1,2,1])
        self.assertEqual(games[0]['setpatch']['disabled'],[]);self.assertEqual(games[1]['setpatch']['patch'],'26.14')
        self.assertEqual(games[2]['setpatch'],{'patch':'26.15','disabled':['Maokai','Yunara'],'hotfix':'Aug 1','footnote':None})
        self.assertEqual(games[0]['game']['first_sel'],'LGD');self.assertEqual(games[0]['match']['qq'],'13366')
        self.assertEqual(games[0]['match']['date'],'2026-07-22')  # parameters continue on following lines
    def test_links_by_ids_never_by_names(self):
        games=m.parse_data_page(PAGE)
        oe={'13366-13366_game_1','13366-13366_game_2','LOLTMNT02_1'}
        self.assertEqual([m.link(g,oe) for g in games],[('13366-13366_game_1','lpl_qq_series_id'),('13366-13366_game_2','lpl_qq_series_id'),('LOLTMNT02_1','riot_platform_game_id')])
        self.assertEqual(m.link(games[2],set()),(None,None))
    def test_game_on_same_line_as_match_parameters(self):
        games=m.parse_data_page('{{SetPatch|patch=1 |disabled=Mel}}\n{{MatchSchedule|team1=A |team2=B |date=2025-10-14 |game1={{MatchSchedule/Game\n|riot_platform_game_id=X\n}}\n}}\n')
        self.assertEqual(len(games),1);self.assertEqual(games[0]['match']['date'],'2025-10-14');self.assertEqual(games[0]['game']['riot_platform_game_id'],'X')
    def test_game_before_any_setpatch_has_none(self):
        games=m.parse_data_page('{{MatchSchedule|team1=A |team2=B |qq=1\n|game1={{MatchSchedule/Game\n|blue=A |red=B\n}}\n')
        self.assertIsNone(games[0]['setpatch'])
if __name__=='__main__':unittest.main()
