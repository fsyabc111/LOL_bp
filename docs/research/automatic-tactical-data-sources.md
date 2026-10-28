# 战术数据自动获取：来源与可行性研究

- 调查日期：2026-10-28（Asia/Taipei）。
- 对应设计：[v0.2 早期设计](../design/early-design.md)。
- 状态：公开来源调查与少量字段抽样，不是完整数据集、接入验收或战术模型效果证明。
- 本次未注册账号、使用 API 凭证、绕过访问限制或抓取全量比赛；未安装依赖或实现采集应用。

## 1. 结论

可以采用“版本化机制资料自动导入 + 对局统计自动计算 + 受证据约束的文本提取/模型归纳”建立知识，不要求用户逐个写全英雄画像、克制矩阵或发力期表。

但这些内容并非同一种数据：基础属性、冷却和部分技能标签可直接读取；等级/装备条件下的数值可以在公式解析后计算；对位与协同需要从真实对局估计；线权、资源布置和整套阵容的取胜路径需要带条件的推断。系统必须保留它们的区别。

优先路线是 Riot Data Dragon 做版本与实体基础，CommunityDragon 的版本化客户端及游戏 BIN JSON 补更细机制，官方补丁与热修复校验变化。League of Legends Wiki 是更丰富的语义资料候选，但本次未跑通直接程序访问。Meraki JSON 的结构值得参考，本次发现其 `latest` 样本与目标 26.20 明确不符，不能直接作为当前版本主源。

## 2. 需求与可获得信息的对应

| 系统需要的信息 | 推荐自动来源/处理 | 仍需保留的限制 |
| --- | --- | --- |
| 英雄身份、基础属性、成长、普攻射程 | Data Dragon 版本化 JSON，必要时跨来源核对 | 成长字段不能自动等同完整等级公式；模式、重做及异常值需检查 |
| 技能范围、CD、消耗、伤害和倍率 | CDragon 基本英雄 JSON + 游戏 BIN JSON + 官方变更 | 需要解析根技能、子技能、等级数组、计算节点及脚本依赖 |
| 控制、位移、伤害类型、命中条件 | 原生技能标签与描述自动提取，关联到原始字段/文本 | 描述并不覆盖全部机制；“有控制”不等于“稳定开团” |
| 装备价格、属性、合成与主动效果 | Data Dragon/CDragon 装备 + 官方补丁 | 商店展示文本未必包含完整主动公式和被动交互 |
| 英雄能力画像 | 规则计算与受证据约束的文本结构化，按版本存储 | 属于派生知识，应记录可用范围、未知和矛盾，不直接视为游戏事实 |
| 对位、下路组合、中野协同 | 按位置和补丁对比赛样本计算，经基线校正和样本平滑 | 数据稀疏、玩家与队伍实力偏差、职业/排位分布差异 |
| 发力窗口 | 机制节点 + 对局中的等级/装备/经济时间截面 | 不是单一“前中后期”标签；不能用最终局长胜率直接当成长曲线 |
| 中立资源能力与资源情景 | 官方资源规则、技能对野怪等机制、历史事件/位置等观测 | 能输出部分能力与机会代理；完整视野、兵线及实际战术意图未必可观测 |
| 阵容取胜路径 | 以上资料与统计的条件化归纳，再做候选比较 | 不是任何静态数据接口直接提供的真值，不宣称精确模拟整局 |

## 3. 机制与静态资料来源

### 3.1 Riot Data Dragon：版本化基础，技能公式不能假定完整

