"""医疗器械 SKU 查询、本地缓存与单据匹配。"""

import json
import os
from pathlib import Path
import tempfile

import requests

from config import (
    WMS_CUSTOMER_ID,
    WMS_QUERY_MEDICAL_DEVICE_URL,
    WMS_WAREHOUSE_ID,
)


MEDICAL_DEVICE_WARNING = "该订单包含医疗器械（标红显示），请注意！"
MEDICAL_DEVICE_CACHE_FILENAME = ".ge_tool_medical_device_skus.json"
MEDICAL_DEVICE_GROUP_FIELDS = (
    "sku_Group1",
    "sku_Group2",
    "sku_Group3",
    "sku_Group4",
    "sku_Group5",
)
MEDICAL_DEVICE_GROUP_YES_VALUES = {
    "sku_Group1": "SNY",
    "sku_Group2": "LOTY",
    "sku_Group3": "EXPY",
    "sku_Group4": "HAZARDY",
    "sku_Group5": "TUBE",
}
MEDICAL_DEVICE_SKU_FIELDS_BY_TEMPLATE = {
    "GE-发票单": "ITEM NUMBER",
    "GE-ORACLE拣货单": "Item Number",
    "GE-OSCAR拣货单": "物料编号",
}


def normalize_medical_device_sku(value):
    """统一 SKU 的空白与大小写，保留前导零和连字符。"""
    if value is None:
        return ""
    return str(value).strip().upper()


def _normalize_medical_device_group_value(value):
    """去除产品属性首尾空白，空值规范为接口空字符串。"""
    if value is None:
        return ""
    return str(value).strip()


def _normalize_medical_device_catalog_record(
    record, preserve_none_values=False
):
    """规范化一条 catalog 记录；旧缓存缺失的属性保留为未知。"""
    sku = normalize_medical_device_sku(record.get("sku"))
    if not sku:
        return None
    normalized = {"sku": sku}
    for field in MEDICAL_DEVICE_GROUP_FIELDS:
        if field not in record:
            normalized[field] = None
        elif preserve_none_values and record.get(field) is None:
            normalized[field] = None
        else:
            normalized[field] = _normalize_medical_device_group_value(
                record.get(field)
            )
    return normalized


def _normalize_medical_device_catalog(catalog, preserve_none_values=False):
    """去重并规范化 catalog，首次出现的 SKU 记录生效。"""
    if not isinstance(catalog, list):
        return []
    normalized = []
    seen_skus = set()
    for item in catalog:
        if isinstance(item, str):
            record = _normalize_medical_device_catalog_record(
                {"sku": item},
                preserve_none_values=preserve_none_values,
            )
        elif isinstance(item, dict):
            record = _normalize_medical_device_catalog_record(
                item,
                preserve_none_values=preserve_none_values,
            )
        else:
            continue
        if record is None or record["sku"] in seen_skus:
            continue
        seen_skus.add(record["sku"])
        normalized.append(record)
    return sorted(normalized, key=lambda item: item["sku"])


def extract_medical_device_catalog(response_body):
    """从 QUERYMD 回告中提取去重后的医疗器械记录。"""
    try:
        items = response_body["Response"]["items"]["item"]
    except (KeyError, TypeError) as exc:
        raise ValueError("医疗器械查询回告缺少 item 明细") from exc
    if items is None:
        return []
    if isinstance(items, dict):
        items = [items]
    if not isinstance(items, list):
        raise ValueError("医疗器械查询回告 item 格式异常")
    if any(not isinstance(item, dict) for item in items):
        raise ValueError("医疗器械查询回告 item 明细格式异常")

    catalog = []
    for item in items:
        record = {"sku": item.get("sku")}
        for field in MEDICAL_DEVICE_GROUP_FIELDS:
            value = item.get(field)
            record[field] = _normalize_medical_device_group_value(
                "" if value is None else value
            )
        catalog.append(record)
    return _normalize_medical_device_catalog(catalog)


def query_medical_device_catalog(timeout=10):
    """调用 QUERYMD 接口并返回医疗器械记录，仅 HTTP 200 视为成功。"""
    payload = {
        "data": {
            "header": {
                "warehouseId": WMS_WAREHOUSE_ID,
                "customerId": WMS_CUSTOMER_ID,
            }
        }
    }
    response = requests.post(
        WMS_QUERY_MEDICAL_DEVICE_URL, json=payload, timeout=timeout
    )
    if response.status_code != 200:
        raise RuntimeError(f"医疗器械查询接口 HTTP {response.status_code}")
    try:
        response_body = response.json()
    except ValueError as exc:
        raise ValueError("医疗器械查询回告不是有效 JSON") from exc
    return extract_medical_device_catalog(response_body)


def get_medical_device_sku_cache_path():
    """返回三端共用的用户主目录缓存路径。"""
    return Path.home() / MEDICAL_DEVICE_CACHE_FILENAME


