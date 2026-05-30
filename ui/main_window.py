"""
Main application window for translation application
"""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import customtkinter as ctk
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
from translation_app.core.file_translation_control import FileTranslationControl, FileTranslationInterrupted
from translation_app.core.email_handler import EmailHandler
from translation_app.core.ocr_handler import get_ocr_handler
from translation_app.ui.theme import setup_theme
from translation_app.ui.components import create_styled_button, create_language_combobox, create_styled_card
from translation_app.utils.validators import FileValidator, LanguageValidator
from translation_app.utils.error_handler import FileProcessingError, handle_translation_error
from translation_app.utils.logger import logger
from translation_app.config import config


# Universal Tkinter after-callback tracker to prevent Tcl "invalid command name" spam during teardown
original_after = tk.Misc.after
original_after_cancel = tk.Misc.after_cancel

# Global mapping to track which widget originally registered each after_id
after_id_to_widget = {}

def tracked_after(self, delay_ms, callback=None, *args):
    try:
        root = self.winfo_toplevel()
    except Exception:
        root = None

    if root and getattr(root, '_is_destroyed', False):
        return ""
    if getattr(self, '_is_destroyed', False):
        return ""
    try:
        if not self.winfo_exists():
            return ""
    except Exception:
        pass

    if callback is None:
        return original_after(self, delay_ms)

    # Initialize instance-level tracker on the root if not present
    if root is not None:
        if not hasattr(root, '_local_after_ids'):
            root._local_after_ids = set()
        local_set = root._local_after_ids
    else:
        local_set = None

    callback_id = None

    def wrapper(*w_args, **w_kwargs):
        try:
            if getattr(self, '_is_destroyed', False):
                return
            if not self.winfo_exists():
                return
            if root and (getattr(root, '_is_destroyed', False) or not root.winfo_exists()):
                return
        except Exception:
            return

        if callback_id:
            after_id_to_widget.pop(callback_id, None)

        if local_set and callback_id in local_set:
            try:
                local_set.discard(callback_id)
            except Exception:
                pass
        try:
            callback(*w_args, **w_kwargs)
        except Exception:
            pass

    try:
        callback_id = original_after(self, delay_ms, wrapper, *args)
        if callback_id:
            after_id_to_widget[callback_id] = self
        if local_set is not None and callback_id:
            local_set.add(callback_id)
        return callback_id
    except Exception:
        return ""

def tracked_after_cancel(self, id_):
    if not id_:
        return

    # Remove from global root tracker
    try:
        root = self.winfo_toplevel()
        if root and hasattr(root, '_local_after_ids'):
            root._local_after_ids.discard(id_)
    except Exception:
        pass

    # Clean up original widget's _tclCommands list to prevent TclError on destroy
    orig_widget = after_id_to_widget.pop(id_, None)
    if orig_widget:
        try:
            data = orig_widget.tk.call('after', 'info', id_)
            script = data[0]
            orig_widget.deletecommand(script)
        except Exception:
            pass

    try:
        original_after_cancel(self, id_)
    except Exception:
        pass

# Apply the global interceptor
tk.Misc.after = tracked_after
tk.Misc.after_cancel = tracked_after_cancel


# Set CustomTkinter theme and appearance
ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")


