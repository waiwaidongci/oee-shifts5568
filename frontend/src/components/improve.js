import {esc,fmt,time} from '../utils/format.js';
import {table} from './common/table.js';
import {status} from './common/status.js';

export function improveResult(run){
 if(!run)return '<p class="empty">选择一次测算查看组合、费用与逐分钟恢复依据。</p>';
 const r=run.result;
 return `<section class="report">
 <div class="report-top"><h2>${esc(run.name)}</h2>${status(run.status)}</div>
 <p>预算 ${fmt(run.budget)} · 提交于 ${time(run.created)}</p>
 <p class="checksum">冻结依据 SHA256 ${esc(run.checksum)}</p>
 ${run.error?'<p class="error">'+esc(run.error)+'</p>':''}
 ${r?`
 <div class="metrics">
  <div><small>组合费用</small><strong>${fmt(r.total_cost)}</strong></div>
  <div><small>预算余量</small><strong>${fmt(r.budget_remaining)}</strong></div>
  <div><small>恢复停机分钟</small><strong>${fmt(r.recovered_minutes)}</strong></div>
  <div><small>折理论产量（件）</small><strong>${fmt(r.recovered_pieces)}</strong></div>
  <div><small>入选措施</small><strong>${r.chosen_measures.length}</strong></div>
 </div>
 <p class="method">${esc(r.method)}</p>
 <h3>全局最优组合（预算内）</h3>
 ${table(r.chosen_measures.map(m=>({措施:m.name,费用:m.cost,
   '消除停机记录数':m.targets.length,
   '记录明细':m.targets.map(t=>'底稿#'+t.source_id+'/停机'+(t.interval_index+1)).join('，')})))}
 <h3>按班次节拍折算</h3>
 ${table(r.shift_rows.map(v=>({日期:v.period,设备:v.department,
   '恢复分钟':v.recovered_minutes,'理想秒/件':v.ideal_seconds,
   '理论产量（件）':v.theoretical_pieces})))}
 <h3>逐分钟恢复依据</h3>
 <p class="method">每条为一段连续恢复区间；该区间内每一分钟的同班全部重叠停机记录（下列编号）均被组合内措施消除，才计入恢复。</p>
 ${table(r.recovery_basis.map(b=>({日期:b.period,设备:b.department,
   '起分钟':b.start_minute,'止分钟(不含)':b.end_minute,'分钟数':b.minutes,
   '理想秒/件':b.ideal_seconds,'理论件':b.theoretical_pieces,
   '消除的停机记录序号':b.eliminated_interval_index.map(i=>i+1).join('、')})))}
 <h3>与单项收益排序的对照</h3>
 <p class="warning">${esc(r.greedy_compare.note)}</p>
 ${table([{
   '口径':'按单项收益排序逐项选入',
   '选入措施':r.greedy_compare.chosen.join('，'),
   '费用':r.greedy_compare.cost,
   '名义单项收益合计(件)':r.greedy_compare.nominal_sum_pieces,
   '同口径去重恢复(件)':r.greedy_compare.pieces},
  {'口径':'全局最优组合（本测算结论）','选入措施':r.chosen_measures.map(m=>m.name).join('，'),
   '费用':r.total_cost,'名义单项收益合计(件)':'—','同口径去重恢复(件)':r.recovered_pieces}]
 )}
 <details><summary>求解器与限时保证</summary>
  <p class="method">${esc(r.solver.algorithm)}；候选 ${r.solver.candidate_count} 项、支配剔除 ${r.solver.dominated_count} 项、
  评估覆盖态 ${r.solver.evaluated_states} 个、组合空间 2^${r.solver.candidate_count}=${fmt(r.solver.combination_space)}；
  用时 ${r.solver.elapsed_seconds}s / 限时 ${r.solver.limit_seconds}s，限时内证优才发布，超时拒绝。</p>
 </details>
 <details><summary>冻结快照（底稿、措施与预算的同一时点依据）</summary>
  <pre style="white-space:pre-wrap;overflow-wrap:anywhere;font-size:11px">${esc(JSON.stringify({budget:run.budget,
   period:run.snapshot.period,frozen_at:new Date(run.snapshot.frozen_at*1000).toISOString(),
   measures:run.snapshot.measures.map(m=>({name:m.name,cost:m.cost,targets:m.targets})),
   sources:run.snapshot.sources.map(s=>({source_id:s._id,period:s.period,department:s.department,
     ideal_seconds:s.ideal_seconds,downtime:s.downtime}))},null,2))}</pre>
 </details>`:''}
 </section>`;
}
