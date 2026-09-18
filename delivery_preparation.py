"""把单据快照原子化准备为 Excel 导出或 WMS 请求目标。"""

import os
from dataclasses import dataclass
from datetime import datetime

from config import (
    WMS_CUSTOMER_ID,
    WMS_WAREHOUSE_ID,
)
from document_template import (
    get_preview_layout,
    merge_preview_rows,
    normalize_document,
)


EXPORT = "export"
WMS_SEND = "wms_send"

BLOCKING = "blocking"
WARNING = "warning"

PUT_PURCHASE_ORDER = "putPurchaseOrder"
PUT_ORIGINAL_SALES_ORDER = "putOriginalSalesOrder"

_VALID_TARGETS = frozenset({EXPORT, WMS_SEND})

_CONSIGNEE_TEMPLATES = frozenset({
    "GE-ORACLE拣货单",
    "GE-OSCAR拣货单",
})

_MANUAL_NUMBER_FIELDS = {
    "GE-ORACLE拣货单": "Order Number",
    "GE-OSCAR拣货单": "服务申请号",
    "GE-发票单": "INVOICE NO",
}

_WMS_DETAIL_HEADERS = (
    "ITEM NUMBER",
    "QTY",
    "LPN Number",
    "Serial Number",
    "LOT Number",
    "Expiration Date",
    "COUNTRY OF ORIGIN",
    "SALES ORDER NO",
    "CUSTOMER PO",
)

_ORACLE_DETAIL_HEADERS = (
    "Task Id",
    "Item Number",
    "Qty",
    "LPN",
    "Serial",
    "Lot",
    "COO",
    "Pick From Locator",
    "Org",
)

_OSCAR_DETAIL_HEADERS = (
    "物料编号",
    "数量",
    "序列号",
    "货位",
    "仓库",
    "状态",
    "跟踪号",
)

_INVALID_FILENAME_CHARS = ("\\", "/", ":", "*", "?", '"', "<", ">", "|")
_MANUAL_FILENAME = "空白单据"


@dataclass(frozen=True)
class ValidationIssue:
    """单据快照不能执行目标动作的原因。"""

    document_id: str
    target: str
    code: str
    severity: str
    field: str = ""
    line_id: str = ""


@dataclass(frozen=True)
class PreparedExport:
    """可直接交给 Excel adapter 写入的完整导出工件。"""

    template: str
    rows: tuple
    output_base_name: str
    log_row: tuple
    header_values: object = None


@dataclass(frozen=True)
class PreparedWmsRequest:
    """可直接交给 WMS adapter 发送的接口请求。"""

    method: str
    payload: dict


@dataclass(frozen=True)
class PreparationResult:
    """一次目标准备的校验问题与可选 artifact。"""

    issues: tuple
    artifact: object = None


def _text(value):
    return "" if value is None else str(value).strip()


def _optional_item(target, key, value):
    text = _text(value)
    if text:
        target[key] = text


def _validation_issues(snapshot, target):
    document_id = snapshot.document_id
    if not snapshot.lines:
        return (
            ValidationIssue(
                document_id=document_id,
                target=target,
                code="no_exportable_lines",
                severity=BLOCKING,
            ),
        )

    header_fields, _ = get_preview_layout(snapshot.template)
    required_by_field = {}
    if "订单类型" in header_fields:
        required_by_field["订单类型"] = "order_type_required"
    if snapshot.template == "GE-发票单":
        if "运单号" in header_fields:
            required_by_field["运单号"] = "waybill_required"
        if target == WMS_SEND and "INVOICE NO" in header_fields:
            required_by_field["INVOICE NO"] = "invoice_no_required"
    if target == WMS_SEND:
        if (
            snapshot.template == "GE-ORACLE拣货单"
            and "Order Number" in header_fields
        ):
            required_by_field["Order Number"] = "order_number_required"
        if (
            snapshot.template == "GE-OSCAR拣货单"
            and "服务申请号" in header_fields
        ):
            required_by_field["服务申请号"] = "service_request_no_required"

    if (
        snapshot.medical_device_present
        and snapshot.template in _CONSIGNEE_TEMPLATES
        and "客商编码" in header_fields
    ):
        required_by_field["客商编码"] = "consignee_required"

    issues = []
    for field in header_fields:
        code = required_by_field.get(field)
        if not code:
            continue
        if not _text(snapshot.header_values.get(field, "")):
            issues.append(ValidationIssue(
                document_id=document_id,
                target=target,
                code=code,
                severity=BLOCKING,
                field=field,
            ))
    if snapshot.medical_device_present:
        issues.append(ValidationIssue(
            document_id=document_id,
            target=target,
            code="medical_device_present",
            severity=WARNING,
        ))
    return tuple(issues)


