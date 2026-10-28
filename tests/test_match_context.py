import importlib.util
import unittest
from pathlib import Path
spec = importlib.util.spec_from_file_location('context', Path(__file__).resolve().parents[1]/'scripts/collect_match_context.py')
context = importlib.util.module_from_spec(spec); spec.loader.exec_module(context)

class MappingTests(unittest.TestCase):
    def setUp(self):
        self.rows=[{'date':'2024-01-01 01:00:00','teamname':'A', **{f'pick{i}':str(i) for i in range(1,6)}}, {'date':'2024-01-01 01:00:00','teamname':'B', **{f'pick{i}':str(i+5) for i in range(1,6)}}]
        self.game={'datetime_utc':'2024-01-01 01:05:00','team_blue':'A','team_red':'B','picks_blue':['5','4','3','2','1'],'picks_red':['10','9','8','7','6']}
    def test_exact_riot_game_id_cross_checked(self):
        self.assertEqual(context.join_game('id',self.rows,{'id':[self.game]},{}),(self.game,'exact_riot_game_id_cross_checked'))
    def test_exact_id_date_conflict_rejected(self):
        self.game['datetime_utc']='2024-01-02 01:05:00'
        self.assertEqual(context.join_game('id',self.rows,{'id':[self.game]},{}),(None,'exact_riot_game_id_conflict'))
    def test_exact_id_team_conflict_rejected(self):
        self.game['team_blue']='Other'
        self.assertIsNone(context.join_game('id',self.rows,{'id':[self.game]}, {})[0])
    def test_exact_id_champion_conflict_rejected(self):
        self.game['picks_blue'][0]='Other'
        self.assertIsNone(context.join_game('id',self.rows,{'id':[self.game]}, {})[0])
    def test_ambiguous_identity_not_verified(self):
        self.assertIsNone(context.join_game('id',self.rows,{}, {context.identity(self.rows):[self.game,self.game]})[0])
    def test_unique_identity_is_order_insensitive(self):
        self.assertIs(context.join_game('id',self.rows,{}, {context.identity(self.rows):[self.game]})[0], self.game)
if __name__=='__main__':unittest.main()
