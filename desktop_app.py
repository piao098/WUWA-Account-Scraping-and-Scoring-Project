"""Desktop GUI for scraping, scoring, filtering, previewing, and pushing accounts."""

from __future__ import annotations

import json
import queue
import re
import sys
import threading
import time
import traceback
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import BooleanVar, END, Listbox, MULTIPLE, StringVar, Tk, Toplevel, messagebox
from tkinter import ttk
from typing import Any, Callable

import batch_scorer
import filter_results
import notify
import report
import value_model
from fetch_list import DEFAULT_PAGE_SIZE
from score_accounts import DEFAULT_RULES


APP_TITLE = "螃蟹鸣潮账号筛选推送器"


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


SCRIPT_DIR = app_dir()
CONFIG_PATH = SCRIPT_DIR / "configs" / "app_filters.json"
RAW_OUTPUT = SCRIPT_DIR / "data" / "accounts_raw.json"
SCORE_OUTPUT = SCRIPT_DIR / "data" / "score_results_batch.json"
VALUE_OUTPUT = SCRIPT_DIR / "data" / "value_results.json"
FILTERED_OUTPUT = SCRIPT_DIR / "data" / "value_results_filtered.json"
REPORT_OUTPUT = SCRIPT_DIR / "reports" / "report_filtered.html"
PUSH_PREVIEW = SCRIPT_DIR / "reports" / "push_preview.html"
RULES_PATH = SCRIPT_DIR / "configs" / "scoring_rules.json"
CHARACTER_TIERS_PATH = SCRIPT_DIR / "configs" / "character_tiers.json"
VALUE_FORMULA_PATH = SCRIPT_DIR / "configs" / "value_formula.json"
NOTIFY_CONFIG_PATH = SCRIPT_DIR / "notify_config.json"


DEFAULT_STATE: dict[str, Any] = {
    "price_group_step": "100",
    "price_group_top_n": "5",
    "prefilter_group_candidate_limit": "",
    "min_price": "200",
    "max_price": "2000",
    "max_publish_age_days": "7",
    "min_total_score": "",
    "min_value_score": "",
    "min_five_star_characters": "",
    "min_five_star_weapons": "",
    "min_effective_pulls": "",
    "min_collectible_score": "",
    "max_hot_count": "",
    "required_characters": "",
    "required_weapons": "",
    "excluded_keywords": "",
    "require_bargain": False,
    "hide_tap_bound": False,
    "hide_wegame_bound": False,
    "hide_change_bind_cd": False,
    "use_list_snapshot": False,
    "schedule_enabled": False,
    "schedule_mode": "interval",
    "schedule_interval_minutes": "120",
    "schedule_daily_time": "09:00",
    "schedule_push": True,
}

DEFAULT_NOTIFY_STATE: dict[str, str] = {
    "pushplus_token": "",
    "pushplus_topic": "",
    "pushplus_title": "螃蟹鸣潮账号最终评分 - Top推荐",
}


