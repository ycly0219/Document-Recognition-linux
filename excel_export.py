"""Excel 识别结果与处理日志导出。"""

import os
import sys
import time
from copy import copy

from openpyxl import load_workbook

from document_template import get_core_headers
from logging_utils import print_log


def _resource_path(filename):
    """返回模板文件在源码目录或 PyInstaller 解包目录中的路径。"""
    if getattr(sys, "frozen", False):
        base_dir = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, filename)


def get_output_dir():
    """返回没有历史记录时目录选择框默认打开的导出目录。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.getcwd()


EXPORT_DIR_STATE_FILE = os.path.expanduser("~/.ge_tool_export_dir")


def get_last_export_dir():
    """返回上次人工选择的导出目录，没有记录或不可读时返回 None。"""
    try:
        with open(EXPORT_DIR_STATE_FILE, encoding="utf-8") as state_file:
            export_dir = state_file.read().strip()
    except OSError:
        return None
    return export_dir or None


def save_last_export_dir(export_dir):
    """保存上次人工选择的导出目录，供下次启动作为默认位置。"""
    try:
        with open(EXPORT_DIR_STATE_FILE, "w", encoding="utf-8") as state_file:
            state_file.write(export_dir)
    except OSError:
        print_log("导出目录未能保存，下次启动不会记住")


PO_TEMPLATE_PATH = _resource_path("DOC_PO_HEADER.xlsx")
SALESORDER_TEMPLATE_PATH = _resource_path("DOC_SALESORDER_HEADER.xlsx")
OSCAR_SALESORDER_TEMPLATE_PATH = _resource_path("DOC_SALESORDER_HEADER_1.xlsx")

_INVOICE_FIXED_VALUES = {
    "A": "WH004078",
    "C": "00",
    "D": "GEHC",
    "R": "WH004078",
    "S": "GEHC",
    "V": "EA",
    "AC": "GOOD",
}

_INVOICE_DYNAMIC_COLUMNS = {
    "B": 0,   # 订单类型 -> OSI/POIN/REPAIRIN
    "G": 1,   # 运单号 -> poReference2
    "F": 2,   # INVOICE NO
    "L": 14,  # CARRIER
    "M": 15,  # HAWB
    "T": 3,   # ITEM NUMBER
    "U": 4,   # QTY
    "X": 8,   # Expiration Date
    "Z": 7,   # LOT Number
    "AD": 6,  # Serial Number
    "AF": 5,  # LPN Number
    "AJ": 9,  # COUNTRY OF ORIGIN
    "AK": 10, # SALES ORDER NO
    "AL": 11, # CUSTOMER PO
}

_ORACLE_CORE_INDEX = {
    field: index
    for index, field in enumerate(get_core_headers("GE-ORACLE拣货单"))
}

_SALESORDER_FIXED_VALUES = {
    "A": "WH004078",
    "B": "00",
    "E": "Y",
    "F": "GEHC",
    "AE": "WH004078",
    "AF": "GEHC",
    "AH": "00",
    "AJ": "ORACLE",  # 货物来源
    "AP": "EA",
    "AQ": "HD78_E841_01",
    "AR": "HD78_E841_01",
    "AS": "0",
    "AT": "0",
    "AU": "0",
    "AV": "0",
}

_SALESORDER_DYNAMIC_COLUMNS = {
    "C": _ORACLE_CORE_INDEX["订单类型"],          # GNCK_*/GWCK_*
    "D": _ORACLE_CORE_INDEX["Pick Slip Print Date"],
    "G": _ORACLE_CORE_INDEX["Order Number"],
    "I": _ORACLE_CORE_INDEX["System Id"],          # 参考编号3
    "L": _ORACLE_CORE_INDEX["OrderType"],
    "M": _ORACLE_CORE_INDEX["Ordered Date"],
    "N": _ORACLE_CORE_INDEX["Shipment Priority"],
    "O": _ORACLE_CORE_INDEX["Ship Method"],
    "P": _ORACLE_CORE_INDEX["Service Level"],
    "Q": _ORACLE_CORE_INDEX["FE SSO"],
    "R": _ORACLE_CORE_INDEX["FE Name"],
    "S": _ORACLE_CORE_INDEX["Shipping Instruction"],
    "T": _ORACLE_CORE_INDEX["Special Instruction"],
    "U": _ORACLE_CORE_INDEX["Pick From Subinv"],
    "V": _ORACLE_CORE_INDEX["客商编码"],
    "W": _ORACLE_CORE_INDEX["Ship To Address"],
    "Y": _ORACLE_CORE_INDEX["SHIP TO NO"],          # udf01
    "AG": _ORACLE_CORE_INDEX["Item Number"],
    "AI": _ORACLE_CORE_INDEX["Lot"],
    "AK": _ORACLE_CORE_INDEX["Org"],
    "AL": _ORACLE_CORE_INDEX["Pick From Subinv"],  # 质量状态
    "AM": _ORACLE_CORE_INDEX["Serial"],
    "AN": _ORACLE_CORE_INDEX["LPN"],
    "AO": _ORACLE_CORE_INDEX["Qty"],
    "AW": _ORACLE_CORE_INDEX["Task Id"],
    "AY": _ORACLE_CORE_INDEX["Pick From Locator"],
}

_OSCAR_CORE_INDEX = {
    field: index
    for index, field in enumerate(get_core_headers("GE-OSCAR拣货单"))
}

_OSCAR_FIXED_VALUES = {
    "A": "WH004078",
    "B": "00",
    "E": "Y",
    "F": "GEHC",
    "AL": "WH004078",
    "AM": "GEHC",
    "AO": "00",
    "AQ": "OSCAR",  # 货物来源
    "AW": "EA",
    "AX": "HD78_E841_01",
    "AY": "HD78_E841_01",
    "AZ": "0",
    "BA": "0",
    "BB": "0",
    "BC": "0",
}

_OSCAR_DYNAMIC_COLUMNS = {
    "C": _OSCAR_CORE_INDEX["订单类型"],          # GNCK_*/GWCK_*
    "G": _OSCAR_CORE_INDEX["服务申请号"],
    "H": _OSCAR_CORE_INDEX["SR编号"],
    "I": _OSCAR_CORE_INDEX["客户设备id"],
    "P": _OSCAR_CORE_INDEX["时效"],
    "Q": _OSCAR_CORE_INDEX["SSO"],
    "R": _OSCAR_CORE_INDEX["姓名"],
    "Z": _OSCAR_CORE_INDEX["客商编码"],
    "AA": _OSCAR_CORE_INDEX["供应商"],          # 收货人名称
    "AB": _OSCAR_CORE_INDEX["收货人"],          # 收货联系人
    "AC": _OSCAR_CORE_INDEX["收货人电话"],      # 收货人电话1
    "AD": _OSCAR_CORE_INDEX["收货地址"],
    "AE": _OSCAR_CORE_INDEX["申请说明"],
    "AN": _OSCAR_CORE_INDEX["物料编号"],
    "AR": _OSCAR_CORE_INDEX["仓库"],
    "AS": _OSCAR_CORE_INDEX["状态"],            # 好件->GOOD
    "AT": _OSCAR_CORE_INDEX["序列号"],
    "AV": _OSCAR_CORE_INDEX["数量"],
    "BE": _OSCAR_CORE_INDEX["跟踪号"],
    "BF": _OSCAR_CORE_INDEX["货位"],
}

def _row_value(row, index):
    """读取预览行字段，兼容界面手工新增的不完整行。"""
    return row[index] if index < len(row) else ""


def _export_oracle_salesorder_template(
    rows, output_file, quality_status=""
):
    """按 DOC_SALESORDER_HEADER 的销售订单表头模板导出售后单数据。"""
    wb = load_workbook(SALESORDER_TEMPLATE_PATH)
    ws = wb["0"]
    del wb["系统代码说明"]

    for row_index, preview_row in enumerate(rows, start=3):
        if row_index > 3:
            for col_index in range(1, ws.max_column + 1):
                template_cell = ws.cell(row=3, column=col_index)
                target_cell = ws.cell(row=row_index, column=col_index)
                target_cell._style = copy(template_cell._style)

        for col_name, value in _SALESORDER_FIXED_VALUES.items():
            ws[f"{col_name}{row_index}"] = value
        for col_name, source_index in _SALESORDER_DYNAMIC_COLUMNS.items():
            ws[f"{col_name}{row_index}"] = (
                quality_status
                if col_name == "AL"
                else _row_value(preview_row, source_index)
            )

    wb.save(output_file)


def _export_oscar_salesorder_template(rows, output_file):
    """按 DOC_SALESORDER_HEADER_1 的销售订单表头模板导出OSCAR拣货单数据。"""
    wb = load_workbook(OSCAR_SALESORDER_TEMPLATE_PATH)
    ws = wb["0"]
    del wb["系统代码说明"]

    creation_time = time.strftime("%Y-%m-%d %H:%M:%S")

    for row_index, preview_row in enumerate(rows, start=3):
        if row_index > 3:
            for col_index in range(1, ws.max_column + 1):
                template_cell = ws.cell(row=3, column=col_index)
                target_cell = ws.cell(row=row_index, column=col_index)
                target_cell._style = copy(template_cell._style)

        ws[f"D{row_index}"] = creation_time
        for col_name, value in _OSCAR_FIXED_VALUES.items():
            ws[f"{col_name}{row_index}"] = value
        for col_name, source_index in _OSCAR_DYNAMIC_COLUMNS.items():
            ws[f"{col_name}{row_index}"] = _row_value(
                preview_row, source_index
            )

    wb.save(output_file)


def _export_invoice_po_template(rows, output_file):
    """按 DOC_PO_HEADER 的采购订单表头模板导出发票数据。"""
    wb = load_workbook(PO_TEMPLATE_PATH)
    ws = wb["采购订单表头"]
    del wb["系统代码说明"]

    now = time.localtime()
    creation_time = f"{now.tm_year}-{now.tm_mon}-{now.tm_mday} " \
                    f"{time.strftime('%H:%M:%S', now)}"

    for row_index, preview_row in enumerate(rows, start=3):
        if row_index > 3:
            for col_index in range(1, ws.max_column + 1):
                template_cell = ws.cell(row=3, column=col_index)
                target_cell = ws.cell(row=row_index, column=col_index)
                target_cell._style = copy(template_cell._style)

        ws[f"E{row_index}"] = creation_time
        for col_name, value in _INVOICE_FIXED_VALUES.items():
            ws[f"{col_name}{row_index}"] = value
        for col_name, source_index in _INVOICE_DYNAMIC_COLUMNS.items():
            ws[f"{col_name}{row_index}"] = _row_value(
                preview_row, source_index
            )
        if ws[f"B{row_index}"].value == "OSI":
            ws[f"AA{row_index}"] = "ORACLE"

    wb.save(output_file)


def write_export(prepared_export, output_file=None):
    """生成单个文件的识别结果 Excel，返回输出文件路径。"""
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    output_file = output_file or os.path.join(
        get_output_dir(), f"GE单据OCR识别结果_{timestamp}.xlsx"
    )

    if prepared_export.template == "GE-发票单":
        _export_invoice_po_template(prepared_export.rows, output_file)
        print_log(f"Excel导出完成，路径：{output_file}")
        return output_file
    if prepared_export.template == "GE-ORACLE拣货单":
        _export_oracle_salesorder_template(
            prepared_export.rows,
            output_file,
            quality_status=prepared_export.header_values.get(
                "质量状态", ""
            ),
        )
        print_log(f"Excel导出完成，路径：{output_file}")
        return output_file
    if prepared_export.template == "GE-OSCAR拣货单":
        _export_oscar_salesorder_template(
            prepared_export.rows, output_file
        )
        print_log(f"Excel导出完成，路径：{output_file}")
        return output_file

    raise ValueError(f"不支持的导出模板: {prepared_export.template}")
