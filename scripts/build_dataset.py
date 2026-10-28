#!/usr/bin/env python3
"""Audit local OE-shaped CSVs and build a conservative, traceable analysis dataset.

No network calls, inferred series IDs, filled-in bans, or verified BP sequences.
Python 3.9+, standard library only. Original CSV files are never modified.
"""
import argparse
import collections
import csv
import hashlib
import json
import math
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
TARGET_LEAGUES = {"LPL", "LCK", "WLDs"}
ROLES = {"top", "jng", "mid", "bot", "sup"}
SIDES = {"Blue", "Red"}
EXPECTED_SLOTS = {(side, role) for side in SIDES for role in ROLES | {"team"}}
REQUIRED = {"gameid", "league", "date", "patch", "position", "side", "participantid",
            "champion", "playerid", "teamid", "result", "gamelength", "firstPick"}
METRICS = [f"{metric}at{minute}" for minute in (10, 15, 20, 25)
           for metric in ("gold", "xp", "cs")]
STAT_FIELDS = (METRICS + [f"{metric}diffat{minute}" for minute in (10, 15, 20, 25)
                         for metric in ("gold", "xp", "cs")]
               + ["kills", "deaths", "assists", "damagetochampions", "totalgold", "total cs"])
KEEP_FIELDS = (REQUIRED | set(STAT_FIELDS) | {"split", "playoffs", "game", "playername",
               "teamname", "datacompleteness", "url"}
               | {f"{kind}{n}" for kind in ("pick", "ban") for n in range(1, 6)})


def dump_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    tmp.replace(path)


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def number(value):
    """Missing/invalid numbers stay unknown; never treat an empty result as a loss."""
    if value is None or not str(value).strip():
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def text_or_none(value):
    return value if value and value.strip() else None


def inspect_game(rows):
    """Return gates separately for structure, outcomes, timepoints, and draft replay."""
    issues = []

    def issue(code, severity="error", detail=None):
        issues.append({"code": code, "severity": severity, "detail": detail})

    players = [r for r in rows if r.get("position") != "team"]
    teams = [r for r in rows if r.get("position") == "team"]
    slots = [(r.get("side"), r.get("position")) for r in rows]
    if len(rows) != 12 or set(slots) != EXPECTED_SLOTS:
        issue("invalid_participant_structure", detail={"players": len(players), "teams": len(teams)})
    if len(set(slots)) != len(slots):
        issue("duplicate_side_position")
    for key in ("league", "date", "patch", "split", "playoffs", "game", "gamelength"):
        if len({r.get(key, "") for r in rows}) != 1:
            issue("conflicting_game_field", detail=key)
    if any(not r.get("patch") for r in rows):
        issue("missing_patch")
    if any(not r.get("date") for r in rows):
        issue("missing_date")
    if any(not r.get("champion") or not r.get("playerid") or not r.get("teamid") for r in players):
        issue("missing_participant_identity")
    if len({r.get("playerid") for r in players}) != len(players):
        issue("duplicate_player_identity")
    if any(not r.get("participantid") for r in rows) or len({r.get("participantid") for r in rows}) != len(rows):
        issue("invalid_participant_ids")
    if any(not r.get("teamid") for r in teams) or len({r.get("teamid") for r in teams}) != len(teams):
        issue("invalid_opposing_team_identity")
    champions = [r.get("champion") for r in players]
    if len(set(champions)) != len(champions):
        issue("duplicate_champion")
    for team in teams:
        side = team.get("side")
        members = [r for r in players if r.get("side") == side]
        picks = [team.get(f"pick{i}", "") for i in range(1, 6)]
        if not all(picks):
            issue("missing_team_pick", detail=side)
        elif collections.Counter(picks) != collections.Counter(r.get("champion") for r in members):
            issue("team_pick_set_mismatch", detail=side)
        if any(r.get("teamid") != team.get("teamid") for r in members):
            issue("team_identity_conflict", detail=side)
        empty_bans = [i for i in range(1, 6) if not team.get(f"ban{i}")]
        if empty_bans:
            issue("unknown_ban_slots", "warning", {"side": side, "slots": empty_bans})
    first_values = [number(r.get("firstPick")) for r in teams]
    if len(first_values) != 2 or sorted(v for v in first_values if v is not None) != [0, 1]:
        issue("invalid_first_pick_flags")
    structural_valid = not any(i["severity"] == "error" for i in issues)

    results = [number(r.get("result")) for r in teams]
    valid_outcome = len(results) == 2 and sorted(v for v in results if v is not None) == [0, 1]
    if not valid_outcome:
        issue("no_unique_recorded_winner", detail="Possible remake/void/missing result; not adjudicated.")
    for team in teams:
        if any(number(r.get("result")) != number(team.get("result")) for r in players
               if r.get("side") == team.get("side")):
            issue("player_team_result_conflict")
            valid_outcome = False
    duration = number(rows[0].get("gamelength"))
    if duration is None or duration <= 0:
        issue("invalid_duration")
        valid_outcome = False
    winner = next((r.get("side") for r in teams if number(r.get("result")) == 1), None) if valid_outcome else None
    timepoints = {}
    for minute in (10, 15, 20, 25):
        fields = [f"{kind}at{minute}" for kind in ("gold", "xp", "cs")]
        values = [r.get(f) for r in players for f in fields]
        missing = sum(not str(value or "").strip() for value in values)
        invalid = sum(bool(str(value or "").strip()) and (number(value) is None or number(value) < 0)
                      for value in values)
        if duration is None:
            status = "unknown_duration"
        elif duration < minute * 60:
            status = "game_ended_before_cutoff"
        elif invalid:
            status = "invalid_observations"
        elif missing or len(players) != 10:
            status = "missing_observations"
        else:
            status = "observed"
        timepoints[str(minute)] = {"status": status, "missing_player_values": missing,
                                  "invalid_player_values": invalid}
    return {"structural_valid": structural_valid,
            "outcome_eligible": structural_valid and valid_outcome,
            "winner_side": winner, "timepoints": timepoints,
            "bp_order_status": "unverified_source_columns", "replay_ready": False,
            "issues": issues}


