# 首批样本集成索引

`data/curated/sample-index.json` 是数据交付索引，不是训练产物，也没有推荐模型。运行：

```sh
python3 scripts/assemble_sample.py
python3 -m unittest discover -s tests -p test_sample_index.py
```

脚本完全离线，读取 replay candidates、match context、rules、patches 和 static-data manifest，按 OE gameid 连接。输出按 gameid 排序，包含 schema_version 与所有输入文件 SHA-256；不写生成时间，因此同输入字节产生同输出字节。

每局保留 OE 与外部源 ID、系列赛、来源定位、两个来源的原始补丁值、候选静态版本和映射状态。14.16→14.16.1 使用 patches.json 的 inferred 状态；OE 16.16 / 16.17 / 16.20 只关联同数字补丁的 `.1` 候选目录，不用临近或最新版本回填。26.x 与16.x 仍不视为官方已验证的等价映射；候选静态资料不证明赛事服务器或热修复构建一致。

只有 static-data manifest 列出的成功产物可以使用。脚本核对每项产物 SHA-256、对应成功下载记录的 source_snapshot_sha256 和原始文件 SHA-256，缺值或不一致立即报错。英雄名在同候选版本的成功 en_US 英雄目录中精确匹配 aliases/name，其次允许唯一 casefold 匹配；输出稳定数字 ID 与匹配方法，歧义/缺失保留 unknown。

规则适用性与事实字段分别保留：2024 LCK 主样本规则仍为 inferred；2026 LCK 规则要求比赛日期不早于7月29日并属于 Season Playoffs；Worlds 的 observed 文档仍含未知 Fearless / draft template；LPL 保留 unknown。全局 First Selection 公告仅作为候选补充，不能填补赛事专属未知规则。规则观察不证明任何一局历史 BP 步骤。

readiness 独立报告 context、source_data、entities_same_candidate_version、rules_complete、bp_verified 和 replay_ready。实体解析成功只说明候选目录里有唯一数字身份；映射/赛事构建仍未确认时继续保留 blocker。bp_verified 只来自[逐手验证器](bp-validation.md)的 `verified` 结果，bp_validator_status 照录其状态；即使两个来源的字符串标记为 verified 也不会升格。索引读取 `bp-validation.json` 前核对其记录的输入哈希，过期即报错。context 的 source_record_verified 只证明关联，本轮全部 replay_ready=false。WLDs 标签只有在已关联的核验上下文明确为 World Championship/Worlds 且不含 Regional Qualifier 时才套用 Worlds 规则，否则保留 unknown_pending。

测试覆盖错版本隔离、manifest 哈希冲突拒绝、上下文不能提升未验证 BP、未知规则保留、唯一 casefold 和未知实体处理。

本轮实际集成 **42 局**，校验 static manifest 的 **74 个成功产物**及其对应原始快照。42 局 context 与源结构检查通过；839 个按局去重的选禁英雄名称均在各自候选补丁目录映射到数字 ID。这是身份解析覆盖，不表示赛事构建映射已核实，也不表示全部静态端点可用（16.16/16.17 中文符文仍失败）。

规则完整就绪 0、BP 验证就绪 0、可回放就绪 0。全部42局保留规则不完整/推断与BP未核验 blocker；31局保留14.16静态版本映射 inferred，11局保留2026数字版本候选与赛事构建未核验。2026规则候选按赛事分别展示 observed/unknown，未把LPL全局First Selection公告升级为完整赛事规则。

11项离线单测通过。连续两次生成输出 SHA-256 相同，验证同输入确定性；最终交付应以索引内 input_sha256 重新核对当前输入，任何输入变化后重新运行此命令。