class App(Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1280x840")
        self.minsize(1100, 720)
        self.configure(bg="#eef2f7")

        self.text_vars: dict[str, StringVar] = {}
        self.bool_vars: dict[str, BooleanVar] = {}
        self.formula_vars: dict[str, StringVar] = {}
        self.tier_edit_vars: dict[str, StringVar] = {}
        self.progress_vars: dict[str, StringVar] = {}
        self.schedule_vars: dict[str, StringVar] = {}
        self.notify_vars: dict[str, StringVar] = {}
        self.tier_data: dict[str, Any] = {}
        self.progress_start_time: float | None = None
        self.detail_start_time: float | None = None
        self.next_schedule_time: datetime | None = None
        self.schedule_running = False
        self.detail_total = 0
        self.detail_done = 0
        self.detail_reused = 0
        self.detail_errors = 0
        self.log_queue: queue.Queue[str] = queue.Queue()
        self.worker: threading.Thread | None = None

        self._configure_style()
        self._build_ui()
        self._load_state()
        self._load_notify_state()
        self._load_formula_state()
        self._load_tier_editor()
        self._recompute_schedule("启动")
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(120, self._drain_log_queue)
        self.after(1000, self._tick_progress)
        self.after(1000, self._tick_schedule)

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", font=("Microsoft YaHei UI", 10))
        style.configure("TFrame", background="#eef2f7")
        style.configure("Hero.TFrame", background="#0f172a")
        style.configure("ActionBar.TFrame", background="#0f172a")
        style.configure("Card.TFrame", background="#ffffff", relief="solid", borderwidth=1)
        style.configure("PrimaryAccent.TFrame", background="#2563eb")
        style.configure("Title.TLabel", background="#eef2f7", foreground="#0f172a", font=("Microsoft YaHei UI", 18, "bold"))
        style.configure("HeroTitle.TLabel", background="#0f172a", foreground="#ffffff", font=("Microsoft YaHei UI", 20, "bold"))
        style.configure("HeroSub.TLabel", background="#0f172a", foreground="#cbd5e1", font=("Microsoft YaHei UI", 10))
        style.configure("Chip.TLabel", background="#1e293b", foreground="#dbeafe", font=("Microsoft YaHei UI", 9), padding=(8, 4))
        style.configure("Sub.TLabel", background="#eef2f7", foreground="#64748b", font=("Microsoft YaHei UI", 10))
        style.configure("CardTitle.TLabel", background="#ffffff", foreground="#0f172a", font=("Microsoft YaHei UI", 12, "bold"))
        style.configure("MetricValue.TLabel", background="#ffffff", foreground="#2563eb", font=("Microsoft YaHei UI", 13, "bold"))
        style.configure("TLabel", background="#ffffff", foreground="#374151")
        style.configure("Muted.TLabel", background="#ffffff", foreground="#6b7280")
        style.configure("Formula.TLabel", background="#ffffff", foreground="#111827", font=("Consolas", 11))
        style.configure("FormulaNote.TLabel", background="#ffffff", foreground="#6b7280", font=("Microsoft YaHei UI", 9))
        style.configure("TEntry", fieldbackground="#ffffff", bordercolor="#cbd5e1", lightcolor="#cbd5e1", darkcolor="#cbd5e1", padding=(6, 4))
        style.configure("TCheckbutton", background="#ffffff", foreground="#374151")
        style.configure("Primary.TButton", background="#2563eb", foreground="#ffffff", bordercolor="#2563eb", focusthickness=0, padding=(16, 9), font=("Microsoft YaHei UI", 10, "bold"))
        style.map("Primary.TButton", background=[("active", "#1d4ed8"), ("disabled", "#93c5fd")], foreground=[("disabled", "#eff6ff")])
        style.configure("Danger.TButton", background="#dc2626", foreground="#ffffff", bordercolor="#dc2626", focusthickness=0, padding=(16, 9), font=("Microsoft YaHei UI", 10, "bold"))
        style.map("Danger.TButton", background=[("active", "#b91c1c"), ("disabled", "#fca5a5")])
        style.configure("Ghost.TButton", background="#ffffff", foreground="#334155", bordercolor="#cbd5e1", padding=(14, 8))
        style.map("Ghost.TButton", background=[("active", "#f8fafc")])
        style.configure("TNotebook", background="#eef2f7", borderwidth=0, tabmargins=(2, 0, 2, 0))
        style.configure("TNotebook.Tab", background="#dbe3ee", foreground="#334155", padding=(16, 8), borderwidth=0, font=("Microsoft YaHei UI", 10))
        style.map("TNotebook.Tab", background=[("selected", "#ffffff"), ("active", "#eaf0f7")], foreground=[("selected", "#0f172a")])
        style.configure("Treeview", background="#ffffff", fieldbackground="#ffffff", foreground="#334155", rowheight=28, bordercolor="#e2e8f0", borderwidth=0)
        style.configure("Treeview.Heading", background="#f1f5f9", foreground="#334155", relief="flat", font=("Microsoft YaHei UI", 10, "bold"))
        style.map("Treeview", background=[("selected", "#dbeafe")], foreground=[("selected", "#1e3a8a")])
        style.configure("Horizontal.TProgressbar", troughcolor="#e2e8f0", background="#2563eb", bordercolor="#e2e8f0", lightcolor="#2563eb", darkcolor="#2563eb")

    def _build_ui(self) -> None:
        header = ttk.Frame(self, style="Hero.TFrame", padding=(24, 18, 24, 16))
        header.pack(fill="x", padx=0, pady=0)
        title_row = ttk.Frame(header, style="Hero.TFrame")
        title_row.pack(fill="x")
        title_area = ttk.Frame(title_row, style="Hero.TFrame")
        title_area.pack(side="left", fill="x", expand=True)
        ttk.Label(title_area, text=APP_TITLE, style="HeroTitle.TLabel").pack(anchor="w")
        ttk.Label(
            title_area,
            text="螃蟹在售账号抓取、价值评分、筛选报告、PushPlus 推送和定时任务的一体化控制台",
            style="HeroSub.TLabel",
        ).pack(anchor="w", pady=(5, 0))
        chips = ttk.Frame(title_area, style="Hero.TFrame")
        chips.pack(anchor="w", pady=(10, 0))
        for text in ("B服过滤", "最近7天默认", "详情全量评分", "配置持久化"):
            ttk.Label(chips, text=text, style="Chip.TLabel").pack(side="left", padx=(0, 8))
        self._build_actions(header)

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=18, pady=(14, 10))

        progress_page = ttk.Frame(notebook, padding=(0, 0, 0, 0))
        notebook.add(progress_page, text="运行进度")
        self._build_progress_page(progress_page)

        run_page = ttk.Frame(notebook, padding=(0, 0, 0, 0))
        notebook.add(run_page, text="筛选运行")
        run_page.columnconfigure(0, weight=1)
        run_page.columnconfigure(1, weight=1)
        run_page.rowconfigure(0, weight=1)

        left = self._card(run_page, "运行说明")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        right = self._card(run_page, "筛选条件")
        right.grid(row=0, column=1, sticky="nsew", padx=(8, 0))

        self._build_runtime_form(left)
        self._build_filter_form(right)

        notify_page = ttk.Frame(notebook, padding=(0, 0, 0, 0))
        notebook.add(notify_page, text="推送配置")
        self._build_notify_page(notify_page)

        schedule_page = ttk.Frame(notebook, padding=(0, 0, 0, 0))
        notebook.add(schedule_page, text="定时推送")
        self._build_schedule_page(schedule_page)

        tier_page = ttk.Frame(notebook, padding=(0, 0, 0, 0))
        notebook.add(tier_page, text="角色排行榜")
        self._build_tier_page(tier_page)

        formula_page = ttk.Frame(notebook, padding=(0, 0, 0, 0))
        notebook.add(formula_page, text="公式参数")
        self._build_formula_page(formula_page)

        bottom = ttk.Frame(self, padding=(18, 0, 18, 18))
        bottom.pack(fill="both")
        self._build_log(bottom)

    def _card(self, parent: ttk.Frame, title: str) -> ttk.Frame:
        outer = ttk.Frame(parent, style="Card.TFrame", padding=(16, 14, 16, 16))
        outer.columnconfigure(0, weight=1)
        title_bar = ttk.Frame(outer, style="Card.TFrame")
        title_bar.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        title_bar.columnconfigure(1, weight=1)
        accent = ttk.Frame(title_bar, width=4, height=18)
        accent.configure(style="PrimaryAccent.TFrame")
        accent.grid(row=0, column=0, sticky="nsw", padx=(0, 8))
        ttk.Label(title_bar, text=title, style="CardTitle.TLabel").grid(row=0, column=1, sticky="w")
        return outer

    def _entry(self, parent: ttk.Frame, row: int, key: str, label: str, hint: str = "") -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=5)
        var = self.text_vars.get(key)
        if var is None:
            var = StringVar()
            self.text_vars[key] = var
        ttk.Entry(parent, textvariable=var).grid(row=row, column=1, sticky="ew", pady=5, padx=(8, 0))
        if hint:
            ttk.Label(parent, text=hint, style="Muted.TLabel").grid(row=row, column=2, sticky="w", pady=5, padx=(8, 0))

    def _choice_entry(
        self,
        parent: ttk.Frame,
        row: int,
        key: str,
        label: str,
        button_text: str,
        options_loader: Callable[[], list[str]],
    ) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=5)
        var = StringVar()
        self.text_vars[key] = var
        ttk.Entry(parent, textvariable=var).grid(row=row, column=1, sticky="ew", pady=5, padx=(8, 0))
        ttk.Button(
            parent,
            text=button_text,
            style="Ghost.TButton",
            command=lambda: self._open_multi_select(key, label, options_loader()),
        ).grid(row=row, column=2, sticky="ew", pady=5, padx=(8, 0))

    def _checkbox(self, parent: ttk.Frame, row: int, key: str, label: str) -> None:
        var = BooleanVar(value=False)
        self.bool_vars[key] = var
        ttk.Checkbutton(parent, text=label, variable=var).grid(row=row, column=0, columnspan=3, sticky="w", pady=5)

    def _progress_value(self, key: str, default: str = "-") -> StringVar:
        var = StringVar(value=default)
        self.progress_vars[key] = var
        return var

    def _metric(self, parent: ttk.Frame, row: int, label: str, key: str, default: str = "-") -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=6)
        ttk.Label(parent, textvariable=self._progress_value(key, default), style="MetricValue.TLabel").grid(
            row=row, column=1, sticky="w", pady=6, padx=(10, 0)
        )

    def _build_progress_page(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.columnconfigure(1, weight=1)
        parent.rowconfigure(0, weight=1)

        left = self._card(parent, "实时进度")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        left.columnconfigure(1, weight=1)
        self._metric(left, 1, "当前阶段", "phase", "待开始")
        self._metric(left, 2, "开始时间", "start_time", "-")
        self._metric(left, 3, "已用时间", "elapsed", "00:00:00")
        self._metric(left, 4, "预计剩余", "eta", "-")
        ttk.Separator(left).grid(row=5, column=0, columnspan=2, sticky="ew", pady=8)
        self._metric(left, 6, "列表页数", "list_pages", "0")
        self._metric(left, 7, "列表账号", "list_accounts", "0")
        self._metric(left, 8, "详情候选", "detail_total", "0")
        self._metric(left, 9, "已抓详情", "detail_done", "0")
        self._metric(left, 10, "复用详情", "detail_reused", "0")
        self._metric(left, 11, "详情错误", "detail_errors", "0")

        progress_frame = ttk.Frame(left)
        progress_frame.grid(row=12, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        progress_frame.columnconfigure(0, weight=1)
        self.progress_bar = ttk.Progressbar(progress_frame, mode="determinate", maximum=100, value=0)
        self.progress_bar.grid(row=0, column=0, sticky="ew")
        ttk.Label(progress_frame, textvariable=self._progress_value("progress_percent", "0%"), style="Muted.TLabel").grid(
            row=0, column=1, sticky="e", padx=(10, 0)
        )

        right = self._card(parent, "抓取范围")
        right.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        right.columnconfigure(1, weight=1)
        ttk.Label(
            right,
            text="默认按螃蟹最新上架顺序抓取，直到列表中出现早于该天数的账号；留空表示尝试抓完整在售列表。",
            style="Muted.TLabel",
            wraplength=430,
            justify="left",
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 10))
        self._entry(right, 2, "max_publish_age_days", "从最新开始抓取天数", "默认7；留空=不限")
        self._entry(right, 3, "min_price", "最低价格", "例：200")
        self._entry(right, 4, "max_price", "最高价格", "例：2000")
        ttk.Button(right, text="保存范围设置", style="Primary.TButton", command=self._save_state).grid(
            row=5, column=0, columnspan=3, sticky="ew", pady=(12, 0)
        )
        ttk.Separator(right).grid(row=6, column=0, columnspan=3, sticky="ew", pady=14)
        ttk.Label(
            right,
            text="ETA 进入详情阶段后会更准。列表阶段因为总量未知，只显示已翻页和已发现账号数。",
            style="Muted.TLabel",
            wraplength=430,
            justify="left",
        ).grid(row=7, column=0, columnspan=3, sticky="w")

    def _notify_entry(self, parent: ttk.Frame, row: int, key: str, label: str, hint: str = "", show: str = "") -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=6)
        var = self.notify_vars.get(key)
        if var is None:
            var = StringVar()
            self.notify_vars[key] = var
        ttk.Entry(parent, textvariable=var, show=show, width=42).grid(row=row, column=1, sticky="ew", pady=6, padx=(8, 0))
        if hint:
            ttk.Label(parent, text=hint, style="Muted.TLabel").grid(row=row, column=2, sticky="w", pady=6, padx=(8, 0))

    def _build_notify_page(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.columnconfigure(1, weight=1)
        parent.rowconfigure(0, weight=1)

        left = self._card(parent, "PushPlus 配置")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        left.columnconfigure(1, weight=1)
        ttk.Label(
            left,
            text="每个用户的手机推送 token 都不同。这里保存的是本机私有配置，不会提交到 Git。",
            style="Muted.TLabel",
            wraplength=520,
            justify="left",
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 10))
        self._notify_entry(left, 2, "pushplus_token", "PushPlus Token", "必填；保存到 notify_config.json", show="*")
        self._notify_entry(left, 3, "pushplus_topic", "群组 Topic", "可选；个人推送留空")
        self._notify_entry(left, 4, "pushplus_title", "推送标题", "可自定义手机通知标题")
        buttons = ttk.Frame(left)
        buttons.grid(row=5, column=0, columnspan=3, sticky="ew", pady=(12, 0))
        buttons.columnconfigure(0, weight=1)
        buttons.columnconfigure(1, weight=1)
        ttk.Button(buttons, text="保存推送配置", style="Primary.TButton", command=self._save_notify_state).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(buttons, text="打开 PushPlus", style="Ghost.TButton", command=lambda: webbrowser.open("https://www.pushplus.plus/")).grid(row=0, column=1, sticky="ew", padx=(6, 0))

        right = self._card(parent, "当前状态")
        right.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        ttk.Label(
            right,
            text=(
                "正式推送到手机、定时推送到手机都会读取这里保存的配置。\n\n"
                "如果没有填写 token，程序仍然可以生成本地推送预览，但正式推送会失败。\n\n"
                "分享项目时只提交 notify_config.example.json，不提交 notify_config.json。"
            ),
            style="Muted.TLabel",
            wraplength=480,
            justify="left",
        ).grid(row=1, column=0, sticky="w")

    def _schedule_value(self, key: str, default: str = "-") -> StringVar:
        var = StringVar(value=default)
        self.schedule_vars[key] = var
        return var

    def _schedule_metric(self, parent: ttk.Frame, row: int, label: str, key: str, default: str = "-") -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=6)
        ttk.Label(parent, textvariable=self._schedule_value(key, default), style="MetricValue.TLabel").grid(
            row=row, column=1, sticky="w", pady=6, padx=(10, 0)
        )

    def _build_schedule_page(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.columnconfigure(1, weight=1)
        parent.rowconfigure(0, weight=1)

        left = self._card(parent, "定时规则")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        left.columnconfigure(1, weight=1)
        ttk.Label(
            left,
            text="程序保持打开时生效；到点后会按当前筛选条件完整爬取、评分并推送。若正在运行任务，会跳过本次并计算下一次。",
            style="Muted.TLabel",
            wraplength=470,
            justify="left",
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 10))
        self._checkbox(left, 2, "schedule_enabled", "启用定时推送")

        ttk.Label(left, text="触发方式").grid(row=3, column=0, sticky="w", pady=5)
        mode_var = self.text_vars.get("schedule_mode")
        if mode_var is None:
            mode_var = StringVar()
            self.text_vars["schedule_mode"] = mode_var
        mode_box = ttk.Combobox(
            left,
            textvariable=mode_var,
            values=("interval", "daily"),
            state="readonly",
        )
        mode_box.grid(row=3, column=1, sticky="ew", pady=5, padx=(8, 0))
        ttk.Label(left, text="interval=间隔；daily=每天固定时间", style="Muted.TLabel").grid(row=3, column=2, sticky="w", pady=5, padx=(8, 0))

        self._entry(left, 4, "schedule_interval_minutes", "间隔分钟", "例：120")
        self._entry(left, 5, "schedule_daily_time", "每天时间", "HH:MM，例：09:00")
        self._checkbox(left, 6, "schedule_push", "到点后正式推送到手机")
        ttk.Label(
            left,
            text="如果不勾选“正式推送”，到点只生成推送预览，适合先测试。",
            style="Muted.TLabel",
            wraplength=470,
            justify="left",
        ).grid(row=7, column=0, columnspan=3, sticky="w", pady=(4, 10))

        buttons = ttk.Frame(left)
        buttons.grid(row=8, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        buttons.columnconfigure(0, weight=1)
        buttons.columnconfigure(1, weight=1)
        ttk.Button(buttons, text="保存定时设置", style="Primary.TButton", command=self._save_schedule_state).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(buttons, text="立即按定时规则运行一次", style="Ghost.TButton", command=self._run_schedule_now).grid(row=0, column=1, sticky="ew", padx=(6, 0))

        right = self._card(parent, "定时状态")
        right.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        right.columnconfigure(1, weight=1)
        self._schedule_metric(right, 1, "状态", "schedule_status", "未启用")
        self._schedule_metric(right, 2, "下次运行", "schedule_next", "-")
        self._schedule_metric(right, 3, "倒计时", "schedule_countdown", "-")
        self._schedule_metric(right, 4, "上次触发", "schedule_last", "-")
        self._schedule_metric(right, 5, "运行模式", "schedule_run_mode", "-")
        ttk.Separator(right).grid(row=6, column=0, columnspan=2, sticky="ew", pady=12)
        ttk.Label(
            right,
            text="定时推送不会弹出确认框；如果配置了 PushPlus token 且勾选正式推送，到点会直接发到手机。",
            style="Muted.TLabel",
            wraplength=430,
            justify="left",
        ).grid(row=7, column=0, columnspan=2, sticky="w")

    def _build_runtime_form(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(1, weight=1)
        help_text = (
            "无需设置爬取参数。\n\n"
            "默认从最新发布开始爬取，直到超过右侧“最近发布天数”为止；如果该项留空，则翻完螃蟹当前所有在售账号。\n\n"
            "价格和时间范围内的账号会全部抓详情并评分，不做候选截断；“每组选取”只影响最终报告和推送展示数量。\n\n"
            "先点顶部“开始运行（生成预览）”检查结果；确认后再点“正式推送到手机”。\n\n"
            "PushPlus token 从 notify_config.json 读取，可沿用 cangbaoge 配置。"
        )
        ttk.Label(parent, text=help_text, style="Muted.TLabel", justify="left").grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(4, 0)
        )

    def _build_filter_form(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(1, weight=1)
        self._entry(parent, 1, "min_price", "最低价格", "留空不限")
        self._entry(parent, 2, "max_price", "最高价格", "留空不限")
        self._entry(parent, 3, "max_publish_age_days", "最近发布天数", "例：7，留空不限")
        self._entry(parent, 4, "price_group_step", "每组跨度", "例：100")
        self._entry(parent, 5, "price_group_top_n", "每组选取", "例：5")
        self._entry(parent, 6, "prefilter_group_candidate_limit", "每组详情候选上限", "留空=抓全部")
        ttk.Separator(parent).grid(row=7, column=0, columnspan=3, sticky="ew", pady=10)
        self._entry(parent, 8, "min_total_score", "最低总分", "")
        self._entry(parent, 9, "min_value_score", "最低性价比", "")
        self._entry(parent, 10, "min_five_star_characters", "五星角色不少于", "")
        self._entry(parent, 11, "min_five_star_weapons", "五星武器不少于", "")
        self._entry(parent, 12, "min_effective_pulls", "等效抽数不少于", "")
        self._entry(parent, 13, "min_collectible_score", "饰品分不少于", "")
        self._entry(parent, 14, "max_hot_count", "热度不高于", "")
        ttk.Separator(parent).grid(row=15, column=0, columnspan=3, sticky="ew", pady=10)
        self._choice_entry(parent, 16, "required_characters", "必须有角色", "选择", self._character_options)
        self._choice_entry(parent, 17, "required_weapons", "必须有武器", "选择", self._weapon_options)
        self._choice_entry(parent, 18, "excluded_keywords", "排除关键词", "常用词", self._keyword_options)
        ttk.Separator(parent).grid(row=19, column=0, columnspan=3, sticky="ew", pady=10)
        self._checkbox(parent, 20, "require_bargain", "只看支持议价")
        self._checkbox(parent, 21, "hide_tap_bound", "过滤 TAP 已绑定")
        self._checkbox(parent, 22, "hide_wegame_bound", "过滤 Wegame 已绑定")
        self._checkbox(parent, 23, "hide_change_bind_cd", "过滤存在换绑 CD")
        self._checkbox(parent, 24, "use_list_snapshot", "使用最近完整列表快照")

    def _build_tier_page(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=3)
        parent.columnconfigure(1, weight=2)
        parent.rowconfigure(0, weight=1)

        left = self._card(parent, "角色排行榜")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        left.rowconfigure(2, weight=1)
        left.columnconfigure(0, weight=1)
        ttk.Label(
            left,
            text="调整后会写入 configs/character_tiers.json，下一次评分会直接使用新的梯度和专武映射。",
            style="Muted.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(0, 8))

        table_frame = ttk.Frame(left)
        table_frame.grid(row=2, column=0, sticky="nsew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)
        self.tier_tree = ttk.Treeview(
            table_frame,
            columns=("tier", "name", "multiplier", "version", "role_type", "signature_weapon"),
            show="headings",
            height=18,
        )
        headings = {
            "tier": "梯度",
            "name": "角色",
            "multiplier": "倍率",
            "version": "版本",
            "role_type": "定位",
            "signature_weapon": "专武",
        }
        widths = {
            "tier": 70,
            "name": 120,
            "multiplier": 70,
            "version": 70,
            "role_type": 120,
            "signature_weapon": 150,
        }
        for key, label in headings.items():
            self.tier_tree.heading(key, text=label)
            self.tier_tree.column(key, width=widths[key], anchor="w", stretch=key in {"name", "role_type", "signature_weapon"})
        scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.tier_tree.yview)
        self.tier_tree.configure(yscrollcommand=scroll.set)
        self.tier_tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        self.tier_tree.bind("<<TreeviewSelect>>", lambda _event: self._on_tier_select())

        toolbar = ttk.Frame(left)
        toolbar.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        ttk.Button(toolbar, text="上移", style="Ghost.TButton", command=lambda: self._move_selected_character(-1)).pack(side="left")
        ttk.Button(toolbar, text="下移", style="Ghost.TButton", command=lambda: self._move_selected_character(1)).pack(side="left", padx=(8, 0))
        ttk.Button(toolbar, text="重新读取", style="Ghost.TButton", command=self._load_tier_editor).pack(side="right")
        ttk.Button(toolbar, text="保存排行榜", style="Primary.TButton", command=self._save_tier_editor).pack(side="right", padx=(0, 8))

        right = self._card(parent, "编辑角色")
        right.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        right.columnconfigure(1, weight=1)
        self._tier_entry(right, 1, "name", "角色名")
        ttk.Label(right, text="梯度").grid(row=2, column=0, sticky="w", pady=5)
        tier_var = StringVar()
        self.tier_edit_vars["tier"] = tier_var
        tier_box = ttk.Combobox(right, textvariable=tier_var, values=("T0", "T0.5", "T1", "T2", "T3", "T4"), state="readonly")
        tier_box.grid(row=2, column=1, sticky="ew", pady=5, padx=(8, 0))
        self._tier_entry(right, 3, "multiplier", "梯度倍率")
        self._tier_entry(right, 4, "version", "版本")
        self._tier_entry(right, 5, "role_type", "定位")
        self._tier_entry(right, 6, "signature_weapon", "专武名")
        self._tier_entry(right, 7, "reason", "备注")

        buttons = ttk.Frame(right)
        buttons.grid(row=8, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        ttk.Button(buttons, text="应用到选中角色", style="Primary.TButton", command=self._apply_tier_edit).pack(fill="x", pady=(0, 8))
        ttk.Button(buttons, text="新增角色", style="Ghost.TButton", command=self._add_tier_character).pack(fill="x", pady=(0, 8))
        ttk.Button(buttons, text="删除选中角色", style="Danger.TButton", command=self._delete_tier_character).pack(fill="x")
        ttk.Separator(right).grid(row=9, column=0, columnspan=2, sticky="ew", pady=14)
        ttk.Button(
            right,
            text="打开原网页梯度编辑器",
            style="Ghost.TButton",
            command=lambda: self._open_path(SCRIPT_DIR / "角色梯度编辑器.html"),
        ).grid(row=10, column=0, columnspan=2, sticky="ew")

    def _tier_entry(self, parent: ttk.Frame, row: int, key: str, label: str) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=5)
        var = StringVar()
        self.tier_edit_vars[key] = var
        ttk.Entry(parent, textvariable=var).grid(row=row, column=1, sticky="ew", pady=5, padx=(8, 0))

    def _formula_param(self, parent: ttk.Frame, key: str, width: int = 7) -> ttk.Entry:
        var = self.formula_vars.get(key)
        if var is None:
            var = StringVar()
            self.formula_vars[key] = var
        return ttk.Entry(parent, textvariable=var, width=width)

    def _formula_line(self, parent: ttk.Frame, row: int, parts: list[str | tuple[str, int]]) -> None:
        line = ttk.Frame(parent)
        line.grid(row=row, column=0, sticky="w", pady=5)
        for part in parts:
            if isinstance(part, tuple):
                key, width = part
                self._formula_param(line, key, width).pack(side="left", padx=2)
            else:
                ttk.Label(line, text=part, style="Formula.TLabel").pack(side="left")

    def _build_formula_page(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)

        wrap = ttk.Frame(parent)
        wrap.grid(row=0, column=0, sticky="nsew")
        wrap.columnconfigure(0, weight=1)
        wrap.columnconfigure(1, weight=1)
        wrap.rowconfigure(0, weight=1)
        wrap.rowconfigure(1, weight=1)

        character = self._card(wrap, "角色分公式")
        character.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=(0, 8))
        ttk.Label(
            character,
            text="输入框嵌在公式里；角色梯度值来自“角色排行榜”页。",
            style="FormulaNote.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(0, 8))
        self._formula_line(character, 2, ["角色分 = 角色梯度值 × ( 1 + 命座分 + 专武分 + 配队命中分 )"])
        self._formula_line(
            character,
            3,
            [
                "命座分 = {1命:",
                ("resonance_1", 5),
                ", 2命:",
                ("resonance_2", 5),
                ", 3命:",
                ("resonance_3", 5),
                ", 4命:",
                ("resonance_4", 5),
                ", 5命:",
                ("resonance_5", 5),
                ", 6命:",
                ("resonance_6", 5),
                "}",
            ],
        )
        self._formula_line(
            character,
            4,
            [
                "专武分 = 有专武时 ",
                ("signature_weapon_first_points", 5),
                " + (总精炼 - 1) × ",
                ("signature_weapon_extra_points", 5),
                "；无专武=0",
            ],
        )
        self._formula_line(character, 5, ["配队命中分 = 命中核心二人组时 ", ("team_complete_bonus", 5), "；未命中=0"])

        resource = self._card(wrap, "资源与饰品公式")
        resource.grid(row=1, column=0, sticky="nsew", padx=(0, 8), pady=(8, 0))
        self._formula_line(
            resource,
            1,
            [
                "等效限定抽 = 星声 / ",
                ("astrite_per_pull", 6),
                " + 月相 / ",
                ("lunite_per_pull", 6),
                " + 浮金波纹 + 余波珊瑚 / ",
                ("coral_per_pull", 5),
            ],
        )
        self._formula_line(resource, 2, ["资源分 = 等效限定抽 / ", ("pulls_per_target_character", 6), " × ", ("points_per_target_character", 5)])
        self._formula_line(
            resource,
            3,
            [
                "饰品分 = 等效月相 / ",
                ("astrite_per_pull", 6),
                " / ",
                ("pulls_per_target_character", 6),
                " × ",
                ("points_per_target_character", 5),
            ],
        )
        self._formula_line(resource, 4, ["人民币饰品：等效月相 = 人民币价格 × ", ("lunite_per_rmb", 5)])

        value = self._card(wrap, "性价比公式")
        value.grid(row=0, column=1, rowspan=2, sticky="nsew", padx=(8, 0))
        self._formula_line(
            value,
            1,
            [
                "期望分 = ",
                ("expected_base", 6),
                " × (1 - exp(-((价格 / ",
                ("expected_price_scale", 7),
                ") ^ ",
                ("expected_power", 5),
                ")))",
            ],
        )
        self._formula_line(value, 2, ["超额分 = 账号总分 - 期望分"])
        self._formula_line(value, 3, ["价格效率 = 账号总分 / max(价格, 1) × ", ("efficiency_multiplier", 6)])
        self._formula_line(
            value,
            4,
            [
                "性价比 = clamp(",
                ("value_base", 6),
                " + 超额分 × ",
                ("delta_weight", 5),
                " + min(价格效率, ",
                ("efficiency_cap", 5),
                ") × ",
                ("efficiency_weight", 5),
                ", ",
                ("min_value_score", 5),
                ", ",
                ("max_value_score", 6),
                ")",
            ],
        )
        ttk.Separator(value).grid(row=5, column=0, sticky="ew", pady=14)
        ttk.Button(value, text="保存公式参数", style="Primary.TButton", command=self._save_formula_state).grid(row=6, column=0, sticky="ew", pady=(0, 8))
        ttk.Button(value, text="重新读取公式", style="Ghost.TButton", command=self._load_formula_state).grid(row=7, column=0, sticky="ew")

    def _load_json(self, path: Path, default: dict[str, Any]) -> dict[str, Any]:
        if not path.exists():
            return dict(default)
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            self._log(f"读取 {path.name} 失败：{exc}")
            return dict(default)

    def _write_json(self, path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _float_var(self, key: str, default: float = 0.0) -> float:
        value = self.formula_vars[key].get().strip()
        return default if not value else float(value)

    def _load_formula_state(self) -> None:
        if not self.formula_vars:
            return
        rules = self._load_json(RULES_PATH, {})
        formula = rules.get("formula") or {}
        character = formula.get("character") or {}
        resonance = character.get("resonance_points") or {}
        resource = formula.get("resource") or {}
        collectible = formula.get("collectible") or {}
        value_formula = value_model.load_formula(VALUE_FORMULA_PATH)

        defaults = {
            "signature_weapon_first_points": character.get("signature_weapon_first_points", 0.7),
            "signature_weapon_extra_points": character.get("signature_weapon_extra_points", 0.2),
            "team_complete_bonus": character.get("team_complete_bonus", 0.3),
            "astrite_per_pull": resource.get("astrite_per_pull", 160),
            "lunite_per_pull": resource.get("lunite_per_pull", 160),
            "coral_per_pull": resource.get("coral_per_pull", 8),
            "pulls_per_target_character": resource.get("pulls_per_target_character", 71),
            "points_per_target_character": resource.get("points_per_target_character", 2),
            "lunite_per_rmb": collectible.get("lunite_per_rmb", 20),
            **value_formula,
        }
        for index in range(1, 7):
            defaults[f"resonance_{index}"] = resonance.get(str(index), resonance.get(index, 0))
        for key, var in self.formula_vars.items():
            var.set(str(defaults.get(key, "")))
        self._log("公式参数已读取")

    def _save_formula_state(self) -> None:
        try:
            rules = self._load_json(RULES_PATH, {"version": "v2", "components": {}})
            rules.setdefault("formula", {})
            rules["formula"]["character"] = {
                "resonance_points": {
                    str(index): self._float_var(f"resonance_{index}")
                    for index in range(1, 7)
                },
                "signature_weapon_first_points": self._float_var("signature_weapon_first_points", 0.7),
                "signature_weapon_extra_points": self._float_var("signature_weapon_extra_points", 0.2),
                "team_complete_bonus": self._float_var("team_complete_bonus", 0.3),
            }
            rules["formula"]["resource"] = {
                "astrite_per_pull": self._float_var("astrite_per_pull", 160),
                "lunite_per_pull": self._float_var("lunite_per_pull", 160),
                "coral_per_pull": self._float_var("coral_per_pull", 8),
                "pulls_per_target_character": self._float_var("pulls_per_target_character", 71),
                "points_per_target_character": self._float_var("points_per_target_character", 2),
            }
            rules["formula"]["collectible"] = {
                "astrite_per_pull": self._float_var("astrite_per_pull", 160),
                "lunite_per_rmb": self._float_var("lunite_per_rmb", 20),
                "pulls_per_target_character": self._float_var("pulls_per_target_character", 71),
                "points_per_target_character": self._float_var("points_per_target_character", 2),
            }
            self._write_json(RULES_PATH, rules)

            value_formula = {
                key: self._float_var(key, float(value_model.DEFAULT_VALUE_FORMULA[key]))
                for key in value_model.DEFAULT_VALUE_FORMULA
            }
            self._write_json(VALUE_FORMULA_PATH, {"value_formula": value_formula})
            self._log(f"公式参数已保存：{RULES_PATH}；{VALUE_FORMULA_PATH}")
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"保存公式失败：{exc}")

    def _tier_names(self) -> list[str]:
        tiers = self.tier_data.get("tiers") or {}
        multipliers = self.tier_data.get("tier_multipliers") or {}
        names = list(dict.fromkeys([*multipliers.keys(), *tiers.keys(), "T0", "T0.5", "T1", "T2", "T3", "T4"]))
        return names

    def _load_tier_editor(self) -> None:
        if not hasattr(self, "tier_tree"):
            return
        self.tier_data = self._load_json(
            CHARACTER_TIERS_PATH,
            {"version": "custom", "tier_multipliers": {}, "tiers": {}},
        )
        self._refresh_tier_tree()
        self._log("角色排行榜已读取")

    def _refresh_tier_tree(self) -> None:
        self.tier_tree.delete(*self.tier_tree.get_children())
        tiers = self.tier_data.get("tiers") or {}
        multipliers = self.tier_data.get("tier_multipliers") or {}
        for tier in self._tier_names():
            for index, entry in enumerate(tiers.get(tier) or []):
                iid = f"{tier}::{index}"
                self.tier_tree.insert(
                    "",
                    "end",
                    iid=iid,
                    values=(
                        tier,
                        entry.get("name", ""),
                        multipliers.get(tier, ""),
                        entry.get("version", ""),
                        entry.get("role_type", ""),
                        entry.get("signature_weapon", ""),
                    ),
                )

    def _selected_tier_ref(self) -> tuple[str, int] | None:
        selection = self.tier_tree.selection()
        if not selection:
            return None
        tier, index = selection[0].split("::", 1)
        return tier, int(index)

    def _on_tier_select(self) -> None:
        ref = self._selected_tier_ref()
        if not ref:
            return
        tier, index = ref
        entries = (self.tier_data.get("tiers") or {}).get(tier) or []
        if index >= len(entries):
            return
        entry = entries[index]
        multipliers = self.tier_data.get("tier_multipliers") or {}
        values = {
            "name": entry.get("name", ""),
            "tier": tier,
            "multiplier": multipliers.get(tier, ""),
            "version": entry.get("version", ""),
            "role_type": entry.get("role_type", ""),
            "signature_weapon": entry.get("signature_weapon", ""),
            "reason": entry.get("reason", ""),
        }
        for key, value in values.items():
            if key in self.tier_edit_vars:
                self.tier_edit_vars[key].set(str(value))

    def _entry_from_tier_form(self) -> tuple[str, dict[str, Any], float | None]:
        tier = self.tier_edit_vars["tier"].get().strip()
        if not tier:
            raise ValueError("梯度不能为空")
        name = self.tier_edit_vars["name"].get().strip()
        if not name:
            raise ValueError("角色名不能为空")
        multiplier_text = self.tier_edit_vars["multiplier"].get().strip()
        multiplier = float(multiplier_text) if multiplier_text else None
        entry = {
            "name": name,
            "version": self.tier_edit_vars["version"].get().strip(),
            "role_type": self.tier_edit_vars["role_type"].get().strip(),
            "signature_weapon": self.tier_edit_vars["signature_weapon"].get().strip(),
            "reason": self.tier_edit_vars["reason"].get().strip(),
        }
        return tier, entry, multiplier

    def _apply_tier_edit(self) -> None:
        ref = self._selected_tier_ref()
        if not ref:
            messagebox.showinfo(APP_TITLE, "请先选择一个角色。")
            return
        try:
            new_tier, entry, multiplier = self._entry_from_tier_form()
            old_tier, index = ref
            tiers = self.tier_data.setdefault("tiers", {})
            old_entries = tiers.setdefault(old_tier, [])
            if index >= len(old_entries):
                return
            old_entries.pop(index)
            tiers.setdefault(new_tier, []).append(entry)
            if multiplier is not None:
                self.tier_data.setdefault("tier_multipliers", {})[new_tier] = multiplier
            self._refresh_tier_tree()
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"应用角色修改失败：{exc}")

    def _add_tier_character(self) -> None:
        try:
            tier, entry, multiplier = self._entry_from_tier_form()
            self.tier_data.setdefault("tiers", {}).setdefault(tier, []).append(entry)
            if multiplier is not None:
                self.tier_data.setdefault("tier_multipliers", {})[tier] = multiplier
            self._refresh_tier_tree()
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"新增角色失败：{exc}")

    def _delete_tier_character(self) -> None:
        ref = self._selected_tier_ref()
        if not ref:
            messagebox.showinfo(APP_TITLE, "请先选择一个角色。")
            return
        tier, index = ref
        entries = self.tier_data.setdefault("tiers", {}).setdefault(tier, [])
        if index < len(entries):
            entries.pop(index)
        self._refresh_tier_tree()

    def _move_selected_character(self, direction: int) -> None:
        ref = self._selected_tier_ref()
        if not ref:
            return
        tier, index = ref
        entries = self.tier_data.setdefault("tiers", {}).setdefault(tier, [])
        new_index = index + direction
        if index < 0 or index >= len(entries) or new_index < 0 or new_index >= len(entries):
            return
        entries[index], entries[new_index] = entries[new_index], entries[index]
        self._refresh_tier_tree()
        new_iid = f"{tier}::{new_index}"
        self.tier_tree.selection_set(new_iid)
        self.tier_tree.see(new_iid)

    def _save_tier_editor(self) -> None:
        self._write_json(CHARACTER_TIERS_PATH, self.tier_data)
        try:
            from score_accounts import load_character_tiers

            load_character_tiers.cache_clear()
        except Exception:
            pass
        self._log(f"角色排行榜已保存：{CHARACTER_TIERS_PATH}")

    def _split_selection(self, value: str) -> list[str]:
        normalized = value.replace("，", ",").replace("、", ",")
        return [part.strip() for part in normalized.split(",") if part.strip()]

    def _set_selection(self, key: str, values: list[str]) -> None:
        seen = set()
        merged = []
        for value in values:
            value = value.strip()
            if value and value not in seen:
                seen.add(value)
                merged.append(value)
        self.text_vars[key].set("、".join(merged))

    def _open_multi_select(self, key: str, title: str, options: list[str]) -> None:
        if not options:
            messagebox.showinfo(APP_TITLE, "暂时没有可选项。")
            return

        current = set(self._split_selection(self.text_vars[key].get()))
        dialog = Toplevel(self)
        dialog.title(title)
        dialog.geometry("420x520")
        dialog.transient(self)
        dialog.grab_set()
        dialog.configure(bg="#f4f6f8")

        frame = ttk.Frame(dialog, padding=(14, 14, 14, 10))
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=f"选择{title}", style="CardTitle.TLabel").pack(anchor="w", pady=(0, 8))
        ttk.Label(frame, text="可多选；确定后会自动写入输入框。", style="Sub.TLabel").pack(anchor="w", pady=(0, 8))

        search_var = StringVar()
        search = ttk.Entry(frame, textvariable=search_var)
        search.pack(fill="x", pady=(0, 8))

        list_frame = ttk.Frame(frame)
        list_frame.pack(fill="both", expand=True)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical")
        box = Listbox(
            list_frame,
            selectmode=MULTIPLE,
            activestyle="dotbox",
            exportselection=False,
            height=18,
            font=("Microsoft YaHei UI", 10),
        )
        box.configure(yscrollcommand=scrollbar.set)
        scrollbar.configure(command=box.yview)
        box.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        all_options = sorted({option for option in options if option})
        visible_options: list[str] = []

        def refresh() -> None:
            keyword = search_var.get().strip().lower()
            selected_now = set(box.get(index) for index in box.curselection())
            current.update(selected_now)
            box.delete(0, END)
            visible_options.clear()
            for option in all_options:
                if not keyword or keyword in option.lower():
                    visible_options.append(option)
                    box.insert(END, option)
                    if option in current:
                        box.selection_set(END)

        def confirm() -> None:
            selected = [box.get(index) for index in box.curselection()]
            existing = self._split_selection(self.text_vars[key].get())
            self._set_selection(key, existing + selected)
            dialog.destroy()

        def clear() -> None:
            self.text_vars[key].set("")
            dialog.destroy()

        search_var.trace_add("write", lambda *_: refresh())
        refresh()

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(10, 0))
        ttk.Button(buttons, text="确定", style="Primary.TButton", command=confirm).pack(side="left")
        ttk.Button(buttons, text="清空", style="Ghost.TButton", command=clear).pack(side="left", padx=(8, 0))
        ttk.Button(buttons, text="取消", style="Ghost.TButton", command=dialog.destroy).pack(side="right")
        search.focus_set()

    def _character_options(self) -> list[str]:
        names: set[str] = set()
        tier_path = SCRIPT_DIR / "configs" / "character_tiers.json"
        if tier_path.exists():
            try:
                data = json.loads(tier_path.read_text(encoding="utf-8"))
                for entries in (data.get("tiers") or {}).values():
                    for entry in entries or []:
                        if entry.get("name"):
                            names.add(str(entry["name"]))
            except Exception as exc:
                self._log(f"读取角色选项失败：{exc}")
        raw_path = SCRIPT_DIR / "data" / "accounts_raw.json"
        if raw_path.exists():
            try:
                data = json.loads(raw_path.read_text(encoding="utf-8"))
                for account in data.get("items") or []:
                    for item in account.get("characters") or []:
                        if item.get("name"):
                            names.add(str(item["name"]))
            except Exception:
                pass
        return sorted(names)

    def _weapon_options(self) -> list[str]:
        names: set[str] = set()
        tier_path = SCRIPT_DIR / "configs" / "character_tiers.json"
        if tier_path.exists():
            try:
                data = json.loads(tier_path.read_text(encoding="utf-8"))
                for entries in (data.get("tiers") or {}).values():
                    for entry in entries or []:
                        weapon = str(entry.get("signature_weapon") or "").strip()
                        if weapon and weapon != "待补充":
                            names.add(weapon)
            except Exception as exc:
                self._log(f"读取武器选项失败：{exc}")
        raw_path = SCRIPT_DIR / "data" / "accounts_raw.json"
        if raw_path.exists():
            try:
                data = json.loads(raw_path.read_text(encoding="utf-8"))
                for account in data.get("items") or []:
                    for item in account.get("weapons") or []:
                        if item.get("name"):
                            names.add(str(item["name"]))
            except Exception:
                pass
        return sorted(names)

    def _keyword_options(self) -> list[str]:
        return [
            "B服",
            "自抽",
            "初始号",
            "科技",
            "脚本",
            "无包赔",
            "自主截图",
            "不可议价",
            "找回",
            "换绑CD",
        ]

    def _build_actions(self, parent: ttk.Frame) -> None:
        bar = ttk.Frame(parent, style="ActionBar.TFrame")
        bar.pack(fill="x", pady=(16, 0))
        self.preview_button = ttk.Button(bar, text="开始运行（生成预览）", style="Primary.TButton", command=lambda: self._start(push=False))
        self.preview_button.pack(side="left", padx=(0, 8))
        self.push_button = ttk.Button(bar, text="正式推送到手机", style="Danger.TButton", command=lambda: self._start(push=True))
        self.push_button.pack(side="left", padx=(0, 8))
        ttk.Button(bar, text="保存筛选条件", style="Ghost.TButton", command=self._save_state).pack(side="left", padx=(0, 8))
        ttk.Button(bar, text="保存全部配置", style="Ghost.TButton", command=self._save_all_settings).pack(side="left", padx=(0, 8))
        ttk.Button(bar, text="打开推送预览", style="Ghost.TButton", command=lambda: self._open_path(PUSH_PREVIEW)).pack(side="right", padx=(8, 0))
        ttk.Button(bar, text="打开筛选报告", style="Ghost.TButton", command=lambda: self._open_path(REPORT_OUTPUT)).pack(side="right", padx=(8, 0))

    def _build_log(self, parent: ttk.Frame) -> None:
        log_frame = ttk.Frame(parent, style="Card.TFrame", padding=(12, 10, 12, 12))
        log_frame.pack(fill="both", expand=True)
        ttk.Label(log_frame, text="运行日志", style="CardTitle.TLabel").pack(anchor="w", pady=(0, 6))
        self.log = ttk.Treeview(log_frame, columns=("time", "message"), show="headings", height=8)
        self.log.heading("time", text="时间")
        self.log.heading("message", text="消息")
        self.log.column("time", width=90, anchor="center", stretch=False)
        self.log.column("message", width=900, anchor="w")
        self.log.pack(fill="both", expand=True)

    def _load_state(self) -> None:
        state = dict(DEFAULT_STATE)
        if CONFIG_PATH.exists():
            try:
                state.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
            except Exception as exc:
                self._log(f"读取配置失败，使用默认值：{exc}")
        for key, value in state.items():
            if key in self.text_vars:
                self.text_vars[key].set(str(value))
            elif key in self.bool_vars:
                self.bool_vars[key].set(bool(value))

    def _load_notify_state(self) -> None:
        state = dict(DEFAULT_NOTIFY_STATE)
        if NOTIFY_CONFIG_PATH.exists():
            try:
                state.update(json.loads(NOTIFY_CONFIG_PATH.read_text(encoding="utf-8")))
            except Exception as exc:
                self._log(f"读取推送配置失败，使用默认值：{exc}")
        for key, value in state.items():
            if key in self.notify_vars:
                self.notify_vars[key].set(str(value or ""))

    def _collect_state(self) -> dict[str, Any]:
        state: dict[str, Any] = {}
        for key, var in self.text_vars.items():
            state[key] = var.get().strip()
        for key, var in self.bool_vars.items():
            state[key] = bool(var.get())
        return state

    def _collect_notify_state(self) -> dict[str, str]:
        return {key: var.get().strip() for key, var in self.notify_vars.items()}

    def _save_state(self) -> None:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(self._collect_state(), ensure_ascii=False, indent=2), encoding="utf-8")
        self._log(f"筛选条件已保存：{CONFIG_PATH}")

    def _save_notify_state(self) -> None:
        data = self._collect_notify_state()
        NOTIFY_CONFIG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        token = data.get("pushplus_token") or ""
        status = "已配置 token" if token else "未配置 token，仅可生成预览"
        self._log(f"推送配置已保存：{NOTIFY_CONFIG_PATH}（{status}）")

    def _save_all_settings(self) -> None:
        self._save_state()
        self._save_notify_state()
        self._save_formula_state()
        self._save_tier_editor()
        self._recompute_schedule("保存全部配置")
        self._log("全部配置已保存")

    def _as_int(self, key: str, default: int) -> int:
        value = self.text_vars[key].get().strip()
        return default if not value else int(float(value))

    def _as_float(self, key: str, default: float) -> float:
        value = self.text_vars[key].get().strip()
        return default if not value else float(value)

    def _format_seconds(self, seconds: float | None) -> str:
        if seconds is None or seconds < 0:
            return "-"
        total = int(seconds)
        hours, rem = divmod(total, 3600)
        minutes, secs = divmod(rem, 60)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"

    def _set_schedule_status(self, key: str, value: Any) -> None:
        var = self.schedule_vars.get(key)
        if var is not None:
            var.set(str(value))

    def _schedule_bool(self, key: str) -> bool:
        var = self.bool_vars.get(key)
        return bool(var.get()) if var is not None else bool(DEFAULT_STATE.get(key))

    def _schedule_text(self, key: str) -> str:
        var = self.text_vars.get(key)
        return var.get().strip() if var is not None else str(DEFAULT_STATE.get(key) or "")

    def _parse_daily_time(self, value: str) -> tuple[int, int]:
        match = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", value or "")
        if not match:
            raise ValueError("每天时间必须是 HH:MM，例如 09:00")
        hour = int(match.group(1))
        minute = int(match.group(2))
        if hour > 23 or minute > 59:
            raise ValueError("每天时间必须在 00:00 到 23:59 之间")
        return hour, minute

    def _compute_next_schedule_time(self, now: datetime | None = None) -> datetime | None:
        if not self._schedule_bool("schedule_enabled"):
            return None
        now = now or datetime.now()
        mode = self._schedule_text("schedule_mode") or "interval"
        if mode == "daily":
            hour, minute = self._parse_daily_time(self._schedule_text("schedule_daily_time"))
            candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if candidate <= now:
                candidate += timedelta(days=1)
            return candidate
        minutes_text = self._schedule_text("schedule_interval_minutes") or "120"
        minutes = float(minutes_text)
        if minutes <= 0:
            raise ValueError("间隔分钟必须大于 0")
        return now + timedelta(minutes=minutes)

    def _schedule_mode_text(self) -> str:
        mode = self._schedule_text("schedule_mode") or "interval"
        action = "正式推送" if self._schedule_bool("schedule_push") else "生成预览"
        if mode == "daily":
            return f"每天 {self._schedule_text('schedule_daily_time')}，{action}"
        return f"每 {self._schedule_text('schedule_interval_minutes')} 分钟，{action}"

    def _recompute_schedule(self, reason: str = "") -> None:
        try:
            self.next_schedule_time = self._compute_next_schedule_time()
            if self.next_schedule_time:
                self._set_schedule_status("schedule_status", "已启用")
                self._set_schedule_status("schedule_next", self.next_schedule_time.strftime("%Y-%m-%d %H:%M:%S"))
                self._set_schedule_status("schedule_run_mode", self._schedule_mode_text())
                if reason:
                    self._set_schedule_status("schedule_last", f"{reason}：{time.strftime('%H:%M:%S')}")
            else:
                self._set_schedule_status("schedule_status", "未启用")
                self._set_schedule_status("schedule_next", "-")
                self._set_schedule_status("schedule_countdown", "-")
                self._set_schedule_status("schedule_run_mode", "-")
        except Exception as exc:
            self.next_schedule_time = None
            self._set_schedule_status("schedule_status", f"设置错误：{exc}")
            self._set_schedule_status("schedule_next", "-")
            self._set_schedule_status("schedule_countdown", "-")
            self._set_schedule_status("schedule_run_mode", "-")

    def _save_schedule_state(self) -> None:
        self._save_state()
        self._recompute_schedule("保存定时设置")
        self._log("定时推送设置已保存")

    def _run_schedule_now(self) -> None:
        push = self._schedule_bool("schedule_push")
        if self._start(push=push, confirm=False, source="定时设置立即运行"):
            self._set_schedule_status("schedule_last", "手动触发：" + time.strftime("%H:%M:%S"))

    def _set_progress(self, key: str, value: Any) -> None:
        var = self.progress_vars.get(key)
        if var is not None:
            var.set(str(value))

    def _reset_progress(self) -> None:
        self.progress_start_time = time.time()
        self.detail_start_time = None
        self.detail_total = 0
        self.detail_done = 0
        self.detail_reused = 0
        self.detail_errors = 0
        self._set_progress("phase", "准备开始")
        self._set_progress("start_time", time.strftime("%H:%M:%S"))
        self._set_progress("elapsed", "00:00:00")
        self._set_progress("eta", "估算中")
        self._set_progress("list_pages", "0")
        self._set_progress("list_accounts", "0")
        self._set_progress("detail_total", "0")
        self._set_progress("detail_done", "0")
        self._set_progress("detail_reused", "0")
        self._set_progress("detail_errors", "0")
        self._set_progress("progress_percent", "0%")
        if hasattr(self, "progress_bar"):
            self.progress_bar.configure(value=0)

    def _update_detail_progress(self) -> None:
        total_done = self.detail_done + self.detail_reused
        total = max(self.detail_total, 0)
        self._set_progress("detail_done", total_done)
        self._set_progress("detail_reused", self.detail_reused)
        self._set_progress("detail_errors", self.detail_errors)
        self._set_progress("detail_total", total)
        if total > 0:
            percent = min(100, round(total_done / total * 100, 1))
            if hasattr(self, "progress_bar"):
                self.progress_bar.configure(value=percent)
            self._set_progress("progress_percent", f"{percent:g}%")
            active_done = max(self.detail_done, 0)
            if self.detail_start_time and active_done > 0 and total_done < total:
                elapsed = max(time.time() - self.detail_start_time, 0.1)
                rate = active_done / elapsed
                remaining = max(total - total_done, 0) / max(rate, 0.001)
                self._set_progress("eta", self._format_seconds(remaining))
            elif total_done >= total:
                self._set_progress("eta", "00:00:00")

    def _parse_progress_message(self, message: str) -> None:
        if message.startswith("开始爬取"):
            self._set_progress("phase", "爬取列表")
            self._set_progress("eta", "估算中")
            return

        match = re.search(r"List page (\d+): .*total unique (\d+)", message)
        if match:
            self._set_progress("phase", "爬取列表")
            self._set_progress("list_pages", match.group(1))
            self._set_progress("list_accounts", match.group(2))
            self._set_progress("eta", "估算中")
            return

        match = re.search(r"List checkpoint: resume page (\d+), total unique (\d+)", message)
        if match:
            self._set_progress("phase", "恢复列表")
            self._set_progress("list_pages", match.group(1))
            self._set_progress("list_accounts", match.group(2))
            return

        match = re.search(r"List snapshot: use last complete list with (\d+) accounts", message)
        if match:
            self._set_progress("phase", "使用列表快照")
            self._set_progress("list_accounts", match.group(1))
            return

        match = re.search(r"List prefilter: (\d+) -> (\d+) detail candidates, removed (\d+)", message)
        if match:
            self._set_progress("phase", "准备详情")
            self._set_progress("list_accounts", match.group(1))
            self.detail_total = int(match.group(2))
            self._set_progress("detail_total", self.detail_total)
            self._update_detail_progress()
            return

        match = re.search(r"Detail checkpoint: reuse (\d+) ok, (\d+) errors", message)
        if match:
            self.detail_reused = int(match.group(1))
            self.detail_errors = int(match.group(2))
            self._set_progress("phase", "复用详情缓存")
            self._update_detail_progress()
            return

        match = re.search(r"Detail workers: \d+; pending (\d+) / (\d+)", message)
        if match:
            pending = int(match.group(1))
            self.detail_total = int(match.group(2))
            self.detail_reused = max(self.detail_total - pending, self.detail_reused)
            self.detail_start_time = time.time()
            self._set_progress("phase", "爬取详情")
            self._update_detail_progress()
            return

        if message.startswith("Detail ") and (" ok" in message or " error " in message):
            if self.detail_start_time is None:
                self.detail_start_time = time.time()
            self.detail_done += 1
            if " error " in message:
                self.detail_errors += 1
            self._set_progress("phase", "爬取详情")
            self._update_detail_progress()
            return

        if message.startswith("爬取完成"):
            self._set_progress("phase", "评分中")
            self._set_progress("eta", "估算中")
            return

        if message.startswith("性价比完成") or message.startswith("筛选完成") or message.startswith("生成HTML"):
            self._set_progress("phase", "生成结果")
            self._set_progress("eta", "估算中")
            return

        if message.startswith("完成："):
            self._set_progress("phase", "完成")
            self._set_progress("eta", "00:00:00")
            if hasattr(self, "progress_bar") and self.detail_total:
                self.progress_bar.configure(value=100)
                self._set_progress("progress_percent", "100%")

    def _start(self, push: bool, confirm: bool = True, source: str = "手动运行") -> bool:
        if self.worker and self.worker.is_alive():
            if confirm:
                messagebox.showinfo(APP_TITLE, "当前任务还在运行，请稍等。")
            else:
                self._log(f"{source}跳过：当前任务还在运行")
            return False
        if push and confirm and not messagebox.askyesno(APP_TITLE, "确认现在爬取、筛选并正式推送到手机吗？"):
            return False
        try:
            top_per_segment = self._as_int("price_group_top_n", 5)
        except ValueError as exc:
            if confirm:
                messagebox.showerror(APP_TITLE, f"参数格式不正确：{exc}")
            else:
                self._log(f"{source}失败：参数格式不正确：{exc}")
            return False

        state = self._collect_state()
        self._save_state()
        self._reset_progress()
        self._set_running(True)
        self._log(f"{source}已启动：" + ("正式推送" if push else "生成预览"))
        self.worker = threading.Thread(
            target=self._run_pipeline,
            kwargs={
                "push": push,
                "top_per_segment": top_per_segment,
                "filters": state,
            },
            daemon=True,
        )
        self.worker.start()
        return True

    def _run_pipeline(
        self,
        push: bool,
        top_per_segment: int,
        filters: dict[str, Any],
    ) -> None:
        old_safe_print = batch_scorer.safe_print
        batch_scorer.safe_print = self._thread_log
        try:
            self._thread_log("开始爬取商品列表与详情")
            batch = batch_scorer.run(
                pages=0,
                page_size=DEFAULT_PAGE_SIZE,
                limit=0,
                list_delay=2.0,
                detail_delay=0.2,
                raw_output=RAW_OUTPUT,
                score_output=SCORE_OUTPUT,
                rules=RULES_PATH if RULES_PATH.exists() else DEFAULT_RULES,
                top_n=top_per_segment,
                fetch_all=True,
                detail_workers=6,
                filters=filters,
                use_complete_list_snapshot=bool(filters.get("use_list_snapshot")),
            )
            source = batch["raw"].get("source") or {}
            self._thread_log(
                "列表完成：来源=%s，全量%s个，详情候选%s个，列表预筛剔除%s个"
                % (
                    source.get("list_source") or "unknown",
                    source.get("list_accounts"),
                    source.get("detail_candidates"),
                    source.get("prefilter_removed_count"),
                )
            )
            self._thread_log(
                "爬取完成：详情%s个，错误%s个，评分%s个"
                % (
                    batch["raw"]["total_accounts"],
                    batch["raw"]["error_count"],
                    batch["scored"]["total_accounts"],
                )
            )

            self._thread_log("计算性价比")
            value = value_model.run(SCORE_OUTPUT, VALUE_OUTPUT, top_per_segment, VALUE_FORMULA_PATH)
            self._thread_log(f"性价比完成：{value['total_accounts']}个")

            self._thread_log("应用筛选条件")
            filtered = filter_results.run(VALUE_OUTPUT, FILTERED_OUTPUT, filters)
            self._thread_log(
                "筛选完成：保留%s个，剔除%s个"
                % (filtered["total_accounts"], len(filtered.get("filtered_out") or []))
            )

            self._thread_log("生成HTML报告")
            report.run(FILTERED_OUTPUT, REPORT_OUTPUT)

            self._thread_log("生成推送内容" + ("并正式推送" if push else "预览"))
            ok = notify.run(
                input_path=FILTERED_OUTPUT,
                preview_path=PUSH_PREVIEW,
                top_n=top_per_segment,
                per_segment=top_per_segment,
                dry_run=not push,
            )
            if not ok:
                raise RuntimeError("PushPlus返回失败")
            self._thread_log("完成：" + ("已推送到手机" if push else "已生成推送预览"))
        except Exception:
            self._thread_log("任务失败：\n" + traceback.format_exc())
        finally:
            batch_scorer.safe_print = old_safe_print
            self.log_queue.put("__DONE__")

    def _set_running(self, running: bool) -> None:
        state = "disabled" if running else "normal"
        self.preview_button.configure(state=state)
        self.push_button.configure(state=state)

    def _thread_log(self, message: str) -> None:
        self.log_queue.put(message)

    def _log(self, message: str) -> None:
        self._parse_progress_message(message)
        timestamp = time.strftime("%H:%M:%S")
        self.log.insert("", "end", values=(timestamp, message))
        rows = self.log.get_children()
        if len(rows) > 200:
            self.log.delete(rows[0])
        self.log.see(rows[-1] if rows else "")

    def _tick_progress(self) -> None:
        if self.progress_start_time:
            self._set_progress("elapsed", self._format_seconds(time.time() - self.progress_start_time))
            if self.worker and self.worker.is_alive():
                self._update_detail_progress()
        self.after(1000, self._tick_progress)

    def _tick_schedule(self) -> None:
        try:
            if self._schedule_bool("schedule_enabled"):
                if self.next_schedule_time is None:
                    self._recompute_schedule()
                now = datetime.now()
                if self.next_schedule_time:
                    remaining = (self.next_schedule_time - now).total_seconds()
                    self._set_schedule_status("schedule_countdown", self._format_seconds(max(remaining, 0)))
                    if remaining <= 0:
                        push = self._schedule_bool("schedule_push")
                        if self.worker and self.worker.is_alive():
                            self._set_schedule_status("schedule_last", "跳过：任务运行中 " + time.strftime("%H:%M:%S"))
                            self._log("定时推送跳过：当前已有任务运行")
                            self._recompute_schedule("跳过本轮")
                        else:
                            started = self._start(push=push, confirm=False, source="定时推送")
                            self._set_schedule_status(
                                "schedule_last",
                                ("已触发：" if started else "触发失败：") + time.strftime("%H:%M:%S"),
                            )
                            self._recompute_schedule("已安排下一次")
            else:
                if self.next_schedule_time is not None:
                    self.next_schedule_time = None
                self._set_schedule_status("schedule_status", "未启用")
                self._set_schedule_status("schedule_next", "-")
                self._set_schedule_status("schedule_countdown", "-")
                self._set_schedule_status("schedule_run_mode", "-")
        except Exception as exc:
            self.next_schedule_time = None
            self._set_schedule_status("schedule_status", f"设置错误：{exc}")
            self._set_schedule_status("schedule_countdown", "-")
        self.after(1000, self._tick_schedule)

    def _drain_log_queue(self) -> None:
        while True:
            try:
                message = self.log_queue.get_nowait()
            except queue.Empty:
                break
            if message == "__DONE__":
                self._set_running(False)
            else:
                self._log(message)
        self.after(120, self._drain_log_queue)

    def _open_path(self, path: Path) -> None:
        if not path.exists():
            messagebox.showinfo(APP_TITLE, f"文件还不存在：{path}")
            return
        webbrowser.open(path.resolve().as_uri())

    def _on_close(self) -> None:
        try:
            self._save_state()
        except Exception:
            pass
        self.destroy()


def main() -> None:
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