def _output_base_name(snapshot):
    if not snapshot.metadata.manual:
        return os.path.splitext(os.path.basename(snapshot.metadata.filename))[0]
    field = _MANUAL_NUMBER_FIELDS.get(snapshot.template, "")
    value = _text(snapshot.header_values.get(field, ""))
    for char in _INVALID_FILENAME_CHARS:
        value = value.replace(char, "_")
    return value or _MANUAL_FILENAME


def _prepare_export(snapshot, normalized_headers, normalized_details):
    rows = merge_preview_rows(
        snapshot.template, normalized_headers, normalized_details
    )
    return PreparedExport(
        template=snapshot.template,
        rows=tuple(tuple(row) for row in rows),
        output_base_name=_output_base_name(snapshot),
        log_row=tuple(snapshot.metadata.log_row or ()),
        header_values=normalized_headers,
    )


def _build_put_purchase_order_payload(header_values, detail_rows):
    header = {
        "warehouseId": WMS_WAREHOUSE_ID,
        "customerId": WMS_CUSTOMER_ID,
        "poType": _text(header_values.get("订单类型", "")),
        "docNo": _text(header_values.get("INVOICE NO", "")),
        "poReferenceA": _text(header_values.get("运单号", "")),
        "udf01": _text(header_values.get("CARRIER", "")),
        "udf02": _text(header_values.get("HAWB", "")),
    }

    details = []
    for line_no, row in enumerate(detail_rows, start=1):
        row_map = dict(zip(_WMS_DETAIL_HEADERS, row))
        details.append({
            "lineNo": str(line_no),
            "customerId": WMS_CUSTOMER_ID,
            "sku": _text(row_map.get("ITEM NUMBER")),
            "orderedQty": _text(row_map.get("QTY")),
            "packUom": "EA",
            "lotAtt02": _text(row_map.get("Expiration Date")),
            "lotAtt03": datetime.now().strftime("%Y-%m-%d"),
            "lotAtt04": _text(row_map.get("LOT Number")),
            "lotAtt05": "ORACLE",
            "lotAtt08": "GOOD",
            "lotAtt09": _text(row_map.get("Serial Number")),
            "lotAtt11": _text(row_map.get("LPN Number")),
            "lotAtt15": _text(row_map.get("COUNTRY OF ORIGIN")),
            "lotAtt16": _text(row_map.get("SALES ORDER NO")),
            "lotAtt17": _text(row_map.get("CUSTOMER PO")),
        })

    return {"data": {"header": [{**header, "details": details}]}}


def _build_oracle_put_original_sales_order_payload(
    header_values, detail_rows
):
    header = {
        "warehouseId": WMS_WAREHOUSE_ID,
        "customerId": WMS_CUSTOMER_ID,
        "consigneeId": _text(header_values.get("客商编码")),
        "consigneeName": "虚拟收货人",
    }
    _optional_item(header, "orderType", header_values.get("订单类型"))
    _optional_item(header, "docNo", header_values.get("Order Number"))
    _optional_item(header, "soReferenceB", header_values.get("System Id"))
    _optional_item(
        header, "orderTime", header_values.get("Pick Slip Print Date")
    )
    _optional_item(
        header, "consigneeAddress1", header_values.get("Ship To Address")
    )
    _optional_item(header, "hedi01", header_values.get("OrderType"))
    _optional_item(header, "hedi02", header_values.get("Ordered Date"))
    _optional_item(
        header, "hedi03", header_values.get("Shipment Priority")
    )
    _optional_item(header, "hedi04", header_values.get("Ship Method"))
    _optional_item(header, "hedi05", header_values.get("Service Level"))
    _optional_item(header, "hedi06", header_values.get("FE SSO"))
    _optional_item(header, "hedi07", header_values.get("FE Name"))
    _optional_item(
        header, "hedi08", header_values.get("Shipping Instruction")
    )
    _optional_item(
        header, "hedi11", header_values.get("Special Instruction")
    )
    _optional_item(
        header, "hedi12", header_values.get("Pick From Subinv")
    )
    _optional_item(header, "userDefine1", header_values.get("SHIP TO NO"))

    quality_status = header_values.get("质量状态", "")
    details = []
    for line_no, row in enumerate(detail_rows, start=1):
        row_map = dict(zip(_ORACLE_DETAIL_HEADERS, row))
        detail = {
            "lineNo": str(line_no),
            "sku": _text(row_map.get("Item Number")),
            "qtyOrdered": _text(row_map.get("Qty")),
            "packUom": "EA",
            "price": "0",
            "lotAtt05": "ORACLE",
        }
        _optional_item(detail, "lotAtt04", row_map.get("Lot"))
        _optional_item(detail, "lotAtt07", row_map.get("Org"))
        _optional_item(detail, "lotAtt08", quality_status)
        _optional_item(detail, "lotAtt09", row_map.get("Serial"))
        _optional_item(detail, "lotAtt11", row_map.get("LPN"))
        _optional_item(detail, "dedi01", row_map.get("Task Id"))
        _optional_item(detail, "dedi03", row_map.get("Pick From Locator"))
        details.append(detail)

    return {"data": {"header": [{**header, "details": details}]}}


