# 数据来源、归属与快照

## 本地 OE 命名文件

用户提供的2023–2026年度 CSV 位于 `data/`，文件名指向 Oracle's Elixir。发布者候选入口为 <https://oracleselixir.com/tools/downloads>；本轮没有验证与该入口原件一致，也不知道原始下载日期。`manifests/local-oe.json` 仅确认本地字节快照。原文件不再分发；规范化统计和小批记录保留来源标记，不把第三方内容声明为本项目独有。

## GPTilt / Leaguepedia

`curated/match_context.jsonl` 中的源赛事、系列赛、局号、源补丁、源日期、来源页/录像链接来自 [GPTilt lol-esports-matches](https://huggingface.co/datasets/gptilt/lol-esports-matches)，固定 revision `04787d28f0661cff22568c3abc5f39a406906b6d`。发布者[数据卡](https://huggingface.co/datasets/gptilt/lol-esports-matches/blob/04787d28f0661cff22568c3abc5f39a406906b6d/README.md)声明 CC BY-SA 3.0，上游是 [Leaguepedia](https://lol.fandom.com/wiki/League_of_Legends_Esports_Wiki)。

相应数据的复制和派生继续保留 GPTilt、Leaguepedia 署名及 [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/) 要求。本站进行了样本选择、OE 关联、字段命名及质量标注；这些是本项目的处理，不是来源对处理结果的认可。`replay_candidates.jsonl` 和 `sample-index.json` 嵌入/派生相应上下文字段时沿用此归属。没有把该许可扩大到其他来源、Riot资产或自有代码。

两个来源共享上游，不能把一致性当作独立录像验证。games的picks是历史分路顺序；不用于恢复逐手BP。

## Leaguepedia 逐手选禁表

`curated/bp_sequences.jsonl` 的逐手选禁顺序摘自 [Leaguepedia](https://lol.fandom.com/wiki/League_of_Legends_Esports_Wiki) 各赛段 Picks and Bans 页面，通过公开 MediaWiki parse 接口低频读取。每条记录带页面标题、修订号、获取时间和原始响应哈希；`manifests/leaguepedia-pb.json` 保存采集记录，原始响应留在本地 `raw/leaguepedia-pb/`。Leaguepedia 内容按 [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/) 使用，派生记录沿用该署名与许可；与 OE 的关联和质量标注是本项目的处理。

`curated/patch_changes.jsonl` 的英雄改动（说明文字截取与改动方向）摘自 Leaguepedia 的 Patch 页面，采集记录在 `manifests/leaguepedia-patches.json`；`curated/patch_mapping.json` 的补丁号对照由 `event_restrictions.jsonl` 中的逐局记录派生。归属与许可同上；改动方向是本项目按关键词与数值自动判定的结果，不是 Riot 的标注。

`curated/champion_traits.json` 的标签与评分来自 Data Dragon 16.20.1 英雄列表（见下节）。

`curated/event_restrictions.jsonl` 的赛事禁用英雄、列出的补丁和选边字段摘自 Leaguepedia 赛段 Data 页面（MediaWiki revisions API），每条记录带页面修订号与比赛定位。归属与许可同上；这是社区记录，不是主办方原件。

## Riot 规则与静态资料

规则出处及每项条款定位见 `curated/rules.json`、`curated/patches.json` 与 `manifests/rules-evidence.json`。官方书和第三方托管镜像分开标注；本仓库跟踪结构化摘要，不上传整份PDF正文。

静态英雄/装备/符文/召唤师技能资料来自 [Riot Data Dragon](https://developer.riotgames.com/docs/lol#data-dragon)。`manifests/static-data.json` 记录每次请求、版本、原始和规范化哈希。游戏内容和资产归 Riot；公共访问不改变其权利归属。没有下载或上传图片素材。

`curated/champion_availability.json` 列出每个比赛补丁对应 Data Dragon 版本（`<major>.<minor>.1`）的英雄编号，采集记录在 `manifests/champion-availability.json`；它说明英雄已经在游戏中上线，不证明赛事服务器的实际版本。

来源缺失、HTTP错误、HTTP200占位页和未核验适用范围均保留原状态。`raw/` 保存本地证据，`manifests/` 保存可跟踪来源清单；API密钥和本地运行产物不进入版本控制。