官方[文档](https://developer.riotgames.com/docs/lol#data-dragon)列出版本化英雄、装备等数据，且提示更新可能滞后。本次实际读取[版本列表](https://ddragon.leagueoflegends.com/api/versions.json)，前两项为 `16.21.1`、`16.20.1`。这说明应显式选择目标版本，而不是只请求 latest。

实际读取 [16.20.1 Ahri JSON](https://ddragon.leagueoflegends.com/cdn/16.20.1/data/en_US/champion/Ahri.json)：

- 文件内 `version=16.20.1`，有基础属性与成长、普攻射程、技能 CD、消耗和范围等。
- E 的 tooltip 含未解析的 `charmduration`、`totaldamage` 占位符；对应 `effectBurn` 样本为零值数组，`vars` 为空。
- 因而可以自动导入可核实字段和描述，但不能宣称仅靠这个 JSON 已获得控制时长与伤害的完整公式。

一次普通下载 `16.20.1/item.json` 出现响应截断，本次没有将该响应当作成功解析的证据。正式接入需要下载完整性、JSON 解析与字段覆盖检查。

### 3.2 CommunityDragon：原始机制细，但需要正确解释

项目自己的[说明](https://www.communitydragon.org/docs)区分 RAW 与 CDN，并说明 RAW 提供游戏和客户端解包资料；其[路径文档](https://github.com/CommunityDragon/Docs/blob/master/assets.md)提供脚本可用的 JSON 目录列表，同时明确详细英雄 BIN 数据没有统一的易读格式。

本次验证了下列路径：

- [目标版本元数据](https://raw.communitydragon.org/16.20/content-metadata.json)：返回 `16.20.8248524+branch.releases-16-20.content.release`。
- [Ahri 基本数据](https://raw.communitydragon.org/16.20/plugins/rcp-be-lol-game-data/global/default/v1/champions/103.json)：包含 `tacticalInfo`、`playstyleInfo`、技能描述、range、cooldownCoefficients 与 costCoefficients。
- [Ahri 游戏 BIN JSON](https://raw.communitydragon.org/16.20/game/data/characters/ahri/ahri.bin.json)：包含根技能/子技能、控制标签、数据值、计算节点、施法时间及导弹对象。
- [装备 JSON](https://raw.communitydragon.org/16.20/plugins/rcp-be-lol-game-data/global/default/v1/items.json)：3152 火箭腰带的描述含 10 技能急速，与官方 26.20 公告相符。

阿狸基本资料中的 crowdControl=2、mobility=3 是客户端粗粒度评分，不能当作“控制链稳定性”“进场可靠性”或“克制分数”。技能动态描述仍有占位符，需关联更细数据。

在游戏 BIN 样本中，E 根技能记录具有 `Trait_ImmobilizingCCSpell` 标签，以及 BaseDamage、APRatio、CharmDuration、mSpellCalculations 和 mCastTime；子弹对象具有速度与宽度字段。这支持自动建立部分控制、射程、施法和伤害能力资料。

实际发现的解析陷阱：

- 同一 E 根记录的 `castRange` 为 10000，`castRangeDisplayOverride` 为 975，不能直接把任意 range 字段当作有效命中距离。
- 根记录的 `missileSpeed` 为 1200，子弹对象的速度为 1550，需先识别实际执行对象。
- 部分数组包含多于实际技能等级数量的值，部分字段仍为哈希名；不能简单取前五项或把所有数字当作同一等级口径。
- 文件目录存在不等于每个子文件都在该补丁发生变化；应保留内容哈希与原始元数据，而不是仅凭修改时间推断技能变更。

最初猜测的 `game/characters/...` 和 `global/en_us/...` 路径返回 404；按照项目文档纠正为 `game/data/characters/...` 与 `global/default/...` 后成功。正式实现应通过版本目录和已知索引定位，不以反复猜路径替代发现机制。

即使客户端包含大量公式，也不能推定所有服务端脚本、碰撞行为和特例都完整可计算。应从受支持的公式节点开始，未解析节点保留为 unknown，而不是生成看似精确的伤害或控制链模拟。

### 3.3 Meraki Analytics：结构丰富，但本次 latest 样本明确过期

[项目 README](https://github.com/meraki-analytics/lolstaticdata)说明其从 Wiki 提取技能资料、生成 JSON，并要求缓存以减少 CDN 负载，也承认复杂交互需要额外处理。仓库代码显示 MIT，不应将代码许可直接扩大解释为所有上游游戏素材或 Wiki 内容的许可。

实际读取 [Ahri.json](https://cdn.merakianalytics.com/riot/lol/resources/latest/en-US/champions/Ahri.json)，可见技能效果、leveling/modifiers、targeting、damageType、castTime、速度、宽度、注释等。这个格式可以作为我们规范化机制数据的参考。

但仅有 latest 路径不能证明当前性，本次有内容级反例：

| 对照项 | Meraki latest 实际值 | 官方目标 26.20 | 判断 |
| --- | --- | --- | --- |
| [Kindred W](https://cdn.merakianalytics.com/riot/lol/resources/latest/en-US/champions/Kindred.json) | 正文仍写对野怪 150%；`patchLastChanged=25.S1.3` | 官方将野怪倍率从 150% 调至 165% | 与目标补丁不符 |
| [火箭腰带 3152](https://cdn.merakianalytics.com/riot/lol/resources/latest/en-US/items/3152.json) | `abilityHaste.flat=15`，主动伤害仍为 100 加 10% AP；图标地址含 15.9 | 官方写技能急速 20→10、主动伤害 100+10% AP→135+15% AP | 与目标补丁不符 |

对照依据为[官方 26.20 公告](https://www.leagueoflegends.com/en-us/news/game-updates/league-of-legends-patch-26-20-notes/)。上述文件的 HTTP Last-Modified 也为 2025-04-30，但过期判断主要依据内容不一致，而非仅凭时间头。

因此，本次不推荐直接将 Meraki latest 当作 2026 年目标版本的事实主源。是否存在更新的维护分支、替代发布位置或可稳定重建的生成器，还需单独验证；本次没有安装或运行其生成代码。

### 3.4 League of Legends Wiki：可提取语义的候选，访问未跑通

搜索索引能读取其 [Module:ChampionData/data](https://wiki.leagueoflegends.com/en-us/Module%3AChampionData/data) 与[模板字段说明](https://wiki.leagueoflegends.com/en-us/Template%3AChampion_data)。其中有基础/成长属性、攻速、普攻前摇、角色、能力评分、技能列表和近期版本字段。这表明不是所有信息都只能人工读网页。

但本次直接页面请求受限，普通 MediaWiki API `action=query&meta=siteinfo` 请求返回 403；未获取可用的批量数据或审核通过的访问方式，也未确认适用于所需内容的当前再利用条款。不得把搜索索引可见当作已经跑通程序接入。

如后续能通过站点允许的导出/API 使用，应保留页名、修订号、获取时间与内容范围，并显式区分 PC 召唤师峡谷、Wild Rift、Classic、历史页面和用户草稿。资料中部分“位置”字段有旧更新时间，不能仅因页面近期被抓取就视为最新职业定位。

### 3.5 官方补丁与热修复：自动抽取变化事实

使用[官方补丁目录](https://www.leagueoflegends.com/en-us/news/tags/patch-notes/)及具体公告，按正文分区识别目标模式、实体、旧值、新值、机制调整和热修复日期。

建议先用确定性解析和受来源约束的文本模型产生结构化变更草稿，再与目标版本 JSON 做一致性检查。出现冲突时保留双方来源和状态，禁止由模型凭记忆选一个值填入事实库。未公开或未解析的特例保留未知。

## 4. 抽样清单与证据指纹

以下为本次实际收到并成功解析的响应指纹。原始字节未存入本仓库；指纹和观察记录可用于后续重取比对，但不足以替代原始快照。

| 样本 | HTTP Last-Modified（GMT） | SHA-256 |
| --- | --- | --- |
| [DDragon versions](https://ddragon.leagueoflegends.com/api/versions.json) | 2026-10-20 22:42:59 | `344c1f32acc5af49a90bd10355f8ee6ba59e4119d6797ce0f26e287463e2262a` |
| [DDragon 16.20.1 Ahri](https://ddragon.leagueoflegends.com/cdn/16.20.1/data/en_US/champion/Ahri.json) | 2026-10-06 21:13:50 | `27a17429c2ee4391b190242985ad252e47eb7fe01e016db81c10497ecd4a3cb8` |
| [CDragon 16.20 metadata](https://raw.communitydragon.org/16.20/content-metadata.json) | 2026-10-19 20:31:26 | `ab28af6e79f41825ad5f1f8b9d8f262df1267ce1ce0ea7d77291800484879dcd` |
| [CDragon Ahri basic](https://raw.communitydragon.org/16.20/plugins/rcp-be-lol-game-data/global/default/v1/champions/103.json) | 2026-09-29 00:55:04 | `cb6ff238751de7d5123b3b81447d6e736e75522cbb1941811424ebc9b7490336` |
| [CDragon Ahri BIN](https://raw.communitydragon.org/16.20/game/data/characters/ahri/ahri.bin.json) | 2026-10-19 20:31:31 | `770a7e5b7bdaf1d1de42b7d33a09912a8e56a3244bb0ab2b5d00d94e8b0013a2` |
| [CDragon items](https://raw.communitydragon.org/16.20/plugins/rcp-be-lol-game-data/global/default/v1/items.json) | 2026-10-19 20:36:08 | `6b3e3479ae3c6ffba4d7845f95416897c891f392838ee5fb3671930ddec60c6b` |
| [Meraki Ahri](https://cdn.merakianalytics.com/riot/lol/resources/latest/en-US/champions/Ahri.json) | 2025-04-30 00:13:08 | `22617c532512de0f2faff7b59fb6456a7f3c66640763e7cb18fde258ead2ca55` |
| [Meraki Kindred](https://cdn.merakianalytics.com/riot/lol/resources/latest/en-US/champions/Kindred.json) | 2025-04-30 00:13:12 | `523eb4329e7cc031839bc84cef63ee556c3ed73e7b352b21dc34152e56ac7708` |
| [Meraki item 3152](https://cdn.merakianalytics.com/riot/lol/resources/latest/en-US/items/3152.json) | 2025-04-30 00:17:58 | `5dd7a63063d106068c2a3dbff91358b3b1334da6fe1019c797324059442fdb46` |

这些读取仅证明具体样本在调查时可访问及其字段存在，不证明每个英雄、所有补丁、全部模式或所有公式的正确性和完整率。间歇性 TLS EOF、404、403 和响应截断均保留为来源接入需要处理的失败类型，没有通过绕过限制恢复访问。

## 5. 自动构建知识的推荐流程

1. **版本清单与快照。** 显式选择目标补丁，保存来源原始版本和内容哈希，区分文件获取时间、字段有效时间和热修复。原始数据不依赖 latest 路径保持不变。
2. **统一实体。** 以英雄/装备 ID 与技能槽关联多来源；客户端别名、根技能/子技能和模式分别保留。
3. **直接事实解析。** 数值、等级数组、原生标签、物品价格与配方使用可测试的确定性解析；未支持节点保留，不强行计算。
4. **语义结构化。** 模型或文本规则只从给定描述提取控制类型、目标、命中条件、位移、保护、清线等候选标签；每项附原文定位与置信状态，不使用模型记忆补缺。
5. **条件计算。** 在明确的等级、装备、目标抗性和命中假设下计算受支持的伤害、冷却或控制窗口。计算结果记录假设，不能包装成通用实战强度。
6. **比赛证据学习。** 用版本、位置、玩家与队伍背景等分层信息估计对位和协同；韩服与职业数据分别报告。发力与资源机会从时间截面研究，不从最终局长直接推断。
7. **自动一致性检查。** 比较官方改动与版本 JSON、检查单位/等级范围/引用完整性、检测上游模式混入与内容陈旧；不一致项暂缓进入事实层。
8. **解释与例外。** 排序和解释引用当前可用证据。人工只处理可选反馈或小规模异常抽查；系统不等待用户录完整张知识表才启动。

需要开发的是可复用的字段解析、概念定义、来源校验和更新逻辑，具体英雄事实与关系记录由管道批量生成。一次定义“哪些原生控制字段可以支持某种标签”，与让用户为每个英雄手填标签不同；战术上更强的描述仍应由证据与模型验证。

文本模型优先在知识构建阶段运行，输出来源定位、适用条件和缺失状态，再做确定性校验和冲突检查。BP 时读取已生成的版本快照，避免每次临时联网重建全英雄知识。新补丁触发受影响资料和依赖标签的增量重算，未经版本核验的记录不静默沿用。

建议将生成结果区分为 `observed`（直接来源值）、`derived`（可复现计算）、`inferred`（文本/模型判断）与 `unknown`（缺失或冲突）。这些状态是设计建议，尚未冻结存储格式。

## 6. 访问与使用条件

- Data Dragon 按 Riot 开发者政策与素材使用要求接入，不能把公开素材误当作不受条件约束的数据。
- CDragon 公开提供脚本可用的原始资料和目录接口，但项目[Legal 说明](https://www.communitydragon.org/docs)仍将游戏资产归属 Riot；代码许可证与资产使用条件分开核查。
- Meraki 要求缓存与合理使用；上游包含 Wiki，其仓库 MIT 代码许可不自动消除内容来源的义务。
- Wiki 直接接入本次失败，当前批量访问和许可状态未验收；不通过反爬绕过或搜索结果批量拼装代替正式接入。

## 7. 比赛时间线与对位、协同统计

本节记录比赛数据来源的样本核查。机制资料已经验证的字段不能替代比赛表现证据，也不能自动产生完整的职业克制、组合胜率、发力期和资源控制标签。

### 7.1 已有比赛记录：本地 OE 命名文件与 GPTilt

工作进行期间，`data/` 中出现 2023–2026 年的 `*_LoL_esports_match_data_from_OraclesElixir.csv`。本轮仅只读计算指纹并抽查各文件前 120 行；没有创建、改写或提交这些原始文件。文件名不足以确认下载来源、发布日期或与发布者原件一致性，后续应与 [OE 官方下载入口](https://oracleselixir.com/tools/downloads)核验。

| 本地年度文件 | 字节数 | SHA-256 |
| --- | --- | --- |
| 2023 | 85,839,572 | `efe4d2abe53ec3a19c77196a1a132ee88864f317b1791e544ca9e0077fd47050` |
| 2024 | 79,204,928 | `a2c67680a53c73622cc974db4f534e49e44cc11dab2e5fd5ecfae421f772d865` |
| 2025 | 79,186,324 | `882245414e94e13a9c70f14ed1047a36bffe2279f29526bffe884130d4aaf592` |
| 2026 | 78,775,160 | `4bf862668d7bbfa38fcbcfc38229669b0f7c852f840fe8dcae2c9d599a786662` |

四份表头均为 165 列，包含 gameid、datacompleteness、league、date、patch、side、position、playername、teamname、champion、ban1–5、pick1–5、firstPick，以及 goldat10/15、xpat10/15、csat10/15 和差值等字段。每份前 120 行均对应 10 小局、100 玩家行和 20 队伍行；这些样本的玩家 champion、队伍 pick1/firstPick 有值。应按行类型检查字段，不能把玩家行的 pick1 空值或队伍行的 champion 空值误报为数据缺失。

按正确行类型检查，2024 前 100 玩家行的 goldat15 全空，2025/2026 各有 30/100 空值；这只说明文件头部样本含不完整比赛，不代表整年或目标赛事缺失率。2026 文件首条实际 patch 为 15.24，2024 文件首条为 13.24，不能用年度文件名代替比赛补丁。

这些字段为自动建立对位/同队组合及部分 10/15 分钟表现指标提供候选输入，但 pick1–5 的实际顺序、目标赛事覆盖、跨来源关联和数据发布时间仍待核查。它们不是逐分钟事件流，不能凭这些列恢复连续视野、完整装备购买过程或资源前精确站位。

本次实际读取 [Hugging Face 官方 viewer rows 接口样本](https://datasets-server.huggingface.co/rows?dataset=gptilt%2Flol-esports-matches&config=games&split=train&offset=0&length=20)，HTTP 200；响应声明 games 为 138,402 条记录（单次快照，非官方完整比赛数量）。前 20 条可解析，字段包括 game_id、match_id、tournament、game_number、datetime_utc、patch、双方队伍、结果、picks/bans、vod 和 source_url。首条为 2012 年记录，patch 为空，说明需要逐年检查空值。

响应 SHA-256 为 `5583655d1ea2f64919c51bf0e5188ece72aaab8fcb724fb63a00fedd3a4189c1`。[数据卡](https://huggingface.co/datasets/gptilt/lol-esports-matches)说明 picks 按最终分路排序，因此可以自动生成历史同位置对位、同队组合和交叉对手样本，但不能重建 BP 选取顺序。比赛结果只能支持结果关联，不能直接表示前期压制或资源转化。

另读取 [offset=138382 的末页样本](https://datasets-server.huggingface.co/rows?dataset=gptilt%2Flol-esports-matches&config=games&split=train&offset=138382&length=20)，同样 HTTP 200；末条是 2024-08-31 的 Z10 Scouting Grounds/MaR Showmatch、patch 14.16，响应 SHA-256 为 `9d7012a98c1acc19b7bb7f69feb81f7fdd84a6d6c5b879098da7ebd6e4be9ee2`。分页顺序不是时间顺序，不能用最后一页推断最新覆盖。

按照 [HF 官方 filter 文档](https://huggingface.co/docs/dataset-viewer/filter)，尝试筛选 2026 年并按时间降序读取少量记录，本次请求超时。本轮只验证自动读取和字段结构，没有验收 2026 年 LPL/LCK/Worlds 的完整或最新覆盖；超时也不能解释为这些比赛不存在。

建议先用这些样本生成按补丁、位置和背景分层的关系研究数据，统计相对英雄基线的增量并做平滑和时间验证。由同一局产生的多条关系不是独立比赛样本。训练中可用历史最终分路整理标签，当前 BP 推断不能提前获知当前小局最终分路。

### 7.2 时间线能支持什么：一个历史示例

本次实际读取 [RiotTuxedo 在 2021 年公开的 timeline 示例](https://gist.github.com/RiotTuxedo/ab04ac027546f711ce820faed394295b)，[原始响应](https://gist.githubusercontent.com/RiotTuxedo/ab04ac027546f711ce820faed394295b/raw/b9d7d3ee81ed23705abb490ebec37653b8c63408/response.json)的 SHA-256 为 `9f4ecac66428088a3137ac3db6e9e248ca0ad812f67b3b95d0703f8ede516ff6`。原文含 3 个前导零匿名占位值，不能直接作为严格 JSON；仅在内存将这些零数字占位改为 0 后解析，未把原始文本错误隐藏为成功接入。

该样本有 21 帧，frameInterval 为 60000，帧含 totalGold、xp、level、minionsKilled、jungleMinionsKilled、position、championStats 和 damageStats；事件含装备购买/出售/撤回/销毁、技能升级、史诗野怪击杀、建筑击杀、插眼和排眼等。它支持设计以下派生方向：

- 历史前期经济、经验、补刀和位置截面，以及装备和技能节点的到达时间。
- 对资源击杀、建筑推进及相关事件做版本化时间窗口统计。
- 将机制节点与历史发育轨迹联系，研究条件化的发力窗口。

但该 WARD 事件样例只有创建/击杀者、时间、类型等，没有位置，不能据此恢复完整视野区域；位置截面也不等于连续站位或兵线状态。缺少对应观测时，线权、视野控制和资源逼迫属于代理或推断。

这是 2021 年历史示例，不是当前韩服认证调用，也不是当前职业赛事时间线接入。当前字段、历史可取范围和更新频率需按 [Match-V5 参考](https://developer.riotgames.com/apis#match-v5)及实际 Key 权限另行验收，不预设普通比赛 API 会提供全部职业赛事数据。

### 7.3 已有统计站：方法参考，不作为已确认免费接口

| 来源 | 调查发现 | 适用边界 |
| --- | --- | --- |
| [Lolalytics Ahri counters](https://lolalytics.com/lol/ahri/counters/) | 展示按版本、段位、位置的对位样本和胜率，解释 Delta1/Delta2 相对基线修正 | 可借鉴校正思路；未确认公开导出/API及批量获取条件，不默认抓取 |
| [OP.GG 协同说明](https://help.op.gg/hc/en-us/articles/48465803895065-champions-with-good-synergy) | 自有说明涉及上野、中野、下辅等排位组合关系 | 可借鉴统计维度；不等于已获得底层比赛或对外接口 |
| [BPGG About](https://bpgg.app/en/about) / [FAQ](https://bpgg.app/en/faq) | 自述使用 OE，并提供职业 synergy/counters 等分析 | 与 OE 非独立上游；FAQ 仍有蓝方先选的说明，与 2026 First Selection 不一致，规则和解析不能照搬 |

优先从已经取得可用样本和使用条件的比赛记录自行计算关系，保留基线、样本量和偏差说明。站点展示分数不直接当作训练真值，不通过聚合数据反推出不存在的时间线或完整战术标签。

### 7.4 从记录自动生成关系与时间窗口

1. **同位置对位与局部组合。** 对有可靠历史分路的比赛生成敌对位置配对、同队角色配对及下路四英雄样本，关联补丁、队伍/玩家背景和结果。角色未知、补丁缺失或赛事分类有误的记录按指标要求排除或降级，不强行归类。
2. **结果关系与对线表现分开。** 比赛结果可用于估计配对结果相对基线的变化；有相应时间截面的经济、经验、补刀后，才能研究前期对线表现。仅有最终阵容和胜负时，不生成“前期压制”标签。
3. **装备与等级节点。** 结合版本化装备配方、价格及时间线事件重建历史装备/等级到达节点，处理出售、撤回和销毁，不将第一件购买直接认定为核心装备完成。由这些记录研究情景下的能力窗口，不把幸存到后期的比赛结果当作纯成长能力。
4. **资源事件与代理。** 按版本资源规则建立事件窗口，再关联此前可见的经济、等级、位置及参与事件。若只有稀疏位置快照，输出粗粒度位置/经济代理；不伪造精确兵线、技能可用状态或视野覆盖。
5. **阵容关系。** 在已验证的能力画像和关系统计之上学习或归纳组合交互，保留高阶样本不足、角色不确定和执行条件。多条共现关系或局部优势不能机械相加成为完整阵容真值。

职业与韩服数据保留不同来源类型和统计口径。韩服官方 API 的认证调用和当前样本仍待取得并验收；职业细粒度数据也不能由韩服时间线替代。若免费职业来源只有 10/15 分钟聚合指标，就先研究其支持的范围，后续再评估授权事件流或其他合适来源，不把它写成已经可得。

## 8. 下一步可行性验收

优先做一个小规模自动抽取实验，覆盖若干包含控制、位移、宠物、多形态、成长机制的不同类型英雄与若干装备。输出字段覆盖率、未解析公式、来源冲突、版本不符和自动标签证据，而不是要求用户先手填这些标签。

对于无法从已验证来源直接取得的信息，先标记缺口并缩小功能承诺。后续只在具备对应数据和评估结果时启用伤害模拟、线权代理、复杂组合和资源情景推断。
