"""Tkinter 入口模块，负责界面、后台线程与批量处理编排。"""

import json
import os
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import tkinter.font as tkfont
from tkinterdnd2 import DND_FILES, TkinterDnD

from config import FEISHU_CALL_TIMES, MODEL_MAP
from customer_client import (
    CUSTOMER_COLUMNS,
    customer_record_display_rows,
    filter_customer_record_display_rows,
    query_customer_records,
)
from excel_export import (
    export_excel,
    get_last_export_dir,
    get_output_dir,
    save_last_export_dir,
)
from feishu_client import get_tenant_access_token, send_to_bitable_repeated
from logging_utils import log_queue, print_log
from medical_device_client import (
    MEDICAL_DEVICE_WARNING,
    filter_medical_device_catalog_rows,
    load_medical_device_catalog,
    medical_device_catalog_display_rows,
    medical_device_catalog_skus,
    refresh_or_load_medical_device_catalog,
    sort_medical_device_catalog_rows,
)
from mock_data import generate_mock_data
from ocr_client import (
    OCRAborted,
    OCRResultTimeout,
    call_get_result_api,
    call_process_api,
    upload_file_to_server,
)
from parsers import (
    get_core_headers,
    get_default_order_type_label,
    get_order_type_labels,
    get_preview_layout,
    get_preview_wide_fields,
    merge_preview_rows,
    parse_commit_result,
)
import preview_table as preview_model
from wms_client import (
    build_put_original_sales_order_payload,
    build_put_purchase_order_payload,
    build_put_sku_payload,
    format_wms_response,
    is_wms_send_success,
    send_put_original_sales_order,
    send_put_purchase_order,
    send_put_sku,
    validate_put_sku_form,
)


ui_message_queue = queue.Queue()
worker_thread = None
export_thread = None
continue_thread = None
abort_event = threading.Event()
preview_select_text = ""
preview_files = []
preview_table = None
active_tree = None
continue_query_active = False
last_combo_text = ""
progress_percent = 0
progress_color = "#16A34A"
session_log_lines = []
log_window = None
log_window_text = None
wms_thread = None
wms_send_active = False
wms_window = None
wms_window_request_text = None
wms_window_response_text = None
wms_confirm_button = None
product_thread = None
product_send_active = False
product_window = None
product_send_button = None
product_response_text = None
product_response_status = None
wms_window_response_status = None
medical_device_catalog = []
medical_device_skus = frozenset()
medical_device_catalog_thread = None
medical_device_catalog_refresh_pending = False
medical_device_catalog_refresh_lock = threading.Lock()
medical_device_catalog_refresh_active = False
medical_device_catalog_refresh_status = "尚未查询医疗器械信息"
medical_device_window = None
medical_device_tree = None
medical_device_search_var = None
medical_device_status_label = None
medical_device_refresh_button = None
medical_device_sort_column = None
medical_device_sort_stage = 0
medical_device_copy_status_after_id = None
customer_records = []
customer_query_thread = None
customer_query_pending = False
customer_query_lock = threading.Lock()
customer_query_active = False
customer_query_status = "尚未查询客商信息"
customer_window = None
customer_tree = None
customer_code_search_var = None
customer_name_search_var = None
customer_status_label = None
customer_use_button = None
customer_refresh_button = None
customer_copy_status_after_id = None

MEDICAL_DEVICE_WARNING_COLOR = "#B42318"
MEDICAL_DEVICE_ROW_TAG = "medical_device_row"
COPY_STATUS_DURATION_MS = 2000
MEDICAL_DEVICE_COLUMNS = (
    "产品编码",
    "是否序列号控制",
    "是否批次控制",
    "是否效期控制",
    "是否危险品",
    "是否球管",
)

FONT_CANDIDATES = (
    "Noto Sans CJK SC",
    "WenQuanYi Micro Hei",
    "WenQuanYi Zen Hei",
    "Source Han Sans CN",
    "黑体",
    "Microsoft YaHei UI",
)


def _resolve_cjk_font_family(root):
    """返回当前系统中第一个可用的中文字体，无命中时回退默认字体。"""
    available = set(tkfont.families(root))
    for family in FONT_CANDIDATES:
        if family in available:
            return family
    return tkfont.nametofont("TkDefaultFont", root).actual("family")


MAX_BATCH_FILES = 5
SUPPORTED_DROP_EXTENSIONS = {".png", ".jpg", ".jpeg", ".pdf"}
MANUAL_STATUS = "人工填写"
MANUAL_FILENAME = "空白单据"
_UI_STATUS_TO_MODEL = {
    "成功": preview_model.SUCCESS,
    "失败": preview_model.FAILED,
    "结果未生成": preview_model.PENDING,
    MANUAL_STATUS: preview_model.MANUAL,
}
_MODEL_STATUS_TO_UI = {
    value: key for key, value in _UI_STATUS_TO_MODEL.items()
}
RESPONSE_STATE_STYLES = {
    "neutral": {
        "text": "尚未发送",
        "background": "#F8FAFC",
        "foreground": "#475569",
        "border": "#CBD5E1",
    },
    "sending": {
        "text": "发送中...",
        "background": "#EFF6FF",
        "foreground": "#1D4ED8",
        "border": "#BFDBFE",
    },
    "success": {
        "text": "发送成功",
        "background": "#ECFDF3",
        "foreground": "#067647",
        "border": "#ABEFC6",
    },
    "failure": {
        "text": "发送失败",
        "background": "#FEF3F2",
        "foreground": "#B42318",
        "border": "#FECDCA",
    },
}
OSCAR_HEADER_DISPLAY_LABELS = {
    "供应商": "客户/供应商",
}


class EditableTreeview(ttk.Treeview):
    """渲染预览快照，并把用户操作转发给权威状态模型。"""

    def __init__(self, master, on_command=None, **kwargs):
        super().__init__(master, **kwargs)
        self._entry = None
        self._bound_item = None
        self._bound_col = None
        self._clipboard = []
        self._on_command = on_command
        self._snapshot = None
        self.bind("<Double-1>", self._start_edit)
        for sequence in ("<Control-c>", "<Command-c>"):
            self.bind(sequence, self._copy_shortcut)
        for sequence in ("<Control-v>", "<Command-v>"):
            self.bind(sequence, self._paste_shortcut)
        for sequence in ("<Control-z>", "<Command-z>"):
            self.bind(sequence, self._undo_shortcut)

    def set_snapshot(self, snapshot):
        """按只读模型快照重绘当前页签的明细树。"""
        self._snapshot = snapshot
        for row_id in self.get_children(""):
            self.delete(row_id)
        if snapshot is None:
            return

        line_by_id = {
            line.line_id: line for line in snapshot.lines
        }
        group_by_line = {}
        for group in snapshot.split_groups:
            for line_id in group.line_ids:
                group_by_line[line_id] = group

        rendered_groups = set()
        rendered_lines = set()
        export_index = 0
        for line in snapshot.lines:
            group = group_by_line.get(line.line_id)
            if group is not None:
                if group.group_id not in rendered_groups:
                    self.insert(
                        "",
                        tk.END,
                        iid=group.group_id,
                        values=group.summary_values,
                        tags=("summary_row",),
                    )
                    self.item(group.group_id, open=True)
                    for child_id in group.line_ids:
                        child = line_by_id.get(child_id)
                        if child is None:
                            continue
                        self.insert(
                            group.group_id,
                            tk.END,
                            iid=child.line_id,
                            values=child.values,
                            tags=self._row_tags(
                                child, export_index
                            ),
                        )
                        export_index += 1
                    rendered_groups.add(group.group_id)
                    rendered_lines.update(group.line_ids)
                continue
            if line.line_id in rendered_lines:
                continue
            self.insert(
                "",
                tk.END,
                iid=line.line_id,
                values=line.values,
                tags=self._row_tags(line, export_index),
            )
            export_index += 1
        self._renumber()
        self.auto_size_columns(fill_width=True)

    @staticmethod
    def _row_tags(line, export_index):
        tags = (
            "zebra_even" if export_index % 2 == 0 else "zebra_odd"
        )
        if line.medical_device:
            tags = (tags, MEDICAL_DEVICE_ROW_TAG)
        return tags

    def select_line_ids(self, line_ids):
        """选中指定实际明细行，缺失的 ID 自动忽略。"""
        selected = [
            line_id for line_id in line_ids or ()
            if self.exists(line_id)
        ]
        if not selected:
            return
        self.selection_set(*selected)
        self.see(selected[0])

    def _start_edit(self, event):
        if self.identify("region", event.x, event.y) != "cell":
            return
        row_id = self.identify_row(event.y)
        col_index = int(self.identify_column(event.x).replace("#", "")) - 1
        headers = self["columns"]
        if not row_id or col_index < 0 or col_index >= len(headers):
            return
        if self._is_summary_row(row_id):
            return
        bbox = self.bbox(row_id, self.identify_column(event.x))
        if not bbox:
            return
        self._finish_edit()
        col_id = headers[col_index]
        entry = tk.Entry(self)
        entry.insert(0, self.set(row_id, col_id))
        entry.select_range(0, tk.END)
        entry.place(x=bbox[0], y=bbox[1], width=bbox[2], height=bbox[3])
        entry.focus_set()
        self._entry = entry
        self._bound_item = row_id
        self._bound_col = col_id
        entry.bind("<Return>", self._finish_edit)
        entry.bind("<FocusOut>", self._finish_edit)
        entry.bind("<Escape>", self._cancel_edit)
        for sequence in ("<Control-z>", "<Command-z>"):
            entry.bind(sequence, self._cancel_edit)

    def _finish_edit(self, _event=None):
        if self._entry is None:
            return
        new_value = self._entry.get()
        row_id = self._bound_item
        col_id = self._bound_col
        old_value = self.set(row_id, col_id)
        self._destroy_edit()
        if new_value != old_value:
            self._dispatch(
                "update_line",
                (row_id, col_id, new_value),
            )

    def _cancel_edit(self, _event=None):
        self._destroy_edit()
        self.focus_set()
        return "break"

    def _destroy_edit(self):
        if self._entry is not None:
            self._entry.destroy()
        self._entry = None
        self._bound_item = None
        self._bound_col = None

    def _dispatch(self, command, payload=()):
        if self._on_command is None:
            return None
        return self._on_command(self, command, payload)

    def _copy_shortcut(self, _event=None):
        active_tree_copy_selected()
        return "break"

    def _paste_shortcut(self, _event=None):
        active_tree_paste_row()
        return "break"

    def _undo_shortcut(self, _event=None):
        self._dispatch("undo")
        return "break"

    def _is_summary_row(self, row_id):
        return "summary_row" in self.item(row_id, "tags")

    def _exportable_rows_in_order(self):
        ordered = []

        def visit(parent_id):
            for row_id in self.get_children(parent_id):
                if not parent_id and self._is_summary_row(row_id):
                    visit(row_id)
                else:
                    ordered.append(row_id)

        visit("")
        return ordered

    def _selected_rows_in_order(self):
        selected = set(self.selection())
        if not selected:
            return []
        return [
            row_id for row_id in self._exportable_rows_in_order()
            if row_id in selected
        ]

    def has_clipboard(self):
        return bool(self._clipboard)

    def has_copyable_selection(self):
        return bool(self._selected_rows_in_order())

    def copy_selected(self):
        selected = self._selected_rows_in_order()
        if not selected:
            self._clipboard = []
            return False
        headers = self["columns"]
        self._clipboard = [
            tuple(self.set(row_id, col) for col in headers)
            for row_id in selected
        ]
        return True

    def clear_clipboard(self):
        self._clipboard.clear()

    def _selected_anchor(self):
        selected = self._selected_rows_in_order()
        if selected:
            return selected[-1]
        return None

    def insert_row_after_selection(self):
        if not self["columns"]:
            return None
        anchor = self._selected_anchor()
        return self._dispatch("insert_line", (anchor,))

    def paste_clipboard(self):
        if not self._clipboard or not self["columns"]:
            return False
        anchor = self._selected_anchor()
        self._dispatch("paste_lines", (anchor, self._clipboard))
        return True

    def add_row(self):
        if self["columns"]:
            return self._dispatch("insert_line", (None,))
        return None

    def delete_selected(self):
        selected = self.selection()
        if not selected:
            return
        line_ids = []
        for row_id in selected:
            if self._is_summary_row(row_id):
                line_ids.extend(self.get_children(row_id))
            else:
                line_ids.append(row_id)
        if line_ids:
            self._dispatch("delete_lines", (tuple(dict.fromkeys(line_ids)),))

    def undo(self):
        result = self._dispatch("undo")
        return bool(result)

    def _renumber(self):
        for index, row_id in enumerate(self.get_children(""), 1):
            self.item(row_id, text=index)
            if self._is_summary_row(row_id):
                for child_index, child_id in enumerate(
                    self.get_children(row_id), 1
                ):
                    self.item(child_id, text=f"{index}.{child_index}")

    def auto_size_columns(self, max_width=320, min_width=90, padding=26,
                          fill_width=False):
        """按内容自动收缩列宽并居中，长内容由用户拖动列宽查看。"""
        font = tkfont.nametofont("TkDefaultFont")
        heading_font = tkfont.Font(font=PREVIEW_HEADING_FONT)
        for col in self["columns"]:
            content_w = []

            def collect_values(parent_id):
                for row_id in self.get_children(parent_id):
                    content_w.append(font.measure(self.set(row_id, col)))
                    collect_values(row_id)

            collect_values("")
            width = max([heading_font.measure(col)] + content_w) + padding
            width = min(max(min_width, width), max_width)
            self.column(col, width=width, minwidth=min_width,
                        stretch=fill_width, anchor="center")
            self.heading(col, anchor="center")

    def clear_rows(self):
        for row_id in self.get_children(""):
            self.delete(row_id)

