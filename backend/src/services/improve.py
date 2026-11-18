import hashlib,json,time
from fastapi import HTTPException
from src.models.source import Source
from src.models.run import ImproveMeasure,ImproveRun
from src.services.audit import log
from src.services.optimizer import (validate_measure,build_inventory,optimize,
 greedy_compare,SOLVE_LIMIT_SECONDS)
from src.config.settings import REDIS_URL
import redis


def list_measures(db,active_only=False):
 q=db.query(ImproveMeasure).order_by(ImproveMeasure.id)
 if active_only:q=q.filter(ImproveMeasure.active==True)
 return q.all()


def save_measure(db,user,name,cost,targets,id=None):
 validate_measure(name,cost,targets)
 name=name.strip()
 dup=db.query(ImproveMeasure).filter(ImproveMeasure.name==name)
 if id is None:
  if dup.first():raise HTTPException(409,'措施名称已存在')
  obj=ImproveMeasure(name=name,cost=float(cost),targets=targets,active=True,created=time.time())
  db.add(obj)
 else:
  obj=db.get(ImproveMeasure,id)
  if not obj:raise HTTPException(404,'措施不存在')
  if dup.filter(ImproveMeasure.id!=id).first():raise HTTPException(409,'措施名称已存在')
  obj.name=name;obj.cost=float(cost);obj.targets=targets
 log(db,user.email,'measure.update' if id else 'measure.create',name)
 db.commit();return obj


def toggle_measure(db,user,id):
 obj=db.get(ImproveMeasure,id)
 if not obj:raise HTTPException(404,'措施不存在')
 obj.active=not obj.active
 log(db,user.email,'measure.toggle','%s:%s'%(obj.name,obj.active));db.commit();return obj


def target_inventory(db,period):
 """供前端勾选：按班次分组列出全部停机记录，含冻结用source_id与interval_index。"""
 q=db.query(Source).order_by(Source.id)
 rows=[x for x in q.all() if period=='全部' or x.data.get('period')==period]
 groups=[]
 for x in rows:
  d=x.data
  groups.append({'source_id':x.id,'natural_key':x.natural_key,'period':d['period'],
   'department':d['department'],'ideal_seconds':d['ideal_seconds'],
   'shift_start':d['start'],'shift_end':d['end'],
   'intervals':[{'interval_index':i,'start':p[0],'end':p[1]} for i,p in enumerate(d['downtime'])]})
 return groups


