"""演示用固定样例数据，结构与真实解析结果一致，不调用接口。"""

from parsers import RecognitionResult


def _result(header_values, detail_lines, split_groups=()):
    return RecognitionResult(
        header_values=header_values,
        detail_lines=tuple(detail_lines),
        split_groups=tuple(split_groups),
    )


def generate_mock_data(select_text):
    """按模板生成两个演示文件页签的模拟识别结果。"""
    if select_text == "GE-ORACLE拣货单":
        first = _result(
            {
                "Pick Slip Print Date": "19-MAY-26 16:44:22",
                "Order Number": "PO240821-001",
                "OrderType": "ORACLE",
                "Ordered Date": "19-MAY-26",
                "Shipment Priority": "P1",
                "Ship Method": "AIR",
                "Service Level": "STANDARD",
                "FE SSO": "SSO001",
                "FE Name": "ZHANGSAN",
                "SHIP TO NO": "SHIP-001",
                "Ship To Address": "NO.100 ZHANGJIANG ROAD SHANGHAI",
                "Shipping Instruction": "SHIP ASAP",
                "Customer Name": "GE HEALTHCARE",
                "Customer Number": "CUS-1001",
                "System Id": "SYS-01",
                "Pick From Subinv": "SUBINV-A",
                "Customer PO": "PO-2026-001",
                "Delivery": "DEL-20260821-01",
                "Email": "FE@GE.COM",
            },
            (
                {
                    "Task Id": "T1001",
                    "Item Number": "ITEM-A001",
                    "Qty": "10",
                    "LPN": "LPN-A18-480056",
                    "Serial": "SN-12444",
                    "Pick From Locator": "A-01-01",
                    "Org": "99999",
                },
                {
                    "Task Id": "T1002",
                    "Item Number": "ITEM-B001",
                    "Qty": "5",
                    "LPN": "LPN-B02",
                    "Lot": "LOT-B02",
                    "COO": "US",
                    "Pick From Locator": "B-02-03",
                    "Org": "99999",
                },
            ),
        )
        second = _result(
            {
                "Pick Slip Print Date": "19-MAY-26 16:44:22",
                "Order Number": "PO240821-002",
                "OrderType": "ORACLE",
                "Ordered Date": "19-MAY-26",
                "Shipment Priority": "P2",
                "Ship Method": "SEA",
                "Service Level": "STANDARD",
                "FE SSO": "SSO002",
                "FE Name": "LISI",
                "SHIP TO NO": "SHIP-002",
                "Ship To Address": "NO.200 PUJIAN ROAD SHANGHAI",
                "Customer Name": "GE HEALTHCARE",
                "Customer Number": "CUS-1002",
                "System Id": "SYS-02",
                "Pick From Subinv": "SUBINV-B",
                "Customer PO": "PO-2026-002",
                "Delivery": "DEL-20260821-02",
                "Email": "FE2@GE.COM",
            },
            (
                {
                    "Task Id": "T2001",
                    "Item Number": "ITEM-C001",
                    "Qty": "8",
                    "LPN": "LPN-C03",
                    "Serial": "SN-C03",
                    "Lot": "LOT-C03",
                    "COO": "DE",
                    "Pick From Locator": "C-03-05",
                    "Org": "99999",
                },
            ),
        )
    elif select_text == "GE-OSCAR拣货单":
        first = _result(
            {
                "服务申请号": "SA20260821-01",
                "SR编号": "SR-001",
                "时效": "24H",
                "供应商": "GE SUPPLIER",
                "收货人": "RECEIVER-01",
                "收货地址": "NO.1 SUPPLY ROAD SHANGHAI",
                "收货人电话": "13800000001",
                "申请说明": "APPLICATION NOTE",
                "SSO": "SSO-OSC-01",
                "姓名": "LI SI",
                "客户设备id": "DEVICE-001",
            },
            (
                {
                    "物料编号": "MT-OSC-001",
                    "数量": "12",
                    "序列号": "SN-0001",
                    "货位": "LOC-01",
                    "仓库": "WH-A",
                    "状态": "好件",
                    "跟踪号": "TR-0001",
                },
                {
                    "物料编号": "MT-OSC-002",
                    "数量": "6",
                    "序列号": "SN-0002",
                    "货位": "LOC-02",
                    "仓库": "WH-A",
                    "状态": "PICKED",
                    "跟踪号": "TR-0002",
                },
            ),
        )
        second = _result(
            {
                "服务申请号": "SA20260821-02",
                "SR编号": "SR-002",
                "时效": "48H",
                "供应商": "GE SUPPLIER",
                "收货人": "RECEIVER-02",
                "收货地址": "NO.2 SUPPLY ROAD SHANGHAI",
                "收货人电话": "13900000002",
                "申请说明": "APPLICATION NOTE 2",
                "SSO": "SSO-OSC-02",
                "姓名": "WANG WU",
                "客户设备id": "DEVICE-002",
            },
            (
                {
                    "物料编号": "MT-OSC-003",
                    "数量": "3",
                    "序列号": "SN-0003",
                    "货位": "LOC-03",
                    "仓库": "WH-B",
                    "状态": "好件",
                    "跟踪号": "TR-0003",
                },
            ),
        )
    elif select_text == "GE-发票单":
        first_header = {
            "INVOICE NO": "INV20260821-01",
            "DATE": "2026/08/21",
            "DELIVERY": "DEL-20260821",
            "CARRIER": "FEDEX",
            "HAWB": "HAWB-001",
        }
        first = _result(
            first_header,
            (
                {
                    "ITEM NUMBER": "ITEM-INV-001",
                    "QTY": "1",
                    "LPN Number": "LPN-1",
                    "LOT Number": "LOT-01",
                    "Expiration Date": "2026/09/30",
                    "COUNTRY OF ORIGIN": "CN",
                    "SALES ORDER NO": "SO-001",
                    "CUSTOMER PO": "PO-001",
                },
                {
                    "ITEM NUMBER": "ITEM-INV-001",
                    "QTY": "1",
                    "LPN Number": "LPN-2",
                    "LOT Number": "LOT-01",
                    "Expiration Date": "2026/09/30",
                    "COUNTRY OF ORIGIN": "CN",
                    "SALES ORDER NO": "SO-001",
                    "CUSTOMER PO": "PO-001",
                },
                {
                    "ITEM NUMBER": "ITEM-INV-001",
                    "QTY": "1",
                    "LPN Number": "LPN-3",
                    "LOT Number": "LOT-01",
                    "Expiration Date": "2026/09/30",
                    "COUNTRY OF ORIGIN": "CN",
                    "SALES ORDER NO": "SO-001",
                    "CUSTOMER PO": "PO-001",
                },
                {
                    "ITEM NUMBER": "ITEM-INV-002",
                    "QTY": "1",
                    "LPN Number": "LPN-4",
                    "Serial Number": "SN-A",
                    "LOT Number": "LOT-02",
                    "Expiration Date": "2026/10/31",
                    "COUNTRY OF ORIGIN": "US",
                    "SALES ORDER NO": "SO-002",
                    "CUSTOMER PO": "PO-002",
                },
                {
                    "ITEM NUMBER": "ITEM-INV-002",
                    "QTY": "1",
                    "LPN Number": "LPN-4",
                    "Serial Number": "SN-B",
                    "LOT Number": "LOT-02",
                    "Expiration Date": "2026/10/31",
                    "COUNTRY OF ORIGIN": "US",
                    "SALES ORDER NO": "SO-002",
                    "CUSTOMER PO": "PO-002",
                },
            ),
            (
                {
                    "child_indexes": (0, 1, 2),
                    "summary_values": {
                        "ITEM NUMBER": "ITEM-INV-001",
                        "QTY": "3",
                        "LPN Number": "原始行汇总",
                    },
                },
                {
                    "child_indexes": (3, 4),
                    "summary_values": {
                        "ITEM NUMBER": "ITEM-INV-002",
                        "QTY": "2",
                        "LPN Number": "原始行汇总",
                    },
                },
            ),
        )
        second = _result(
            {
                "INVOICE NO": "INV20260821-02",
                "DATE": "2026/08/22",
                "DELIVERY": "DEL-20260822",
                "CARRIER": "DHL",
                "HAWB": "HAWB-002",
            },
            (
                {
                    "ITEM NUMBER": "ITEM-INV-003",
                    "QTY": "1",
                    "LPN Number": "LPN-9",
                    "Serial Number": "SN-C",
                    "LOT Number": "LOT-03",
                    "Expiration Date": "2026/11/30",
                    "COUNTRY OF ORIGIN": "DE",
                    "SALES ORDER NO": "SO-003",
                    "CUSTOMER PO": "PO-003",
                },
            ),
        )
    else:
        raise ValueError(f"未知模板: {select_text}")

    return [
        {
            "filename": "模拟文件-01.png",
            "status": "成功",
            "message": "模拟数据，未调用 OCR",
            "recognition_result": first,
        },
        {
            "filename": "模拟文件-02.pdf",
            "status": "成功",
            "message": "模拟数据，未调用 OCR",
            "recognition_result": second,
        },
    ]