class CopyableTreeview(ttk.Treeview):
    """只读列表，支持通过快捷键或右键菜单复制当前单元格。"""

    def __init__(self, master, on_copy_status=None, **kwargs):
        super().__init__(master, **kwargs)
        self._copied_cell = None
        self._on_copy_status = on_copy_status
        self._copy_menu = tk.Menu(self, tearoff=0)
        self._copy_menu.add_command(
            label="复制单元格", command=self._copy_remembered_cell
        )
        self.bind(
            "<ButtonPress-1>", self._remember_clicked_cell, add="+"
        )
        self.bind(
            "<Control-c>", self._copy_remembered_cell
        )
        self.bind(
            "<Command-c>", self._copy_remembered_cell
        )
        self.bind("<Button-2>", self._show_copy_menu, add="+")
        self.bind("<Button-3>", self._show_copy_menu, add="+")

    def clear_copied_cell(self):
        """清除已记录的单元格，避免复制刷新前的旧内容。"""
        self._copied_cell = None

    def _remember_clicked_cell(self, event):
        if self._remember_event_cell(event):
            self.focus_set()

    def _remember_event_cell(self, event):
        if self.identify("region", event.x, event.y) != "cell":
            self.clear_copied_cell()
            return False
        row_id = self.identify_row(event.y)
        column_token = self.identify_column(event.x)
        columns = self["columns"]
        try:
            column_index = int(column_token.replace("#", "")) - 1
        except ValueError:
            self.clear_copied_cell()
            return False
        if not row_id or column_index < 0 or column_index >= len(columns):
            self.clear_copied_cell()
            return False
        self._copied_cell = (row_id, columns[column_index])
        return True

    def _show_copy_menu(self, event):
        if not self._remember_event_cell(event):
            return "break"
        try:
            self._copy_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._copy_menu.grab_release()
        return "break"

    def _copy_remembered_cell(self, _event=None):
        if self._copied_cell is None:
            self._notify_copy_status(
                "请先点击要复制的单元格", error=True
            )
            return "break"

        row_id, column_id = self._copied_cell
        try:
            if (
                not self.exists(row_id)
                or column_id not in self["columns"]
            ):
                raise tk.TclError("单元格已刷新")
            value = self.set(row_id, column_id)
            self.clipboard_clear()
            self.clipboard_append(value)
        except tk.TclError:
            self.clear_copied_cell()
            self._notify_copy_status(
                "请先点击要复制的单元格", error=True
            )
            return "break"

        title = str(self.heading(column_id, "text"))
        for suffix in (" ↑", " ↓"):
            if title.endswith(suffix):
                title = title[:-len(suffix)]
                break
        self._notify_copy_status(
            f"已复制：{title} {value}", error=False
        )
        return "break"

    def _notify_copy_status(self, message, error=False):
        if self._on_copy_status is not None:
            self._on_copy_status(message, error)


def _append_line_to_log_window(line):
    """把一行日志追加到已打开的日志窗口，避免跨线程操作 Tkinter。"""
    if log_window is None or log_window_text is None:
        return
    try:
        if not log_window.winfo_exists():
            return
        log_window_text.config(state=tk.NORMAL)
        log_window_text.insert(tk.END, line + "\n")
        log_window_text.see(tk.END)
        log_window_text.config(state=tk.DISABLED)
    except tk.TclError:
        pass


def _refresh_log_window():
    """刷新日志窗口内容，用于打开时载入本次会话已有日志。"""
    if log_window is None or log_window_text is None:
        return
    try:
        if not log_window.winfo_exists():
            return
        log_window_text.config(state=tk.NORMAL)
        log_window_text.delete("1.0", tk.END)
        for line in session_log_lines:
            log_window_text.insert(tk.END, line + "\n")
        log_window_text.see(tk.END)
        log_window_text.config(state=tk.DISABLED)
    except tk.TclError:
        pass


def flush_log():
    """由主线程把日志队列写入会话缓冲与打开的日志窗口。"""
    while True:
        try:
            line = log_queue.get_nowait()
        except queue.Empty:
            break
        session_log_lines.append(line)
        _append_line_to_log_window(line)
    if log_window is not None and log_window_text is not None:
        try:
            log_window_text.update_idletasks()
        except tk.TclError:
            pass


def open_log_window():
    """打开或聚焦本次会话的日志窗口。"""
    global log_window, log_window_text
    flush_log()
    if log_window is not None:
        try:
            if log_window.winfo_exists():
                log_window.deiconify()
                log_window.lift()
                log_window.focus_force()
                return
        except tk.TclError:
            log_window = None
            log_window_text = None

    log_window = tk.Toplevel(win)
    log_window.title("处理日志")
    log_window.geometry("900x500")
    log_window.minsize(400, 200)

    body = tk.Frame(log_window)
    body.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

    log_window_text = tk.Text(body, state=tk.DISABLED, wrap=tk.WORD)
    log_scrollbar = ttk.Scrollbar(
        body, orient="vertical", command=log_window_text.yview
    )
    log_window_text.configure(yscrollcommand=log_scrollbar.set)
    log_window_text.grid(row=0, column=0, sticky="nsew")
    log_scrollbar.grid(row=0, column=1, sticky="ns")

    body.rowconfigure(0, weight=1)
    body.columnconfigure(0, weight=1)
    log_window.protocol("WM_DELETE_WINDOW", close_log_window)
    _refresh_log_window()


def close_log_window():
    """关闭日志窗口并允许重新打开。"""
    global log_window, log_window_text
    if log_window is not None:
        log_window.destroy()
    log_window = None
    log_window_text = None


def _wms_text_pane(parent, title):
    """创建接口发送窗口中的只读文本分栏。"""
    tk.Label(parent, text=title, font=BUTTON_FONT, anchor="w").grid(
        row=0, column=0, sticky="w", pady=(0, 4)
    )
    text = tk.Text(parent, state=tk.DISABLED, wrap=tk.NONE)
    vsb = ttk.Scrollbar(parent, orient="vertical", command=text.yview)
    hsb = ttk.Scrollbar(parent, orient="horizontal", command=text.xview)
    text.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
    text.grid(row=1, column=0, sticky="nsew")
    vsb.grid(row=1, column=1, sticky="ns")
    hsb.grid(row=2, column=0, sticky="ew")
    parent.rowconfigure(1, weight=1)
    parent.columnconfigure(0, weight=1)
    return text


def _set_response_state(text_widget, status_label, state):
    """同步更新接口返回区的状态条和文本边框颜色。"""
    style = RESPONSE_STATE_STYLES.get(state, RESPONSE_STATE_STYLES["neutral"])
    if status_label is not None:
        status_label.config(
            text=style["text"],
            background=style["background"],
            foreground=style["foreground"],
        )
    if text_widget is not None:
        text_widget.config(
            highlightbackground=style["border"],
            highlightcolor=style["border"],
        )


def _wms_response_pane(parent, title):
    """创建带全宽状态条和状态边框的只读接口返回区。"""
    status_label = tk.Label(
        parent, anchor="w", font=BUTTON_FONT, padx=10, pady=5
    )
    status_label.grid(row=0, column=0, sticky="ew", pady=(0, 4))
    tk.Label(parent, text=title, font=BUTTON_FONT, anchor="w").grid(
        row=1, column=0, sticky="w", pady=(0, 4)
    )
    text = tk.Text(
        parent, state=tk.DISABLED, wrap=tk.NONE, highlightthickness=2
    )
    vsb = ttk.Scrollbar(parent, orient="vertical", command=text.yview)
    hsb = ttk.Scrollbar(parent, orient="horizontal", command=text.xview)
    text.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
    text.grid(row=2, column=0, sticky="nsew")
    vsb.grid(row=2, column=1, sticky="ns")
    hsb.grid(row=3, column=0, sticky="ew")
    parent.rowconfigure(2, weight=1)
    parent.columnconfigure(0, weight=1)
    _set_response_state(text, status_label, "neutral")
    return text, status_label


def _replace_wms_response(token, text, state="neutral"):
    """用最新接口回告覆盖本次发送对应的二级窗口返回区。"""
    if wms_window_response_text is None or id(wms_window_response_text) != token:
        return
    try:
        if not wms_window_response_text.winfo_exists():
            return
        wms_window_response_text.config(state=tk.NORMAL)
        wms_window_response_text.delete("1.0", tk.END)
        wms_window_response_text.insert(tk.END, text)
        wms_window_response_text.yview_moveto(0)
        wms_window_response_text.config(state=tk.DISABLED)
        _set_response_state(
            wms_window_response_text, wms_window_response_status, state
        )
    except tk.TclError:
        pass


def _replace_product_response(token, text, state="neutral"):
    """用最新产品接口回告覆盖新增产品窗口返回区。"""
    if product_response_text is None or id(product_response_text) != token:
        return
    try:
        if not product_response_text.winfo_exists():
            return
        product_response_text.config(state=tk.NORMAL)
        product_response_text.delete("1.0", tk.END)
        product_response_text.insert(tk.END, text)
        product_response_text.yview_moveto(0)
        product_response_text.config(state=tk.DISABLED)
        _set_response_state(
            product_response_text, product_response_status, state
        )
    except tk.TclError:
        pass


def poll_log_queue():
    """周期刷新日志队列，保证日志窗口随时显示最新内容。"""
    flush_log()
    win.after(200, poll_log_queue)


# ---------------- 主流程函数 ----------------
def run_task():
    """按钮入口：弹出文件选择框后启动真实或模拟批量处理。"""
    select_text = combo_model.get().strip()
    mock_mode = mock_var.get()
    files = ()
    if not mock_mode:
        files = filedialog.askopenfilenames(
            title="选择要处理的文件",
            filetypes=[
                ("全部支持文件", "*.png;*.jpg;*.jpeg;*.pdf"),
                ("图片文件", "*.png;*.jpg;*.jpeg"),
                ("PDF 文件", "*.pdf"),
                ("PNG 文件", "*.png"),
                ("JPG 文件", "*.jpg;*.jpeg"),
                ("所有文件", "*.*")
            ]
        )
        if not files:
            return
    _launch_batch(files, select_text, mock_mode)


def _launch_batch(files, select_text, mock_mode):
    """按已选文件启动真实或模拟批量处理。"""
    if continue_query_active:
        messagebox.showwarning(
            "温馨提示",
            "正在继续查询原任务，请等待完成后再次选择文件"
        )
        return
    if not select_text or select_text not in MODEL_MAP:
        messagebox.showwarning("温馨提示", "请先选择单据规则！")
        return

    if not mock_mode and len(files) > MAX_BATCH_FILES:
        messagebox.showwarning(
            "温馨提示",
            f"每次最多选择 {MAX_BATCH_FILES} 个文件，请重新选择。"
        )
        return

    clear_preview()
    abort_event.clear()
    abort_btn.config(state=tk.NORMAL)
    btn.config(text="正在处理...", state=tk.DISABLED)
    mock_check.config(state=tk.DISABLED)
    set_progress_state(50, "处理进度：已开始（50%）")
    win.update()
    current_model_id = MODEL_MAP[select_text]

    global worker_thread
    worker_thread = threading.Thread(
        target=process_batch_worker,
        args=(files, select_text, current_model_id, mock_mode),
        daemon=True
    )
    worker_thread.start()
    win.after(100, poll_ui_queue)


def _parse_dropped_files(event):
    """把 TkDND 返回的原始 Tcl 列表解析为文件路径列表。"""
    return list(win.tk.splitlist(event.data))


def _validate_drop_files(paths):
    """校验拖入文件类型和数量，合法时返回 (文件列表, 空错误)。"""
    if not paths:
        return None, "未识别到可导入的文件。"
    invalid = [
        path for path in paths
        if os.path.splitext(path)[1].lower() not in SUPPORTED_DROP_EXTENSIONS
    ]
    if invalid:
        return None, "仅支持拖入 PNG/JPG/JPEG/PDF 文件。"
    if len(paths) > MAX_BATCH_FILES:
        return None, f"每次最多选择 {MAX_BATCH_FILES} 个文件，请重新选择。"
    return paths, ""


def on_file_drop(event):
    """接收拖入文件并按按钮一致逻辑启动批量处理。"""
    if _background_task_active() or continue_query_active:
        messagebox.showwarning("温馨提示", "请等待当前任务完成后再拖入文件")
        return
    files, error = _validate_drop_files(_parse_dropped_files(event))
    if error:
        messagebox.showwarning("温馨提示", error)
        return
    _launch_batch(files, combo_model.get().strip(), mock_var.get())


def abort_processing():
    """请求中止当前 OCR 处理批次或继续查询。"""
    abort_event.set()
    abort_btn.config(state=tk.DISABLED)
    if continue_query_active:
        print_log("收到中止请求，正在停止继续查询")
    else:
        print_log("收到中止请求，正在停止当前批次")
    set_progress_state(50, "处理进度：正在中止...", "#D97706")


def finish_abort_state():
    """恢复中止后的初始界面状态。"""
    abort_btn.config(state=tk.DISABLED)
    btn.config(text="选择文件并开始处理", state=tk.NORMAL)
    mock_check.config(state=tk.NORMAL)
    set_progress_state(0, "处理进度：已中止", "#D97706")


def process_batch_worker(files, select_text, current_model_id, mock_mode):
    """后台线程入口，统一捕获批量处理异常。"""
    try:
        if mock_mode:
            if abort_event.is_set():
                ui_message_queue.put(("processing_aborted",))
                return
            process_mock_batch(select_text)
        elif not process_batch(files, select_text, current_model_id):
            print_log("批次已由用户中止，正在恢复界面")
            ui_message_queue.put(("processing_aborted",))
            return
        if abort_event.is_set():
            print_log("批次已由用户中止，正在恢复界面")
            ui_message_queue.put(("processing_aborted",))
    except Exception as e:
        print_log(f"处理流程异常: {str(e)}")
        ui_message_queue.put(("processing_error", f"处理流程异常: {str(e)}"))


def _send_feishu_statistics(select_text):
    """后台按配置次数发送单个成功文件的飞书统计，失败只记录日志。"""
    print_log("开始同步统计数据至飞书多维表格...")
    token = get_tenant_access_token()
    if not token:
        print_log("无有效Token，跳过写入飞书多维表格")
        return
    send_to_bitable_repeated(token, select_text, FEISHU_CALL_TIMES)


def process_batch(files, select_text, current_model_id):
    """逐文件执行 OCR 处理，按文件组织预览结果并通过队列回传 UI。"""
    total_files = len(files)
    file_results = []
    core_data = []
    success_count = 0
    fail_count = 0
    pending_count = 0
    print_log(f"===== 批量处理，共{total_files}个文件，模版：{select_text} =====")

    for done, file_path in enumerate(files, 1):
        if abort_event.is_set():
            print_log("已收到中止请求，停止处理新文件")
            return False
        filename = os.path.basename(file_path)
        status = "失败"
        res_msg = ""
        file_id = ""
        file_url = ""
        req_uuid = ""
        parsed_rows = []
        split_groups = []
        ocr_result_dict = None

        try:
            file_id, file_url = upload_file_to_server(file_path)
            if abort_event.is_set():
                raise OCRAborted()
            # 传入当前选中的单据规则名称，用于内部判断sysCode
            req_uuid, _ = call_process_api(file_url, filename, file_id, current_model_id, select_text)
            if abort_event.is_set():
                raise OCRAborted()
            _, ocr_result_dict = call_get_result_api(req_uuid, abort_event)
            if abort_event.is_set():
                raise OCRAborted()

            if ocr_result_dict and ocr_result_dict.get("status") is True:
                commit_result = ocr_result_dict.get("data", {}).get("commitResult", {})
                parsed_rows, split_groups = parse_commit_result(
                    select_text, commit_result, filename
                )
                core_data.extend(parsed_rows)
                if select_text == "GE-发票单":
                    print_log(f"{filename} 处理完成后总明细行数:{len(core_data)}")

                status = "成功"
                res_msg = "处理成功"
                success_count += 1
                print_log(f"✅ [{filename}] 处理成功")
                if not abort_event.is_set():
                    threading.Thread(
                        target=_send_feishu_statistics,
                        args=(select_text,),
                        daemon=True,
                    ).start()

            else:
                raise Exception("OCR返回识别状态异常")

        except OCRResultTimeout:
            status = "结果未生成"
            res_msg = "识别5分钟未生成结果，可稍后点击“继续查询原任务”"
            pending_count += 1
            print_log(f"⏳ [{filename}] 5分钟内未生成识别结果，等待后续继续查询")
        except OCRAborted:
            print_log("批次已由用户中止")
            return False
        except Exception as e:
            status = "失败"
            res_msg = str(e)
            fail_count += 1
            print_log(f"❌ [{filename}] 处理失败：{e}")

        file_results.append({
            "filename": filename,
            "status": status,
            "message": res_msg,
            "rows": parsed_rows,
            "split_groups": split_groups,
            "req_uuid": req_uuid,
            "log_row": [filename, file_id, file_url, req_uuid, "", status, res_msg, ""],
        })
        ui_message_queue.put(("progress", done, total_files))

    print_log(f"\n===== 批量处理结束 =====")
    print_log(f"总文件：{total_files} | 成功：{success_count} | 失败：{fail_count} | "
              f"结果未生成：{pending_count} | 有效明细行数：{len(core_data)}")
    if abort_event.is_set():
        print_log("批次已由用户中止，不进入预览")
        return False

    ui_message_queue.put(("preview", select_text,
                          get_core_headers(select_text), file_results,
                          success_count, fail_count))
    return True


