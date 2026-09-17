"""Flux WMS 请求发送与 putSKU 报文构建。"""

import json
import re

import requests

from config import (
    WMS_PUT_ORIGINAL_SALES_ORDER_URL,
    WMS_PUT_PURCHASE_ORDER_URL,
    WMS_PUT_SKU_CUSTOMER_IDS,
    WMS_PUT_SKU_URL,
)
from delivery_preparation import (
    PUT_ORIGINAL_SALES_ORDER,
    PUT_PURCHASE_ORDER,
)


def _text(value):
    """把界面值统一转成 WMS 报文使用的字符串。"""
    return "" if value is None else str(value).strip()


_PUT_SKU_CHECKBOX_FIELDS = (
    ("serial_control", "skuGroup1", "SNY", "N"),
    ("batch_control", "skuGroup2", "LOTY", "N"),
    ("expiry_control", "skuGroup3", "EXPY", "N"),
    ("dangerous", "skuGroup4", "HAZARDY", "N"),
    ("medical_device", "freightClass", "MD", ""),
    ("tube", "skuGroup5", "TUBE", "N"),
)

_SHELF_LIFE_UNIT_VALUES = {
    "DAY": "DAY",
    "MONTH": "MONTH",
    "YEAR": "YEAR",
    "日": "DAY",
    "月": "MONTH",
    "年": "YEAR",
}


def _checked(value):
    """把 Tk BooleanVar 或简单字符串整理为布尔值。"""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in ("1", "true", "yes", "y", "是")


def _normalize_shelf_life_unit(value):
    """把有效期单位统一成 putSKU 使用的 DAY/MONTH/YEAR。"""
    return _SHELF_LIFE_UNIT_VALUES.get(_text(value), "MONTH")


def validate_put_sku_form(form):
    """新增产品表单校验，返回空字符串表示通过。"""
    raw_sku = form.get("sku")
    sku = "" if raw_sku is None else str(raw_sku)
    if not re.fullmatch(r"[A-Z0-9-]{1,50}", sku):
        return "产品编码只能包含大写字母、数字和-，长度1-50位，不能包含空格或换行"
    if not _text(form.get("sku_descr")):
        return "产品描述不能为空"
    if _checked(form.get("medical_device")):
        if not _checked(form.get("expiry_control")):
            return "勾选医疗器械后，效期控制必选"
        serial_control = _checked(form.get("serial_control"))
        batch_control = _checked(form.get("batch_control"))
        if not serial_control and not batch_control:
            return "勾选医疗器械后，序列号控制和批次控制必须选择一项"
        if serial_control and batch_control:
            return "勾选医疗器械后，序列号控制和批次控制只能选择一项"
        shelf_life = form.get("shelf_life")
        if shelf_life is None or not str(shelf_life).isdigit():
            return "勾选医疗器械后，有效期必填且必须为纯数字"
    return ""


def build_put_sku_payload(form):
    """按新增产品表单组装 Flux WMS putSKU 报文。"""
    raw_sku = form.get("sku")
    sku = "" if raw_sku is None else str(raw_sku)
    medical_device = _checked(form.get("medical_device"))
    header = {
        "sku": sku,
        "skuDescr1": _text(form.get("sku_descr")),
        "activeFlag": "Y",
        "packId": "HD78_E841_01",
    }
    for form_key, field, checked_value, no_value in _PUT_SKU_CHECKBOX_FIELDS:
        header[field] = (
            checked_value if _checked(form.get(form_key)) else no_value
        )
    header.update({
        "shelfLifeFlag": "Y" if medical_device else "",
        "shelfLifeUnit": (
            _normalize_shelf_life_unit(form.get("shelf_life_unit"))
            if medical_device else ""
        ),
        "shelfLifeType": "M" if medical_device else "",
        "shelfLife": _text(form.get("shelf_life")) if medical_device else "",
        "qcPoint": "BEFORRECEIVING",
        "qcRule": "HD78_E841_01",
    })
    headers = [
        {"customerId": customer_id, **header}
        for customer_id in WMS_PUT_SKU_CUSTOMER_IDS
    ]
    return {"data": {"header": headers}}


def send_wms_request(prepared_request):
    """发送交付准备模块生成的 WMS 请求并返回接口响应对象。"""
    if prepared_request.method == PUT_PURCHASE_ORDER:
        url = WMS_PUT_PURCHASE_ORDER_URL
    elif prepared_request.method == PUT_ORIGINAL_SALES_ORDER:
        url = WMS_PUT_ORIGINAL_SALES_ORDER_URL
    else:
        raise ValueError(f"不支持的WMS请求类型: {prepared_request.method}")
    return requests.post(url, json=prepared_request.payload, timeout=30)


def send_put_sku(payload):
    """发送 putSKU 产品主数据报文并返回接口响应对象。"""
    return requests.post(WMS_PUT_SKU_URL, json=payload, timeout=30)


def is_wms_send_success(response):
    """按 HTTP 状态与顶层 returnFlag 判定 WMS 接口是否发送成功。"""
    if getattr(response, "status_code", None) != 200:
        return False
    try:
        body = response.json()
        return_flag = body["Response"]["return"]["returnFlag"]
    except (ValueError, AttributeError, KeyError, TypeError):
        return False
    return return_flag == "1" or (
        isinstance(return_flag, int)
        and not isinstance(return_flag, bool)
        and return_flag == 1
    )


def format_wms_response(response):
    """把接口回告整理为可读文本，优先展示格式化 JSON。"""
    try:
        body = json.dumps(response.json(), ensure_ascii=False, indent=2)
    except (ValueError, AttributeError):
        body = getattr(response, "text", "") or ""
    status_code = getattr(response, "status_code", None)
    if status_code is None:
        return body
    return f"HTTP {status_code}\n{body}"
