# 数据集使用与重建

本项目的数据集建设以原始快照、确定性转换和分项验收为基础。已取得的数据不等同于已确认完整、可直接训练或可准确重放 BP。

## 本地职业比赛管道

环境：Python 3.9+；审计、SQLite 和离线测试仅使用标准库。

```sh
python3 scripts/build_dataset.py
python3 -m unittest discover -s tests -v
```

输入是 `data/` 下的四份 `2023`–`2026_LoL_esports_match_data_from_OraclesElixir.csv`。原文件由用户提供，未与发布者原件核验，管道不修改它们；获取时间和下载 URL 未知，不以文件 mtime 冒充获取时间。所有 CSV 全文件扫描，当前只对 LPL、LCK、WLDs 标签规范化。

| 产物 | 用途 | Git |
| --- | --- | --- |
| `data/manifests/local-oe.json` | 原文件哈希、字段列表、按年度/标签/指标的覆盖和异常 | 跟踪 |
| `docs/data/local-audit.md` | 可读的当前检查报告 | 跟踪 |
| `data/curated/replay_candidates.jsonl` | 代表复盘候选记录，保留未验收状态 | 跟踪 |
| `data/processed/lol_bp.sqlite3` | 目标比赛的本地规范化库，可重新生成 | 忽略 |
| `data/raw/` | 后续采集的原始来源快照，按 manifest 追溯 | 忽略 |
| 原始年度 CSV | 保留用户原文件 | 忽略 |

脚本支持 `--input-dir`、`--output-dir`、`--manifest`、`--report`、`--candidates`、`--context` 指定路径。输入文件读取前后核对哈希；同 gameid 跨文件重复、畸形 CSV 或歧义上下文会失败，不静默合并。构建新库并通过完整性检查后才替换旧 SQLite。

## 表与质量状态

- `sources`：本地快照的文件名、SHA-256、列定义与来源状态。
- `games`：按局保存源赛事标签、补丁、时间、结构/赛果门槛及时间截面状态。
- `player_games`：每局选手、历史最终分路、英雄及原始统计数值。源记录号可回查 CSV。
- `team_drafts`：地图边、firstPick 及 pick/ban 原始列；这些列尚未被解释成已验证事件序列。
- `issues`：有问题的记录仍保留，通过视图/质量字段控制使用，不销毁失败证据。
- `match_context`：有独立来源关联文件时保存原文 JSON；不自动覆盖 OE 原值。

`outcome_games` 只接受结构一致且双方恰好一胜一负的记录。`observed_15min_games` 要求比赛到达15分钟，十名选手都有相应经济、经验和补刀值。指标缺失和比赛在观察时点前结束分开保存。空值为 null，不作为0；空 Ban 不自动推断具体原因。

`replay_ready` 默认 false。需要另行确认逐手顺序、系列赛前序小局、规则适用期、赛事禁用和异常处理，才能形成正式复盘验收集。当前主样本为 CSV 标注的2024 LCK Summer playoffs 31小局，后续上下文补充不意味着这些门槛自动通过。

## 分析边界

- `WLDs` 保留为来源标签，不批量重命名为 Worlds 正赛；需要逐赛事/阶段映射。
- `date_raw` 不自动添加时区；历史信息可知时间未知，因此本轮没有声称通过严格历史推荐回测。
- 历史最终分路、赛果、赛后统计属于标签或历史已结束比赛信息，不能直接作为当前 BP 的已知特征。
- 同一系列赛不可拆到训练和测试两侧。尚未冻结训练/验证/测试划分，也没有训练推荐模型。
- 机制事实、统计观察、推断与 unknown 分开保存；“未取得”不等于“能力不存在”。

## 比赛上下文与规则证据

已从固定的 GPTilt / Leaguepedia 派生快照关联42小局、11系列赛：2024 LCK Summer Playoffs 31局，以及2026 LPL/LCK/Worlds各一个系列赛。38局通过Riot game id加日期/队伍/阵容集合交叉检查，4局通过日期、双方队名和英雄集合唯一匹配。该状态确认源记录关联，不表示官方/录像独立验收。

Parquet读取是唯一可选外部依赖。本轮实际验证使用Python3.12和fastparquet，版本见 `requirements/data-context.txt`；CSV、静态、规则管道及单元测试仍只需要标准库。

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements/data-context.txt
.venv/bin/python scripts/collect_match_context.py --download
python3 scripts/build_dataset.py
```

已有 `data/raw/match-context/` 缓存时省略 `--download`，固定Parquet哈希不符会失败。该命令更新源关联清单；再次运行build才会将最新上下文同步到SQLite与候选集。

规则证据由 `scripts/collect_rules_evidence.py` 采集，结构化事实经过来源阅读后另存 `rules.json` / `patches.json`。重跑只追加未审核快照，不自动改变现有事实或将新的HTTP200判为有效规则。初次迁移可用 `--migrate-only` 离线执行；旧事实绑定旧哈希，新规则修订必须重新核验。

详细证据和访问失败见 [比赛上下文核验](../research/match-context-verification.md)、[规则与补丁证据](../research/dataset-rules-evidence.md)。来源归属见 [SOURCES.md](../../data/SOURCES.md)。2026 OE的16.xx与上下文的26.xx保留为未消解差异，不覆盖原值。

## 原始数据与再分发

本仓库不上传用户原始年度文件、第三方大快照、整份规则书、图片或凭证。可复现脚本和来源清单不代表上游提供了永久可用性或额外使用许可。不同来源的许可与署名分别记录，不能把本仓库代码的许可扩大到第三方数据和 Riot 游戏资产。

## 静态资料与样本索引

```sh
python3 scripts/collect_static_data.py
python3 scripts/assemble_sample.py
```

采集器默认取14.16.1、16.16.1、16.17.1、16.20.1四版本的中英文基础目录，前后两个版本另取11名样例英雄的技能详情。本轮75/77响应成功，74份规范化文件；两个中文符文目录网络失败，所以采集命令返回非零退出码，不能写成全量成功。

成功输出仍可用于离线样本索引；只读取manifest成功清单并验证原始/派生哈希，不按目录里“有文件”就判定有效。`--offline` 可从原始缓存重建，当前缺两份缓存仍会明确非零退出；该命令会重写manifest的运行状态，保留正式网络失败证据时应在临时副本中做重建验证。详细计数、缺口及字段限制见[静态资料说明](static-data.md)。

建议顺序：收集上下文 → 构建CSV/SQLite → 收集静态资料 → 采集Leaguepedia逐手表（`collect_leaguepedia_pb.py`，需要SQLite）→ 测量OE顺序（`measure_oe_order.py`）→ 逐手BP验证 → 生成sample index → 跑离线测试。规则与patches结构化记录已有版本，本轮不需要重新联网获取规则书；如主动刷新则按规则证据文档审核新内容。输入快照变化后重新生成下游产物，`sample-index.json` 内的input_sha256用于识别过期索引。

索引目前覆盖42小局、11系列赛，关联英雄数字ID及候选规则。生成索引前须运行 `python3 scripts/validate_bp.py`；[逐手BP验证器](bp-validation.md)已实现，但尚无独立逐手证据，所有replay_ready保持false；详见[样本索引说明](sample-index.md)和[数据集状态](dataset-status.md)。