def process_mock_batch(select_text):
    """生成两个演示文件页签并直接进入预览流程。"""
    print_log(f"===== 模拟数据模式，模板：{select_text} =====")
    ui_message_queue.put(("progress", 1, 2))
    headers, file_results = generate_mock_data(select_text)
    for file_result in file_results:
        file_result["log_row"] = [
            file_result["filename"], "", "", "", "",
            file_result["status"], file_result["message"], ""
        ]
    success_count = sum(item["status"] == "成功" for item in file_results)
    fail_count = len(file_results) - success_count
    total_rows = sum(len(item["rows"]) for item in file_results)
    print_log(f"生成模拟页签数: {len(file_results)}，明细总行数: {total_rows}")
    ui_message_queue.put(("progress", 2, 2))
    ui_message_queue.put(("preview", select_text, headers,
                          file_results, success_count, fail_count))


# ---------------- 预览与导出交互 ----------------
def _short_tab_label(filename, max_len=22):
    """生成长文件名页签使用的短标签。"""
    name = os.path.basename(filename)
    if len(name) <= max_len:
        return name
    return name[:max_len - 1] + "…"


def _model_status(status_text):
    """把旧文件结果中的中文状态转换为权威模型状态。"""
    try:
        return _UI_STATUS_TO_MODEL[status_text]
    except KeyError as exc:
        raise ValueError(f"未知预览状态: {status_text}") from exc


def _document_inputs(raw_file_results):
    """把后台文件结果转换为模型输入，所有业务字段立即脱敏为只读值。"""
    inputs = []
    for index, file_result in enumerate(raw_file_results, start=1):
        inputs.append(preview_model.DocumentInput(
            metadata=preview_model.DocumentMetadata(
                document_id=f"document-{index}",
                filename=file_result.get("filename") or f"document-{index}",
                status=_model_status(file_result.get("status", "")),
                message=file_result.get("message", ""),
                req_uuid=file_result.get("req_uuid", ""),
                log_row=tuple(file_result.get("log_row") or ()),
                manual=bool(file_result.get("manual")),
            ),
            header_values=dict(file_result.get("header_values") or {}),
            rows=tuple(
                tuple(row) for row in (file_result.get("rows") or ())
            ),
            split_groups=tuple(file_result.get("split_groups") or ()),
        ))
    return tuple(inputs)


def _replace_preview_table(select_text, headers, raw_file_results):
    """创建当前会话唯一的权威预览表格。"""
    global preview_table
    header_fields, detail_fields = get_preview_layout(select_text)
    preview_table = preview_model.PreviewTable(
        select_text,
        headers,
        header_fields,
        detail_fields,
        _document_inputs(raw_file_results),
        catalog_skus=medical_device_skus,
    )
    return preview_table


def _new_preview_file_info(snapshot):
    """创建仅保存 Tk 控件引用与展示缓存的页签包装。"""
    return {
        "document_id": snapshot.document_id,
        "filename": snapshot.metadata.filename,
        "tab": None,
        "tree": None,
        "status_label": None,
        "medical_warning_label": None,
        "consignee_label": None,
        "consignee_entry": None,
        "consignee_value_var": None,
    }


def _preview_file_info(document_id):
    """按模型单据 ID 查找页签包装。"""
    for info in preview_files:
        if info.get("document_id") == document_id:
            return info
    return None


def _preview_file_info_for_tree(tree):
    """按 Tk Treeview 查找对应页签包装。"""
    for info in preview_files:
        if info.get("tree") is tree:
            return info
    return None


def _active_preview_document_id():
    """返回当前选中的预览单据 ID。"""
    info = _active_preview_file()
    return info.get("document_id", "") if info is not None else ""


def _snapshot_for_info(info):
    """返回页签包装对应的模型快照。"""
    if preview_table is None or info is None:
        return None
    return preview_table.snapshot(info["document_id"])


def _active_snapshot():
    """返回当前选中页签的模型快照。"""
    return _snapshot_for_info(_active_preview_file())


def _status_text(snapshot):
    """生成与旧界面一致的状态文案。"""
    status = _MODEL_STATUS_TO_UI[snapshot.metadata.status]
    text = f"状态：{status}"
    if not snapshot.lines:
        text += "；当前无明细数据"
    if snapshot.metadata.message:
        text += f"；{snapshot.metadata.message}"
    return text


def _status_color(snapshot):
    """返回状态文案对应的前景色。"""
    if snapshot.metadata.status == preview_model.PENDING:
        return "#D97706"
    if snapshot.metadata.status == preview_model.FAILED:
        return "#B42318"
    return "#111827"


def _render_file_status_label(file_result, snapshot):
    """按权威快照刷新页签顶部状态文案。"""
    status_label = file_result.get("status_label")
    if status_label is None:
        return
    try:
        if status_label.winfo_exists():
            status_label.config(
                text=_status_text(snapshot),
                fg=_status_color(snapshot),
            )
    except tk.TclError:
        pass


def _render_preview_snapshot(file_result, snapshot):
    """把模型快照同步到当前页签的控件。"""
    tree = file_result.get("tree")
    if tree is not None:
        tree.set_snapshot(snapshot)
    _render_file_status_label(file_result, snapshot)
    _refresh_file_medical_device_display(
        file_result,
        snapshot,
        preview_select_text,
    )


def _render_preview_document(document_id):
    """刷新指定单据页签。"""
    info = _preview_file_info(document_id)
    snapshot = _snapshot_for_info(info)
    if info is None or snapshot is None:
        return
    _render_preview_snapshot(info, snapshot)


def _render_all_preview_files():
    """刷新全部页签的模型快照。"""
    for info in preview_files:
        _render_preview_document(info["document_id"])


def _handle_preview_tree_command(tree, command, payload):
    """把 Tk 明细表格的手势转发给权威模型并重绘结果。"""
    info = _preview_file_info_for_tree(tree)
    if info is None or preview_table is None:
        return None
    document_id = info["document_id"]
    try:
        if command == "update_line":
            line_id, field, value = payload
            result = preview_table.update_line(
                document_id, line_id, field, value
            )
        elif command == "insert_line":
            result = preview_table.insert_line(document_id, payload[0])
        elif command == "paste_lines":
            result = preview_table.paste_lines(
                document_id, payload[0], payload[1]
            )
        elif command == "delete_lines":
            result = preview_table.delete_lines(document_id, payload[0])
        elif command == "undo":
            result = preview_table.undo(document_id)
        else:
            raise ValueError(f"未知预览表格命令: {command}")
    except ValueError as exc:
        print_log(f"预览表格操作失败：{exc}")
        return None

    _render_preview_snapshot(info, result.snapshot)
    tree.select_line_ids(result.selection_hint)
    refresh_export_state()
    return result


def _refresh_file_medical_device_display(file_result, snapshot, select_text):
    """按权威快照刷新医疗器械提示和客商编码默认值。"""
    warning_label = file_result.get("medical_warning_label")
    if warning_label is None:
        return
    try:
        if not warning_label.winfo_exists():
            return
    except tk.TclError:
        return

    has_medical_device = snapshot.medical_device_present
    if has_medical_device:
        warning_label.config(text=MEDICAL_DEVICE_WARNING)
        if not warning_label.winfo_manager():
            warning_label.place(relx=0.5, rely=0.5, anchor="center")
    else:
        warning_label.place_forget()

    consignee_entry = file_result.get("consignee_entry")
    consignee_label = file_result.get("consignee_label")
    consignee_value_var = file_result.get("consignee_value_var")
    if (
        consignee_entry is None
        or consignee_label is None
        or consignee_value_var is None
    ):
        return
    try:
        if (
            not consignee_entry.winfo_exists()
            or not consignee_label.winfo_exists()
        ):
            return
    except tk.TclError:
        return

    if has_medical_device:
        header_value = snapshot.header_values.get("客商编码", "")
        consignee_label.config(
            font=BODY_FONT_BOLD, fg=MEDICAL_DEVICE_WARNING_COLOR
        )
        consignee_entry.config(state=tk.DISABLED)
    else:
        header_value = snapshot.header_values.get("客商编码", "")
        consignee_label.config(font=BODY_FONT, fg="#6B7280")
        consignee_entry.config(state=tk.DISABLED)
    consignee_value_var.set(header_value)
    _refresh_customer_backfill_state()


def _render_medical_device_window_status(text, error=False):
    if medical_device_status_label is None:
        return
    try:
        if medical_device_status_label.winfo_exists():
            medical_device_status_label.config(
                text=text,
                fg="#B42318" if error else "#475569",
            )
    except tk.TclError:
        pass


def _cancel_medical_device_copy_status_timer():
    global medical_device_copy_status_after_id
    if medical_device_copy_status_after_id is None:
        return
    try:
        win.after_cancel(medical_device_copy_status_after_id)
    except (tk.TclError, ValueError):
        pass
    medical_device_copy_status_after_id = None


def _restore_medical_device_copy_status():
    global medical_device_copy_status_after_id
    medical_device_copy_status_after_id = None
    _render_medical_device_window_status(
        medical_device_catalog_refresh_status
    )


def _show_medical_device_copy_status(message, error=False):
    global medical_device_copy_status_after_id
    _cancel_medical_device_copy_status_timer()
    if medical_device_status_label is None:
        return
    try:
        if not medical_device_status_label.winfo_exists():
            return
        medical_device_status_label.config(
            text=message,
            fg="#B42318" if error else "#067647",
        )
    except tk.TclError:
        return
    medical_device_copy_status_after_id = win.after(
        COPY_STATUS_DURATION_MS,
        _restore_medical_device_copy_status,
    )


def _set_medical_device_refresh_state(active, status):
    """同步医疗器械窗口的查询状态和重新查询按钮。"""
    global medical_device_catalog_refresh_active
    global medical_device_catalog_refresh_status
    _cancel_medical_device_copy_status_timer()
    medical_device_catalog_refresh_active = active
    medical_device_catalog_refresh_status = status
    if medical_device_refresh_button is not None:
        try:
            if medical_device_refresh_button.winfo_exists():
                medical_device_refresh_button.config(
                    state=tk.DISABLED if active else tk.NORMAL,
                    text="查询中..." if active else "重新查询",
                )
        except tk.TclError:
            pass
    if medical_device_status_label is not None:
        try:
            if medical_device_status_label.winfo_exists():
                medical_device_status_label.config(
                    text=status, fg="#475569"
                )
        except tk.TclError:
            pass


def _refresh_medical_device_window():
    """按当前搜索和排序状态刷新医疗器械列表。"""
    if medical_device_tree is None:
        return
    try:
        if not medical_device_tree.winfo_exists():
            return
    except tk.TclError:
        return

    rows = medical_device_catalog_display_rows(medical_device_catalog)
    search_text = (
        medical_device_search_var.get()
        if medical_device_search_var is not None else ""
    )
    rows = filter_medical_device_catalog_rows(rows, search_text)
    if medical_device_sort_column is not None:
        if medical_device_sort_stage == 1:
            rows = sort_medical_device_catalog_rows(
                rows, medical_device_sort_column
            )
        elif medical_device_sort_stage == 2:
            rows = sort_medical_device_catalog_rows(
                rows, medical_device_sort_column, descending=True
            )

    medical_device_tree.clear_copied_cell()
    medical_device_tree.delete(*medical_device_tree.get_children())
    for row in rows:
        medical_device_tree.insert("", tk.END, values=row)

    column_ids = medical_device_tree["columns"]
    for index, title in enumerate(MEDICAL_DEVICE_COLUMNS):
        heading = title
        if index == medical_device_sort_column:
            heading += " ↑" if medical_device_sort_stage == 1 else " ↓"
        medical_device_tree.heading(column_ids[index], text=heading)


def _on_medical_device_search_changed(*_args):
    """SKU 搜索框变化时立即过滤列表。"""
    _refresh_medical_device_window()


def _on_medical_device_heading_clicked(column_index):
    """按升序、降序、原始顺序循环切换指定列的排序。"""
    global medical_device_sort_column, medical_device_sort_stage
    if medical_device_sort_column != column_index:
        medical_device_sort_column = column_index
        medical_device_sort_stage = 1
    else:
        medical_device_sort_stage += 1
        if medical_device_sort_stage > 2:
            medical_device_sort_column = None
            medical_device_sort_stage = 0
    _refresh_medical_device_window()


def close_medical_device_window():
    """关闭医疗器械窗口并允许重新打开。"""
    global medical_device_window, medical_device_tree
    global medical_device_search_var, medical_device_status_label
    global medical_device_refresh_button, medical_device_sort_column
    global medical_device_sort_stage
    _cancel_medical_device_copy_status_timer()
    if medical_device_window is not None:
        try:
            medical_device_window.destroy()
        except tk.TclError:
            pass
    medical_device_window = None
    medical_device_tree = None
    medical_device_search_var = None
    medical_device_status_label = None
    medical_device_refresh_button = None
    medical_device_sort_column = None
    medical_device_sort_stage = 0


