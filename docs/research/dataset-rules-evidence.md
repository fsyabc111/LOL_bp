# 首批数据集规则与补丁证据

核验日期：2026-10-28。本文件只区分实际取得的规则文本、适用期推断和未知事项；不构成比赛异常已验收的声明。可机读记录见 `data/curated/rules.json`、`patches.json`；每个事实带 `status`、`source_id`、页码/条款。来源 URL、UTC、原始字节 SHA-256、大小及 HTTP 状态见 `data/manifests/rules-evidence.json`。`data/raw/rules/` 是本地证据缓存，不建议提交整份版权正文。

## 已取得的证据

通过 [Riot 官方规则库](https://competitiveops.riotgames.com/en-US/library?SPIEL=lol) HTML 中公开的 `externalTitle` / `externalUrl`，正常下载四份 2026 PDF，不需要浏览器或私有 API。国际通则与 Worlds 细则均是官方库直接链接。LCK 韩文文本由 pypdf 读取，以下为摘要翻译，保留页码和条款供复查。

- [2024 LCK 规则书镜像](https://static.wikia.nocookie.net/lolesports_gamepedia_en/images/7/74/LCK_2024_Rulebook.pdf/revision/latest?cb=20240413022358)：Riot Korea 编写、Leaguepedia CDN 托管，修订 2023-12-18、生效 2024-01-17。p50 §7.7.4 明确四阶段：ban `ABABAB`、pick `ABBAAB`、ban `BABA`、pick `BAAB`，其中 A=蓝方、B=红方。p39-40 §6.2.3.1 规定 playoffs BO5 和 tournament draft；p50 §7.7.5 规定对方下一手锁定前通知错误可以由裁判恢复到错误处。本次未找到 Summer 专门修订，故上述文本确实存在为 observed，但用作 Summer Playoffs 最终适用规则为 inferred。不能仅凭未找到 Fearless 条款写 `fearless=false`。
- [2026 LCK 通则](https://cdn.sanity.io/files/dsfx7636/news_live/4b72bb20244653d0d7dbe162e929d1c07b1f936f.pdf)：官方库说明修订 2026-06-29、生效 2026-07-29。p37 §7.7.1.1 仍为上述20手顺序，但 A=先选队、B=后选队。§7.7.1.2.1-2 将双方在前局选择的英雄从该 match 后续局可选池移除；例子将 ban 与 pick 分开，§7.7.1.2.5 保留其他 tournament draft 规则。§7.7.1.2.3 错选已消耗英雄要恢复 BP、可能处罚；§7.7.1.2.4 ban 已消耗英雄则损失该 ban 机会，不额外处罚。p44 §8.5.2 明确重开保留此前小局的 Fearless 禁用池，本次重开局的 pick 不计消耗。
- [2026 LCK 赛事细则](https://cdn.sanity.io/files/dsfx7636/news_live/b5e4819daa2793425433910ca02b1c479b2f15a3.pdf)：p7 §2.6 拆开地图边与先后选、后续局前局败者获 RoFS；p20-22 §4.1.1/4.2.1/4.3.1 明确常规轮次、play-in、playoffs 为 Fearless；p26 §5.1 明确 Road to MSI。p24 §4.3.2.8 为赛季总决赛首局例外，上半区胜者同时选边与选顺序。不能将7月版追溯为4–5月 Round 1–2 比赛已核实适用版本；需要早期版本。
- [2026 Season Start](https://lolesports.com/en-AU/news/season-start-2026-lol-esports) 的 Introducing First Selection 部分确认：原先有选边权的队伍获得 First Selection，可以先决定地图边或者先后选；对方决定另一项，并宣布赛季开始全赛区启用。这支持 LPL/LCK 的两维分离，但不是每项赛事的 Fearless 细则证据。
- [Worlds 2026 细则](https://cdn.sanity.io/files/dsfx7636/news_live/faa5ce974e58615911fbee931c6123e2785a8b46.pdf)：p9-10 §4.1.4 确认 First Selection、后续局败者权利，以及 Play-In Round4 首局上半区队伍双重选择例外。p15 §5.1 明确比赛版本26.20，并允许赛事方临时限制英雄等内容，赛前向队伍提供限制清单。该清单未取得，不能记为空数组。文件 §4.1.3.1.3 仍出现“2025 WCE Champion”，是来源内遗留，未自行修正。
- [2026 国际赛事通则](https://cdn.sanity.io/files/dsfx7636/news_live/d29e446e0a0d0813a8caaae1d2817dd82cfe79c6.pdf) p18 §4.5.2–7 确认 draft 重做恢复先前相同顺序及 Fearless 误选处理，但没有在所读文字明确给出 Worlds 全赛段 Fearless 消耗定义。§4.5.4 指向 Appendix Figure4，未独立解释图像，因此不将2026 LCK模板直接套给Worlds。

[2025 官方赛季说明](https://lolesports.com/en-US/news/lol-esports-in-2025) 的 Fearless Explained 确认当年双方前局 pick 消耗、每局10个标准 ban 仍保留；[2025 后续公告](https://lolesports.com/en-PH/news/fearless-draft-takes-over-2025)说明当年剩余赛季和 Worlds BO3/BO5。它们是背景证据，不自动证明2026 LPL/Worlds适用范围。

## 补丁命名与访问结果

[官方14.16公告](https://www.leagueoflegends.com/en-us/news/game-updates/patch-14-16-notes/)和[官方26.20公告](https://www.leagueoflegends.com/en-us/news/game-updates/league-of-legends-patch-26-20-notes/)可经搜索工具读取正文，但本地普通 HTTP 抓取均收到3307字节腾讯占位 HTML，HTTP200并非正文成功。原始响应已保留并标 `wrong_content_http_200`。en-SG/en-GB普通请求也相同；浏览器回退失败于 browser-harness daemon 启动，未规避地域/访问限制。故本轮**未取得可复查的公告及热修复本地全文快照**，热修复日期与比赛实际部署状态全部 unknown。

实际成功取得 Data Dragon [14.16.1 Ahri](https://ddragon.leagueoflegends.com/cdn/14.16.1/data/en_US/champion/Ahri.json) 和 [16.20.1 Ahri](https://ddragon.leagueoflegends.com/cdn/16.20.1/data/en_US/champion/Ahri.json)，分别观察到 `$.version`。 [官方 Data Dragon 文档](https://developer.riotgames.com/docs/lol#data-dragon)是资源版本与更新语义的依据，不能证明锦标赛服务器热修复构建。14.16→14.16.1仅作为同主/次版本资源候选映射（inferred）；26.20→16.20.1缺少官方明文等价证据，标unverified，不实现减10命名规则。

## 对首批数据集的限制

2024样本可先检查20手顺序，但结果必须附“基于已存2024规则书、Summer修订待核实”。赛事补丁14.16仍应由逐局独立来源确认；本次规则书不证明比赛所用补丁。2026 LCK例子若选择7月前小局，需要补早期规则版本；7月后可使用已取得版本，同时检查赛事细则。2026 LPL Fearless、Worlds Fearless范围和重开消耗仍不得启用确定性合法性检查。未知禁用英雄/重开情况均不能视为没有发生。

重取：`python3 scripts/collect_rules_evidence.py` 使用标准库单次顺序请求固定公开源，40秒超时、记录错误，不重试不绕限流。该脚本只采集证据，不自动从PDF生成事实。

Manifest 已离线迁移为 schema_version=2：

- `sources` 固定初次研究使用的 source_id 与 SHA-256 映射，curated 的 source_id locator 仍解析到原始版本，重取不会更换。
- `snapshots` / `collections` 追加每次抓取结果。原始字节保存在 `data/raw/rules/sha256/<sha256>.<suffix>`；同名内容缓存若字节不符会拒绝使用。
- **每次新抓取，无论失败、HTTP200占位、相同字节还是变化内容，`semantic_status` 一律为 `unreviewed`**。既有语义审阅不会自动传递给新抓取。
- `semantic_reviews` 的旧观察迁移显式带 `source_id` 与 `sha256`；`snapshot_saved` 仅表示原始响应已存储，不等于规则内容 verified。先前 `content_status`、publisher 和访问失败记录均保留。
- 原始旧路径保留在 `legacy_path`，对应文件不改写。新字节不会覆盖它或已有哈希快照。

仅迁移本地已有证据可运行 `python3 scripts/collect_rules_evidence.py --migrate-only`，没有网络请求。当前迁移保留全部15个原始响应，5项离线回归测试覆盖迁移、变化内容、HTTP200占位、HTTP/传输失败和缓存损坏。任何后续 curated 版本更新都需要显式审阅与改动固定映射，不能把“最近抓取”默认当作已验收规则。

## 2026-10-29 补充：2025 规则书与赛事禁用名单

### 新取得的规则书

两份文件来自 [Riot 官方规则库](https://competitiveops.riotgames.com/en-US/library?SPIEL=lol)，通过 `python3 scripts/collect_rules_evidence.py --only worlds_2025_rules lck_2025_rules --pin` 下载并固定为来源（`--pin` 只追加尚未固定的成功来源，不改动已有映射）。正文用 pypdf 5.1.0 读取；附录中只有图片的页面，渲染后人工查看。

- **[2025 Worlds 规则 v1.0](https://cdn.sanity.io/files/dsfx7636/news_live/d3d5b3d1ad2d201d397818ca4209c99536182a18.pdf)**（库中标注 ARCHIVED）
  - p28 §7.3：比赛补丁为 15.20；赛前向队伍提供禁用名单，该名单未取得。
  - p30 §7.5.4：所有比赛采用 Fearless，本系列赛已选英雄在剩余对局中禁用，每局 10 个标准 ban 不变。
  - p31 §7.5.5–7.5.8：蛇形选禁；Fearless 误选英雄时回退重选，误禁则不回退。
  - p54 附录 Figure 3（图片）：Ban1 蓝红交替各 3 手；Pick1 为蓝、红、红、蓝、蓝、红；Ban2 为红、蓝、红、蓝；Pick2 为红、蓝、蓝、红。即 snake_20，A = 蓝方。
  - p19 §6.1.1.2：选边规则为首局抛硬币或按种子，之后由上一局败方选边。
- **[2025 LCK & LCK CL 规则](https://cdn.sanity.io/files/dsfx7636/news_live/3e74c542dd1efc5c07529772e4b978ab83c99352.pdf)**（2025-03-03 修订，2025-04-02 生效）
  - p35–36 §7.7.1.1：明文规定"蓝方 = A，红方 = B"，顺序为 ABABAB / ABBAAB / BABA / BAAB。
  - p36 §7.7.1.2：定义 Fearless（双方前局所选英雄不可再选；误选回退并可能处罚，误禁则失去该 ban）。
  - p42 §8.5.2：重赛时前序局的 Fearless 消耗保留，重赛局本身的 pick 不计入。
  - p34 §7.4.3：新英雄在其上线补丁内禁用。
  - 本书没有说明哪些赛事采用 Fearless，这在赛事细则中规定。库中"2025 赛事细则"条目指向的是同一份文件，因此 2025 LCK 的 Fearless 适用标为 **inferred**。规则在 2025-04-02 生效，2025 LCK Cup 不在其适用期内。

`rules.json` 的相应调整：

- 新增 `worlds_2025`：模板、A 方、Fearless、补丁均为 observed，赛事禁用为 unknown。
- 新增 `lck_2025_from_2025_04_02`。
- `worlds_2026` 的模板、A 方、Fearless 由 unknown 改为 **inferred**。理由：2026 国际赛事通则 v1.1 p18 §4.5.4 写明蛇形选禁，但所引用的 Figure 4 不在 PDF 中；p19 §4.5.6–7 涉及 Fearless 误选，但没有定义适用范围。因此步骤顺序和 Fearless 定义取自 2025 版规则，"A = 先选方"沿用 2026 LCK 的明文。
- 2026 LCK 规则改为按其赛事细则列出的适用范围匹配（常规赛 1–2、3–4 轮、Play-In、季后赛、Road to MSI），不再只认 Season Playoffs；同时仍要求比赛日期不早于 2026-07-29。

验证器只接受 observed 的模板和 A 方，所以 2026 Worlds 样本局仍为 blocked。

LPL：官方规则库中没有 LPL 文件，本次检索也没有找到腾讯公开的 2025–2026 LPL 规则书，因此 LPL 仍为 practice_observed（模板）和 assumed（Fearless）。

### Leaguepedia 赛事禁用名单

`scripts/collect_leaguepedia_data_pages.py` 读取 59 个 Data 页面的 wikitext（2024 LCK 夏季季后赛，以及 2025–2026 LCK、LPL、Worlds 各赛段；不含表演赛），原始响应按哈希存放。页面中的 `{{SetPatch|patch=..|disabled=..|hotfix=..}}` 对其后的比赛有效，直到下一条 SetPatch 出现。

- **关联方式**：只按 ID 关联，不按队名。LCK 与 Worlds 用 `riot_platform_game_id`，LPL 用 `qq` 系列号拼成 `<qq>-<qq>_game_<n>`。共关联 2,726 局，没有重复。未关联的是 2026 Worlds 正赛中 62 局 OE 尚未收录的比赛，以及 LCK、LPL 各 1 局 OE 中没有的比赛。
- **结果**：523 局列有禁用英雄，例如 2024 LCK 夏季季后赛禁用 Aurora，2025 年多段禁用 Mel、Yunara，2026 年部分赛段禁用 Zac、Maokai。所有禁用名都能映射到英雄 ID。
- **一致性**：全量回放中，没有任何一局历史 pick 使用了该局列出的禁用英雄，可以作为关联和语义正确的旁证。
- **数据性质**：这是社区记录，状态标为 `community_listed`，等级低于规则书。空名单表示 Leaguepedia 没有列出禁用英雄，不等于主办方确认无禁用。sample index 的 `rules_complete` 仍只认规则书，所以不受这份名单影响；应用会据此拦截英雄并显示来源。

### 当前规则状态覆盖（2024–2026，按局计）

| 年 | 标签 | 模板 | 跨局限制 | 赛事禁用 | 局数 |
| --- | --- | --- | --- | --- | ---: |
| 2024 | LCK | observed（夏季季后赛） | assumed | community_listed | 31 |
| 2024 | LCK / LPL / WLDs 其余 | practice_observed | assumed | unknown | 1,300 |
| 2025 | LCK（04-02 起） | observed | inferred | community_listed | 446 |
| 2025 | LCK Cup 等 | practice_observed | assumed | community_listed | 109 |
| 2025 | LPL | practice_observed | assumed | community_listed | 805 |
| 2025 | Worlds | observed | observed | community_listed | 84 |
| 2026 | LCK（7-29 后、规则范围内） | observed | observed | community_listed | 153 |
| 2026 | LCK 其余 | practice_observed | assumed | community_listed | 349 |
| 2026 | LPL | practice_observed | assumed | community_listed | 674 |
| 2026 | Worlds | inferred | inferred | community_listed | 51 |
| 2025–2026 | WLDs 中的地区资格赛等 | practice_observed | assumed | community_listed | 24 |

仍未补齐：

- LPL 规则书。
- 2025 LCK 赛事细则（各赛事 Fearless 范围、选边规则）与 2025 LCK Cup 规则。
- 2026 LCK 7 月前的修订版。
- 2024 夏季修订。
- 官方赛事禁用名单原件，以及热修复版本。
