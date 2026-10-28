# 首批比赛上下文核验

核验日期：2026-10-28。这里的 `source_record_verified` 只表示已读取发布者结构化记录并以确定性规则关联 OE 小局，不表示录像、官方赛程或独立上游已逐局验收。

## 来源与语义

本次实际下载 [GPTilt games](https://huggingface.co/datasets/gptilt/lol-esports-matches/tree/04787d28f0661cff22568c3abc5f39a406906b6d/games)、[matches](https://huggingface.co/datasets/gptilt/lol-esports-matches/tree/04787d28f0661cff22568c3abc5f39a406906b6d/matches) 及[发布者数据卡](https://huggingface.co/datasets/gptilt/lol-esports-matches/blob/04787d28f0661cff22568c3abc5f39a406906b6d/README.md)，固定 revision `04787d28f0661cff22568c3abc5f39a406906b6d`。原始 Parquet 留在 `data/raw/match-context/`，字节数与 SHA-256 在 `data/manifests/match-context.json`，大快照不应纳入 Git。

数据卡声明 games 源于 Leaguepedia `ScoreboardGames`，matches 源于 `MatchSchedule`；它们共享 Leaguepedia 上游，不能把两表一致算为独立交叉验证。数据卡声明内容许可 CC BY-SA 3.0，使用/再分发应保留 GPTilt 和 Leaguepedia 归属及对应许可。源是持续覆盖更新的快照，没有历史修订流。

尤其是 `picks_blue` / `picks_red` 明确按 top→jungle→mid→bot→support 排列。它们只用作两侧英雄集合校验，不用作 BP 顺序。OE 的 pick1–5 在本次尚未取得独立逐手来源对照，因此所有产出记录 `bp_order_status=unknown`；没有任何序列被标为 verified。

## 可复现方法

```sh
python3 -m venv .venv
.venv/bin/pip install pyarrow==21.0.0
.venv/bin/python scripts/collect_match_context.py --download
python3 -m unittest discover -s tests -p test_match_context.py
```

已有缓存时省略 `--download`。脚本只读本地年度 OE CSV，输出小型 JSONL 与 manifest。先按 `riot_game_id` 精确匹配 OE `gameid`，仍要求日期、双方队名和英雄集合全部一致；冲突输出 conflict，不能进入 source_record_verified。不匹配时，要求 日历日期、双方完整队名、双方各五英雄集合的联合键只对应一条源记录，不进行模糊队名、猜 ID 或按日期排列自动编造系列赛。歧义保留 unmatched。系列赛号、局号、BO 和赛事字段均保留源值。

2024 目标是本地 8 月 23 日至 9 月 8 日 LCK playoffs 全段；2026 每个 OE 标签取能被源完整覆盖的最新一场系列赛。OE 标签不直接证明源赛事身份，尤其 WLDs 可能含地区资格赛；应使用输出 `tournament` 检查。

## 访问失败与边界

[Leaguepedia Cargo](https://lol.fandom.com/api.php?action=cargoquery&format=json&tables=PicksAndBansS7&fields=GameId&limit=1) 两次有限尝试返回 HTTP 403。原始失败响应与时间戳保存为 `data/raw/match-context/leaguepedia-response.txt`、`access-attempts.json`。browser-harness 兜底启动失败，本地 Chrome `DevToolsActivePort` 返回 Operation not permitted；未使用代理或绕访问限制。HF viewer filter 一次返回 500，随后改用发布者公开完整 Parquet，而非推断其不存在。

这些访问失败不证明源没有 BP；本轮只证明当前可读取路径未提供已验收的逐手 BP。官方赛制、全局 BP 规则与录像逐手仍为缺口。

## 实际结果

本次成功关联 **42 小局 / 11 系列赛**：

| 范围 | 小局 | 系列赛 | BP 顺序 |
| --- | ---: | ---: | --- |
| 2024 LCK Summer Playoffs 全赛段 | 31 | 8 | unknown |
| 2026 LPL Grand Finals，Finals | 4 | 1 | unknown |
| 2026 LCK Season Playoffs，Finals | 4 | 1 | unknown |
| 2026 Worlds Play-In，Round 3 | 3 | 1 | unknown |

38 局通过 Riot game id 精确关联；4 局 LPL 通过 日历日期、双方完整队名及双方英雄集合唯一匹配。逐局原始源字段另保存在 `selected-source-records.json`，包括完整源键，便于无需提交大 Parquet 也能检查具体证据。42 局蓝红方队名及日历日期均与 OE 一致。OE 时间列尚未取得时区字段字典确认；比较只截取日期字符串，与源 datetime_utc 日期对照，不执行模糊时区转换。2024 的31局补丁均为 14.16，两源完全一致。

**2026 补丁编号存在未消解的来源差异**：OE 使用 16.16 / 16.17 / 16.20，GPTilt 使用 26.16 / 26.17 / 26.20。输出同时保存 `oe_patch` 和源 `patch`，标记 `different_source_notation_unresolved`；本次未取得官方编号映射证据，不能直接覆盖或宣称逐字符串一致。源记录核验状态不等于该冲突已解决。

完整 GPTilt games 快照 138,402 行，源最大 datetime 为 **2026-10-25 00:34:00 UTC**。这是快照最大时间，不代表每赛事完整覆盖到该时间，也不能覆盖 OE 中10月26日的新比赛。

实际执行采用备用读取依赖：Python 3.12、pandas 2.2.3、fastparquet 2026.9.0、cramjam 2.14.0、fsspec 2026.9.0。pyarrow 的31MB安装包下载过慢，临时下载已停止，不能将其安装或运行称为通过。脚本优先 pyarrow，缺少时回退 fastparquet；可替换上面的安装命令为：

```sh
pip install pandas==2.2.3 fastparquet==2026.9.0 cramjam==2.14.0 fsspec==2026.9.0
```

映射单元测试6项通过，覆盖精确ID及日期/队伍/英雄冲突拒绝、集合不依赖英雄顺序以及联合键歧义拒绝。尚未完成：官方/录像独立逐局验收、任何逐手 BP 序列、2026编号映射、首选顺序与地图边关系、全局 BP 消耗英雄的规则级核验。

本轮重新从固定 revision 下载三份来源文件，`acquisitions.json` 和 manifest 保留每份固定 source_url、真实下载完成 retrieved_at、HTTP 状态、字节数和校验值。缓存复用只重算 generated_at，保留原 retrieved_at，不把处理时间伪装为获取时间。两份 Parquet 哈希也与 Hugging Face 该 revision 的 LFS oid 逐一相符，脚本强制检查。