def open_medical_device_window():
    """打开或聚焦非模态医疗器械目录窗口。"""
    global medical_device_window, medical_device_tree
    global medical_device_search_var, medical_device_status_label
    global medical_device_refresh_button
    if medical_device_window is not None:
        try:
            if medical_device_window.winfo_exists():
                medical_device_window.deiconify()
                medical_device_window.lift()
                medical_device_window.focus_force()
                return
        except tk.TclError:
            medical_device_window = None
            medical_device_tree = None

    width, height = 1000, 620
    win.update_idletasks()
    parent_x = win.winfo_rootx()
    parent_y = win.winfo_rooty()
    parent_width = win.winfo_width()
    parent_height = win.winfo_height()
    x = parent_x + max((parent_width - width) // 2, 0)
    y = parent_y + max((parent_height - height) // 2, 0)

    medical_device_window = tk.Toplevel(win)
    medical_device_window.title("查询医疗器械")
    medical_device_window.geometry(f"{width}x{height}+{x}+{y}")
    medical_device_window.minsize(760, 420)
    medical_device_window.transient(win)
    medical_device_window.protocol(
        "WM_DELETE_WINDOW", close_medical_device_window
    )

    body = tk.Frame(medical_device_window)
    body.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

    search_frame = tk.Frame(body)
    search_frame.pack(fill=tk.X, pady=(0, 8))
    tk.Label(
        search_frame, text="SKU 搜索", font=BODY_FONT
    ).pack(side=tk.LEFT, padx=(0, 8))
    medical_device_search_var = tk.StringVar()
    search_entry = tk.Entry(
        search_frame, textvariable=medical_device_search_var,
        font=BODY_FONT,
    )
    search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
    medical_device_search_var.trace_add(
        "write", _on_medical_device_search_changed
    )

    footer = tk.Frame(body)
    footer.pack(side=tk.BOTTOM, fill=tk.X, pady=(8, 0))
    medical_device_status_label = tk.Label(
        footer,
        text=medical_device_catalog_refresh_status,
        font=BODY_FONT,
        anchor="w",
        fg="#475569",
    )
    medical_device_status_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
    tk.Button(
        footer, text="关闭", command=close_medical_device_window,
        padx=15, font=BUTTON_FONT,
        disabledforeground=DISABLED_FOREGROUND,
    ).pack(side=tk.RIGHT)
    tk.Button(
        footer, text="新增产品", command=open_add_product_window,
        padx=15, bg="#0E7490", fg="#111827", font=BUTTON_FONT,
        activebackground="#155E75", activeforeground="#111827",
        disabledforeground=DISABLED_FOREGROUND,
    ).pack(side=tk.RIGHT, padx=(0, 15))
    medical_device_refresh_button = tk.Button(
        footer, text="重新查询",
        command=lambda: _start_medical_device_catalog_refresh("手动查询"),
        padx=15, font=BUTTON_FONT,
        disabledforeground=DISABLED_FOREGROUND,
    )
    medical_device_refresh_button.pack(side=tk.RIGHT, padx=(0, 15))

    table_frame = tk.Frame(body)
    table_frame.pack(fill=tk.BOTH, expand=True)
    column_ids = tuple(
        f"medical_device_column_{index}"
        for index in range(len(MEDICAL_DEVICE_COLUMNS))
    )
    medical_device_tree = CopyableTreeview(
        table_frame,
        columns=column_ids,
        show="headings",
        selectmode="browse",
        style="Preview.Treeview",
        on_copy_status=_show_medical_device_copy_status,
    )
    vertical_scrollbar = ttk.Scrollbar(
        table_frame, orient="vertical", command=medical_device_tree.yview
    )
    horizontal_scrollbar = ttk.Scrollbar(
        table_frame, orient="horizontal", command=medical_device_tree.xview
    )
    medical_device_tree.configure(
        yscrollcommand=vertical_scrollbar.set,
        xscrollcommand=horizontal_scrollbar.set,
    )
    medical_device_tree.grid(row=0, column=0, sticky="nsew")
    vertical_scrollbar.grid(row=0, column=1, sticky="ns")
    horizontal_scrollbar.grid(row=1, column=0, sticky="ew")
    table_frame.rowconfigure(0, weight=1)
    table_frame.columnconfigure(0, weight=1)

    for index, title in enumerate(MEDICAL_DEVICE_COLUMNS):
        width = 170 if index == 0 else 130
        medical_device_tree.heading(
            column_ids[index],
            text=title,
            anchor="center",
            command=lambda column_index=index:
                _on_medical_device_heading_clicked(column_index),
        )
        medical_device_tree.column(
            column_ids[index],
            width=width,
            minwidth=110,
            stretch=True,
            anchor="center",
        )

    _set_medical_device_refresh_state(
        medical_device_catalog_refresh_active,
        medical_device_catalog_refresh_status,
    )
    _refresh_medical_device_window()
    search_entry.focus_set()


def _apply_medical_device_catalog(catalog):
    """更新内存 catalog、派生 SKU 集合并回刷相关界面。"""
    global medical_device_catalog, medical_device_skus
    medical_device_catalog = [dict(record) for record in catalog]
    medical_device_skus = frozenset(
        medical_device_catalog_skus(medical_device_catalog)
    )
    _refresh_medical_device_window()
    if preview_table is None or not preview_files or not preview_select_text:
        return
    preview_table.refresh_catalog(medical_device_skus)
    _render_all_preview_files()


def _medical_device_catalog_refresh_worker(reason):
    """后台查询医疗器械目录，成功覆盖缓存，失败时回传上次缓存。"""
    print_log(f"正在刷新医疗器械目录：{reason}")
    with medical_device_catalog_refresh_lock:
        catalog, source, error = refresh_or_load_medical_device_catalog()
    if source == "network":
        print_log(f"医疗器械目录已更新：{len(catalog)} 条")
        error_text = ""
    elif error is not None:
        print_log(f"医疗器械目录查询失败，使用{source}数据：{error}")
        error_text = str(error)
    else:
        error_text = ""
    ui_message_queue.put(
        ("medical_device_catalog", catalog, source, error_text)
    )


def _start_medical_device_catalog_refresh(reason):
    """启动不阻塞 OCR 的医疗器械目录后台刷新。"""
    global medical_device_catalog_thread
    global medical_device_catalog_refresh_pending
    if (
        medical_device_catalog_thread is not None
        and medical_device_catalog_thread.is_alive()
    ):
        medical_device_catalog_refresh_pending = True
    else:
        medical_device_catalog_refresh_pending = False
        medical_device_catalog_thread = threading.Thread(
            target=_medical_device_catalog_refresh_worker,
            args=(reason,),
            daemon=True,
        )
        medical_device_catalog_thread.start()
    _set_medical_device_refresh_state(
        True, "正在查询医疗器械信息..."
    )
    win.after(100, poll_ui_queue)


def _render_customer_window_status(text, error=False):
    if customer_status_label is None:
        return
    try:
        if customer_status_label.winfo_exists():
            customer_status_label.config(
                text=text,
                fg="#B42318" if error else "#475569",
            )
    except tk.TclError:
        pass


def _cancel_customer_copy_status_timer():
    global customer_copy_status_after_id
    if customer_copy_status_after_id is None:
        return
    try:
        win.after_cancel(customer_copy_status_after_id)
    except (tk.TclError, ValueError):
        pass
    customer_copy_status_after_id = None


def _restore_customer_copy_status():
    global customer_copy_status_after_id
    customer_copy_status_after_id = None
    _render_customer_window_status(customer_query_status)


def _show_customer_copy_status(message, error=False):
    global customer_copy_status_after_id
    _cancel_customer_copy_status_timer()
    if customer_status_label is None:
        return
    try:
        if not customer_status_label.winfo_exists():
            return
        customer_status_label.config(
            text=message,
            fg="#B42318" if error else "#067647",
        )
    except tk.TclError:
        return
    customer_copy_status_after_id = win.after(
        COPY_STATUS_DURATION_MS,
        _restore_customer_copy_status,
    )


def _set_customer_window_status(text, error=False):
    """更新客商窗口状态栏，不弹模态错误框。"""
    _cancel_customer_copy_status_timer()
    _render_customer_window_status(text, error)


def _customer_backfill_error():
    """返回当前页签不允许回填客商编码的原因。"""
    if preview_select_text not in (
        "GE-ORACLE拣货单", "GE-OSCAR拣货单"
    ):
        return "当前单据模板不支持回填客商编码"
    info = _active_preview_file()
    if info is None:
        return "请先选择 ORACLE 或 OSCAR 拣货单页签"
    snapshot = _active_snapshot()
    if snapshot is None or not snapshot.consignee_backfill_allowed:
        return "当前页签未命中医疗器械，不能回填客商编码"
    return ""


def _selected_customer_code():
    """返回客商列表当前选中行的客商编码。"""
    if customer_tree is None:
        return ""
    try:
        if not customer_tree.winfo_exists():
            return ""
        selection = customer_tree.selection()
    except tk.TclError:
        return ""
    if not selection:
        return ""
    values = customer_tree.item(selection[0], "values")
    return str(values[0]).strip() if values else ""


def _refresh_customer_backfill_state():
    """按当前页签与选中行刷新「使用选中客商」按钮。"""
    if customer_use_button is None:
        return
    try:
        if not customer_use_button.winfo_exists():
            return
        enabled = (
            bool(_selected_customer_code())
            and not _customer_backfill_error()
        )
        customer_use_button.config(
            state=tk.NORMAL if enabled else tk.DISABLED
        )
    except tk.TclError:
        pass


def _refresh_customer_window():
    """按两个搜索框的当前值刷新客商列表。"""
    if customer_tree is None:
        return
    try:
        if not customer_tree.winfo_exists():
            return
    except tk.TclError:
        return

    rows = customer_record_display_rows(customer_records)
    customer_code = (
        customer_code_search_var.get()
        if customer_code_search_var is not None else ""
    )
    customer_name = (
        customer_name_search_var.get()
        if customer_name_search_var is not None else ""
    )
    rows = filter_customer_record_display_rows(
        rows, customer_code, customer_name
    )

    customer_tree.clear_copied_cell()
    customer_tree.delete(*customer_tree.get_children())
    for row in rows:
        customer_tree.insert("", tk.END, values=row)
    _refresh_customer_backfill_state()


def _on_customer_search_changed(*_args):
    """客商编码或名称发生变化时立即本地过滤。"""
    _refresh_customer_window()


def _on_customer_selection_changed(_event=None):
    """刷新当前选中客商是否可回填。"""
    _refresh_customer_backfill_state()


def _use_selected_customer():
    """把选中客商编码回填到执行操作时的当前预览页签。"""
    error = _customer_backfill_error()
    if error:
        _set_customer_window_status(error, error=True)
        return
    customer_id = _selected_customer_code()
    if not customer_id:
        _set_customer_window_status("请先选择一条客商记录", error=True)
        return
    info = _active_preview_file()
    if info is None:
        _set_customer_window_status(
            "请先选择 ORACLE 或 OSCAR 拣货单页签", error=True
        )
        return

    try:
        preview_table.backfill_consignee(
            info["document_id"], customer_id
        )
    except ValueError as exc:
        _set_customer_window_status(str(exc), error=True)
        return
    _render_preview_document(info["document_id"])
    close_customer_window()


def _on_customer_row_double_click(event):
    """双击客商行时按当前页签校验后回填。"""
    if customer_tree is None:
        return
    row_id = customer_tree.identify_row(event.y)
    if not row_id:
        return
    customer_tree.selection_set(row_id)
    customer_tree.focus(row_id)
    _use_selected_customer()


def close_customer_window():
    """关闭客商窗口并允许下次打开时重新查询。"""
    global customer_window, customer_tree, customer_code_search_var
    global customer_name_search_var, customer_status_label
    global customer_use_button, customer_refresh_button
    _cancel_customer_copy_status_timer()
    if customer_window is not None:
        try:
            customer_window.destroy()
        except tk.TclError:
            pass
    customer_window = None
    customer_tree = None
    customer_code_search_var = None
    customer_name_search_var = None
    customer_status_label = None
    customer_use_button = None
    customer_refresh_button = None


def open_customer_window():
    """打开或聚焦非模态客商查询窗口。"""
    global customer_window, customer_tree, customer_code_search_var
    global customer_name_search_var, customer_status_label
    global customer_use_button, customer_refresh_button
    if customer_window is not None:
        try:
            if customer_window.winfo_exists():
                customer_window.deiconify()
                customer_window.lift()
                customer_window.focus_force()
                return
        except tk.TclError:
            customer_window = None
            customer_tree = None

    width, height = 1050, 620
    win.update_idletasks()
    parent_x = win.winfo_rootx()
    parent_y = win.winfo_rooty()
    parent_width = win.winfo_width()
    parent_height = win.winfo_height()
    x = parent_x + max((parent_width - width) // 2, 0)
    y = parent_y + max((parent_height - height) // 2, 0)

    customer_window = tk.Toplevel(win)
    customer_window.title("查询客商")
    customer_window.geometry(f"{width}x{height}+{x}+{y}")
    customer_window.minsize(760, 420)
    customer_window.transient(win)
    customer_window.protocol("WM_DELETE_WINDOW", close_customer_window)

    body = tk.Frame(customer_window)
    body.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

    search_frame = tk.Frame(body)
    search_frame.pack(fill=tk.X, pady=(0, 8))
    tk.Label(
        search_frame, text="客商编码", font=BODY_FONT
    ).pack(side=tk.LEFT, padx=(0, 8))
    customer_code_search_var = tk.StringVar()
    code_entry = tk.Entry(
        search_frame, textvariable=customer_code_search_var,
        font=BODY_FONT,
    )
    code_entry.pack(
        side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 18)
    )
    tk.Label(
        search_frame, text="客商名称", font=BODY_FONT
    ).pack(side=tk.LEFT, padx=(0, 8))
    customer_name_search_var = tk.StringVar()
    name_entry = tk.Entry(
        search_frame, textvariable=customer_name_search_var,
        font=BODY_FONT,
    )
    name_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
    customer_code_search_var.trace_add(
        "write", _on_customer_search_changed
    )
    customer_name_search_var.trace_add(
        "write", _on_customer_search_changed
    )

    footer = tk.Frame(body)
    footer.pack(side=tk.BOTTOM, fill=tk.X, pady=(8, 0))
    customer_status_label = tk.Label(
        footer,
        text=customer_query_status,
        font=BODY_FONT,
        anchor="w",
        fg="#475569",
    )
    customer_status_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
    tk.Button(
        footer, text="关闭", command=close_customer_window,
        padx=15, font=BUTTON_FONT,
        disabledforeground=DISABLED_FOREGROUND,
    ).pack(side=tk.RIGHT)
    customer_refresh_button = tk.Button(
        footer, text="重新查询",
        command=lambda: _start_customer_query("手动重新查询"),
        padx=15, font=BUTTON_FONT,
        disabledforeground=DISABLED_FOREGROUND,
    )
    customer_refresh_button.pack(side=tk.RIGHT, padx=(0, 15))
    customer_use_button = tk.Button(
        footer, text="使用选中客商", command=_use_selected_customer,
        padx=15, bg="#0E7490", fg="#111827", font=BUTTON_FONT,
        activebackground="#155E75", activeforeground="#111827",
        disabledforeground=DISABLED_FOREGROUND,
        state=tk.DISABLED,
    )
    customer_use_button.pack(side=tk.RIGHT, padx=(0, 15))

    table_frame = tk.Frame(body)
    table_frame.pack(fill=tk.BOTH, expand=True)
    column_ids = tuple(
        f"customer_column_{index}"
        for index in range(len(CUSTOMER_COLUMNS))
    )
    customer_tree = CopyableTreeview(
        table_frame,
        columns=column_ids,
        show="headings",
        selectmode="browse",
        style="Preview.Treeview",
        on_copy_status=_show_customer_copy_status,
    )
    vertical_scrollbar = ttk.Scrollbar(
        table_frame, orient="vertical", command=customer_tree.yview
    )
    horizontal_scrollbar = ttk.Scrollbar(
        table_frame, orient="horizontal", command=customer_tree.xview
    )
    customer_tree.configure(
        yscrollcommand=vertical_scrollbar.set,
        xscrollcommand=horizontal_scrollbar.set,
    )
    customer_tree.grid(row=0, column=0, sticky="nsew")
    vertical_scrollbar.grid(row=0, column=1, sticky="ns")
    horizontal_scrollbar.grid(row=1, column=0, sticky="ew")
    table_frame.rowconfigure(0, weight=1)
    table_frame.columnconfigure(0, weight=1)
    customer_tree.bind(
        "<<TreeviewSelect>>", _on_customer_selection_changed
    )
    customer_tree.bind(
        "<Double-1>", _on_customer_row_double_click
    )

    column_widths = (140, 220, 300, 110, 140)
    for index, title in enumerate(CUSTOMER_COLUMNS):
        customer_tree.heading(column_ids[index], text=title, anchor="center")
        customer_tree.column(
            column_ids[index],
            width=column_widths[index],
            minwidth=90,
            stretch=True,
            anchor="center" if index < 2 else "w",
        )

    _set_customer_query_state(
        customer_query_active, customer_query_status
    )
    _refresh_customer_window()
    code_entry.focus_set()
    _start_customer_query("打开窗口")


def _set_customer_query_state(active, status):
    """同步客商窗口的查询状态和重新查询按钮。"""
    global customer_query_active, customer_query_status
    customer_query_active = active
    customer_query_status = status
    if customer_refresh_button is not None:
        try:
            if customer_refresh_button.winfo_exists():
                customer_refresh_button.config(
                    state=tk.DISABLED if active else tk.NORMAL,
                    text="查询中..." if active else "重新查询",
                )
        except tk.TclError:
            pass
    _set_customer_window_status(status)
    _refresh_customer_backfill_state()


def _customer_query_worker(reason):
    """后台查询客商，失败时只回传错误并保留当前列表。"""
    print_log(f"正在查询客商信息：{reason}")
    with customer_query_lock:
        try:
            records = query_customer_records()
        except Exception as exc:
            print_log(f"客商信息查询失败：{exc}")
            ui_message_queue.put(
                ("customer_query_result", [], str(exc))
            )
            return
    print_log(f"客商信息查询完成：{len(records)} 条")
    ui_message_queue.put(("customer_query_result", records, ""))


def _start_customer_query(reason):
    """启动不阻塞主界面的客商查询。"""
    global customer_query_thread, customer_query_pending
    if (
        customer_query_thread is not None
        and customer_query_thread.is_alive()
    ):
        customer_query_pending = True
    else:
        customer_query_pending = False
        customer_query_thread = threading.Thread(
            target=_customer_query_worker,
            args=(reason,),
            daemon=True,
        )
        customer_query_thread.start()
    _set_customer_query_state(True, "正在查询客商信息...")
    win.after(100, poll_ui_queue)


def _build_scrolled_preview_tree(
    parent, columns, snapshot, on_command=None
):
    """创建带滚动条的明细预览表格，并返回其外层容器与 Treeview。"""
    frame = tk.Frame(parent)
    tree = EditableTreeview(
        frame,
        style="Preview.Treeview",
        selectmode="extended",
        on_command=on_command,
    )
    tree.bind("<<TreeviewSelect>>",
              lambda _event: refresh_row_action_state())
    tree.tag_configure("new_row", background="#FFF3CD")
    tree.tag_configure("zebra_even", background="#FFFFFF")
    tree.tag_configure("zebra_odd", background="#EFF5F9")
    default_font = tkfont.nametofont("TkDefaultFont")
    summary_font = (
        default_font.actual()["family"],
        default_font.actual()["size"],
        "bold",
    )
    tree.tag_configure(
        "summary_row",
        background="#FEF3C7",
        foreground="#334155",
        font=summary_font,
    )
    tree.tag_configure(
        MEDICAL_DEVICE_ROW_TAG,
        foreground=MEDICAL_DEVICE_WARNING_COLOR,
    )

    vsb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    hsb = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
    tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
    tree.grid(row=0, column=0, sticky="nsew")
    vsb.grid(row=0, column=1, sticky="ns")
    hsb.grid(row=1, column=0, sticky="ew")
    frame.rowconfigure(0, weight=1)
    frame.columnconfigure(0, weight=1)

    tree["columns"] = columns
    tree.column(
        "#0",
        width=65 if sys.platform.startswith("linux") else 60,
        minwidth=52,
        stretch=False,
        anchor="center",
    )
    for column in columns:
        tree.heading(column, text=column)

    tree.set_snapshot(snapshot)
    return frame, tree


def _build_header_form(parent, file_result, header_fields, header_values, select_text):
    """把单据头字段渲染为多列表单，编辑时直接同步到导出数据。"""
    form = tk.Frame(parent)
    columns = 5 if len(header_fields) >= 5 else max(1, len(header_fields))
    wide_fields = set(get_preview_wide_fields(select_text))
    placements = _build_header_placements(header_fields, wide_fields, columns)
    for index, field in enumerate(header_fields):
        row, column, span = placements[index]
        cell = tk.Frame(form)
        cell.grid(row=row, column=column, columnspan=span,
                  sticky="nsew", padx=4, pady=2)
        label_fg = (
            MEDICAL_DEVICE_WARNING_COLOR
            if field in ("订单类型", "运单号")
            else "#6B7280" if field == "客商编码"
            else "#111827"
        )
        label_font = BODY_FONT if field == "客商编码" else BODY_FONT_BOLD
        display_label = OSCAR_HEADER_DISPLAY_LABELS.get(field, field)
        label = tk.Label(
            cell, text=display_label, anchor="w", font=label_font, fg=label_fg
        )
        label.pack(fill=tk.X)
        if field == "客商编码":
            file_result["consignee_label"] = label
        value_var = tk.StringVar(master=form, value=header_values.get(field, ""))
        if (
            (select_text == "GE-OSCAR拣货单" and field == "收货地址")
            or (select_text == "GE-ORACLE拣货单" and field == "Ship To Address")
        ):
            text_widget = tk.Text(
                cell,
                height=2,
                wrap=tk.WORD,
                relief=tk.SUNKEN,
                bd=1,
            )
            text_widget.insert("1.0", value_var.get())
            text_widget.pack(fill=tk.X)

            def _sync_header_text(
                _event=None,
                text_widget=text_widget,
                current_field=field,
                current_result=file_result,
            ):
                _sync_header_value(
                    current_result,
                    current_field,
                    text_widget.get("1.0", "end-1c"),
                )

            text_widget.bind("<KeyRelease>", _sync_header_text)
            text_widget.bind("<FocusOut>", _sync_header_text)
        else:
            if field == "订单类型":
                order_type_labels = get_order_type_labels(select_text)
                default_label = get_default_order_type_label(select_text)
                if default_label and value_var.get() not in order_type_labels:
                    value_var.set(default_label)
                ttk.Combobox(
                    cell, textvariable=value_var, state="readonly",
                    values=order_type_labels,
                ).pack(fill=tk.X)
            elif field == "客商编码":
                entry = tk.Entry(
                    cell,
                    textvariable=value_var,
                    state=tk.DISABLED,
                    disabledforeground=DISABLED_FOREGROUND,
                )
                entry.pack(fill=tk.X)
                file_result["consignee_entry"] = entry
                file_result["consignee_value_var"] = value_var
            else:
                tk.Entry(cell, textvariable=value_var).pack(fill=tk.X)
            value_var.trace_add(
                "write",
                lambda *_args, field=field, value_var=value_var,
                file_result=file_result: _sync_header_value(
                    file_result, field, value_var.get()
                ),
            )
    for col_index in range(columns):
        form.columnconfigure(col_index, weight=1, uniform="header")
    return form


def _sync_header_value(file_result, field, value):
    """保存允许编辑的单据头值。"""
    if field == "客商编码":
        return
    if preview_table is not None:
        preview_table.update_header(
            file_result["document_id"],
            field,
            value,
            record_undo=False,
        )


def _build_header_placements(fields, wide_fields, columns=5):
    """计算多列表单中每个字段的跨列位置。"""
    placements = []
    row = 0
    col = 0
    for field in fields:
        span = 2 if field in wide_fields else 1
        if col + span > columns:
            row += 1
            col = 0
        placements.append((row, col, span))
        col += span
    return placements


def _build_file_tab(file_result, snapshot, select_text, add_tab=True):
    """为单个文件创建“单据头表单 + 明细”预览页签，并返回明细表格。"""
    tab = ttk.Frame(preview_notebook)
    tab.pack_propagate(False)
    if add_tab:
        preview_notebook.add(tab, text=_short_tab_label(file_result["filename"]))

    status_frame = tk.Frame(tab)
    status_frame.pack(fill=tk.X)
    status_label = tk.Label(
        status_frame,
        text=_status_text(snapshot),
        anchor="w",
        fg=_status_color(snapshot),
    )
    status_label.pack(fill=tk.X, padx=8, pady=(0, 4))
    file_result["status_label"] = status_label
    header_fields, detail_fields = get_preview_layout(select_text)
    header_values = dict(snapshot.header_values)

    tk.Label(tab, text="单据头", anchor="w",
             font=SECTION_FONT).pack(fill=tk.X, padx=8, pady=(0, 2))
    header_panel = _build_header_form(
        tab, file_result, header_fields, header_values, select_text
    )
    header_panel.pack(fill=tk.X, padx=8, pady=(0, 4))

    detail_title_row = tk.Frame(tab)
    detail_title_row.pack(fill=tk.X, padx=8, pady=(0, 2))
    tk.Label(detail_title_row, text="明细", anchor="w",
             font=SECTION_FONT).pack(side=tk.LEFT)
    medical_warning_label = tk.Label(
        detail_title_row,
        text=MEDICAL_DEVICE_WARNING,
        anchor="center",
        justify="center",
        font=SECTION_FONT,
        fg=MEDICAL_DEVICE_WARNING_COLOR,
    )
    file_result["medical_warning_label"] = medical_warning_label

    detail_panel, detail_tree = _build_scrolled_preview_tree(
        tab,
        detail_fields,
        snapshot,
        on_command=_handle_preview_tree_command,
    )
    detail_panel.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 4))

    file_result["tree"] = detail_tree
    file_result["tab"] = tab
    _refresh_file_medical_device_display(
        file_result, snapshot, select_text
    )
    return detail_tree


def _replace_file_tab(file_result, select_text):
    """重建单个文件页签，保留原页签位置与选中状态。"""
    global active_tree
    old_tab = file_result["tab"]
    was_selected = str(preview_notebook.select()) == str(old_tab)
    index = preview_notebook.index(old_tab)
    active_tree = None
    old_tab.destroy()
    _build_file_tab(
        file_result,
        preview_table.snapshot(file_result["document_id"]),
        select_text,
        add_tab=False,
    )
    if preview_notebook.tabs():
        preview_notebook.insert(
            index,
            file_result["tab"],
            text=_short_tab_label(file_result["filename"]),
        )
        if was_selected:
            preview_notebook.select(file_result["tab"])
    else:
        preview_notebook.add(
            file_result["tab"],
            text=_short_tab_label(file_result["filename"]),
        )
        preview_notebook.select(file_result["tab"])
    on_preview_tab_changed()


def _background_task_active():
    """返回是否有后台处理、导出或续查线程正在运行。"""
    return (
        (worker_thread is not None and worker_thread.is_alive())
        or (export_thread is not None and export_thread.is_alive())
        or (continue_thread is not None and continue_thread.is_alive())
        or (wms_thread is not None and wms_thread.is_alive())
        or (product_thread is not None and product_thread.is_alive())
    )


def create_blank_preview(select_text):
    """创建当前模板的空白可编辑页签，用于不选择文件的手工填写。"""
    global preview_select_text, preview_files, active_tree
    headers = get_core_headers(select_text)
    file_result = {
        "filename": MANUAL_FILENAME,
        "status": MANUAL_STATUS,
        "message": "未选择文件，等待人工填写",
        "rows": [],
        "req_uuid": "",
        "log_row": [MANUAL_FILENAME, "", "", "", "", MANUAL_STATUS, MANUAL_STATUS, ""],
        "manual": True,
    }
    preview_select_text = select_text
    _replace_preview_table(select_text, headers, [file_result])
    preview_files = [_new_preview_file_info(
        preview_table.snapshot("document-1")
    )]
    active_tree = None
    _build_file_tab(
        preview_files[0],
        preview_table.snapshot("document-1"),
        select_text,
    )
    preview_notebook.select(0)
    on_preview_tab_changed()
    set_progress_state(0, "处理进度：待开始")


def on_template_changed(_event=None):
    """选择模板时清空旧预览并预渲染当前模板的空白页。"""
    global last_combo_text
    selected_text = combo_model.get().strip()
    if selected_text not in MODEL_MAP:
        return
    if _background_task_active():
        combo_model.set(last_combo_text)
        return
    last_combo_text = selected_text
    clear_preview()
    create_blank_preview(selected_text)


def _active_preview_file():
    """返回当前选中的预览文件数据，未选中时返回 None。"""
    selected_tab = preview_notebook.select()
    for info in preview_files:
        if str(info["tab"]) == selected_tab:
            return info
    return None


def show_preview(select_text, headers, file_results,
                 success_count, fail_count):
    """按文件创建预览页签，并调整界面按钮状态。"""
    global preview_select_text, preview_files, active_tree
    preview_select_text = select_text

    for info in preview_files:
        if info.get("tab") is not None:
            info["tab"].destroy()
    _replace_preview_table(select_text, headers, file_results)
    table_snapshot = preview_table.snapshot_table()
    preview_files = [
        _new_preview_file_info(snapshot)
        for snapshot in table_snapshot.documents
    ]
    active_tree = None
    for info, snapshot in zip(preview_files, table_snapshot.documents):
        _build_file_tab(
            info,
            snapshot,
            select_text,
        )

    if preview_notebook.tabs():
        preview_notebook.select(0)
    on_preview_tab_changed()
    mock_check.config(state=tk.NORMAL)
    btn.config(text="选择文件并开始处理", state=tk.NORMAL)
    abort_btn.config(state=tk.DISABLED)
    total_rows = sum(len(snapshot.lines) for snapshot in table_snapshot.documents)
    pending_count = sum(
        snapshot.metadata.status == preview_model.PENDING
        for snapshot in table_snapshot.documents
    )
    print_log(f"预览数据就绪：模板 {select_text}，页签数 {len(preview_files)}，"
              f"明细行数 {total_rows}，"
              f"成功 {success_count}，失败 {fail_count}，"
              f"结果未生成 {pending_count}")
    set_progress_state(100, "处理进度：完成")


def on_preview_tab_changed(_event=None):
    """切换页签时更新当前预览文件名和操作按钮状态。"""
    global active_tree
    info = _active_preview_file()
    if info is not None:
        if active_tree is not None and active_tree is not info["tree"]:
            active_tree.clear_clipboard()
        active_tree = info["tree"]
        current_file_label.config(text=f"当前预览文件：{info['filename']}")
        snapshot = _snapshot_for_info(info)
        continue_btn.config(
            state=tk.NORMAL if not continue_query_active
            and snapshot is not None
            and snapshot.metadata.status == preview_model.PENDING
            else tk.DISABLED
        )
        refresh_export_state()
        _refresh_customer_backfill_state()
        return
    if active_tree is not None:
        active_tree.clear_clipboard()
    active_tree = None
    current_file_label.config(text="当前预览文件：未选择")
    continue_btn.config(state=tk.DISABLED)
    refresh_export_state()
    _refresh_customer_backfill_state()


def refresh_row_action_state():
    """按当前选中行与复制内容刷新插入/复制/粘贴按钮。"""
    active = active_tree is not None
    active_info = _active_preview_file()
    editable = active and active_info is not None
    insert_btn.config(state=tk.NORMAL if editable else tk.DISABLED)
    copy_btn.config(
        state=tk.NORMAL if editable and active_tree.has_copyable_selection()
        else tk.DISABLED
    )
    paste_btn.config(
        state=tk.NORMAL if editable and active_tree.has_clipboard() else tk.DISABLED
    )


def refresh_export_state():
    """根据所有页签当前明细行数和操作状态刷新底部按钮。"""
    snapshots = [
        _snapshot_for_info(info) for info in preview_files
    ]
    has_rows = any(
        snapshot is not None and bool(snapshot.lines)
        for snapshot in snapshots
    )
    active_snapshot = _active_snapshot()
    active_has_rows = (
        active_snapshot is not None and bool(active_snapshot.lines)
    )
    tree_editable = active_tree is not None and active_snapshot is not None
    refresh_row_action_state()
    export_btn.config(state=tk.NORMAL if has_rows else tk.DISABLED)
    wms_send_btn.config(
        state=tk.NORMAL
        if active_has_rows
        and preview_select_text in (
            "GE-发票单", "GE-ORACLE拣货单", "GE-OSCAR拣货单"
        )
        and not _background_task_active()
        and not wms_send_active and not product_send_active
        else tk.DISABLED
    )
    add_btn.config(state=tk.NORMAL if tree_editable else tk.DISABLED)
    del_btn.config(state=tk.NORMAL if tree_editable else tk.DISABLED)


def active_tree_add_row():
    """在当前预览页签新增一行明细并刷新导出状态。"""
    if active_tree:
        active_tree.add_row()
        active_tree.focus_set()
        refresh_export_state()


def active_tree_delete_selected():
    """在当前预览页签删除选中行并刷新导出状态。"""
    if active_tree:
        active_tree.delete_selected()
        active_tree.focus_set()
        refresh_export_state()


def active_tree_insert_row():
    """在当前预览页签选中行下方插入空白行并刷新操作状态。"""
    if active_tree:
        active_tree.insert_row_after_selection()
        active_tree.focus_set()
        refresh_export_state()


def active_tree_copy_selected():
    """复制当前预览页签选中的整行并刷新操作状态。"""
    if active_tree:
        active_tree.copy_selected()
        refresh_export_state()


def active_tree_paste_row():
    """把当前预览页签复制的整行粘贴为新明细行并刷新操作状态。"""
    if active_tree:
        active_tree.paste_clipboard()
        active_tree.focus_set()
        refresh_export_state()


def clear_preview():
    """清空所有预览页签并恢复初始状态。"""
    global preview_select_text, preview_files, preview_table, active_tree
    global continue_query_active
    for info in preview_files:
        if info.get("tab") is not None:
            info["tab"].destroy()
    preview_files = []
    preview_table = None
    active_tree = None
    continue_query_active = False
    preview_select_text = ""
    current_file_label.config(text="当前预览文件：未选择")
    continue_btn.config(state=tk.DISABLED)
    refresh_export_state()
    set_progress_state(0, "处理进度：待开始")
    btn.config(text="选择文件并开始处理", state=tk.NORMAL)
    abort_btn.config(state=tk.DISABLED)
    mock_check.config(state=tk.NORMAL)


def continue_current_task():
    """继续查询当前“结果未生成”页签记录的原 OCR 任务。"""
    global continue_query_active, continue_thread
    if continue_query_active:
        return
    info = _active_preview_file()
    snapshot = _active_snapshot()
    if (
        info is None
        or snapshot is None
        or snapshot.metadata.status != preview_model.PENDING
    ):
        return
    req_uuid = str(snapshot.metadata.req_uuid).strip()
    if not req_uuid:
        messagebox.showwarning("温馨提示", "当前文件缺少原任务 reqUuid，无法继续查询")
        return

    abort_event.clear()
    continue_query_active = True
    continue_btn.config(state=tk.DISABLED)
    abort_btn.config(state=tk.NORMAL)
    set_progress_state(
        50,
        f"处理进度：正在续查 {os.path.basename(info['filename'])}...",
        "#D97706",
    )
    continue_thread = threading.Thread(
        target=continue_task_worker,
        args=(
            snapshot.document_id,
            snapshot.metadata.filename,
            preview_select_text,
            req_uuid,
            snapshot.metadata.log_row,
            abort_event,
        ),
        daemon=True,
    )
    continue_thread.start()
    refresh_export_state()
    win.after(100, poll_ui_queue)


def continue_task_worker(
    document_id, filename, select_text, req_uuid, log_row, cancel_event
):
    """后台继续查询原 OCR 任务，成功后解析并回传预览刷新消息。"""
    print_log(f"继续查询原任务 reqUuid={req_uuid}，文件：{filename}")
    try:
        _, ocr_result_dict = call_get_result_api(req_uuid, cancel_event)
        if cancel_event.is_set():
            raise OCRAborted("OCR识别已由用户中止")
        if not (ocr_result_dict and ocr_result_dict.get("status") is True):
            raise Exception("OCR返回识别状态异常")
        commit_result = ocr_result_dict.get("data", {}).get("commitResult", {})
        parsed_rows, split_groups = parse_commit_result(
            select_text, commit_result, filename
        )
        updated_log_row = list(log_row)
        if len(updated_log_row) > 6:
            updated_log_row[5] = "成功"
            updated_log_row[6] = "处理成功"
        if cancel_event.is_set():
            raise OCRAborted("OCR识别已由用户中止")
        threading.Thread(
            target=_send_feishu_statistics,
            args=(select_text,),
            daemon=True,
        ).start()
        print_log(f"✅ [{filename}] 继续查询成功")
        ui_message_queue.put((
            "continue_success",
            document_id,
            select_text,
            parsed_rows,
            split_groups,
            tuple(updated_log_row),
        ))
    except OCRResultTimeout:
        print_log(f"⏳ [{filename}] 继续查询5分钟仍未生成结果")
        ui_message_queue.put((
            "continue_pending",
            document_id,
            "再次查询5分钟仍未生成结果，可继续查询原任务",
        ))
    except OCRAborted:
        print_log(f"⏹ [{filename}] 继续查询已由用户中止")
        ui_message_queue.put(("continue_aborted", document_id))
    except Exception as e:
        print_log(f"❌ [{filename}] 继续查询失败：{e}")
        ui_message_queue.put((
            "continue_pending",
            document_id,
            f"继续查询失败：{e}",
        ))


def _apply_continue_success(
    document_id, select_text, parsed_rows, split_groups, updated_log_row
):
    """按续查成功结果重建对应页签，并刷新可编辑/导出状态。"""
    old_snapshot = preview_table.snapshot(document_id)
    preview_table.replace_document(
        document_id,
        preview_model.DocumentInput(
            metadata=preview_model.DocumentMetadata(
                document_id=document_id,
                filename=old_snapshot.metadata.filename,
                status=preview_model.SUCCESS,
                message="处理成功",
                req_uuid=old_snapshot.metadata.req_uuid,
                log_row=tuple(updated_log_row),
                manual=False,
            ),
            rows=tuple(tuple(row) for row in parsed_rows),
            split_groups=tuple(split_groups),
        ),
    )
    info = _preview_file_info(document_id)
    if info is not None:
        _replace_file_tab(info, select_text)
    refresh_export_state()


def _manual_export_base_name(select_text, header_values):
    """根据手工空白页所属模板取单据编号作为导出基准名。"""
    field_by_template = {
        "GE-ORACLE拣货单": "Order Number",
        "GE-OSCAR拣货单": "服务申请号",
        "GE-发票单": "INVOICE NO",
    }
    value = str(
        header_values.get(field_by_template.get(select_text, ""), "")
    ).strip()
    for char in ("\\", "/", ":", "*", "?", '"', "<", ">", "|"):
        value = value.replace(char, "_")
    return value or MANUAL_FILENAME


def _blocking_issue_files(target):
    """按校验原因汇总所有有明细预览单据中的阻塞问题文件名。"""
    blocking_files = {}
    for info in preview_files:
        snapshot = _snapshot_for_info(info)
        if snapshot is None or not snapshot.lines:
            continue
        for issue in preview_table.validate(snapshot.document_id, target):
            if issue.severity != preview_model.BLOCKING:
                continue
            blocking_files.setdefault(issue.code, []).append(
                snapshot.metadata.filename
            )
    return blocking_files


def start_export():
    """选择导出目录后收集有明细的文件页签并启动批量导出线程。"""
    blocking_files = _blocking_issue_files(preview_model.EXPORT)
    validation_messages = (
        ("order_type_required", "以下文件请先选择订单类型：\n"),
        ("waybill_required", "以下文件请先填写运单号：\n"),
        ("consignee_required", "以下文件请先填写客商编码：\n"),
    )
    for code, message in validation_messages:
        filenames = blocking_files.get(code)
        if filenames:
            messagebox.showwarning(
                "温馨提示",
                message + "\n".join(filenames),
            )
            return
    export_targets = []
    for info in preview_files:
        snapshot = _snapshot_for_info(info)
        if snapshot is None or not snapshot.lines:
            continue
        full_rows = merge_preview_rows(
            preview_select_text,
            snapshot.header_values,
            tuple(line.values for line in snapshot.lines),
        )
        export_targets.append({
            "filename": snapshot.metadata.filename,
            "manual": snapshot.metadata.manual,
            "header_values": snapshot.header_values,
            "log_row": snapshot.metadata.log_row,
            "rows": tuple(tuple(row) for row in full_rows),
        })
    if not export_targets:
        messagebox.showwarning("温馨提示", "没有可导出的明细数据")
        return
    last_dir = get_last_export_dir()
    initial_dir = last_dir if last_dir and os.path.isdir(last_dir) else get_output_dir()
    output_dir = filedialog.askdirectory(
        title="选择Excel导出目录",
        initialdir=initial_dir,
    )
    if not output_dir:
        return
    save_last_export_dir(output_dir)
    export_btn.config(state=tk.DISABLED)
    global export_thread
    export_thread = threading.Thread(
        target=export_worker,
        args=(export_targets, output_dir, preview_select_text),
        daemon=True,
    )
    export_thread.start()
    refresh_export_state()
    win.after(100, poll_ui_queue)


def export_worker(export_targets, output_dir, select_text):
    """后台逐文件导出 Excel 到指定目录，汇总成功和失败消息。"""
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    exported = []
    failures = []
    for target in export_targets:
        filename = target["filename"]
        if target["manual"]:
            base_name = _manual_export_base_name(
                select_text, target["header_values"]
            )
        else:
            base_name = os.path.splitext(os.path.basename(filename))[0]
        output_file = os.path.join(
            output_dir, f"{base_name}_识别结果_{timestamp}.xlsx"
        )
        suffix = 2
        while os.path.exists(output_file):
            output_file = os.path.join(
                output_dir, f"{base_name}_识别结果_{timestamp}_{suffix}.xlsx"
            )
            suffix += 1
        try:
            export_excel(
                select_text,
                target["rows"],
                [target["log_row"]],
                output_file,
            )
            exported.append(os.path.basename(output_file))
        except PermissionError:
            failures.append(f"{filename}：文件被占用")
        except Exception as e:
            failures.append(f"{filename}：{e}")

    if not exported and failures:
        ui_message_queue.put(("export_error", "Excel导出失败！\n" + "\n".join(failures)))
        return
    if failures:
        msg = f"导出完成！\n成功 {len(exported)} 个，失败 {len(failures)} 个。\n\n"
        msg += "\n".join(failures)
        ui_message_queue.put(("complete", msg))
        return
    msg = f"导出完成！\n已生成 {len(exported)} 个文件：\n" + "\n".join(exported)
    ui_message_queue.put(("complete", msg))


def close_product_window():
    """关闭新增产品窗口并清理界面引用。"""
    global product_window, product_response_text, product_response_status
    global product_send_button
    if product_window is not None:
        try:
            product_window.destroy()
        except tk.TclError:
            pass
    product_window = None
    product_response_text = None
    product_response_status = None
    product_send_button = None
    if wms_window is not None:
        try:
            if wms_window.winfo_exists():
                win.after_idle(_reapply_wms_grab)
        except tk.TclError:
            pass


def open_add_product_window(parent=None):
    """打开新增产品模态窗口，支持连续录入并发送产品主数据。"""
    global product_window, product_response_text, product_response_status
    global product_send_button
    if product_send_active:
        return
    if product_window is not None:
        try:
            if product_window.winfo_exists():
                product_window.lift()
                product_window.focus_force()
                return
        except tk.TclError:
            product_window = None
    if parent is None:
        parent = wms_window if wms_window is not None else win
    try:
        if not parent.winfo_exists():
            return
    except tk.TclError:
        return

    product_window = tk.Toplevel(parent)
    product_window.title("新增产品")
    product_window.geometry("760x640")
    product_window.minsize(680, 560)
    product_window.transient(parent)
    product_window.grab_set()
    product_window.protocol("WM_DELETE_WINDOW", close_product_window)

    body = tk.Frame(product_window)
    body.pack(fill=tk.BOTH, expand=True, padx=12, pady=10)

    form = tk.Frame(body)
    form.pack(fill=tk.X)
    form.columnconfigure(1, weight=1)
    form.columnconfigure(3, weight=1)

    product_code_var = tk.StringVar()
    tk.Label(
        form, text="产品编码（必填）", fg="#B42318", font=BUTTON_FONT,
        anchor="w",
    ).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 4))
    product_code_entry = tk.Entry(
        form, textvariable=product_code_var, font=BODY_FONT
    )
    product_code_entry.grid(
        row=1, column=0, columnspan=4, sticky="ew", pady=(0, 10)
    )

    tk.Label(
        form, text="产品描述（必填）", fg="#B42318", font=BUTTON_FONT,
        anchor="w",
    ).grid(row=2, column=0, columnspan=4, sticky="w", pady=(0, 4))
    sku_descr_text = tk.Text(
        form, height=2, wrap=tk.WORD, font=BODY_FONT
    )
    sku_descr_text.grid(
        row=3, column=0, columnspan=4, sticky="ew", pady=(0, 10)
    )

    tk.Label(
        form, text="产品属性", font=BODY_FONT_BOLD, anchor="w"
    ).grid(row=4, column=0, columnspan=4, sticky="w")
    attribute_frame = tk.Frame(form)
    attribute_frame.grid(
        row=5, column=0, columnspan=4, sticky="w", pady=(4, 6)
    )

    serial_var = tk.BooleanVar(value=False)
    batch_var = tk.BooleanVar(value=False)
    expiry_var = tk.BooleanVar(value=False)
    dangerous_var = tk.BooleanVar(value=False)
    medical_var = tk.BooleanVar(value=False)
    tube_var = tk.BooleanVar(value=False)

    checkbox_first_row = (
        ("序列号控制", serial_var),
        ("批次控制", batch_var),
        ("效期控制", expiry_var),
    )
    checkbox_second_row = (
        ("危险品", dangerous_var),
        ("医疗器械", medical_var),
        ("球管", tube_var),
    )
    expiry_checkbox = None
    for col, (text, variable) in enumerate(checkbox_first_row):
        checkbox = tk.Checkbutton(
            attribute_frame, text=text, variable=variable, font=BODY_FONT
        )
        checkbox.grid(row=0, column=col, sticky="w", padx=(0, 16))
        if variable is expiry_var:
            expiry_checkbox = checkbox
    for col, (text, variable) in enumerate(checkbox_second_row):
        tk.Checkbutton(
            attribute_frame, text=text, variable=variable, font=BODY_FONT
        ).grid(row=1, column=col, sticky="w", padx=(0, 16), pady=(4, 0))

    shelf_life_var = tk.StringVar()
    shelf_life_unit_var = tk.StringVar(value="MONTH")
    shelf_frame = tk.Frame(form)
    shelf_frame.grid(
        row=6, column=0, columnspan=4, sticky="w", pady=(8, 0)
    )
    tk.Label(
        shelf_frame, text="有效期", font=BODY_FONT
    ).pack(side=tk.LEFT)
    shelf_life_entry = tk.Entry(
        shelf_frame, textvariable=shelf_life_var, width=12,
        state=tk.DISABLED, font=BODY_FONT,
    )
    shelf_life_entry.pack(side=tk.LEFT, padx=(8, 12))
    shelf_radios = []
    for unit_value, unit_label in (
        ("DAY", "日"), ("MONTH", "月"), ("YEAR", "年")
    ):
        radio = tk.Radiobutton(
            shelf_frame, text=unit_label, value=unit_value,
            variable=shelf_life_unit_var, state=tk.DISABLED,
            font=BODY_FONT,
        )
        radio.pack(side=tk.LEFT, padx=(0, 10))
        shelf_radios.append(radio)

    def toggle_shelf_life(*_args):
        enabled = bool(medical_var.get())
        state = tk.NORMAL if enabled else tk.DISABLED
        shelf_life_entry.config(state=state)
        for radio in shelf_radios:
            radio.config(state=state)

    expiry_before_medical = None

    def on_serial_change(*_args):
        if medical_var.get() and serial_var.get():
            batch_var.set(False)

    def on_batch_change(*_args):
        if medical_var.get() and batch_var.get():
            serial_var.set(False)

    def apply_medical_rules(*_args):
        nonlocal expiry_before_medical
        if medical_var.get():
            if serial_var.get() and batch_var.get():
                serial_var.set(False)
                batch_var.set(False)
            if expiry_before_medical is None:
                expiry_before_medical = bool(expiry_var.get())
                expiry_var.set(True)
            expiry_checkbox.config(state=tk.DISABLED)
        else:
            if expiry_before_medical is not None:
                expiry_var.set(expiry_before_medical)
                expiry_before_medical = None
            expiry_checkbox.config(state=tk.NORMAL)
        toggle_shelf_life()

    serial_var.trace_add("write", on_serial_change)
    batch_var.trace_add("write", on_batch_change)
    medical_var.trace_add("write", apply_medical_rules)
    apply_medical_rules()

    response_frame = tk.Frame(body)
    response_frame.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
    product_response_text, product_response_status = _wms_response_pane(
        response_frame, "接口返回内容"
    )
    product_response_text.configure(height=5)
    _replace_product_response(id(product_response_text), "尚未发送", "neutral")

    checkbox_vars = [
        serial_var, batch_var, expiry_var,
        dangerous_var, medical_var, tube_var,
    ]

    def collect_product_form():
        return {
            "sku": product_code_var.get(),
            "sku_descr": sku_descr_text.get("1.0", "end-1c"),
            "serial_control": serial_var.get(),
            "batch_control": batch_var.get(),
            "expiry_control": expiry_var.get(),
            "dangerous": dangerous_var.get(),
            "medical_device": medical_var.get(),
            "tube": tube_var.get(),
            "shelf_life": shelf_life_var.get(),
            "shelf_life_unit": shelf_life_unit_var.get(),
        }

    def clear_product_form():
        if product_send_active:
            return
        product_code_var.set("")
        sku_descr_text.delete("1.0", tk.END)
        if medical_var.get():
            medical_var.set(False)
        for variable in checkbox_vars:
            variable.set(False)
        shelf_life_var.set("")
        shelf_life_unit_var.set("MONTH")
        toggle_shelf_life()
        _replace_product_response(id(product_response_text), "尚未发送")
        product_send_button.config(state=tk.NORMAL, text="确认发送")
        product_code_entry.focus_set()

    def start_product_send():
        global product_thread, product_send_active
        if product_send_active:
            return
        form_values = collect_product_form()
        error = validate_put_sku_form(form_values)
        if error:
            messagebox.showwarning(
                "校验失败", error, parent=product_window
            )
            return
        payload = build_put_sku_payload(form_values)
        medical_device = bool(form_values.get("medical_device"))
        product_send_active = True
        product_send_button.config(state=tk.DISABLED, text="发送中...")
        token = id(product_response_text)
        _replace_product_response(
            token, "发送中...\n\n正在等待接口返回。", "sending"
        )
        product_thread = threading.Thread(
            target=product_send_worker,
            args=(payload, token, medical_device),
            daemon=True,
        )
        product_thread.start()
        refresh_export_state()
        win.after(100, poll_ui_queue)

    button_frame = tk.Frame(body)
    button_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(8, 0))
    product_send_button = tk.Button(
        button_frame, text="确认发送", command=start_product_send,
        width=12, bg="#0E7490", fg="#111827", font=BUTTON_FONT,
        activebackground="#155E75", activeforeground="#111827",
        disabledforeground=DISABLED_FOREGROUND,
    )
    product_send_button.pack(side=tk.RIGHT, padx=(0, 8))
    tk.Button(
        button_frame, text="取消", command=close_product_window,
        width=10, font=BUTTON_FONT,
        disabledforeground=DISABLED_FOREGROUND,
    ).pack(side=tk.RIGHT, padx=(8, 0))
    tk.Button(
        button_frame, text="清空", command=clear_product_form,
        width=10, font=BUTTON_FONT,
        disabledforeground=DISABLED_FOREGROUND,
    ).pack(side=tk.RIGHT)
    product_window.after(100, product_code_entry.focus_set)


