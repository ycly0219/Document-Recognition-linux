"""客商查询、回告解析与本地列表过滤。"""

import secrets

import requests

from config import (
    WMS_CUSTOMER_ID,
    WMS_QUERY_CUSTOMER_URL,
    WMS_WAREHOUSE_ID,
)


CUSTOMER_COLUMNS = (
    "客商编码",
    "客商名称",
    "地址",
    "联系人",
    "联系人电话",
)
CUSTOMER_FIELD_MAP = (
    ("customerId", "客商编码"),
    ("customerDescr1", "客商名称"),
    ("address1", "地址"),
    ("contact1", "联系人"),
    ("contact1_Tel1", "联系人电话"),
)


def _customer_text(value):
    """把回告值转为界面文本，空值显示为空并保留编码前导零。"""
    if value is None:
        return ""
    return str(value).strip()


def _extract_customer_return(response_body):
    """读取客商查询回告的状态码和描述。"""
    try:
        response = response_body["Response"]
    except (KeyError, TypeError) as exc:
        raise ValueError("客商查询回告缺少 Response") from exc
    if not isinstance(response, dict):
        raise ValueError("客商查询回告 Response 格式异常")
    if "returnCode" not in response:
        raise ValueError("客商查询回告缺少 returnCode")
    return response.get("returnCode"), _customer_text(
        response.get("returnDesc")
    )


def is_customer_query_success(response_body):
    """判断客商查询回告是否成功，支持字符串和数值业务码。"""
    return_code, _ = _extract_customer_return(response_body)
    return return_code == "0000" or (
        type(return_code) in (int, float) and return_code == 0
    )


def extract_customer_records(response_body):
    """从 QUERYCO 回告中按接口顺序提取客商记录。"""
    try:
        items = response_body["Response"]["items"]["item"]
    except (KeyError, TypeError) as exc:
        raise ValueError("客商查询回告缺少 item 明细") from exc
    if items is None:
        items = []
    elif isinstance(items, dict):
        items = [items]
    if not isinstance(items, list):
        raise ValueError("客商查询回告 item 格式异常")
    if any(not isinstance(item, dict) for item in items):
        raise ValueError("客商查询回告 item 明细格式异常")

    records = []
    for item in items:
        records.append({
            field: _customer_text(item.get(field))
            for field, _ in CUSTOMER_FIELD_MAP
        })
    return records


def query_customer_records(timeout=10):
    """调用 QUERYCO，成功时按固定字段映射返回客商记录。"""
    payload = {
        "data": {
            "header": {
                "warehouseId": WMS_WAREHOUSE_ID,
                "customerId": WMS_CUSTOMER_ID,
            }
        }
    }
    response = requests.post(
        WMS_QUERY_CUSTOMER_URL, json=payload, timeout=timeout
    )
    try:
        response_body = response.json()
    except ValueError as exc:
        if response.status_code != 200:
            raise RuntimeError(
                f"客商查询接口 HTTP {response.status_code}"
            ) from exc
        raise ValueError("客商查询回告不是有效 JSON") from exc
    if response.status_code != 200:
        try:
            _, return_desc = _extract_customer_return(response_body)
        except ValueError:
            return_desc = ""
        detail = f"：{return_desc}" if return_desc else ""
        raise RuntimeError(
            f"客商查询接口 HTTP {response.status_code}{detail}"
        )
    if not is_customer_query_success(response_body):
        return_code, return_desc = _extract_customer_return(response_body)
        detail = (
            f"：{return_desc}"
            if return_desc
            else f"，returnCode={return_code}"
        )
        raise RuntimeError(f"客商查询失败{detail}")
    return extract_customer_records(response_body)


def customer_record_display_rows(records):
    """把客商记录转换为列表窗口使用的显示行。"""
    return [
        [record.get(field, "") for field, _ in CUSTOMER_FIELD_MAP]
        for record in records
    ]


def filter_customer_record_display_rows(
    rows, customer_code="", customer_name="", customer_address=""
):
    """按客商编码、名称和地址做包含匹配，条件间取交集。"""
    code_query = str(customer_code or "").strip().casefold()
    name_query = str(customer_name or "").strip().casefold()
    address_query = str(customer_address or "").strip().casefold()
    filtered = []
    for row in rows:
        code = str(row[0]).casefold()
        name = str(row[1]).casefold()
        address = str(row[2]).casefold()
        if code_query and code_query not in code:
            continue
        if name_query and name_query not in name:
            continue
        if address_query and address_query not in address:
            continue
        filtered.append(list(row))
    return filtered


def generate_customer_id(existing_ids=()):
    """生成允许前导零的八位数字客商编码。"""
    existing = {str(value).strip() for value in existing_ids}
    while True:
        customer_id = f"{secrets.randbelow(100_000_000):08d}"
        if customer_id != "00000000" and customer_id not in existing:
            return customer_id
