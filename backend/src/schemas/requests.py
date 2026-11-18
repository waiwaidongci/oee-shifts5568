from pydantic import BaseModel,Field
class Login(BaseModel): email:str; password:str
class DataInput(BaseModel): data:dict
class RunInput(BaseModel): name:str=Field(min_length=2,max_length=120); policy_id:int; period:str='全部'
class ReviewInput(BaseModel): note:str=Field(min_length=4,max_length=2000)
class ScheduleInput(BaseModel): name:str=Field(min_length=2,max_length=120); run_id:int; interval_seconds:int=Field(ge=5,le=86400)
class MeasureTarget(BaseModel): source_id:int; interval_index:int=Field(ge=0)
class MeasureInput(BaseModel):
 name:str=Field(min_length=2,max_length=120)
 cost:float=Field(ge=0)
 targets:list[MeasureTarget]=Field(min_length=1)
class ImproveRunInput(BaseModel):
 name:str=Field(min_length=2,max_length=120)
 budget:float=Field(ge=0)
 period:str='全部'
 measure_ids:list[int]=Field(min_length=1,max_length=30)