def product_send_worker(payload, token, medical_device=False):
    """后台发送 putSKU 产品主数据报文并回传结果。"""
    print_log("正在发送WMS产品主数据报文...")
    try:
        response = send_put_sku(payload)
        text = format_wms_response(response)
        print_log(f"WMS产品接口回告：{text[:200]}")
        success = is_wms_send_success(response)
        if success:
            result_text = f"发送成功\n\n{text}"
        else:
            result_text = f"发送失败：HTTP 状态或 returnFlag 不满足\n\n{text}"
        ui_message_queue.put(
            (
                "product_send_result",
                token,
                success,
                result_text,
                medical_device,
            )
        )
    except Exception as e:
        print_log(f"WMS产品接口发送失败: {e}")
        ui_message_queue.put(
            (
                "product_send_result",
                token,
                False,
                f"发送失败：{e}",
                medical_device,
            )
        )


def close_wms_window():
    """关闭接口发送二级窗口并清理界面引用。"""
    global wms_window, wms_window_request_text, wms_window_response_text
    global wms_window_response_status, wms_confirm_button
    close_product_window()
    if wms_window is not None:
        try:
            wms_window.destroy()
        except tk.TclError:
            pass
    wms_window = None
    wms_window_request_text = None
    wms_window_response_text = None
    wms_window_response_status = None
    wms_confirm_button = None