def load_context(path):
    if not path.exists():
        return {}
    context = {}
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                row = json.loads(line)
                key = row.get("oe_gameid")
                if key:
                    if key in context:
                        raise ValueError(f"Duplicate context for {key}; resolve conflict explicitly")
                    context[key] = row
    return context


SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE sources (source_id TEXT PRIMARY KEY, filename TEXT NOT NULL, sha256 TEXT NOT NULL,
  provenance_status TEXT NOT NULL, metadata_json TEXT NOT NULL);
CREATE TABLE games (gameid TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources,
  league_raw TEXT, split_raw TEXT, playoffs_raw TEXT, date_raw TEXT, patch_raw TEXT,
  game_number_raw TEXT, duration_seconds REAL, structural_valid INTEGER NOT NULL,
  outcome_eligible INTEGER NOT NULL, winner_side TEXT, replay_ready INTEGER NOT NULL,
  bp_order_status TEXT NOT NULL, timepoints_json TEXT NOT NULL);
CREATE TABLE player_games (gameid TEXT NOT NULL REFERENCES games, source_record_number INTEGER NOT NULL,
  side TEXT, final_role TEXT, player_id TEXT, player_name TEXT, team_id TEXT, team_name TEXT,
  champion_name_raw TEXT, result REAL, stats_json TEXT NOT NULL,
  PRIMARY KEY(gameid, source_record_number));
CREATE TABLE team_drafts (gameid TEXT NOT NULL REFERENCES games, source_record_number INTEGER NOT NULL,
  side TEXT, team_id TEXT, team_name TEXT, first_pick_raw TEXT, result REAL,
  picks_raw_json TEXT NOT NULL, bans_raw_json TEXT NOT NULL,
  PRIMARY KEY(gameid, source_record_number));
CREATE TABLE issues (gameid TEXT NOT NULL REFERENCES games, code TEXT NOT NULL,
  severity TEXT NOT NULL, detail_json TEXT);
CREATE TABLE match_context (gameid TEXT PRIMARY KEY REFERENCES games, context_json TEXT NOT NULL);
CREATE INDEX idx_games_scope ON games(league_raw, patch_raw, date_raw);
CREATE INDEX idx_player_history ON player_games(player_id, champion_name_raw);
CREATE VIEW outcome_games AS SELECT * FROM games WHERE outcome_eligible=1;
CREATE VIEW observed_15min_games AS SELECT * FROM games WHERE structural_valid=1
  AND json_extract(timepoints_json, '$.15.status')='observed';