class MainWindow(ctk.CTk):
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

        self.TM_POLICY_DISPLAY_MAP = {
            "tm_prefer_cache": "Ưu tiên bộ nhớ dịch",
            "tm_suggest_only": "Chỉ gợi ý, vẫn dịch lại bằng AI",
            "tm_retranslate_and_update": "Dịch lại và cập nhật bộ nhớ",
            "tm_disabled": "Tắt bộ nhớ dịch"
        }
        self.TM_POLICY_VALUE_MAP = {v: k for k, v in self.TM_POLICY_DISPLAY_MAP.items()}
        initial_policy = self.config_manager.translation_memory_policy
        display_policy = self.TM_POLICY_DISPLAY_MAP.get(initial_policy, "Ưu tiên bộ nhớ dịch")
        self.tm_policy_var = tk.StringVar(value=display_policy)

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
        self._is_destroyed = False
        self._after_ids = set()

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
        self._file_translation_in_progress = False
        self._file_translation_control: Optional[FileTranslationControl] = None
        self._selected_file_paths: list[str] = []
        self._selected_file_display_value: str = ""

        # Setup UI
        self.setup_window()
        self.setup_theme()
        self.create_widgets()

        # Bind global mouse wheel events for smooth scrolling
        self.bind_all("<MouseWheel>", self._on_mouse_wheel)
        self.bind_all("<Button-4>", self._on_mouse_wheel)
        self.bind_all("<Button-5>", self._on_mouse_wheel)

        logger.info("Main window initialized")

    def setup_window(self):
        """Setup window properties"""
        from translation_app import __version__
        self.title(f"Dịch tự động v{__version__} - Bùi Đức Vinh - Phòng phát triển hệ thống chế tạo")
        self.geometry("720x750")
        self.minsize(720, 600)


    def setup_theme(self):
        """Setup theme and colors"""
        self.colors, self.style = setup_theme()
        self.configure(fg_color=self.colors['gray_light'])

    def create_widgets(self):
        """Create all UI widgets"""
        # Create CTkTabview for modern tabs with premium pill selector styling
        self.tabview = ctk.CTkTabview(
            self,
            command=self._on_tab_changed,
            fg_color=self.colors['gray_light'],
            segmented_button_fg_color=self.colors['white'],
            segmented_button_selected_color=self.colors['tab_selected_bg'],
            segmented_button_selected_hover_color=self.colors['tab_selected_hover'],
            segmented_button_unselected_color=self.colors['white'],
            segmented_button_unselected_hover_color=self.colors['gray'],
            text_color=self.colors['gray_dark']
        )
        self.tabview.pack(expand=True, fill="both", padx=10, pady=10)

        # Add tabs
        self.tabview.add("Dịch file")
        self.tabview.add("Dịch văn bản")
        self.tabview.add("Dịch email")
        self.tabview.add("Dịch ảnh")
        self.tabview.add("Công việc")
        self.tabview.add("Thuật ngữ")
        self.tabview.add("Bộ nhớ dịch")
        self.tabview.add("Cấu hình AI")

        # Assign tabs to self variables
        self.tab_file = self.tabview.tab("Dịch file")
        self.tab_paragraph = self.tabview.tab("Dịch văn bản")
        self.tab_email = self.tabview.tab("Dịch email")
        self.tab_image = self.tabview.tab("Dịch ảnh")
        self.tab_jobs = self.tabview.tab("Công việc")
        self.tab_glossary = self.tabview.tab("Thuật ngữ")
        self.tab_tm = self.tabview.tab("Bộ nhớ dịch")
        self.tab_ai = self.tabview.tab("Cấu hình AI")

        # For backward compatibility with existing unit tests
        class NotebookCompat:
            def __init__(self, tabview):
                self._tabview = tabview
                # The exact list of tab names in order
                self._tabs = ["Dịch file", "Dịch văn bản", "Dịch email", "Dịch ảnh", "Công việc", "Thuật ngữ", "Bộ nhớ dịch", "Cấu hình AI"]
            def index(self, val):
                if val == "end":
                    return len(self._tabs)
                return self._tabs.index(val)
            def tab(self, index, option=None):
                if isinstance(index, int):
                    name = self._tabs[index]
                else:
                    name = index
                if option == "text":
                    return name
                return {"text": name}
        self.notebook = NotebookCompat(self.tabview)

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

        # Schedule background refresh after UI is fully initialized and ready
        self._auto_refresh_after_id = self.after(100, self._auto_refresh_provider_models_on_startup)

        # Start polling for background model discovery queue results
        self.after(50, self._poll_provider_model_refresh_results)

    def _on_strategy_changed(self, *args):
        """Update translation strategy when ComboBox changes"""
        new_strat = self.strat_var.get()
        self.translation_service.set_strategy(new_strat)

        # Update dynamic mode description
        desc_map = {
            "Tự động chọn AI tốt nhất": "💡 Khuyến nghị: Tự động chọn AI tốt nhất.",
            "Chỉ dùng AI, không dùng Google Translate": "💡 Chỉ dùng AI, không bao giờ dùng Google Translate kể cả khi AI lỗi.",
            "Chỉ dùng Gemini": "💡 Chỉ sử dụng Gemini AI.",
            "Chỉ dùng ChatAnyWhere": "💡 Chỉ sử dụng ChatAnyWhere.",
            "Chỉ dùng DeepSeek": "💡 Chỉ sử dụng DeepSeek.",
            "Chỉ dùng NVIDIA NIM": "💡 Chỉ sử dụng NVIDIA NIM.",
            "Chỉ dùng OpenAI tùy chỉnh": "💡 Chỉ sử dụng OpenAI tùy chỉnh.",
            "Chỉ dùng Google Translate": "💡 Sử dụng Google Translate dịch thuật.",
            "Nâng cao: dùng thứ tự ưu tiên bên dưới": "💡 Thứ tự dịch sẽ chạy từ trên xuống dưới theo danh sách.",
            "Tự động chọn từ pool AI miễn phí": "💡 Pool AI: Tự động chọn AI miễn phí hoạt động tốt nhất.",
            "Pool AI miễn phí (không dùng Google)": "💡 Không dùng Google: Google sẽ không được gọi kể cả khi toàn bộ AI lỗi.",
            "Pool AI miễn phí (Google làm dự phòng cuối)": "💡 Google dự phòng cuối: Google chỉ chạy sau khi toàn bộ AI provider thất bại."
        }
        text = desc_map.get(new_strat, f"💡 Chế độ: {new_strat}")
        if hasattr(self, 'lbl_mode_rec'):
            self.lbl_mode_rec.configure(text=text)

    def _on_tab_changed(self):
        """Handle tab switch to trigger auto refresh when opening AI config tab."""
        if not self.winfo_exists():
            return
        try:
            selected_tab = self.tabview.get()
            if selected_tab == "Cấu hình AI":
                self._auto_refresh_provider_models_on_startup()
        except Exception:
            pass

    def setup_ai_tab(self):
        """Setup the AI Configuration tab with Unified Provider settings using CustomTkinter."""
        # CTkScrollableFrame handles scrolling and responsive width beautifully
        scroll_frame = ctk.CTkScrollableFrame(self.tab_ai, fg_color="transparent")
        scroll_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Header
        label_title = ctk.CTkLabel(
            scroll_frame, text="⚙️ Cấu hình Dịch thuật & AI",
            font=('Segoe UI', 16, 'bold'),
            text_color=('#1E3A5F', '#818CF8')
        )
        label_title.pack(pady=(15, 10))

        # --- PHẦN A: CẤU HÌNH NHANH (Smart Card) ---
        frame_quick = create_styled_card(scroll_frame, title="⚡ Cấu hình nhanh")
        frame_quick.pack(fill=tk.X, padx=20, pady=8)

        # Smart Router Checkbox
        chk_router = ctk.CTkCheckBox(
            frame_quick, text="Bật bộ định tuyến AI thông minh (Smart Router)",
            variable=self.use_router_var,
            font=('Segoe UI', 10, 'bold'),
            command=self._on_quick_router_toggled
        )
        chk_router.pack(anchor=tk.W, padx=15, pady=(5, 2))

        lbl_router_desc = ctk.CTkLabel(
            frame_quick, text="💡 Tự động chọn AI dịch tốt nhất tại thời điểm dịch, tối ưu tốc độ và chi phí.",
            text_color=self.colors['gray_medium'],
            font=('Segoe UI', 9, 'italic')
        )
        lbl_router_desc.pack(anchor=tk.W, padx=15, pady=(0, 10))

        # Mode Selection Combobox
        frame_mode_row = ctk.CTkFrame(frame_quick, fg_color="transparent")
        frame_mode_row.pack(fill=tk.X, padx=15, pady=5)

        ctk.CTkLabel(
            frame_mode_row, text="Chế độ dịch:",
            font=('Segoe UI', 10, 'bold')
        ).pack(side=tk.LEFT, padx=(0, 10))

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
            "ai_waterfall": "Nâng cao: dùng thứ tự ưu tiên bên dưới",
            "ai_pool_auto": "Tự động chọn từ pool AI miễn phí",
            "ai_pool_no_google": "Pool AI miễn phí (không dùng Google)",
            "ai_pool_with_google_last_resort": "Pool AI miễn phí (Google làm dự phòng cuối)"
        }
        initial_display_val = strategy_display_map.get(current_strategy, "Tự động chọn AI tốt nhất")

        self.strat_var = tk.StringVar(value=initial_display_val)

        # Using styled OptionMenu for strategy
        self.strat_combo = create_language_combobox(
            frame_mode_row, self.strat_var, [
                "Tự động chọn AI tốt nhất",
                "Chỉ dùng AI, không dùng Google Translate",
                "Chỉ dùng Gemini",
                "Chỉ dùng ChatAnyWhere",
                "Chỉ dùng DeepSeek",
                "Chỉ dùng NVIDIA NIM",
                "Chỉ dùng OpenAI tùy chỉnh",
                "Chỉ dùng Google Translate",
                "Nâng cao: dùng thứ tự ưu tiên bên dưới",
                "Tự động chọn từ pool AI miễn phí",
                "Pool AI miễn phí (không dùng Google)",
                "Pool AI miễn phí (Google làm dự phòng cuối)"
            ]
        )
        self.strat_combo.pack(side=tk.LEFT, padx=10)

        self.lbl_mode_rec = ctk.CTkLabel(
            frame_mode_row, text="💡 Khuyến nghị: Tự động chọn AI tốt nhất",
            text_color=self.colors['gray_medium'],
            font=('Segoe UI', 9, 'italic')
        )
        self.lbl_mode_rec.pack(side=tk.LEFT, padx=5)

        # Configured Status Summary
        frame_summary = ctk.CTkFrame(frame_quick, fg_color="transparent")
        frame_summary.pack(fill=tk.X, padx=15, pady=(10, 10))

        ctk.CTkLabel(
            frame_summary, text="Trạng thái cấu hình các nguồn AI:",
            font=('Segoe UI', 10, 'bold')
        ).pack(anchor=tk.W)

        self.lbl_quick_summary = ctk.CTkLabel(
            frame_summary, text="Đang tải...",
            text_color=self.colors['gray_dark'],
            font=('Segoe UI', 10), justify=tk.LEFT, wraplength=620
        )
        self.lbl_quick_summary.pack(fill=tk.X, anchor=tk.W, pady=2)

        # --- PHẦN B: DANH SÁCH NHÀ CUNG CẤP (Card Frame) ---
        frame_providers = create_styled_card(scroll_frame, title="🤖 Các nhà cung cấp AI hiện khả dụng")
        frame_providers.pack(fill=tk.X, padx=20, pady=8)

        columns = ("name", "enabled", "api_key_status", "key_count", "default_model")

        # Container frame for treeview and side buttons
        frame_tree_container = ctk.CTkFrame(frame_providers, fg_color="transparent")
        frame_tree_container.pack(fill=tk.BOTH, expand=True, padx=15, pady=(5, 15))

        # Move Up/Down buttons on the right side
        frame_move_buttons = ctk.CTkFrame(frame_tree_container, fg_color="transparent")
        frame_move_buttons.pack(side=tk.RIGHT, padx=(10, 0), fill=tk.Y)

        self.btn_move_to_top = create_styled_button(
            frame_move_buttons, text="▲▲ Lên trên cùng", command=self._move_provider_to_top,
            width=120
        )
        self.btn_move_to_top.pack(pady=5)

        self.btn_move_up = create_styled_button(
            frame_move_buttons, text="▲ Di chuyển lên", command=self._move_provider_up,
            width=120
        )
        self.btn_move_up.pack(pady=5)

        self.btn_move_down = create_styled_button(
            frame_move_buttons, text="▼ Di chuyển xuống", command=self._move_provider_down,
            width=120
        )
        self.btn_move_down.pack(pady=5)

        self.btn_move_to_bottom = create_styled_button(
            frame_move_buttons, text="▼▼ Xuống dưới cùng", command=self._move_provider_to_bottom,
            width=120
        )
        self.btn_move_to_bottom.pack(pady=5)

        # Styled Ttk Treeview
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
        self.frame_detail = create_styled_card(scroll_frame)
        self.frame_detail.pack(fill=tk.X, padx=20, pady=8)

        self.lbl_detail_title = ctk.CTkLabel(
            self.frame_detail, text="🛠️ Chi tiết nhà cung cấp được chọn (Vui lòng chọn dòng ở trên)",
            font=('Segoe UI', 10, 'bold'),
            text_color=('#1E3A5F', '#818CF8')
        )
        self.lbl_detail_title.pack(anchor=tk.W, padx=15, pady=(10, 5))

        # Instance vars for Section C controls
        self.selected_provider = None
        self.prov_enabled_var = tk.BooleanVar(value=False)
        self.prov_base_url_var = tk.StringVar()
        self.prov_new_key_var = tk.StringVar()
        self.prov_new_model_var = tk.StringVar()
        self.prov_default_model_var = tk.StringVar()

        # Enabled Checkbox
        self.chk_prov_enabled = ctk.CTkCheckBox(
            self.frame_detail, text="Bật nhà cung cấp này trong hệ thống",
            variable=self.prov_enabled_var,
            font=('Segoe UI', 10, 'bold'),
            state=tk.DISABLED
        )
        self.chk_prov_enabled.pack(anchor=tk.W, padx=15, pady=5)

        self.lbl_google_tip = ctk.CTkLabel(
            self.frame_detail, text="💡 Tắt Google Translate nếu bạn muốn chắc chắn chỉ dùng AI provider.",
            text_color=('#1E3A5F', '#818CF8'),
            font=('Segoe UI', 9, 'italic')
        )

        # Base URL Row
        self.frame_base_url = ctk.CTkFrame(self.frame_detail, fg_color="transparent")
        self.frame_base_url.pack(fill=tk.X, padx=15, pady=5)

        ctk.CTkLabel(
            self.frame_base_url, text="Base URL:", width=90, anchor='w',
            font=('Segoe UI', 10, 'bold')
        ).pack(side=tk.LEFT)

        self.entry_base_url = ctk.CTkEntry(
            self.frame_base_url, textvariable=self.prov_base_url_var,
            state=tk.DISABLED, corner_radius=8
        )
        self.entry_base_url.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

        # Key pool frame
        self.frame_keys = ctk.CTkFrame(self.frame_detail, fg_color="transparent")
        self.frame_keys.pack(fill=tk.X, padx=15, pady=5)

        ctk.CTkLabel(
            self.frame_keys, text="API Keys:", width=90, anchor='w',
            font=('Segoe UI', 10, 'bold')
        ).pack(side=tk.LEFT, anchor=tk.N, pady=5)

        self.frame_keys_list_buttons = ctk.CTkFrame(self.frame_keys, fg_color="transparent")
        self.frame_keys_list_buttons.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

        # Styled Listbox to match premium theme colors
        self.listbox_keys = tk.Listbox(
            self.frame_keys_list_buttons, height=3,
            bg=('#FFFFFF' if ctk.get_appearance_mode() == 'Light' else '#2E2E33'),
            fg=('#1F2937' if ctk.get_appearance_mode() == 'Light' else '#F3F4F6'),
            selectbackground=('#4A90E2' if ctk.get_appearance_mode() == 'Light' else '#6366F1'),
            selectforeground='#FFFFFF',
            borderwidth=1, relief='solid',
            font=('Consolas', 9), state=tk.DISABLED
        )
        self.listbox_keys.pack(fill=tk.X, expand=True, pady=(0, 5))

        self.frame_add_key = ctk.CTkFrame(self.frame_keys_list_buttons, fg_color="transparent")
        self.frame_add_key.pack(fill=tk.X)

        self.entry_new_key = ctk.CTkEntry(
            self.frame_add_key, textvariable=self.prov_new_key_var,
            width=200, show="*", state=tk.DISABLED, corner_radius=8,
            placeholder_text="Nhập API Key mới..."
        )
        self.entry_new_key.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))

        self.btn_add_key = create_styled_button(
            self.frame_add_key, text="Thêm Key", command=self._add_provider_key
        )
        self.btn_add_key.configure(state=tk.DISABLED)
        self.btn_add_key.pack(side=tk.LEFT, padx=2)

        self.btn_delete_key = create_styled_button(
            self.frame_add_key, text="Xóa Key", command=self._delete_provider_key
        )
        self.btn_delete_key.configure(state=tk.DISABLED)
        self.btn_delete_key.pack(side=tk.LEFT, padx=2)

        # Model catalog frame
        self.frame_models = ctk.CTkFrame(self.frame_detail, fg_color="transparent")
        self.frame_models.pack(fill=tk.X, padx=15, pady=5)

        ctk.CTkLabel(
            self.frame_models, text="Model:", width=90, anchor='w',
            font=('Segoe UI', 10, 'bold')
        ).pack(side=tk.LEFT, anchor=tk.N, pady=5)

        self.frame_models_list_buttons = ctk.CTkFrame(self.frame_models, fg_color="transparent")
        self.frame_models_list_buttons.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

        # Styled Listbox to match premium theme
        self.listbox_models = tk.Listbox(
            self.frame_models_list_buttons, height=4,
            bg=('#FFFFFF' if ctk.get_appearance_mode() == 'Light' else '#2E2E33'),
            fg=('#1F2937' if ctk.get_appearance_mode() == 'Light' else '#F3F4F6'),
            selectbackground=('#4A90E2' if ctk.get_appearance_mode() == 'Light' else '#6366F1'),
            selectforeground='#FFFFFF',
            borderwidth=1, relief='solid',
            font=('Consolas', 9), state=tk.DISABLED
        )
        self.listbox_models.pack(fill=tk.X, expand=True, pady=(0, 5))

        self.frame_add_model = ctk.CTkFrame(self.frame_models_list_buttons, fg_color="transparent")
        self.frame_add_model.pack(fill=tk.X)

        self.entry_new_model = ctk.CTkEntry(
            self.frame_add_model, textvariable=self.prov_new_model_var,
            width=200, state=tk.DISABLED, corner_radius=8,
            placeholder_text="Nhập Model ID..."
        )
        self.entry_new_model.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))

        self.btn_add_model = create_styled_button(
            self.frame_add_model, text="Thêm Model", command=self._add_provider_model
        )
        self.btn_add_model.configure(state=tk.DISABLED)
        self.btn_add_model.pack(side=tk.LEFT, padx=2)

        self.btn_delete_model = create_styled_button(
            self.frame_add_model, text="Xóa Model", command=self._delete_provider_model
        )
        self.btn_delete_model.configure(state=tk.DISABLED)
        self.btn_delete_model.pack(side=tk.LEFT, padx=2)

        self.btn_refresh_models = create_styled_button(
            self.frame_add_model, text="Làm mới model", command=self._refresh_provider_models_catalog
        )
        self.btn_refresh_models.configure(state=tk.DISABLED)
        self.btn_refresh_models.pack(side=tk.LEFT, padx=2)

        # Default model row
        self.frame_model = ctk.CTkFrame(self.frame_detail, fg_color="transparent")
        self.frame_model.pack(fill=tk.X, padx=15, pady=5)

        ctk.CTkLabel(
            self.frame_model, text="Model mặc định:", width=90, anchor='w',
            font=('Segoe UI', 10, 'bold')
        ).pack(side=tk.LEFT)

        # Compatibility Wrapper OptionMenu
        self.combo_model = create_language_combobox(self.frame_model, self.prov_default_model_var, [])
        original_configure = self.combo_model.configure
        def compat_configure(**kwargs):
            if "state" in kwargs:
                if kwargs["state"] == "readonly":
                    kwargs["state"] = "normal"
            original_configure(**kwargs)
        self.combo_model.configure = compat_configure
        self.combo_model.pack(side=tk.LEFT, padx=5)

        # Refresh status label
        self.lbl_refresh_status = ctk.CTkLabel(
            self.frame_detail, text="",
            text_color=self.colors['gray_medium'],
            font=('Segoe UI', 9, 'italic'), anchor='w', justify=tk.LEFT
        )
        self.lbl_refresh_status.pack(fill=tk.X, padx=15, pady=(2, 5))

        # Section C action buttons
        self.frame_detail_actions = ctk.CTkFrame(self.frame_detail, fg_color="transparent")
        self.frame_detail_actions.pack(fill=tk.X, padx=15, pady=(10, 15))

        self.btn_save_prov = create_styled_button(
            self.frame_detail_actions, text="💾 Lưu cấu hình nhà cung cấp", command=self._save_provider_detail
        )
        self.btn_save_prov.configure(state=tk.DISABLED)
        self.btn_save_prov.pack(side=tk.LEFT)

        # --- PHẦN D: THÔNG TIN KỸ THUẬT / NÂNG CAO ---
        self.frame_advanced_router = create_styled_card(scroll_frame, title="📊 Trạng thái hoạt động nâng cao (Debug/Router Health)")
        self.frame_advanced_router.pack(fill=tk.X, padx=20, pady=8)

        # Router stats row
        frame_router_stats = ctk.CTkFrame(self.frame_advanced_router, fg_color="transparent")
        frame_router_stats.pack(fill=tk.X, padx=15, pady=(0, 5))

        self.lbl_router_status = ctk.CTkLabel(
            frame_router_stats, text="Trạng thái Smart Router: Đang kiểm tra...",
            font=('Segoe UI', 10, 'bold'), anchor='w'
        )
        self.lbl_router_status.pack(fill=tk.X, side=tk.TOP, anchor=tk.W, pady=(0, 5))

        frame_router_buttons = ctk.CTkFrame(frame_router_stats, fg_color="transparent")
        frame_router_buttons.pack(fill=tk.X)

        create_styled_button(
            frame_router_buttons, text="Làm mới trạng thái", command=self._refresh_router_health
        ).pack(side=tk.RIGHT, padx=5)

        create_styled_button(
            frame_router_buttons, text="Reset Cooldowns (Khôi phục)", command=self._reset_router_cooldowns
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
        self.router_tree.pack(fill=tk.BOTH, expand=True, padx=15, pady=(5, 15))

        # Save general settings row (Legacy section 4 TM/Glossary integration)
        frame_general_save = create_styled_card(scroll_frame, title="⚙️ Cài đặt nâng cao (Bộ nhớ & Thuật ngữ)")
        frame_general_save.pack(fill=tk.X, padx=20, pady=(8, 20))

        # Row 1: Translation Memory Settings
        tm_row = ctk.CTkFrame(frame_general_save, fg_color="transparent")
        tm_row.pack(fill=tk.X, padx=15, pady=5)

        ctk.CTkCheckBox(
            tm_row, text="Bật Bộ nhớ dịch (Translation Memory)",
            variable=self.use_tm_var,
            font=('Segoe UI', 10)
        ).pack(side=tk.LEFT)

        ctk.CTkLabel(tm_row, text="Độ dài tối thiểu segment lưu cache:", font=('Segoe UI', 10)).pack(side=tk.LEFT, padx=(20, 5))
        ctk.CTkEntry(tm_row, textvariable=self.min_seg_len_var, width=60, corner_radius=8).pack(side=tk.LEFT)

        # Row 1.5: TM Quality Policy Settings
        tm_policy_row = ctk.CTkFrame(frame_general_save, fg_color="transparent")
        tm_policy_row.pack(fill=tk.X, padx=15, pady=5)

        ctk.CTkLabel(tm_policy_row, text="Chính sách chất lượng TM:", font=('Segoe UI', 10)).pack(side=tk.LEFT, padx=(5, 5))
        tm_policy_combo = create_language_combobox(
            tm_policy_row, self.tm_policy_var,
            ["Ưu tiên bộ nhớ dịch", "Chỉ gợi ý, vẫn dịch lại bằng AI", "Dịch lại và cập nhật bộ nhớ", "Tắt bộ nhớ dịch"]
        )
        tm_policy_combo.pack(side=tk.LEFT, padx=5)

        # Row 2: Glossary Settings
        glossary_row = ctk.CTkFrame(frame_general_save, fg_color="transparent")
        glossary_row.pack(fill=tk.X, padx=15, pady=5)

        ctk.CTkCheckBox(
            glossary_row, text="Bật Thuật ngữ (Glossary)",
            variable=self.use_glossary_var,
            font=('Segoe UI', 10)
        ).pack(side=tk.LEFT)

        ctk.CTkLabel(glossary_row, text="Cấp độ thực thi:", font=('Segoe UI', 10)).pack(side=tk.LEFT, padx=(20, 5))

        def _on_glossary_level_changed(*args):
            level = self.glossary_level_var.get()
            if level == "validate":
                self.glossary_note_label.configure(text="💡 Note: 'validate' được dành riêng cho các tính năng tương lai.", text_color="orange")
            else:
                self.glossary_note_label.configure(text="💡 Cài đặt thực thi thuật ngữ thành công.", text_color="green")

        self.glossary_level_var.trace_add("write", _on_glossary_level_changed)
        glossary_level_combo = create_language_combobox(
            glossary_row, self.glossary_level_var,
            ["off", "prompt", "validate"]
        )
        glossary_level_combo.pack(side=tk.LEFT)
        ctk.CTkLabel(glossary_row, text="Max terms/segment:", font=('Segoe UI', 10)).pack(side=tk.LEFT, padx=(20, 5))

        # Max glossary entries input
        ctk.CTkEntry(glossary_row, textvariable=self.max_glossary_terms_var, width=60, corner_radius=8).pack(side=tk.LEFT)

        self.glossary_note_label = ctk.CTkLabel(
            frame_general_save, text="💡 Thuật ngữ giúp chuẩn hóa các cụm từ chuyên ngành.",
            text_color=self.colors['gray_medium'], font=('Segoe UI', 9, 'italic')
        )
        self.glossary_note_label.pack(anchor=tk.W, padx=15, pady=(2, 5))

        # Row for Auto Refresh setting
        auto_refresh_row = ctk.CTkFrame(frame_general_save, fg_color="transparent")
        auto_refresh_row.pack(fill=tk.X, padx=15, pady=5)

        ctk.CTkCheckBox(
            auto_refresh_row, text="Tự động làm mới model khi mở app",
            variable=self.auto_refresh_provider_models_var,
            font=('Segoe UI', 10)
        ).pack(side=tk.LEFT)

        ctk.CTkLabel(
            auto_refresh_row, text="💡 Tự động tải danh sách model mới của OpenAI/NVIDIA trong background.",
            text_color=self.colors['gray_medium'], font=('Segoe UI', 9, 'italic')
        ).pack(side=tk.LEFT, padx=(10, 0))

        # Row 3: Save button
        save_btn_row = ctk.CTkFrame(frame_general_save, fg_color="transparent")
        save_btn_row.pack(fill=tk.X, padx=15, pady=(5, 15))

        create_styled_button(
            save_btn_row, text="💾 Lưu cài đặt nâng cao",
            command=self._save_advanced_settings
        ).pack(side=tk.LEFT)

        # --- PHẦN E: THIẾT LẬP NHANH API KEY CHO NGƯỜI MỚI (WIZARD) ---
        frame_guide = create_styled_card(scroll_frame, title="📚 Hướng dẫn & Thiết lập nhanh API Key (Dành cho Người mới)")
        frame_guide.pack(fill=tk.X, padx=20, pady=(8, 20))

        self.guide_data = {
            "gemini": {
                "name": "Gemini AI (Google)",
                "difficulty": "Dễ",
                "difficulty_color": ("#059669", "#34D399"),
                "free_tier": "Có (Free Tier cực kỳ hào phóng)",
                "recommend": "Khuyên dùng ngay (Khởi đầu tốt nhất cho mọi người)",
                "needs": "Khóa API Key",
                "suggested_model": "gemini-2.5-flash",
                "url": "https://aistudio.google.com/",
                "steps": [
                    "1. Bấm nút '🌐 Mở trang lấy API Key' để truy cập Google AI Studio.",
                    "2. Đăng nhập bằng tài khoản Google của bạn.",
                    "3. Chọn 'Create API Key' -> Chọn một dự án -> Sao chép khóa API được tạo ra.",
                    "4. Bấm nút '🔍 Chọn nhà cung cấp này ở bảng trên' để tự động chuyển sang cấu hình Gemini.",
                    "5. Dán khóa API vừa sao chép vào ô 'API Keys'.",
                    "6. Bấm nút 'Thêm Key' rồi bấm '💾 Lưu cấu hình nhà cung cấp' ở phía dưới.",
                    "7. Chọn chế độ dịch 'Tự động chọn từ pool AI miễn phí' ở phần Cấu hình nhanh."
                ],
                "errors": "Lỗi 429 (Hết hạn mức): Gemini Free giới hạn 15 request/phút. App sẽ tự chuyển sang AI khác trong pool nếu bạn cấu hình thêm Groq/OpenRouter."
            },
            "groq": {
                "name": "Groq AI",
                "difficulty": "Dễ",
                "difficulty_color": ("#059669", "#34D399"),
                "free_tier": "Có (Miễn phí hoàn toàn theo hạn mức tốc độ)",
                "recommend": "Khuyên dùng ngay (Tốc độ dịch siêu tốc, gần như tức thời)",
                "needs": "Khóa API Key",
                "suggested_model": "llama3-8b-8192",
                "url": "https://console.groq.com/keys",
                "steps": [
                    "1. Bấm '🌐 Mở trang lấy API Key' để truy cập Groq Console.",
                    "2. Đăng nhập hoặc tạo tài khoản miễn phí.",
                    "3. Vào mục 'API Keys' -> Bấm 'Create API Key' -> Copy khóa vừa sinh.",
                    "4. Bấm nút '🔍 Chọn nhà cung cấp này ở bảng trên'.",
                    "5. Dán khóa API vào ô 'API Keys' -> Bấm 'Thêm Key' -> Bấm '💾 Lưu cấu hình'.",
                    "6. Bạn đã sẵn sàng sử dụng Groq trong Pool AI."
                ],
                "errors": "Lỗi 401: Key chưa kích hoạt hoặc sai ký tự. Lỗi 429: Hạn mức RPM/TPM của gói free đã hết, hãy chờ 1 phút hoặc để Router tự động chuyển sang AI khác."
            },
            "openrouter": {
                "name": "OpenRouter",
                "difficulty": "Dễ",
                "difficulty_color": ("#059669", "#34D399"),
                "free_tier": "Có nhiều Model miễn phí chất lượng",
                "recommend": "Khuyên dùng ngay (Kho model phong phú, cập nhật liên tục)",
                "needs": "Khóa API Key",
                "suggested_model": "google/gemini-2.5-flash:free",
                "url": "https://openrouter.ai/keys",
                "steps": [
                    "1. Bấm '🌐 Mở trang lấy API Key' để truy cập OpenRouter.",
                    "2. Đăng nhập bằng tài khoản Google hoặc Github.",
                    "3. Vào phần 'Keys' -> Chọn 'Create Key' -> Sao chép khóa.",
                    "4. Bấm nút '🔍 Chọn nhà cung cấp này ở bảng trên'.",
                    "5. Dán khóa API vào ô 'API Keys' -> Bấm 'Thêm Key' -> Bấm '💾 Lưu cấu hình'."
                ],
                "errors": "Lỗi 401: Key không hợp lệ. Lỗi 402: Hết tiền (nếu chọn model trả phí, hãy đảm bảo chọn đúng model có nhãn ':free')."
            },
            "deepseek": {
                "name": "DeepSeek",
                "difficulty": "Dễ",
                "difficulty_color": ("#059669", "#34D399"),
                "free_tier": "Tặng credit dùng thử / Giá cực rẻ",
                "recommend": "Khuyên dùng ngay (Chất lượng dịch thuật xuất sắc nhất)",
                "needs": "Khóa API Key",
                "suggested_model": "deepseek-v4-flash",
                "url": "https://platform.deepseek.com/api_keys",
                "steps": [
                    "1. Bấm '🌐 Mở trang lấy API Key' để đăng nhập DeepSeek Platform.",
                    "2. Tạo tài khoản -> Vào mục 'API Keys' -> Bấm 'Create API Key'.",
                    "3. Sao chép khóa -> Bấm '🔍 Chọn nhà cung cấp này ở bảng trên'.",
                    "4. Dán khóa API vào ô 'API Keys' -> Bấm 'Thêm Key' -> Bấm '💾 Lưu cấu hình'."
                ],
                "errors": "Lỗi 402 (Hết số dư): Tài khoản dùng thử đã hết hạn hoặc hết tiền. Hãy nạp một lượng nhỏ (khoảng 2-5$) để dùng cực lâu nhờ giá siêu rẻ."
            },
            "mistral": {
                "name": "Mistral AI",
                "difficulty": "Dễ",
                "difficulty_color": ("#059669", "#34D399"),
                "free_tier": "Có dùng thử hạn chế",
                "recommend": "Khuyên dùng ngay (Rất tốt cho dịch thuật đa ngôn ngữ)",
                "needs": "Khóa API Key",
                "suggested_model": "mistral-tiny",
                "url": "https://console.mistral.ai/api-keys/",
                "steps": [
                    "1. Bấm '🌐 Mở trang lấy API Key' để vào Mistral Console.",
                    "2. Tạo tài khoản -> Chọn mục 'API Keys' -> Nhấp 'Create new key'.",
                    "3. Copy key -> Bấm '🔍 Chọn nhà cung cấp này ở bảng trên'.",
                    "4. Dán khóa API vào ô 'API Keys' -> Bấm 'Thêm Key' -> Bấm '💾 Lưu cấu hình'."
                ],
                "errors": "Lỗi 403: Không có quyền truy cập API. Lỗi 429: Vượt quá tốc độ free-tier."
            },
            "cerebras": {
                "name": "Cerebras AI",
                "difficulty": "Trung bình",
                "difficulty_color": ("#D97706", "#FBBF24"),
                "free_tier": "Có (Gói Free beta cực rộng rãi)",
                "recommend": "Dành cho người dùng nâng cao (Có thể cấu hình sau)",
                "needs": "Khóa API Key",
                "suggested_model": "llama3.1-8b",
                "url": "https://cloud.cerebras.ai/",
                "steps": [
                    "1. Đăng ký tài khoản trên Cerebras Cloud.",
                    "2. Vào dashboard -> Chọn mục 'API Keys' -> Tạo khóa mới.",
                    "3. Chọn Cerebras trên bảng nhà cung cấp và dán key vào."
                ],
                "errors": "Chủ yếu gặp lỗi 429 nếu bạn gửi yêu cầu dịch tệp quá dồn dập."
            },
            "sambanova": {
                "name": "SambaNova Cloud",
                "difficulty": "Trung bình",
                "difficulty_color": ("#D97706", "#FBBF24"),
                "free_tier": "Có (Gói beta miễn phí)",
                "recommend": "Dành cho người dùng nâng cao (Có thể cấu hình sau)",
                "needs": "Khóa API Key",
                "suggested_model": "meta-llama/Llama-3-8B-Instruct",
                "url": "https://cloud.sambanova.ai/",
                "steps": [
                    "1. Truy cập SambaNova Cloud và tạo tài khoản.",
                    "2. Vào mục 'API Keys' -> Tạo khóa API của bạn.",
                    "3. Chọn SambaNova ở bảng trên -> Dán khóa -> Thêm Key -> Lưu cấu hình."
                ],
                "errors": "Lỗi 429: SambaNova giới hạn tốc độ gắt gao trên tài khoản free."
            },
            "cloudflare": {
                "name": "Cloudflare Workers AI",
                "difficulty": "Khó",
                "difficulty_color": ("#DC2626", "#F87171"),
                "free_tier": "Có (Hạn mức hàng ngày 10k request free)",
                "recommend": "Dành cho người dùng nâng cao (Yêu cầu kỹ năng cấu hình)",
                "needs": "API Token + Account ID + Base URL cụ thể",
                "suggested_model": "@cf/meta/llama-3-8b-instruct",
                "url": "https://dash.cloudflare.com/",
                "steps": [
                    "1. Đăng nhập Cloudflare Dashboard -> Vào 'AI' -> Lấy Account ID của bạn.",
                    "2. Tạo API Token với quyền 'Workers AI: Read' tại trang quản lý token.",
                    "3. Chọn Cloudflare ở bảng trên -> Nhập Base URL dạng: https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/ai/run",
                    "4. Điền API Token vào ô 'API Keys' -> Thêm Key -> Lưu cấu hình."
                ],
                "errors": "Lỗi 400/Bad Request: URL chứa Account ID sai hoặc Model ID không tồn tại trên Cloudflare AI."
            },
            "huggingface": {
                "name": "HuggingFace Inference API",
                "difficulty": "Trung bình",
                "difficulty_color": ("#D97706", "#FBBF24"),
                "free_tier": "Có (Inference miễn phí cho cộng đồng)",
                "recommend": "Dành cho người dùng nâng cao (Có thể cấu hình sau)",
                "needs": "Access Token (Read)",
                "suggested_model": "meta-llama/Meta-Llama-3-8B-Instruct",
                "url": "https://huggingface.co/settings/tokens",
                "steps": [
                    "1. Đăng nhập HuggingFace -> Vào Settings -> Access Tokens.",
                    "2. Nhấp 'Create new token' -> Chọn loại 'Read' -> Đặt tên và lưu lại.",
                    "3. Chọn HuggingFace ở bảng trên -> Dán token vào ô 'API Keys'."
                ],
                "errors": "Lỗi 503 (Model loading): Model đang được tải lên server HuggingFace, hãy thử lại sau vài giây hoặc cấu hình model phổ biến khác."
            },
            "github": {
                "name": "GitHub Models",
                "difficulty": "Khó",
                "difficulty_color": ("#DC2626", "#F87171"),
                "free_tier": "Có (Hạn mức reset hàng ngày theo tài khoản Github)",
                "recommend": "Dành cho người dùng nâng cao (Yêu cầu đăng ký duyệt marketplace)",
                "needs": "Personal Access Token (classic hoặc fine-grained)",
                "suggested_model": "meta-llama-3-8b-instruct",
                "url": "https://github.com/settings/tokens",
                "steps": [
                    "1. Đăng ký tài khoản Github và đăng ký quyền truy cập Github Models Marketplace.",
                    "2. Vào GitHub Settings -> Developer Settings -> Personal Access Tokens -> classic -> Tạo token.",
                    "3. Chọn GitHub Models ở bảng trên -> Dán token Github làm API key -> Thêm Key."
                ],
                "errors": "Lỗi 403: Token không có quyền hoặc tài khoản chưa được phê duyệt truy cập GitHub Models Marketplace."
            },
            "ai21": {
                "name": "AI21 Studio",
                "difficulty": "Trung bình",
                "difficulty_color": ("#D97706", "#FBBF24"),
                "free_tier": "Có dùng thử",
                "recommend": "Dành cho người dùng nâng cao (Có thể cấu hình sau)",
                "needs": "Khóa API Key",
                "suggested_model": "jamba-1.5-mini",
                "url": "https://studio.ai21.com/",
                "steps": [
                    "1. Tạo tài khoản AI21 Studio.",
                    "2. Sao chép API Key mặc định từ trang quản trị của bạn.",
                    "3. Chọn AI21 Studio ở bảng trên -> Dán khóa -> Thêm Key -> Lưu cấu hình."
                ],
                "errors": "Lỗi 401: API key không hợp lệ hoặc tài khoản đã hết thời hạn dùng thử miễn phí."
            },
            "nvidia_nim": {
                "name": "NVIDIA NIM",
                "difficulty": "Trung bình",
                "difficulty_color": ("#D97706", "#FBBF24"),
                "free_tier": "Có (Tặng 1000 credit trải nghiệm free)",
                "recommend": "Dành cho người dùng nâng cao (Có thể cấu hình sau)",
                "needs": "Khóa API Key (nvapi-...)",
                "suggested_model": "meta/llama-3.1-405b-instruct",
                "url": "https://build.nvidia.com/",
                "steps": [
                    "1. Tạo tài khoản Nvidia Developer.",
                    "2. Chọn một model bất kỳ -> Chọn 'Get API Key' -> Tạo khóa và lưu lại.",
                    "3. Chọn NVIDIA NIM ở bảng trên -> Dán khóa nvapi- vào -> Thêm Key."
                ],
                "errors": "Lỗi 403: API key bị từ chối hoặc hết hạn mức tín dụng trải nghiệm miễn phí."
            },
            "chatanywhere": {
                "name": "ChatAnyWhere Proxy",
                "difficulty": "Dễ",
                "difficulty_color": ("#059669", "#34D399"),
                "free_tier": "Có (Hạn mức miễn phí 200 req/ngày)",
                "recommend": "Khuyên dùng ngay (Thích hợp cho học tập/phát triển)",
                "needs": "Khóa API Key",
                "suggested_model": "gpt-4o-mini",
                "url": "https://github.com/chatanywhere/GPT_API_free",
                "steps": [
                    "1. Truy cập trang GitHub của ChatAnyWhere.",
                    "2. Thực hiện theo liên kết hướng dẫn để nhận API key miễn phí.",
                    "3. Chọn ChatAnyWhere ở bảng trên -> Dán key vào ô 'API Keys'."
                ],
                "errors": "Lỗi 429: Hạn mức gọi API miễn phí hàng ngày đã hết. Hãy chờ sang ngày hôm sau."
            },
            "openai_compatible": {
                "name": "OpenAI tùy chỉnh / Local",
                "difficulty": "Trung bình",
                "difficulty_color": ("#D97706", "#FBBF24"),
                "free_tier": "Phụ thuộc nguồn của bạn",
                "recommend": "Dành cho người dùng nâng cao (Cấu hình model local Ollama/LM Studio)",
                "needs": "Base URL + Model ID + API Key (nếu có)",
                "suggested_model": "gpt-4o-mini",
                "url": "http://localhost:1234/v1",
                "steps": [
                    "1. Đảm bảo server local (LM Studio / Ollama) của bạn đang chạy.",
                    "2. Chọn 'OpenAI tùy chỉnh' ở bảng trên.",
                    "3. Điền Base URL (ví dụ: http://localhost:1234/v1).",
                    "4. Điền model ID tương ứng -> Dán key (hoặc nhập 'lm-studio' nếu dùng local) -> Lưu cấu hình."
                ],
                "errors": "Lỗi Connection Error: Không thể kết nối tới Base URL. Hãy kiểm tra xem server local đã được khởi động chưa."
            }
        }

        # I. Khung giới thiệu "Người mới nên làm gì?"
        frame_onboard = ctk.CTkFrame(frame_guide, fg_color=("#F3F4F6", "#1E1E22"), corner_radius=8)
        frame_onboard.pack(fill=tk.X, padx=15, pady=(10, 5))

        lbl_onboard_title = ctk.CTkLabel(
            frame_onboard, text="💡 Người mới bắt đầu nên làm gì?",
            font=('Segoe UI', 11, 'bold'),
            text_color=('#1F2937', '#F3F4F6')
        )
        lbl_onboard_title.pack(anchor=tk.W, padx=15, pady=(8, 4))

        onboard_texts = [
            "• Bạn KHÔNG CẦN phải lấy đầy đủ cả 15 khóa API để ứng dụng hoạt động.",
            "• Khuyến nghị bắt đầu: Chỉ cần lấy API key của 3 nhà cung cấp chính: Gemini AI, Groq và OpenRouter.",
            "• Mở rộng sau: Khi đã quen, bạn có thể đăng ký thêm DeepSeek, Mistral AI, Cerebras, SambaNova...",
            "• Google Translate: Mặc định được bật và không yêu cầu key, có thể dùng làm dự phòng cuối cùng."
        ]
        for t in onboard_texts:
            lbl_item = ctk.CTkLabel(
                frame_onboard, text=t,
                font=('Segoe UI', 10),
                text_color=('#4B5563', '#9CA3AF'),
                justify=tk.LEFT,
                wraplength=650
            )
            lbl_item.pack(anchor=tk.W, padx=25, pady=2)

        # Space
        ctk.CTkLabel(frame_guide, text="", height=5, fg_color="transparent").pack()

        # II. Khung chọn nhà cung cấp
        frame_select_row = ctk.CTkFrame(frame_guide, fg_color="transparent")
        frame_select_row.pack(fill=tk.X, padx=15, pady=5)

        ctk.CTkLabel(
            frame_select_row, text="1️⃣ Bước 1: Chọn nhà cung cấp:",
            font=('Segoe UI', 11, 'bold')
        ).pack(side=tk.LEFT, padx=(0, 10))

        self.wizard_prov_var = tk.StringVar(value="Gemini AI")

        # Display name mapping to internal name
        self.wizard_display_to_internal = {
            "Gemini AI": "gemini",
            "Groq": "groq",
            "OpenRouter": "openrouter",
            "DeepSeek": "deepseek",
            "Mistral AI": "mistral",
            "Cerebras": "cerebras",
            "SambaNova": "sambanova",
            "Cloudflare Workers AI": "cloudflare",
            "HuggingFace": "huggingface",
            "GitHub Models": "github",
            "AI21 Studio": "ai21",
            "NVIDIA NIM": "nvidia_nim",
            "ChatAnyWhere": "chatanywhere",
            "OpenAI tùy chỉnh": "openai_compatible"
        }

        # Create dropdown
        self.wizard_combo = create_language_combobox(
            frame_select_row, self.wizard_prov_var,
            list(self.wizard_display_to_internal.keys())
        )
        self.wizard_combo.pack(side=tk.LEFT, padx=5)

        # III. Thẻ hướng dẫn chi tiết (Dynamic card)
        self.frame_wizard_card = ctk.CTkFrame(frame_guide, fg_color=("#F9FAFB", "#2E2E33"), border_width=1, border_color=('#E5E7EB', '#4B5563'), corner_radius=8)
        self.frame_wizard_card.pack(fill=tk.X, padx=15, pady=8)

        # Grid layout for fields in card
        self.frame_wizard_card.columnconfigure(1, weight=1)

        # 1. Tên
        self.lbl_wiz_name = ctk.CTkLabel(
            self.frame_wizard_card, text="Gemini AI",
            font=('Segoe UI', 13, 'bold'),
            text_color=('#1E3A5F', '#818CF8')
        )
        self.lbl_wiz_name.grid(row=0, column=0, columnspan=2, sticky=tk.W, padx=15, pady=(10, 5))

        # 2. Hàng thông số (Mức độ, Miễn phí, Khuyên dùng)
        self.frame_wiz_stats = ctk.CTkFrame(self.frame_wizard_card, fg_color="transparent")
        self.frame_wiz_stats.grid(row=1, column=0, columnspan=2, sticky=tk.W, padx=15, pady=2)

        self.lbl_wiz_diff_lbl = ctk.CTkLabel(self.frame_wiz_stats, text="Độ dễ: ", font=('Segoe UI', 10, 'bold'))
        self.lbl_wiz_diff_lbl.pack(side=tk.LEFT)
        self.lbl_wiz_diff = ctk.CTkLabel(self.frame_wiz_stats, text="Dễ", font=('Segoe UI', 10, 'bold'), text_color="#10B981")
        self.lbl_wiz_diff.pack(side=tk.LEFT, padx=(0, 15))

        self.lbl_wiz_free_lbl = ctk.CTkLabel(self.frame_wiz_stats, text="Miễn phí: ", font=('Segoe UI', 10, 'bold'))
        self.lbl_wiz_free_lbl.pack(side=tk.LEFT)
        self.lbl_wiz_free = ctk.CTkLabel(self.frame_wiz_stats, text="Có (Free Tier)", font=('Segoe UI', 10), text_color=('#1F2937', '#F3F4F6'))
        self.lbl_wiz_free.pack(side=tk.LEFT, padx=(0, 15))

        self.lbl_wiz_rec_lbl = ctk.CTkLabel(self.frame_wiz_stats, text="Khuyên dùng: ", font=('Segoe UI', 10, 'bold'))
        self.lbl_wiz_rec_lbl.pack(side=tk.LEFT)
        self.lbl_wiz_rec = ctk.CTkLabel(self.frame_wiz_stats, text="Nên dùng", font=('Segoe UI', 10), text_color=('#1F2937', '#F3F4F6'))
        self.lbl_wiz_rec.pack(side=tk.LEFT)

        # 3. Thông tin yêu cầu
        self.lbl_wiz_req_lbl = ctk.CTkLabel(self.frame_wizard_card, text="Cần điền trong app:", font=('Segoe UI', 10, 'bold'))
        self.lbl_wiz_req_lbl.grid(row=2, column=0, sticky=tk.W, padx=15, pady=2)
        self.lbl_wiz_req = ctk.CTkLabel(self.frame_wizard_card, text="API Key", font=('Segoe UI', 10))
        self.lbl_wiz_req.grid(row=2, column=1, sticky=tk.W, padx=5, pady=2)

        # 4. Model gợi ý
        self.lbl_wiz_model_lbl = ctk.CTkLabel(self.frame_wizard_card, text="Model khuyên dùng:", font=('Segoe UI', 10, 'bold'))
        self.lbl_wiz_model_lbl.grid(row=3, column=0, sticky=tk.W, padx=15, pady=2)
        self.lbl_wiz_model = ctk.CTkLabel(self.frame_wizard_card, text="gemini-2.5-flash", font=('Segoe UI', 10, 'bold'), text_color=('#3B82F6', '#60A5FA'))
        self.lbl_wiz_model.grid(row=3, column=1, sticky=tk.W, padx=5, pady=2)

        # 5. Các bước thực hiện
        self.lbl_wiz_steps_lbl = ctk.CTkLabel(self.frame_wizard_card, text="Các bước thực hiện:", font=('Segoe UI', 10, 'bold'))
        self.lbl_wiz_steps_lbl.grid(row=4, column=0, sticky=tk.NW, padx=15, pady=(5, 2))

        self.frame_wiz_steps = ctk.CTkFrame(self.frame_wizard_card, fg_color="transparent")
        self.frame_wiz_steps.grid(row=4, column=1, sticky=tk.W, padx=5, pady=(5, 2))

        # 6. Lỗi thường gặp
        self.lbl_wiz_err_lbl = ctk.CTkLabel(self.frame_wizard_card, text="Lỗi thường gặp:", font=('Segoe UI', 10, 'bold'), text_color=('#DC2626', '#F87171'))
        self.lbl_wiz_err_lbl.grid(row=5, column=0, sticky=tk.NW, padx=15, pady=(5, 10))
        self.lbl_wiz_err = ctk.CTkLabel(self.frame_wizard_card, text="-", font=('Segoe UI', 10, 'italic'), justify=tk.LEFT, wraplength=520)
        self.lbl_wiz_err.grid(row=5, column=1, sticky=tk.W, padx=5, pady=(5, 10))

        # IV. Thanh công cụ hành động nhanh
        self.frame_wizard_actions = ctk.CTkFrame(frame_guide, fg_color="transparent")
        self.frame_wizard_actions.pack(fill=tk.X, padx=15, pady=(5, 15))

        self.btn_wiz_open_link = create_styled_button(
            self.frame_wizard_actions, text="🌐 Mở trang lấy API Key", command=self._on_wizard_open_link
        )
        self.btn_wiz_open_link.pack(side=tk.LEFT, padx=2)

        self.btn_wiz_copy_model = create_styled_button(
            self.frame_wizard_actions, text="📋 Sao chép Model gợi ý", command=self._on_wizard_copy_model
        )
        self.btn_wiz_copy_model.pack(side=tk.LEFT, padx=2)

        self.btn_wiz_focus = create_styled_button(
            self.frame_wizard_actions, text="🔍 Chọn nhà cung cấp ở trên", command=self._on_wizard_focus_provider
        )
        self.btn_wiz_focus.pack(side=tk.LEFT, padx=2)

        # Test Connection button wired to health checker
        self.btn_wiz_test_conn = create_styled_button(
            self.frame_wizard_actions, text="🔌 Kiểm tra kết nối", command=self._on_wizard_test_connection
        )
        self.btn_wiz_test_conn.pack(side=tk.LEFT, padx=2)

        # Wire Combobox trace
        self.wizard_prov_var.trace_add("write", self._on_wizard_selection_changed)

        # Initialize guide content
        self._on_wizard_selection_changed()

        # --- PHẦN F: KIỂM TRA KẾT NỐI & MODEL (HEALTH CHECKER) ---
        frame_health = create_styled_card(scroll_frame, title="🛡️ Kiểm tra kết nối & Mô hình (Health Checker)")
        frame_health.pack(fill=tk.X, padx=20, pady=(8, 20))

        # Row 1: Select provider and model input
        frame_health_controls = ctk.CTkFrame(frame_health, fg_color="transparent")
        frame_health_controls.pack(fill=tk.X, padx=15, pady=5)

        ctk.CTkLabel(frame_health_controls, text="Chọn nhà cung cấp:", font=('Segoe UI', 10, 'bold')).pack(side=tk.LEFT, padx=(0, 5))

        self.health_prov_var = ctk.StringVar(value="Gemini AI")

        # We need a display label matching the catalog list
        provider_display_names = [
            "Gemini AI", "Groq", "Cerebras", "OpenRouter", "Mistral AI", "SambaNova",
            "Cloudflare Workers AI", "HuggingFace", "GitHub Models", "AI21 Studio",
            "ChatAnyWhere", "DeepSeek", "NVIDIA NIM", "OpenAI tùy chỉnh", "Google Translate"
        ]

        self.health_prov_combo = ctk.CTkComboBox(
            frame_health_controls,
            values=provider_display_names,
            variable=self.health_prov_var,
            width=180
        )
        self.health_prov_combo.pack(side=tk.LEFT, padx=(0, 15))

        ctk.CTkLabel(frame_health_controls, text="Mô hình tùy chọn:", font=('Segoe UI', 10, 'bold')).pack(side=tk.LEFT, padx=(0, 5))

        self.health_model_var = ctk.StringVar()
        self.health_model_combo = ctk.CTkComboBox(
            frame_health_controls,
            values=[],
            variable=self.health_model_var,
            width=250,
            state="normal"
        )
        self.health_model_combo.pack(side=tk.LEFT)
        self.entry_health_model = self.health_model_combo

        # Row 2: Action buttons
        frame_health_actions = ctk.CTkFrame(frame_health, fg_color="transparent")
        frame_health_actions.pack(fill=tk.X, padx=15, pady=5)

        self.btn_health_provider = create_styled_button(
            frame_health_actions, text="🔌 Kiểm tra Provider", command=self._on_health_check_provider
        )
        self.btn_health_provider.pack(side=tk.LEFT, padx=2)

        self.btn_health_model = create_styled_button(
            frame_health_actions, text="🎯 Kiểm tra Model", command=self._on_health_check_model
        )
        self.btn_health_model.pack(side=tk.LEFT, padx=2)

        self.btn_health_models = create_styled_button(
            frame_health_actions, text="🔍 Quét Model của Provider", command=self._on_health_check_provider_models
        )
        self.btn_health_models.pack(side=tk.LEFT, padx=2)

        self.btn_health_all = create_styled_button(
            frame_health_actions, text="🌐 Quét toàn bộ AI đã bật", command=self._on_health_check_all_configured
        )
        self.btn_health_all.pack(side=tk.LEFT, padx=2)

        self.btn_health_cancel = create_styled_button(
            frame_health_actions, text="🛑 Dừng kiểm tra", command=self._on_health_cancel,
            fg_color=("#EF4444", "#DC2626"), hover_color=("#DC2626", "#B91C1C")
        )
        self.btn_health_cancel.configure(state=tk.DISABLED)
        self.btn_health_cancel.pack(side=tk.LEFT, padx=2)

        # Row 3: Status & Progress
        frame_health_status = ctk.CTkFrame(frame_health, fg_color="transparent")
        frame_health_status.pack(fill=tk.X, padx=15, pady=5)

        self.lbl_health_status = ctk.CTkLabel(
            frame_health_status, text="Sẵn sàng thực hiện kiểm tra.",
            text_color=self.colors['gray_medium'],
            font=('Segoe UI', 9, 'italic')
        )
        self.lbl_health_status.pack(side=tk.LEFT, padx=(0, 10))

        self.progress_health = ctk.CTkProgressBar(frame_health_status, width=200)
        self.progress_health.configure(mode="indeterminate")

        # Row 4: Results Treeview table
        frame_health_table = ctk.CTkFrame(frame_health, fg_color="transparent")
        frame_health_table.pack(fill=tk.BOTH, expand=True, padx=15, pady=10)

        columns = ("provider", "model", "status", "latency", "details", "suggestion")
        self.health_tree = ttk.Treeview(frame_health_table, columns=columns, show="headings", height=6)
        self.health_tree.heading("provider", text="Nhà cung cấp")
        self.health_tree.heading("model", text="Mô hình")
        self.health_tree.heading("status", text="Trạng thái")
        self.health_tree.heading("latency", text="Thời gian")
        self.health_tree.heading("details", text="Chi tiết lỗi / Thông báo")
        self.health_tree.heading("suggestion", text="Gợi ý khắc phục")

        self.health_tree.column("provider", width=120, anchor=tk.W)
        self.health_tree.column("model", width=180, anchor=tk.W)
        self.health_tree.column("status", width=150, anchor=tk.CENTER)
        self.health_tree.column("latency", width=80, anchor=tk.CENTER)
        self.health_tree.column("details", width=250, anchor=tk.W)
        self.health_tree.column("suggestion", width=220, anchor=tk.W)

        self.health_tree.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)

        # Style health tree row categories
        self.health_tree.tag_configure("ok", foreground="#10B981")
        self.health_tree.tag_configure("warning", foreground="#D97706")
        self.health_tree.tag_configure("error", foreground="#DC2626")

        health_scroll = ttk.Scrollbar(frame_health_table, orient=tk.VERTICAL, command=self.health_tree.yview)
        self.health_tree.configure(yscrollcommand=health_scroll.set)
        health_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # Wire Combobox trace
        self.health_prov_var.trace_add("write", self._on_health_provider_changed)

        self.health_cancel_event = threading.Event()

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
            configured_summaries = []

            # Helper for displaying configured/not configured
            def get_status(p_name, display_name):
                p_cfg = pub_data.get(p_name, {})
                keys_count = len(p_cfg.get("api_keys", []))
                # For Gemini, also check legacy key just in case
                if p_name == "gemini" and not keys_count:
                    legacy_exists = bool(self.config_manager.api_key or self.config_manager.api_keys)
                    keys_count = len(self.config_manager.api_keys) or (1 if legacy_exists else 0)

                if keys_count > 0:
                    return f"{display_name} 🟢 ({keys_count} key)"
                return None

            ai_providers = [
                ("gemini", "Gemini"),
                ("groq", "Groq"),
                ("cerebras", "Cerebras"),
                ("openrouter", "OpenRouter"),
                ("mistral", "Mistral AI"),
                ("sambanova", "SambaNova"),
                ("cloudflare", "Cloudflare Workers AI"),
                ("huggingface", "HuggingFace"),
                ("github", "GitHub Models"),
                ("ai21", "AI21 Studio"),
                ("chatanywhere", "ChatAnyWhere"),
                ("deepseek", "DeepSeek"),
                ("nvidia_nim", "NVIDIA NIM"),
                ("openai_compatible", "OpenAI tùy chỉnh")
            ]

            for p_name, display in ai_providers:
                status = get_status(p_name, display)
                if status:
                    configured_summaries.append(status)

            if configured_summaries:
                self.lbl_quick_summary.configure(
                    text="  |  ".join(configured_summaries),
                    text_color=('#059669', '#34D399')
                )
            else:
                self.lbl_quick_summary.configure(
                    text="⚠️ Chưa có nguồn AI nào được cấu hình khóa API (Google Translate sẽ được sử dụng làm phương án dự phòng cuối cùng).",
                    text_color=('#DC2626', '#F87171')
                )
        except Exception as e:
            logger.error(f"Error updating quick summary: {e}")
            self.lbl_quick_summary.configure(text="Lỗi tải trạng thái")

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
                "groq": "Groq",
                "cerebras": "Cerebras",
                "openrouter": "OpenRouter",
                "mistral": "Mistral AI",
                "sambanova": "SambaNova",
                "cloudflare": "Cloudflare Workers AI",
                "huggingface": "HuggingFace",
                "github": "GitHub Models",
                "ai21": "AI21 Studio",
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
            self.chk_prov_enabled.configure(state=tk.DISABLED)
            self.entry_base_url.configure(state=tk.DISABLED)
            self.listbox_keys.configure(state=tk.DISABLED)
            self.entry_new_key.configure(state=tk.DISABLED)
            self.btn_add_key.configure(state=tk.DISABLED)
            self.btn_delete_key.configure(state=tk.DISABLED)
            self.listbox_models.configure(state=tk.DISABLED)
            self.entry_new_model.configure(state=tk.DISABLED)
            self.btn_add_model.configure(state=tk.DISABLED)
            self.btn_delete_model.configure(state=tk.DISABLED)
            self.btn_refresh_models.configure(state=tk.DISABLED)
            self.combo_model.configure(state="disabled")
            self.btn_save_prov.configure(state=tk.DISABLED)
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
        self.chk_prov_enabled.configure(state=tk.NORMAL)

        # Update base url
        self.prov_base_url_var.set(p_cfg.get("base_url", ""))
        self.entry_base_url.configure(state=tk.NORMAL if p_name != "google" else tk.DISABLED)

        # Update listbox keys (masked representation)
        self.listbox_keys.configure(state=tk.NORMAL)
        self.listbox_keys.delete(0, tk.END)

        keys_count = len(p_cfg.get("api_keys", []))
        if p_name == "gemini" and not keys_count:
            keys_count = len(self.config_manager.api_keys) or (1 if self.config_manager.api_key else 0)

        for i in range(keys_count):
            self.listbox_keys.insert(tk.END, f"Key {i+1}: đã cấu hình")

        self.prov_new_key_var.set("")
        self.entry_new_key.configure(state=tk.NORMAL if p_name != "google" else tk.DISABLED)
        self.btn_add_key.configure(state=tk.NORMAL if p_name != "google" else tk.DISABLED)
        self.btn_delete_key.configure(state=tk.NORMAL if p_name != "google" else tk.DISABLED)

        self._refresh_provider_model_controls(p_name, catalog_entry)

        self.btn_save_prov.configure(state=tk.NORMAL)

        if p_name == "google":
            self.lbl_google_tip.pack(anchor=tk.W, pady=5)
        else:
            self.lbl_google_tip.pack_forget()

        self.lbl_detail_title.configure(text=f"🛠️ Chi tiết nhà cung cấp được chọn: {p_name.upper()}")

    def _refresh_provider_model_controls(self, provider_name: str, catalog_entry: dict | None = None):
        catalog = self.config_manager.get_provider_model_catalog_public()
        entry = catalog_entry if isinstance(catalog_entry, dict) else catalog.get("providers", {}).get(provider_name, {})
        model_entries = entry.get("models", []) if isinstance(entry, dict) else []

        self.listbox_models.configure(state=tk.NORMAL)
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
        self.entry_new_model.configure(state=tk.NORMAL if not is_google else tk.DISABLED)
        self.btn_add_model.configure(state=tk.NORMAL if not is_google else tk.DISABLED)
        self.btn_delete_model.configure(state=tk.NORMAL if not is_google else tk.DISABLED)
        self.btn_refresh_models.configure(state=tk.NORMAL if entry.get("supports_refresh", False) else tk.DISABLED)

        default_model = str(entry.get("default_model", "")).strip()
        combo_values = list(enabled_models)
        if default_model and default_model not in combo_values:
            combo_values.insert(0, default_model)
        self.combo_model.configure(values=combo_values)
        self.prov_default_model_var.set(default_model or (combo_values[0] if combo_values else ""))
        self.combo_model.configure(state="readonly" if combo_values and not is_google else "disabled")

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
            self.btn_refresh_models.configure(state=tk.DISABLED, text="Đang quét model...")
            self.listbox_models.configure(state=tk.DISABLED)
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
        if getattr(self, '_is_destroyed', False) or not self.winfo_exists():
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

        if getattr(self, '_is_destroyed', False) or not self.winfo_exists():
            if callable(on_complete):
                on_complete()
            return

        # Restore button visuals if selected provider is this provider
        if self.selected_provider == provider_name:
            self.listbox_models.configure(state=tk.NORMAL)
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
        if getattr(self, '_is_destroyed', False) or not self.winfo_exists():
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
            if not getattr(self, '_is_destroyed', False) and self.winfo_exists():
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
        if getattr(self, '_is_destroyed', False) or not self.winfo_exists():
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
        if getattr(self, '_is_destroyed', False) or not hasattr(self, 'lbl_refresh_status'):
            return

        if not self.selected_provider:
            self.lbl_refresh_status.configure(text="")
            return

        p_name = self.selected_provider
        catalog = self.config_manager.get_provider_model_catalog_public()
        entry = catalog.get("providers", {}).get(p_name, {})
        supports_refresh = entry.get("supports_refresh", False)

        if not supports_refresh:
            self.lbl_refresh_status.configure(text="💡 Nhà cung cấp này không hỗ trợ tự động làm mới model.")
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

        self.lbl_refresh_status.configure(text=status_text)

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

    def _move_provider_to_top(self):
        """Move selected provider to the absolute top of the router priority list."""
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
            order.remove(p_name)
            order.insert(0, p_name)
            self.config_manager.provider_order = order
            self.config_manager.save_config()
            self._refresh_providers_tree()
            self.prov_tree.selection_set(p_name)
            self._refresh_quick_config_summary()

    def _move_provider_to_bottom(self):
        """Move selected provider to the absolute bottom of the router priority list."""
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
            order.remove(p_name)
            order.append(p_name)
            self.config_manager.provider_order = order
            self.config_manager.save_config()
            self._refresh_providers_tree()
            self.prov_tree.selection_set(p_name)
            self._refresh_quick_config_summary()

    def setup_file_tab(self):
        """Setup file translation tab using CustomTkinter with Card UI Layout"""
        scroll_frame = ctk.CTkScrollableFrame(self.tab_file, fg_color="transparent")
        scroll_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Header Title
        label_title = ctk.CTkLabel(
            scroll_frame, text="📁 Trình biên dịch tài liệu văn phòng (AI File Translator)",
            font=('Segoe UI', 15, 'bold'),
            text_color=('#1E3A5F', '#818CF8')
        )
        label_title.pack(pady=(15, 10))

        # CARD 1: CHỌN FILE & NGÔN NGỮ
        card_file_lang = create_styled_card(scroll_frame, title="📂 Chọn tài liệu & Ngôn ngữ", accent="cyan")
        card_file_lang.pack(fill=tk.X, padx=15, pady=6)

        # File selection row
        frame_file_entry = ctk.CTkFrame(card_file_lang, fg_color="transparent")
        frame_file_entry.pack(fill=tk.X, padx=15, pady=(5, 10))

        self.entry_file_path = ctk.CTkEntry(
            frame_file_entry, font=('Segoe UI', 10),
            placeholder_text="Chọn tài liệu cần dịch..."
        )
        self.entry_file_path.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))

        self.button_browse_file = create_styled_button(
            frame_file_entry, text="Duyệt File...", command=self.browse_file
        )
        self.button_browse_file.pack(side=tk.LEFT)

        # Languages Row
        frame_lang_row = ctk.CTkFrame(card_file_lang, fg_color="transparent")
        frame_lang_row.pack(fill=tk.X, padx=15, pady=(0, 15))

        # Source language
        frame_src_lang = ctk.CTkFrame(frame_lang_row, fg_color="transparent")
        frame_src_lang.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))

        ctk.CTkLabel(
            frame_src_lang, text="Ngôn ngữ nguồn:",
            font=('Segoe UI', 10, 'bold')
        ).pack(anchor=tk.W, pady=(0, 2))

        self.src_lang_file = tk.StringVar(value=config.default_src_lang)
        self.combobox_src_lang_file = create_language_combobox(
            frame_src_lang, self.src_lang_file,
            list(self.display_languages.keys())
        )
        self.combobox_src_lang_file.pack(fill=tk.X)

        # Destination language
        frame_dest_lang = ctk.CTkFrame(frame_lang_row, fg_color="transparent")
        frame_dest_lang.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(10, 0))

        ctk.CTkLabel(
            frame_dest_lang, text="Ngôn ngữ đích:",
            font=('Segoe UI', 10, 'bold')
        ).pack(anchor=tk.W, pady=(0, 2))

        self.dest_lang_file = tk.StringVar(value=config.default_dest_lang)
        self.combobox_dest_lang_file = create_language_combobox(
            frame_dest_lang, self.dest_lang_file,
            list(self.display_languages.keys())
        )
        self.combobox_dest_lang_file.pack(fill=tk.X)

        # CARD 2: CẤU HÌNH PDF & TRÍ TUỆ NHÂN TẠO
        card_ai_pdf = create_styled_card(scroll_frame, title="🤖 Tùy chọn dịch thuật thông minh (AI & PDF)", accent="indigo")
        card_ai_pdf.pack(fill=tk.X, padx=15, pady=6)

        frame_ai_option = ctk.CTkFrame(card_ai_pdf, fg_color="transparent")
        frame_ai_option.pack(fill=tk.X, padx=15, pady=10)

        self.use_ai_vision_for_pdf = tk.BooleanVar(value=False)
        checkbox_ai_vision = ctk.CTkCheckBox(
            frame_ai_option,
            text="🤖 Dùng AI Vision cho PDF (mạnh nhất cho PDF scan, tiếng Nhật/Trung)",
            variable=self.use_ai_vision_for_pdf,
            font=('Segoe UI', 10)
        )
        checkbox_ai_vision.pack(anchor=tk.W, pady=(0, 5))

        self.use_experimental_pdf_output = tk.BooleanVar(value=False)
        checkbox_pdf_experimental = ctk.CTkCheckBox(
            frame_ai_option,
            text="Xuất PDF thử nghiệm cho PDF text đơn giản",
            variable=self.use_experimental_pdf_output,
            font=('Segoe UI', 10)
        )
        checkbox_pdf_experimental.pack(anchor=tk.W, pady=(4, 0))

        ctk.CTkLabel(
            frame_ai_option,
            text="💡 Chế độ thử nghiệm: chỉ phù hợp PDF text đơn giản 1-2 trang. Bố cục có thể lệch. Với tài liệu quan trọng, hãy dùng chế độ DOCX ổn định.",
            font=('Segoe UI', 9, 'italic'),
            justify=tk.LEFT,
            text_color=self.colors['gray_medium']
        ).pack(anchor=tk.W, pady=(2, 10))

        # Pages per batch option
        frame_batch_option = ctk.CTkFrame(frame_ai_option, fg_color="transparent")
        frame_batch_option.pack(anchor=tk.W, pady=(4, 5))

        ctk.CTkLabel(
            frame_batch_option,
            text="⚡ Số trang/batch:",
            font=('Segoe UI', 9, 'bold')
        ).pack(side=tk.LEFT, padx=(0, 5))

        self.ai_vision_pages_per_batch = tk.StringVar(value="4")
        combo_batch = create_language_combobox(
            frame_batch_option,
            textvariable=self.ai_vision_pages_per_batch,
            values=["1", "2", "4", "6", "9"]
        )
        combo_batch.config(width=5)
        combo_batch.pack(side=tk.LEFT, padx=5)

        ctk.CTkLabel(
            frame_batch_option,
            text="(Ghép nhiều trang = tiết kiệm 75% requests AI)",
            font=('Segoe UI', 9, 'italic'),
            text_color=self.colors['gray_medium']
        ).pack(side=tk.LEFT, padx=5)

        # PDF QA Report frame
        frame_pdf_report = ctk.CTkFrame(card_ai_pdf, fg_color=('#F1F5F9', '#2E2E33'), corner_radius=8)
        frame_pdf_report.pack(fill=tk.X, padx=15, pady=(5, 15))

        ctk.CTkLabel(
            frame_pdf_report,
            text="📊 Báo cáo PDF thử nghiệm",
            font=('Segoe UI', 10, 'bold')
        ).pack(anchor=tk.W, padx=15, pady=(8, 2))

        self.label_pdf_report_hint = ctk.CTkLabel(
            frame_pdf_report,
            text=self._get_pdf_report_export_hint(),
            font=('Segoe UI', 9), justify=tk.LEFT, wraplength=760
        )
        self.label_pdf_report_hint.pack(anchor=tk.W, padx=15, pady=(2, 2))

        self.label_pdf_report_notice = ctk.CTkLabel(
            frame_pdf_report,
            text=self._get_pdf_report_export_notice(),
            font=('Segoe UI', 9, 'italic'), justify=tk.LEFT, wraplength=760,
            text_color=self.colors['gray_medium']
        )
        self.label_pdf_report_notice.pack(anchor=tk.W, pady=(2, 8), padx=15)

        frame_pdf_report_buttons = ctk.CTkFrame(frame_pdf_report, fg_color="transparent")
        frame_pdf_report_buttons.pack(fill=tk.X, padx=15, pady=(0, 10))

        self.btn_export_pdf_report_json = create_styled_button(
            frame_pdf_report_buttons,
            text="Xuất báo cáo JSON",
            command=self.export_pdf_report_json
        )
        self.btn_export_pdf_report_json.configure(state=tk.DISABLED)
        self.btn_export_pdf_report_json.pack(side=tk.LEFT, padx=(0, 8))

        self.btn_export_pdf_report_html = create_styled_button(
            frame_pdf_report_buttons,
            text="Xuất báo cáo HTML",
            command=self.export_pdf_report_html
        )
        self.btn_export_pdf_report_html.configure(state=tk.DISABLED)
        self.btn_export_pdf_report_html.pack(side=tk.LEFT)

        # CARD 3: TIẾN TRÌNH DỊCH THUẬT & HÀNH ĐỘNG
        card_actions = create_styled_card(scroll_frame, title="⚡ Tiến trình & Thao tác", accent="cyan")
        card_actions.pack(fill=tk.X, padx=15, pady=6)

        # Supported format info text
        label_info_file = ctk.CTkLabel(
            card_actions,
            text="💡 Hỗ trợ: Excel (.xlsx, .xls) | Word (.docx, .doc) | PowerPoint (.pptx, .ppt) | PDF (.pdf - Cần audit layout) | Text (.txt)",
            font=('Segoe UI', 9, 'bold'), justify=tk.LEFT,
            text_color=self.colors['gray_medium']
        )
        label_info_file.pack(padx=15, pady=(10, 5), anchor='w')

        # Buttons Row
        frame_buttons = ctk.CTkFrame(card_actions, fg_color="transparent")
        frame_buttons.pack(fill=tk.X, padx=15, pady=10)

        self.button_translate_file = create_styled_button(
            frame_buttons, text="⚡ Bắt đầu Dịch File",
            command=self.translate_file
        )
        self.button_translate_file.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))

        self.button_pause_file = create_styled_button(
            frame_buttons, text="⏸️ Tạm dừng",
            command=self._request_pause_file_translation
        )
        self.button_pause_file.configure(state=tk.DISABLED)
        self.button_pause_file.pack(side=tk.LEFT, padx=5)

        self.button_cancel_file = create_styled_button(
            frame_buttons, text="🛑 Hủy bỏ",
            command=self._request_cancel_file_translation
        )
        self.button_cancel_file.configure(state=tk.DISABLED)
        self.button_cancel_file.pack(side=tk.LEFT, padx=(5, 0))

        # Status & Progress indicators
        frame_status = ctk.CTkFrame(card_actions, fg_color="transparent")
        frame_status.pack(fill=tk.X, padx=15, pady=(5, 15))

        self.label_file_status = ctk.CTkLabel(
            frame_status,
            text="Trạng thái: Sẵn sàng biên dịch",
            font=('Segoe UI', 10), anchor=tk.W
        )
        self.label_file_status.pack(fill=tk.X, pady=(0, 5))

        self.progress_file = ctk.CTkProgressBar(
            frame_status,
            progress_color=('#4A90E2', '#6366F1'),
            fg_color=('#CBD5E1', '#3E3E44'),
            height=10
        )
        self.progress_file.pack(fill=tk.X, pady=5)
        self.progress_file.set(0)

    def setup_paragraph_tab(self):
        """Setup paragraph translation tab using CustomTkinter with Slate Card Layout"""
        scroll_frame = ctk.CTkScrollableFrame(self.tab_paragraph, fg_color="transparent")
        scroll_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Header Title
        label_title = ctk.CTkLabel(
            scroll_frame, text="📝 Biên dịch & Phân tích văn bản ngắn (AI Text Translator)",
            font=('Segoe UI', 15, 'bold'),
            text_color=('#1E3A5F', '#818CF8')
        )
        label_title.pack(pady=(15, 10))

        # CARD 1: NHẬP LIỆU & TÙY CHỌN DỊCH
        card_input = create_styled_card(scroll_frame, title="📝 Văn bản gốc & Cài đặt", accent="cyan")
        card_input.pack(fill=tk.X, padx=15, pady=6)

        # Languages Row
        frame_lang_row = ctk.CTkFrame(card_input, fg_color="transparent")
        frame_lang_row.pack(fill=tk.X, padx=15, pady=5)

        # Source language
        frame_src_lang = ctk.CTkFrame(frame_lang_row, fg_color="transparent")
        frame_src_lang.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        ctk.CTkLabel(
            frame_src_lang, text="Ngôn ngữ nguồn:",
            font=('Segoe UI', 10, 'bold')
        ).pack(anchor=tk.W, pady=(0, 2))

        self.src_lang_paragraph = tk.StringVar(value=config.default_src_lang)
        combobox_src_lang_paragraph = create_language_combobox(
            frame_src_lang, self.src_lang_paragraph,
            list(self.display_languages.keys())
        )
        combobox_src_lang_paragraph.pack(fill=tk.X)

        # Destination language
        frame_dest_lang = ctk.CTkFrame(frame_lang_row, fg_color="transparent")
        frame_dest_lang.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(10, 0))
        ctk.CTkLabel(
            frame_dest_lang, text="Ngôn ngữ đích:",
            font=('Segoe UI', 10, 'bold')
        ).pack(anchor=tk.W, pady=(0, 2))

        self.dest_lang_paragraph = tk.StringVar(value=config.default_dest_lang)
        combobox_dest_lang_paragraph = create_language_combobox(
            frame_dest_lang, self.dest_lang_paragraph,
            list(self.display_languages.keys())
        )
        combobox_dest_lang_paragraph.pack(fill=tk.X)

        # Context (Optional) Row
        frame_context = ctk.CTkFrame(card_input, fg_color="transparent")
        frame_context.pack(fill=tk.X, padx=15, pady=8)

        ctk.CTkLabel(
            frame_context, text="Bối cảnh / Ghi chú (AI gợi ý chính xác hơn):",
            font=('Segoe UI', 9, 'bold')
        ).pack(anchor=tk.W, pady=(0, 2))

        self.entry_paragraph_context = ctk.CTkEntry(
            frame_context, font=('Segoe UI', 10),
            placeholder_text="Ví dụ: tài liệu kỹ thuật, ngữ cảnh hội thoại trang trọng..."
        )
        self.entry_paragraph_context.pack(fill=tk.X)

        # Input text area
        frame_text_input = ctk.CTkFrame(card_input, fg_color="transparent")
        frame_text_input.pack(fill=tk.X, padx=15, pady=(5, 10))

        ctk.CTkLabel(
            frame_text_input, text="Nội dung cần dịch:",
            font=('Segoe UI', 10, 'bold')
        ).pack(anchor=tk.W, pady=(0, 2))

        self.entry_paragraph_input = ctk.CTkTextbox(
            frame_text_input, font=('Segoe UI', 10),
            height=110, corner_radius=8
        )
        self.entry_paragraph_input.pack(fill=tk.X)

        # Action buttons row
        frame_buttons_para = ctk.CTkFrame(card_input, fg_color="transparent")
        frame_buttons_para.pack(fill=tk.X, padx=15, pady=(0, 15))

        button_translate_paragraph = create_styled_button(
            frame_buttons_para, text="⚡ Dịch văn bản",
            command=self.translate_paragraph
        )
        button_translate_paragraph.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))

        button_clear_paragraph = create_styled_button(
            frame_buttons_para, text="🧹 Xóa nội dung",
            command=self.clear_input_paragraph
        )
        button_clear_paragraph.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 5))

        button_analyze_paragraph = create_styled_button(
            frame_buttons_para, text="🔍 Phân tích AI",
            command=self.analyze_paragraph
        )
        button_analyze_paragraph.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 0))

        # CARD 2: KẾT QUẢ DỊCH THUẬT & TELEMETRY
        card_output = create_styled_card(scroll_frame, title="🔮 Bản dịch & Phân tích chuyên sâu", accent="indigo")
        card_output.pack(fill=tk.X, padx=15, pady=6)

        # Output Header for provider details
        frame_output_header = ctk.CTkFrame(card_output, fg_color="transparent")
        frame_output_header.pack(fill=tk.X, padx=15, pady=(5, 2))

        self.lbl_last_translation_source = ctk.CTkLabel(
            frame_output_header, text="",
            font=('Segoe UI', 9, 'italic'), anchor=tk.W,
            text_color=self.colors['navy']
        )
        self.lbl_last_translation_source.pack(fill=tk.X)

        # Output text area
        frame_text_output = ctk.CTkFrame(card_output, fg_color="transparent")
        frame_text_output.pack(fill=tk.X, padx=15, pady=(0, 10))

        self.entry_paragraph_output = ctk.CTkTextbox(
            frame_text_output, font=('Segoe UI', 10),
            height=130, corner_radius=8
        )
        self.entry_paragraph_output.pack(fill=tk.X)

        # Actions
        frame_output_actions = ctk.CTkFrame(card_output, fg_color="transparent")
        frame_output_actions.pack(fill=tk.X, padx=15, pady=(0, 15))

        button_copy_paragraph = create_styled_button(
            frame_output_actions, text="📋 Sao chép bản dịch",
            command=self.copy_output_paragraph
        )
        button_copy_paragraph.pack(fill=tk.X)

    def setup_email_tab(self):
        """Setup email translation tab using CustomTkinter with Slate Card Layout"""
        scroll_frame = ctk.CTkScrollableFrame(self.tab_email, fg_color="transparent")
        scroll_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Header Title
        label_title = ctk.CTkLabel(
            scroll_frame, text="📧 Trình biên dịch hòm thư Outlook (AI Outlook Translator)",
            font=('Segoe UI', 15, 'bold'),
            text_color=('#1E3A5F', '#818CF8')
        )
        label_title.pack(pady=(15, 10))

        # CARD: CẤU HÌNH DỊCH EMAIL
        card_email = create_styled_card(scroll_frame, title="📧 Cài đặt dịch hòm thư Outlook", accent="cyan")
        card_email.pack(fill=tk.X, padx=15, pady=6)

        # Folder row
        frame_folder = ctk.CTkFrame(card_email, fg_color="transparent")
        frame_folder.pack(fill=tk.X, padx=15, pady=(5, 10))

        ctk.CTkLabel(
            frame_folder, text="Tên thư mục Outlook cần dịch:",
            font=('Segoe UI', 10, 'bold')
        ).pack(anchor=tk.W, pady=(0, 2))

        self.entry_folder_name = ctk.CTkEntry(
            frame_folder, font=('Segoe UI', 10),
            placeholder_text="Ví dụ: Inbox, Sent Items, hoặc tên thư mục riêng..."
        )
        self.entry_folder_name.pack(fill=tk.X)

        # Languages Row
        frame_lang_row = ctk.CTkFrame(card_email, fg_color="transparent")
        frame_lang_row.pack(fill=tk.X, padx=15, pady=(0, 10))

        # Source language
        frame_src_lang = ctk.CTkFrame(frame_lang_row, fg_color="transparent")
        frame_src_lang.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        ctk.CTkLabel(
            frame_src_lang, text="Ngôn ngữ nguồn:",
            font=('Segoe UI', 10, 'bold')
        ).pack(anchor=tk.W, pady=(0, 2))

        self.src_lang_email = tk.StringVar(value=config.default_src_lang)
        combobox_src_lang_email = create_language_combobox(
            frame_src_lang, self.src_lang_email,
            list(self.display_languages.keys())
        )
        combobox_src_lang_email.pack(fill=tk.X)

        # Destination language
        frame_dest_lang = ctk.CTkFrame(frame_lang_row, fg_color="transparent")
        frame_dest_lang.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(10, 0))
        ctk.CTkLabel(
            frame_dest_lang, text="Ngôn ngữ đích:",
            font=('Segoe UI', 10, 'bold')
        ).pack(anchor=tk.W, pady=(0, 2))

        self.dest_lang_email = tk.StringVar(value=config.default_dest_lang)
        combobox_dest_lang_email = create_language_combobox(
            frame_dest_lang, self.dest_lang_email,
            list(self.display_languages.keys())
        )
        combobox_dest_lang_email.pack(fill=tk.X)

        # Info & limits
        frame_info = ctk.CTkFrame(card_email, fg_color="transparent")
        frame_info.pack(fill=tk.X, padx=15, pady=5)

        label_info = ctk.CTkLabel(
            frame_info,
            text=f"💡 Lưu ý: Hệ thống dịch tự động {config.max_emails_to_translate} email mới nhất thỏa mãn điều kiện lọc trong thư mục được cấu hình.",
            text_color=self.colors.get('gray_medium', 'gray'),
            font=('Segoe UI', 9, 'italic'), justify=tk.LEFT, wraplength=580
        )
        label_info.pack(anchor=tk.W)

        # Translate button
        frame_button = ctk.CTkFrame(card_email, fg_color="transparent")
        frame_button.pack(fill=tk.X, padx=15, pady=(10, 15))

        button_translate_email = create_styled_button(
            frame_button, text="⚡ Bắt đầu Dịch hòm thư Outlook",
            command=self.translate_email
        )
        button_translate_email.pack(fill=tk.X)

    def setup_image_tab(self):
        """Setup image translation tab using CustomTkinter with Slate Card Layout"""
        scroll_frame = ctk.CTkScrollableFrame(self.tab_image, fg_color="transparent")
        scroll_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Header Title
        label_title = ctk.CTkLabel(
            scroll_frame, text="📸 Trình nhận diện & Biên dịch hình ảnh (AI Image OCR & Translator)",
            font=('Segoe UI', 15, 'bold'),
            text_color=('#1E3A5F', '#818CF8')
        )
        label_title.pack(pady=(15, 10))

        # CARD 1: TỆP NGUỒN & CẤU HÌNH NGÔN NGỮ
        card_config = create_styled_card(scroll_frame, title="📸 Tệp tin hình ảnh & Ngôn ngữ", accent="cyan")
        card_config.pack(fill=tk.X, padx=15, pady=6)

        # Browse Image Row
        frame_image_entry = ctk.CTkFrame(card_config, fg_color="transparent")
        frame_image_entry.pack(fill=tk.X, padx=15, pady=(5, 8))

        self.entry_image_path = ctk.CTkEntry(
            frame_image_entry, font=('Segoe UI', 10),
            placeholder_text="Chọn tệp ảnh từ máy tính hoặc dán từ clipboard..."
        )
        self.entry_image_path.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))

        button_browse_image = create_styled_button(
            frame_image_entry, text="Duyệt Ảnh...",
            command=self.browse_image
        )
        button_browse_image.pack(side=tk.LEFT)

        # Paste from Clipboard Row
        frame_paste_clipboard = ctk.CTkFrame(card_config, fg_color="transparent")
        frame_paste_clipboard.pack(fill=tk.X, padx=15, pady=5)

        button_paste_clipboard = create_styled_button(
            frame_paste_clipboard, text="📋 Dán ảnh từ Clipboard",
            command=self.paste_image_from_clipboard
        )
        button_paste_clipboard.pack(side=tk.LEFT, padx=(0, 15))

        self.label_clipboard_status = ctk.CTkLabel(
            frame_paste_clipboard,
            text="Chưa có ảnh từ clipboard (Nhấn Ctrl+V để dán trực tiếp)",
            font=('Segoe UI', 9, 'italic'),
            text_color=self.colors['gray_medium']
        )
        self.label_clipboard_status.pack(side=tk.LEFT, anchor=tk.W)

        # Languages Row
        frame_lang_row = ctk.CTkFrame(card_config, fg_color="transparent")
        frame_lang_row.pack(fill=tk.X, padx=15, pady=(5, 15))

        # Source language
        frame_src_lang = ctk.CTkFrame(frame_lang_row, fg_color="transparent")
        frame_src_lang.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        ctk.CTkLabel(
            frame_src_lang, text="Ngôn ngữ nguồn:",
            font=('Segoe UI', 10, 'bold')
        ).pack(anchor=tk.W, pady=(0, 2))

        self.src_lang_image = tk.StringVar(value=config.default_src_lang)
        combobox_src_lang_image = create_language_combobox(
            frame_src_lang, self.src_lang_image,
            list(self.display_languages.keys())
        )
        combobox_src_lang_image.pack(fill=tk.X)

        # Destination language
        frame_dest_lang = ctk.CTkFrame(frame_lang_row, fg_color="transparent")
        frame_dest_lang.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(10, 0))
        ctk.CTkLabel(
            frame_dest_lang, text="Ngôn ngữ đích:",
            font=('Segoe UI', 10, 'bold')
        ).pack(anchor=tk.W, pady=(0, 2))

        self.dest_lang_image = tk.StringVar(value=config.default_dest_lang)
        combobox_dest_lang_image = create_language_combobox(
            frame_dest_lang, self.dest_lang_image,
            list(self.display_languages.keys())
        )
        combobox_dest_lang_image.pack(fill=tk.X)

        # CARD 2: PREVIEW HÌNH ẢNH
        card_preview = create_styled_card(scroll_frame, title="👁️ Xem trước hình ảnh nguồn", accent="indigo")
        card_preview.pack(fill=tk.X, padx=15, pady=6)

        self.label_image_preview = ctk.CTkLabel(
            card_preview,
            text="Chưa tải hình ảnh nào lên để xem trước",
            font=('Segoe UI', 9, 'italic'),
            text_color=self.colors['gray_medium']
        )
        self.label_image_preview.pack(fill=tk.X, padx=15, pady=(5, 15))

        # CARD 3: KẾT QUẢ OCR & PHÂN TÍCH
        card_result = create_styled_card(scroll_frame, title="📊 Kết quả OCR & Biên dịch chuyên sâu", accent="cyan")
        card_result.pack(fill=tk.X, padx=15, pady=6)

        # Large action button OCR
        frame_primary_action = ctk.CTkFrame(card_result, fg_color="transparent")
        frame_primary_action.pack(fill=tk.X, padx=15, pady=(10, 5))

        button_translate_image = create_styled_button(
            frame_primary_action, text="⚡ Bắt đầu Trích xuất OCR & Dịch",
            command=self.translate_image
        )
        button_translate_image.pack(fill=tk.X)

        # Context AI Row
        frame_image_context = ctk.CTkFrame(card_result, fg_color="transparent")
        frame_image_context.pack(fill=tk.X, padx=15, pady=5)

        ctk.CTkLabel(
            frame_image_context, text="Bối cảnh AI (Tùy chọn):",
            font=('Segoe UI', 9, 'bold')
        ).pack(side=tk.LEFT)

        self.entry_image_context = ctk.CTkEntry(
            frame_image_context, font=('Segoe UI', 10),
            placeholder_text="Ghi chú bối cảnh hình ảnh..."
        )
        self.entry_image_context.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(10, 10))

        button_analyze_image = create_styled_button(
            frame_image_context, text="🔍 Phân tích AI",
            command=self.analyze_image_text
        )
        button_analyze_image.pack(side=tk.RIGHT)

        # Output Text Box area
        frame_text_output = ctk.CTkFrame(card_result, fg_color="transparent")
        frame_text_output.pack(fill=tk.X, padx=15, pady=5)

        self.text_output = ctk.CTkTextbox(
            frame_text_output, font=('Segoe UI', 10),
            height=130, corner_radius=8
        )
        self.text_output.pack(fill=tk.X)

        # Save Button
        frame_save = ctk.CTkFrame(card_result, fg_color="transparent")
        frame_save.pack(fill=tk.X, padx=15, pady=(10, 15))

        button_save_image_text = create_styled_button(
            frame_save, text="💾 Lưu kết quả dịch thuật",
            command=self.save_translated_image_text
        )
        button_save_image_text.pack(fill=tk.X)

        # Bind Ctrl+V for paste (bind to both tab and main window for better coverage)
        self.tab_image.bind('<Control-v>', lambda e: self.paste_image_from_clipboard())
        self.bind('<Control-v>', self._handle_ctrl_v_paste)

    # Event handlers
    def _handle_ctrl_v_paste(self, event):
        """Handle Ctrl+V paste - only if on image tab"""
        try:
            current_tab = self.tabview.get()
            if current_tab == "Dịch ảnh":
                self.paste_image_from_clipboard()
        except Exception:
            pass

    def browse_file(self):
        """Browse for file"""
        file_paths = list(filedialog.askopenfilenames(filetypes=[("All Files", "*.*")]))
        if file_paths:
            self._set_selected_file_paths(file_paths)

    def _build_file_selection_display(self, file_paths: list[str]) -> str:
        if not file_paths:
            return ""
        if len(file_paths) == 1:
            return file_paths[0]
        if len(file_paths) == 2:
            return " | ".join(file_paths)
        return f"{len(file_paths)} files selected | {file_paths[0]}"

    def _set_selected_file_paths(self, file_paths: list[str]) -> None:
        normalized_paths = [str(path).strip() for path in file_paths if str(path).strip()]
        self._selected_file_paths = normalized_paths
        self._selected_file_display_value = self._build_file_selection_display(normalized_paths)
        if hasattr(self, "entry_file_path"):
            self.entry_file_path.configure(state=tk.NORMAL)
            self.entry_file_path.delete(0, tk.END)
            self.entry_file_path.insert(0, self._selected_file_display_value)
            if self._file_translation_in_progress:
                self.entry_file_path.configure(state=tk.DISABLED)

    def _get_selected_file_paths(self) -> list[str]:
        current_value = self.entry_file_path.get().strip() if hasattr(self, "entry_file_path") else ""
        if self._selected_file_paths and current_value == self._selected_file_display_value:
            return list(self._selected_file_paths)
        if not current_value:
            return []
        return [current_value]

    def _set_file_translation_busy(self, is_busy: bool, status_text: str = "") -> None:
        self._file_translation_in_progress = bool(is_busy)
        if hasattr(self, "button_translate_file"):
            self.button_translate_file.configure(
                state=tk.DISABLED if is_busy else tk.NORMAL,
                text="Dang dich file..." if is_busy else "Dich File",
            )
        if hasattr(self, "button_pause_file"):
            self.button_pause_file.configure(state=tk.NORMAL if is_busy else tk.DISABLED)
        if hasattr(self, "button_cancel_file"):
            self.button_cancel_file.configure(state=tk.NORMAL if is_busy else tk.DISABLED)
        if hasattr(self, "button_browse_file"):
            self.button_browse_file.configure(state=tk.DISABLED if is_busy else tk.NORMAL)
        if hasattr(self, "entry_file_path"):
            self.entry_file_path.configure(state=tk.DISABLED if is_busy else tk.NORMAL)
        for widget_name in ("combobox_src_lang_file", "combobox_dest_lang_file"):
            widget = getattr(self, widget_name, None)
            if widget is not None:
                widget.configure(state=tk.DISABLED if is_busy else "readonly")
        if status_text:
            self.label_file_status.configure(text=status_text)

    def _request_pause_file_translation(self) -> None:
        if self._file_translation_control is None:
            return
        self._file_translation_control.request_pause()
        if hasattr(self, "button_pause_file"):
            self.button_pause_file.configure(state=tk.DISABLED)
        self.label_file_status.configure(text="Dang tam dung va se luu ban dang co o diem an toan tiep theo...")

    def _request_cancel_file_translation(self) -> None:
        if self._file_translation_control is None:
            return
        self._file_translation_control.request_cancel()
        if hasattr(self, "button_pause_file"):
            self.button_pause_file.configure(state=tk.DISABLED)
        if hasattr(self, "button_cancel_file"):
            self.button_cancel_file.configure(state=tk.DISABLED)
        self.label_file_status.configure(text="Dang huy va se luu ban dang co o diem an toan tiep theo...")

    def _prepare_file_translation_tasks(self, file_paths: list[str]) -> list[dict]:
        handlers_map = {
            '.xlsx': (self.excel_handler, '.xlsx'),
            '.xls': (self.excel_handler, '.xlsx'),
            '.docx': (self.word_handler, '.docx'),
            '.doc': (self.word_handler, '.docx'),
            '.pptx': (self.powerpoint_handler, '.pptx'),
            '.ppt': (self.powerpoint_handler, '.pptx'),
            '.txt': (self.text_handler, '.txt'),
            '.pdf': (self.pdf_handler, '.docx'),
        }

        tasks = []
        today_str = datetime.now().strftime("%Y%m%d")
        for file_path in file_paths:
            base, ext = os.path.splitext(file_path)
            ext_lower = ext.lower()
            if ext_lower not in handlers_map:
                raise ValueError(
                    f"Loai file '{ext}' khong duoc ho tro.\n\n"
                    "Cac dinh dang duoc ho tro:\n"
                    "- Excel: .xlsx, .xls\n"
                    "- Word: .docx, .doc\n"
                    "- PowerPoint: .pptx, .ppt\n"
                    "- Text: .txt\n"
                    "- PDF: .pdf"
                )

            handler, output_ext = handlers_map[ext_lower]
            use_ai_vision = ext_lower == '.pdf' and self.use_ai_vision_for_pdf.get()
            use_pdf_experimental = ext_lower == '.pdf' and self.use_experimental_pdf_output.get()
            if use_pdf_experimental:
                output_ext = '.pdf'

            tasks.append(
                {
                    "input_file": file_path,
                    "output_file": f"{base}_translated_{today_str}{output_ext}",
                    "handler": handler,
                    "ext_lower": ext_lower,
                    "use_ai_vision": use_ai_vision,
                    "use_pdf_experimental": use_pdf_experimental,
                    "pages_per_batch": int(self.ai_vision_pages_per_batch.get()) if use_ai_vision else 4,
                }
            )
        return tasks

    def _format_file_translation_error(self, task: dict, exc: Exception) -> str:
        if task.get("use_pdf_experimental") and isinstance(exc, FileProcessingError):
            return "PDF này không phù hợp với chế độ thử nghiệm. Vui lòng dùng chế độ DOCX ổn định."
        return handle_translation_error(exc, f"Dịch file '{os.path.basename(task['input_file'])}'")

    def translate_file(self):
        """Translate one or more selected files."""
        if self._file_translation_in_progress:
            self.label_file_status.configure(text="Đang dịch file. Vui lòng chờ tác vụ hiện tại hoàn tất.")
            return

        file_paths = self._get_selected_file_paths()
        src_lang = self.src_lang_file.get()
        dest_lang = self.dest_lang_file.get()

        try:
            if not file_paths:
                raise ValueError("Vui long chon it nhat mot file.")
            LanguageValidator.validate_language_pair(src_lang, dest_lang)
            for file_path in file_paths:
                FileValidator.validate_file(file_path)
        except Exception as exc:
            messagebox.showerror("Loi", str(exc))
            return

        if any(str(path).lower().endswith(".pdf") for path in file_paths):
            use_ai_vision = self.use_ai_vision_for_pdf.get()
            use_pdf_experimental = self.use_experimental_pdf_output.get()
            if not use_ai_vision and not use_pdf_experimental:
                user_choice = self._show_pdf_ai_guide_and_wait()
                if user_choice is None:
                    logger.info("User cancelled PDF translation dialog")
                    return

        try:
            tasks = self._prepare_file_translation_tasks(file_paths)
        except Exception as exc:
            messagebox.showerror("Loi", str(exc))
            return

        def make_progress_callback(file_index: int, total_files: int):
            prefix = f"[{file_index}/{total_files}] " if total_files > 1 else ""

            def update_progress(text, value=None):
                def _update():
                    self.label_file_status.configure(text=f"{prefix}{text}")
                    if value is not None:
                        self.progress_file.set(value / 100.0)
                    self.update_idletasks()
                self.after(0, _update)

            return update_progress

        self._file_translation_control = FileTranslationControl()
        self.translation_service.set_file_translation_control(self._file_translation_control)
        self._set_file_translation_busy(True)
        self.progress_file.set(0)
        self.label_file_status.configure(
            text=f"Đang chuẩn bị dịch {len(tasks)} file..." if len(tasks) > 1 else "Đang chuẩn bị dịch file..."
        )

        def translate_thread():
            successes = []
            failures = []
            interruption = None

            try:
                total_files = len(tasks)
                for file_index, task in enumerate(tasks, start=1):
                    self.translation_service.raise_if_file_translation_stopped()
                    file_path = task["input_file"]
                    output_file = task["output_file"]
                    handler = task["handler"]
                    update_progress = make_progress_callback(file_index, total_files)

                    if hasattr(handler, 'progress_callback'):
                        handler.progress_callback = update_progress

                    if task["use_ai_vision"]:
                        update_progress(
                            f"Đang chuẩn bị dịch AI Vision '{os.path.basename(file_path)}' ({task['pages_per_batch']} trang/batch)...",
                            2,
                        )
                    elif task["use_pdf_experimental"]:
                        update_progress(
                            f"Đang chuẩn bị xuất PDF thử nghiệm '{os.path.basename(file_path)}'...",
                            2,
                        )
                    else:
                        update_progress(f"Đang chuẩn bị dịch '{os.path.basename(file_path)}'...", 2)

                    try:
                        if task["use_ai_vision"]:
                            self.pdf_handler.progress_callback = update_progress
                            self.pdf_handler.translate_with_ai_vision(
                                file_path,
                                output_file,
                                src_lang,
                                dest_lang,
                                pages_per_batch=task["pages_per_batch"],
                            )
                        elif task["use_pdf_experimental"]:
                            self.pdf_handler.progress_callback = update_progress
                            self.pdf_handler.translate_to_pdf_experimental(
                                file_path,
                                output_file,
                                src_lang,
                                dest_lang,
                            )
                            self._remember_pdf_report_context(file_path, output_file)
                        else:
                            handler.translate(file_path, output_file, src_lang, dest_lang)

                        successes.append(task)
                    except FileTranslationInterrupted as exc:
                        if task["use_pdf_experimental"] and self.pdf_handler.last_pdf_qa_report:
                            self._remember_pdf_report_context(file_path, output_file)
                        interruption = (exc, len(successes))
                        break
                    except Exception as exc:
                        if task["use_pdf_experimental"] and self.pdf_handler.last_pdf_qa_report:
                            self._remember_pdf_report_context(file_path, output_file)
                        failures.append((task, self._format_file_translation_error(task, exc)))
                        logger.error(f"File translation failed for '{file_path}': {exc}")

                def _on_complete():
                    self.translation_service.clear_file_translation_control()
                    self._file_translation_control = None
                    self.progress_file.set(0)
                    self._set_file_translation_busy(False)
                    if any(task.get("use_pdf_experimental") for task in successes):
                        self._update_pdf_report_export_state()
                    if hasattr(self, "_refresh_jobs_list"):
                        self._refresh_jobs_list()

                    if interruption is not None:
                        exc, completed_count = interruption
                        title = "Tạm dừng" if exc.status == "paused" else "Đã hủy"
                        message = f"Đã dừng dịch sau khi hoàn tất {completed_count}/{len(tasks)} file."
                        if exc.partial_saved and exc.output_file:
                            message += f"\n\nĐã lưu bản đang dịch dở tại:\n{exc.output_file}"
                        elif exc.output_file:
                            message += f"\n\nKhông thể lưu bản đang dịch dở tại:\n{exc.output_file}"
                        if failures:
                            message += f"\n\nĐã có {len(failures)} file lỗi trước khi dừng."
                        messagebox.showwarning(title, message)
                        self.label_file_status.configure(text="")
                        return

                    if failures and successes:
                        failed_preview = "\n".join(
                            f"- {os.path.basename(item['input_file'])}: {error}"
                            for item, error in failures[:3]
                        )
                        messagebox.showwarning(
                            "Hoàn tất có cảnh báo",
                            (
                                f"Đã dịch xong {len(successes)}/{len(tasks)} file.\n"
                                f"{len(failures)} file lỗi.\n\n{failed_preview}"
                            ),
                        )
                    elif failures:
                        failed_preview = "\n".join(
                            f"- {os.path.basename(item['input_file'])}: {error}"
                            for item, error in failures[:3]
                        )
                        messagebox.showerror(
                            "Lỗi",
                            f"Không dịch được file nào.\n\n{failed_preview}",
                        )
                    else:
                        if len(successes) == 1:
                            output_file = successes[0]["output_file"]
                            messagebox.showinfo(
                                "Thành công",
                                (
                                    f"File '{os.path.basename(successes[0]['input_file'])}' đã được dịch.\n\n"
                                    f"Đã lưu kết quả tại:\n{output_file}"
                                ),
                            )
                        else:
                            output_preview = "\n".join(
                                f"- {os.path.basename(task['output_file'])}"
                                for task in successes[:5]
                            )
                            messagebox.showinfo(
                                "Thành công",
                                (
                                    f"Đã dịch xong {len(successes)} file.\n\n"
                                    f"Kết quả đầu ra:\n{output_preview}"
                                ),
                            )

                    self.label_file_status.configure(text="")

                self.after(0, _on_complete)
            except Exception as exc:
                caught_error = exc

                def _on_error():
                    self.translation_service.clear_file_translation_control()
                    self._file_translation_control = None
                    self.progress_file.set(0)
                    self._set_file_translation_busy(False)
                    self.label_file_status.configure(text="Dịch file thất bại.")
                    messagebox.showerror("Lỗi", handle_translation_error(caught_error, "Dịch file"))

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
        self.btn_export_pdf_report_json.configure(state=button_state)
        self.btn_export_pdf_report_html.configure(state=button_state)
        hint_text = (
            "Đã có báo cáo PDF thử nghiệm công khai an toàn. Bạn có thể xuất JSON hoặc HTML."
            if has_report
            else self._get_pdf_report_export_hint()
        )
        self.label_pdf_report_hint.configure(text=hint_text)

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
                    "groq": "Groq",
                    "cerebras": "Cerebras",
                    "openrouter": "OpenRouter",
                    "mistral": "Mistral AI",
                    "sambanova": "SambaNova",
                    "cloudflare": "Cloudflare Workers AI",
                    "huggingface": "HuggingFace",
                    "github": "GitHub Models",
                    "ai21": "AI21 Studio",
                    "google": "Google Translate",
                    "translation_memory": "Bộ nhớ dịch (TM Cache)"
                }.get(provider, provider)

                text_info = f"Được dịch bởi: {display_provider}"
                if model and model != "none":
                    text_info += f" / {model}"
                if fallbacks > 0:
                    text_info += f" (Fallback: {fallbacks} lần)"
                self.lbl_last_translation_source.configure(text=text_info)
            else:
                self.lbl_last_translation_source.configure(text="")
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
            self.label_image_preview.configure(image='', text="Chua co anh de hien thi")
            self.label_clipboard_status.configure(text="Chưa có ảnh từ clipboard")

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
            self.label_clipboard_status.configure(
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
            self.label_image_preview.configure(
                image=self.preview_photo,
                text=''
            )

        except Exception as e:
            logger.error(f"Error updating image preview: {e}", exc_info=True)
            self.label_image_preview.configure(
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

            display_policy = self.tm_policy_var.get()
            policy_val = self.TM_POLICY_VALUE_MAP.get(display_policy, "tm_prefer_cache")
            self.config_manager.translation_memory_policy = policy_val

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
        """Setup the Jobs tracking tab using CustomTkinter with Slate Card Layout."""
        scroll_frame = ctk.CTkScrollableFrame(self.tab_jobs, fg_color="transparent")
        scroll_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Header Title
        label_title = ctk.CTkLabel(
            scroll_frame, text="📋 Tiến độ & Lịch sử dịch thuật (AI Translation Jobs)",
            font=('Segoe UI', 15, 'bold'),
            text_color=('#1E3A5F', '#818CF8')
        )
        label_title.pack(pady=(15, 10))

        # CARD 1: LỊCH SỬ CÔNG VIỆC
        card_list = create_styled_card(scroll_frame, title="📋 Lịch sử công việc hiện tại")
        card_list.pack(fill=tk.X, padx=15, pady=6)

        # Top row inside card for actions
        frame_action_top = ctk.CTkFrame(card_list, fg_color="transparent")
        frame_action_top.pack(fill=tk.X, padx=15, pady=(5, 10))

        ctk.CTkLabel(
            frame_action_top, text="Nhấn 'Làm mới' để đồng bộ tiến độ các tác vụ nền:",
            font=('Segoe UI', 9, 'italic'),
            text_color=self.colors['gray_medium']
        ).pack(side=tk.LEFT)

        create_styled_button(
            frame_action_top, text="🔄 Làm mới danh sách", command=self._refresh_jobs_list,
            width=140
        ).pack(side=tk.RIGHT)

        # Styled Ttk Treeview
        frame_tree = ctk.CTkFrame(card_list, fg_color="transparent")
        frame_tree.pack(fill=tk.X, padx=15, pady=(0, 15))

        columns = ("job_id", "job_type", "status", "progress", "created_at")
        self.jobs_tree = ttk.Treeview(frame_tree, columns=columns, show="headings", height=6)
        self.jobs_tree.heading("job_id", text="Mã công việc (Job ID)")
        self.jobs_tree.heading("job_type", text="Loại")
        self.jobs_tree.heading("status", text="Trạng thái")
        self.jobs_tree.heading("progress", text="Tiến độ")
        self.jobs_tree.heading("created_at", text="Ngày tạo")

        self.jobs_tree.column("job_id", width=180)
        self.jobs_tree.column("job_type", width=90, anchor=tk.CENTER)
        self.jobs_tree.column("status", width=90, anchor=tk.CENTER)
        self.jobs_tree.column("progress", width=80, anchor=tk.CENTER)
        self.jobs_tree.column("created_at", width=150)
        self.jobs_tree.pack(fill=tk.BOTH, expand=True)

        # CARD 2: CHI TIẾT & HÀNH ĐỘNG
        card_detail = create_styled_card(scroll_frame, title="🔍 Chi tiết & Thao tác công việc")
        card_detail.pack(fill=tk.X, padx=15, pady=6)

        # Telemetry detail box
        frame_detail_box = ctk.CTkFrame(card_detail, fg_color="transparent")
        frame_detail_box.pack(fill=tk.X, padx=15, pady=5)

        self.job_detail_text = ctk.CTkTextbox(
            frame_detail_box, font=('Segoe UI', 9),
            height=100, corner_radius=8
        )
        self.job_detail_text.pack(fill=tk.X)
        self.job_detail_text.configure(state="disabled")

        # Action Buttons row
        frame_buttons = ctk.CTkFrame(card_detail, fg_color="transparent")
        frame_buttons.pack(fill=tk.X, padx=15, pady=(10, 15))

        create_styled_button(
            frame_buttons, text="📁 Mở thư mục", command=self._open_selected_job_folder,
            width=130
        ).pack(side=tk.LEFT, padx=(0, 10))

        create_styled_button(
            frame_buttons, text="⚠️ Xem lỗi phân đoạn", command=self._view_selected_job_errors,
            width=150
        ).pack(side=tk.LEFT, padx=(0, 10))

        resume_btn = create_styled_button(
            frame_buttons, text="⏯️ Tiếp tục", command=self._resume_selected_job,
            width=100
        )
        resume_btn.configure(state="disabled")
        resume_btn.pack(side=tk.LEFT)

        ctk.CTkLabel(
            frame_buttons, text="* Tiếp tục (Resume) là tính năng nâng cao cho các bản cập nhật kế tiếp.",
            font=('Segoe UI', 8, 'italic'), text_color=self.colors['gray_medium']
        ).pack(side=tk.LEFT, padx=15)

        # Bind select event
        self.jobs_tree.bind("<<TreeviewSelect>>", self._on_job_selected)
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

            self.job_detail_text.configure(state="normal")
            self.job_detail_text.delete("1.0", tk.END)
            self.job_detail_text.insert(tk.END, detail_info)
            self.job_detail_text.configure(state="disabled")
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

            # Create sub window using CustomTkinter
            err_win = ctk.CTkToplevel(self)
            err_win.title(f"⚠️ Danh sách phân đoạn bị lỗi - Job: {job_id}")
            err_win.geometry("750x450")
            err_win.transient(self)
            err_win.after(10, lambda: err_win.grab_set())

            frame = ctk.CTkFrame(err_win, fg_color="transparent")
            frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

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
        """Setup the Glossary tab using CustomTkinter with Slate Card Layout."""
        scroll_frame = ctk.CTkScrollableFrame(self.tab_glossary, fg_color="transparent")
        scroll_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Header Title
        label_title = ctk.CTkLabel(
            scroll_frame, text="📖 Quản lý Từ điển Thuật ngữ (Glossary Dictionary)",
            font=('Segoe UI', 15, 'bold'),
            text_color=('#1E3A5F', '#818CF8')
        )
        label_title.pack(pady=(15, 10))

        # CARD 1: BỘ LỌC & THAO TÁC CSV
        card_filter = create_styled_card(scroll_frame, title="🔍 Lọc thuật ngữ & Tác vụ dữ liệu")
        card_filter.pack(fill=tk.X, padx=15, pady=6)

        frame_filter_row = ctk.CTkFrame(card_filter, fg_color="transparent")
        frame_filter_row.pack(fill=tk.X, padx=15, pady=(5, 15))

        # Left filter items
        frame_filters = ctk.CTkFrame(frame_filter_row, fg_color="transparent")
        frame_filters.pack(side=tk.LEFT)

        ctk.CTkLabel(frame_filters, text="Nguồn:", font=('Segoe UI', 10, 'bold')).pack(side=tk.LEFT)
        self.glossary_filter_src = tk.StringVar(value="auto")
        glossary_filter_src_combo = create_language_combobox(
            frame_filters, textvariable=self.glossary_filter_src,
            values=["auto"] + list(self.display_languages.keys())
        )
        glossary_filter_src_combo.config(width=10)
        glossary_filter_src_combo.pack(side=tk.LEFT, padx=5)

        ctk.CTkLabel(frame_filters, text="Đích:", font=('Segoe UI', 10, 'bold')).pack(side=tk.LEFT, padx=(10, 0))
        self.glossary_filter_tgt = tk.StringVar(value="vi")
        glossary_filter_tgt_combo = create_language_combobox(
            frame_filters, textvariable=self.glossary_filter_tgt,
            values=list(self.display_languages.keys())
        )
        glossary_filter_tgt_combo.config(width=10)
        glossary_filter_tgt_combo.pack(side=tk.LEFT, padx=5)

        create_styled_button(
            frame_filters, text="🔍 Lọc", command=self._refresh_glossary_list,
            width=80
        ).pack(side=tk.LEFT, padx=10)

        # Right import/export CSV buttons
        frame_csv = ctk.CTkFrame(frame_filter_row, fg_color="transparent")
        frame_csv.pack(side=tk.RIGHT)

        create_styled_button(
            frame_csv, text="📥 Nhập CSV", command=self._import_glossary_csv,
            width=110
        ).pack(side=tk.LEFT, padx=5)

        create_styled_button(
            frame_csv, text="📤 Xuất CSV", command=self._export_glossary_csv,
            width=110
        ).pack(side=tk.LEFT, padx=5)

        # CARD 2: TỪ ĐIỂN THUẬT NGỮ HIỆN TẠI
        card_list = create_styled_card(scroll_frame, title="📖 Danh sách thuật ngữ trong hệ thống")
        card_list.pack(fill=tk.X, padx=15, pady=6)

        frame_tree = ctk.CTkFrame(card_list, fg_color="transparent")
        frame_tree.pack(fill=tk.X, padx=15, pady=(0, 15))

        columns = ("id", "source_term", "target_term", "source_lang", "target_lang", "domain", "note")
        self.glossary_tree = ttk.Treeview(frame_tree, columns=columns, show="headings", height=6)
        self.glossary_tree.heading("id", text="ID")
        self.glossary_tree.heading("source_term", text="Thuật ngữ gốc")
        self.glossary_tree.heading("target_term", text="Thuật ngữ dịch")
        self.glossary_tree.heading("source_lang", text="Mã nguồn")
        self.glossary_tree.heading("target_lang", text="Mã đích")
        self.glossary_tree.heading("domain", text="Chuyên ngành")
        self.glossary_tree.heading("note", text="Ghi chú")

        self.glossary_tree.column("id", width=40, anchor=tk.CENTER)
        self.glossary_tree.column("source_term", width=140)
        self.glossary_tree.column("target_term", width=140)
        self.glossary_tree.column("source_lang", width=70, anchor=tk.CENTER)
        self.glossary_tree.column("target_lang", width=70, anchor=tk.CENTER)
        self.glossary_tree.column("domain", width=100)
        self.glossary_tree.column("note", width=130)
        self.glossary_tree.pack(fill=tk.BOTH, expand=True)

        # CARD 3: THÊM THUẬT NGỮ MỚI
        card_add = create_styled_card(scroll_frame, title="➕ Thêm thuật ngữ mới vào từ điển")
        card_add.pack(fill=tk.X, padx=15, pady=6)

        # Form grid layout
        f_row1 = ctk.CTkFrame(card_add, fg_color="transparent")
        f_row1.pack(fill=tk.X, pady=4, padx=15)

        ctk.CTkLabel(f_row1, text="Thuật ngữ gốc *:", width=110, anchor=tk.W, font=('Segoe UI', 10, 'bold')).pack(side=tk.LEFT)
        self.glossary_add_src_term = tk.StringVar()
        ctk.CTkEntry(f_row1, textvariable=self.glossary_add_src_term, width=200, corner_radius=8).pack(side=tk.LEFT, padx=5)

        ctk.CTkLabel(f_row1, text="Thuật ngữ dịch *:", width=110, anchor=tk.W, font=('Segoe UI', 10, 'bold')).pack(side=tk.LEFT, padx=(25, 0))
        self.glossary_add_tgt_term = tk.StringVar()
        ctk.CTkEntry(f_row1, textvariable=self.glossary_add_tgt_term, width=200, corner_radius=8).pack(side=tk.LEFT, padx=5)

        f_row2 = ctk.CTkFrame(card_add, fg_color="transparent")
        f_row2.pack(fill=tk.X, pady=4, padx=15)

        ctk.CTkLabel(f_row2, text="Ngôn ngữ nguồn *:", width=110, anchor=tk.W, font=('Segoe UI', 10, 'bold')).pack(side=tk.LEFT)
        self.glossary_add_src_lang = tk.StringVar(value="en")
        glossary_add_src_combo = create_language_combobox(
            f_row2, textvariable=self.glossary_add_src_lang,
            values=list(self.display_languages.keys())
        )
        glossary_add_src_combo.config(width=10)
        glossary_add_src_combo.pack(side=tk.LEFT, padx=5)

        ctk.CTkLabel(f_row2, text="Ngôn ngữ đích *:", width=110, anchor=tk.W, font=('Segoe UI', 10, 'bold')).pack(side=tk.LEFT, padx=(25, 0))
        self.glossary_add_tgt_lang = tk.StringVar(value="vi")
        glossary_add_tgt_combo = create_language_combobox(
            f_row2, textvariable=self.glossary_add_tgt_lang,
            values=list(self.display_languages.keys())
        )
        glossary_add_tgt_combo.config(width=10)
        glossary_add_tgt_combo.pack(side=tk.LEFT, padx=5)

        f_row3 = ctk.CTkFrame(card_add, fg_color="transparent")
        f_row3.pack(fill=tk.X, pady=4, padx=15)

        ctk.CTkLabel(f_row3, text="Chuyên ngành:", width=110, anchor=tk.W).pack(side=tk.LEFT)
        self.glossary_add_domain = tk.StringVar()
        ctk.CTkEntry(f_row3, textvariable=self.glossary_add_domain, width=200, corner_radius=8).pack(side=tk.LEFT, padx=5)

        ctk.CTkLabel(f_row3, text="Ghi chú:", width=110, anchor=tk.W).pack(side=tk.LEFT, padx=(25, 0))
        self.glossary_add_note = tk.StringVar()
        ctk.CTkEntry(f_row3, textvariable=self.glossary_add_note, width=200, corner_radius=8).pack(side=tk.LEFT, padx=5)

        # Form actions buttons
        btn_form_row = ctk.CTkFrame(card_add, fg_color="transparent")
        btn_form_row.pack(fill=tk.X, padx=15, pady=(10, 15))

        create_styled_button(
            btn_form_row, text="➕ Thêm vào từ điển", command=self._add_glossary_term,
            width=160
        ).pack(side=tk.LEFT, padx=(0, 10))

        create_styled_button(
            btn_form_row, text="🗑️ Xóa thuật ngữ đã chọn", command=self._delete_glossary_term,
            width=180
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
        """Setup the Translation Memory (TM) tab using CustomTkinter with Slate Card Layout."""
        scroll_frame = ctk.CTkScrollableFrame(self.tab_tm, fg_color="transparent")
        scroll_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Header Title
        label_title = ctk.CTkLabel(
            scroll_frame, text="🧠 Bộ nhớ dịch thuật (Translation Memory Cache)",
            font=('Segoe UI', 15, 'bold'),
            text_color=('#1E3A5F', '#818CF8')
        )
        label_title.pack(pady=(15, 10))

        # CARD 1: TÌM KIẾM
        card_search = create_styled_card(scroll_frame, title="🔍 Tra cứu & Lọc bộ nhớ")
        card_search.pack(fill=tk.X, padx=15, pady=6)

        frame_filter = ctk.CTkFrame(card_search, fg_color="transparent")
        frame_filter.pack(fill=tk.X, padx=15, pady=(5, 15))

        ctk.CTkLabel(frame_filter, text="Từ khóa:", font=('Segoe UI', 10, 'bold')).pack(side=tk.LEFT)
        self.tm_search_query = tk.StringVar()
        ctk.CTkEntry(frame_filter, textvariable=self.tm_search_query, width=150, corner_radius=8).pack(side=tk.LEFT, padx=5)

        ctk.CTkLabel(frame_filter, text="Nguồn:", font=('Segoe UI', 10, 'bold')).pack(side=tk.LEFT, padx=(10, 0))
        self.tm_filter_src = tk.StringVar(value="auto")
        tm_filter_src_combo = create_language_combobox(
            frame_filter, textvariable=self.tm_filter_src,
            values=["auto"] + list(self.display_languages.keys())
        )
        tm_filter_src_combo.configure(width=10)
        tm_filter_src_combo.pack(side=tk.LEFT, padx=5)

        ctk.CTkLabel(frame_filter, text="Đích:", font=('Segoe UI', 10, 'bold')).pack(side=tk.LEFT, padx=(10, 0))
        self.tm_filter_tgt = tk.StringVar(value="vi")
        tm_filter_tgt_combo = create_language_combobox(
            frame_filter, textvariable=self.tm_filter_tgt,
            values=list(self.display_languages.keys())
        )
        tm_filter_tgt_combo.configure(width=10)
        tm_filter_tgt_combo.pack(side=tk.LEFT, padx=5)

        create_styled_button(
            frame_filter, text="🔍 Tìm kiếm", command=self._refresh_tm_list,
            width=100
        ).pack(side=tk.LEFT, padx=10)

        # CARD 2: DỮ LIỆU BỘ NHỚ DỊCH
        card_list = create_styled_card(scroll_frame, title="🧠 Danh sách các phân đoạn đã ghi nhớ")
        card_list.pack(fill=tk.X, padx=15, pady=6)

        frame_tree = ctk.CTkFrame(card_list, fg_color="transparent")
        frame_tree.pack(fill=tk.X, padx=15, pady=(0, 15))

        columns = ("id", "source_lang", "target_lang", "source_text", "translated_text", "provider", "model", "hit_count", "updated_at")
        self.tm_tree = ttk.Treeview(frame_tree, columns=columns, show="headings", height=8)
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
        self.tm_tree.pack(fill=tk.BOTH, expand=True)

        # Bottom row action
        action_row = ctk.CTkFrame(card_list, fg_color="transparent")
        action_row.pack(fill=tk.X, padx=15, pady=(0, 15))

        create_styled_button(
            action_row, text="🔄 Làm mới", command=self._refresh_tm_list,
            width=120
        ).pack(side=tk.LEFT, padx=(0, 10))

        create_styled_button(
            action_row, text="🗑️ Xóa bản ghi đã chọn", command=self._delete_tm_segment,
            width=180
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
            self.lbl_router_status.configure(text="Trạng thái Smart Router: 🟢 HOẠT ĐỘNG (Tự động chọn AI tốt nhất)", text_color="green")
        else:
            self.lbl_router_status.configure(text="Trạng thái Smart Router: 🔴 TẮT (Sử dụng cấu hình chế độ dịch cũ)", text_color="red")

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
                    "groq": "Groq",
                    "cerebras": "Cerebras",
                    "openrouter": "OpenRouter",
                    "mistral": "Mistral AI",
                    "sambanova": "SambaNova",
                    "cloudflare": "Cloudflare Workers AI",
                    "huggingface": "HuggingFace",
                    "github": "GitHub Models",
                    "ai21": "AI21 Studio",
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
        """Clean up all tracked after tasks and set destroyed flag."""
        self._is_destroyed = True

        # Cancel all tracked after callbacks for this window instance
        if hasattr(self, '_after_ids'):
            for after_id in list(self._after_ids):
                try:
                    super().after_cancel(after_id)
                except Exception:
                    pass
            self._after_ids.clear()

        if hasattr(self, '_local_after_ids'):
            for after_id in list(self._local_after_ids):
                try:
                    super().after_cancel(after_id)
                except Exception:
                    pass
            self._local_after_ids.clear()

        # Clean up specific other after references if any
        if hasattr(self, '_provider_model_poll_after_ids'):
            self._provider_model_poll_after_ids.clear()
        self._auto_refresh_after_id = None

        # Force Tcl/Tk to process all pending deletions and release handles immediately
        try:
            self.update_idletasks()
        except Exception:
            pass

        super().destroy()
        import gc
        gc.collect()

    def after(self, delay_ms, callback=None, *args):
        """Track scheduled after tasks on the window instance."""
        if getattr(self, '_is_destroyed', False):
            return ""

        if callback is None:
            return super().after(delay_ms)

        callback_id = None

        def wrapper(*w_args, **w_kwargs):
            if getattr(self, '_is_destroyed', False):
                return
            if hasattr(self, '_after_ids') and callback_id in self._after_ids:
                self._after_ids.discard(callback_id)
            callback(*w_args, **w_kwargs)

        callback_id = super().after(delay_ms, wrapper, *args)
        if hasattr(self, '_after_ids'):
            self._after_ids.add(callback_id)
        return callback_id

    def after_cancel(self, id_):
        """Cancel and clean up a scheduled after task."""
        if hasattr(self, '_after_ids') and id_ in self._after_ids:
            self._after_ids.discard(id_)
        try:
            super().after_cancel(id_)
        except Exception:
            pass

    def _on_mouse_wheel(self, event):
        """Handle global mouse wheel scroll for scrollable canvas widgets."""
        widget = event.widget
        if isinstance(widget, str):
            try:
                widget = self.nametowidget(widget)
            except Exception:
                return

        if not widget or not hasattr(widget, "master"):
            return

        current = widget

        # Check if the event occurred inside a text, listbox, or treeview
        # that already handles scrolling natively.
        while current:
            if isinstance(current, (tk.Text, tk.Listbox, ttk.Treeview)):
                return
            if not hasattr(current, "master"):
                break
            current = current.master

        # Find the nearest scrollable canvas parent
        current = widget
        canvas = None
        while current:
            if isinstance(current, tk.Canvas) and hasattr(current, "yview"):
                canvas = current
                break
            if not hasattr(current, "master"):
                break
            current = current.master

        if canvas:
            if event.delta:
                canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            elif event.num == 4:  # Linux scroll up
                canvas.yview_scroll(-1, "units")
            elif event.num == 5:  # Linux scroll down
                canvas.yview_scroll(1, "units")

    def _on_wizard_selection_changed(self, *args):
        """Update wizard card content based on selected combobox provider."""
        display_name = self.wizard_prov_var.get()
        internal_name = self.wizard_display_to_internal.get(display_name)
        if not internal_name or internal_name not in self.guide_data:
            return

        data = self.guide_data[internal_name]

        # Update labels
        self.lbl_wiz_name.configure(text=data["name"])

        # Difficulty label with color
        diff_text = data["difficulty"]
        diff_color = data.get("difficulty_color", ("#059669", "#34D399"))
        self.lbl_wiz_diff.configure(text=diff_text, text_color=diff_color)

        self.lbl_wiz_free.configure(text=data["free_tier"])
        self.lbl_wiz_rec.configure(text=data["recommend"])
        self.lbl_wiz_req.configure(text=data["needs"])
        self.lbl_wiz_model.configure(text=data["suggested_model"])

        # Rebuild steps frame
        for widget in self.frame_wiz_steps.winfo_children():
            widget.destroy()

        for step in data["steps"]:
            lbl_step = ctk.CTkLabel(
                self.frame_wiz_steps, text=step,
                font=('Segoe UI', 10),
                text_color=('#1F2937', '#F3F4F6'),
                justify=tk.LEFT,
                wraplength=520,
                anchor=tk.W
            )
            lbl_step.pack(anchor=tk.W, fill=tk.X, pady=1)

        self.lbl_wiz_err.configure(text=data["errors"])

    def _on_wizard_open_link(self):
        """Open the URL of the selected provider in a web browser."""
        import webbrowser
        display_name = self.wizard_prov_var.get()
        internal_name = self.wizard_display_to_internal.get(display_name)
        if not internal_name or internal_name not in self.guide_data:
            return
        url = self.guide_data[internal_name]["url"]
        try:
            webbrowser.open(url)
        except Exception as e:
            logger.error(f"Error opening wizard URL: {e}")

    def _on_wizard_copy_model(self):
        """Copy the suggested model name to the clipboard."""
        display_name = self.wizard_prov_var.get()
        internal_name = self.wizard_display_to_internal.get(display_name)
        if not internal_name or internal_name not in self.guide_data:
            return
        model = self.guide_data[internal_name]["suggested_model"]
        try:
            self.clipboard_clear()
            self.clipboard_append(model)
            self.update()
            messagebox.showinfo("Sao chép thành công", f"Đã sao chép model '{model}' vào clipboard!")
        except Exception as e:
            logger.error(f"Error copying model to clipboard: {e}")
            messagebox.showerror("Lỗi", f"Không thể sao chép model: {str(e)}")

    def _on_wizard_focus_provider(self):
        """Select and focus the selected provider in the main Treeview."""
        display_name = self.wizard_prov_var.get()
        internal_name = self.wizard_display_to_internal.get(display_name)
        if not internal_name:
            return

        if self.prov_tree.exists(internal_name):
            self.prov_tree.selection_set(internal_name)
            self.prov_tree.see(internal_name)
            self._on_provider_selected()
        else:
            # Fallback for search or case mismatch
            for item in self.prov_tree.get_children():
                if item.lower() == internal_name.lower():
                    self.prov_tree.selection_set(item)
                    self.prov_tree.see(item)
                    self._on_provider_selected()
                    break

    def _on_wizard_test_connection(self):
        """Forward wizard connection checks directly to health scanner."""
        selected_provider = self.wizard_prov_var.get()
        self.health_prov_var.set(selected_provider)
        self._on_health_check_provider()

    def _on_health_check_provider(self):
        """Run diagnostics on selected provider default model."""
        display_name = self.health_prov_var.get()
        internal_name = self.wizard_display_to_internal.get(display_name)
        if not internal_name:
            return
        self._run_health_checks_in_background(self._execute_provider_check, internal_name)

    def _on_health_check_model(self):
        """Run diagnostics on custom model input."""
        display_name = self.health_prov_var.get()
        internal_name = self.wizard_display_to_internal.get(display_name)
        if not internal_name:
            return
        check_model = self.health_model_var.get().strip()
        if not check_model:
            messagebox.showerror("Lỗi", "Vui lòng nhập Model ID để kiểm tra.")
            return
        self._run_health_checks_in_background(self._execute_model_check, internal_name, check_model)

    def _on_health_check_provider_models(self):
        """Audit all model pools for the selected provider."""
        display_name = self.health_prov_var.get()
        internal_name = self.wizard_display_to_internal.get(display_name)
        if not internal_name:
            return
        self._run_health_checks_in_background(self._execute_provider_models_check, internal_name)

    def _on_health_check_all_configured(self):
        """Audit all enabled providers and models in configuration."""
        self._run_health_checks_in_background(self._execute_all_configured_check)

    def _run_health_checks_in_background(self, target_fn, *args, **kwargs):
        """Build thread workers with active progress state updates to execute long running HTTP probe checks."""
        self.health_cancel_event.clear()
        self._set_health_buttons_state(tk.DISABLED)
        self.btn_wiz_test_conn.configure(state=tk.DISABLED)
        self.btn_health_cancel.configure(state=tk.NORMAL)

        self.lbl_health_status.configure(text="⏳ Đang quét kiểm tra kết nối AI, vui lòng đợi...", text_color="#3B82F6")
        self.progress_health.pack(side=tk.LEFT, padx=5)
        self.progress_health.start()

        def worker():
            try:
                from translation_app.core.provider_health_checker import ProviderHealthChecker
                checker = ProviderHealthChecker(
                    config_manager=self.config_manager,
                    provider_router=getattr(self.translation_service, "_provider_router", None) if self.translation_service else None,
                    cancel_event=self.health_cancel_event
                )
                results = target_fn(checker, *args, **kwargs)
                self.after(0, self._on_health_check_finished, results)
            except Exception as e:
                logger.error(f"Health checker worker thread error: {e}")
                self.after(0, self._on_health_check_finished, [])

        t = threading.Thread(target=worker, daemon=True)
        t.start()

    def _execute_provider_check(self, checker, provider_id):
        res = checker.check_provider(provider_id, on_result=lambda r: self.after(0, self._append_single_health_result, r))
        return [res]

    def _execute_model_check(self, checker, provider_id, model_id):
        res = checker.check_model(provider_id, model_id, on_result=lambda r: self.after(0, self._append_single_health_result, r))
        return [res]

    def _execute_provider_models_check(self, checker, provider_id):
        return checker.check_provider_models(provider_id, on_result=lambda r: self.after(0, self._append_single_health_result, r))

    def _execute_all_configured_check(self, checker):
        return checker.check_all_configured(on_result=lambda r: self.after(0, self._append_single_health_result, r))

    def _on_health_cancel(self):
        """Cancel current active health check cooperative thread."""
        self.health_cancel_event.set()
        self.lbl_health_status.configure(text="🛑 Đang yêu cầu dừng quét kiểm tra...", text_color="#EF4444")
        self.btn_health_cancel.configure(state=tk.DISABLED)

    def _append_single_health_result(self, res):
        """Append a single health result to the Treeview progressively."""
        if getattr(self, '_is_destroyed', False):
            return

        status_disp = "❓ Lỗi chưa phân loại"
        tag = "error"

        if res.status == "ok":
            status_disp = "✅ Sống"
            tag = "ok"
        elif res.status == "missing_key":
            status_disp = "🔐 Thiếu key"
            tag = "warning"
        elif res.status == "auth_error":
            status_disp = "🔑 Sai key / hết quyền"
            tag = "error"
        elif res.status == "quota_or_rate_limited":
            status_disp = "🚦 Hết quota / bị giới hạn tốc độ"
            tag = "warning"
        elif res.status == "model_not_found":
            status_disp = "❌ Model không tồn tại"
            tag = "error"
        elif res.status == "endpoint_not_found":
            status_disp = "🌐 Sai endpoint / base URL"
            tag = "error"
        elif res.status == "payload_error":
            status_disp = "🧾 Payload không hợp lệ"
            tag = "error"
        elif res.status == "timeout":
            status_disp = "⏱ Timeout"
            tag = "warning"
        elif res.status == "provider_disabled":
            status_disp = "🚫 Provider đang tắt"
            tag = "warning"
        elif res.status == "cancelled":
            status_disp = "🛑 Đã dừng"
            tag = "warning"
        elif res.status == "provider_wrapper_error":
            status_disp = "🧩 Lỗi wrapper kiểm tra"
            tag = "warning"

        err_msg = res.raw_error_sanitized or res.message
        latency_disp = f"{res.latency_ms} ms" if res.latency_ms > 0 else "-"

        # Remove existing duplicate row if exists
        for child in self.health_tree.get_children():
            vals = self.health_tree.item(child, "values")
            if vals and vals[0] == res.provider_name and vals[1] == res.model_id:
                self.health_tree.delete(child)

        self.health_tree.insert(
            "", 0,  # Insert at top
            values=(res.provider_name, res.model_id, status_disp, latency_disp, err_msg, res.suggestion),
            tags=(tag,)
        )

    def _set_health_buttons_state(self, state):
        self.btn_health_provider.configure(state=state)
        self.btn_health_model.configure(state=state)
        self.btn_health_models.configure(state=state)
        self.btn_health_all.configure(state=state)

    def _on_health_check_finished(self, results):
        """Handle rendering the diagnostic outcomes to the Treeview table once check finishes."""
        if getattr(self, '_is_destroyed', False):
            return

        self.progress_health.stop()
        self.progress_health.pack_forget()
        self._set_health_buttons_state(tk.NORMAL)
        self.btn_wiz_test_conn.configure(state=tk.NORMAL)
        self.btn_health_cancel.configure(state=tk.DISABLED)

        if self.health_cancel_event.is_set():
            self.lbl_health_status.configure(text="Đã dừng quét kiểm tra.", text_color=self.colors['gray_medium'])
        else:
            self.lbl_health_status.configure(text="Hoàn tất kiểm tra.", text_color=self.colors['gray_medium'])

        # Refresh configurations trees and summaries
        self._refresh_quick_config_summary()
        self._refresh_providers_tree()
        self._refresh_router_health()

    def _on_health_provider_changed(self, *args):
        """Update suggestion model list when selected health checker provider shifts."""
        display_name = self.health_prov_var.get()
        internal_name = self.wizard_display_to_internal.get(display_name)
        if not internal_name:
            return

        # Fetch models from catalog
        catalog = self.config_manager.get_provider_model_catalog_public()
        prov_entry = catalog.get("providers", {}).get(internal_name, {})
        models = prov_entry.get("models", [])

        # Also check configured models in profile
        pub_data = self.config_manager.get_provider_profiles_public()
        p_cfg = pub_data.get(internal_name, {})
        cfg_models = p_cfg.get("models", [])

        unique_models = []
        for m in models:
            m_id = m.get("id") if isinstance(m, dict) else m
            if m_id and m_id not in unique_models:
                unique_models.append(m_id)
        for m_id in cfg_models:
            if m_id and m_id not in unique_models:
                unique_models.append(m_id)

        # Set default model
        default_model = p_cfg.get("default_model") or prov_entry.get("default_model") or ""

        if unique_models:
            self.health_model_combo.configure(values=unique_models)
            if default_model in unique_models:
                self.health_model_var.set(default_model)
            else:
                self.health_model_var.set(unique_models[0])
        else:
            self.health_model_combo.configure(values=[])
            self.health_model_var.set(default_model)