def _build_oscar_put_original_sales_order_payload(
    header_values, detail_rows
):
    header = {
        "warehouseId": WMS_WAREHOUSE_ID,
        "customerId": WMS_CUSTOMER_ID,
        "consigneeId": _text(header_values.get("客商编码")),
    }
    _optional_item(header, "orderType", header_values.get("订单类型"))
    _optional_item(header, "docNo", header_values.get("服务申请号"))
    _optional_item(header, "soReferenceA", header_values.get("SR编号"))
    _optional_item(header, "soReferenceB", header_values.get("客户设备id"))
    header["orderTime"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _optional_item(header, "notes", header_values.get("申请说明"))
    _optional_item(
        header, "consigneeAddress1", header_values.get("收货地址")
    )
    _optional_item(header, "hedi01", header_values.get("客户设备id"))
    _optional_item(header, "hedi05", header_values.get("时效"))
    _optional_item(header, "hedi06", header_values.get("SSO"))
    _optional_item(header, "hedi07", header_values.get("姓名"))
    _optional_item(header, "consigneeName", header_values.get("供应商"))
    _optional_item(header, "consigneeContact", header_values.get("收货人"))
    _optional_item(header, "consigneeTel1", header_values.get("收货人电话"))

    details = []
    for line_no, row in enumerate(detail_rows, start=1):
        row_map = dict(zip(_OSCAR_DETAIL_HEADERS, row))
        detail = {
            "lineNo": str(line_no),
            "sku": _text(row_map.get("物料编号")),
            "qtyOrdered": _text(row_map.get("数量")),
            "packUom": "EA",
            "price": "0",
            "lotAtt05": "OSCAR",
        }
        _optional_item(detail, "lotAtt07", row_map.get("仓库"))
        _optional_item(detail, "lotAtt08", row_map.get("状态"))
        _optional_item(detail, "lotAtt09", row_map.get("序列号"))
        _optional_item(detail, "dedi02", row_map.get("跟踪号"))
        _optional_item(detail, "dedi03", row_map.get("货位"))
        details.append(detail)

    return {"data": {"header": [{**header, "details": details}]}}


def _prepare_wms_request(snapshot, normalized_headers, normalized_details):
    if snapshot.template == "GE-发票单":
        return PreparedWmsRequest(
            method=PUT_PURCHASE_ORDER,
            payload=_build_put_purchase_order_payload(
                normalized_headers, normalized_details
            ),
        )
    if snapshot.template == "GE-ORACLE拣货单":
        return PreparedWmsRequest(
            method=PUT_ORIGINAL_SALES_ORDER,
            payload=_build_oracle_put_original_sales_order_payload(
                normalized_headers, normalized_details
            ),
        )
    if snapshot.template == "GE-OSCAR拣货单":
        return PreparedWmsRequest(
            method=PUT_ORIGINAL_SALES_ORDER,
            payload=_build_oscar_put_original_sales_order_payload(
                normalized_headers, normalized_details
            ),
        )
    raise ValueError(f"不支持的WMS模板: {snapshot.template}")


def prepare_delivery(snapshot, target):
    """一次完成目标校验与 artifact 构建；阻塞时 artifact 为 None。"""
    if target not in _VALID_TARGETS:
        raise ValueError(f"未知校验目标: {target}")

    issues = _validation_issues(snapshot, target)
    if any(issue.severity == BLOCKING for issue in issues):
        return PreparationResult(issues=issues)

    normalized_headers, normalized_details = normalize_document(
        snapshot.template,
        snapshot.header_values,
        tuple(line.values for line in snapshot.lines),
    )
    if target == EXPORT:
        artifact = _prepare_export(
            snapshot, normalized_headers, normalized_details
        )
    else:
        artifact = _prepare_wms_request(
            snapshot, normalized_headers, normalized_details
        )
    return PreparationResult(issues=issues, artifact=artifact)
