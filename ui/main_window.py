"""
Main application window for translation application
"""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import os
import re
import time
from datetime import datetime
from typing import Optional
from PIL import Image, ImageGrab, ImageTk
import threading

from translation_app.core.translator import TranslationService
from translation_app.core.file_handlers.excel_handler import ExcelHandler
from translation_app.core.file_handlers.word_handler import WordHandler
from translation_app.core.file_handlers.powerpoint_handler import PowerPointHandler
from translation_app.core.file_handlers.pdf_handler import PDFHandler
from translation_app.core.file_handlers.pdf_regression_report import (
    build_pdf_regression_report_bundle,
    export_pdf_regression_report_html,
    export_pdf_regression_report_json,
)
from translation_app.core.file_handlers.text_handler import TextHandler
from translation_app.core.email_handler import EmailHandler
from translation_app.core.ocr_handler import get_ocr_handler
from translation_app.ui.theme import setup_theme
from translation_app.ui.components import create_styled_button, create_language_combobox
from translation_app.utils.validators import FileValidator, LanguageValidator
from translation_app.utils.error_handler import FileProcessingError, handle_translation_error
from translation_app.utils.logger import logger
from translation_app.config import config


class MainWindow(tk.Tk):
    """Main application window"""
    
    def __init__(self):
        """Initialize main window"""
        super().__init__()

        # Initialize services
        self.translation_service = TranslationService()
        self.excel_handler = ExcelHandler(self.translation_service)
        self.word_handler = WordHandler(self.translation_service)
        self.powerpoint_handler = PowerPointHandler(self.translation_service)
        self.pdf_handler = PDFHandler(self.translation_service)
        self.text_handler = TextHandler(self.translation_service)
        self.email_handler = EmailHandler(self.translation_service)
        self.ocr_handler = get_ocr_handler()

        # Core Managers & Config
        from translation_app.core.ai_service import get_ai_service
        from translation_app.core.translation_job import get_translation_job_manager
        from translation_app.core.translation_memory import get_tm_manager
        
        self.config_manager = get_ai_service().config_manager
        self.job_manager = get_translation_job_manager()
        self.tm_manager = get_tm_manager()

        # Advanced config variables for bindings
        self.use_tm_var = tk.BooleanVar(value=self.config_manager.use_translation_memory)
        self.min_seg_len_var = tk.StringVar(value=str(self.config_manager.min_segment_length_to_cache))
        self.use_glossary_var = tk.BooleanVar(value=self.config_manager.use_glossary)
        self.max_glossary_terms_var = tk.StringVar(value=str(self.config_manager.max_glossary_terms_per_segment))
        self.glossary_level_var = tk.StringVar(value=self.config_manager.glossary_enforcement_level)
        self.use_router_var = tk.BooleanVar(value=self.config_manager.use_provider_router)
        self.router_policy_var = tk.StringVar(value=self.config_manager.provider_router_policy)
        self.auto_refresh_provider_models_var = tk.BooleanVar(value=self.config_manager.auto_refresh_provider_models)

        # Background model catalog refresh tracking
        self._provider_model_refresh_inflight = set()
        self._provider_model_auto_refresh_attempted = set()
        self._provider_model_auto_refresh_queue = []
        self._provider_model_auto_refresh_running = False
        self._provider_model_refresh_queue_results = []
        self._provider_model_poll_after_ids = set()
        self._auto_refresh_after_id = None

        # Filter out backward compatibility keys for cleaner UI
        # Keep 'auto' for auto-detect, filter out zh-cn/zh-tw variations
        self.display_languages = {k: v for k, v in config.supported_languages.items()
                                if k == 'auto' or (not k.startswith(('zh-cn', 'zh-tw')) or k in ['zh-CN', 'zh-TW'])}

        # Clipboard image for paste functionality
        self.clipboard_image: Optional[Image.Image] = None
        self.preview_photo: Optional[ImageTk.PhotoImage] = None
        self._preview_photo_refs: list = []  # Lưu references để tránh garbage collection
        self.last_ocr_text: str = "" # To store OCR result for analysis
        self.last_pdf_report_input_file: Optional[str] = None
        self.last_pdf_report_output_file: Optional[str] = None

        # Setup UI
        self.setup_window()
        self.setup_theme()
        self.create_widgets()
        
        logger.info("Main window initialized")
    
    def setup_window(self):
        """Setup window properties"""
        from translation_app import __version__
        self.title(f"Dịch tự động v{__version__} - Bùi Đức Vinh - Phòng phát triển hệ thống chế tạo")
        self.geometry("720x750")

    
    def setup_theme(self):
        """Setup theme and colors"""
        self.colors, self.style = setup_theme()
        self.configure(bg=self.colors['gray_light'])
    
    def create_widgets(self):
        """Create all UI widgets"""
        # Create notebook for tabs
        self.notebook = ttk.Notebook(self, style='TNotebook')
        
        # Create tabs
        self.tab_file = tk.Frame(self.notebook, bg=self.colors['gray_light'])
        self.tab_paragraph = tk.Frame(self.notebook, bg=self.colors['gray_light'])
        self.tab_email = tk.Frame(self.notebook, bg=self.colors['gray_light'])
        self.tab_image = tk.Frame(self.notebook, bg=self.colors['gray_light'])
        self.tab_jobs = tk.Frame(self.notebook, bg=self.colors['gray_light'])
        self.tab_glossary = tk.Frame(self.notebook, bg=self.colors['gray_light'])
        self.tab_tm = tk.Frame(self.notebook, bg=self.colors['gray_light'])
        self.tab_ai = tk.Frame(self.notebook, bg=self.colors['gray_light'])
        
        self.notebook.add(self.tab_file, text="Dịch file")
        self.notebook.add(self.tab_paragraph, text="Dịch văn bản")
        self.notebook.add(self.tab_email, text="Dịch email")
        self.notebook.add(self.tab_image, text="Dịch ảnh")
        self.notebook.add(self.tab_jobs, text="Công việc")
        self.notebook.add(self.tab_glossary, text="Thuật ngữ")
        self.notebook.add(self.tab_tm, text="Bộ nhớ dịch")
        self.notebook.add(self.tab_ai, text="Cấu hình AI")
        
        self.notebook.pack(expand=True, fill="both", padx=5, pady=5)
        
        # Setup each tab
        self.setup_file_tab()
        self.setup_paragraph_tab()
        self.setup_email_tab()
        self.setup_image_tab()
        self.setup_ai_tab()
        self.setup_jobs_tab()
        self.setup_glossary_tab()
        self.setup_tm_tab()

        # Connect Strategy ComboBox to Translation Service
        self.strat_var.trace_add("write", self._on_strategy_changed)

        # Notebook tab selection binding
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        # Schedule background refresh after UI is fully initialized and ready
        self._auto_refresh_after_id = self.after(100, self._auto_refresh_provider_models_on_startup)
        
        # Start polling for background model discovery queue results
        self.after(50, self._poll_provider_model_refresh_results)
    
    def _on_strategy_changed(self, *args):
        """Update translation strategy when ComboBox changes"""
        new_strat = self.strat_var.get()
        self.translation_service.set_strategy(new_strat)

    def _on_tab_changed(self, event=None):
        """Handle notebook tab switch to trigger auto refresh when opening AI config tab."""
        if not self.winfo_exists():
            return
        selected_tab = self.notebook.select()
        if not selected_tab:
            return
        # Switch tab index matches tab_ai
        try:
            if self.notebook.index(selected_tab) == self.notebook.index(self.tab_ai):
                self._auto_refresh_provider_models_on_startup()
        except Exception:
            pass
    
    def setup_ai_tab(self):
        """Setup the AI Configuration tab with Unified Provider settings."""
        # Main Canvas + Scrollbar
        canvas = tk.Canvas(self.tab_ai, bg=self.colors['gray_light'], highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.tab_ai, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg=self.colors['gray_light'])

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw", width=700)
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # Header
        label_title = tk.Label(
            scrollable_frame, text="⚙️ Cấu hình Dịch thuật & AI",
            bg=self.colors['gray_light'], fg=self.colors['navy'],
            font=('Segoe UI', 16, 'bold')
        )
        label_title.pack(pady=(15, 10))

        # --- PHẦN A: CẤU HÌNH NHANH ---
        frame_quick = tk.LabelFrame(
            scrollable_frame, text="⚡ Cấu hình nhanh",
            bg=self.colors['gray_light'], fg=self.colors['navy'],
            font=('Segoe UI', 10, 'bold'), padx=15, pady=10
        )
        frame_quick.pack(fill=tk.X, padx=20, pady=5)

        # Smart Router Checkbox
        chk_router = tk.Checkbutton(
            frame_quick, text="Bật bộ định tuyến AI thông minh (Smart Router)",
            variable=self.use_router_var, bg=self.colors['gray_light'],
            fg=self.colors['gray_dark'], font=('Segoe UI', 9, 'bold'),
            activebackground=self.colors['gray_light'],
            command=self._on_quick_router_toggled
        )
        chk_router.pack(anchor=tk.W, pady=(0, 5))
        
        lbl_router_desc = tk.Label(
            frame_quick, text="💡 Tự động chọn AI dịch tốt nhất tại thời điểm dịch, tối ưu tốc độ và chi phí.",
            bg=self.colors['gray_light'], fg=self.colors['gray_medium'],
            font=('Segoe UI', 8, 'italic')
        )
        lbl_router_desc.pack(anchor=tk.W, pady=(0, 10))

        # Mode Selection Combobox
        frame_mode_row = tk.Frame(frame_quick, bg=self.colors['gray_light'])
        frame_mode_row.pack(fill=tk.X, pady=5)
        
        tk.Label(frame_mode_row, text="Chế độ dịch:", bg=self.colors['gray_light'], font=('Segoe UI', 9)).pack(side=tk.LEFT)
        
        # Map current strategy to display string
        current_strategy = self.translation_service.strategy
        strategy_display_map = {
            "waterfall": "Tự động chọn AI tốt nhất",
            "ai": "Chỉ dùng AI, không dùng Google Translate",
            "gemini_only": "Chỉ dùng Gemini",
            "chatanywhere_only": "Chỉ dùng ChatAnyWhere",
            "deepseek_only": "Chỉ dùng DeepSeek",
            "nvidia_nim_only": "Chỉ dùng NVIDIA NIM",
            "openai_compatible_only": "Chỉ dùng OpenAI tùy chỉnh",
            "google": "Chỉ dùng Google Translate",
            "ai_waterfall": "Nâng cao: dùng thứ tự ưu tiên bên dưới"
        }
        initial_display_val = strategy_display_map.get(current_strategy, "Tự động chọn AI tốt nhất")
        
        self.strat_var = tk.StringVar(value=initial_display_val)
        self.strat_combo = ttk.Combobox(
            frame_mode_row, textvariable=self.strat_var, values=[
                "Tự động chọn AI tốt nhất",
                "Chỉ dùng AI, không dùng Google Translate",
                "Chỉ dùng Gemini",
                "Chỉ dùng ChatAnyWhere",
                "Chỉ dùng DeepSeek",
                "Chỉ dùng NVIDIA NIM",
                "Chỉ dùng OpenAI tùy chỉnh",
                "Chỉ dùng Google Translate",
                "Nâng cao: dùng thứ tự ưu tiên bên dưới"
            ], state="readonly", width=40
        )
        self.strat_combo.pack(side=tk.LEFT, padx=10)
        
        lbl_mode_rec = tk.Label(
            frame_mode_row, text="💡 Khuyến nghị: Tự động chọn AI tốt nhất",
            bg=self.colors['gray_light'], fg=self.colors['gray_medium'],
            font=('Segoe UI', 8, 'italic')
        )
        lbl_mode_rec.pack(side=tk.LEFT)

        # Configured Status Summary
        frame_summary = tk.Frame(frame_quick, bg=self.colors['gray_light'])
        frame_summary.pack(fill=tk.X, pady=(10, 0))
        
        tk.Label(frame_summary, text="Trạng thái cấu hình các nguồn AI:", bg=self.colors['gray_light'], font=('Segoe UI', 9, 'bold')).pack(anchor=tk.W)
        
        self.lbl_quick_summary = tk.Label(
            frame_summary, text="Đang tải...",
            bg=self.colors['gray_light'], fg=self.colors['gray_dark'],
            font=('Segoe UI', 9), justify=tk.LEFT, wraplength=620
        )
        self.lbl_quick_summary.pack(fill=tk.X, anchor=tk.W, pady=2)

        # --- PHẦN B: DANH SÁCH NHÀ CUNG CẤP ---
        frame_providers = tk.LabelFrame(
            scrollable_frame, text="🤖 Các nhà cung cấp AI hiện khả dụng",
            bg=self.colors['gray_light'], fg=self.colors['navy'],
            font=('Segoe UI', 10, 'bold'), padx=15, pady=10
        )
        frame_providers.pack(fill=tk.X, padx=20, pady=5)

        columns = ("name", "enabled", "api_key_status", "key_count", "default_model")
        
        # Container frame for treeview and side buttons
        frame_tree_container = tk.Frame(frame_providers, bg=self.colors['gray_light'])
        frame_tree_container.pack(fill=tk.BOTH, expand=True)

        # Move Up/Down buttons on the right side
        frame_move_buttons = tk.Frame(frame_tree_container, bg=self.colors['gray_light'])
        frame_move_buttons.pack(side=tk.RIGHT, padx=10, fill=tk.Y)

        self.btn_move_up = create_styled_button(
            frame_move_buttons, text="▲ Di chuyển lên", command=self._move_provider_up,
            width=15, colors=self.colors
        )
        self.btn_move_up.pack(pady=5)

        self.btn_move_down = create_styled_button(
            frame_move_buttons, text="▼ Di chuyển xuống", command=self._move_provider_down,
            width=15, colors=self.colors
        )
        self.btn_move_down.pack(pady=5)

        self.prov_tree = ttk.Treeview(frame_tree_container, columns=columns, show="headings", height=6)
        self.prov_tree.heading("name", text="Nhà cung cấp")
        self.prov_tree.heading("enabled", text="Trạng thái")
        self.prov_tree.heading("api_key_status", text="API Key")
        self.prov_tree.heading("key_count", text="Số Key")
        self.prov_tree.heading("default_model", text="Model mặc định")
        
        self.prov_tree.column("name", width=130)
        self.prov_tree.column("enabled", width=90, anchor=tk.CENTER)
        self.prov_tree.column("api_key_status", width=120, anchor=tk.CENTER)
        self.prov_tree.column("key_count", width=80, anchor=tk.CENTER)
        self.prov_tree.column("default_model", width=180)
        
        self.prov_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.prov_tree.bind("<<TreeviewSelect>>", self._on_provider_selected)

        # --- PHẦN C: CHI TIẾT & CẤU HÌNH NHÀ CUNG CẤP ---
        self.frame_detail = tk.LabelFrame(
            scrollable_frame, text="🛠️ Chi tiết nhà cung cấp được chọn (Vui lòng chọn dòng ở trên)",
            bg=self.colors['gray_light'], fg=self.colors['navy'],
            font=('Segoe UI', 10, 'bold'), padx=15, pady=10
        )
        self.frame_detail.pack(fill=tk.X, padx=20, pady=5)

        # Instance vars for Section C controls
        self.selected_provider = None
        self.prov_enabled_var = tk.BooleanVar(value=False)
        self.prov_base_url_var = tk.StringVar()
        self.prov_new_key_var = tk.StringVar()
        self.prov_new_model_var = tk.StringVar()
        self.prov_default_model_var = tk.StringVar()

        # Enabled Checkbox
        self.chk_prov_enabled = tk.Checkbutton(
            self.frame_detail, text="Bật nhà cung cấp này trong hệ thống",
            variable=self.prov_enabled_var, bg=self.colors['gray_light'],
            fg=self.colors['gray_dark'], font=('Segoe UI', 9, 'bold'),
            state=tk.DISABLED
        )
        self.chk_prov_enabled.pack(anchor=tk.W, pady=2)

        self.lbl_google_tip = tk.Label(
            self.frame_detail, text="💡 Tắt Google Translate nếu bạn muốn chắc chắn chỉ dùng AI provider.",
            bg=self.colors['gray_light'], fg=self.colors['navy'],
            font=('Segoe UI', 9, 'italic')
        )

        # Base URL Row
        self.frame_base_url = tk.Frame(self.frame_detail, bg=self.colors['gray_light'])
        self.frame_base_url.pack(fill=tk.X, pady=5)
        tk.Label(self.frame_base_url, text="Base URL:", width=12, bg=self.colors['gray_light'], anchor=tk.W).pack(side=tk.LEFT)
        self.entry_base_url = tk.Entry(self.frame_base_url, textvariable=self.prov_base_url_var, bg=self.colors['white'], state=tk.DISABLED)
        self.entry_base_url.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

        # Key pool frame
        self.frame_keys = tk.Frame(self.frame_detail, bg=self.colors['gray_light'])
        self.frame_keys.pack(fill=tk.X, pady=5)
        
        tk.Label(self.frame_keys, text="API Keys:", width=12, bg=self.colors['gray_light'], anchor=tk.W).pack(side=tk.LEFT, anchor=tk.N)
        
        self.frame_keys_list_buttons = tk.Frame(self.frame_keys, bg=self.colors['gray_light'])
        self.frame_keys_list_buttons.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

        self.listbox_keys = tk.Listbox(self.frame_keys_list_buttons, height=3, bg=self.colors['white'], font=('Consolas', 9), state=tk.DISABLED)
        self.listbox_keys.pack(fill=tk.X, expand=True, pady=(0, 5))

        self.frame_add_key = tk.Frame(self.frame_keys_list_buttons, bg=self.colors['gray_light'])
        self.frame_add_key.pack(fill=tk.X)
        
        self.entry_new_key = tk.Entry(self.frame_add_key, textvariable=self.prov_new_key_var, bg=self.colors['white'], width=30, show="*", state=tk.DISABLED)
        self.entry_new_key.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        
        self.btn_add_key = create_styled_button(
            self.frame_add_key, text="Thêm Key", command=self._add_provider_key, colors=self.colors
        )
        self.btn_add_key.config(state=tk.DISABLED)
        self.btn_add_key.pack(side=tk.LEFT, padx=2)
        
        self.btn_delete_key = create_styled_button(
            self.frame_add_key, text="Xóa Key", command=self._delete_provider_key, colors=self.colors
        )
        self.btn_delete_key.config(state=tk.DISABLED)
        self.btn_delete_key.pack(side=tk.LEFT, padx=2)

        # Model catalog frame
        self.frame_models = tk.Frame(self.frame_detail, bg=self.colors['gray_light'])
        self.frame_models.pack(fill=tk.X, pady=5)

        tk.Label(self.frame_models, text="Model:", width=12, bg=self.colors['gray_light'], anchor=tk.W).pack(side=tk.LEFT, anchor=tk.N)

        self.frame_models_list_buttons = tk.Frame(self.frame_models, bg=self.colors['gray_light'])
        self.frame_models_list_buttons.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

        self.listbox_models = tk.Listbox(self.frame_models_list_buttons, height=4, bg=self.colors['white'], font=('Consolas', 9), state=tk.DISABLED)
        self.listbox_models.pack(fill=tk.X, expand=True, pady=(0, 5))

        self.frame_add_model = tk.Frame(self.frame_models_list_buttons, bg=self.colors['gray_light'])
        self.frame_add_model.pack(fill=tk.X)

        self.entry_new_model = tk.Entry(self.frame_add_model, textvariable=self.prov_new_model_var, bg=self.colors['white'], width=30, state=tk.DISABLED)
        self.entry_new_model.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))

        self.btn_add_model = create_styled_button(
            self.frame_add_model, text="Thêm Model", command=self._add_provider_model, colors=self.colors
        )
        self.btn_add_model.config(state=tk.DISABLED)
        self.btn_add_model.pack(side=tk.LEFT, padx=2)

        self.btn_delete_model = create_styled_button(
            self.frame_add_model, text="Xóa Model", command=self._delete_provider_model, colors=self.colors
        )
        self.btn_delete_model.config(state=tk.DISABLED)
        self.btn_delete_model.pack(side=tk.LEFT, padx=2)

        self.btn_refresh_models = create_styled_button(
            self.frame_add_model, text="Làm mới model", command=self._refresh_provider_models_catalog, colors=self.colors
        )
        self.btn_refresh_models.config(state=tk.DISABLED)
        self.btn_refresh_models.pack(side=tk.LEFT, padx=2)

        # Default model row
        self.frame_model = tk.Frame(self.frame_detail, bg=self.colors['gray_light'])
        self.frame_model.pack(fill=tk.X, pady=5)
        tk.Label(self.frame_model, text="Model mặc định:", width=12, bg=self.colors['gray_light'], anchor=tk.W).pack(side=tk.LEFT)
        
        self.combo_model = ttk.Combobox(self.frame_model, textvariable=self.prov_default_model_var, state="disabled", width=30)
        self.combo_model.pack(side=tk.LEFT, padx=5)

        # Refresh status label
        self.lbl_refresh_status = tk.Label(
            self.frame_detail, text="", bg=self.colors['gray_light'],
            fg=self.colors['gray_dark'], font=('Segoe UI', 8, 'italic'), anchor=tk.W, justify=tk.LEFT
        )
        self.lbl_refresh_status.pack(fill=tk.X, pady=(2, 5))

        # Section C action buttons
        self.frame_detail_actions = tk.Frame(self.frame_detail, bg=self.colors['gray_light'])
        self.frame_detail_actions.pack(fill=tk.X, pady=(10, 0))
        
        self.btn_save_prov = create_styled_button(
            self.frame_detail_actions, text="💾 Lưu cấu hình nhà cung cấp", command=self._save_provider_detail, colors=self.colors
        )
        self.btn_save_prov.config(state=tk.DISABLED)
        self.btn_save_prov.pack(side=tk.LEFT, padx=(0, 10))

        # --- PHẦN D: THÔNG TIN KỸ THUẬT / NÂNG CAO ---
        self.frame_advanced_router = tk.LabelFrame(
            scrollable_frame, text="📊 Trạng thái hoạt động nâng cao (Debug/Router Health)",
            bg=self.colors['gray_light'], fg=self.colors['navy'],
            font=('Segoe UI', 10, 'bold'), padx=15, pady=10
        )
        self.frame_advanced_router.pack(fill=tk.X, padx=20, pady=5)

        # Router stats row
        frame_router_stats = tk.Frame(self.frame_advanced_router, bg=self.colors['gray_light'])
        frame_router_stats.pack(fill=tk.X, pady=(0, 5))
        
        self.lbl_router_status = tk.Label(
            frame_router_stats, text="Trạng thái Smart Router: Đang kiểm tra...",
            font=('Segoe UI', 9, 'bold'), bg=self.colors['gray_light'], anchor=tk.W
        )
        self.lbl_router_status.pack(fill=tk.X, side=tk.TOP, anchor=tk.W, pady=(0, 5))

        frame_router_buttons = tk.Frame(frame_router_stats, bg=self.colors['gray_light'])
        frame_router_buttons.pack(fill=tk.X)

        create_styled_button(
            frame_router_buttons, text="Làm mới trạng thái", command=self._refresh_router_health, colors=self.colors
        ).pack(side=tk.RIGHT, padx=5)

        create_styled_button(
            frame_router_buttons, text="Reset Cooldowns (Khôi phục)", command=self._reset_router_cooldowns, colors=self.colors
        ).pack(side=tk.RIGHT, padx=5)

        # Health table Treeview
        r_cols = ("provider", "model", "available", "cooldown", "failures", "last_error", "latency")
        self.router_tree = ttk.Treeview(self.frame_advanced_router, columns=r_cols, show="headings", height=4)
        self.router_tree.heading("provider", text="Provider")
        self.router_tree.heading("model", text="Model ID")
        self.router_tree.heading("available", text="Khả dụng")
        self.router_tree.heading("cooldown", text="Cooldown")
        self.router_tree.heading("failures", text="Lỗi liên tiếp")
        self.router_tree.heading("last_error", text="Lỗi gần nhất")
        self.router_tree.heading("latency", text="Latency (ms)")
        
        self.router_tree.column("provider", width=100)
        self.router_tree.column("model", width=140)
        self.router_tree.column("available", width=70, anchor=tk.CENTER)
        self.router_tree.column("cooldown", width=90)
        self.router_tree.column("failures", width=80, anchor=tk.CENTER)
        self.router_tree.column("last_error", width=150)
        self.router_tree.column("latency", width=80, anchor=tk.CENTER)
        self.router_tree.pack(fill=tk.BOTH, expand=True, pady=5)

        # Save general settings row (Legacy section 4 TM/Glossary integration)
        frame_general_save = tk.LabelFrame(
            scrollable_frame, text="⚙️ Cài đặt nâng cao (Bộ nhớ & Thuật ngữ)",
            bg=self.colors['gray_light'], fg=self.colors['navy'],
            font=('Segoe UI', 10, 'bold'), padx=15, pady=10
        )
        frame_general_save.pack(fill=tk.X, padx=20, pady=(5, 20))

        # Row 1: Translation Memory Settings
        tm_row = tk.Frame(frame_general_save, bg=self.colors['gray_light'])
        tm_row.pack(fill=tk.X, pady=2)
        tk.Checkbutton(
            tm_row, text="Bật Bộ nhớ dịch (Translation Memory)", 
            variable=self.use_tm_var, bg=self.colors['gray_light'],
            fg=self.colors['gray_dark'], activebackground=self.colors['gray_light']
        ).pack(side=tk.LEFT)
        tk.Label(tm_row, text="Độ dài tối thiểu segment lưu cache:", bg=self.colors['gray_light']).pack(side=tk.LEFT, padx=(20, 5))
        tk.Entry(tm_row, textvariable=self.min_seg_len_var, width=5, bg=self.colors['white']).pack(side=tk.LEFT)

        # Row 2: Glossary Settings
        glossary_row = tk.Frame(frame_general_save, bg=self.colors['gray_light'])
        glossary_row.pack(fill=tk.X, pady=2)
        tk.Checkbutton(
            glossary_row, text="Bật Thuật ngữ (Glossary)", 
            variable=self.use_glossary_var, bg=self.colors['gray_light'],
            fg=self.colors['gray_dark'], activebackground=self.colors['gray_light']
        ).pack(side=tk.LEFT)
        tk.Label(glossary_row, text="Cấp độ thực thi:", bg=self.colors['gray_light']).pack(side=tk.LEFT, padx=(20, 5))
        
        def _on_glossary_level_changed(*args):
            level = self.glossary_level_var.get()
            if level == "validate":
                self.glossary_note_label.config(text="💡 Note: 'validate' được dành riêng cho các tính năng tương lai.", fg="orange")
            else:
                self.glossary_note_label.config(text="💡 Cài đặt thực thi thuật ngữ thành công.", fg="green")

        self.glossary_level_var.trace_add("write", _on_glossary_level_changed)
        glossary_level_combo = ttk.Combobox(
            glossary_row, textvariable=self.glossary_level_var, 
            values=["off", "prompt", "validate"], state="readonly", width=10
        )
        glossary_level_combo.pack(side=tk.LEFT)
        tk.Label(glossary_row, text="Max terms/segment:", bg=self.colors['gray_light']).pack(side=tk.LEFT, padx=(20, 5))
        tk.Spinbox(
            glossary_row, from_=1, to=999, textvariable=self.max_glossary_terms_var, width=5, bg=self.colors['white']
        ).pack(side=tk.LEFT)

        self.glossary_note_label = tk.Label(
            frame_general_save, text="💡 Thuật ngữ giúp chuẩn hóa các cụm từ chuyên ngành.", 
            bg=self.colors['gray_light'], fg=self.colors['gray_medium'], font=('Segoe UI', 8, 'italic')
        )
        self.glossary_note_label.pack(anchor=tk.W, pady=(2, 5))

        # Row for Auto Refresh setting
        auto_refresh_row = tk.Frame(frame_general_save, bg=self.colors['gray_light'])
        auto_refresh_row.pack(fill=tk.X, pady=2)
        chk_auto_refresh = tk.Checkbutton(
            auto_refresh_row, text="Tự động làm mới model khi mở app", 
            variable=self.auto_refresh_provider_models_var, bg=self.colors['gray_light'],
            fg=self.colors['gray_dark'], activebackground=self.colors['gray_light']
        )
        chk_auto_refresh.pack(side=tk.LEFT)
        tk.Label(
            auto_refresh_row, text="💡 Tự động tải danh sách model mới của OpenAI/NVIDIA trong background.",
            bg=self.colors['gray_light'], fg=self.colors['gray_medium'], font=('Segoe UI', 8, 'italic')
        ).pack(side=tk.LEFT, padx=(10, 0))

        # Row 3: Save button
        save_btn_row = tk.Frame(frame_general_save, bg=self.colors['gray_light'])
        save_btn_row.pack(fill=tk.X, pady=(5, 0))
        create_styled_button(
            save_btn_row, text="💾 Lưu cài đặt nâng cao", 
            command=self._save_advanced_settings, colors=self.colors
        ).pack(side=tk.LEFT)

        # Initial data loading
        self._refresh_quick_config_summary()
        self._refresh_providers_tree()
        self._refresh_router_health()

    def _on_quick_router_toggled(self):
        """Handle toggle of Smart Router checkbox in Section A."""
        val = self.use_router_var.get()
        self.config_manager.use_provider_router = val
        self.config_manager.save_config()
        self._refresh_router_health()
        
    def _refresh_quick_config_summary(self):
        """Update the quick status label in Section A based on configured keys."""
        try:
            pub_data = self.config_manager.get_provider_profiles_public()
            summaries = []
            
            # Helper for displaying configured/not configured
            def get_status(p_name, display_name):
                p_cfg = pub_data.get(p_name, {})
                keys_count = len(p_cfg.get("api_keys", []))
                # For Gemini, also check legacy key just in case
                if p_name == "gemini" and not keys_count:
                    legacy_exists = bool(self.config_manager.api_key or self.config_manager.api_keys)
                    keys_count = len(self.config_manager.api_keys) or (1 if legacy_exists else 0)
                
                if keys_count > 0:
                    return f"{display_name}: 🟢 Đã cấu hình ({keys_count} key)"
                else:
                    return f"{display_name}: 🔴 Chưa cấu hình"

            summaries.append(get_status("gemini", "Gemini"))
            summaries.append(get_status("chatanywhere", "ChatAnyWhere"))
            summaries.append(get_status("deepseek", "DeepSeek"))
            summaries.append(get_status("nvidia_nim", "NVIDIA NIM"))
            summaries.append(get_status("openai_compatible", "OpenAI tùy chỉnh"))
            
            self.lbl_quick_summary.config(text="  |  ".join(summaries))
        except Exception as e:
            logger.error(f"Error updating quick summary: {e}")
            self.lbl_quick_summary.config(text="Lỗi tải trạng thái")

    def _refresh_providers_tree(self):
        """Reload providers Treeview in Section B."""
        for item in self.prov_tree.get_children():
            self.prov_tree.delete(item)
            
        try:
            pub_data = self.config_manager.get_provider_profiles_public()
            provider_display_names = {
                "gemini": "Gemini AI",
                "chatanywhere": "ChatAnyWhere",
                "deepseek": "DeepSeek",
                "nvidia_nim": "NVIDIA NIM",
                "openai_compatible": "OpenAI tùy chỉnh",
                "google": "Google Translate"
            }
            
            # Sort providers by priority order list
            order = list(self.config_manager.provider_order)
            full_order = [p for p in order if p in provider_display_names]
            for p in provider_display_names:
                if p not in full_order:
                    full_order.append(p)
            
            for p_name in full_order:
                display = provider_display_names[p_name]
                p_cfg = pub_data.get(p_name, {})
                enabled = "🟢 Bật" if p_cfg.get("enabled", False) else "🔴 Tắt"
                
                # Check api keys
                api_keys = p_cfg.get("api_keys", [])
                keys_count = len(api_keys)
                if p_name == "gemini" and not keys_count:
                    legacy_exists = bool(self.config_manager.api_key or self.config_manager.api_keys)
                    keys_count = len(self.config_manager.api_keys) or (1 if legacy_exists else 0)

                api_key_status = "Đã cấu hình" if keys_count > 0 else "Chưa cấu hình"
                if p_name == "google":
                    # Google doesn't need keys, but can be enabled or disabled
                    api_key_status = "Không yêu cầu key"
                    keys_count = 0
                
                # Models
                default_model = p_cfg.get("default_model", "") or "Chưa cài đặt"
                if p_name == "gemini" and not p_cfg.get("default_model"):
                    default_model = "gemini-3.5-flash (Waterfall)"
                
                self.prov_tree.insert(
                    "", tk.END, iid=p_name,
                    values=(display, enabled, api_key_status, f"{keys_count} key" if keys_count else "-", default_model)
                )
        except Exception as e:
            logger.error(f"Error loading providers list in Treeview: {e}")

    def _on_provider_selected(self, event=None):
        """Update Section C fields when a provider is selected in Section B."""
        selection = self.prov_tree.selection()
        if not selection:
            self.selected_provider = None
            self.chk_prov_enabled.config(state=tk.DISABLED)
            self.entry_base_url.config(state=tk.DISABLED)
            self.listbox_keys.config(state=tk.DISABLED)
            self.entry_new_key.config(state=tk.DISABLED)
            self.btn_add_key.config(state=tk.DISABLED)
            self.btn_delete_key.config(state=tk.DISABLED)
            self.listbox_models.config(state=tk.DISABLED)
            self.entry_new_model.config(state=tk.DISABLED)
            self.btn_add_model.config(state=tk.DISABLED)
            self.btn_delete_model.config(state=tk.DISABLED)
            self.btn_refresh_models.config(state=tk.DISABLED)
            self.combo_model.config(state="disabled")
            self.btn_save_prov.config(state=tk.DISABLED)
            return

        p_name = selection[0]
        self.selected_provider = p_name
        
        # Load profile data
        pub_data = self.config_manager.get_provider_profiles_public()
        p_cfg = pub_data.get(p_name, {})
        catalog = self.config_manager.get_provider_model_catalog_public()
        catalog_entry = catalog.get("providers", {}).get(p_name, {})
        
        # Update enabled
        self.prov_enabled_var.set(p_cfg.get("enabled", False))
        self.chk_prov_enabled.config(state=tk.NORMAL)
        
        # Update base url
        self.prov_base_url_var.set(p_cfg.get("base_url", ""))
        self.entry_base_url.config(state=tk.NORMAL if p_name in ("chatanywhere", "deepseek", "nvidia_nim", "openai_compatible") else tk.DISABLED)
        
        # Update listbox keys (masked representation)
        self.listbox_keys.config(state=tk.NORMAL)
        self.listbox_keys.delete(0, tk.END)
        
        keys_count = len(p_cfg.get("api_keys", []))
        if p_name == "gemini" and not keys_count:
            keys_count = len(self.config_manager.api_keys) or (1 if self.config_manager.api_key else 0)

        for i in range(keys_count):
            self.listbox_keys.insert(tk.END, f"Key {i+1}: đã cấu hình")
            
        self.prov_new_key_var.set("")
        self.entry_new_key.config(state=tk.NORMAL if p_name != "google" else tk.DISABLED)
        self.btn_add_key.config(state=tk.NORMAL if p_name != "google" else tk.DISABLED)
        self.btn_delete_key.config(state=tk.NORMAL if p_name != "google" else tk.DISABLED)
        
        self._refresh_provider_model_controls(p_name, catalog_entry)
            
        self.btn_save_prov.config(state=tk.NORMAL)

        if p_name == "google":
            self.lbl_google_tip.pack(anchor=tk.W, pady=5)
        else:
            self.lbl_google_tip.pack_forget()
        
        self.frame_detail.config(text=f"🛠️ Chi tiết nhà cung cấp được chọn: {p_name.upper()}")

    def _refresh_provider_model_controls(self, provider_name: str, catalog_entry: dict | None = None):
        catalog = self.config_manager.get_provider_model_catalog_public()
        entry = catalog_entry if isinstance(catalog_entry, dict) else catalog.get("providers", {}).get(provider_name, {})
        model_entries = entry.get("models", []) if isinstance(entry, dict) else []

        self.listbox_models.config(state=tk.NORMAL)
        self.listbox_models.delete(0, tk.END)

        enabled_models = []
        for model_entry in model_entries:
            model_id = str(model_entry.get("id", "")).strip()
            if not model_id:
                continue
            status = "Bật" if model_entry.get("enabled", True) else "Tắt"
            
            # Map source to premium tag
            src_val = model_entry.get("source", "user")
            if src_val == "api_discovered":
                src_tag = "API-discovered"
            elif src_val == "user":
                src_tag = "configured/user"
            elif src_val in ("seed", "default", "legacy"):
                src_tag = "legacy/seed"
            elif src_val == "docs_known":
                src_tag = "configured/docs-known"
            else:
                src_tag = str(src_val)

            # Map visibility to premium tag
            vis_val = model_entry.get("visibility", "unverified")
            if vis_val == "current_key_visible":
                vis_tag = "current-key-visible"
            elif vis_val == "live_validated":
                vis_tag = "live-validated"
            elif vis_val == "unverified":
                vis_tag = "unverified"
            elif vis_val == "unavailable":
                vis_tag = "unavailable"
            else:
                vis_tag = str(vis_val)

            self.listbox_models.insert(tk.END, f"{model_id} [{status} | {src_tag} | {vis_tag}]")
            if model_entry.get("enabled", True):
                enabled_models.append(model_id)

        is_google = provider_name == "google"
        self.prov_new_model_var.set("")
        self.entry_new_model.config(state=tk.NORMAL if not is_google else tk.DISABLED)
        self.btn_add_model.config(state=tk.NORMAL if not is_google else tk.DISABLED)
        self.btn_delete_model.config(state=tk.NORMAL if not is_google else tk.DISABLED)
        self.btn_refresh_models.config(state=tk.NORMAL if entry.get("supports_refresh", False) else tk.DISABLED)

        default_model = str(entry.get("default_model", "")).strip()
        combo_values = list(enabled_models)
        if default_model and default_model not in combo_values:
            combo_values.insert(0, default_model)
        self.combo_model.config(values=combo_values)
        self.prov_default_model_var.set(default_model or (combo_values[0] if combo_values else ""))
        self.combo_model.config(state="readonly" if combo_values and not is_google else "disabled")

    def _add_provider_key(self):
        """Add new API Key to current selected provider."""
        if not self.selected_provider:
            return
            
        new_key = self.prov_new_key_var.get().strip()
        if not new_key:
            messagebox.showwarning("Cảnh báo", "Vui lòng nhập API Key trước khi nhấn thêm.")
            return
            
        success = self.config_manager.add_provider_api_key(self.selected_provider, new_key)
        if success:
            self.config_manager.save_config()
            self._refresh_quick_config_summary()
            self._refresh_providers_tree()
            self._on_provider_selected() # Refresh detail pane
            messagebox.showinfo("Thành công", f"Đã thêm key mới cho nhà cung cấp {self.selected_provider} thành công.")
        else:
            messagebox.showerror("Lỗi", "Không thể thêm key mới. Kiểm tra xem key có bị trùng lặp không.")

    def _delete_provider_key(self):
        """Delete selected key from key pool."""
        if not self.selected_provider:
            return
            
        sel_key_idx = self.listbox_keys.curselection()
        if not sel_key_idx:
            messagebox.showwarning("Cảnh báo", "Vui lòng chọn một key trong danh sách API Keys ở trên để xóa.")
            return
            
        idx = sel_key_idx[0]
        if messagebox.askyesno("Xác nhận", f"Bạn có chắc muốn xóa Key {idx+1} của nhà cung cấp {self.selected_provider}?"):
            success = self.config_manager.remove_provider_api_key(self.selected_provider, idx)
            if success:
                self.config_manager.save_config()
                self._refresh_quick_config_summary()
                self._refresh_providers_tree()
                self._on_provider_selected() # Refresh detail pane
                messagebox.showinfo("Thành công", "Đã xóa API key thành công.")
            else:
                messagebox.showerror("Lỗi", "Không thể xóa API key.")

    def _add_provider_model(self):
        """Add a model to the selected provider catalog."""
        if not self.selected_provider:
            return

        model_id = self.prov_new_model_var.get().strip()
        if not model_id:
            messagebox.showwarning("Cảnh báo", "Vui lòng nhập model trước khi thêm.")
            return

        success = self.config_manager.add_provider_model(self.selected_provider, model_id)
        if not success:
            messagebox.showerror("Lỗi", "Không thể thêm model. Model có thể đã tồn tại.")
            return

        self.config_manager.save_config()
        self._refresh_providers_tree()
        self._on_provider_selected()
        messagebox.showinfo("Thành công", f"Đã thêm model mới cho {self.selected_provider}.")

    def _delete_provider_model(self):
        """Delete the selected model from the provider catalog."""
        if not self.selected_provider:
            return

        selected = self.listbox_models.curselection()
        if not selected:
            messagebox.showwarning("Cảnh báo", "Vui lòng chọn model cần xóa.")
            return

        raw_value = self.listbox_models.get(selected[0])
        model_id = raw_value.split(" [", 1)[0].strip()
        if not model_id:
            return

        if not messagebox.askyesno("Xác nhận", f"Bạn có chắc muốn xóa model '{model_id}' khỏi {self.selected_provider}?"):
            return

        success = self.config_manager.remove_provider_model(self.selected_provider, model_id)
        if not success:
            messagebox.showerror("Lỗi", "Không thể xóa model đã chọn.")
            return

        self.config_manager.save_config()
        self._refresh_providers_tree()
        self._on_provider_selected()
        messagebox.showinfo("Thành công", f"Đã xóa model '{model_id}'.")

    def _refresh_provider_models_catalog(self):
        """Refresh models from selected provider using the background helper."""
        if not self.selected_provider:
            return
        self._start_provider_model_refresh(self.selected_provider, manual=True, force=True)

    def _start_provider_model_refresh(
        self,
        provider_name: str,
        manual: bool = False,
        force: bool = False,
        on_complete: Optional[callable] = None,
    ) -> bool:
        """Start a background thread to refresh provider models without making any Tkinter calls in it."""
        if not self.winfo_exists():
            return False

        provider_name = str(provider_name or "").strip().lower()

        # Prevent double-refreshing the same provider at the same time
        if provider_name in self._provider_model_refresh_inflight:
            return False

        # If this is auto-refresh (not force), check caching
        if not force:
            if not self.config_manager.should_auto_refresh_provider_models(provider_name):
                return False

        # Mark as inflight and register attempt
        self._provider_model_auto_refresh_attempted.add(provider_name)
        self._provider_model_refresh_inflight.add(provider_name)

        # Update manual refresh controls visual state if this provider is currently selected
        if self.selected_provider == provider_name:
            self.btn_refresh_models.config(state=tk.DISABLED, text="Đang quét model...")
            self.listbox_models.config(state=tk.DISABLED)
            self._refresh_provider_model_status_widgets()

        def worker():
            success = False
            discovered_count = 0
            error_text = ""
            try:
                discovered = self.config_manager.refresh_provider_models(provider_name)
                self.config_manager.save_config()
                success = True
                discovered_count = len(discovered)
            except Exception as e:
                error_text = str(e)

            # Append the result thread-safely to our list. Python lists are thread-safe for appending.
            self._provider_model_refresh_queue_results.append({
                "provider_name": provider_name,
                "manual": manual,
                "success": success,
                "count": discovered_count,
                "error_text": error_text,
                "on_complete": on_complete,
            })

        threading.Thread(target=worker, daemon=True).start()
        return True

    def _poll_provider_model_refresh_results(self):
        """Periodically poll for background thread results on the main thread."""
        if not self.winfo_exists():
            return

        while self._provider_model_refresh_queue_results:
            res = self._provider_model_refresh_queue_results.pop(0)
            self._handle_provider_model_refresh_done(
                res["provider_name"],
                res["manual"],
                res["success"],
                res["count"],
                res["error_text"],
                res["on_complete"],
            )

        poll_after_id = self.after(50, self._poll_provider_model_refresh_results)
        self._provider_model_poll_after_ids.add(poll_after_id)

    def _handle_provider_model_refresh_done(
        self,
        provider_name: str,
        manual: bool,
        success: bool,
        count: int,
        error_text: str,
        on_complete: Optional[callable] = None,
    ):
        """Handle UI updates after a background provider model refresh completes. Runs on main thread."""
        if provider_name in self._provider_model_refresh_inflight:
            self._provider_model_refresh_inflight.remove(provider_name)

        # Update cache state
        self.config_manager.record_provider_model_refresh_result(
            provider_name,
            "success" if success else "error",
            count,
            error_text if not success else None,
        )

        if not self.winfo_exists():
            if callable(on_complete):
                on_complete()
            return

        # Restore button visuals if selected provider is this provider
        if self.selected_provider == provider_name:
            self.listbox_models.config(state=tk.NORMAL)
            self._on_provider_selected()

        # Update list elements
        self._refresh_providers_tree()
        self._refresh_provider_model_status_widgets()

        # Handle feedback popups
        if manual:
            if success:
                messagebox.showinfo(
                    "Thành công",
                    f"Đã làm mới và phát hiện {count} model từ API cho {provider_name}.",
                )
            else:
                messagebox.showerror(
                    "Lỗi",
                    f"Không thể làm mới model: {error_text}",
                )

        if callable(on_complete):
            on_complete()

    def _run_next_auto_provider_model_refresh(self):
        """Process next provider in the auto refresh queue. Runs on main thread."""
        if not self.winfo_exists():
            return

        if self._provider_model_auto_refresh_running:
            return

        if not self._provider_model_auto_refresh_queue:
            self._refresh_provider_model_status_widgets()
            return

        provider_name = self._provider_model_auto_refresh_queue.pop(0)
        self._provider_model_auto_refresh_running = True

        def continue_queue():
            self._provider_model_auto_refresh_running = False
            if self.winfo_exists():
                self.after(0, self._run_next_auto_provider_model_refresh)

        started = self._start_provider_model_refresh(
            provider_name,
            manual=False,
            force=False,
            on_complete=continue_queue,
        )
        if not started:
            continue_queue()

    def _auto_refresh_provider_models_on_startup(self):
        """Auto refresh eligible provider models in the background on startup or tab focus."""
        if hasattr(self, '_auto_refresh_after_id') and self._auto_refresh_after_id:
            try:
                self.after_cancel(self._auto_refresh_after_id)
            except Exception:
                pass
        self._auto_refresh_after_id = None
        if not self.winfo_exists():
            return

        self._refresh_provider_model_status_widgets()
        if not self.config_manager.auto_refresh_provider_models:
            return

        # Get list of providers prioritised by user's configuration
        ordered_names = list(self.config_manager.provider_order)
        for provider_name in self.config_manager.providers_config.keys():
            if provider_name not in ordered_names:
                ordered_names.append(provider_name)

        # Get all providers that need background auto-refresh
        eligible = [
            provider_name
            for provider_name in ordered_names
            if provider_name not in self._provider_model_auto_refresh_attempted
            and self.config_manager.should_auto_refresh_provider_models(provider_name)
        ]
        if not eligible:
            self._refresh_provider_model_status_widgets()
            return

        self._provider_model_auto_refresh_queue = eligible
        self._refresh_provider_model_status_widgets()
        self._run_next_auto_provider_model_refresh()

    def _refresh_provider_model_status_widgets(self):
        """Update localized status widgets for the current provider model refresh status."""
        if not hasattr(self, 'lbl_refresh_status'):
            return

        if not self.selected_provider:
            self.lbl_refresh_status.config(text="")
            return

        p_name = self.selected_provider
        catalog = self.config_manager.get_provider_model_catalog_public()
        entry = catalog.get("providers", {}).get(p_name, {})
        supports_refresh = entry.get("supports_refresh", False)

        if not supports_refresh:
            self.lbl_refresh_status.config(text="💡 Nhà cung cấp này không hỗ trợ tự động làm mới model.")
            return

        state = self.config_manager.get_provider_model_refresh_state_public().get(p_name, {})
        last_refreshed_str = state.get("last_refreshed_at")
        last_status = state.get("last_status", "never")
        last_error = state.get("last_error", "")
        last_count = state.get("last_count", 0)

        status_text = ""
        if p_name in self._provider_model_refresh_inflight:
            status_text = "⏳ Đang quét danh sách model từ API ở background..."
        elif last_status == "never":
            status_text = "🔄 Chưa từng được làm mới. Nhấn 'Làm mới model' để tải."
        elif last_status == "success":
            time_part = last_refreshed_str.split(".")[0].replace("T", " ") if last_refreshed_str else "không rõ"
            status_text = f"🟢 Làm mới thành công lúc {time_part}. Tìm thấy {last_count} model."
        elif last_status == "error":
            time_part = last_refreshed_str.split(".")[0].replace("T", " ") if last_refreshed_str else "không rõ"
            err_msg = last_error[:60] + "..." if len(last_error) > 60 else last_error
            status_text = f"🔴 Làm mới lỗi lúc {time_part}: {err_msg}"

        self.lbl_refresh_status.config(text=status_text)

    def _save_provider_detail(self):
        """Save base_url, enabled state and default model for current provider."""
        if not self.selected_provider:
            return
            
        enabled = self.prov_enabled_var.get()
        base_url = self.prov_base_url_var.get().strip()
        default_model = self.prov_default_model_var.get().strip()
        
        self.config_manager.update_provider_enabled(self.selected_provider, enabled)
        if self.selected_provider in ("chatanywhere", "deepseek", "nvidia_nim", "openai_compatible"):
            self.config_manager.update_provider_base_url(self.selected_provider, base_url)

        if default_model and not self.config_manager.set_provider_default_model(self.selected_provider, default_model):
            messagebox.showerror("Lỗi", "Model mặc định không tồn tại trong catalog của provider.")
            return
        self.config_manager.save_config()
        
        self._refresh_quick_config_summary()
        self._refresh_providers_tree()
        self._on_provider_selected() # Refresh detail pane
        self._refresh_router_health() # Sync to router snapshot
        messagebox.showinfo("Thành công", f"Đã lưu các cài đặt cho {self.selected_provider} thành công.")

    def _move_provider_up(self):
        """Move selected provider up in the router priority list."""
        selection = self.prov_tree.selection()
        if not selection:
            messagebox.showwarning("Cảnh báo", "Vui lòng chọn một nhà cung cấp để di chuyển.")
            return
        p_name = selection[0]
        order = list(self.config_manager.provider_order)
        if p_name not in order:
            return
        idx = order.index(p_name)
        if idx > 0:
            order[idx], order[idx-1] = order[idx-1], order[idx]
            self.config_manager.provider_order = order
            self.config_manager.save_config()
            self._refresh_providers_tree()
            self.prov_tree.selection_set(p_name)
            self._refresh_quick_config_summary()

    def _move_provider_down(self):
        """Move selected provider down in the router priority list."""
        selection = self.prov_tree.selection()
        if not selection:
            messagebox.showwarning("Cảnh báo", "Vui lòng chọn một nhà cung cấp để di chuyển.")
            return
        p_name = selection[0]
        order = list(self.config_manager.provider_order)
        if p_name not in order:
            return
        idx = order.index(p_name)
        if idx < len(order) - 1:
            order[idx], order[idx+1] = order[idx+1], order[idx]
            self.config_manager.provider_order = order
            self.config_manager.save_config()
            self._refresh_providers_tree()
            self.prov_tree.selection_set(p_name)
            self._refresh_quick_config_summary()

    def setup_file_tab(self):
        """Setup file translation tab"""
        # File selection frame
        frame_file_select = tk.Frame(self.tab_file, bg=self.colors['gray_light'])
        frame_file_select.pack(fill=tk.X, padx=15, pady=10)
        
        label_file_path = tk.Label(
            frame_file_select, text="Chọn File:",
            bg=self.colors['gray_light'], fg=self.colors['gray_dark'],
            font=('Segoe UI', 11, 'bold')
        )
        label_file_path.pack(anchor=tk.W, pady=(0, 5))
        
        frame_file_entry = tk.Frame(frame_file_select, bg=self.colors['gray_light'])
        frame_file_entry.pack(fill=tk.X, pady=5)
        
        self.entry_file_path = tk.Entry(
            frame_file_entry, width=55, font=('Segoe UI', 10),
            bg=self.colors['white'], fg=self.colors['gray_dark'],
            relief='solid', borderwidth=1
        )
        self.entry_file_path.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        
        button_browse = create_styled_button(
            frame_file_entry, text="Duyệt...", command=self.browse_file, colors=self.colors
        )
        button_browse.pack(side=tk.LEFT)
        
        # Language selection frame
        frame_lang = tk.Frame(self.tab_file, bg=self.colors['gray_light'])
        frame_lang.pack(fill=tk.X, padx=15, pady=10)
        
        frame_lang_row = tk.Frame(frame_lang, bg=self.colors['gray_light'])
        frame_lang_row.pack(fill=tk.X)
        
        # Source language
        frame_src_lang = tk.Frame(frame_lang_row, bg=self.colors['gray_light'])
        frame_src_lang.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        
        label_src_lang_file = tk.Label(
            frame_src_lang, text="Ngôn ngữ nguồn:",
            bg=self.colors['gray_light'], fg=self.colors['gray_dark'],
            font=('Segoe UI', 11, 'bold')
        )
        label_src_lang_file.pack(anchor=tk.W, pady=(0, 5))
        
        self.src_lang_file = tk.StringVar(value=config.default_src_lang)
        combobox_src_lang_file = create_language_combobox(
            frame_src_lang, self.src_lang_file,
            list(self.display_languages.keys()), self.colors
        )
        combobox_src_lang_file.pack(fill=tk.X)
        
        # Destination language
        frame_dest_lang = tk.Frame(frame_lang_row, bg=self.colors['gray_light'])
        frame_dest_lang.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(10, 0))
        
        label_dest_lang_file = tk.Label(
            frame_dest_lang, text="Ngôn ngữ đích:",
            bg=self.colors['gray_light'], fg=self.colors['gray_dark'],
            font=('Segoe UI', 11, 'bold')
        )
        label_dest_lang_file.pack(anchor=tk.W, pady=(0, 5))
        
        self.dest_lang_file = tk.StringVar(value=config.default_dest_lang)
        combobox_dest_lang_file = create_language_combobox(
            frame_dest_lang, self.dest_lang_file,
            list(self.display_languages.keys()), self.colors
        )
        combobox_dest_lang_file.pack(fill=tk.X)
        
        # Info label
        label_info_file = tk.Label(
            self.tab_file,
            text="Chương trình hỗ trợ dịch các loại file:\n"
                 "• Excel (.xlsx, .xls): Hỗ trợ tốt nhất hiện tại\n"
                 "• Word (.docx, .doc): Cần kiểm chứng định dạng\n"
                 "• PowerPoint (.pptx, .ppt): Cần kiểm chứng định dạng\n"
                 "• PDF (.pdf): Cần audit layout\n"
                 "• Text (.txt): Dịch thuần văn bản",
            bg=self.colors['gray_light'], fg=self.colors['gray_medium'],
            font=('Segoe UI', 9), justify=tk.LEFT
        )
        label_info_file.pack(padx=15, pady=10)
        
        # AI Vision option for PDF (powerful method for stubborn PDFs)
        frame_ai_option = tk.Frame(self.tab_file, bg=self.colors['gray_light'])
        frame_ai_option.pack(fill=tk.X, padx=15, pady=5)
        
        self.use_ai_vision_for_pdf = tk.BooleanVar(value=False)
        checkbox_ai_vision = tk.Checkbutton(
            frame_ai_option,
            text="🤖 Dùng AI Vision cho PDF (mạnh nhất cho PDF scan, tiếng Nhật/Trung)",
            variable=self.use_ai_vision_for_pdf,
            bg=self.colors['gray_light'], fg=self.colors['gray_dark'],
            font=('Segoe UI', 9),
            activebackground=self.colors['gray_light'],
            selectcolor=self.colors['white']
        )
        checkbox_ai_vision.pack(anchor=tk.W)

        self.use_experimental_pdf_output = tk.BooleanVar(value=False)
        checkbox_pdf_experimental = tk.Checkbutton(
            frame_ai_option,
            text="Xuất PDF thử nghiệm cho PDF text đơn giản",
            variable=self.use_experimental_pdf_output,
            bg=self.colors['gray_light'], fg=self.colors['gray_dark'],
            font=('Segoe UI', 9),
            activebackground=self.colors['gray_light'],
            selectcolor=self.colors['white']
        )
        checkbox_pdf_experimental.pack(anchor=tk.W, pady=(4, 0))

        label_pdf_experimental_warning = tk.Label(
            frame_ai_option,
            text=(
                "    Chế độ thử nghiệm: chỉ phù hợp PDF text đơn giản 1-2 trang. "
                "Bố cục có thể lệch. Với tài liệu quan trọng, hãy dùng chế độ DOCX ổn định."
            ),
            bg=self.colors['gray_light'], fg=self.colors['gray_medium'],
            font=('Segoe UI', 8, 'italic'),
            justify=tk.LEFT,
            wraplength=760
        )
        label_pdf_experimental_warning.pack(anchor=tk.W, pady=(2, 0))

        frame_pdf_report = tk.LabelFrame(
            self.tab_file,
            text="Báo cáo PDF thử nghiệm",
            bg=self.colors['gray_light'], fg=self.colors['navy'],
            font=('Segoe UI', 10, 'bold'), padx=12, pady=10
        )
        frame_pdf_report.pack(fill=tk.X, padx=15, pady=(8, 0))

        self.label_pdf_report_hint = tk.Label(
            frame_pdf_report,
            text=self._get_pdf_report_export_hint(),
            bg=self.colors['gray_light'], fg=self.colors['gray_dark'],
            font=('Segoe UI', 9), justify=tk.LEFT, wraplength=760
        )
        self.label_pdf_report_hint.pack(anchor=tk.W)

        self.label_pdf_report_notice = tk.Label(
            frame_pdf_report,
            text=self._get_pdf_report_export_notice(),
            bg=self.colors['gray_light'], fg=self.colors['gray_medium'],
            font=('Segoe UI', 8, 'italic'), justify=tk.LEFT, wraplength=760
        )
        self.label_pdf_report_notice.pack(anchor=tk.W, pady=(4, 8))

        frame_pdf_report_buttons = tk.Frame(frame_pdf_report, bg=self.colors['gray_light'])
        frame_pdf_report_buttons.pack(fill=tk.X)

        self.btn_export_pdf_report_json = create_styled_button(
            frame_pdf_report_buttons,
            text="Xuất báo cáo JSON",
            command=self.export_pdf_report_json,
            colors=self.colors
        )
        self.btn_export_pdf_report_json.config(state=tk.DISABLED)
        self.btn_export_pdf_report_json.pack(side=tk.LEFT, padx=(0, 8))

        self.btn_export_pdf_report_html = create_styled_button(
            frame_pdf_report_buttons,
            text="Xuất báo cáo HTML",
            command=self.export_pdf_report_html,
            colors=self.colors
        )
        self.btn_export_pdf_report_html.config(state=tk.DISABLED)
        self.btn_export_pdf_report_html.pack(side=tk.LEFT)

        # Pages per batch option (to save API requests)
        frame_batch_option = tk.Frame(frame_ai_option, bg=self.colors['gray_light'])
        frame_batch_option.pack(anchor=tk.W, pady=(2, 0))
        
        label_batch = tk.Label(
            frame_batch_option,
            text="    Số trang/batch:",
            bg=self.colors['gray_light'], fg=self.colors['gray_dark'],
            font=('Segoe UI', 8)
        )
        label_batch.pack(side=tk.LEFT)
        
        self.ai_vision_pages_per_batch = tk.StringVar(value="4")
        combo_batch = ttk.Combobox(
            frame_batch_option,
            textvariable=self.ai_vision_pages_per_batch,
            values=["1", "2", "4", "6", "9"],
            state="readonly",
            width=5,
            font=('Segoe UI', 8)
        )
        combo_batch.pack(side=tk.LEFT, padx=5)
        
        label_batch_info = tk.Label(
            frame_batch_option,
            text="(4 trang = tiết kiệm 75% request)",
            bg=self.colors['gray_light'], fg=self.colors['gray_medium'],
            font=('Segoe UI', 8, 'italic')
        )
        label_batch_info.pack(side=tk.LEFT)
        
        # Info tooltip for AI Vision
        label_ai_info = tk.Label(
            frame_ai_option,
            text="    💡 Ghép nhiều trang thành 1 ảnh grid = tiết kiệm 75% requests AI (giảm RPD)",
            bg=self.colors['gray_light'], fg=self.colors['gray_medium'],
            font=('Segoe UI', 8, 'italic')
        )
        label_ai_info.pack(anchor=tk.W)

        
        # Buttons frame
        frame_buttons = tk.Frame(self.tab_file, bg=self.colors['gray_light'])
        frame_buttons.pack(fill=tk.X, padx=15, pady=15)
        
        button_translate_file = create_styled_button(
            frame_buttons, text="Dịch File",
            command=self.translate_file, colors=self.colors
        )
        button_translate_file.pack(fill=tk.X, pady=5)

        
        # Status frame for progress indication
        frame_status = tk.Frame(self.tab_file, bg=self.colors['gray_light'])
        frame_status.pack(fill=tk.X, padx=15, pady=(0, 10))
        
        self.label_file_status = tk.Label(
            frame_status,
            text="",
            bg=self.colors['gray_light'], fg=self.colors['gray_dark'],
            font=('Segoe UI', 10), anchor=tk.W
        )
        self.label_file_status.pack(fill=tk.X, pady=(0, 5))
        
        self.progress_file = ttk.Progressbar(
            frame_status,
            mode='indeterminate',
            length=400,
            style='TProgressbar'
        )
        self.progress_file.pack(fill=tk.X)
    
    def setup_paragraph_tab(self):
        """Setup paragraph translation tab"""
        # Input frame
        frame_input = tk.Frame(self.tab_paragraph, bg=self.colors['gray_light'])
        frame_input.pack(fill=tk.BOTH, expand=True, padx=15, pady=10)
        
        label_paragraph_input = tk.Label(
            frame_input, text="Nhập nội dung cần dịch:",
            bg=self.colors['gray_light'], fg=self.colors['gray_dark'],
            font=('Segoe UI', 11, 'bold')
        )
        label_paragraph_input.pack(anchor=tk.W, pady=(0, 5))
        
        self.entry_paragraph_input = tk.Text(
            frame_input, height=10, wrap=tk.WORD,
            bg=self.colors['white'], fg=self.colors['gray_dark'],
            font=('Segoe UI', 10), relief='solid', borderwidth=1,
            padx=10, pady=10
        )
        self.entry_paragraph_input.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        # Language and buttons frame
        frame_lang_para = tk.Frame(self.tab_paragraph, bg=self.colors['gray_light'])
        frame_lang_para.pack(fill=tk.X, padx=15, pady=10)
        
        frame_lang_para_row = tk.Frame(frame_lang_para, bg=self.colors['gray_light'])
        frame_lang_para_row.pack(fill=tk.X)
        
        # Source language
        frame_src_lang_para = tk.Frame(frame_lang_para_row, bg=self.colors['gray_light'])
        frame_src_lang_para.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        
        label_src_lang_paragraph = tk.Label(
            frame_src_lang_para, text="Ngôn ngữ nguồn:",
            bg=self.colors['gray_light'], fg=self.colors['gray_dark'],
            font=('Segoe UI', 11, 'bold')
        )
        label_src_lang_paragraph.pack(anchor=tk.W, pady=(0, 5))
        
        self.src_lang_paragraph = tk.StringVar(value=config.default_src_lang)
        combobox_src_lang_paragraph = create_language_combobox(
            frame_src_lang_para, self.src_lang_paragraph,
            list(self.display_languages.keys()), self.colors
        )
        combobox_src_lang_paragraph.pack(fill=tk.X)
        
        # Destination language
        frame_dest_lang_para = tk.Frame(frame_lang_para_row, bg=self.colors['gray_light'])
        frame_dest_lang_para.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(10, 0))
        
        label_dest_lang_paragraph = tk.Label(
            frame_dest_lang_para, text="Ngôn ngữ đích:",
            bg=self.colors['gray_light'], fg=self.colors['gray_dark'],
            font=('Segoe UI', 11, 'bold')
        )
        label_dest_lang_paragraph.pack(anchor=tk.W, pady=(0, 5))
        
        self.dest_lang_paragraph = tk.StringVar(value=config.default_dest_lang)
        combobox_dest_lang_paragraph = create_language_combobox(
            frame_dest_lang_para, self.dest_lang_paragraph,
            list(self.display_languages.keys()), self.colors
        )
        combobox_dest_lang_paragraph.pack(fill=tk.X)
        
        # Buttons frame
        frame_buttons_para = tk.Frame(frame_lang_para, bg=self.colors['gray_light'])
        frame_buttons_para.pack(fill=tk.X, pady=10)
        
        button_translate_paragraph = create_styled_button(
            frame_buttons_para, text="Dịch nội dung",
            command=self.translate_paragraph, colors=self.colors
        )
        button_translate_paragraph.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        
        button_clear_paragraph = create_styled_button(
            frame_buttons_para, text="Xóa nội dung",
            command=self.clear_input_paragraph, colors=self.colors
        )
        button_clear_paragraph.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 5))

        # NEW: Analyze button
        button_analyze_paragraph = create_styled_button(
            frame_buttons_para, text="🔍 Phân tích ý nghĩa câu (AI)",
            command=self.analyze_paragraph, colors=self.colors
        )
        # Use a slightly different color or highlight if possible, but keep style consistent
        button_analyze_paragraph.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 0))
        
        # Context frame (NEW)
        frame_context = tk.Frame(self.tab_paragraph, bg=self.colors['gray_light'])
        frame_context.pack(fill=tk.X, padx=15, pady=(5, 0))
        
        tk.Label(frame_context, text="Bối cảnh/Ghi chú thêm (Tùy chọn):", 
                 bg=self.colors['gray_light'], font=('Segoe UI', 9, 'italic')).pack(side=tk.LEFT)
        self.entry_paragraph_context = tk.Entry(frame_context, font=('Segoe UI', 10), bg=self.colors['white'])
        self.entry_paragraph_context.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10)
        
        # Output frame
        frame_output = tk.Frame(self.tab_paragraph, bg=self.colors['gray_light'])
        frame_output.pack(fill=tk.BOTH, expand=True, padx=15, pady=10)
        
        label_paragraph_output = tk.Label(
            frame_output, text="Bản dịch:",
            bg=self.colors['gray_light'], fg=self.colors['gray_dark'],
            font=('Segoe UI', 11, 'bold')
        )
        label_paragraph_output.pack(anchor=tk.W, pady=(0, 5))
        
        self.entry_paragraph_output = tk.Text(
            frame_output, height=10, wrap=tk.WORD,
            bg=self.colors['white'], fg=self.colors['gray_dark'],
            font=('Times New Roman', 12), relief='solid', borderwidth=1,
            padx=10, pady=10
        )
        self.entry_paragraph_output.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        self.lbl_last_translation_source = tk.Label(
            frame_output, text="",
            bg=self.colors['gray_light'], fg=self.colors['navy'],
            font=('Segoe UI', 9, 'italic'), anchor=tk.W
        )
        self.lbl_last_translation_source.pack(fill=tk.X, pady=(0, 5))
        
        button_copy_paragraph = create_styled_button(
            frame_output, text="Sao chép đoạn văn đã dịch",
            command=self.copy_output_paragraph, colors=self.colors
        )
        button_copy_paragraph.pack(fill=tk.X)
    
    def setup_email_tab(self):
        """Setup email translation tab"""
        # Folder frame
        frame_folder = tk.Frame(self.tab_email, bg=self.colors['gray_light'])
        frame_folder.pack(fill=tk.X, padx=15, pady=15)
        
        label_folder_name = tk.Label(
            frame_folder, text="Nhập tên thư mục trong hòm thư cần dịch:",
            bg=self.colors['gray_light'], fg=self.colors['gray_dark'],
            font=('Segoe UI', 11, 'bold')
        )
        label_folder_name.pack(anchor=tk.W, pady=(0, 5))
        
        self.entry_folder_name = tk.Entry(
            frame_folder, width=50, font=('Segoe UI', 10),
            bg=self.colors['white'], fg=self.colors['gray_dark'],
            relief='solid', borderwidth=1
        )
        self.entry_folder_name.pack(fill=tk.X, pady=5)
        
        # Language frame
        frame_lang_email = tk.Frame(self.tab_email, bg=self.colors['gray_light'])
        frame_lang_email.pack(fill=tk.X, padx=15, pady=10)
        
        frame_lang_email_row = tk.Frame(frame_lang_email, bg=self.colors['gray_light'])
        frame_lang_email_row.pack(fill=tk.X)
        
        # Source language
        frame_src_lang_email = tk.Frame(frame_lang_email_row, bg=self.colors['gray_light'])
        frame_src_lang_email.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        
        label_src_lang_email = tk.Label(
            frame_src_lang_email, text="Ngôn ngữ nguồn:",
            bg=self.colors['gray_light'], fg=self.colors['gray_dark'],
            font=('Segoe UI', 11, 'bold')
        )
        label_src_lang_email.pack(anchor=tk.W, pady=(0, 5))
        
        self.src_lang_email = tk.StringVar(value=config.default_src_lang)
        combobox_src_lang_email = create_language_combobox(
            frame_src_lang_email, self.src_lang_email,
            list(self.display_languages.keys()), self.colors
        )
        combobox_src_lang_email.pack(fill=tk.X)
        
        # Destination language
        frame_dest_lang_email = tk.Frame(frame_lang_email_row, bg=self.colors['gray_light'])
        frame_dest_lang_email.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(10, 0))
        
        label_dest_lang_email = tk.Label(
            frame_dest_lang_email, text="Ngôn ngữ đích:",
            bg=self.colors['gray_light'], fg=self.colors['gray_dark'],
            font=('Segoe UI', 11, 'bold')
        )
        label_dest_lang_email.pack(anchor=tk.W, pady=(0, 5))
        
        self.dest_lang_email = tk.StringVar(value=config.default_dest_lang)
        combobox_dest_lang_email = create_language_combobox(
            frame_dest_lang_email, self.dest_lang_email,
            list(self.display_languages.keys()), self.colors
        )
        combobox_dest_lang_email.pack(fill=tk.X)
        
        # Info label
        label_info = tk.Label(
            self.tab_email,
            text=f"Chương trình có thể dịch được {config.max_emails_to_translate} mail mới nhất chứa bộ lọc trong thư mục được cấu hình",
            bg=self.colors['gray_light'], fg=self.colors['gray_medium'],
            font=('Segoe UI', 9), justify=tk.LEFT
        )
        label_info.pack(padx=15, pady=10)
        
        # Button frame
        frame_button_email = tk.Frame(self.tab_email, bg=self.colors['gray_light'])
        frame_button_email.pack(fill=tk.X, padx=15, pady=15)
        
        button_translate_email = create_styled_button(
            frame_button_email, text="Dịch Email",
            command=self.translate_email, colors=self.colors
        )
        button_translate_email.pack(fill=tk.X)
    
    def setup_image_tab(self):
        """Setup image translation tab"""
        # Image selection frame
        frame_image_select = tk.Frame(self.tab_image, bg=self.colors['gray_light'])
        frame_image_select.pack(fill=tk.X, padx=15, pady=10)
        
        label_image_path = tk.Label(
            frame_image_select, text="Chọn File ảnh:",
            bg=self.colors['gray_light'], fg=self.colors['gray_dark'],
            font=('Segoe UI', 11, 'bold')
        )
        label_image_path.pack(anchor=tk.W, pady=(0, 5))
        
        frame_image_entry = tk.Frame(frame_image_select, bg=self.colors['gray_light'])
        frame_image_entry.pack(fill=tk.X, pady=5)
        
        self.entry_image_path = tk.Entry(
            frame_image_entry, width=55, font=('Segoe UI', 10),
            bg=self.colors['white'], fg=self.colors['gray_dark'],
            relief='solid', borderwidth=1
        )
        self.entry_image_path.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        
        button_browse_image = create_styled_button(
            frame_image_entry, text="Duyệt...",
            command=self.browse_image, colors=self.colors
        )
        button_browse_image.pack(side=tk.LEFT)
        
        # Paste from clipboard frame
        frame_paste_clipboard = tk.Frame(self.tab_image, bg=self.colors['gray_light'])
        frame_paste_clipboard.pack(fill=tk.X, padx=15, pady=10)
        
        button_paste_clipboard = create_styled_button(
            frame_paste_clipboard, text="Dán từ Clipboard (Bấm vào nút để dán ảnh)",
            command=self.paste_image_from_clipboard, colors=self.colors
        )
        button_paste_clipboard.pack(side=tk.LEFT, padx=(0, 10))
        
        self.label_clipboard_status = tk.Label(
            frame_paste_clipboard,
            text="Chưa có ảnh từ clipboard",
            bg=self.colors['gray_light'], fg=self.colors['gray_medium'],
            font=('Segoe UI', 9)
        )
        self.label_clipboard_status.pack(side=tk.LEFT)
        
        # Preview frame
        frame_preview = tk.Frame(self.tab_image, bg=self.colors['gray_light'])
        frame_preview.pack(fill=tk.X, padx=15, pady=10)
        
        label_preview_title = tk.Label(
            frame_preview, text="Preview ảnh:",
            bg=self.colors['gray_light'], fg=self.colors['gray_dark'],
            font=('Segoe UI', 11, 'bold')
        )
        label_preview_title.pack(anchor=tk.W, pady=(0, 5))
        
        self.label_image_preview = tk.Label(
            frame_preview,
            text="Chua co anh de hien thi",
            bg=self.colors['white'], fg=self.colors['gray_medium'],
            font=('Segoe UI', 9),
            relief='solid', borderwidth=1,
            width=40, height=10
        )
        self.label_image_preview.pack(fill=tk.X, pady=5)
        
        # Language frame
        frame_lang_image = tk.Frame(self.tab_image, bg=self.colors['gray_light'])
        frame_lang_image.pack(fill=tk.X, padx=15, pady=10)
        
        frame_lang_image_row = tk.Frame(frame_lang_image, bg=self.colors['gray_light'])
        frame_lang_image_row.pack(fill=tk.X)
        
        # Source language
        frame_src_lang_image = tk.Frame(frame_lang_image_row, bg=self.colors['gray_light'])
        frame_src_lang_image.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        
        label_src_lang_image = tk.Label(
            frame_src_lang_image, text="Ngôn ngữ nguồn:",
            bg=self.colors['gray_light'], fg=self.colors['gray_dark'],
            font=('Segoe UI', 11, 'bold')
        )
        label_src_lang_image.pack(anchor=tk.W, pady=(0, 5))
        
        self.src_lang_image = tk.StringVar(value=config.default_src_lang)
        combobox_src_lang_image = create_language_combobox(
            frame_src_lang_image, self.src_lang_image,
            list(self.display_languages.keys()), self.colors
        )
        combobox_src_lang_image.pack(fill=tk.X)
        
        # Destination language
        frame_dest_lang_image = tk.Frame(frame_lang_image_row, bg=self.colors['gray_light'])
        frame_dest_lang_image.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(10, 0))
        
        label_dest_lang_image = tk.Label(
            frame_dest_lang_image, text="Ngôn ngữ đích:",
            bg=self.colors['gray_light'], fg=self.colors['gray_dark'],
            font=('Segoe UI', 11, 'bold')
        )
        label_dest_lang_image.pack(anchor=tk.W, pady=(0, 5))
        
        self.dest_lang_image = tk.StringVar(value=config.default_dest_lang)
        combobox_dest_lang_image = create_language_combobox(
            frame_dest_lang_image, self.dest_lang_image,
            list(self.display_languages.keys()), self.colors
        )
        combobox_dest_lang_image.pack(fill=tk.X)
        
        # Info label
        label_info_image = tk.Label(
            self.tab_image,
            text="Chương trình sẽ OCR text trong ảnh và dịch sang ngôn ngữ đích",
            bg=self.colors['gray_light'], fg=self.colors['gray_medium'],
            font=('Segoe UI', 9), justify=tk.LEFT
        )
        label_info_image.pack(padx=15, pady=10)
        
        # Button frame
        frame_button_image = tk.Frame(self.tab_image, bg=self.colors['gray_light'])
        frame_button_image.pack(fill=tk.X, padx=15, pady=10)
        
        button_translate_image = create_styled_button(
            frame_button_image, text="OCR và Dịch ảnh",
            command=self.translate_image, colors=self.colors
        )
        button_translate_image.pack(fill=tk.X, pady=(0, 10))
        
        # Result frame
        frame_result = tk.Frame(self.tab_image, bg=self.colors['gray_light'])
        frame_result.pack(fill=tk.BOTH, expand=True, padx=15, pady=5)
        
        # Context frame for AI Analysis (NEW)
        frame_image_context = tk.Frame(frame_result, bg=self.colors['gray_light'])
        frame_image_context.pack(fill=tk.X, pady=(0, 5))
        
        tk.Label(frame_image_context, text="Bối cảnh/Ghi chú thêm (AI):", 
                 bg=self.colors['gray_light'], font=('Segoe UI', 9, 'italic')).pack(side=tk.LEFT)
        self.entry_image_context = tk.Entry(frame_image_context, font=('Segoe UI', 10), bg=self.colors['white'])
        self.entry_image_context.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10)
        
        button_analyze_image = create_styled_button(
            frame_image_context, text="🔍 Phân tích AI",
            command=self.analyze_image_text, colors=self.colors
        )
        button_analyze_image.pack(side=tk.RIGHT)

        # Output area
        
        label_text_output = tk.Label(
            frame_result, text="Kết quả OCR và Dịch:",
            bg=self.colors['gray_light'], fg=self.colors['gray_dark'],
            font=('Segoe UI', 11, 'bold')
        )
        label_text_output.pack(anchor=tk.W, pady=(0, 5))
        
        self.text_output = tk.Text(
            frame_result, height=15, wrap=tk.WORD,
            bg=self.colors['white'], fg=self.colors['gray_dark'],
            font=('Times New Roman', 12), relief='solid', borderwidth=1,
            padx=10, pady=10
        )
        self.text_output.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        button_save_image_text = create_styled_button(
            frame_result, text="Lưu Kết Quả",
            command=self.save_translated_image_text, colors=self.colors
        )
        button_save_image_text.pack(fill=tk.X)
        
        # Bind Ctrl+V for paste (bind to both tab and notebook for better coverage)
        self.tab_image.bind('<Control-v>', lambda e: self.paste_image_from_clipboard())
        self.notebook.bind('<Control-v>', self._handle_ctrl_v_paste)
    
    # Event handlers
    def _handle_ctrl_v_paste(self, event):
        """Handle Ctrl+V paste - only if on image tab"""
        current_tab = self.notebook.index(self.notebook.select())
        if current_tab == 3:  # Image tab is index 3 (0=File, 1=Paragraph, 2=Email, 3=Image)
            self.paste_image_from_clipboard()
    
    def browse_file(self):
        """Browse for file"""
        file_path = filedialog.askopenfilename(filetypes=[("All Files", "*.*")])
        if file_path:
            self.entry_file_path.delete(0, tk.END)
            self.entry_file_path.insert(0, file_path)
    
    def translate_file(self):
        """Translate selected file"""
        file_path = self.entry_file_path.get()
        src_lang = self.src_lang_file.get()
        dest_lang = self.dest_lang_file.get()
        
        # Validate
        try:
            FileValidator.validate_file(file_path)
            LanguageValidator.validate_language_pair(src_lang, dest_lang)
        except Exception as e:
            messagebox.showerror("Lỗi", str(e))
            return
        
        # Determine file type and output
        base, ext = os.path.splitext(file_path)
        ext_lower = ext.lower()
        today_str = datetime.now().strftime("%Y%m%d")
        
        use_ai_vision = (ext_lower == '.pdf' and self.use_ai_vision_for_pdf.get())
        use_pdf_experimental = (ext_lower == '.pdf' and self.use_experimental_pdf_output.get())

        # Show PDF AI Vision guide if it's a PDF file and get user's choice
        if ext_lower == '.pdf' and not use_ai_vision and not use_pdf_experimental:
            user_choice = self._show_pdf_ai_guide_and_wait()
            if user_choice is None:
                # User closed dialog without making a choice - cancel translation
                logger.info("User cancelled PDF translation dialog")
                return
            # user_choice is already reflected in self.use_ai_vision_for_pdf
            use_ai_vision = self.use_ai_vision_for_pdf.get()

        
        handlers_map = {
            '.xlsx': (self.excel_handler, '.xlsx'),
            '.xls': (self.excel_handler, '.xlsx'),
            '.docx': (self.word_handler, '.docx'),
            '.doc': (self.word_handler, '.docx'),
            '.pptx': (self.powerpoint_handler, '.pptx'),
            '.ppt': (self.powerpoint_handler, '.pptx'),
            '.txt': (self.text_handler, '.txt'),
            '.pdf': (self.pdf_handler, '.docx')
        }
        
        if ext_lower not in handlers_map:
            messagebox.showerror(
                "Lỗi",
                f"Loại file '{ext}' không được hỗ trợ.\n\n"
                f"Các định dạng được hỗ trợ:\n"
                f"- Excel: .xlsx, .xls\n"
                f"- Word: .docx, .doc\n"
                f"- PowerPoint: .pptx, .ppt\n"
                f"- Text: .txt\n"
                f"- PDF: .pdf"
            )
            return
        
        handler, output_ext = handlers_map[ext_lower]
        if use_pdf_experimental:
            output_ext = '.pdf'
        output_file = f"{base}_translated_{today_str}{output_ext}"
        pages_per_batch = int(self.ai_vision_pages_per_batch.get()) if use_ai_vision else 4
        
        # Prepare progress update function

        def update_progress(text, value=None):
            def _update():
                self.label_file_status.config(text=text)
                if value is not None:
                    self.progress_file.config(mode='determinate')
                    self.progress_file['value'] = value
                self.update_idletasks()
            self.after(0, _update)

        # Show progress indicator
        self.progress_file.stop()
        self.progress_file.config(mode='determinate', value=0)
        
        if use_ai_vision:
            update_progress(f"⚙️ Đang chuẩn bị dịch AI Vision ({pages_per_batch} trang/batch)...", 2)
        elif use_pdf_experimental:
            update_progress("⚙️ Đang chuẩn bị xuất PDF thử nghiệm...", 2)
        else:
            update_progress(f"Đang chuẩn bị dịch '{os.path.basename(file_path)}'...", 2)
        
        # Translate in thread to avoid blocking UI
        def translate_thread():
            try:
                # Set progress callback for handlers
                if hasattr(handler, 'progress_callback'):
                    handler.progress_callback = update_progress
                
                # Use AI Vision for PDF if checkbox is checked
                if use_ai_vision:
                    self.pdf_handler.progress_callback = update_progress
                    self.pdf_handler.translate_with_ai_vision(
                        file_path, output_file, src_lang, dest_lang,
                        pages_per_batch=pages_per_batch
                    )
                elif use_pdf_experimental:
                    self.pdf_handler.progress_callback = update_progress
                    self.pdf_handler.translate_to_pdf_experimental(
                        file_path, output_file, src_lang, dest_lang
                    )
                    self._remember_pdf_report_context(file_path, output_file)
                else:
                    handler.translate(file_path, output_file, src_lang, dest_lang)

                # Stop progress and show success
                def _on_success():
                    self.progress_file['value'] = 100
                    if use_ai_vision:
                        method_info = " (AI Vision)"
                    elif use_pdf_experimental:
                        method_info = " (PDF thử nghiệm)"
                    else:
                        method_info = ""
                    self.label_file_status.config(text="🟢 Hoàn tất!")
                    if use_pdf_experimental:
                        self._update_pdf_report_export_state()
                    messagebox.showinfo(
"Thành công",
                        f"File '{os.path.basename(file_path)}' đã được dịch{method_info}.\n\n"
                        f"Đã lưu kết quả tại:\n{output_file}"
                    )
                    self.label_file_status.config(text="")
                    self.progress_file.config(mode='indeterminate')
                    self.progress_file.stop()
                
                self.after(0, _on_success)
                
            except Exception as e:
                # Stop progress and show error
                def _on_error():
                    self.progress_file.config(mode='indeterminate')
                    self.progress_file.stop()
                    self.label_file_status.config(text="")
                    if use_pdf_experimental and self.pdf_handler.last_pdf_qa_report:
                        self._remember_pdf_report_context(file_path, output_file)
                        self._update_pdf_report_export_state()
                    if use_pdf_experimental and isinstance(e, FileProcessingError):
                        error_msg = "PDF này không phù hợp với chế độ thử nghiệm. Vui lòng dùng chế độ DOCX ổn định."
                    else:
                        error_msg = handle_translation_error(e, "Dịch file")
                    messagebox.showerror("Lỗi", error_msg)
                
                self.after(0, _on_error)
        
        threading.Thread(target=translate_thread, daemon=True).start()

    @staticmethod
    def _get_pdf_report_export_notice() -> str:
        return (
            "Báo cáo này giúp kiểm tra số block dịch, vùng được bảo vệ, cảnh báo overflow "
            "và visual diff. Đây không phải chứng nhận giữ layout tuyệt đối."
        )

    @staticmethod
    def _get_pdf_report_export_hint() -> str:
        return "Chưa có báo cáo PDF thử nghiệm. Hãy chạy dịch PDF thử nghiệm trước."

    def _remember_pdf_report_context(self, input_file: str, output_file: str) -> None:
        self.last_pdf_report_input_file = input_file
        self.last_pdf_report_output_file = output_file

    def _has_exportable_pdf_report(self) -> bool:
        return bool(self.pdf_handler.last_pdf_qa_report)

    def _update_pdf_report_export_state(self) -> None:
        has_report = self._has_exportable_pdf_report()
        button_state = tk.NORMAL if has_report else tk.DISABLED
        self.btn_export_pdf_report_json.config(state=button_state)
        self.btn_export_pdf_report_html.config(state=button_state)
        hint_text = (
            "Đã có báo cáo PDF thử nghiệm công khai an toàn. Bạn có thể xuất JSON hoặc HTML."
            if has_report
            else self._get_pdf_report_export_hint()
        )
        self.label_pdf_report_hint.config(text=hint_text)

    def _build_pdf_report_bundle(self):
        if not self._has_exportable_pdf_report():
            return None
        return build_pdf_regression_report_bundle(
            qa_report=dict(self.pdf_handler.last_pdf_qa_report or {}),
            metadata={
                "input_file": self.last_pdf_report_input_file,
                "output_file": self.last_pdf_report_output_file,
            },
        )

    def _export_pdf_report(self, report_type: str) -> Optional[str]:
        if not self._has_exportable_pdf_report():
            messagebox.showwarning("Cảnh báo", self._get_pdf_report_export_hint())
            self._update_pdf_report_export_state()
            return None

        report_config = {
            "json": {
                "title": "Xuất báo cáo PDF thử nghiệm dạng JSON",
                "extension": ".json",
                "filename": "pdf_regression_report.json",
                "filetypes": [("JSON Files", "*.json"), ("All Files", "*.*")],
                "exporter": export_pdf_regression_report_json,
                "success": "Đã xuất báo cáo PDF thử nghiệm dạng JSON tại:\n{path}",
            },
            "html": {
                "title": "Xuất báo cáo PDF thử nghiệm dạng HTML",
                "extension": ".html",
                "filename": "pdf_regression_report.html",
                "filetypes": [("HTML Files", "*.html"), ("All Files", "*.*")],
                "exporter": export_pdf_regression_report_html,
                "success": "Đã xuất báo cáo PDF thử nghiệm dạng HTML tại:\n{path}",
            },
        }
        config = report_config[report_type]
        output_path = filedialog.asksaveasfilename(
            title=config["title"],
            defaultextension=config["extension"],
            initialfile=config["filename"],
            filetypes=config["filetypes"],
        )
        if not output_path:
            return None

        bundle = self._build_pdf_report_bundle()
        if bundle is None:
            messagebox.showwarning("Cảnh báo", self._get_pdf_report_export_hint())
            self._update_pdf_report_export_state()
            return None

        try:
            config["exporter"](bundle, output_path)
        except Exception as exc:
            logger.error("Failed to export PDF regression report: %s", exc)
            messagebox.showerror(
                "Lỗi",
                "Không thể xuất báo cáo PDF thử nghiệm. Vui lòng kiểm tra đường dẫn lưu và thử lại.",
            )
            return None

        messagebox.showinfo("Thành công", config["success"].format(path=output_path))
        return output_path

    def export_pdf_report_json(self) -> Optional[str]:
        return self._export_pdf_report("json")

    def export_pdf_report_html(self) -> Optional[str]:
        return self._export_pdf_report("html")


    
    def translate_paragraph(self):
        """Translate paragraph"""
        input_text = self.entry_paragraph_input.get("1.0", tk.END).strip()
        if not input_text:
            messagebox.showwarning("Cảnh báo", "Vui lòng nhập đoạn văn để dịch.")
            return
        
        src_lang = self.src_lang_paragraph.get()
        dest_lang = self.dest_lang_paragraph.get()
        
        try:
            LanguageValidator.validate_language_pair(src_lang, dest_lang)
            translated_text = self.translation_service.translate_text(input_text, src_lang, dest_lang)
            self.entry_paragraph_output.delete("1.0", tk.END)
            self.entry_paragraph_output.insert(tk.END, translated_text)
            
            # Show translation source telemetry
            metadata = self.translation_service.last_translation_metadata
            provider = metadata.get("provider", "")
            model = metadata.get("model", "")
            fallbacks = metadata.get("fallback_count", 0)
            
            if provider:
                display_provider = {
                    "gemini": "Gemini AI",
                    "chatanywhere": "ChatAnyWhere",
                    "deepseek": "DeepSeek",
                    "nvidia_nim": "NVIDIA NIM",
                    "openai_compatible": "OpenAI tùy chỉnh",
                    "google": "Google Translate",
                    "translation_memory": "Bộ nhớ dịch (TM Cache)"
                }.get(provider, provider)
                
                text_info = f"Được dịch bởi: {display_provider}"
                if model and model != "none":
                    text_info += f" / {model}"
                if fallbacks > 0:
                    text_info += f" (Fallback: {fallbacks} lần)"
                self.lbl_last_translation_source.config(text=text_info)
            else:
                self.lbl_last_translation_source.config(text="")
        except Exception as e:
            error_msg = handle_translation_error(e, "Dịch đoạn văn")
            messagebox.showerror("Lỗi", error_msg)

    def analyze_paragraph(self):
        """Analyze paragraph meaning using AI"""
        input_text = self.entry_paragraph_input.get("1.0", tk.END).strip()
        context = self.entry_paragraph_context.get().strip()
        
        if not input_text:
            messagebox.showwarning("Cảnh báo", "Vui lòng nhập đoạn văn để phân tích.")
            return
        
        src_lang = self.src_lang_paragraph.get()
        dest_lang = self.dest_lang_paragraph.get()
        
        # Show waiting status
        self.entry_paragraph_output.delete("1.0", tk.END)
        self.entry_paragraph_output.insert(tk.END, "⏳ Đang phân tích chuyên sâu... Vui lòng đợi trong giây lát...")
        self.update()

        def run_analysis():
            try:
                from translation_app.core.ai_service import get_ai_service
                ai_service = get_ai_service()
                
                if not ai_service.is_available():
                    self.after(0, lambda: messagebox.showwarning("Yêu cầu cấu hình", "Vui lòng cấu hình Gemini API Key trong tab 'Cấu hình AI' để sử dụng tính năng này."))
                    self.after(0, lambda: self.entry_paragraph_output.delete("1.0", tk.END))
                    return

                result = ai_service.analyze_sentence(input_text, src_lang, dest_lang, context)
                
                if result.get("status") == "success":
                    analysis_text = result["text"]
                    self.after(0, lambda: self._display_analysis(analysis_text))
                else:
                    self.after(0, lambda: messagebox.showerror("Lỗi AI", f"Không thể phân tích: {result.get('text')}"))
                    self.after(0, lambda: self.entry_paragraph_output.delete("1.0", tk.END))
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Lỗi", f"Đã xảy ra lỗi khi phân tích: {str(e)}"))
                self.after(0, lambda: self.entry_paragraph_output.delete("1.0", tk.END))

        threading.Thread(target=run_analysis, daemon=True).start()

    def _display_analysis(self, text):
        self.entry_paragraph_output.delete("1.0", tk.END)
        self.entry_paragraph_output.insert(tk.END, text)
    
    def clear_input_paragraph(self):
        """Clear paragraph input"""
        self.entry_paragraph_input.delete("1.0", tk.END)
    
    def copy_output_paragraph(self):
        """Copy translated paragraph to clipboard"""
        output_text = self.entry_paragraph_output.get("1.0", tk.END)
        self.clipboard_clear()
        self.clipboard_append(output_text)
        self.update()
    
    def translate_email(self):
        """Translate emails"""
        folder_name = self.entry_folder_name.get().strip()
        src_lang = self.src_lang_email.get()
        dest_lang = self.dest_lang_email.get()
        
        if not folder_name:
            messagebox.showwarning("Cảnh báo", "Vui lòng nhập tên thư mục.")
            return
        
        try:
            LanguageValidator.validate_language_pair(src_lang, dest_lang)
            
            def translate_thread():
                try:
                    count = self.email_handler.translate_latest_unread_emails(
                        folder_name, src_lang, dest_lang
                    )
                    self.after(0, lambda: messagebox.showinfo(
"Thành công",
                        f"{count} email mới nhất chứa bộ lọc đã được dịch và gửi thành công."
                    ))
                except Exception as e:
                    error_msg = handle_translation_error(e, "Dịch email")
                    self.after(0, lambda: messagebox.showerror("Lỗi", error_msg))
            
            threading.Thread(target=translate_thread, daemon=True).start()
        except Exception as e:
            messagebox.showerror("Lỗi", str(e))
    
    def browse_image(self):
        """Browse for image file"""
        file_path = filedialog.askopenfilename(
            filetypes=[("Image Files", "*.png *.jpg *.jpeg *.bmp *.gif *.tiff *.webp"), ("All Files", "*.*")]
        )
        if file_path:
            # Clear clipboard image when selecting file
            self.clipboard_image = None
            self.preview_photo = None
            self.label_image_preview.config(image='', text="Chua co anh de hien thi")
            self.label_clipboard_status.config(text="Chưa có ảnh từ clipboard")
            
            self.entry_image_path.delete(0, tk.END)
            self.entry_image_path.insert(0, file_path)
    
    def paste_image_from_clipboard(self):
        """Paste image from clipboard"""
        try:
            # Get image from clipboard
            clipboard_img = ImageGrab.grabclipboard()
            
            if clipboard_img is None:
                messagebox.showwarning(
                    "Cảnh báo",
                    "Clipboard không chứa ảnh.\n\n"
                    "Vui lòng copy ảnh vào clipboard trước (screenshot hoặc copy ảnh từ ứng dụng khác)."
                )
                return
            
            # Check if it's actually an image
            if not isinstance(clipboard_img, Image.Image):
                messagebox.showwarning(
                    "Cảnh báo",
                    "Clipboard không chứa ảnh hợp lệ.\n\n"
                    "Vui lòng copy ảnh vào clipboard trước."
                )
                return
            
            # Convert to RGB if needed
            if clipboard_img.mode != 'RGB':
                clipboard_img = clipboard_img.convert('RGB')
            
            # Save to instance variable
            self.clipboard_image = clipboard_img
            
            # Update entry to show clipboard status
            self.entry_image_path.delete(0, tk.END)
            self.entry_image_path.insert(0, "[Clipboard]")
            
            # Update status label
            width, height = clipboard_img.size
            self.label_clipboard_status.config(
                text=f"Đã paste ảnh từ clipboard ({width}x{height}px)",
                fg=self.colors['gray_dark']
            )
            
            # Create preview
            self._update_image_preview(clipboard_img)
            
            logger.info(f"Pasted image from clipboard: {width}x{height}px")
            
        except Exception as e:
            error_msg = f"Lỗi khi lấy ảnh từ clipboard: {str(e)}"
            logger.error(error_msg, exc_info=True)
            messagebox.showerror("Lỗi", error_msg)
    
    def _update_image_preview(self, image: Image.Image):
        """Update image preview label"""
        try:
            # Resize image for preview (max width 300px, maintain aspect ratio)
            max_width = 300
            width, height = image.size
            
            if width > max_width:
                ratio = max_width / width
                new_width = max_width
                new_height = int(height * ratio)
                preview_img = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
            else:
                preview_img = image.copy()
            
            # Convert to PhotoImage for Tkinter
            # Lưu reference để tránh garbage collection - Tkinter cần giữ reference
            self.preview_photo = ImageTk.PhotoImage(preview_img)
            self._preview_photo_refs.append(self.preview_photo)  # Giữ reference thêm một lần nữa
            
            # Giới hạn số lượng references để tránh memory leak
            if len(self._preview_photo_refs) > 10:
                self._preview_photo_refs.pop(0)
            
            # Update label
            self.label_image_preview.config(
                image=self.preview_photo,
                text=''
            )
            
        except Exception as e:
            logger.error(f"Error updating image preview: {e}", exc_info=True)
            self.label_image_preview.config(
                image='',
                text=f"Lỗi hiển thị preview: {str(e)}"
            )
    
    def translate_image(self):
        """Translate image with OCR"""
        src_lang = self.src_lang_image.get()
        dest_lang = self.dest_lang_image.get()
        
        # Check if using clipboard image or file
        img = None
        if self.clipboard_image is not None:
            # Use clipboard image
            img = self.clipboard_image.copy()
            image_source = "clipboard"
        else:
            # Use file path
            image_path = self.entry_image_path.get()
            if not image_path or image_path == "[Clipboard]":
                messagebox.showerror("Lỗi", "Vui lòng chọn file ảnh hoặc dán ảnh từ clipboard để dịch.")
                return
            
            if not os.path.exists(image_path):
                messagebox.showerror("Lỗi", "File ảnh không tồn tại.")
                return
            
            # Read image from file
            try:
                img = Image.open(image_path)
                image_source = image_path
            except Exception as e:
                messagebox.showerror("Lỗi", f"Không thể đọc file ảnh: {str(e)}")
                return
        
        # Validate that we have an image
        if img is None:
            messagebox.showerror("Lỗi", "Không thể tải ảnh để dịch.")
            return
        
        if not self.ocr_handler.is_installed():
            messagebox.showerror(
                "Lỗi",
                "Tesseract OCR chưa được cài đặt!\n\n"
                "Để dịch được text trong ảnh, bạn cần:\n"
                "1. Tải và cài đặt Tesseract OCR từ:\n"
                "   https://github.com/UB-Mannheim/tesseract/wiki\n"
                "2. Tải language pack phù hợp từ:\n"
                "   https://github.com/tesseract-ocr/tessdata\n"
                "3. Đặt file traineddata vào thư mục tessdata của Tesseract"
            )
            return
        
        def translate_thread():
            try:
                # Work with a local copy to avoid closure issues
                working_img = img.copy() if img is not None else None
                if working_img is None:
                    self.after(0, lambda: messagebox.showerror("Lỗi", "Không thể tải ảnh để dịch."))
                    return
                
                # Ensure image is RGB
                if working_img.mode != 'RGB':
                    working_img = working_img.convert('RGB')
                
                # OCR
                self.after(0, lambda: self.text_output.delete("1.0", tk.END))
                self.after(0, lambda: self.text_output.insert(tk.END, "Đang OCR ảnh...\n"))
                self.after(0, lambda: self.update())
                
                ocr_lang = self.ocr_handler.get_ocr_language(src_lang)
                try:
                    text = self.ocr_handler.extract_text_from_image(working_img, lang=ocr_lang)
                except Exception:
                    text = self.ocr_handler.extract_text_from_image(working_img, lang='eng')
                
                self.last_ocr_text = text # Save for AI analysis
                
                if not text.strip():
                    self.after(0, lambda: self.text_output.delete("1.0", tk.END))
                    self.after(0, lambda: self.text_output.insert(tk.END, "Không tìm thấy text trong ảnh."))
                    self.after(0, lambda: messagebox.showwarning("Cảnh báo", "Không tìm thấy text trong ảnh."))
                    return
                
                # Display original text
                self.after(0, lambda: self.text_output.delete("1.0", tk.END))
                self.after(0, lambda: self.text_output.insert(tk.END, f"Text gốc ({src_lang}):\n"))
                self.after(0, lambda: self.text_output.insert(tk.END, "-" * 50 + "\n"))
                self.after(0, lambda: self.text_output.insert(tk.END, text + "\n\n"))
                
                # Translate
                self.after(0, lambda: self.text_output.insert(tk.END, "Đang dịch...\n"))
                self.after(0, lambda: self.update())
                
                translated_text = self.translation_service.translate_long_text(text, src_lang, dest_lang)
                
                # Display translated text
                self.after(0, lambda: self.text_output.insert(tk.END, f"Text dịch ({dest_lang}):\n"))
                self.after(0, lambda: self.text_output.insert(tk.END, "-" * 50 + "\n"))
                self.after(0, lambda: self.text_output.insert(tk.END, translated_text))
                self.after(0, lambda: messagebox.showinfo("Thành công", "Đã OCR và dịch ảnh thành công!"))
            except Exception as e:
                error_msg = handle_translation_error(e, "OCR và dịch ảnh")
                self.after(0, lambda: self.text_output.delete("1.0", tk.END))
                self.after(0, lambda: self.text_output.insert(tk.END, error_msg))
                self.after(0, lambda: messagebox.showerror("Lỗi", error_msg))
        
        threading.Thread(target=translate_thread, daemon=True).start()
    
    def save_translated_image_text(self):
        """Save translated image text to file"""
        text = self.text_output.get("1.0", tk.END).strip()
        if not text:
            messagebox.showwarning("Cảnh báo", "Không có nội dung để lưu.")
            return
        
        # Determine output file name
        if self.clipboard_image is not None:
            # Use clipboard - suggest default name
            default_name = f"clipboard_translated_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            output_file = filedialog.asksaveasfilename(
                defaultextension=".txt",
                initialfile=default_name,
                filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")]
            )
            if not output_file:
                return
        else:
            image_path = self.entry_image_path.get()
            if image_path and image_path != "[Clipboard]":
                base, ext = os.path.splitext(image_path)
                output_file = f"{base}_translated_{datetime.now().strftime('%Y%m%d')}.txt"
            else:
                output_file = filedialog.asksaveasfilename(
                    defaultextension=".txt",
                    filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")]
                )
                if not output_file:
                    return
        
        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(text)
            messagebox.showinfo("Thành công", f"Đã lưu kết quả tại:\n{output_file}")
        except Exception as e:
            messagebox.showerror("Lỗi", f"Không thể lưu file: {str(e)}")
    
    def _open_ai_settings(self):
        """Open the AI Settings dialog."""
        from translation_app.ui.ai_settings_dialog import AISettingsDialog
        AISettingsDialog(self)
    
    def analyze_image_text(self):
        """Analyze image OCR text meaning using AI"""
        input_text = self.last_ocr_text.strip()
        context = self.entry_image_context.get().strip()
        
        if not input_text:
            messagebox.showwarning("Cảnh báo", "Vui lòng 'OCR và Dịch ảnh' trước khi yêu cầu phân tích.")
            return
        
        src_lang = self.src_lang_image.get()
        dest_lang = self.dest_lang_image.get()
        
        # Show waiting status
        self.text_output.delete("1.0", tk.END)
        self.text_output.insert(tk.END, "⏳ Đang phân tích chuyên sâu nội dung ảnh... Vui lòng đợi trong giây lát...")
        self.update()

        def run_analysis():
            try:
                from translation_app.core.ai_service import get_ai_service
                ai_service = get_ai_service()
                
                if not ai_service.is_available():
                    self.after(0, lambda: messagebox.showwarning("Yêu cầu cấu hình", "Vui lòng cấu hình Gemini API Key trong tab 'Cấu hình AI' để sử dụng tính năng này."))
                    self.after(0, lambda: self.text_output.delete("1.0", tk.END))
                    return

                result = ai_service.analyze_sentence(input_text, src_lang, dest_lang, context)
                
                if result.get("status") == "success":
                    analysis_text = result["text"]
                    self.after(0, lambda: self._display_image_analysis(analysis_text))
                else:
                    self.after(0, lambda: messagebox.showerror("Lỗi AI", f"Không thể phân tích: {result.get('text')}"))
                    self.after(0, lambda: self.text_output.delete("1.0", tk.END))
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Lỗi", f"Đã xảy ra lỗi khi phân tích: {str(e)}"))
                self.after(0, lambda: self.text_output.delete("1.0", tk.END))

        threading.Thread(target=run_analysis, daemon=True).start()

    def _display_image_analysis(self, text):
        self.text_output.delete("1.0", tk.END)
        self.text_output.insert(tk.END, "=== BẢN PHÂN TÍCH NGHĨA CHUYÊN SÂU (AI) ===\n\n")
        self.text_output.insert(tk.END, text)
    
    def _show_pdf_ai_guide_and_wait(self):
        """
        Show a detailed guide for PDF AI Vision translation and WAIT for user's choice.
        Uses wait_window() to block until user makes a decision.
        
        Returns:
            True: User chose to use AI Vision (ai checkbox is now True)
            False: User chose to continue with normal translation
            None: User cancelled/closed dialog without making a choice
        """
        import webbrowser
        from translation_app.core.ai_service import get_ai_service
        
        logger.info("Showing PDF AI Vision guide dialog")
        
        # Check if AI is already configured
        ai_service = get_ai_service()
        ai_configured = ai_service.is_available()
        
        # Track user's choice using a mutable container
        user_choice = {'value': None}  # None = cancelled, True = use AI, False = normal
        
        # Create guide dialog
        guide_dialog = tk.Toplevel(self)
        guide_dialog.title("💡 Gợi ý: Dịch PDF tốt hơn với AI Vision")
        guide_dialog.geometry("650x580")
        guide_dialog.configure(bg=self.colors['white'])
        guide_dialog.transient(self)
        guide_dialog.grab_set()
        
        # Handle window close (X button) - treat as cancel
        def on_dialog_close():
            user_choice['value'] = None
            guide_dialog.destroy()
        
        guide_dialog.protocol("WM_DELETE_WINDOW", on_dialog_close)
        
        # Center the dialog
        guide_dialog.update_idletasks()
        x = (guide_dialog.winfo_screenwidth() // 2) - (650 // 2)
        y = (guide_dialog.winfo_screenheight() // 2) - (580 // 2)
        guide_dialog.geometry(f"+{x}+{y}")
        
        # Main frame with padding
        main_frame = tk.Frame(guide_dialog, bg=self.colors['white'], padx=20, pady=15)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Title
        title_label = tk.Label(
            main_frame,
            text="🤖 Bạn đang dịch file PDF",
            font=('Segoe UI', 14, 'bold'),
            bg=self.colors['white'], fg=self.colors['gray_dark']
        )
        title_label.pack(anchor=tk.W, pady=(0, 10))
        
        # Why AI Vision is better
        why_frame = tk.LabelFrame(
            main_frame,
            text="📊 Tại sao nên dùng AI Vision?",
            font=('Segoe UI', 10, 'bold'),
            bg=self.colors['white'], fg=self.colors['gray_dark'],
            padx=10, pady=10
        )
        why_frame.pack(fill=tk.X, pady=(0, 10))
        
        why_text = """- PDF thường rất khó dịch chính xác (bảng bị vỡ, mất format, thiếu nội dung).
- AI Vision có thể hỗ trợ đọc PDF scan/ảnh tốt hơn OCR thường trong một số trường hợp. Tuy nhiên, khả năng giữ nguyên layout/format PDF chưa được audit đầy đủ. Vui lòng kiểm tra file đầu ra trước khi dùng chính thức.
- AI hiểu ngữ cảnh và có thể giúp dịch thuật ngữ kỹ thuật tốt hơn trong một số tình huống."""

        tk.Label(
            why_frame, text=why_text,
            font=('Segoe UI', 9), justify=tk.LEFT,
            bg=self.colors['white'], fg=self.colors['gray_dark']
        ).pack(anchor=tk.W)
        
        # Status indicator
        status_frame = tk.Frame(main_frame, bg=self.colors['white'])
        status_frame.pack(fill=tk.X, pady=(0, 10))
        
        if ai_configured:
            status_icon = "[OK]"
            status_text = "API Gemini đã được cấu hình! Bạn có thể sử dụng AI Vision ngay."
            status_color = "green"
        else:
            status_icon = "[WARN]"
            status_text = "Chưa cấu hình API Gemini. Làm theo hướng dẫn bên dưới để bắt đầu."
            status_color = "orange"
        
        tk.Label(
            status_frame, text=f"{status_icon} {status_text}",
            font=('Segoe UI', 10, 'bold'),
            bg=self.colors['white'], fg=status_color
        ).pack(anchor=tk.W)
        
        # Step-by-step guide (only show if not configured)
        if not ai_configured:
            guide_frame = tk.LabelFrame(
                main_frame,
                text="📖 Hướng dẫn từng bước (CHI TIẾT)",
                font=('Segoe UI', 10, 'bold'),
                bg=self.colors['white'], fg=self.colors['gray_dark'],
                padx=10, pady=10
            )
            guide_frame.pack(fill=tk.X, pady=(0, 10))
            
            steps_text = """Bước 1: Lấy API Key từ Google AI Studio (MIỄN PHÍ)
   ----------------------------------------------------------------------
   1.1  Nhấn nút "🔗 Mở Google AI Studio" bên dưới
   1.2  Đăng nhập bằng tài khoản Google của bạn
   1.3  Nhấn nút "Get API Key" (Lấy API Key)
   1.4  Nhấn "Create API key" (Tạo API key mới)
   1.5  Chọn một dự án bất kỳ hoặc tạo mới
   1.6  COPY mã API key (chuỗi dài bắt đầu bằng "AIza...")

Bước 2: Cấu hình trong ứng dụng
   ----------------------------------------------------------------------
   2.1  Quay lại ứng dụng này
   2.2  Chọn tab "Cấu hình AI" (hoặc nhấn nút bên dưới)
   2.3  Dán API key vào ô "Thêm API Key"
   2.4  Nhấn nút "Thêm Key" để lưu
   2.5  Đóng cửa sổ cấu hình

Bước 3: Sử dụng AI Vision
   ----------------------------------------------------------------------
   3.1  Quay lại tab "Dịch file"
   3.2  Tích chọn "🤖 Dùng AI Vision cho PDF"
   3.3  Chọn số trang/batch (4 = tiết kiệm 75% request)
   3.4  Nhấn "Dịch File"
   
💡 MẸO: Bạn có thể thêm NHIỀU API key để xoay vòng khi hết quota!"""
            
            steps_label = tk.Label(
                guide_frame, text=steps_text,
                font=('Consolas', 9), justify=tk.LEFT,
                bg=self.colors['white'], fg=self.colors['gray_dark']
            )
            steps_label.pack(anchor=tk.W)
        
        # Buttons frame
        btn_frame = tk.Frame(main_frame, bg=self.colors['white'])
        btn_frame.pack(fill=tk.X, pady=(10, 0))
        
        def open_ai_studio():
            webbrowser.open("https://aistudio.google.com/app/apikey")
        
        def open_ai_settings():
            # Opening settings means user wants to configure first - treat as cancel
            user_choice['value'] = None
            guide_dialog.destroy()
            self._open_ai_settings()
        
        def use_ai_vision():
            logger.info("User chose: AI Vision translation")
            self.use_ai_vision_for_pdf.set(True)
            user_choice['value'] = True
            guide_dialog.destroy()
        
        def use_normal_translation():
            logger.info("User chose: Normal translation (no AI)")
            user_choice['value'] = False
            guide_dialog.destroy()
        
        # Row 1: AI Studio and Settings buttons
        btn_row1 = tk.Frame(btn_frame, bg=self.colors['white'])
        btn_row1.pack(fill=tk.X, pady=(0, 5))
        
        if not ai_configured:
            btn_ai_studio = tk.Button(
                btn_row1, text="🔗 Mở Google AI Studio",
                font=('Segoe UI', 10, 'bold'),
                bg="#4285F4", fg="white",
                command=open_ai_studio,
                cursor="hand2",
                padx=15, pady=5
            )
            btn_ai_studio.pack(side=tk.LEFT, padx=(0, 10))
            
            btn_settings = tk.Button(
                btn_row1, text="⚙️ Mở Cấu hình AI",
                font=('Segoe UI', 10),
                bg=self.colors['gray_light'], fg=self.colors['gray_dark'],
                command=open_ai_settings,
                cursor="hand2",
                padx=15, pady=5
            )
            btn_settings.pack(side=tk.LEFT)
        
        # Row 2: Action buttons
        btn_row2 = tk.Frame(btn_frame, bg=self.colors['white'])
        btn_row2.pack(fill=tk.X, pady=(10, 0))
        
        if ai_configured:
            btn_use_ai = tk.Button(
                btn_row2, text="🚀 Bật AI Vision và Dịch",
                font=('Segoe UI', 11, 'bold'),
                bg="#34A853", fg="white",
                command=use_ai_vision,
                cursor="hand2",
                padx=20, pady=8
            )
            btn_use_ai.pack(side=tk.LEFT, padx=(0, 10))
        
        btn_continue = tk.Button(
            btn_row2, 
            text="Tiếp tục dịch thường" if not ai_configured else "Dịch thường (không dùng AI)",
            font=('Segoe UI', 10),
            bg=self.colors['gray_light'], fg=self.colors['gray_dark'],
            command=use_normal_translation,  # Changed: now properly sets choice to False
            cursor="hand2",
            padx=15, pady=5
        )
        btn_continue.pack(side=tk.LEFT)
        
        # Don't show again checkbox
        dont_show_frame = tk.Frame(main_frame, bg=self.colors['white'])
        dont_show_frame.pack(fill=tk.X, pady=(15, 0))
        
        # Note about request limits
        note_text = """📊 Lưu ý về giới hạn API (miễn phí):
• Gemini 2.5 Flash: ~1500 requests/ngày (RPD)
• Gửi 4 trang/batch = tiết kiệm 75% requests
• Thêm nhiều API key để tăng giới hạn"""
        
        tk.Label(
            dont_show_frame, text=note_text,
            font=('Segoe UI', 8, 'italic'), justify=tk.LEFT,
            bg=self.colors['white'], fg=self.colors['gray_medium']
        ).pack(anchor=tk.W)
        
        # CRITICAL: Wait for dialog to close before returning
        # This blocks until the dialog is destroyed
        self.wait_window(guide_dialog)
        
        logger.info(f"PDF dialog closed with user choice: {user_choice['value']}")
        return user_choice['value']


    def _save_advanced_settings(self):
        """Save advanced settings (TM, Glossary, Router) to config."""
        try:
            min_seg_len = int(self.min_seg_len_var.get().strip() or "2")
            max_glossary_terms = int(self.max_glossary_terms_var.get().strip() or "20")

            if min_seg_len < 0:
                messagebox.showerror("Loi", "Do dai toi thieu segment luu cache phai la so nguyen >= 0.")
                return
            if max_glossary_terms <= 0:
                messagebox.showerror("Loi", "Max glossary terms per segment phai la so nguyen > 0.")
                return

            self.config_manager.use_translation_memory = self.use_tm_var.get()
            self.config_manager.min_segment_length_to_cache = min_seg_len
            self.config_manager.use_glossary = self.use_glossary_var.get()
            self.config_manager.max_glossary_terms_per_segment = max_glossary_terms
            self.config_manager.glossary_enforcement_level = self.glossary_level_var.get()
            self.config_manager.use_provider_router = self.use_router_var.get()
            self.config_manager.provider_router_policy = self.router_policy_var.get()
            self.config_manager.auto_refresh_provider_models = self.auto_refresh_provider_models_var.get()
            
            if self.config_manager.save_config():
                messagebox.showinfo("Thanh cong", "Da luu cai dat nang cao thanh cong!")
            else:
                messagebox.showerror("Loi", "Khong the luu file cau hinh settings.")
        except ValueError:
            messagebox.showerror(
                "Loi",
                "Gia tri so khong hop le. Vui long nhap so nguyen hop le cho cache segment va max glossary terms."
            )
        except Exception as e:
            messagebox.showerror("Loi", f"Loi khi luu settings: {str(e)}")

    def setup_jobs_tab(self):
        """Setup the Jobs tracking tab."""
        main_frame = tk.Frame(self.tab_jobs, bg=self.colors['gray_light'], padx=15, pady=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Title and Refresh row
        title_row = tk.Frame(main_frame, bg=self.colors['gray_light'])
        title_row.pack(fill=tk.X, pady=(0, 10))
        
        tk.Label(
            title_row, text="📋 Danh sách các công việc dịch thuật (Jobs)", 
            font=('Segoe UI', 12, 'bold'), bg=self.colors['gray_light'], fg=self.colors['navy']
        ).pack(side=tk.LEFT)
        
        create_styled_button(
            title_row, text="Làm mới", command=self._refresh_jobs_list, colors=self.colors
        ).pack(side=tk.RIGHT)

        # Treeview for jobs list
        columns = ("job_id", "job_type", "status", "progress", "created_at")
        self.jobs_tree = ttk.Treeview(main_frame, columns=columns, show="headings", height=8)
        self.jobs_tree.heading("job_id", text="Mã công việc (Job ID)")
        self.jobs_tree.heading("job_type", text="Loại công việc")
        self.jobs_tree.heading("status", text="Trạng thái")
        self.jobs_tree.heading("progress", text="Tiến độ (%)")
        self.jobs_tree.heading("created_at", text="Ngày tạo")
        
        self.jobs_tree.column("job_id", width=180)
        self.jobs_tree.column("job_type", width=100)
        self.jobs_tree.column("status", width=100)
        self.jobs_tree.column("progress", width=100, anchor=tk.CENTER)
        self.jobs_tree.column("created_at", width=160)
        self.jobs_tree.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        # Detail Panel (LabelFrame)
        self.job_detail_frame = tk.LabelFrame(
            main_frame, text="🔍 Chi tiết công việc được chọn", 
            bg=self.colors['gray_light'], fg=self.colors['navy'], font=('Segoe UI', 10, 'bold'),
            padx=10, pady=10
        )
        self.job_detail_frame.pack(fill=tk.X, pady=(0, 10))

        self.job_detail_text = tk.Text(self.job_detail_frame, height=5, wrap=tk.WORD, bg=self.colors['white'], font=('Segoe UI', 9))
        self.job_detail_text.pack(fill=tk.X)
        self.job_detail_text.config(state=tk.DISABLED)

        # Bind select event
        self.jobs_tree.bind("<<TreeviewSelect>>", self._on_job_selected)

        # Action Buttons row
        action_row = tk.Frame(main_frame, bg=self.colors['gray_light'])
        action_row.pack(fill=tk.X)

        create_styled_button(
            action_row, text="Mở thư mục công việc", command=self._open_selected_job_folder, colors=self.colors
        ).pack(side=tk.LEFT, padx=(0, 10))

        create_styled_button(
            action_row, text="Xem lỗi phân đoạn", command=self._view_selected_job_errors, colors=self.colors
        ).pack(side=tk.LEFT, padx=(0, 10))

        resume_btn = create_styled_button(
            action_row, text="Khôi phục công việc (Đang phát triển)", command=self._resume_selected_job, colors=self.colors
        )
        resume_btn.config(state=tk.DISABLED)
        resume_btn.pack(side=tk.LEFT)
        
        tk.Label(
            action_row, text="* Tính năng khôi phục (Resume) được dành riêng cho các phiên bản tương lai.", 
            font=('Segoe UI', 8, 'italic'), bg=self.colors['gray_light'], fg=self.colors['gray_medium']
        ).pack(side=tk.LEFT, padx=10)

        self._refresh_jobs_list()

    def _refresh_jobs_list(self):
        """Load jobs list from core TranslationJobManager."""
        for item in self.jobs_tree.get_children():
            self.jobs_tree.delete(item)
            
        try:
            jobs = self.job_manager.list_jobs(limit=50)
            for j in jobs:
                job_id = j.get("job_id")
                job_type = j.get("job_type", "unknown")
                status = j.get("status", "pending")
                
                # Fetch progress percent
                progress_percent = 0.0
                try:
                    summary = self.job_manager.get_job_summary(job_id)
                    progress_percent = summary.get("progress", {}).get("percent", 0.0)
                except:
                    pass
                    
                created_at = j.get("created_at", "")
                if created_at and "T" in created_at:
                    created_at = created_at.split(".")[0].replace("T", " ")
                    
                self.jobs_tree.insert(
                    "", tk.END, iid=job_id,
                    values=(job_id, job_type, status, f"{progress_percent}%", created_at)
                )
        except Exception as e:
            logger.error(f"Failed to load jobs list in UI: {e}")

    def _on_job_selected(self, event=None):
        selection = self.jobs_tree.selection()
        if not selection:
            return
            
        job_id = selection[0]
        try:
            summary = self.job_manager.get_job_summary(job_id)
            job = summary.get("job", {})
            progress = summary.get("progress", {})
            
            detail_info = (
                f"Job ID: {job_id}\n"
                f"Ngôn ngữ: {job.get('source_lang', 'auto')} -> {job.get('target_lang', 'vi')}  |  Chiến lược: {job.get('strategy', 'waterfall')}\n"
                f"Tiến độ: {progress.get('percent', 0.0)}% ({progress.get('completed_segments', 0)} / {progress.get('total_segments', 0)} phân đoạn)  |  Lỗi: {progress.get('failed_segments', 0)} phân đoạn\n"
                f"File đang dịch: {progress.get('current_file', 'None')}\n"
                f"Sheet/Tab đang dịch: {progress.get('current_sheet', 'None')}\n"
                f"Ghi chú: {job.get('notes', '')}"
            )
            
            self.job_detail_text.config(state=tk.NORMAL)
            self.job_detail_text.delete("1.0", tk.END)
            self.job_detail_text.insert(tk.END, detail_info)
            self.job_detail_text.config(state=tk.DISABLED)
        except Exception as e:
            logger.error(f"Error loading job detail in UI: {e}")

    def _open_selected_job_folder(self):
        selection = self.jobs_tree.selection()
        if not selection:
            messagebox.showwarning("Cảnh báo", "Vui lòng chọn một Job từ danh sách!")
            return
            
        job_id = selection[0]
        try:
            job_dir = self.job_manager._get_job_dir(job_id)
            if job_dir.exists():
                os.startfile(str(job_dir))
            else:
                messagebox.showerror("Lỗi", "Thư mục lưu trữ của Job này không tồn tại.")
        except Exception as e:
            messagebox.showerror("Lỗi", f"Không thể mở thư mục: {str(e)}")

    def _view_selected_job_errors(self):
        selection = self.jobs_tree.selection()
        if not selection:
            messagebox.showwarning("Cảnh báo", "Vui lòng chọn một Job từ danh sách!")
            return
            
        job_id = selection[0]
        try:
            failed_items = self.job_manager.load_failed_items(job_id)
            if not failed_items:
                messagebox.showinfo("Thông tin", "Không có phân đoạn bị lỗi nào được ghi nhận cho Job này.")
                return
                
            # Create sub window
            err_win = tk.Toplevel(self)
            err_win.title(f"⚠️ Danh sách phân đoạn bị lỗi - Job: {job_id}")
            err_win.geometry("750x450")
            err_win.transient(self)
            err_win.grab_set()
            
            frame = tk.Frame(err_win, padx=10, pady=10)
            frame.pack(fill=tk.BOTH, expand=True)
            
            columns = ("file", "sheet", "cell", "error_type", "error_message")
            tree = ttk.Treeview(frame, columns=columns, show="headings", height=15)
            tree.heading("file", text="File")
            tree.heading("sheet", text="Sheet")
            tree.heading("cell", text="O/Vi tri")
            tree.heading("error_type", text="Loai Loi")
            tree.heading("error_message", text="Thong tin loi chi tiet")
            
            tree.column("file", width=120)
            tree.column("sheet", width=80)
            tree.column("cell", width=70, anchor=tk.CENTER)
            tree.column("error_type", width=100)
            tree.column("error_message", width=340)
            tree.pack(fill=tk.BOTH, expand=True)
            
            for item in failed_items:
                tree.insert(
                    "", tk.END,
                    values=(
                        os.path.basename(item.get("file", "") or ""),
                        item.get("sheet", "") or "",
                        item.get("cell", "") or "",
                        item.get("error_type", "") or "",
                        item.get("error_message", "") or ""
                    )
                )
        except Exception as e:
            messagebox.showerror("Lỗi", f"Không thể tải các phân đoạn lỗi: {str(e)}")

    def _resume_selected_job(self):
        # Reserved command placeholder
        pass

    def setup_glossary_tab(self):
        """Setup the Glossary tab."""
        main_frame = tk.Frame(self.tab_glossary, bg=self.colors['gray_light'], padx=15, pady=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Filter and Actions Row
        top_row = tk.Frame(main_frame, bg=self.colors['gray_light'])
        top_row.pack(fill=tk.X, pady=(0, 10))

        tk.Label(top_row, text="Ngôn ngữ nguồn:", bg=self.colors['gray_light']).pack(side=tk.LEFT)
        self.glossary_filter_src = tk.StringVar(value="auto")
        glossary_filter_src_combo = ttk.Combobox(
            top_row, textvariable=self.glossary_filter_src, 
            values=["auto"] + list(self.display_languages.keys()), state="readonly", width=8
        )
        glossary_filter_src_combo.pack(side=tk.LEFT, padx=5)

        tk.Label(top_row, text="Ngôn ngữ đích:", bg=self.colors['gray_light']).pack(side=tk.LEFT, padx=(10, 0))
        self.glossary_filter_tgt = tk.StringVar(value="vi")
        glossary_filter_tgt_combo = ttk.Combobox(
            top_row, textvariable=self.glossary_filter_tgt, 
            values=list(self.display_languages.keys()), state="readonly", width=8
        )
        glossary_filter_tgt_combo.pack(side=tk.LEFT, padx=5)

        create_styled_button(
            top_row, text="Lọc", command=self._refresh_glossary_list, colors=self.colors
        ).pack(side=tk.LEFT, padx=10)

        create_styled_button(
            top_row, text="Nhập từ CSV (Import)", command=self._import_glossary_csv, colors=self.colors
        ).pack(side=tk.RIGHT, padx=5)

        create_styled_button(
            top_row, text="Xuất ra CSV (Export)", command=self._export_glossary_csv, colors=self.colors
        ).pack(side=tk.RIGHT, padx=5)

        # Treeview for glossary
        columns = ("id", "source_term", "target_term", "source_lang", "target_lang", "domain", "note")
        self.glossary_tree = ttk.Treeview(main_frame, columns=columns, show="headings", height=8)
        self.glossary_tree.heading("id", text="ID")
        self.glossary_tree.heading("source_term", text="Thuật ngữ gốc")
        self.glossary_tree.heading("target_term", text="Thuật ngữ dịch")
        self.glossary_tree.heading("source_lang", text="Mã nguồn")
        self.glossary_tree.heading("target_lang", text="Mã đích")
        self.glossary_tree.heading("domain", text="Chuyên ngành")
        self.glossary_tree.heading("note", text="Ghi chú")
        
        self.glossary_tree.column("id", width=40, anchor=tk.CENTER)
        self.glossary_tree.column("source_term", width=150)
        self.glossary_tree.column("target_term", width=150)
        self.glossary_tree.column("source_lang", width=80, anchor=tk.CENTER)
        self.glossary_tree.column("target_lang", width=80, anchor=tk.CENTER)
        self.glossary_tree.column("domain", width=90)
        self.glossary_tree.column("note", width=100)
        self.glossary_tree.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        # Add Term Form (LabelFrame)
        add_frame = tk.LabelFrame(
            main_frame, text="➕ Thêm thuật ngữ mới", 
            bg=self.colors['gray_light'], fg=self.colors['navy'], font=('Segoe UI', 10, 'bold'),
            padx=10, pady=10
        )
        add_frame.pack(fill=tk.X, pady=(0, 5))

        # Form fields
        f_row1 = tk.Frame(add_frame, bg=self.colors['gray_light'])
        f_row1.pack(fill=tk.X, pady=2)
        tk.Label(f_row1, text="Thuật ngữ gốc *:", width=15, bg=self.colors['gray_light'], anchor=tk.W).pack(side=tk.LEFT)
        self.glossary_add_src_term = tk.StringVar()
        tk.Entry(f_row1, textvariable=self.glossary_add_src_term, bg=self.colors['white'], width=30).pack(side=tk.LEFT, padx=5)

        tk.Label(f_row1, text="Thuật ngữ dịch *:", width=15, bg=self.colors['gray_light'], anchor=tk.W).pack(side=tk.LEFT, padx=(20, 0))
        self.glossary_add_tgt_term = tk.StringVar()
        tk.Entry(f_row1, textvariable=self.glossary_add_tgt_term, bg=self.colors['white'], width=30).pack(side=tk.LEFT, padx=5)

        f_row2 = tk.Frame(add_frame, bg=self.colors['gray_light'])
        f_row2.pack(fill=tk.X, pady=2)
        tk.Label(f_row2, text="Ngôn ngữ nguồn *:", width=15, bg=self.colors['gray_light'], anchor=tk.W).pack(side=tk.LEFT)
        self.glossary_add_src_lang = tk.StringVar(value="en")
        glossary_add_src_combo = ttk.Combobox(
            f_row2, textvariable=self.glossary_add_src_lang, 
            values=list(self.display_languages.keys()), state="readonly", width=8
        )
        glossary_add_src_combo.pack(side=tk.LEFT, padx=5)

        tk.Label(f_row2, text="Ngôn ngữ đích *:", width=15, bg=self.colors['gray_light'], anchor=tk.W).pack(side=tk.LEFT, padx=(20, 0))
        self.glossary_add_tgt_lang = tk.StringVar(value="vi")
        glossary_add_tgt_combo = ttk.Combobox(
            f_row2, textvariable=self.glossary_add_tgt_lang, 
            values=list(self.display_languages.keys()), state="readonly", width=8
        )
        glossary_add_tgt_combo.pack(side=tk.LEFT, padx=5)

        f_row3 = tk.Frame(add_frame, bg=self.colors['gray_light'])
        f_row3.pack(fill=tk.X, pady=2)
        tk.Label(f_row3, text="Chuyên ngành:", width=15, bg=self.colors['gray_light'], anchor=tk.W).pack(side=tk.LEFT)
        self.glossary_add_domain = tk.StringVar()
        tk.Entry(f_row3, textvariable=self.glossary_add_domain, bg=self.colors['white'], width=20).pack(side=tk.LEFT, padx=5)

        tk.Label(f_row3, text="Ghi chú:", width=15, bg=self.colors['gray_light'], anchor=tk.W).pack(side=tk.LEFT, padx=(20, 0))
        self.glossary_add_note = tk.StringVar()
        tk.Entry(f_row3, textvariable=self.glossary_add_note, bg=self.colors['white'], width=35).pack(side=tk.LEFT, padx=5)

        # Form buttons row
        btn_form_row = tk.Frame(main_frame, bg=self.colors['gray_light'])
        btn_form_row.pack(fill=tk.X, pady=5)

        create_styled_button(
            btn_form_row, text="➕ Thêm thuật ngữ", command=self._add_glossary_term, colors=self.colors
        ).pack(side=tk.LEFT, padx=(0, 10))

        create_styled_button(
            btn_form_row, text="🗑️ Xóa thuật ngữ đã chọn", command=self._delete_glossary_term, colors=self.colors
        ).pack(side=tk.LEFT)

        self._refresh_glossary_list()

    def _refresh_glossary_list(self):
        for item in self.glossary_tree.get_children():
            self.glossary_tree.delete(item)
            
        try:
            src = self.glossary_filter_src.get()
            tgt = self.glossary_filter_tgt.get()
            terms = self.tm_manager.list_glossary_terms(
                source_lang=src if src != 'auto' else None,
                target_lang=tgt,
                active_only=False
            )
            for t in terms:
                self.glossary_tree.insert(
                    "", tk.END, iid=t["id"],
                    values=(t["id"], t["source_term"], t["target_term"], t["source_lang"], t["target_lang"], t["domain"], t["note"])
                )
        except Exception as e:
            logger.error(f"Error loading glossary list in UI: {e}")

    def _add_glossary_term(self):
        src_term = self.glossary_add_src_term.get().strip()
        tgt_term = self.glossary_add_tgt_term.get().strip()
        src_lang = self.glossary_add_src_lang.get().strip()
        tgt_lang = self.glossary_add_tgt_lang.get().strip()
        domain = self.glossary_add_domain.get().strip()
        note = self.glossary_add_note.get().strip()
        
        if not src_term or not tgt_term or not src_lang or not tgt_lang:
            messagebox.showwarning("Canh bao", "Vui long nhap cac truong bat buoc (*) cua thuat ngu!")
            return
            
        try:
            term_id = self.tm_manager.add_glossary_term(
                src_term, tgt_term, src_lang, tgt_lang, domain, note
            )
            if term_id:
                messagebox.showinfo("Thanh cong", f"Da them thuat ngu thanh cong (ID: {term_id})!")
                self.glossary_add_src_term.set("")
                self.glossary_add_tgt_term.set("")
                self.glossary_add_domain.set("")
                self.glossary_add_note.set("")
                self._refresh_glossary_list()
            else:
                messagebox.showerror("Loi", "Khong the them thuat ngu vao database core.")
        except Exception as e:
            messagebox.showerror("Loi", f"Loi khi them thuat ngu: {str(e)}")

    def _delete_glossary_term(self):
        selection = self.glossary_tree.selection()
        if not selection:
            messagebox.showwarning("Canh bao", "Vui long chon thuat ngu can xoa!")
            return
            
        term_id = int(selection[0])
        if messagebox.askyesno("Xac nhan", f"Ban co chac muon xoa thuat ngu (ID: {term_id})?"):
            try:
                if self.tm_manager.remove_glossary_term(term_id):
                    messagebox.showinfo("Thanh cong", "Da xoa thuat ngu khoi database core!")
                    self._refresh_glossary_list()
                else:
                    messagebox.showerror("Loi", "Khong the xoa thuat ngu khoi database core.")
            except Exception as e:
                messagebox.showerror("Loi", f"Loi khi xoa: {str(e)}")

    def _import_glossary_csv(self):
        csv_path = filedialog.askopenfilename(
            filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")]
        )
        if not csv_path:
            return
            
        try:
            success, failed = self.tm_manager.import_glossary_csv(csv_path)
            messagebox.showinfo(
                "Ket qua Import",
                f"Import thanh cong {success} dong, that bai {failed} dong!"
            )
            self._refresh_glossary_list()
        except Exception as e:
            messagebox.showerror("Loi", f"Loi khi import CSV: {str(e)}")

    def _export_glossary_csv(self):
        csv_path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")]
        )
        if not csv_path:
            return
            
        try:
            if self.tm_manager.export_glossary_csv(csv_path):
                messagebox.showinfo("Thanh cong", f"Da xuat thuat ngu ra file CSV tai:\n{csv_path}")
            else:
                messagebox.showerror("Loi", "Khong the xuat CSV.")
        except Exception as e:
            messagebox.showerror("Loi", f"Loi khi xuat CSV: {str(e)}")

    def setup_tm_tab(self):
        """Setup the Translation Memory (TM) tab."""
        main_frame = tk.Frame(self.tab_tm, bg=self.colors['gray_light'], padx=15, pady=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Filter bar
        filter_row = tk.Frame(main_frame, bg=self.colors['gray_light'])
        filter_row.pack(fill=tk.X, pady=(0, 10))

        tk.Label(filter_row, text="Tìm kiếm:", bg=self.colors['gray_light']).pack(side=tk.LEFT)
        self.tm_search_query = tk.StringVar()
        tk.Entry(filter_row, textvariable=self.tm_search_query, width=25, bg=self.colors['white']).pack(side=tk.LEFT, padx=5)

        tk.Label(filter_row, text="Ngôn ngữ nguồn:", bg=self.colors['gray_light']).pack(side=tk.LEFT, padx=(10, 0))
        self.tm_filter_src = tk.StringVar(value="auto")
        tm_filter_src_combo = ttk.Combobox(
            filter_row, textvariable=self.tm_filter_src, 
            values=["auto"] + list(self.display_languages.keys()), state="readonly", width=8
        )
        tm_filter_src_combo.pack(side=tk.LEFT, padx=5)

        tk.Label(filter_row, text="Ngôn ngữ đích:", bg=self.colors['gray_light']).pack(side=tk.LEFT, padx=(10, 0))
        self.tm_filter_tgt = tk.StringVar(value="vi")
        tm_filter_tgt_combo = ttk.Combobox(
            filter_row, textvariable=self.tm_filter_tgt, 
            values=list(self.display_languages.keys()), state="readonly", width=8
        )
        tm_filter_tgt_combo.pack(side=tk.LEFT, padx=5)

        create_styled_button(
            filter_row, text="Tìm kiếm", command=self._refresh_tm_list, colors=self.colors
        ).pack(side=tk.LEFT, padx=10)

        # Treeview for TM
        columns = ("id", "source_lang", "target_lang", "source_text", "translated_text", "provider", "model", "hit_count", "updated_at")
        self.tm_tree = ttk.Treeview(main_frame, columns=columns, show="headings", height=12)
        self.tm_tree.heading("id", text="ID")
        self.tm_tree.heading("source_lang", text="Mã nguồn")
        self.tm_tree.heading("target_lang", text="Mã đích")
        self.tm_tree.heading("source_text", text="Văn bản gốc (Xem trước)")
        self.tm_tree.heading("translated_text", text="Bản dịch (Xem trước)")
        self.tm_tree.heading("provider", text="Nhà cung cấp")
        self.tm_tree.heading("model", text="Mô hình")
        self.tm_tree.heading("hit_count", text="Số lần khớp")
        self.tm_tree.heading("updated_at", text="Cập nhật")

        self.tm_tree.column("id", width=40, anchor=tk.CENTER)
        self.tm_tree.column("source_lang", width=70, anchor=tk.CENTER)
        self.tm_tree.column("target_lang", width=70, anchor=tk.CENTER)
        self.tm_tree.column("source_text", width=180)
        self.tm_tree.column("translated_text", width=180)
        self.tm_tree.column("provider", width=80)
        self.tm_tree.column("model", width=90)
        self.tm_tree.column("hit_count", width=80, anchor=tk.CENTER)
        self.tm_tree.column("updated_at", width=100)
        self.tm_tree.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        # Bottom row action
        action_row = tk.Frame(main_frame, bg=self.colors['gray_light'])
        action_row.pack(fill=tk.X)

        create_styled_button(
            action_row, text="Làm mới", command=self._refresh_tm_list, colors=self.colors
        ).pack(side=tk.LEFT, padx=(0, 10))

        create_styled_button(
            action_row, text="Xóa bản ghi đã chọn", command=self._delete_tm_segment, colors=self.colors
        ).pack(side=tk.LEFT)

        self._refresh_tm_list()

    def _refresh_tm_list(self):
        for item in self.tm_tree.get_children():
            self.tm_tree.delete(item)
            
        try:
            query = self.tm_search_query.get().strip()
            src = self.tm_filter_src.get()
            tgt = self.tm_filter_tgt.get()
            
            # Using new API method search_segments
            results = self.tm_manager.search_segments(
                query=query,
                source_lang=src if src != 'auto' else None,
                target_lang=tgt,
                limit=100
            )
            for r in results:
                # Truncate to 80 chars preview to maintain privacy and format cleanly
                src_preview = r["source_text"][:80] + "..." if len(r["source_text"]) > 80 else r["source_text"]
                tgt_preview = r["translated_text"][:80] + "..." if len(r["translated_text"]) > 80 else r["translated_text"]
                
                updated = r["updated_at"] or ""
                if updated and " " in updated:
                    updated = updated.split(" ")[0] # Keep only date for cleaner treeview
                    
                self.tm_tree.insert(
                    "", tk.END, iid=r["id"],
                    values=(
                        r["id"], r["source_lang"], r["target_lang"],
                        src_preview, tgt_preview, r["provider"], r["model"],
                        r["hit_count"], updated
                    )
                )
        except Exception as e:
            logger.error(f"Error loading TM segments in UI: {e}")

    def _delete_tm_segment(self):
        selection = self.tm_tree.selection()
        if not selection:
            messagebox.showwarning("Canh bao", "Vui long chon segment can xoa!")
            return
            
        segment_id = int(selection[0])
        if messagebox.askyesno("Xac nhan", f"Ban co chac muon xoa segment (ID: {segment_id}) khoi bo nho?"):
            try:
                if self.tm_manager.delete_segment(segment_id):
                    messagebox.showinfo("Thanh cong", "Da xoa segment khoi bo nho dich!")
                    self._refresh_tm_list()
                else:
                    messagebox.showerror("Loi", "Khong the xoa segment khoi database TM core.")
            except Exception as e:
                messagebox.showerror("Loi", f"Loi khi xoa segment: {str(e)}")

    def _sanitize_router_error_text(self, value: str) -> str:
        """Return a redacted, truncated provider-router error string for UI display."""
        sanitized = str(value or "").strip()
        if not sanitized:
            return "None"

        sanitized = re.sub(r"AIza[0-9A-Za-z\-_]{8,}", "[REDACTED_API_KEY]", sanitized)
        sanitized = re.sub(r"Bearer\s+[A-Za-z0-9\-\._~+/=]+", "Bearer [REDACTED]", sanitized, flags=re.IGNORECASE)
        sanitized = re.sub(r"sk-[A-Za-z0-9\-_]+", "[REDACTED_API_KEY]", sanitized)

        for banned_token in ("api_key", "authorization", "prompt", "source_text"):
            if banned_token in sanitized.lower():
                return "[REDACTED_SENSITIVE_ERROR]"

        if len(sanitized) > 80:
            sanitized = sanitized[:80] + "..."
        return sanitized

    def _refresh_router_health(self):
        """Load health snapshot of providers from TranslationService's ProviderRouter."""
        router_enabled = self.config_manager.use_provider_router
        if router_enabled:
            self.lbl_router_status.config(text="Trạng thái Smart Router: 🟢 HOẠT ĐỘNG (Tự động chọn AI tốt nhất)", fg="green")
        else:
            self.lbl_router_status.config(text="Trạng thái Smart Router: 🔴 TẮT (Sử dụng cấu hình chế độ dịch cũ)", fg="red")

        for item in self.router_tree.get_children():
            self.router_tree.delete(item)
            
        try:
            # Safely fetch router from TranslationService
            from translation_app.core.ai_service import get_ai_service
            router = self.translation_service._get_provider_router(get_ai_service())
            
            # Fetch dynamic health snapshot
            snapshot = router.get_health_snapshot()
            for entry in snapshot:
                provider = entry.get("provider_name", "")
                model = entry.get("model", "")
                
                is_available = "🟢 Khả dụng" if entry.get("is_available", True) else "🔴 Không khả dụng"
                
                cooldown_val = entry.get("cooldown_until", 0.0)
                cooldown = "Không có"
                if cooldown_val > 0:
                    cooldown_remaining = max(0, int(cooldown_val - time.time()))
                    if cooldown_remaining > 0:
                        cooldown = f"Chờ {cooldown_remaining} giây"
                        is_available = "🟡 Đang hồi chiêu"
                
                failures = entry.get("consecutive_failures", 0)
                last_error = self._sanitize_router_error_text(entry.get("last_error_type", ""))
                latency = entry.get("last_latency_ms", 0)

                # Format provider display name
                provider_display_names = {
                    "gemini": "Gemini AI",
                    "chatanywhere": "ChatAnyWhere",
                    "deepseek": "DeepSeek",
                    "nvidia_nim": "NVIDIA NIM",
                    "openai_compatible": "OpenAI tùy chỉnh",
                    "google": "Google Translate"
                }
                display_prov = provider_display_names.get(provider.lower(), provider)

                self.router_tree.insert(
                    "", tk.END,
                    values=(display_prov, model, is_available, cooldown, failures, last_error, f"{latency} ms" if latency else "-")
                )
        except Exception as e:
            logger.error(f"Error loading router health snapshot in UI: {e}")

    def _reset_router_cooldowns(self):
        try:
            from translation_app.core.ai_service import get_ai_service
            router = self.translation_service._get_provider_router(get_ai_service())
            router.reset_cooldowns()
            messagebox.showinfo("Thành công", "Đã khôi phục toàn bộ trạng thái hoạt động của các AI Providers thành công!")
            self._refresh_router_health()
        except Exception as e:
            messagebox.showerror("Lỗi", f"Không thể khôi phục trạng thái: {str(e)}")

    def on_closing(self):
        """Handle window closing"""
        logger.info("Application closing")
        self.translation_service.shutdown()
        self.destroy()

    def destroy(self):
        """Clean up background pollers and after tasks."""
        if hasattr(self, '_provider_model_poll_after_ids'):
            for after_id in list(self._provider_model_poll_after_ids):
                try:
                    self.after_cancel(after_id)
                except Exception:
                    pass
        if hasattr(self, '_auto_refresh_after_id') and self._auto_refresh_after_id:
            try:
                self.after_cancel(self._auto_refresh_after_id)
            except Exception:
                pass
        super().destroy()