def _release_wms_grab_on_iconify(_event=None):
    """主窗口最小化时释放二级窗口抓取，避免任务栏恢复被模态状态阻塞。"""
    for target in (product_window, wms_window):
        if target is None:
            continue
        try:
            target.grab_release()
        except tk.TclError:
            pass


def _reapply_wms_grab():
    """重新给接口发送二级窗口设置模态抓取。"""
    target = product_window if product_window is not None else wms_window
    if target is None:
        return
    try:
        if target.winfo_exists():
            target.grab_set()
    except tk.TclError:
        pass


def _restore_wms_window_on_map(_event=None):
    """主窗口恢复时同步恢复接口发送二级窗口并重新建立抓取。"""
    if wms_window is not None:
        try:
            if wms_window.winfo_exists():
                wms_window.deiconify()
                wms_window.lift()
                wms_window.focus_force()
        except tk.TclError:
            pass
    if product_window is not None:
        try:
            if product_window.winfo_exists():
                product_window.deiconify()
                product_window.lift()
                product_window.focus_force()
        except tk.TclError:
            pass
    if wms_window is not None or product_window is not None:
        win.after_idle(_reapply_wms_grab)


def open_wms_send_window():
    """打开当前页签的只读报文窗口，支持确认发送和回告展示。"""
    global wms_window, wms_window_request_text, wms_window_response_text
    global wms_confirm_button, wms_thread, product_window
    global wms_send_active
    if product_window is not None:
        try:
            if product_window.winfo_exists():
                product_window.lift()
                product_window.focus_force()
                return
        except tk.TclError:
            product_window = None
    if product_send_active or wms_send_active or _background_task_active():
        return
    if preview_select_text not in (
        "GE-发票单", "GE-ORACLE拣货单", "GE-OSCAR拣货单"
    ):
        return
    snapshot = _active_snapshot()
    if snapshot is None:
        return
    blocking_codes = {
        issue.code
        for issue in preview_table.validate(
            snapshot.document_id, preview_model.WMS_SEND
        )
        if issue.severity == preview_model.BLOCKING
    }
    validation_messages = (
        ("no_exportable_lines", "当前单据没有可发送的明细数据"),
        ("order_type_required", "当前单据请先选择订单类型"),
        (
            "consignee_required",
            "请先填写客商编码：\n" + snapshot.metadata.filename,
        ),
        ("waybill_required", "当前发票缺少运单号，无法发送"),
        ("invoice_no_required", "当前发票缺少INVOICE NO，无法发送"),
        (
            "order_number_required",
            "当前ORACLE拣货单缺少Order Number，无法发送",
        ),
        (
            "service_request_no_required",
            "当前OSCAR拣货单缺少服务申请号，无法发送",
        ),
    )
    for code, message in validation_messages:
        if code in blocking_codes:
            messagebox.showwarning("温馨提示", message)
            return

    header_values = snapshot.header_values
    detail_rows = tuple(line.values for line in snapshot.lines)
    if preview_select_text == "GE-发票单":
        payload = build_put_purchase_order_payload(header_values, detail_rows)
        send_func = send_put_purchase_order
        log_name = "采购订单"
    elif preview_select_text == "GE-ORACLE拣货单":
        payload = build_put_original_sales_order_payload(
            preview_select_text, header_values, detail_rows
        )
        send_func = send_put_original_sales_order
        log_name = "ORACLE销售订单"
    else:
        payload = build_put_original_sales_order_payload(
            preview_select_text, header_values, detail_rows
        )
        send_func = send_put_original_sales_order
        log_name = "OSCAR销售订单"
    if wms_window is not None:
        try:
            if wms_window.winfo_exists():
                wms_window.lift()
                return
        except tk.TclError:
            pass

    wms_window = tk.Toplevel(win)
    wms_window.title("接口发送")
    wms_window.geometry("1000x720")
    wms_window.minsize(720, 480)
    wms_window.transient(win)
    wms_window.grab_set()
    wms_window.protocol("WM_DELETE_WINDOW", close_wms_window)

    body = tk.Frame(wms_window)
    body.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

    button_frame = tk.Frame(body)
    button_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(8, 0))

    paned = tk.PanedWindow(body, orient=tk.VERTICAL, sashwidth=6)
    paned.pack(fill=tk.BOTH, expand=True)

    request_frame = tk.Frame(paned)
    response_frame = tk.Frame(paned)
    paned.add(request_frame, minsize=160)
    paned.add(response_frame, minsize=120)

    wms_window_request_text = _wms_text_pane(request_frame, "组装报文")
    wms_window_response_text, wms_window_response_status = _wms_response_pane(
        response_frame, "接口返回内容"
    )

    wms_window_request_text.config(state=tk.NORMAL)
    wms_window_request_text.insert(
        tk.END, json.dumps(payload, ensure_ascii=False, indent=2)
    )
    wms_window_request_text.config(state=tk.DISABLED)

    _replace_wms_response(id(wms_window_response_text), "尚未发送", "neutral")

    def start_wms_send():
        global wms_thread, wms_send_active
        if wms_send_active or wms_window_response_text is None:
            return
        wms_send_active = True
        if wms_confirm_button is not None:
            wms_confirm_button.config(state=tk.DISABLED, text="发送中...")
        token = id(wms_window_response_text)
        _replace_wms_response(
            token, "发送中...\n\n正在等待接口返回。", "sending"
        )
        wms_thread = threading.Thread(
            target=wms_send_worker,
            args=(payload, token, send_func, log_name),
            daemon=True,
        )
        wms_thread.start()
        refresh_export_state()
        win.after(100, poll_ui_queue)

    wms_confirm_button = tk.Button(
        button_frame, text="确认发送", command=start_wms_send,
        width=12, bg="#0E7490", fg="#111827", font=BUTTON_FONT,
        activebackground="#155E75", activeforeground="#111827",
        disabledforeground=DISABLED_FOREGROUND,
    )
    tk.Button(
        button_frame, text="关闭", command=close_wms_window,
        width=10, font=BUTTON_FONT,
        disabledforeground=DISABLED_FOREGROUND,
    ).pack(side=tk.RIGHT)
    wms_confirm_button.pack(side=tk.RIGHT, padx=(0, 8))
    tk.Button(
        button_frame, text="新增产品", command=open_add_product_window,
        width=10, bg="#0E7490", fg="#111827", font=BUTTON_FONT,
        activebackground="#155E75", activeforeground="#111827",
        disabledforeground=DISABLED_FOREGROUND,
    ).pack(side=tk.RIGHT, padx=(0, 8))

    wms_window.wait_visibility()
    paned.update_idletasks()
    try:
        paned.sash_place(0, 0, max(160, int(paned.winfo_height() * 0.7)))
    except tk.TclError:
        pass

    wms_window_request_text.yview_moveto(0)
    wms_window_response_text.yview_moveto(0)


