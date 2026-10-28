import type { Champion, GameDetail, RuleField, Rules } from '../types';
import { ChampionIcon } from './ChampionIcon';
import { FEARLESS, STATUS, reasonText } from '../labels';

function Status({ field }: { field: RuleField<unknown> }) {
  const s = STATUS[field.status] ?? { text: field.status, tone: 'muted' as const };
  return <span className={`badge ${s.tone}`} title={field.source}>{s.text}</span>;
}

interface Props { detail: GameDetail; rules: Rules; champions: Record<string, Champion> }

export function RulesPanel({ detail, rules, champions }: Props) {
  const source = detail.sequence_source;
  const byName = Object.fromEntries(Object.values(champions).map((c) => [c.name.toLowerCase(), c]));
  return (
    <div className="panel">
      <h3>规则与证据</h3>
      <dl className="facts">
        <dt>赛事</dt><dd>{rules.tournament ?? <span className="muted">未关联</span>}</dd>
        <dt>选禁模板</dt><dd>20 步蛇形 <Status field={rules.template} /></dd>
        <dt>跨局限制</dt><dd>{FEARLESS[rules.fearless.value] ?? rules.fearless.value} <Status field={rules.fearless} /></dd>
        <dt>赛事禁用</dt><dd>{rules.disabled_champions.value.length ? rules.disabled_champions.value.map((n) => byName[n.toLowerCase()]?.name_zh ?? n).join('、') : (rules.disabled_champions.status === 'unknown' ? '未取得' : '无')} <Status field={rules.disabled_champions} /></dd>
        <dt>顺序来源</dt>
        <dd>
          {source.type === 'leaguepedia'
            ? <span title={source.locator}>Leaguepedia 逐手表（rev {source.revid}）</span>
            : <span title={source.note}>OE 列按模板排布{source.measured_agreement ? `（实测一致率 ${(source.measured_agreement * 100).toFixed(2)}%）` : ''}</span>}
          {source.conflict && <span className="badge warn" title="Leaguepedia 与 OE 最终阵容不一致">来源冲突</span>}
        </dd>
        <dt>系列赛</dt><dd>第 {detail.series.position} 局{detail.series.prior_status !== 'complete' && <span className="badge warn">前序局不全</span>}</dd>
      </dl>
      {detail.series.consumed.length > 0 && (
        <>
          <h4>前局已选（{detail.series.consumed.length}）</h4>
          <div className="consumed">{detail.series.consumed.map((id) => <ChampionIcon key={id} champion={champions[id]} rawId={id} size={26} />)}</div>
        </>
      )}
      {detail.replay_findings.length > 0 && (
        <>
          <h4>历史记录与规则不一致</h4>
          <ul className="findings">
            {detail.replay_findings.map((f) => (
              <li key={f.step}>第 {f.step} 步：{[...f.reasons, ...(f.warnings ?? [])].map(reasonText).join('；')}</li>
            ))}
          </ul>
          <p className="muted small">历史照原样回放；不一致可能来自记录错误或规则假设不成立。</p>
        </>
      )}
    </div>
  );
}
