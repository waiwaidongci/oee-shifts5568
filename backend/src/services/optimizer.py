import time
from src.services.validation import number

# 30秒确认最优：worker内部再留2秒余量做落库与序列化
SOLVE_LIMIT_SECONDS=28.0


def validate_measure(name,cost,targets):
 if not isinstance(name,str) or not 2<=len(name.strip())<=120:
  raise ValueError('措施名称需为2-120字')
 number(cost,'措施费用',minimum=0)
 if not isinstance(targets,list) or not targets:
  raise ValueError('措施至少勾选一条停机记录')
 if len(targets)>2000:
  raise ValueError('单措施消除记录过多')
 seen=set()
 for t in targets:
  if not isinstance(t,dict) or set(t)!={'source_id','interval_index'}:
   raise ValueError('停机记录标识必须为 source_id 与 interval_index')
  if not isinstance(t['source_id'],int) or not isinstance(t['interval_index'],int) or t['interval_index']<0:
   raise ValueError('停机记录标识不合法')
  key=(t['source_id'],t['interval_index'])
  if key in seen: raise ValueError('措施内存在重复停机记录')
  seen.add(key)


def build_inventory(sources,source_ids):
 """冻结快照内的停机记录目录：每条=某班次的一个停机区间（同分钟重叠为不同记录）。"""
 by_id={s['_id']:s for s in sources}
 inventory=[]
 for sid in source_ids:
  s=by_id.get(sid)
  if not s: raise ValueError('底稿已被删除或修改，无法冻结同一时点依据，请刷新后重排')
  for idx,pair in enumerate(s['downtime']):
   a,b=int(pair[0]),int(pair[1])
   if b<=a: raise ValueError('停机区间不合法：%s'%([pair]))
   inventory.append({'target_id':len(inventory),'source_id':sid,'interval_index':idx,
    'period':s['period'],'department':s['department'],
    'start':a,'end':b,'ideal_seconds':s['ideal_seconds'],
    'shift_start':int(s['start']),'shift_end':int(s['end'])})
 return inventory


def _shift_map(sources):
 out={}
 for s in sources:
  out[s['_id']]={'period':s['period'],'department':s['department'],
   'ideal_seconds':s['ideal_seconds'],'start':int(s['start']),'end':int(s['end']),
   'intervals':[(max(int(s['start']),int(a)),min(int(s['end']),int(b))) for a,b in s['downtime'] if min(int(s['end']),int(b))>max(int(s['start']),int(a))]}
 return out


def build_minute_index(sources):
 """
 位掩码索引：每条停机记录分配一个全局位；每个整数分钟桶存覆盖该分钟的记录位掩码。
 同班同分钟多条重叠各自占一位 -> 子集是否恢复该分钟只需一次位运算。
 """
 shifts=_shift_map(sources)
 index={};rid=0
 for sid,sh in shifts.items():
  local_to_global={}
  for idx in range(len(sh['intervals'])):
   local_to_global[idx]=rid;rid+=1
  buckets={}  # minute -> 覆盖记录位掩码
  for idx,(a,b) in enumerate(sh['intervals']):
   bit=1<<local_to_global[idx]
   for m in range(a,b):
    buckets[m]=buckets.get(m,0)|bit
  index[sid]={'meta':sh,'local_to_global':local_to_global,'buckets':buckets}
 return index


def _resolve_targets(measures,minute_index):
 target_sets=[]
 for m in measures:
  bits=0
  for t in m['targets']:
   blk=minute_index.get(t['source_id'])
   if not blk or t['interval_index'] not in blk['local_to_global']:
    raise ValueError('措施“%s”引用的停机记录已不存在，请刷新后重排'%m['name'])
   bits|=1<<blk['local_to_global'][t['interval_index']]
  target_sets.append(bits)
 return target_sets


def evaluate(chosen,target_bits,minute_index):
 """评估一组措施：仅当某分钟的全部重叠停机记录位都被消除（cover 包含 need）时，该分钟才计恢复。"""
 cover=0
 for mi in chosen: cover|=target_bits[mi]
 shift_stats={};recovered_intervals={}
 for sid,blk in minute_index.items():
  buckets=blk['buckets'];meta=blk['meta']
  recovered=sorted(m for m,need in buckets.items() if need & ~cover==0)
  if not recovered: continue
  pieces=[];lo=prev=recovered[0]
  for m in recovered[1:]:
   if m==prev+1: prev=m
   else: pieces.append((lo,prev+1));lo=prev=m
  pieces.append((lo,prev+1))
  global_to_local={g:l for l,g in blk['local_to_global'].items()}
  pieces_out=[]
  for a,b in pieces:
   rec_bits=0
   for m in range(a,b): rec_bits|=buckets[m]
   eliminated=sorted(global_to_local[g] for g in global_to_local if (rec_bits>>g)&1)
   pieces_out.append({'start':a,'end':b,'minutes':b-a,'eliminated_interval_index':eliminated})
  minutes=len(recovered);rate=60.0/meta['ideal_seconds']
  shift_stats[sid]={'source_id':sid,'period':meta['period'],'department':meta['department'],
   'recovered_minutes':minutes,'ideal_seconds':meta['ideal_seconds'],
   'theoretical_pieces':minutes*rate}
  recovered_intervals[sid]=pieces_out
 total_minutes=sum(v['recovered_minutes'] for v in shift_stats.values())
 total_pieces=sum(v['theoretical_pieces'] for v in shift_stats.values())
 return total_pieces,total_minutes,shift_stats,recovered_intervals


def _global_buckets(minute_index):
 """聚合为 (need_mask, 每分钟理论件率合计)；同need的分钟只做一次位运算。"""
 agg={}
 for blk in minute_index.values():
  rate=60.0/blk['meta']['ideal_seconds']
  for need in blk['buckets'].values():
   agg[need]=agg.get(need,0.0)+rate
 return list(agg.items())


