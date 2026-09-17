"""无 Tk 的预览表格权威状态模型。"""

from dataclasses import dataclass, field
from types import MappingProxyType

from document_template import get_default_order_type_label


SUCCESS = "success"
FAILED = "failed"
PENDING = "pending"
MANUAL = "manual"

_VALID_STATUSES = frozenset({SUCCESS, FAILED, PENDING, MANUAL})
_UNDO_LIMIT = 20
_CONSIGNEE_TEMPLATES = frozenset({
    "GE-ORACLE拣货单",
    "GE-OSCAR拣货单",
})
_CONSIGNEE_ID_FALLBACK = "CONSIGNEEID"

_MEDICAL_DEVICE_SKU_FIELDS = {
    "GE-发票单": "ITEM NUMBER",
    "GE-ORACLE拣货单": "Item Number",
    "GE-OSCAR拣货单": "物料编号",
}
_INVOICE_SUMMARY_FIELDS = frozenset({
    "ITEM NUMBER",
    "QTY",
    "LPN Number",
})


@dataclass(frozen=True)
class DocumentMetadata:
    """预览单据的处理状态与来源信息。"""

    document_id: str
    filename: str
    status: str
    message: str = ""
    req_uuid: str = ""
    log_row: tuple = ()
    manual: bool = False


@dataclass(frozen=True)
class DocumentInput:
    """创建或替换预览单据时传入的只读输入。"""

    metadata: DocumentMetadata
    header_values: dict = field(default_factory=dict)
    rows: tuple = ()
    split_groups: tuple = ()


@dataclass(frozen=True)
class DetailLine:
    """一条只读实际明细行。"""

    line_id: str
    values: tuple
    medical_device: bool = False


@dataclass(frozen=True)
class SplitGroupView:
    """一个派生展示的拆分分组。"""

    group_id: str
    summary_values: tuple
    line_ids: tuple


@dataclass(frozen=True)
class DocumentSnapshot:
    """单个预览单据的只读业务快照。"""

    metadata: DocumentMetadata
    header_values: object
    lines: tuple
    split_groups: tuple
    medical_device_present: bool
    consignee_backfill_allowed: bool
    can_undo: bool
    template: str = ""

    @property
    def document_id(self):
        return self.metadata.document_id


@dataclass(frozen=True)
class PreviewTableSnapshot:
    """整个预览表格的只读快照。"""

    template: str
    full_headers: tuple
    header_fields: tuple
    detail_fields: tuple
    active_document_id: str
    documents: tuple


@dataclass(frozen=True)
class CommandResult:
    """一次预览表格命令的只读结果。"""

    document_id: str
    snapshot: DocumentSnapshot
    warning_codes: tuple = ()
    can_undo: bool = False
    selection_hint: tuple = ()


@dataclass
class _Line:
    line_id: str
    values: tuple


@dataclass
class _SplitGroup:
    group_id: str
    summary_values: tuple
    line_ids: list


@dataclass
class _UndoEntry:
    metadata: DocumentMetadata
    header_values: dict
    lines: tuple
    split_groups: tuple
    selection_hint: tuple


class _Document:
    def __init__(
        self,
        metadata,
        header_values,
        lines,
        split_groups,
        consignee_backfill_value="",
    ):
        self.metadata = metadata
        self.header_values = header_values
        self.lines = lines
        self.split_groups = split_groups
        self.consignee_backfill_value = consignee_backfill_value
        self.undo_stack = []
        self.next_line_number = len(lines) + 1
        self.next_group_number = len(split_groups) + 1


def _text(value):
    return "" if value is None else str(value)


def _normalize_sku(value):
    return _text(value).strip().upper()


def _require_identifier(value, label):
    text = _text(value)
    if not text:
        raise ValueError(f"{label}不能为空")
    return text


def _validate_headers(values, expected, label):
    values = tuple(values or ())
    if len(values) != len(expected):
        raise ValueError(
            f"{label}字段数量应为{len(expected)}，实际为{len(values)}"
        )
    return tuple(_text(value) for value in values)


