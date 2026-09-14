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


def extract_medical_device_skus(response_body):
    """从 QUERYMD 回告中提取去重后的医疗器械 SKU 列表。"""
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

    skus = {normalize_medical_device_sku(item.get("sku")) for item in items}
    skus.discard("")
    return sorted(skus)


def query_medical_device_skus(timeout=10):
    """调用 QUERYMD 接口并返回 SKU 列表，仅 HTTP 200 视为成功。"""
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
    return extract_medical_device_skus(response_body)


def get_medical_device_sku_cache_path():
    """返回三端共用的用户主目录缓存路径。"""
    return Path.home() / MEDICAL_DEVICE_CACHE_FILENAME


def load_medical_device_skus(cache_path=None):
    """读取本地 SKU 列表；文件缺失或损坏时返回空列表。"""
    path = Path(cache_path) if cache_path is not None else (
        get_medical_device_sku_cache_path()
    )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return []
    if not isinstance(data, list):
        return []
    skus = {normalize_medical_device_sku(sku) for sku in data}
    skus.discard("")
    return sorted(skus)


def save_medical_device_skus(skus, cache_path=None):
    """以原子替换方式覆盖本地 SKU 列表缓存。"""
    path = Path(cache_path) if cache_path is not None else (
        get_medical_device_sku_cache_path()
    )
    normalized_skus = {normalize_medical_device_sku(sku) for sku in skus}
    normalized_skus.discard("")
    normalized = sorted(normalized_skus)
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


def refresh_or_load_medical_device_skus(cache_path=None, timeout=10):
    """优先查询并覆盖缓存；失败时返回上次缓存，并附带错误。"""
    path = Path(cache_path) if cache_path is not None else (
        get_medical_device_sku_cache_path()
    )
    try:
        skus = query_medical_device_skus(timeout=timeout)
        save_medical_device_skus(skus, cache_path=path)
        return skus, "network", None
    except Exception as exc:
        cached_skus = load_medical_device_skus(cache_path=path)
        source = "cache" if path.exists() else "empty"
        return cached_skus, source, exc


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
