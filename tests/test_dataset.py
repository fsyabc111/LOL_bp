"""Offline quality-boundary checks; no upstream responses are mocked as accepted data."""
import contextlib
import copy
import csv
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from scripts.build_dataset import KEEP_FIELDS, METRICS, build, inspect_game, number


def fixture(gameid="fixture_1"):
    rows = []
    for side, side_index in (("Blue", 0), ("Red", 1)):
        champions = [f"fixture_{side}_{i}" for i in range(5)]
        for i, role in enumerate(("top", "jng", "mid", "bot", "sup", "team")):
            row = {key: "" for key in KEEP_FIELDS}
            row.update({"gameid": gameid, "league": "LCK", "date": "2024-09-01 12:00:00",
                        "patch": "14.16", "split": "Summer", "playoffs": "1", "game": "1",
                        "gamelength": "1800", "side": side, "position": role,
                        "participantid": str(side_index * 100 + i), "teamid": f"team_{side}",
                        "teamname": f"Team {side}", "result": str(side_index),
                        "datacompleteness": "complete"})
            if role == "team":
                row["firstPick"] = str(side_index)
                for n in range(1, 6):
                    row[f"pick{n}"] = champions[n - 1]
                    row[f"ban{n}"] = f"banned_{side}_{n}"
            else:
                row.update({"champion": champions[i], "playerid": f"player_{side}_{i}",
                            "playername": f"Player {side} {i}"})
                row.update({key: "1500" for key in METRICS})
            rows.append(row)
    return rows


class QualityBoundaries(unittest.TestCase):
    def test_red_first_is_valid_but_not_verified_replay(self):
        gate = inspect_game(fixture())
        self.assertTrue(gate["structural_valid"])
        self.assertTrue(gate["outcome_eligible"])
        self.assertEqual(gate["winner_side"], "Red")
        self.assertFalse(gate["replay_ready"])

    def test_possible_remake_not_a_double_loss(self):
        rows = fixture()
        for row in rows:
            row["result"] = "0"
            row["gamelength"] = "201"
        gate = inspect_game(rows)
        self.assertTrue(gate["structural_valid"])
        self.assertFalse(gate["outcome_eligible"])
        self.assertIsNone(gate["winner_side"])
        self.assertEqual(gate["timepoints"]["15"]["status"], "game_ended_before_cutoff")

    def test_complete_label_does_not_fill_missing_observation(self):
        rows = fixture()
        rows[0]["goldat15"] = ""
        gate = inspect_game(rows)
        self.assertEqual(gate["timepoints"]["15"]["status"], "missing_observations")
        self.assertEqual(gate["timepoints"]["10"]["status"], "observed")
        self.assertTrue(gate["outcome_eligible"])

    def test_unknown_ban_is_warning_not_fabricated_hero(self):
        rows = fixture()
        team = next(r for r in rows if r["position"] == "team")
        team["ban3"] = ""
        gate = inspect_game(rows)
        self.assertTrue(gate["structural_valid"])
        self.assertIn("unknown_ban_slots", [i["code"] for i in gate["issues"]])
        self.assertEqual(team["ban3"], "")

    def test_duplicate_record_is_not_silently_counted(self):
        rows = fixture()
        rows.append(copy.deepcopy(rows[0]))
        gate = inspect_game(rows)
        self.assertFalse(gate["structural_valid"])
        self.assertFalse(gate["outcome_eligible"])

    def test_bad_pick_set_and_contradictory_result_are_quarantined(self):
        rows = fixture()
        rows[0]["result"] = "1"
        next(r for r in rows if r["position"] == "team")["pick1"] = "nonexistent"
        gate = inspect_game(rows)
        codes = {i["code"] for i in gate["issues"]}
        self.assertIn("team_pick_set_mismatch", codes)
        self.assertIn("player_team_result_conflict", codes)
        self.assertFalse(gate["outcome_eligible"])

    def test_invalid_numbers_are_unknown_not_zero(self):
        for value in ("", "NaN", "inf", "-inf", "broken", None):
            self.assertIsNone(number(value))
        self.assertEqual(number("0"), 0)

    def test_identity_collisions_are_rejected(self):
        for mutation, code in (("player", "duplicate_player_identity"),
                               ("team", "invalid_opposing_team_identity"),
                               ("participant", "invalid_participant_ids")):
            rows = fixture()
            if mutation == "player":
                rows[1]["playerid"] = rows[0]["playerid"]
            elif mutation == "participant":
                rows[1]["participantid"] = rows[0]["participantid"]
            else:
                for row in rows:
                    row["teamid"] = "same_team"
            gate = inspect_game(rows)
            self.assertFalse(gate["outcome_eligible"])
            self.assertIn(code, {issue["code"] for issue in gate["issues"]})

    def test_invalid_timepoint_values_do_not_become_observed(self):
        for invalid in ("-100", "NaN", "garbled"):
            rows = fixture()
            rows[0]["goldat15"] = invalid
            gate = inspect_game(rows)
            self.assertEqual(gate["timepoints"]["15"]["status"], "invalid_observations")
            self.assertEqual(gate["timepoints"]["15"]["invalid_player_values"], 1)


class DatasetIntegration(unittest.TestCase):
    def write_csv(self, root, year, rows):
        path = root / f"{year}_LoL_esports_match_data_from_OraclesElixir.csv"
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=sorted(KEEP_FIELDS))
            writer.writeheader()
            writer.writerows(rows)
        return path

    def run_build(self, root):
        with contextlib.redirect_stdout(io.StringIO()):
            return build(root, root / "processed", root / "manifest.json", root / "report.md",
                         root / "candidates.jsonl", root / "context.jsonl")

    def test_source_immutability_traceability_and_gated_sqlite_views(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            good = fixture("good")
            bad = fixture("void")
            for row in bad:
                row["result"] = "0"
            source = self.write_csv(root, "2024", good + bad)
            before = source.read_bytes()
            audit = self.run_build(root)
            self.assertEqual(before, source.read_bytes())
            self.assertEqual(audit["target_games"], 2)
            db = sqlite3.connect(root / "processed/lol_bp.sqlite3")
            self.assertEqual(db.execute("SELECT gameid FROM outcome_games").fetchall(), [("good",)])
            self.assertEqual(db.execute("SELECT COUNT(*) FROM player_games").fetchone()[0], 20)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM games WHERE replay_ready=1").fetchone()[0], 0)
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
            origin = db.execute("SELECT source_record_number FROM player_games WHERE gameid='good' ORDER BY source_record_number LIMIT 1").fetchone()[0]
            self.assertEqual(origin, 2)
            db.close()
            candidate = json.loads((root / "candidates.jsonl").read_text().splitlines()[0])
            self.assertEqual(candidate["teams"][1]["first_pick_raw"], "1")

    def test_conflicting_files_fail_without_replacing_previous_database(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.write_csv(root, "2024", fixture())
            self.run_build(root)
            db = root / "processed/lol_bp.sqlite3"
            before = db.read_bytes()
            duplicate = fixture()
            for row in duplicate:
                row["date"] = "2025-09-01 12:00:00"
            self.write_csv(root, "2025", duplicate)
            with self.assertRaisesRegex(ValueError, "Duplicate gameid"):
                self.run_build(root)
            self.assertEqual(before, db.read_bytes())

    def test_ambiguous_context_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.write_csv(root, "2024", fixture())
            (root / "context.jsonl").write_text('{"oe_gameid":"fixture_1"}\n' * 2)
            with self.assertRaisesRegex(ValueError, "Duplicate context"):
                self.run_build(root)


if __name__ == "__main__":
    unittest.main()