class PreviewTable:
    """一次预览会话的权威状态。"""

    def __init__(
        self,
        template,
        full_headers,
        header_fields,
        detail_fields,
        documents,
        catalog_skus=frozenset(),
    ):
        self.template = _require_identifier(template, "模板")
        self.full_headers = tuple(full_headers or ())
        self.header_fields = tuple(header_fields or ())
        self.detail_fields = tuple(detail_fields or ())
        self._validate_table_fields()
        self._catalog_skus = self._normalize_catalog_skus(catalog_skus)
        self._documents = {}
        self._active_document_id = ""

        document_inputs = tuple(documents or ())
        if document_inputs and not isinstance(document_inputs[0], DocumentInput):
            raise ValueError("documents 必须是 DocumentInput 序列")
        for document in document_inputs:
            if not isinstance(document, DocumentInput):
                raise ValueError("documents 必须是 DocumentInput 序列")
            document_id = self._validate_document_input(document)
            if document_id in self._documents:
                raise ValueError(f"重复的预览单据 ID: {document_id}")
            self._documents[document_id] = self._create_document(document)
            if not self._active_document_id:
                self._active_document_id = document_id

    def _validate_table_fields(self):
        for label, fields in (
            ("full_headers", self.full_headers),
            ("header_fields", self.header_fields),
            ("detail_fields", self.detail_fields),
        ):
            if len(set(fields)) != len(fields):
                raise ValueError(f"{label} 包含重复字段")
        unknown_headers = set(self.header_fields) - set(self.full_headers)
        unknown_details = set(self.detail_fields) - set(self.full_headers)
        if unknown_headers:
            raise ValueError(f"未知单据头字段: {sorted(unknown_headers)}")
        if unknown_details:
            raise ValueError(f"未知明细字段: {sorted(unknown_details)}")

    def _validate_document_input(self, document):
        if not isinstance(document, DocumentInput):
            raise ValueError("document 必须是 DocumentInput")
        metadata = document.metadata
        if not isinstance(metadata, DocumentMetadata):
            raise ValueError("document.metadata 必须是 DocumentMetadata")
        document_id = _require_identifier(metadata.document_id, "单据 ID")
        _require_identifier(metadata.filename, "文件名")
        if metadata.status not in _VALID_STATUSES:
            raise ValueError(f"未知处理状态: {metadata.status}")
        unknown_headers = set(document.header_values) - set(self.full_headers)
        if unknown_headers:
            raise ValueError(f"未知单据头字段: {sorted(unknown_headers)}")
        for row in document.rows:
            if len(tuple(row)) != len(self.full_headers):
                raise ValueError("输入明细字段数量与 full_headers 不一致")
        return document_id

    def _create_document(self, document):
        metadata = DocumentMetadata(
            document_id=document.metadata.document_id,
            filename=document.metadata.filename,
            status=document.metadata.status,
            message=_text(document.metadata.message),
            req_uuid=_text(document.metadata.req_uuid),
            log_row=tuple(document.metadata.log_row or ()),
            manual=bool(document.metadata.manual),
        )
        header_values = self._merge_header_values(
            document.header_values, document.rows
        )
        lines = []
        for index, row in enumerate(document.rows, start=1):
            full_values = _validate_headers(
                row, self.full_headers, "明细行"
            )
            row_map = dict(zip(self.full_headers, full_values))
            lines.append(_Line(
                f"line-{index}",
                tuple(row_map.get(field, "") for field in self.detail_fields),
            ))
        split_groups = self._build_split_groups(document.split_groups, lines)
        return _Document(metadata, header_values, lines, split_groups)

    def _merge_header_values(self, provided, rows):
        values = {field: "" for field in self.full_headers}
        for row in rows or ():
            row_map = dict(zip(self.full_headers, row))
            for field in self.full_headers:
                value = _text(row_map.get(field, ""))
                if not values[field] and value.strip():
                    values[field] = value
        for field, value in (provided or {}).items():
            values[field] = _text(value)
        if (
            "订单类型" in values
            and not values["订单类型"].strip()
        ):
            values["订单类型"] = get_default_order_type_label(self.template)
        if (
            self.template in _CONSIGNEE_TEMPLATES
            and "客商编码" in values
        ):
            values["客商编码"] = ""
        return values

    def _build_split_groups(self, raw_groups, lines):
        groups = []
        grouped_line_ids = set()
        for index, raw_group in enumerate(raw_groups or (), start=1):
            if not isinstance(raw_group, dict):
                raise ValueError("拆分分组必须是字典")
            child_indexes = tuple(raw_group.get("child_indexes") or ())
            for child_index in child_indexes:
                if (
                    not isinstance(child_index, int)
                    or child_index < 0
                    or child_index >= len(lines)
                ):
                    raise ValueError(f"非法拆分子行索引: {child_index}")
            if len(child_indexes) < 2:
                continue
            child_line_ids = tuple(
                lines[child_index].line_id for child_index in child_indexes
            )
            if grouped_line_ids.intersection(child_line_ids):
                raise ValueError("同一明细行不能属于多个拆分分组")
            summary_row = raw_group.get("summary_row") or ()
            if summary_row:
                summary_values = _validate_headers(
                    summary_row, self.full_headers, "拆分汇总行"
                )
            else:
                summary_values = tuple("" for _ in self.full_headers)
            summary_map = dict(zip(self.full_headers, summary_values))
            display_summary = tuple(
                summary_map.get(field, "") for field in self.detail_fields
            )
            if self.template == "GE-发票单":
                display_summary = tuple(
                    value if field in _INVOICE_SUMMARY_FIELDS else ""
                    for field, value in zip(
                        self.detail_fields, display_summary
                    )
                )
            groups.append(_SplitGroup(
                group_id=f"split-{index}",
                summary_values=display_summary,
                line_ids=list(child_line_ids),
            ))
            grouped_line_ids.update(child_line_ids)
        return groups

    @staticmethod
    def _normalize_catalog_skus(catalog_skus):
        if catalog_skus is None:
            return frozenset()
        return frozenset(
            normalized
            for normalized in (
                _normalize_sku(value) for value in catalog_skus
            )
            if normalized
        )

    def _require_document(self, document_id):
        document_id = _require_identifier(document_id, "单据 ID")
        try:
            return self._documents[document_id]
        except KeyError as exc:
            raise ValueError(f"未知预览单据 ID: {document_id}") from exc

    def _line(self, document, line_id):
        line_id = _require_identifier(line_id, "明细行 ID")
        for line in document.lines:
            if line.line_id == line_id:
                return line
        raise ValueError(f"未知明细行 ID: {line_id}")

    def _line_index(self, document, line_id):
        for index, line in enumerate(document.lines):
            if line.line_id == line_id:
                return index
        raise ValueError(f"未知明细行 ID: {line_id}")

    def _group_for_line(self, document, line_id):
        for group in document.split_groups:
            if line_id in group.line_ids:
                return group
        return None

    def _medical_device_line_ids(self, document):
        field = _MEDICAL_DEVICE_SKU_FIELDS.get(self.template, "")
        if not field or not self._catalog_skus:
            return set()
        try:
            field_index = self.detail_fields.index(field)
        except ValueError:
            return set()
        line_ids = set()
        for line in document.lines:
            if field_index >= len(line.values):
                continue
            sku = _normalize_sku(line.values[field_index])
            if sku and sku in self._catalog_skus:
                line_ids.add(line.line_id)
        return line_ids

    def _effective_consignee_id(self, document, medical_present):
        if (
            self.template not in _CONSIGNEE_TEMPLATES
            or "客商编码" not in self.header_fields
        ):
            return ""
        if medical_present:
            return document.consignee_backfill_value
        return _CONSIGNEE_ID_FALLBACK

    def _consignee_backfill_allowed(self, document, medical_present):
        return (
            self.template in _CONSIGNEE_TEMPLATES
            and "客商编码" in self.header_fields
            and medical_present
        )

    def _snapshot_document(self, document):
        medical_line_ids = self._medical_device_line_ids(document)
        medical_present = bool(medical_line_ids)
        header_values = dict(document.header_values)
        if (
            self.template in _CONSIGNEE_TEMPLATES
            and "客商编码" in header_values
        ):
            header_values["客商编码"] = self._effective_consignee_id(
                document, medical_present
            )
        lines = tuple(
            DetailLine(
                line_id=line.line_id,
                values=tuple(line.values),
                medical_device=line.line_id in medical_line_ids,
            )
            for line in document.lines
        )
        groups = tuple(
            SplitGroupView(
                group_id=group.group_id,
                summary_values=tuple(group.summary_values),
                line_ids=tuple(group.line_ids),
            )
            for group in document.split_groups
        )
        return DocumentSnapshot(
            metadata=document.metadata,
            header_values=MappingProxyType(header_values),
            lines=lines,
            split_groups=groups,
            medical_device_present=medical_present,
            consignee_backfill_allowed=self._consignee_backfill_allowed(
                document, medical_present
            ),
            can_undo=bool(document.undo_stack),
            template=self.template,
        )

    def _command_result(self, document, selection_hint=(), can_undo=None):
        snapshot = self._snapshot_document(document)
        warnings = (
            ("medical_device_present",)
            if snapshot.medical_device_present else ()
        )
        return CommandResult(
            document_id=document.metadata.document_id,
            snapshot=snapshot,
            warning_codes=warnings,
            can_undo=(
                snapshot.can_undo if can_undo is None else can_undo
            ),
            selection_hint=tuple(selection_hint),
        )

    def _push_undo(self, document, selection_hint=()):
        entry = _UndoEntry(
            metadata=document.metadata,
            header_values=dict(document.header_values),
            lines=tuple(
                _Line(line.line_id, tuple(line.values))
                for line in document.lines
            ),
            split_groups=tuple(
                _SplitGroup(
                    group.group_id,
                    tuple(group.summary_values),
                    list(group.line_ids),
                )
                for group in document.split_groups
            ),
            selection_hint=tuple(selection_hint),
        )
        document.undo_stack.append(entry)
        if len(document.undo_stack) > _UNDO_LIMIT:
            del document.undo_stack[0]

    def _restore_undo(self, document, entry):
        document.metadata = entry.metadata
        document.header_values = dict(entry.header_values)
        document.lines = [
            _Line(line.line_id, tuple(line.values))
            for line in entry.lines
        ]
        document.split_groups = [
            _SplitGroup(
                group.group_id,
                tuple(group.summary_values),
                list(group.line_ids),
            )
            for group in entry.split_groups
        ]

    def snapshot(self, document_id):
        """返回指定预览单据的只读快照。"""
        return self._snapshot_document(self._require_document(document_id))

    def snapshot_table(self):
        """返回整个预览表格的只读快照。"""
        return PreviewTableSnapshot(
            template=self.template,
            full_headers=tuple(self.full_headers),
            header_fields=tuple(self.header_fields),
            detail_fields=tuple(self.detail_fields),
            active_document_id=self._active_document_id,
            documents=tuple(
                self._snapshot_document(document)
                for document in self._documents.values()
            ),
        )

    def select_document(self, document_id):
        """切换当前预览单据。"""
        document = self._require_document(document_id)
        self._active_document_id = document.metadata.document_id
        return self._command_result(document)

    def update_header(self, document_id, field, value, record_undo=True):
        """修改单据头字段。"""
        document = self._require_document(document_id)
        if field not in self.header_fields:
            raise ValueError(f"未知单据头字段: {field}")
        if field == "客商编码" and self.template in _CONSIGNEE_TEMPLATES:
            raise ValueError("客商编码不能直接修改，请使用客商编码回填")
        value = _text(value)
        if document.header_values.get(field, "") == value:
            return self._command_result(document)
        if record_undo:
            self._push_undo(document, selection_hint=())
        document.header_values[field] = value
        return self._command_result(document)

    def backfill_consignee(self, document_id, customer_id):
        """从客商查询记录回填当前预览单据的客商编码。"""
        document = self._require_document(document_id)
        if (
            self.template not in _CONSIGNEE_TEMPLATES
            or "客商编码" not in self.header_fields
        ):
            raise ValueError("当前单据模板不支持回填客商编码")
        medical_present = bool(self._medical_device_line_ids(document))
        if not medical_present:
            raise ValueError("当前页签未命中医疗器械，不能回填客商编码")
        customer_id = _text(customer_id).strip()
        if not customer_id:
            raise ValueError("客商编码不能为空")
        document.consignee_backfill_value = customer_id
        return self._command_result(document)

    def update_line(self, document_id, line_id, field, value):
        """修改一条实际明细行。"""
        document = self._require_document(document_id)
        if field not in self.detail_fields:
            raise ValueError(f"未知明细字段: {field}")
        line = self._line(document, line_id)
        field_index = self.detail_fields.index(field)
        value = _text(value)
        if line.values[field_index] == value:
            return self._command_result(
                document, selection_hint=(line.line_id,)
            )
        self._push_undo(document, selection_hint=(line.line_id,))
        values = list(line.values)
        values[field_index] = value
        line.values = tuple(values)
        return self._command_result(
            document, selection_hint=(line.line_id,)
        )

    def _new_line(self, document, values):
        line_id = f"line-{document.next_line_number}"
        document.next_line_number += 1
        return _Line(line_id, tuple(_text(value) for value in values))

    def _insert_line(self, document, after_line_id, values):
        line = self._new_line(document, values)
        if after_line_id is None:
            document.lines.append(line)
            return line
        after_index = self._line_index(document, after_line_id)
        document.lines.insert(after_index + 1, line)
        group = self._group_for_line(document, after_line_id)
        if group is not None:
            group_index = group.line_ids.index(after_line_id)
            group.line_ids.insert(group_index + 1, line.line_id)
        return line

    def insert_line(self, document_id, after_line_id=None):
        """在指定实际明细行之后插入空白行。"""
        document = self._require_document(document_id)
        if after_line_id is not None:
            self._line(document, after_line_id)
        self._push_undo(
            document,
            selection_hint=(
                () if after_line_id is None else (after_line_id,)
            ),
        )
        line = self._insert_line(
            document, after_line_id, ("",) * len(self.detail_fields)
        )
        return self._command_result(
            document, selection_hint=(line.line_id,)
        )

    def delete_lines(self, document_id, line_ids):
        """删除一组实际明细行。"""
        document = self._require_document(document_id)
        line_ids = tuple(dict.fromkeys(line_ids or ()))
        if not line_ids:
            return self._command_result(document)
        for line_id in line_ids:
            self._line(document, line_id)
        self._push_undo(document, selection_hint=line_ids)
        deleted = set(line_ids)
        document.lines = [
            line for line in document.lines if line.line_id not in deleted
        ]
        groups = []
        for group in document.split_groups:
            group.line_ids = [
                line_id for line_id in group.line_ids
                if line_id not in deleted
            ]
            if len(group.line_ids) >= 2:
                groups.append(group)
        document.split_groups = groups
        return self._command_result(document)

    def paste_lines(self, document_id, after_line_id, rows):
        """在指定位置后插入一组实际明细行。"""
        document = self._require_document(document_id)
        if after_line_id is not None:
            self._line(document, after_line_id)
        normalized_rows = tuple(
            _validate_headers(row, self.detail_fields, "粘贴行")
            for row in rows or ()
        )
        if not normalized_rows:
            raise ValueError("粘贴行不能为空")
        self._push_undo(
            document,
            selection_hint=(
                () if after_line_id is None else (after_line_id,)
            ),
        )
        inserted_ids = []
        current_after = after_line_id
        for row in normalized_rows:
            line = self._insert_line(document, current_after, row)
            inserted_ids.append(line.line_id)
            current_after = line.line_id
        return self._command_result(
            document, selection_hint=tuple(inserted_ids)
        )

    def undo(self, document_id):
        """撤销指定预览单据最近一次业务变更。"""
        document = self._require_document(document_id)
        if not document.undo_stack:
            return self._command_result(document)
        entry = document.undo_stack.pop()
        self._restore_undo(document, entry)
        return self._command_result(
            document, selection_hint=entry.selection_hint
        )

    def replace_document(self, document_id, document):
        """用新识别结果替换单据内容并保留单据 ID。"""
        target_id = _require_identifier(document_id, "单据 ID")
        current = self._require_document(target_id)
        self._validate_document_input(document)
        if document.metadata.document_id != target_id:
            raise ValueError("替换单据必须保留原单据 ID")
        replaced = self._create_document(document)
        replaced.consignee_backfill_value = (
            current.consignee_backfill_value
        )
        self._documents[target_id] = replaced
        if not self._active_document_id:
            self._active_document_id = target_id
        return self._command_result(replaced)

    def update_status(self, document_id, status, message=""):
        """更新处理状态或状态说明，不进入撤销栈。"""
        document = self._require_document(document_id)
        if status not in _VALID_STATUSES:
            raise ValueError(f"未知处理状态: {status}")
        document.metadata = DocumentMetadata(
            document_id=document.metadata.document_id,
            filename=document.metadata.filename,
            status=status,
            message=_text(message),
            req_uuid=document.metadata.req_uuid,
            log_row=document.metadata.log_row,
            manual=document.metadata.manual,
        )
        return self._command_result(document)

    def refresh_catalog(self, catalog_skus):
        """替换医疗器械 SKU 目录并重算全部预览单据。"""
        self._catalog_skus = self._normalize_catalog_skus(catalog_skus)
        return self.snapshot_table()
