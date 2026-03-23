"""
Main application window for translation application
"""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import os
from datetime import datetime
from typing import Optional
from PIL import Image, ImageGrab, ImageTk
import threading

from translation_app.core.translator import TranslationService
from translation_app.core.file_handlers.excel_handler import ExcelHandler
from translation_app.core.file_handlers.word_handler import WordHandler
from translation_app.core.file_handlers.powerpoint_handler import PowerPointHandler
from translation_app.core.file_handlers.pdf_handler import PDFHandler
from translation_app.core.file_handlers.text_handler import TextHandler
from translation_app.core.email_handler import EmailHandler
from translation_app.core.ocr_handler import get_ocr_handler
from translation_app.ui.theme import setup_theme
from translation_app.ui.components import create_styled_button, create_language_combobox
from translation_app.utils.validators import FileValidator, LanguageValidator
from translation_app.utils.error_handler import handle_translation_error
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

        # Filter out backward compatibility keys for cleaner UI
        # Keep 'auto' for auto-detect, filter out zh-cn/zh-tw variations
        self.display_languages = {k: v for k, v in config.supported_languages.items()
                                if k == 'auto' or (not k.startswith(('zh-cn', 'zh-tw')) or k in ['zh-CN', 'zh-TW'])}

        # Clipboard image for paste functionality
        self.clipboard_image: Optional[Image.Image] = None
        self.preview_photo: Optional[ImageTk.PhotoImage] = None
        self._preview_photo_refs: list = []  # Lưu references để tránh garbage collection
        self.last_ocr_text: str = "" # To store OCR result for analysis

        # Setup UI
        self.setup_window()
        self.setup_theme()
        self.create_widgets()
        
        logger.info("Main window initialized")
    
    def setup_window(self):
        """Setup window properties"""
        from translation_app import __version__
        self.title(f"Dịch tự động v{__version__}_Bùi Đức Vinh_Phòng phát triển hệ thống chế tạo")
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
        self.tab_ai = tk.Frame(self.notebook, bg=self.colors['gray_light']) # NEW AI TAB
        
        self.notebook.add(self.tab_file, text="Dịch File")
        self.notebook.add(self.tab_paragraph, text="Dịch Đoạn Văn")
        self.notebook.add(self.tab_email, text="Dịch Email")
        self.notebook.add(self.tab_image, text="Dịch Ảnh")
        self.notebook.add(self.tab_ai, text="Cấu hình AI") # ADD TO NOTEBOOK
        
        self.notebook.pack(expand=True, fill="both", padx=5, pady=5)
        
        # Setup each tab
        self.setup_file_tab()
        self.setup_paragraph_tab()
        self.setup_email_tab()
        self.setup_image_tab()
        self.setup_ai_tab()

        # Connect Strategy ComboBox to Translation Service
        self.strat_var.trace_add("write", self._on_strategy_changed)
    
    def _on_strategy_changed(self, *args):
        """Update translation strategy when ComboBox changes"""
        new_strat = self.strat_var.get()
        self.translation_service.set_strategy(new_strat)
    
    def setup_ai_tab(self):
        """Setup the AI Configuration tab."""
        # Main Scrollable content
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
            scrollable_frame, text="🤖 Cấu hình Dịch thuật & AI",
            bg=self.colors['gray_light'], fg=self.colors['navy'],
            font=('Segoe UI', 16, 'bold')
        )
        label_title.pack(pady=(20, 10))
        
        # 1. Google Translate Section
        google_frame = tk.LabelFrame(scrollable_frame, text="🌐 Google Translate (Dịch vụ chính)", 
                                    bg=self.colors['gray_light'], fg=self.colors['navy'],
                                    font=('Segoe UI', 10, 'bold'), padx=10, pady=10)
        google_frame.pack(fill=tk.X, padx=20, pady=10)
        
        tk.Label(google_frame, text="Đây là dịch vụ dịch thuật miễn phí mặc định của ứng dụng.", 
                 bg=self.colors['gray_light'], fg=self.colors['gray_dark']).pack(anchor=tk.W)
        
        tk.Label(google_frame, text="Trạng thái: ✅ Đang hoạt động", 
                 bg=self.colors['gray_light'], fg="green", font=('Segoe UI', 9, 'bold')).pack(anchor=tk.W, pady=5)
        
        # 2. Gemini AI Waterfall Section
        gemini_frame = tk.LabelFrame(scrollable_frame, text="⚡ Gemini AI", 
                                     bg=self.colors['gray_light'], fg=self.colors['navy'],
                                     font=('Segoe UI', 10, 'bold'), padx=10, pady=10)
        gemini_frame.pack(fill=tk.X, padx=20, pady=10)
        
        info_text = (
            "Hệ thống sẽ tự động kích hoạt Gemini nếu Google Translate bị quá tải\n"
            "hoặc trả về lỗi. Điều này giúp quá trình dịch không bị gián đoạn."
        )
        tk.Label(gemini_frame, text=info_text, bg=self.colors['gray_light'], 
                 fg=self.colors['gray_dark'], justify=tk.LEFT).pack(anchor=tk.W)
        
        btn_open = create_styled_button(
            gemini_frame, text="⚙️ Cấu hình API Key & Quản lý Model Gemini",
            command=self._open_ai_settings, colors=self.colors
        )
        btn_open.pack(pady=10)
        
        # API Key Link Section
        link_frame = tk.Frame(gemini_frame, bg=self.colors['gray_light'])
        link_frame.pack(fill=tk.X, pady=(5, 0))
        
        tk.Label(link_frame, text="🔑 Chưa có API Key?", 
                 bg=self.colors['gray_light'], fg=self.colors['gray_dark'],
                 font=('Segoe UI', 9)).pack(side=tk.LEFT)
        
        # Create clickable link label
        link_label = tk.Label(
            link_frame, 
            text="Lấy API Key miễn phí từ Google AI Studio →",
            bg=self.colors['gray_light'], 
            fg="#0066CC",  # Link blue color
            font=('Segoe UI', 9, 'underline'),
            cursor="hand2"  # Hand cursor on hover
        )
        link_label.pack(side=tk.LEFT, padx=(5, 0))
        
        # Bind click event to open URL
        def open_ai_studio_url(event=None):
            import webbrowser
            webbrowser.open("https://aistudio.google.com/app/apikey")
        
        link_label.bind("<Button-1>", open_ai_studio_url)
        
        # Add hover effect
        def on_enter(event):
            link_label.config(fg="#003399")  # Darker blue on hover
        
        def on_leave(event):
            link_label.config(fg="#0066CC")  # Original blue
        
        link_label.bind("<Enter>", on_enter)
        link_label.bind("<Leave>", on_leave)
        
        # 3. Strategy Setting
        strat_frame = tk.LabelFrame(scrollable_frame, text="🛠️ Cài đặt máy dịch thuật", 
                                    bg=self.colors['gray_light'], fg=self.colors['navy'],
                                    font=('Segoe UI', 10, 'bold'), padx=10, pady=10)
        strat_frame.pack(fill=tk.X, padx=20, pady=10)
        
        tk.Label(strat_frame, text="Ưu tiên dịch thuật:", 
                 bg=self.colors['gray_light']).pack(side=tk.LEFT)
        
        self.strat_var = tk.StringVar(value="Google Translate (Mặc định)")
        strat_combo = ttk.Combobox(strat_frame, textvariable=self.strat_var, values=[
            "Google Translate (Mặc định)",
            "Gemini AI (Chỉ dùng AI)",
            "Google Translate -> Gemini AI",
            "Gemini AI -> Google Translate"
        ], state="readonly", width=30)
        strat_combo.pack(side=tk.LEFT, padx=10)
        
        tk.Label(strat_frame, text="💡 Khuyến nghị dùng: Google Translate -> Gemini AI", 
                 bg=self.colors['gray_light'], fg=self.colors['gray_medium'], font=('Segoe UI', 8, 'italic')).pack(side=tk.LEFT)

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
            text="Chương trình tự động nhận diện và dịch các loại file:\nExcel (.xlsx, .xls), Word (.docx, .doc), PowerPoint (.pptx, .ppt), Text (.txt), PDF (.pdf)",
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
            text="    💡 Gộp nhiều trang thành 1 ảnh grid → 1 request AI (tiết kiệm RPD)",
            bg=self.colors['gray_light'], fg=self.colors['gray_medium'],
            font=('Segoe UI', 8, 'italic')
        )
        label_ai_info.pack(anchor=tk.W)

        
        # Buttons frame
        frame_buttons = tk.Frame(self.tab_file, bg=self.colors['gray_light'])
        frame_buttons.pack(fill=tk.X, padx=15, pady=15)
        
        button_translate_file = create_styled_button(
            frame_buttons, text="Dịch File đã chọn",
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
            frame_input, text="Nhập Đoạn Văn:",
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
            frame_buttons_para, text="Dịch đoạn văn đã nhập",
            command=self.translate_paragraph, colors=self.colors
        )
        button_translate_paragraph.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        
        button_clear_paragraph = create_styled_button(
            frame_buttons_para, text="Xóa đoạn văn đã nhập",
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
            frame_output, text="Đoạn Văn Dịch:",
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
            text=f"Chương trình có thể dịch được {config.max_emails_to_translate} mail mới nhất chưa đọc trong thư mục được chỉ định",
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
            frame_image_select, text="Chọn File Ảnh:",
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
            frame_paste_clipboard, text="Paste từ Clipboard (Bấm vào nút để paste ảnh)",
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
            frame_preview, text="Preview Ảnh:",
            bg=self.colors['gray_light'], fg=self.colors['gray_dark'],
            font=('Segoe UI', 11, 'bold')
        )
        label_preview_title.pack(anchor=tk.W, pady=(0, 5))
        
        self.label_image_preview = tk.Label(
            frame_preview,
            text="Chưa có ảnh để hiển thị",
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
            frame_button_image, text="OCR và Dịch Ảnh",
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
        
        # Show PDF AI Vision guide if it's a PDF file and get user's choice
        if ext_lower == '.pdf' and not self.use_ai_vision_for_pdf.get():
            user_choice = self._show_pdf_ai_guide_and_wait()
            if user_choice is None:
                # User closed dialog without making a choice - cancel translation
                logger.info("User cancelled PDF translation dialog")
                return
            # user_choice is already reflected in self.use_ai_vision_for_pdf

        
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
        output_file = f"{base}_translated_{today_str}{output_ext}"
        
        # Check if AI Vision should be used for PDF
        use_ai_vision = (ext_lower == '.pdf' and self.use_ai_vision_for_pdf.get())
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
            update_progress(f"🤖 Đang chuẩn bị dịch AI Vision ({pages_per_batch} trang/batch)...", 2)
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
                else:
                    handler.translate(file_path, output_file, src_lang, dest_lang)

                # Stop progress and show success
                def _on_success():
                    self.progress_file['value'] = 100
                    method_info = " (AI Vision)" if use_ai_vision else ""
                    self.label_file_status.config(text="✓ Hoàn tất!")
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
                    error_msg = handle_translation_error(e, "Dịch file")
                    messagebox.showerror("Lỗi", error_msg)
                
                self.after(0, _on_error)
        
        threading.Thread(target=translate_thread, daemon=True).start()


    
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
        self.entry_paragraph_output.insert(tk.END, "🔄 Đang phân tích chuyên sâu... Vui lòng đợi trong giây lát...")
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
                        f"{count} email mới nhất chưa đọc đã được dịch và gửi thành công."
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
            self.label_image_preview.config(image='', text="Chưa có ảnh để hiển thị")
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
                messagebox.showerror("Lỗi", "Vui lòng chọn file ảnh hoặc paste ảnh từ clipboard để dịch.")
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
            messagebox.showwarning("Cảnh báo", "Vui lòng 'OCR và Dịch Ảnh' trước khi yêu cầu phân tích.")
            return
        
        src_lang = self.src_lang_image.get()
        dest_lang = self.dest_lang_image.get()
        
        # Show waiting status
        self.text_output.delete("1.0", tk.END)
        self.text_output.insert(tk.END, "🔄 Đang phân tích chuyên sâu nội dung ảnh... Vui lòng đợi trong giây lát...")
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
        self.text_output.insert(tk.END, "=== BẢN PHÂN TÍCH Ý NGHĨA CHUYÊN SÂU (AI) ===\n\n")
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
            text="📌 Tại sao nên dùng AI Vision?",
            font=('Segoe UI', 10, 'bold'),
            bg=self.colors['white'], fg=self.colors['gray_dark'],
            padx=10, pady=10
        )
        why_frame.pack(fill=tk.X, pady=(0, 10))
        
        why_text = """• PDF thường rất khó dịch chính xác (bảng bị vỡ, mất format, thiếu nội dung)
• AI Vision của Google Gemini nhận diện tiếng Nhật/Trung/Việt RẤT TỐT
• AI hiểu ngữ cảnh → dịch thuật ngữ kỹ thuật chính xác hơn
• Giữ nguyên cấu trúc bảng và layout tốt hơn"""
        
        tk.Label(
            why_frame, text=why_text,
            font=('Segoe UI', 9), justify=tk.LEFT,
            bg=self.colors['white'], fg=self.colors['gray_dark']
        ).pack(anchor=tk.W)
        
        # Status indicator
        status_frame = tk.Frame(main_frame, bg=self.colors['white'])
        status_frame.pack(fill=tk.X, pady=(0, 10))
        
        if ai_configured:
            status_icon = "✅"
            status_text = "API Gemini đã được cấu hình! Bạn có thể sử dụng AI Vision ngay."
            status_color = "green"
        else:
            status_icon = "⚠️"
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
            
            steps_text = """BƯỚC 1: Lấy API Key từ Google AI Studio (MIỄN PHÍ)
   ────────────────────────────────────────────
   1.1  Nhấn nút "🔗 Mở Google AI Studio" bên dưới
   1.2  Đăng nhập bằng tài khoản Google của bạn
   1.3  Nhấn nút "Get API Key" (Lấy API Key)
   1.4  Nhấn "Create API key" (Tạo API key mới)
   1.5  Chọn một dự án bất kỳ hoặc tạo mới
   1.6  COPY mã API key (chuỗi dài bắt đầu bằng "AIza...")

BƯỚC 2: Cấu hình trong ứng dụng
   ────────────────────────────────────────────
   2.1  Quay lại ứng dụng này
   2.2  Chọn tab "Cấu hình AI" (hoặc nhấn nút bên dưới)
   2.3  Dán API key vào ô "Thêm API Key"
   2.4  Nhấn nút "Thêm Key" để lưu
   2.5  Đóng cửa sổ cấu hình

BƯỚC 3: Sử dụng AI Vision
   ────────────────────────────────────────────
   3.1  Quay lại tab "Dịch File"
   3.2  Tích chọn "🤖 Dùng AI Vision cho PDF"
   3.3  Chọn số trang/batch (4 = tiết kiệm 75% request)
   3.4  Nhấn "Dịch File đã chọn"
   
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
                btn_row2, text="✅ Bật AI Vision và Dịch",
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
• Gộp 4 trang/batch = tiết kiệm 75% requests
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

    def on_closing(self):
        """Handle window closing"""
        logger.info("Application closing")
        self.translation_service.shutdown()
        self.destroy()

