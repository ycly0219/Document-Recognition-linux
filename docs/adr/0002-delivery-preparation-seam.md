# 交付准备统一承载单据快照到目标的转换

`单据快照` 到 Excel 导出或 WMS 发送的校验、语义归一化、字段映射与 artifact 构建统一由 `delivery_preparation.prepare_delivery()` 负责。`excel_export.py` 与 `wms_client.py` 只作为目标 adapter，分别写入文件或发送请求；Tk 只做界面编排，并把 `PreparationResult` 中的 `Validation Issue` 映射为现场提示。这样可以让三种单据模板的交付规则保持 locality，并让测试直接覆盖 `单据快照 -> PreparationResult`，无需依赖 Tk 或真实接口。
