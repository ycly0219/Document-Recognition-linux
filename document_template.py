"""单据模板 schema、订单类型与目标前语义归一化。"""

import re
from datetime import date
from types import MappingProxyType


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

_ORDER_TYPE_OPTIONS_BY_TEMPLATE = {
    "GE-ORACLE拣货单": _PICK_ORDER_TYPE_OPTIONS,
    "GE-OSCAR拣货单": _PICK_ORDER_TYPE_OPTIONS,
    "GE-发票单": _INVOICE_ORDER_TYPE_OPTIONS,
}

_DEFAULT_ORDER_TYPE_BY_TEMPLATE = {
    "GE-ORACLE拣货单": "",
    "GE-OSCAR拣货单": "",
    "GE-发票单": "国外入库",
}

_CORE_HEADERS = {
    "GE-ORACLE拣货单": (
        "订单类型",
        "客商编码",
        "Order Number",
        "Task Id",
        "Item Number",
        "Qty",
        "LPN",
        "Serial",
        "Lot",
        "COO",
        "Pick From Locator",
        "OrderType",
        "Ordered Date",
        "Shipment Priority",
        "Ship Method",
        "Service Level",
        "FE SSO",
        "FE Name",
        "Customer Name",
        "Customer Number",
        "SHIP TO NO",
        "Ship To Address",
        "Email",
        "Shipping Instruction",
        "Special Instruction",
        "Org",
        "Pick Slip Print Date",
        "System Id",
        "Pick From Subinv",
        "Customer PO",
        "Delivery",
    ),
    "GE-OSCAR拣货单": (
        "订单类型",
        "客商编码",
        "服务申请号",
        "物料编号",
        "数量",
        "序列号",
        "货位",
        "状态",
        "仓库",
        "供应商",
        "SSO",
        "收货人",
        "姓名",
        "收货地址",
        "时效",
        "收货人电话",
        "申请说明",
        "客户设备id",
        "SR编号",
        "跟踪号",
    ),
    "GE-发票单": (
        "订单类型",
        "运单号",
        "INVOICE NO",
        "ITEM NUMBER",
        "QTY",
        "LPN Number",
        "Serial Number",
        "LOT Number",
        "Expiration Date",
        "COUNTRY OF ORIGIN",
        "SALES ORDER NO",
        "CUSTOMER PO",
        "DATE",
        "DELIVERY",
        "CARRIER",
        "HAWB",
    ),
}

_PREVIEW_LAYOUT = {
    "GE-ORACLE拣货单": (
        (
            "订单类型",
            "客商编码",
            "Pick Slip Print Date",
            "Order Number",
            "OrderType",
            "Shipment Priority",
            "Service Level",
            "FE SSO",
            "FE Name",
            "SHIP TO NO",
            "Ship To Address",
            "Shipping Instruction",
            "Special Instruction",
            "Customer Name",
            "Customer Number",
            "System Id",
            "Pick From Subinv",
            "Customer PO",
            "Delivery",
        ),
        (
            "Task Id",
            "Item Number",
            "Qty",
            "LPN",
            "Serial",
            "Lot",
            "COO",
            "Pick From Locator",
            "Org",
        ),
    ),
    "GE-OSCAR拣货单": (
        (
            "订单类型",
            "客商编码",
            "服务申请号",
            "SR编号",
            "时效",
            "供应商",
            "收货人",
            "收货地址",
            "收货人电话",
            "申请说明",
            "SSO",
            "姓名",
            "客户设备id",
        ),
        (
            "物料编号",
            "数量",
            "序列号",
            "货位",
            "仓库",
            "状态",
            "跟踪号",
        ),
    ),
    "GE-发票单": (
        (
            "订单类型",
            "运单号",
            "INVOICE NO",
            "DATE",
            "DELIVERY",
            "CARRIER",
            "HAWB",
        ),
        (
            "ITEM NUMBER",
            "QTY",
            "LPN Number",
            "Serial Number",
            "LOT Number",
            "Expiration Date",
            "COUNTRY OF ORIGIN",
            "SALES ORDER NO",
            "CUSTOMER PO",
        ),
    ),
}

_PREVIEW_WIDE_FIELDS = {
    "GE-ORACLE拣货单": ("Ship To Address",),
    "GE-OSCAR拣货单": ("收货地址",),
}

_PREVIEW_HIDDEN_FIELDS = {
    "GE-ORACLE拣货单": ("Ordered Date", "Ship Method"),
}

_DATE_PATTERN = re.compile(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})$")

_ORACLE_MONTH_NAMES = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}

_ORACLE_DATE_PATTERNS = (
    re.compile(
        r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})"
        r"(?:[ T](\d{1,2}):(\d{2})(?::(\d{2}))?)?$"
    ),
    re.compile(
        r"^(\d{1,2})-([A-Za-z]+)-(\d{2}|\d{4})"
        r"(?:[ T](\d{1,2}):(\d{2})(?::(\d{2}))?)?$"
    ),
)


def get_order_type_labels(select_text):
    """返回指定模板可选订单类型中文标签。"""
    return list(_ORDER_TYPE_OPTIONS_BY_TEMPLATE.get(select_text, {}))


def get_order_type_value(select_text, label):
    """把订单类型中文标签转换为当前模板导出值，未知值原样返回。"""
    mapping = _ORDER_TYPE_OPTIONS_BY_TEMPLATE.get(select_text, {})
    return mapping.get(str(label).strip(), label)


def get_default_order_type_label(select_text):
    """返回指定模板初始订单类型；拣货单为空，需要人工必选。"""
    return _DEFAULT_ORDER_TYPE_BY_TEMPLATE.get(select_text, "")


