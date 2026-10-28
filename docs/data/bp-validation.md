# 逐手 BP 序列验证器

`scripts/validate_bp.py` 是离线、确定性的逐手选禁验证器。它只检查“给定的独立逐手证据能否与规则模板、OE 最终阵容和跨局规则一致”，不从任何列推断真实顺序，也不访问网络。

```sh
python3 scripts/build_dataset.py        # 如输入有变化
python3 scripts/validate_bp.py          # 输出 data/curated/bp-validation.json
python3 scripts/assemble_sample.py      # 读取验证结果，更新 readiness
python3 -m unittest discover -s tests -p test_bp_validator.py
```

输出按 gameid 排序、不写生成时间，并记录全部输入的 SHA-256；同输入两次生成字节相同。`assemble_sample.py` 读取前逐项核对这些哈希，任一输入变化即拒绝使用旧验证结果，必须重跑验证器。

## 判定流程

1. **规则模板**：只使用适用状态为 observed/inferred、且 `draft_template` 与 `draft_team_A` 均为 observed 的规则。模板未知、多个规则冲突时为 `blocked`，不默认套用 snake_20。规则适用性是否为推断仍由 sample index 的 `rules_complete` 单独报告。
2. **A/B 队映射**：`draft_team_A=blue` 时 A 为蓝方；`first_pick` 时取 OE firstPick=1 的一侧，独立证据中实际先手的队伍必须与之一致，否则拒绝。
3. **序列检查**：20 步数量、每步行动方与 ban/pick 类型须与模板一致；pick 不可为空；同一局不可重复英雄；每侧 pick 与 ban 的多重集合须等于 OE 最终列。空 ban 只能对应 OE 的空槽，不推断原因。
4. **英雄身份**：在候选静态版本的英文目录中按 aliases/name 解析为数字 ID（如 MonkeyKing 与 Wukong 视为同一英雄）；无法解析时退回去空格、去标点的小写名称比较。
5. **跨局规则**：仅当 `cross_game_ban_scope` 为 observed 的“双方前局 pick 在本系列赛后续局不可选”，且本系列赛所有前序局都在样本中，才执行检查；重复 pick 判为违规，禁用已消耗英雄按规则只记录为损失的 ban。重开局在当前来源中没有记录，标 `remake_status=unknown_not_recorded_in_sources`。规则未知时只列出 `observed_pick_repeats`，不做合法性结论。
6. **来源独立性**：只有 `vod_manual`、`official_broadcast`、`leaguepedia_picks_and_bans` 类型、带 `locator` 的证据才能使结果为 `verified`。每局最多一条证据，多条记录为 `conflicting_evidence_records`，不自动挑选。

## OE 列假设

在模板与 A/B 映射已知时，验证器按模板把每队 OE pick1–5、ban1–5 依次放入该队的行动位置，生成 `oe_column_hypothesis`（`status=hypothesis_unverified`）。它只用于和独立证据比较：独立证据通过后输出 `oe_column_order_agreement`，可统计 OE 列是否等于真实逐手顺序。顺序不一致只报告差异步骤，不导致独立证据被拒绝。OE 列作为来源提交时一律因 `source_not_independent` 被拒绝，不能自证。

## 独立证据输入

`data/curated/bp_sequences.jsonl` 可选，每行一局：

```json
{"oe_gameid": "LOLTMNT03_138505",
 "source": {"source_type": "vod_manual", "url": "https://www.youtube.com/live/YdBvUiXZu88?t=2641",
            "locator": "VOD 00:44:01–00:52:30 draft overlay", "transcribed_at": "2026-10-29", "transcriber": "self"},
 "steps": [{"step": 1, "side": "Blue", "action": "ban", "champion": "Renekton"}, "... 共20步 ..."]}
```

`champion` 写来源中显示的名称；空 ban 写 null。Leaguepedia 来源应在 `locator` 写页面修订号，在 `source` 中补 `retrieved_at` 与原始响应 `sha256`，原始响应存 `data/raw/`。样本外 gameid 会直接报错。38 局的比赛上下文带有 VOD 链接（2026 LPL 四局没有），可以按录像中的选禁界面逐步转录。

## 2026-10-29 运行结果

本轮仍未取得任何独立逐手来源：沙箱内访问 lol.fandom.com、gol.gg、huggingface.co 均在 TLS 握手阶段被断开，与站点本身的 403 不同，属于本地网络限制，未尝试绕过。因此 `bp_sequences.jsonl` 不存在，42 局均为 `no_independent_sequence`，bp_verified 与 replay_ready 仍为 0。

可以确认的部分：

- 35 局可以确定模板及 A/B 映射，生成 OE 列假设，内部检查（步数、重复、集合）均无错误；7 局（2026 LPL 与 Worlds）因模板未知被阻止。
- 2024 LCK 31 局的 firstPick=1 全部在蓝方，与 2024 规则书“A=蓝方”一致；2026 年 11 局中先手 6 次在红方，与 First Selection 拆分地图边与先后选的说明一致。这是 OE 列与规则的一致性，不是顺序验证。
- 2026 LCK 决赛 4 局在已观察的 Fearless 规则下检查通过，前序局齐全，无重复 pick，没有禁用已消耗英雄。
- 2024 LCK 季后赛各系列赛中 23 局与前序局有重复 pick，与当时未采用 Fearless 相符；规则字段仍为 unknown，不据此写入规则事实。2026 LPL 与 Worlds 在样本内没有重复 pick，同样不升格为规则证据。

15 项验证器单元测试覆盖：独立证据通过、OE 顺序差异只报告、OE 列不能自证、缺 locator、行动方错误、步数和空 pick、重复与集合不符、空 ban 对齐、firstPick 映射、模板未知与规则不适用、多条证据冲突、Fearless 违规与禁用已消耗英雄、前序局缺失、未知规则只描述，以及英雄别名。
