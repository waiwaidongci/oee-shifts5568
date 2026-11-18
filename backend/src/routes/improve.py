from fastapi import APIRouter,Depends,HTTPException
from src.config.database import database
from src.controllers.auth import current,editor
from src.models.run import ImproveMeasure,ImproveRun
from src.schemas.requests import MeasureInput,ImproveRunInput
from src.services import improve as svc
from src.services.audit import log
from src.utils.serialize import row
router=APIRouter()

@router.get('/improve/inventory')
def inventory(period:str='全部',db=Depends(database),u=Depends(current)):
 return svc.target_inventory(db,period)

@router.get('/improve/measures')
def measures(db=Depends(database),u=Depends(current)):
 return [row(x) for x in svc.list_measures(db)]

@router.post('/improve/measures')
def create_measure(b:MeasureInput,db=Depends(database),u=Depends(editor)):
 targets=[t.model_dump() for t in b.targets]
 return row(svc.save_measure(db,u,b.name,b.cost,targets))

@router.put('/improve/measures/{id}')
def update_measure(id:int,b:MeasureInput,db=Depends(database),u=Depends(editor)):
 targets=[t.model_dump() for t in b.targets]
 return row(svc.save_measure(db,u,b.name,b.cost,targets,id))

@router.post('/improve/measures/{id}/toggle')
def toggle_measure(id:int,db=Depends(database),u=Depends(editor)):
 return row(svc.toggle_measure(db,u,id))

@router.get('/improve/runs')
def runs(db=Depends(database),u=Depends(current)):
 return [row(x) for x in db.query(ImproveRun).order_by(ImproveRun.id.desc()).all()]

@router.get('/improve/runs/{id}')
def detail(id:int,db=Depends(database),u=Depends(current)):
 obj=db.get(ImproveRun,id)
 if not obj:raise HTTPException(404,'测算任务不存在')
 return row(obj)

@router.post('/improve/runs')
def submit_run(b:ImproveRunInput,db=Depends(database),u=Depends(editor)):
 return row(svc.submit(db,u,b))