def _cover_value(cover,buckets):
 total=0.0
 for need,weight in buckets:
  if need & ~cover==0: total+=weight
 return total


def optimize(measures,sources,budget,deadline):
 """
 预算内全局最优组合。措施收益因同分钟重叠而不可加，无法用普通背包DP，
 采用分支限界穷举证明全局最优：覆盖态最小费用记忆化 + 支配措施剪枝 + 费用剪枝
 + 贪心并集上界（预算内可行贪心解，天然含协同，恒不超过最优值）；限时未证优返回timeout。
 """
 t0=time.time()
 minute_index=build_minute_index(sources)
 target_bits=_resolve_targets(measures,minute_index)
 buckets=_global_buckets(minute_index)
 n=len(measures);costs=[float(m['cost']) for m in measures]

 # 支配剪枝：j覆盖⊆i覆盖且i费用≤j费用（至少一项严格），则j永不入选
 dominated=set()
 for j in range(n):
  for i in range(n):
   if i==j or j in dominated: continue
   if (target_bits[j] & ~target_bits[i])==0 and costs[i]<=costs[j] and (target_bits[i]!=target_bits[j] or costs[i]<costs[j] or i<j):
    dominated.add(j);break
 active=[i for i in range(n) if i not in dominated];k=len(active)

 memo={}
 def value(cover):
  v=memo.get(cover)
  if v is None: v=_cover_value(cover,buckets);memo[cover]=v
  return v

 standalone={i:value(target_bits[i]) for i in active}
 # DFS分支序按单位费用独立收益降序，先找到高质量incumbent
 active.sort(key=lambda i:(-(standalone[i]/costs[i]) if costs[i]>0 else -standalone[i]))
 best_cover=0;best_value=0.0;best_cost=0.0;best_mask=0;timed_out=False
 # 同(pos,cover)只保留最小费用的一次到达：更高费用到达可走的子树是其子集且预算更紧，必不更优
 seen_spent={}

 def optimistic(cover,spent,pos):
  """
  贪心并集上界：从当前覆盖出发，在剩余且买得起的措施中反复选“新增恢复折件/费用”最高者，
  直到无措施可加。每一步都是预算内可行决策，结果是一个真实可行组合的去重恢复值，
  故恒不超过全局最优值（可采纳）；增量按并集计算，完整包含同分钟协同效应。
  """
  cv=cover;room=budget-spent;used=set()
  while True:
   base=value(cv);bi=None;bg=-1.0
   for q in range(pos,k):
    i=active[q]
    if i in used or costs[i]>room+1e-9: continue
    gain=value(cv|target_bits[i])-base
    if gain<=1e-12: continue
    score=gain/costs[i] if costs[i]>0 else float('inf')
    if score>bg: bg=score;bi=i
   if bi is None: break
   used.add(bi);cv|=target_bits[bi];room-=costs[bi]
  return value(cv)

 def dfs(pos,mask,cover,spent):
  nonlocal best_cover,best_value,best_cost,best_mask,timed_out
  if time.time()-t0>deadline:
   timed_out=True;return
  key=(pos,cover)
  prior=seen_spent.get(key)
  if prior is not None and prior<=spent+1e-12:return
  seen_spent[key]=spent
  v=value(cover)
  if v>best_value+1e-12 or (abs(v-best_value)<=1e-12 and spent<best_cost):
   best_cover,best_value,best_cost,best_mask=cover,v,spent,mask
  if pos==k: return
  # 可采纳上界严格低于当前最优才剪枝；等值分支保留，以找到同恢复量下费用更低的组合
  if optimistic(cover,spent,pos)<best_value-1e-9: return
  i=active[pos]
  # 选
  if spent+costs[i]<=budget+1e-9:
   dfs(pos+1,mask|(1<<i),cover|target_bits[i],spent+costs[i])
   if timed_out:return
  # 不选
  dfs(pos+1,mask,cover,spent)

 dfs(0,0,0,0.0)
 chosen=[i for i in range(n) if best_mask>>i&1]
 pieces,minutes,shift_stats,intervals=evaluate(chosen,target_bits,minute_index)
 return {'chosen':chosen,'pieces':pieces,'minutes':minutes,'shift_stats':shift_stats,
  'intervals':intervals,'timed_out':timed_out,'elapsed':time.time()-t0,
  'target_bits':target_bits,'minute_index':minute_index,'costs':costs,
  'dominated':sorted(dominated),'evaluated_states':len(seen_spent)}


def greedy_compare(measures,sources,budget,optimal_pieces):
 """按单项收益排序逐个塞入预算；同时给出名义合计（独立收益直接相加，重叠被重复计数）与去重恢复，供核对单项口径的偏差。"""
 minute_index=build_minute_index(sources)
 target_bits=_resolve_targets(measures,minute_index)
 ranked=sorted(range(len(measures)),key=lambda i:-evaluate([i],target_bits,minute_index)[0])
 chosen=[];spent=0.0
 for i in ranked:
  if spent+measures[i]['cost']<=budget+1e-9:
   chosen.append(i);spent+=measures[i]['cost']
 pieces,minutes,_,_=evaluate(chosen,target_bits,minute_index)
 # 单项排序口径的名义收益（直接相加，不做同分钟去重），展示其高估幅度
 nominal=sum(evaluate([i],target_bits,minute_index)[0] for i in chosen)
 return {'chosen':[measures[i]['name'] for i in chosen],'cost':round(spent,6),
  'pieces':pieces,'minutes':minutes,'nominal_sum_pieces':round(nominal,6),
  'overstatement_pieces':round(max(0.0,nominal-optimal_pieces),6)}