def _freeze(db,measure_ids,period,budget):
 sources=[]
 for x in db.query(Source).order_by(Source.id).all():
  if period=='全部' or x.data.get('period')==period:
   d=dict(x.data);d['_id']=x.id;sources.append(d)
 if not sources:raise HTTPException(422,'所选期间没有底稿')
 measures=[]
 for mid in measure_ids:
  m=db.get(ImproveMeasure,mid)
  if not m:raise HTTPException(404,'措施 #%s 不存在'%mid)
  if not m.active:raise HTTPException(422,'措施“%s”已停用，不能参与测算'%m.name)
  # 同一事务内校验目标全部仍落在当前底稿与所选期间上
  for t in m.targets:
   s=next((x for x in sources if x['_id']==t['source_id']),None)
   if s is None:
    raise HTTPException(422,'措施“%s”引用的底稿#%s不在所选期间，请调整期间或重新勾选'%m.name,t['source_id'])
   if t['interval_index']>=len(s['downtime']):
    raise HTTPException(422,'措施“%s”引用的停机记录已被底稿修改，请重新勾选后再排队'%m.name)
  measures.append({'id':m.id,'name':m.name,'cost':float(m.cost),'targets':m.targets})
 if not measures:raise HTTPException(422,'请至少选择一项改善措施')
 inventory=build_inventory(sources,sorted({s['_id'] for s in sources}))
 snapshot={'period':period,'budget':float(budget),'frozen_at':time.time(),
  'sources':sources,'measures':measures,'target_inventory':inventory}
 checksum=hashlib.sha256(json.dumps(snapshot,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
 return snapshot,checksum


def submit(db,user,body):
 if body.budget<0:raise HTTPException(422,'预算不可为负')
 if not body.measure_ids:raise HTTPException(422,'请至少选择一项改善措施')
 if len(body.measure_ids)>30:raise HTTPException(422,'单次测算最多30项措施，以保证限时内证明全局最优；请分组测算')
 if len(set(body.measure_ids))!=len(body.measure_ids):raise HTTPException(422,'措施不可重复选择')
 snapshot,checksum=_freeze(db,body.measure_ids,body.period,body.budget)
 obj=ImproveRun(name=body.name,status='queued',budget=float(body.budget),
  snapshot=snapshot,checksum=checksum,created=time.time())
 db.add(obj);log(db,user.email,'improve.queue',body.name);db.commit()
 redis.Redis.from_url(REDIS_URL).rpush('improve-jobs',obj.id)
 return obj


def execute(db,run_id):
 obj=db.get(ImproveRun,run_id)
 if not obj or obj.status!='queued':return
 obj.status='running';db.commit()
 try:
  snap=obj.snapshot
  sources=snap['sources'];measures=snap['measures'];budget=snap['budget']
  # 依据冻结快照重算，措施并发修改不影响本次任务
  res=optimize(measures,sources,budget,SOLVE_LIMIT_SECONDS)
  if res['timed_out']:
   obj.status='failed'
   obj.error='限时%.0f秒内未能证明全局最优，按规则拒绝发布；请减少措施数量后重新排队'%SOLVE_LIMIT_SECONDS
   db.commit();return
  chosen_idx=res['chosen']
  chosen_measures=[{'measure_id':measures[i]['id'],'name':measures[i]['name'],
   'cost':measures[i]['cost'],
   'targets':measures[i]['targets']} for i in chosen_idx]
  total_cost=round(sum(measures[i]['cost'] for i in chosen_idx),6)
  # 逐条恢复依据：分钟、班次、被消除的停机记录
  basis=[]
  for sid,blk in res['minute_index'].items():
   for piece in res['intervals'].get(sid,[]):
    meta=blk['meta']
    basis.append({'source_id':sid,'period':meta['period'],'department':meta['department'],
     'start_minute':piece['start'],'end_minute':piece['end'],'minutes':piece['minutes'],
     'ideal_seconds':meta['ideal_seconds'],
     'theoretical_pieces':round(piece['minutes']*60.0/meta['ideal_seconds'],6),
     'eliminated_interval_index':piece['eliminated_interval_index'],
     'rule':'该分钟同班全部重叠停机记录均被组合内措施消除才计恢复'})
  shift_rows=sorted(res['shift_stats'].values(),key=lambda v:(v['period'],v['department']))
  for v in shift_rows:v['theoretical_pieces']=round(v['theoretical_pieces'],6)
  greedy=greedy_compare(measures,sources,budget,res['pieces'])
  obj.result={'budget':budget,'total_cost':total_cost,'budget_remaining':round(budget-total_cost,6),
   'chosen_measures':chosen_measures,
   'recovered_minutes':res['minutes'],
   'recovered_pieces':round(res['pieces'],6),
   'shift_rows':shift_rows,'recovery_basis':basis,
   'greedy_compare':{**greedy,
    'note':'按单项收益排序逐项选入：名义合计把同班同分钟的重叠恢复重复计数（高估），又无法表达“多条记录齐消才恢复”的协同分钟（低估），与去重恢复量并陈供核对，结论以全局最优为准'},
   'solver':{'algorithm':'分支限界穷举（覆盖态最小费用记忆化+支配措施剪枝+费用剪枝+贪心并集可采纳上界），证明全局最优',
    'elapsed_seconds':round(res['elapsed'],4),'limit_seconds':SOLVE_LIMIT_SECONDS,
    'candidate_count':len(measures),'dominated_count':len(res['dominated']),
    'evaluated_states':res['evaluated_states'],'combination_space':2**len(measures)},
   'method':'同班同一分钟上的全部重叠停机记录都被所选措施消除，该分钟才计恢复；恢复分钟×60/理想秒折理论产量；在预算约束下穷举组合取全局最优，不以单项收益排序代替。'}
  obj.status='completed'
 except Exception as exc:
  obj.status='failed';obj.error=str(exc)
 db.commit()
