# 初始结构

SQLAlchemy启动创建以下业务表：shifts, downtimeevents, productioncounts, oeeruns, delivery_schedules, deliveries、users、audits。Source专属JSON字段由对应validation严格校验；Policy为不可覆盖的版本记录；Run保存source/policy冻结快照；Period仅用于已有期间选择器，不计入核心复杂度。已有数据库升级需先备份，后续字段演进应以独立迁移执行。

# 002 停机改善测算

新增 improve_measures（改善措施：名称唯一、费用、停机记录targets、启用状态）与 improve_runs（测算任务：预算、冻结快照、SHA256、结果/错误）。SQLAlchemy启动时 create_all 自动建表，无需手工迁移；既有表不受影响。措施targets以(source_id, interval_index)引用冻结时点的停机记录，排队时在同一事务内校验并整体快照，底稿/措施后续并发修改不改变已排队任务。