def get_core_headers(select_text):
    """返回各单据模板对应的完整列结构。"""
    try:
        return list(_CORE_HEADERS[select_text])
    except KeyError as exc:
        raise ValueError(f"未知模板: {select_text}") from exc


def get_preview_layout(select_text):
    """返回预览用的 Header 字段顺序与 Details 字段顺序。"""
    try:
        header_fields, detail_fields = _PREVIEW_LAYOUT[select_text]
    except KeyError as exc:
        raise ValueError(f"未知模板: {select_text}") from exc
    return list(header_fields), list(detail_fields)


def get_preview_hidden_fields(select_text):
    """返回预览不展示、但导出与接口仍需保留的 Header 字段。"""
    return _PREVIEW_HIDDEN_FIELDS.get(select_text, ())


def get_preview_wide_fields(select_text):
    """返回预览中跨两列展示的 Header 字段。"""
    return _PREVIEW_WIDE_FIELDS.get(select_text, ())


def merge_preview_rows(select_text, header_values, detail_rows):
    """按导出所需的完整列顺序，把单据头与明细行重组为完整行。"""
    full_headers = get_core_headers(select_text)
    _, detail_fields = get_preview_layout(select_text)
    header_index = {
        name: index for index, name in enumerate(full_headers)
    }
    merged_rows = []
    for detail_row in detail_rows:
        row = [header_values.get(name, "") for name in full_headers]
        for index, name in enumerate(detail_fields):
            row[header_index[name]] = (
                detail_row[index] if index < len(detail_row) else ""
            )
        merged_rows.append(row)
    return merged_rows


def _normalize_expiration_date(value):
    """把 YYYY/MM/DD 或 YYYY-MM-DD 转成模板要求的 YYYY-MM-DD。"""
    if value is None:
        return ""
    text = str(value).strip()
    match = _DATE_PATTERN.fullmatch(text)
    if not match:
        return text
    try:
        year, month, day = (int(part) for part in match.groups())
        return date(year, month, day).strftime("%Y-%m-%d")
    except ValueError:
        return text


def _normalize_oracle_datetime(value, include_time):
    """把 Oracle 日期样例转换为销售订单模板要求的格式。"""
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    for pattern in _ORACLE_DATE_PATTERNS:
        match = pattern.fullmatch(text)
        if not match:
            continue
        day_or_year = match.group(1)
        token2 = match.group(2)
        token3 = match.group(3)
        if pattern is _ORACLE_DATE_PATTERNS[0]:
            year, month, day = int(day_or_year), int(token2), int(token3)
        else:
            month_name = token2.upper()
            month_num = _ORACLE_MONTH_NAMES.get(month_name)
            if month_num is None:
                month_num = _ORACLE_MONTH_NAMES.get(month_name[:3])
            if month_num is None:
                return text
            day = int(day_or_year)
            year = int(token3)
            if len(token3) == 2:
                year = 2000 + year if year < 70 else 1900 + year
            month = month_num
        try:
            base = date(year, month, day).strftime("%Y-%m-%d")
        except ValueError:
            return text
        if match.group(4):
            time_text = f"{int(match.group(4)):02d}:{match.group(5)}"
            if match.group(6):
                time_text += f":{match.group(6)}"
            return f"{base} {time_text}" if include_time else base
        return f"{base} 00:00:00" if include_time else base
    return text


def _normalize_oracle_quality_status(pick_from_subinv):
    """按模板规则把 Pick From Subinv 后缀转换为质量状态。"""
    text = str(pick_from_subinv or "").strip().upper()
    if text.endswith("GD"):
        return "GOOD"
    if text.endswith("BAD"):
        return "BAD"
    return ""


def _normalize_oscar_serial(value):
    """把 OSCAR 序列号的空值/N/A 归一化为导出与发送空值。"""
    if value is None:
        return ""
    text = str(value).strip()
    if not text or text.upper() == "N/A":
        return ""
    return text


def _normalize_header_value(template, field, value):
    if field == "订单类型":
        return get_order_type_value(template, value)
    if field == "客商编码":
        return str(value or "").strip()
    if template == "GE-ORACLE拣货单":
        if field == "Pick Slip Print Date":
            return _normalize_oracle_datetime(value, include_time=True)
        if field == "Ordered Date":
            return _normalize_oracle_datetime(value, include_time=False)
    return "" if value is None else value


def _normalize_detail_value(template, field, value):
    if template == "GE-发票单" and field == "Expiration Date":
        return _normalize_expiration_date(value)
    if template == "GE-OSCAR拣货单":
        if field == "序列号":
            return _normalize_oscar_serial(value)
        if field == "状态":
            return "GOOD" if str(value or "").strip() == "好件" else ""
    return "" if value is None else value


def normalize_document(template, header_values, detail_rows):
    """把单据头和明细归一化为下游可直接映射的只读值。"""
    full_headers = get_core_headers(template)
    _, detail_fields = get_preview_layout(template)
    source_headers = header_values or {}
    normalized_headers = {
        field: _normalize_header_value(
            template, field, source_headers.get(field, "")
        )
        for field in full_headers
    }
    if template == "GE-ORACLE拣货单":
        normalized_headers["质量状态"] = _normalize_oracle_quality_status(
            source_headers.get("Pick From Subinv", "")
        )

    normalized_rows = []
    for row in detail_rows or ():
        values = tuple(row or ())
        normalized_rows.append(tuple(
            _normalize_detail_value(
                template,
                field,
                values[index] if index < len(values) else "",
            )
            for index, field in enumerate(detail_fields)
        ))
    return (
        MappingProxyType(normalized_headers),
        tuple(normalized_rows),
    )