def wms_send_worker(payload, token, send_func, log_name):
    """后台发送 WMS 报文，并把回告文本回传主线程。"""
    print_log(f"正在发送WMS{log_name}报文...")
    try:
        response = send_func(payload)
        text = format_wms_response(response)
        print_log(f"WMS接口回告：{text[:200]}")
        success = is_wms_send_success(response)
        if success:
            result_text = f"发送成功\n\n{text}"
        else:
            result_text = f"发送失败：HTTP 状态或 returnFlag 不满足\n\n{text}"
        ui_message_queue.put(
            ("wms_send_result", token, success, result_text)
        )
    except Exception as e:
        print_log(f"WMS接口发送失败: {e}")
        error_text = f"发送失败：{e}"
        ui_message_queue.put(
            ("wms_send_result", token, False, error_text)
        )


def draw_progress_canvas():
    """按当前进度百分比重绘进度条。"""
    width = progress_canvas.winfo_width()
    height = progress_canvas.winfo_height()
    if width <= 1 or height <= 1:
        return
    progress_canvas.delete("all")
    progress_canvas.create_rectangle(
        1, 1, width - 1, height - 1, fill="#E5E7EB", outline="#94A3B8"
    )
    fill_width = int((width - 2) * progress_percent / 100)
    if fill_width > 0:
        progress_canvas.create_rectangle(
            1, 1, fill_width + 1, height - 1, fill=progress_color, outline=""
        )


