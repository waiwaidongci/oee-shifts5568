import {heading} from '../components/common/header.js';
import {improveResult} from '../components/improve.js';
import {table} from '../components/common/table.js';
import {status} from '../components/common/status.js';
import {esc,fmt} from '../utils/format.js';
import {loadInventory} from '../api/business.js';
import {action} from '../hooks/action.js';
import {store,reload} from '../stores/business.js';

const rerender=()=>window.dispatchEvent(new Event('hashchange'));

export function improvements(c,d){
 const measures=d.measures||[];const runs=d.improveruns||[];
 const selected=runs.find(r=>r.id===store.selectedImprove)||runs[0];
 return heading('UPTIME INVESTMENT / 05','停机改善测算与预算组合',
  '为措施登记费用与可消除的停机记录；同班同分钟的重叠停机全部消除才计恢复，按班次节拍折理论产量，在预算内穷举证明全局最优，限时30秒、超时拒绝发布。')
 +`<details open id="measure-panel"><summary>措施台账：费用 + 可消除的停机记录</summary>
  <div id="inventory-box"><p class="empty">选择期间后加载停机记录目录，再勾选记录组成措施。</p></div>
  <form id="measure-form">
   <div class="form-grid">
    <label>措施编号（留空新增）<input name="id" type="number" min="1"></label>
    <label>措施名称（2-120字）<input name="name" required minlength="2" maxlength="120" placeholder="如：更换主轴轴承"></label>
    <label>费用（元）<input name="cost" type="number" step="0.01" min="0" value="1000" required></label>
   </div>
   <p>在上方目录勾选本措施能消除的停机记录（可跨班次多选），已选 <b id="target-count">0</b> 条。</p>
   <div id="target-picked" class="method" style="font-size:11px"></div>
   <button>保存措施</button>
   <button type="button" id="reload-inventory">刷新停机目录</button>
  </form>
  <h3>已登记措施</h3>
  ${table(measures.map(m=>({编号:m.id,措施:m.name,费用:m.cost,
    '消除记录数':m.targets.length,状态:m.active?'启用':'停用',
    '记录':m.targets.map(t=>'底稿#'+t.source_id+'/停机'+(t.interval_index+1)).join('，')})))}
  <div>${measures.map(m=>`<button type="button" class="toggle measure-toggle" data-id="${m.id}">${m.active?'停用':'启用'} #${m.id} ${esc(m.name)}</button>`).join('')}</div>
 </details>
 <details open><summary>提交改善测算（冻结同一时点依据，排队由 worker 求解）</summary>
  <form id="improve-form" class="inline-form">
   <label>任务名称<input name="name" value="${esc(c.title.slice(0,2))}停机改善测算" required minlength="2"></label>
   <label>预算（元）<input name="budget" type="number" step="0.01" min="0" value="5000" required></label>
   <label>期间<select name="period"><option>全部</option>${d.periods.map(p=>`<option>${esc(p.name)}</option>`).join('')}</select></label>
   <div style="flex-basis:100%">
    <p style="font-size:12px;color:var(--muted)">勾选参与测算的启用措施（单次最多30项）：</p>
    <div id="measure-pick" class="weekday-row">${measures.filter(m=>m.active).map(m=>`<label class="weekday"><input type="checkbox" name="m" value="${m.id}">#${m.id} ${esc(m.name)}（${fmt(m.cost)}元）</label>`).join('')||'<span class="empty">暂无启用措施</span>'}</div>
   </div>
   <button>排队测算（限时30秒）</button>
  </form>
 </details>
 <div class="run-layout">
  <aside class="run-list">
   <p class="eyebrow">历史测算（可查）</p>
   ${runs.map(r=>`<button class="select-improve" data-id="${r.id}">${esc(r.name)} ${status(r.status)}</button>`).join('')||'<p class="empty">尚无测算</p>'}
  </aside>
  <div>${improveResult(selected)}</div>
 </div>`;
}

export function bindImprovements(){
 const panel=document.querySelector('#measure-panel');
 if(!panel)return;
 const periodSel=document.querySelector('#improve-form select[name=period]');
 async function loadInv(){
  await action(async()=>{
   const groups=await loadInventory(periodSel?periodSel.value:'全部');
   const box=document.querySelector('#inventory-box');
   if(!groups.length){box.innerHTML='<p class="empty">该期间没有底稿停机记录。</p>';return}
   box.innerHTML=groups.map(g=>`<fieldset><legend>${esc(g.period)} · ${esc(g.department)}（底稿#${g.source_id}，理想 ${g.ideal_seconds} 秒/件）</legend>
    ${g.intervals.map(iv=>`<label class="weekday"><input type="checkbox" class="target-cb" data-source="${g.source_id}" data-index="${iv.interval_index}">
    停机记录 ${iv.interval_index+1}：第 ${iv.start}–${iv.end} 分钟（共 ${iv.end-iv.start} 分钟）</label>`).join('')}</fieldset>`).join('');
   syncPicked();
  });
 }
 function syncPicked(){
  const cbs=[...document.querySelectorAll('.target-cb:checked')];
  document.querySelector('#target-count').textContent=cbs.length;
  document.querySelector('#target-picked').textContent=cbs.map(cb=>'底稿#'+cb.dataset.source+'/停机'+(Number(cb.dataset.index)+1)).join('，')||'未勾选';
 }
 loadInv();
 document.querySelector('#reload-inventory').onclick=e=>{e.preventDefault();loadInv()};
 if(periodSel)periodSel.onchange=()=>loadInv();
 document.querySelector('#inventory-box').onchange=e=>{if(e.target.classList.contains('target-cb'))syncPicked()};

 document.querySelector('#measure-form').onsubmit=e=>{
  e.preventDefault();
  action(async()=>{
   const f=e.target;const b=Object.fromEntries(new FormData(f));
   const targets=[...document.querySelectorAll('.target-cb:checked')].map(cb=>({source_id:Number(cb.dataset.source),interval_index:Number(cb.dataset.index)}));
   if(!targets.length)throw Error('请至少勾选一条停机记录');
   const {saveMeasure}=await import('../api/business.js');
   await saveMeasure({name:b.name,cost:Number(b.cost),targets},b.id?Number(b.id):null);
   await reload();rerender();
  });
 };
 document.querySelectorAll('.measure-toggle').forEach(btn=>btn.onclick=()=>action(async()=>{
  const {toggleMeasure}=await import('../api/business.js');
  await toggleMeasure(Number(btn.dataset.id));await reload();rerender();
 }));
 document.querySelector('#improve-form').onsubmit=e=>{
  e.preventDefault();
  action(async()=>{
   const f=e.target;const b=Object.fromEntries(new FormData(f));
   const measure_ids=[...f.querySelectorAll('input[name=m]:checked')].map(x=>Number(x.value));
   if(!measure_ids.length)throw Error('请至少勾选一项措施');
   if(measure_ids.length>30)throw Error('单次测算最多30项措施');
   const {submitImprove}=await import('../api/business.js');
   const created=await submitImprove({name:b.name,budget:Number(b.budget),period:b.period,measure_ids});
   store.selectedImprove=created.id;await reload();rerender();
  });
 };
 document.querySelectorAll('.select-improve').forEach(btn=>btn.onclick=()=>{
  store.selectedImprove=Number(btn.dataset.id);rerender();
 });
}