def load_medical_device_catalog(cache_path=None):
    """读取本地 catalog；兼容旧版纯 SKU 数组缓存。"""
    path = Path(cache_path) if cache_path is not None else (
        get_medical_device_sku_cache_path()
    )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return []
    if not isinstance(data, list):
        return []
    return _normalize_medical_device_catalog(
        data, preserve_none_values=True
    )


def save_medical_device_catalog(catalog, cache_path=None):
    """以原子替换方式覆盖本地 catalog 缓存。"""
    path = Path(cache_path) if cache_path is not None else (
        get_medical_device_sku_cache_path()
    )
    normalized = _normalize_medical_device_catalog(catalog)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=str(path.parent),
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
            json.dump(normalized, temp_file, ensure_ascii=False, indent=2)
            temp_file.write("\n")
        os.replace(str(temp_path), str(path))
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()
    return normalized


def refresh_or_load_medical_device_catalog(cache_path=None, timeout=10):
    """优先查询并覆盖缓存；失败时返回上次缓存，并附带错误。"""
    path = Path(cache_path) if cache_path is not None else (
        get_medical_device_sku_cache_path()
    )
    try:
        catalog = query_medical_device_catalog(timeout=timeout)
        save_medical_device_catalog(catalog, cache_path=path)
        return catalog, "network", None
    except Exception as exc:
        cached_catalog = load_medical_device_catalog(cache_path=path)
        source = "cache" if path.exists() else "empty"
        return cached_catalog, source, exc


def medical_device_catalog_skus(catalog):
    """从 catalog 派生医疗器械 SKU 集合。"""
    return {
        record["sku"]
        for record in catalog
        if normalize_medical_device_sku(record.get("sku"))
    }


def medical_device_catalog_display_rows(catalog):
    """把 catalog 转成列表窗口使用的显示行。"""
    rows = []
    for record in catalog:
        row = [normalize_medical_device_sku(record.get("sku"))]
        for field in MEDICAL_DEVICE_GROUP_FIELDS:
            value = record.get(field)
            if value is None:
                row.append("")
            elif str(value).strip() == MEDICAL_DEVICE_GROUP_YES_VALUES[field]:
                row.append("Y")
            else:
                row.append("N")
        rows.append(row)
    return rows


def filter_medical_device_catalog_rows(rows, search_text):
    """按 SKU 做不区分大小写的包含匹配。"""
    query = str(search_text or "").strip().casefold()
    if not query:
        return [list(row) for row in rows]
    return [
        list(row) for row in rows
        if query in str(row[0]).casefold()
    ]


def sort_medical_device_catalog_rows(rows, column_index, descending=False):
    """按指定列进行稳定的不区分大小写排序。"""
    non_empty = [
        row for row in rows if str(row[column_index]).strip()
    ]
    empty = [
        row for row in rows if not str(row[column_index]).strip()
    ]
    non_empty.sort(
        key=lambda row: str(row[column_index]).casefold(),
        reverse=descending,
    )
    return non_empty + empty


def extract_medical_device_skus(response_body):
    """兼容旧调用：从 catalog 回告派生去重后的 SKU 列表。"""
    catalog = extract_medical_device_catalog(response_body)
    return sorted(medical_device_catalog_skus(catalog))


def query_medical_device_skus(timeout=10):
    """兼容旧调用：查询 QUERYMD 并返回 SKU 列表。"""
    catalog = query_medical_device_catalog(timeout=timeout)
    return sorted(medical_device_catalog_skus(catalog))


def load_medical_device_skus(cache_path=None):
    """兼容旧调用：从 catalog 缓存派生 SKU 列表。"""
    catalog = load_medical_device_catalog(cache_path=cache_path)
    return sorted(medical_device_catalog_skus(catalog))


def save_medical_device_skus(skus, cache_path=None):
    """兼容旧调用：把 SKU 列表按无属性记录写入 catalog 缓存。"""
    catalog = [{"sku": sku} for sku in skus]
    saved_catalog = save_medical_device_catalog(
        catalog, cache_path=cache_path
    )
    return sorted(medical_device_catalog_skus(saved_catalog))


def refresh_or_load_medical_device_skus(cache_path=None, timeout=10):
    """兼容旧调用：刷新或加载 catalog 后返回 SKU 列表。"""
    catalog, source, error = refresh_or_load_medical_device_catalog(
        cache_path=cache_path, timeout=timeout
    )
    return sorted(medical_device_catalog_skus(catalog)), source, error


def get_medical_device_sku_field(select_text):
    """返回指定单据模板保存物料编码的明细字段名。"""
    return MEDICAL_DEVICE_SKU_FIELDS_BY_TEMPLATE.get(select_text, "")


def row_contains_medical_device_sku(
    row, detail_fields, select_text, medical_device_skus
):
    """判断一条预览明细行是否包含缓存中的医疗器械 SKU。"""
    field = get_medical_device_sku_field(select_text)
    if not field or not medical_device_skus:
        return False
    try:
        field_index = detail_fields.index(field)
    except ValueError:
        return False
    if field_index >= len(row):
        return False
    sku = normalize_medical_device_sku(row[field_index])
    return bool(sku) and sku in medical_device_skus
