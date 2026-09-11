"""集中管理 OCR、飞书接口与模板映射配置。"""

# ================== 配置区域 ==================
# OCR 相关配置
API_URL = "http://172.30.197.3:10000/OcrPlugins/generalOcr/extractGeneralDataAsync"
UPLOAD_API_URL = "http://techfile.i.sinotrans.com:80/objectstorecloud/files/v2"
GET_RESULT_API_URL = "http://172.30.197.3:10000/OcrPlugins/customsOcr/getResultByReqUuid"

ORG_ID = "99999"
SOURCE_CODE = "99999"

OCR_APP_ID = "R5QHOMZd"
OCR_APP_SECRET = "c108525f68088809f53b3ed715abd826"
OCR_APP_KEY = "1MsDKlaQ"
OCR_SYS_CODE = "99999"   # 默认sysCode，非OSCAR单据使用
OCR_SYS_CODE_OSCAR = "LOGISTICS_GE"  # OSCAR拣货单专用sysCode
OCR_ORG_ID = "101162"
OCR_REGIONAL_CODE = ""
OCR_DOC_TYPE = "SINGLE_LLM_EXTRACT_ASYNC"
OCR_CALLBACK_URL = "http://172.30.254.38:10000/OcrPlugins/customsOcr/test"
OCR_MAX_RETRY = 50
OCR_RETRY_INTERVAL = 5
OCR_MAX_POLL_SECONDS = 300

# 模板映射（GE拣货单、GE‑OSCAR拣货单、GE‑发票单）
MODEL_MAP = {
    "GE-ORACLE拣货单": "logistics_east_ge_picklist_99999_1503",
    "GE-OSCAR拣货单": "logistics_ge_oscarpicklist_1503",
    "GE-发票单": "logistics_east_ge_invoice_99999_1503"
}

# 订单类型配置（模板 -> {中文标签: 导出代码}）
_PICK_ORDER_TYPE_OPTIONS = {
    "国内出库_FE": "GNCK_FE",
    "国内出库维修订单": "GNCK_WX",
    "国内出库报废订单": "GNCK_BF",
    "国内出库补货订单": "GNCK_BH",
    "国内出库大保养订单": "GNCK_DBY",
    "国外出库400": "GWCK_400",
    "国外出库600": "GWCK_600",
    "国外出库700": "GWCK_700",
    "国外出库900": "GWCK_900",
}

_INVOICE_ORDER_TYPE_OPTIONS = {
    "国外入库": "OSI",
    "国内采购入库": "POIN",
    "国内外维修入库": "REPAIRIN",
}

ORDER_TYPE_OPTIONS_BY_TEMPLATE = {
    "GE-ORACLE拣货单": _PICK_ORDER_TYPE_OPTIONS,
    "GE-OSCAR拣货单": _PICK_ORDER_TYPE_OPTIONS,
    "GE-发票单": _INVOICE_ORDER_TYPE_OPTIONS,
}

DEFAULT_ORDER_TYPE_BY_TEMPLATE = {
    "GE-ORACLE拣货单": "",
    "GE-OSCAR拣货单": "",
    "GE-发票单": "国外入库",
}

# ---------------- Flux WMS 接口对接配置 ----------------
WMS_PUT_PURCHASE_ORDER_URL = (
    "https://sinoewms-qas.i.sinotrans.com/datahubjson/FluxWmsJsonApi_WJC/"
    "?method=putPurchaseOrder&apptoken=0B61B741BB1970A66A63DD653A131D68"
    "&sign=123&format=json"
)
WMS_PUT_ORIGINAL_SALES_ORDER_URL = (
    "https://sinoewms-qas.i.sinotrans.com/datahubjson/FluxWmsJsonApi_WJC/"
    "?method=putOriginalSalesOrder&apptoken=0B61B741BB1970A66A63DD653A131D68"
    "&sign=123&format=json"
)
WMS_PUT_SKU_URL = (
    "https://sinoewms-qas.i.sinotrans.com/datahubjson/FluxWmsJsonApi_WJC/"
    "?method=putSKU&apptoken=0B61B741BB1970A66A63DD653A131D68"
    "&timestamp=&sign=123&format=json"
)
WMS_CUSTOMER_ID = "GEHC"
WMS_PUT_SKU_CUSTOMER_IDS = (
    WMS_CUSTOMER_ID,
    "GEHC-BF",
    "GEHC-DBY",
    "GEHC-ZLKC",
)
WMS_WAREHOUSE_ID = "WH004078"

# ---------------- 飞书多维表格配置 ----------------
FEISHU_APP_ID = "cli_aa978beae8f81cca"
FEISHU_APP_SECRET = "ywHBY0AmJc00TojMIghLzgRHpyngHXpR"
FEISHU_CALL_TIMES = 3  # 每个成功文件后台写入飞书统计的次数
BITABLE_RECORDS_URL = "https://open.feishu.cn/open-apis/bitable/v1/apps/Jqfwbt2bWaLq7AswNz2c1iSUn4i/tables/tblQRssVXgCA7mEs/records"
# =============================================================