def set_progress_state(percent, text, color="#16A34A"):
    """更新进度文案、颜色和进度条。"""
    global progress_percent, progress_color
    progress_percent = percent
    progress_color = color
    progress_label.config(
        text=text,
        fg="#B42318" if color == "#D92D20" else "#111827"
    )
    draw_progress_canvas()


def update_progress(done, total):
    percent = 50 + round(done / total * 50) if total else 100
    set_progress_state(percent, f"处理进度：{done}/{total}（{percent}%）")


def poll_ui_queue():
    """主线程轮询处理结果消息，并驱动界面状态更新。"""
    global continue_query_active, wms_send_active, product_send_active
    global medical_device_catalog_refresh_active
    global customer_query_active
    flush_log()
    while True:
        try:
            kind, *payload = ui_message_queue.get_nowait()
        except queue.Empty:
            break
        if kind == "preview":
            if abort_event.is_set():
                finish_abort_state()
                continue
            show_preview(*payload)
        elif kind == "progress":
            update_progress(payload[0], payload[1])
        elif kind == "complete":
            refresh_export_state()
            messagebox.showinfo("完成", payload[0])
        elif kind == "processing_aborted":
            finish_abort_state()
        elif kind == "processing_error":
            btn.config(text="选择文件并开始处理", state=tk.NORMAL)
            mock_check.config(state=tk.NORMAL)
            abort_btn.config(state=tk.DISABLED)
            set_progress_state(100, "处理进度：处理失败", "#D92D20")
            messagebox.showerror("错误", payload[0])
        elif kind == "export_error":
            refresh_export_state()
            messagebox.showerror("错误", payload[0])
        elif kind == "continue_aborted":
            document_id = payload[0]
            preview_table.update_status(
                document_id,
                preview_model.PENDING,
                "继续查询已中止",
            )
            continue_query_active = False
            abort_event.clear()
            _render_preview_document(document_id)
            on_preview_tab_changed()
            finish_abort_state()
        elif kind == "continue_success":
            (document_id, select_text, parsed_rows, split_groups,
             updated_log_row) = payload
            continue_query_active = False
            _apply_continue_success(
                document_id,
                select_text,
                parsed_rows,
                split_groups,
                updated_log_row,
            )
            set_progress_state(100, "处理进度：续查完成")
        elif kind == "continue_pending":
            document_id, message = payload
            preview_table.update_status(
                document_id,
                preview_model.PENDING,
                message,
            )
            continue_query_active = False
            _render_preview_document(document_id)
            on_preview_tab_changed()
            set_progress_state(100, "处理进度：续查未生成结果", "#D97706")
        elif kind == "medical_device_catalog":
            catalog, source, error_text = payload
            medical_device_catalog_refresh_active = False
            if source == "network":
                _apply_medical_device_catalog(catalog)
                if catalog:
                    status = f"查询成功，共 {len(catalog)} 条产品信息"
                else:
                    status = "查询成功，未返回产品信息"
            else:
                status = (
                    "查询失败，已保留当前列表"
                    + (f"：{error_text}" if error_text else "")
                )
            _set_medical_device_refresh_state(False, status)
        elif kind == "customer_query_result":
            records, error_text = payload
            customer_query_active = False
            if error_text:
                status = (
                    "查询失败，已保留当前列表"
                    f"：{error_text}"
                )
            else:
                customer_records[:] = records
                _refresh_customer_window()
                status = (
                    f"查询成功，共 {len(records)} 条客商信息"
                    if records else "查询成功，未返回客商信息"
                )
            _set_customer_query_state(False, status)
        elif kind == "product_send_result":
            token, success, text, medical_device = payload
            _replace_product_response(
                token, text, "success" if success else "failure"
            )
            product_send_active = False
            if product_send_button is not None:
                try:
                    if product_send_button.winfo_exists():
                        product_send_button.config(
                            state=tk.NORMAL, text="重新发送"
                        )
                except tk.TclError:
                    pass
            refresh_export_state()
            if success and medical_device:
                _start_medical_device_catalog_refresh(
                    "新增医疗器械产品成功"
                )
        elif kind == "wms_send_result":
            token, success, text = payload
            _replace_wms_response(
                token, text, "success" if success else "failure"
            )
            wms_send_active = False
            if wms_confirm_button is not None:
                try:
                    if wms_confirm_button.winfo_exists():
                        wms_confirm_button.config(
                            state=tk.NORMAL, text="重新发送"
                        )
                except tk.TclError:
                    pass
            refresh_export_state()

    if medical_device_catalog_refresh_pending and (
        medical_device_catalog_thread is None
        or not medical_device_catalog_thread.is_alive()
    ):
        _start_medical_device_catalog_refresh("处理等待中的刷新请求")

    if customer_query_pending and (
        customer_query_thread is None
        or not customer_query_thread.is_alive()
    ):
        _start_customer_query("处理等待中的查询请求")

    if (
        medical_device_catalog_refresh_pending
        or customer_query_pending
        or any(
        thread is not None and thread.is_alive()
        for thread in (
            worker_thread,
            export_thread,
            continue_thread,
            wms_thread,
            product_thread,
            medical_device_catalog_thread,
            customer_query_thread,
        )
        )
    ):
        win.after(100, poll_ui_queue)


# ========== 界面部分 ==========
win = TkinterDnD.Tk()
win.title("GE单据批量OCR处理工具")
max_width, max_height = win.maxsize()
win.geometry(f"{max_width}x{max_height}")
win.bind("<Unmap>", _release_wms_grab_on_iconify)
win.bind("<Map>", _restore_wms_window_on_map)

if sys.platform == "win32":
    UI_FONT_FAMILY = "黑体"
    PREVIEW_HEADING_FONT = ("Microsoft YaHei UI", 10, "bold")
else:
    UI_FONT_FAMILY = _resolve_cjk_font_family(win)
    PREVIEW_HEADING_FONT = (
        UI_FONT_FAMILY,
        14 if sys.platform.startswith("linux") else 15,
        "bold",
    )
BODY_FONT = (UI_FONT_FAMILY, 11)
BODY_FONT_BOLD = (UI_FONT_FAMILY, 11, "bold")
SECTION_FONT = (UI_FONT_FAMILY, 12, "bold")

top = tk.Frame(win)
top.pack(fill=tk.X, padx=10, pady=(10, 0))

BUTTON_FONT = tkfont.nametofont("TkDefaultFont").copy()
BUTTON_FONT.configure(weight="bold")
DISABLED_FOREGROUND = "#111827"

tk.Label(top, text="选择模版规则：", font=BODY_FONT).pack(side=tk.LEFT)
combo_model = ttk.Combobox(top, width=28, font=BODY_FONT, state="readonly")
combo_model["values"] = list(MODEL_MAP.keys())
combo_model.set("")
combo_model.pack(side=tk.LEFT, padx=(0, 20))
last_combo_text = combo_model.get()
combo_model.bind("<<ComboboxSelected>>", on_template_changed)

mock_var = tk.BooleanVar(value=False)
mock_check = tk.Checkbutton(top, text="模拟数据", variable=mock_var, font=BODY_FONT)
mock_check.pack(side=tk.LEFT, padx=(0, 20))

btn = tk.Button(top, text="选择文件并开始处理", command=run_task,
                padx=10, bg="#4CAF50", fg="#0B3D0F", font=BUTTON_FONT,
                disabledforeground=DISABLED_FOREGROUND)
btn.pack(side=tk.LEFT, padx=(0, 10))
continue_btn = tk.Button(
    top, text="继续查询原任务", command=continue_current_task,
    padx=10, bg="#D97706", fg="#111827", font=BUTTON_FONT,
    disabledforeground=DISABLED_FOREGROUND,
    state=tk.DISABLED,
)
continue_btn.pack(side=tk.LEFT, padx=(0, 10))
export_btn = tk.Button(top, text="确认并导出", command=start_export,
                       padx=10, bg="#2196F3", fg="#0A2540", font=BUTTON_FONT,
                       disabledforeground=DISABLED_FOREGROUND,
                       state=tk.DISABLED)
export_btn.pack(side=tk.LEFT, padx=(0, 10))
wms_send_btn = tk.Button(
    top, text="接口发送", command=open_wms_send_window,
    padx=10, bg="#0E7490", fg="#111827", font=BUTTON_FONT,
    activebackground="#155E75", activeforeground="#111827",
    disabledforeground=DISABLED_FOREGROUND,
    state=tk.DISABLED,
)
wms_send_btn.pack(side=tk.LEFT, padx=(0, 10))
abort_btn = tk.Button(
    top, text="中止", command=abort_processing,
    padx=10, bg="#D92D20", fg="#111827", font=BUTTON_FONT,
    activebackground="#B42318", activeforeground="#111827",
    disabledforeground=DISABLED_FOREGROUND,
    state=tk.DISABLED,
)
abort_btn.pack(side=tk.LEFT)

progress_frame = tk.Frame(top)
progress_frame.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 0))

progress_label = tk.Label(progress_frame, text="处理进度：待开始",
                          font=BODY_FONT_BOLD, anchor="w")
progress_label.pack(side=tk.LEFT)

progress_canvas = tk.Canvas(progress_frame, height=14, highlightthickness=0)
progress_canvas.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 0), pady=7)
progress_canvas.bind("<Configure>", lambda _event: draw_progress_canvas())

table_frame = tk.Frame(win)
table_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(2, 10))

current_file_label = tk.Label(
    table_frame, text="当前预览文件：未选择",
    font=BODY_FONT_BOLD, anchor="w"
)
current_file_label.pack(fill=tk.X, padx=2, pady=(0, 4))

preview_notebook = ttk.Notebook(table_frame)
preview_notebook.pack(fill=tk.BOTH, expand=True)
preview_notebook.bind("<<NotebookTabChanged>>", on_preview_tab_changed)
table_frame.drop_target_register(DND_FILES)
table_frame.dnd_bind("<<Drop>>", on_file_drop)

style = ttk.Style(win)
if sys.platform == "win32":
    style.theme_use("clam")
style.configure("Preview.Treeview", background="#FFFFFF",
                fieldbackground="#FFFFFF", rowheight=39)
style.configure("Preview.Treeview.Heading", background="#E8EEF2",
                font=PREVIEW_HEADING_FONT, anchor="center")

op_frame = tk.Frame(win)
op_frame.pack(fill=tk.X, padx=10, pady=(0, 10))

add_btn = tk.Button(op_frame, text="新增行", command=active_tree_add_row,
                    padx=15, font=BUTTON_FONT,
                    disabledforeground=DISABLED_FOREGROUND,
                    state=tk.DISABLED)
add_btn.pack(side=tk.LEFT, padx=(0, 15))
insert_btn = tk.Button(op_frame, text="插入行", command=active_tree_insert_row,
                       padx=15, font=BUTTON_FONT,
                       disabledforeground=DISABLED_FOREGROUND,
                       state=tk.DISABLED)
insert_btn.pack(side=tk.LEFT, padx=(0, 15))
copy_btn = tk.Button(op_frame, text="复制行", command=active_tree_copy_selected,
                     padx=15, font=BUTTON_FONT,
                     disabledforeground=DISABLED_FOREGROUND,
                     state=tk.DISABLED)
copy_btn.pack(side=tk.LEFT, padx=(0, 15))
paste_btn = tk.Button(op_frame, text="粘贴行", command=active_tree_paste_row,
                      padx=15, font=BUTTON_FONT,
                      disabledforeground=DISABLED_FOREGROUND,
                      state=tk.DISABLED)
paste_btn.pack(side=tk.LEFT, padx=(0, 15))
del_btn = tk.Button(op_frame, text="删除行", command=active_tree_delete_selected,
                    padx=15, font=BUTTON_FONT,
                    disabledforeground=DISABLED_FOREGROUND,
                    state=tk.DISABLED)
del_btn.pack(side=tk.LEFT, padx=(0, 15))

query_log_btn = tk.Button(
    op_frame, text="查询日志", command=open_log_window,
    padx=15, font=BUTTON_FONT,
    disabledforeground=DISABLED_FOREGROUND,
)
query_log_btn.pack(side=tk.LEFT, padx=(0, 15))
tk.Button(
    op_frame, text="查询医疗器械", command=open_medical_device_window,
    padx=15, font=BUTTON_FONT,
    disabledforeground=DISABLED_FOREGROUND,
).pack(side=tk.LEFT, padx=(0, 15))
tk.Button(
    op_frame, text="查询客商", command=open_customer_window,
    padx=15, font=BUTTON_FONT,
    disabledforeground=DISABLED_FOREGROUND,
).pack(side=tk.LEFT, padx=(0, 15))
tk.Button(
    op_frame, text="新增产品", command=open_add_product_window,
    padx=15, bg="#0E7490", fg="#111827", font=BUTTON_FONT,
    activebackground="#155E75", activeforeground="#111827",
    disabledforeground=DISABLED_FOREGROUND,
).pack(side=tk.LEFT)

win.after(200, poll_log_queue)

if __name__ == "__main__":
    _apply_medical_device_catalog(load_medical_device_catalog())
    _start_medical_device_catalog_refresh("程序启动")
    if sys.platform == "win32":
        win.state("zoomed")
    elif sys.platform.startswith("linux"):
        try:
            win.attributes("-zoomed", True)
        except tk.TclError:
            pass
    else:
        win.state("zoomed")
    win.mainloop()
