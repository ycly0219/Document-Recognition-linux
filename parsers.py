"""三种单据模板的列头定义、识别结果解析与发票明细拆分。"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from logging_utils import print_log


@dataclass(frozen=True)
class RecognitionResult:
    """一次 OCR 识别的具名字段解析结果。"""

    header_values: Mapping
    detail_lines: tuple
    split_groups: tuple = ()


_ITEM_DETAIL_PATTERN = re.compile(
    r"(?<![A-Za-z])(LPN|Serial|Lot|COO):\s*(.*?)(?=\s*(?:LPN|Serial|Lot|COO):|\Z)",
    re.DOTALL,
)


def _named_values(values):
    """去除空值并冻结一层字段字典。"""
    if not isinstance(values, Mapping):
        raise TypeError("具名字段必须是映射")
    return MappingProxyType({
        field: value for field, value in values.items()
        if value not in ("", None)
    })


def _split_group(child_indexes, summary_values):
    """构造具名字段拆分分组。"""
    return MappingProxyType({
        "child_indexes": tuple(child_indexes),
        "summary_values": _named_values(summary_values),
    })


def _normalize_address(value):
    """把 OCR 地址中的连续空白折为一个空格，并去除首尾空白。"""
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _parse_oracle_picklist(commit_result, filename):
    """解析 GE-ORACLE 拣货单，返回具名字段识别结果。"""
    order_number = commit_result.get("Order Number", {}).get("value", "").strip()
    order_type = commit_result.get("OrderType", {}).get("value", "").strip()
    ordered_date = commit_result.get("Ordered Date", {}).get("value", "").strip()
    shipment_priority = commit_result.get("Shipment Priority", {}).get("value", "").strip()
    ship_method = commit_result.get("Ship Method", {}).get("value", "").strip()
    service_level = commit_result.get("Service Level", {}).get("value", "").strip()
    fe_sso = commit_result.get("FE SSO", {}).get("value", "").strip()
    fe_name = commit_result.get("FE Name", {}).get("value", "").strip()
    customer_name = commit_result.get("Customer Name", {}).get("value", "").strip()
    customer_number = commit_result.get("Customer Number", {}).get("value", "").strip()
    shipping_instruction = commit_result.get("Shipping Instruction", {}).get("value", "").strip()
    special_instruction = commit_result.get("Special Instruction", {}).get("value", "").strip()
    org = commit_result.get("Org", {}).get("value", "").strip()
    pick_slip_print_date = commit_result.get("Pick Slip Print Date", {}).get("value", "").strip()
    system_id = commit_result.get("System Id", {}).get("value", "").strip()
    pick_from_subinv = commit_result.get("Pick From Subinv", {}).get("value", "").strip()
    customer_po = commit_result.get("Customer PO", {}).get("value", "").strip()

    ship_addr = _normalize_address(
        commit_result.get("Ship To Address", {}).get("value", "")
    )
    ship_to_no = commit_result.get("SHIP TO NO", {}).get("value", "").strip()
    email = commit_result.get("Email", {}).get("value", "").strip()
    delivery = commit_result.get("Delivery", {}).get("value", "").strip()
    material_list = commit_result.get("物料信息", {}).get("content", [])

    if not material_list:
        raise Exception("未识别到拣货明细数据")
    if not order_number:
        raise Exception("未识别到Order Number订单号")

    print_log(f"{filename} OrderNumber:{order_number} Delivery:{delivery} 明细行数:{len(material_list)}")
    detail_lines = []
    for item in material_list:
        task_id = item.get("Task Id", {}).get("value", "").strip()
        item_no = item.get("Item Number", {}).get("value", "").strip()
        qty = item.get("Qty", {}).get("value", "").strip()
        pick_loc = item.get("Pick From Locator", {}).get("value", "").strip()
        item_detail = item.get("Item Details", {}).get("value", "").strip()
        un_number_index = item_detail.find("UN Number:")
        if un_number_index >= 0:
            item_detail = item_detail[:un_number_index]
        trace_values = {label: "" for label in ("LPN", "Serial", "Lot", "COO")}
        for label, value in _ITEM_DETAIL_PATTERN.findall(item_detail):
            trace_values[label] = value.strip()

        detail_lines.append(_named_values({
            "Task Id": task_id,
            "Item Number": item_no,
            "Qty": qty,
            "LPN": trace_values["LPN"],
            "Serial": trace_values["Serial"],
            "Lot": trace_values["Lot"],
            "COO": trace_values["COO"],
            "Pick From Locator": pick_loc,
            "Org": org,
        }))
    return RecognitionResult(
        header_values=_named_values({
            "Pick Slip Print Date": pick_slip_print_date,
            "Order Number": order_number,
            "OrderType": order_type,
            "Ordered Date": ordered_date,
            "Shipment Priority": shipment_priority,
            "Ship Method": ship_method,
            "Service Level": service_level,
            "FE SSO": fe_sso,
            "FE Name": fe_name,
            "SHIP TO NO": ship_to_no,
            "Ship To Address": ship_addr,
            "Shipping Instruction": shipping_instruction,
            "Special Instruction": special_instruction,
            "Customer Name": customer_name,
            "Customer Number": customer_number,
            "System Id": system_id,
            "Pick From Subinv": pick_from_subinv,
            "Customer PO": customer_po,
            "Delivery": delivery,
            "Email": email,
        }),
        detail_lines=tuple(detail_lines),
    )


def _parse_oscar_picklist(commit_result, filename):
    """解析 GE-OSCAR 拣货单，返回具名字段识别结果。"""
    service_apply_no = commit_result.get("服务申请号", {}).get("value", "").strip()
    sr_no = commit_result.get("SR编号", {}).get("value", "").strip()
    supplier = commit_result.get("供应商", {}).get("value", "").strip()
    sso = commit_result.get("SSO", {}).get("value", "").strip()
    ship_addr = _normalize_address(
        commit_result.get("收货地址", {}).get("value", "")
    )
    lead_time = commit_result.get("时效", {}).get("value", "").strip()
    consignee_tel = commit_result.get("收货人电话", {}).get("value", "").strip()
    apply_note = commit_result.get("申请说明", {}).get("value", "").strip()
    consignee_name = commit_result.get("收货人", {}).get("value", "").strip()
    real_name = commit_result.get("姓名", {}).get("value", "").strip()
    cust_device_id = commit_result.get("客户设备id", {}).get("value", "").strip()

    material_list = commit_result.get("物料信息", {}).get("content", [])

    if not material_list:
        raise Exception("未识别到OSCAR拣货明细数据")
    if not service_apply_no:
        raise Exception("未识别到服务申请号")

    print_log(f"{filename} 服务申请号:{service_apply_no} SR编号:{sr_no} 收货人:{consignee_name} 姓名:{real_name} 客户设备id:{cust_device_id} 明细行数:{len(material_list)}")
    detail_lines = []
    for item in material_list:
        mat_no = item.get("物料编号", {}).get("value", "").strip()
        qty = item.get("数量", {}).get("value", "").strip()
        serial_no = item.get("序列号", {}).get("value", "").strip()
        track_no = item.get("跟踪号", {}).get("value", "").strip()
        locator = item.get("货位", {}).get("value", "").strip()
        status_val = item.get("状态", {}).get("value", "").strip()
        warehouse = item.get("仓库", {}).get("value", "").strip()

        detail_lines.append(_named_values({
            "物料编号": mat_no,
            "数量": qty,
            "序列号": serial_no,
            "货位": locator,
            "仓库": warehouse,
            "状态": status_val,
            "跟踪号": track_no,
        }))
    return RecognitionResult(
        header_values=_named_values({
            "服务申请号": service_apply_no,
            "SR编号": sr_no,
            "时效": lead_time,
            "供应商": supplier,
            "收货人": consignee_name,
            "收货地址": ship_addr,
            "收货人电话": consignee_tel,
            "申请说明": apply_note,
            "SSO": sso,
            "姓名": real_name,
            "客户设备id": cust_device_id,
        }),
        detail_lines=tuple(detail_lines),
    )


def _parse_invoice(commit_result, filename):
    """解析 GE-发票单，并按 LPN/Serial 与数量关系拆分明细。

    返回具名字段识别结果；只拆出 1 条子行时不返回汇总元数据。
    """
    invoice_no = commit_result.get("INVOICE NO", {}).get("value", "").strip()
    delivery = commit_result.get("DELIVERY", {}).get("value", "").strip()
    doc_date = commit_result.get("DATE", {}).get("value", "").strip()
    carrier = commit_result.get("CARRIER", {}).get("value", "").strip()
    hawb = commit_result.get("HAWB", {}).get("value", "").strip()

    material_list = commit_result.get("物料信息", {}).get("content", [])

    if not material_list:
        raise Exception("未识别到发票明细数据")
    if not invoice_no:
        raise Exception("未识别到INVOICE NO发票号")

    print_log(f"{filename} INVOICE NO:{invoice_no} DELIVERY:{delivery} DATE:{doc_date} CARRIER:{carrier} HAWB:{hawb} 明细总行数:{len(material_list)}")
    detail_lines = []
    split_groups = []
    for item in material_list:
        raw_qty_str = item.get("QTY", {}).get("value", "").strip()
        item_num = item.get("ITEM NUMBER", {}).get("value", "").strip()
        country_of_origin = item.get("COUNTRY OF ORIGIN", {}).get("value", "").strip()
        raw_lpn_str = item.get("LPN Number", {}).get("value", "").strip()
        raw_serial_str = item.get("Serial Number", {}).get("value", "").strip()
        lot = item.get("LOT Number", {}).get("value", "").strip()
        sales_order = item.get("SALES ORDER NO", {}).get("value", "").strip()
        customer_po = item.get("CUSTOMER PO", {}).get("value", "").strip()
        expire = item.get("Expiration Date", {}).get("value", "").strip()
        split_summary_values = {
            "ITEM NUMBER": item_num,
            "QTY": raw_qty_str,
            "LPN Number": "原始行汇总",
        }

        def append_detail(qty, lpn, serial):
            detail_lines.append(_named_values({
                "ITEM NUMBER": item_num,
                "QTY": qty,
                "LPN Number": lpn,
                "Serial Number": serial,
                "LOT Number": lot,
                "Expiration Date": expire,
                "COUNTRY OF ORIGIN": country_of_origin,
                "SALES ORDER NO": sales_order,
                "CUSTOMER PO": customer_po,
            }))

        # 清洗LPN列表
        lpn_list = [lpn.strip() for lpn in raw_lpn_str.split(",") if lpn.strip()]
        lpn_count = len(lpn_list)
        # 清洗Serial列表（为空则返回空数组）
        serial_list = [s.strip() for s in raw_serial_str.split(",") if s.strip()]
        serial_count = len(serial_list)
        # 转换QTY数字，异常置0
        try:
            qty_val = int(raw_qty_str)
        except ValueError:
            qty_val = 0

        # ---------------- 拆分规则（兼容Serial为空） ----------------
        # 情况1：Serial为空，仅按LPN原有规则拆分，Serial填空
        if serial_count == 0:
            if lpn_count == qty_val and lpn_count > 0:
                print_log(f"Serial为空，匹配LPN规则1：LPN数量={lpn_count}=QTY{qty_val}，逐个拆分")
                child_indexes = []
                for single_lpn in lpn_list:
                    child_indexes.append(len(detail_lines))
                    append_detail("1", single_lpn, "")
                # 单条拆分直接作为普通明细行，不生成汇总分组
                if len(child_indexes) > 1:
                    split_groups.append(
                        _split_group(child_indexes, split_summary_values)
                    )
            elif lpn_count == 1 and qty_val > 0:
                single_lpn = lpn_list[0]
                print_log(f"Serial为空，匹配LPN规则2：单LPN，QTY={qty_val}，保留一行")
                append_detail(raw_qty_str, single_lpn, "")
            else:
                # LPN不满足拆分，原样一行
                append_detail(raw_qty_str, raw_lpn_str, "")
        # 情况2：Serial有值，原有多字段匹配逻辑
        else:
            # 场景1：LPN数量=QTY，Serial数量也等于QTY，一一对应拆分
            if lpn_count == qty_val and serial_count == qty_val and qty_val > 0:
                print_log(f"匹配规则1：LPN/Serial数量={lpn_count}=QTY{qty_val}，逐行匹配拆分")
                child_indexes = []
                for idx in range(qty_val):
                    single_lpn = lpn_list[idx]
                    single_serial = serial_list[idx]
                    child_indexes.append(len(detail_lines))
                    append_detail("1", single_lpn, single_serial)
                # 单条拆分直接作为普通明细行，不生成汇总分组
                if len(child_indexes) > 1:
                    split_groups.append(
                        _split_group(child_indexes, split_summary_values)
                    )
            # 场景2：仅1个LPN、仅1个Serial，按QTY循环复制N行
            elif lpn_count == 1 and serial_count == 1 and qty_val > 0:
                single_lpn = lpn_list[0]
                single_serial = serial_list[0]
                print_log(f"匹配规则2：单LPN+单Serial，QTY={qty_val}，保留一行")
                append_detail(raw_qty_str, single_lpn, single_serial)
            # 场景3：只有Serial多个、LPN单个，且serial_count == qty_val
            elif lpn_count == 1 and serial_count == qty_val and qty_val > 0:
                single_lpn = lpn_list[0]
                print_log(f"匹配规则3：单LPN，Serial数量={serial_count}=QTY{qty_val}，拆分Serial多行")
                child_indexes = []
                for single_serial in serial_list:
                    child_indexes.append(len(detail_lines))
                    append_detail("1", single_lpn, single_serial)
                split_groups.append(
                    _split_group(child_indexes, split_summary_values)
                )
            # 场景4：只有LPN多个、Serial单个，且lpn_count == qty_val
            elif serial_count == 1 and lpn_count == qty_val and qty_val > 0:
                single_serial = serial_list[0]
                print_log(f"匹配规则4：单Serial，LPN数量={lpn_count}=QTY{qty_val}，拆分LPN多行")
                child_indexes = []
                for single_lpn in lpn_list:
                    child_indexes.append(len(detail_lines))
                    append_detail("1", single_lpn, single_serial)
                split_groups.append(
                    _split_group(child_indexes, split_summary_values)
                )
            # 其他所有不匹配场景，保留原始一行，LPN/Serial逗号拼接不拆分
            else:
                append_detail(raw_qty_str, raw_lpn_str, raw_serial_str)
    return RecognitionResult(
        header_values=_named_values({
            "INVOICE NO": invoice_no,
            "DATE": doc_date,
            "DELIVERY": delivery,
            "CARRIER": carrier,
            "HAWB": hawb,
        }),
        detail_lines=tuple(detail_lines),
        split_groups=tuple(split_groups),
    )


def parse_commit_result(select_text, commit_result, filename):
    """按当前模板解析单份 OCR 识别结果，返回具名字段识别结果。"""
    if select_text == "GE-ORACLE拣货单":
        return _parse_oracle_picklist(commit_result, filename)
    elif select_text == "GE-OSCAR拣货单":
        return _parse_oscar_picklist(commit_result, filename)
    elif select_text == "GE-发票单":
        return _parse_invoice(commit_result, filename)
    raise ValueError(f"未知模板: {select_text}")