"""


def json_compact(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def candidate(gameid, rows, gate, context):
    representative = rows[0]
    return {"oe_gameid": gameid, "league_raw": representative.get("league"),
            "date_raw": representative.get("date"), "patch_raw": representative.get("patch"),
            "source_id": representative["_source_id"],
            "source_record_numbers": [r["_record_number"] for r in rows],
            "sample_reason": "2024_lck_summer_playoffs" if representative["_source_year"] == "2024"
                and representative.get("league") == "LCK" else "cross_event_source_context",
            "quality": gate,
            "teams": [{"side": r.get("side"), "team_id": r.get("teamid"),
                       "team_name": r.get("teamname"), "first_pick_raw": r.get("firstPick"),
                       "picks_source_columns": [text_or_none(r.get(f"pick{i}")) for i in range(1, 6)],
                       "bans_source_columns": [text_or_none(r.get(f"ban{i}")) for i in range(1, 6)]}
                      for r in rows if r.get("position") == "team"],
            "historical_final_roles": [{"side": r.get("side"), "role": r.get("position"),
                       "player_id": r.get("playerid"), "player_name": r.get("playername"),
                       "champion": r.get("champion")}
                      for r in rows if r.get("position") != "team"],
            "feature_warning": "Final roles and results are post-draft labels, not current-BP inputs.",
            "context": context,
            "replay_blockers": ["BP column ordering not independently verified",
                                "Applicable series rules require explicit linkage"]}


def report_markdown(audit):
    lines = ["# 本地职业赛事数据审计", "", "由 `python3 scripts/build_dataset.py` 生成。原始 CSV 不修改。", "",
             "## 范围与证据边界", "",
             f"扫描全部年度文件 {audit['total_rows']:,} 行，规范化目标标签 {audit['target_games']:,} 小局。",
             "目标标签为 LPL、LCK、WLDs；标签数量不代表官方赛程完整率，WLDs 不直接等同世界赛正赛。",
             "文件来源仅由本地名称提示；尚未与发布者原件核对。哈希标识本地快照，不证明官方真实性。",
             "比赛 date 保留原值；本管道不自行假定时区。来源发布时间和历史可知时间未知。", "",
             "## 按年份与目标标签的覆盖", "",
             "| 年度 | 标签 | 小局 | 玩家行 | goldat15 空值 | 15分钟可观测小局 | 赛果可用小局 |",
             "| --- | --- | ---: | ---: | ---: | ---: | ---: |"]
    for group in audit["target_groups"]:
        lines.append(f"| {group['year']} | {group['league_raw']} | {group['games']} | {group['player_rows']} | "
                     f"{group['player_missing']['goldat15']} | {group['timepoint_status']['15'].get('observed', 0)} | "
                     f"{group['outcome_eligible_games']} |")
    lines += ["", "15分钟可观测要求十名玩家的经济、经验、补刀均有数值且比赛到达15分钟；不是效果验证。",
              "20/25分钟缺值区分比赛尚未到达截面与实际观测缺失，避免把短局当作数据采集失败。", "",
              "## 质量门槛", "",
              "- 阵容结构：每侧五个位置和一条队伍记录，英雄集合与队伍 picks 一致。",
              "- 赛果：结构可用且两队恰有一个胜者，玩家与队伍赛果一致；异常记录仍保留。",
              "- 时间截面：按指标检查，不因 datacompleteness=complete 自动通过。",
              "- 空 Ban：保留 unknown，未判定是漏记、主动空禁还是处罚。",
              "- firstPick 与地图 side 分开保存，不默认蓝方先选。",
              "- BP 重放：全部默认未验收；非空 pick 列不是已证明的全局行动顺序。",
              "- 历史最终分路只用于赛后标签；禁止泄露到当局 BP 决策特征。", "",
              "## 异常计数", "", "| 类型 | 数量 |", "| --- | ---: |"]
    for code, count in sorted(audit["issue_counts"].items()):
        lines.append(f"| `{code}` | {count} |")
    lines += ["", "具体 gameid、源记录号及全量覆盖见 `data/manifests/local-oe.json` 和本地 SQLite。", "",
              "## 代表样本", "",
              f"`data/curated/replay_candidates.jsonl` 共 {audit['candidate_games']} 小局。",
              f"主样本按 CSV 的 2024 / LCK / Summer / playoffs=1 筛选得到 {audit['primary_candidate_games']} 小局；补充有跨源上下文的代表比赛。",
              "该文件是待验收复盘候选集，不是通过逐手录像核验的黄金测试集。", "",
              "## 本地查询", "", "```sql",
              "SELECT league_raw, COUNT(*) FROM outcome_games GROUP BY league_raw;",
              "SELECT gameid, code, detail_json FROM issues WHERE severity = 'error';",
              "SELECT COUNT(*) FROM observed_15min_games;", "```", ""]
    return "\n".join(lines)


def build(input_dir, output_dir, manifest_path, report_path, candidate_path, context_path):
    paths = sorted(input_dir.glob("*_LoL_esports_match_data_from_OraclesElixir.csv"))
    if not paths:
        raise ValueError(f"No source CSVs in {input_dir}")
    context = load_context(context_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    db_path = output_dir / "lol_bp.sqlite3"
    temp_db = db_path.with_suffix(".sqlite3.tmp")
    if temp_db.exists():
        temp_db.unlink()
    conn = sqlite3.connect(temp_db)
    conn.executescript(SCHEMA)
    audit = {"schema_version": 1, "pipeline": "scripts/build_dataset.py", "total_rows": 0,
             "target_games": 0, "source_files": [], "target_groups": [],
             "issue_counts": collections.Counter(), "issue_examples": [],
             "scope": sorted(TARGET_LEAGUES), "known_limitations": [
                 "Local source authenticity and publisher retrieval dates unverified",
                 "League labels are not verified tournament or stage identities",
                 "Draft order and series-specific legality are not validated",
                 "Historical data availability times are unknown",
                 "No causal or recommendation-effectiveness claims"]}
    seen = set()
    candidates = []
    try:
        for path in paths:
            digest = sha256(path)
            if any(item["sha256"] == digest for item in audit["source_files"]):
                raise ValueError(f"Duplicate source content under another filename: {path.name}")
            source_id = "oe-local:" + digest
            source = {"filename": path.name, "sha256": digest, "bytes": path.stat().st_size,
                      "source_id": source_id, "source_url": None, "retrieved_at": None,
                      "publisher_candidate": "Oracle's Elixir", "provenance_status": "user_provided_unverified_origin",
                      "rows": 0, "missing_gameid_rows": 0, "leagues": collections.Counter()}
            games = collections.defaultdict(list)
            year = path.name[:4]
            missing = collections.defaultdict(lambda: collections.Counter())
            counts = collections.Counter()
            with path.open(encoding="utf-8-sig", newline="") as stream:
                reader = csv.DictReader(stream)
                headers = reader.fieldnames or []
                if not REQUIRED.issubset(headers) or len(headers) != len(set(headers)):
                    raise ValueError(f"Invalid schema in {path.name}: missing {REQUIRED - set(headers)} or duplicate header")
                source["fields"] = headers
                source["column_count"] = len(headers)
                for record_number, row in enumerate(reader, start=2):
                    if None in row or any(value is None for value in row.values()):
                        raise ValueError(f"Malformed CSV record {record_number} in {path.name}")
                    source["rows"] += 1
                    source["leagues"][row["league"]] += 1
                    source["missing_gameid_rows"] += not bool(row["gameid"])
                    if row["league"] not in TARGET_LEAGUES:
                        continue
                    if not row["gameid"]:
                        raise ValueError(f"Target row has no gameid: {path.name}:{record_number}")
                    record = {key: row.get(key, "") for key in KEEP_FIELDS}
                    record.update({"_record_number": record_number, "_source_id": source_id, "_source_year": year})
                    games[row["gameid"]].append(record)
                    row_type = "team" if row["position"] == "team" else "player"
                    counts[(row["league"], row_type)] += 1
                    fields = METRICS + ["champion", "playerid", "teamid"] if row_type == "player" else [
                        "patch", "firstPick"] + [f"{kind}{i}" for kind in ("pick", "ban") for i in range(1, 6)]
                    for key in fields:
                        missing[(row["league"], row_type)][key] += not bool(row.get(key, "").strip())
            if sha256(path) != digest:
                raise ValueError(f"Source changed during read: {path.name}")
            conn.execute("INSERT INTO sources VALUES (?,?,?,?,?)", (source_id, path.name, digest,
                         source["provenance_status"], json_compact(source)))
            groups = {}
            for gameid, rows in sorted(games.items()):
                if gameid in seen:
                    raise ValueError(f"Duplicate gameid across source files: {gameid}; no silent overwrite")
                seen.add(gameid)
                first = rows[0]
                league = first["league"]
                group = groups.setdefault(league, {"year": year, "league_raw": league, "games": 0,
                    "player_rows": counts[(league, "player")], "team_rows": counts[(league, "team")],
                    "player_missing": missing[(league, "player")], "team_missing": missing[(league, "team")],
                    "patch_games": collections.Counter(), "date_min": first["date"], "date_max": first["date"],
                    "structurally_valid_games": 0, "outcome_eligible_games": 0,
                    "timepoint_status": {str(m): collections.Counter() for m in (10, 15, 20, 25)}})
                gate = inspect_game(rows)
                group["games"] += 1
                group["patch_games"][first["patch"]] += 1
                group["date_min"] = min(group["date_min"], first["date"])
                group["date_max"] = max(group["date_max"], first["date"])
                group["structurally_valid_games"] += gate["structural_valid"]
                group["outcome_eligible_games"] += gate["outcome_eligible"]
                for minute, value in gate["timepoints"].items():
                    group["timepoint_status"][minute][value["status"]] += 1
                conn.execute("INSERT INTO games VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                    gameid, source_id, league, first["split"], first["playoffs"], first["date"], first["patch"],
                    first["game"], number(first["gamelength"]), gate["structural_valid"], gate["outcome_eligible"],
                    gate["winner_side"], gate["replay_ready"], gate["bp_order_status"], json_compact(gate["timepoints"])))
                for row in rows:
                    if row["position"] == "team":
                        conn.execute("INSERT INTO team_drafts VALUES (?,?,?,?,?,?,?,?,?)", (
                            gameid, row["_record_number"], row["side"], row["teamid"], row["teamname"], row["firstPick"],
                            number(row["result"]), json_compact([text_or_none(row[f"pick{i}"]) for i in range(1, 6)]),
                            json_compact([text_or_none(row[f"ban{i}"]) for i in range(1, 6)])))
                    else:
                        conn.execute("INSERT INTO player_games VALUES (?,?,?,?,?,?,?,?,?,?,?)", (
                            gameid, row["_record_number"], row["side"], row["position"], row["playerid"], row["playername"],
                            row["teamid"], row["teamname"], row["champion"], number(row["result"]),
                            json_compact({key: number(row.get(key)) for key in STAT_FIELDS})))
                for item in gate["issues"]:
                    conn.execute("INSERT INTO issues VALUES (?,?,?,?)", (gameid, item["code"], item["severity"], json_compact(item["detail"])))
                    audit["issue_counts"][item["code"]] += 1
                    audit["issue_examples"].append({"gameid": gameid, "source_id": source_id, **item})
                linked = context.get(gameid)
                if linked:
                    conn.execute("INSERT INTO match_context VALUES (?,?)", (gameid, json_compact(linked)))
                primary = year == "2024" and league == "LCK" and first["split"] == "Summer" and first["playoffs"] == "1"
                if primary or linked:
                    candidates.append(candidate(gameid, rows, gate, linked))
            audit["source_files"].append(source)
            audit["total_rows"] += source["rows"]
            audit["target_games"] += len(games)
            audit["target_groups"].extend(groups[k] for k in sorted(groups))
            conn.commit()
        unknown_context = sorted(set(context) - seen)
        if unknown_context:
            raise ValueError(f"Context references missing local games: {unknown_context[:5]}")
        audit["context_linked_games"] = len(context)
        audit["candidate_games"] = len(candidates)
        audit["primary_candidate_games"] = sum(row["sample_reason"] == "2024_lck_summer_playoffs" for row in candidates)
        audit["context_sha256"] = sha256(context_path) if context_path.exists() else None
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if violations or conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("SQLite integrity validation failed")
        conn.close()
        temp_db.replace(db_path)
    except Exception:
        conn.close()
        if temp_db.exists():
            temp_db.unlink()
        raise
    dump_json(manifest_path, audit)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report_markdown(audit), encoding="utf-8")
    candidate_path.parent.mkdir(parents=True, exist_ok=True)
    candidate_path.write_text("".join(json_compact(row) + "\n" for row in sorted(candidates, key=lambda x: (x["date_raw"], x["oe_gameid"]))), encoding="utf-8")
    print(json.dumps({"database": str(db_path), "source_rows": audit["total_rows"],
                      "target_games": audit["target_games"], "candidates": len(candidates),
                      "context_linked": len(context), "issues": audit["issue_counts"]}, ensure_ascii=False))
    return audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data/processed")
    parser.add_argument("--manifest", type=Path, default=ROOT / "data/manifests/local-oe.json")
    parser.add_argument("--report", type=Path, default=ROOT / "docs/data/local-audit.md")
    parser.add_argument("--candidates", type=Path, default=ROOT / "data/curated/replay_candidates.jsonl")
    parser.add_argument("--context", type=Path, default=ROOT / "data/curated/match_context.jsonl")
    args = parser.parse_args()
    build(args.input_dir, args.output_dir, args.manifest, args.report, args.candidates, args.context)


if __name__ == "__main__":
    main()
