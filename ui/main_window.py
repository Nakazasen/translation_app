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

        # Filter out backward compatibility keys for cleaner UI
        # Keep 'auto' for auto-detect, filter out zh-cn/zh-tw variations
        self.display_languages = {k: v for k, v in config.supported_languages.items()
                                if k == 'auto' or (not k.startswith(('zh-cn', 'zh-tw')) or k in ['zh-CN', 'zh-TW'])}

        # Clipboard image for paste functionality
        self.clipboard_image: Optional[Image.Image] = None
        self.preview_photo: Optional[ImageTk.PhotoImage] = None
        self._preview_photo_refs: list = []  # Lﾆｰu references ﾄ黛ｻ・trﾃ｡nh garbage collection
        self.last_ocr_text: str = "" # To store OCR result for analysis

        # Setup UI
        self.setup_window()
        self.setup_theme()
        self.create_widgets()
        
        logger.info("Main window initialized")
    
    def setup_window(self):
        """Setup window properties"""
        from translation_app import __version__
        self.title(f"D盻議h t盻ｱ ﾄ黛ｻ冢g v{__version__}_Bﾃｹi ﾄ雪ｻｩc Vinh_Phﾃｲng phﾃ｡t tri盻ハ h盻・th盻創g ch蘯ｿ t蘯｡o")
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
        self.tab_jobs = tk.Frame(self.notebook, bg=self.colors['gray_light'])
        self.tab_glossary = tk.Frame(self.notebook, bg=self.colors['gray_light'])
        self.tab_tm = tk.Frame(self.notebook, bg=self.colors['gray_light'])
        self.tab_router = tk.Frame(self.notebook, bg=self.colors['gray_light'])
        
        self.notebook.add(self.tab_file, text="D盻議h File")
        self.notebook.add(self.tab_paragraph, text="D盻議h ﾄ塵蘯｡n Vﾄハ")
        self.notebook.add(self.tab_email, text="D盻議h Email")
        self.notebook.add(self.tab_image, text="D盻議h 蘯｢nh")
        self.notebook.add(self.tab_ai, text="C蘯･u hﾃｬnh AI") # ADD TO NOTEBOOK
        self.notebook.add(self.tab_jobs, text="Jobs")
        self.notebook.add(self.tab_glossary, text="Glossary")
        self.notebook.add(self.tab_tm, text="Translation Memory")
        self.notebook.add(self.tab_router, text="Provider Router")
        
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
        self.setup_router_tab()

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
            scrollable_frame, text="､・C蘯･u hﾃｬnh D盻議h thu蘯ｭt & AI",
            bg=self.colors['gray_light'], fg=self.colors['navy'],
            font=('Segoe UI', 16, 'bold')
        )
        label_title.pack(pady=(20, 10))
        
        # 1. Google Translate Section
        google_frame = tk.LabelFrame(scrollable_frame, text="倹 Google Translate (D盻議h v盻･ chﾃｭnh)", 
                                    bg=self.colors['gray_light'], fg=self.colors['navy'],
                                    font=('Segoe UI', 10, 'bold'), padx=10, pady=10)
        google_frame.pack(fill=tk.X, padx=20, pady=10)
        
        tk.Label(google_frame, text="ﾄ静｢y lﾃ d盻議h v盻･ d盻議h thu蘯ｭt mi盻・ phﾃｭ m蘯ｷc ﾄ黛ｻ杵h c盻ｧa 盻ｩng d盻･ng.", 
                 bg=self.colors['gray_light'], fg=self.colors['gray_dark']).pack(anchor=tk.W)
        
        tk.Label(google_frame, text="Tr蘯｡ng thﾃ｡i: 笨・ﾄ紳ng ho蘯｡t ﾄ黛ｻ冢g", 
                 bg=self.colors['gray_light'], fg="green", font=('Segoe UI', 9, 'bold')).pack(anchor=tk.W, pady=5)
        
        # 2. Gemini AI Waterfall Section
        gemini_frame = tk.LabelFrame(scrollable_frame, text="笞｡ Gemini AI", 
                                     bg=self.colors['gray_light'], fg=self.colors['navy'],
                                     font=('Segoe UI', 10, 'bold'), padx=10, pady=10)
        gemini_frame.pack(fill=tk.X, padx=20, pady=10)
        
        info_text = (
            "H盻・th盻創g s蘯ｽ t盻ｱ ﾄ黛ｻ冢g kﾃｭch ho蘯｡t Gemini n蘯ｿu Google Translate b盻・quﾃ｡ t蘯｣i\n"
            "ho蘯ｷc tr蘯｣ v盻・l盻擁. ﾄ進盻「 nﾃy giﾃｺp quﾃ｡ trﾃｬnh d盻議h khﾃｴng b盻・giﾃ｡n ﾄ双蘯｡n."
        )
        tk.Label(gemini_frame, text=info_text, bg=self.colors['gray_light'], 
                 fg=self.colors['gray_dark'], justify=tk.LEFT).pack(anchor=tk.W)
        
        btn_open = create_styled_button(
            gemini_frame, text="笞呻ｸ・C蘯･u hﾃｬnh API Key & Qu蘯｣n lﾃｽ Model Gemini",
            command=self._open_ai_settings, colors=self.colors
        )
        btn_open.pack(pady=10)
        
        # API Key Link Section
        link_frame = tk.Frame(gemini_frame, bg=self.colors['gray_light'])
        link_frame.pack(fill=tk.X, pady=(5, 0))
        
        tk.Label(link_frame, text="泊 Chﾆｰa cﾃｳ API Key?", 
                 bg=self.colors['gray_light'], fg=self.colors['gray_dark'],
                 font=('Segoe UI', 9)).pack(side=tk.LEFT)
        
        # Create clickable link label
        link_label = tk.Label(
            link_frame, 
            text="Lay API Key mien phi tu Google AI Studio",
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
        strat_frame = tk.LabelFrame(scrollable_frame, text="屏・・Cﾃi ﾄ黛ｺｷt mﾃ｡y d盻議h thu蘯ｭt", 
                                    bg=self.colors['gray_light'], fg=self.colors['navy'],
                                    font=('Segoe UI', 10, 'bold'), padx=10, pady=10)
        strat_frame.pack(fill=tk.X, padx=20, pady=10)
        
        tk.Label(strat_frame, text="ﾆｯu tiﾃｪn d盻議h thu蘯ｭt:", 
                 bg=self.colors['gray_light']).pack(side=tk.LEFT)
        
        self.strat_var = tk.StringVar(value="Google Translate (M蘯ｷc ﾄ黛ｻ杵h)")
        strat_combo = ttk.Combobox(strat_frame, textvariable=self.strat_var, values=[
            "Google Translate (M蘯ｷc ﾄ黛ｻ杵h)",
            "Gemini AI (Ch盻・dﾃｹng AI)",
            "Google Translate -> Gemini AI",
            "Gemini AI -> Google Translate"
        ], state="readonly", width=30)
        strat_combo.pack(side=tk.LEFT, padx=10)
        
        tk.Label(strat_frame, text="庁 Khuy蘯ｿn ngh盻・dﾃｹng: Google Translate -> Gemini AI", 
                 bg=self.colors['gray_light'], fg=self.colors['gray_medium'], font=('Segoe UI', 8, 'italic')).pack(side=tk.LEFT)

        # 4. Advanced Settings (TM / Glossary / Router)
        adv_frame = tk.LabelFrame(scrollable_frame, text="笞呻ｸ・Cﾃi ﾄ黛ｺｷt nﾃ｢ng cao (TM / Glossary / Router)", 
                                  bg=self.colors['gray_light'], fg=self.colors['navy'],
                                  font=('Segoe UI', 10, 'bold'), padx=10, pady=10)
        adv_frame.pack(fill=tk.X, padx=20, pady=10)

        # Row 1: Translation Memory Settings
        tm_row = tk.Frame(adv_frame, bg=self.colors['gray_light'])
        tm_row.pack(fill=tk.X, pady=5)
        
        tk.Checkbutton(
            tm_row, text="B蘯ｭt B盻・nh盻・d盻議h (Translation Memory)", 
            variable=self.use_tm_var, bg=self.colors['gray_light'],
            fg=self.colors['gray_dark'], activebackground=self.colors['gray_light']
        ).pack(side=tk.LEFT)
        
        tk.Label(tm_row, text="ﾄ雪ｻ・dﾃi t盻訴 thi盻ブ segment lﾆｰu cache:", bg=self.colors['gray_light']).pack(side=tk.LEFT, padx=(20, 5))
        tk.Entry(tm_row, textvariable=self.min_seg_len_var, width=5, bg=self.colors['white']).pack(side=tk.LEFT)

        # Row 2: Glossary Settings
        glossary_row = tk.Frame(adv_frame, bg=self.colors['gray_light'])
        glossary_row.pack(fill=tk.X, pady=5)
        
        tk.Checkbutton(
            glossary_row, text="B蘯ｭt Thu蘯ｭt ng盻ｯ (Glossary)", 
            variable=self.use_glossary_var, bg=self.colors['gray_light'],
            fg=self.colors['gray_dark'], activebackground=self.colors['gray_light']
        ).pack(side=tk.LEFT)
        
        tk.Label(glossary_row, text="C蘯･p ﾄ黛ｻ・th盻ｱc thi:", bg=self.colors['gray_light']).pack(side=tk.LEFT, padx=(20, 5))
        
        def _on_glossary_level_changed(*args):
            level = self.glossary_level_var.get()
            if level == "validate":
                self.glossary_note_label.config(text="庁 Note: 'validate' ﾄ柁ｰ盻｣c dﾃnh riﾃｪng cho cﾃ｡c tﾃｭnh nﾄハg tﾆｰﾆ｡ng lai.", fg="orange")
            else:
                self.glossary_note_label.config(text="庁 Cﾃi ﾄ黛ｺｷt th盻ｱc thi thu蘯ｭt ng盻ｯ thﾃnh cﾃｴng.", fg="green")

        self.glossary_level_var.trace_add("write", _on_glossary_level_changed)
        glossary_level_combo = ttk.Combobox(
            glossary_row, textvariable=self.glossary_level_var, 
            values=["off", "prompt", "validate"], state="readonly", width=10
        )
        glossary_level_combo.pack(side=tk.LEFT)

        tk.Label(glossary_row, text="Max terms/segment:", bg=self.colors['gray_light']).pack(side=tk.LEFT, padx=(20, 5))
        tk.Spinbox(
            glossary_row,
            from_=1,
            to=999,
            textvariable=self.max_glossary_terms_var,
            width=5,
            bg=self.colors['white']
        ).pack(side=tk.LEFT)

        self.glossary_note_label = tk.Label(
            adv_frame, text="庁 Thu蘯ｭt ng盻ｯ giﾃｺp chu蘯ｩn hﾃｳa cﾃ｡c c盻･m t盻ｫ chuyﾃｪn ngﾃnh.", 
            bg=self.colors['gray_light'], fg=self.colors['gray_medium'], font=('Segoe UI', 8, 'italic')
        )
        self.glossary_note_label.pack(anchor=tk.W, pady=(2, 5))

        # Row 3: Provider Router Settings
        router_row = tk.Frame(adv_frame, bg=self.colors['gray_light'])
        router_row.pack(fill=tk.X, pady=5)
        
        tk.Checkbutton(
            router_row, text="B蘯ｭt B盻・ﾄ黛ｻ杵h tuy蘯ｿn thﾃｴng minh (Provider Router)", 
            variable=self.use_router_var, bg=self.colors['gray_light'],
            fg=self.colors['gray_dark'], activebackground=self.colors['gray_light']
        ).pack(side=tk.LEFT)
        
        tk.Label(router_row, text="Policy ﾄ黛ｻ杵h tuy蘯ｿn:", bg=self.colors['gray_light']).pack(side=tk.LEFT, padx=(20, 5))
        router_policy_combo = ttk.Combobox(
            router_row, textvariable=self.router_policy_var, 
            values=["ai_first", "ai_waterfall", "google_first"], state="readonly", width=12
        )
        router_policy_combo.pack(side=tk.LEFT)

        # Row 4: Save Settings Button
        save_btn_row = tk.Frame(adv_frame, bg=self.colors['gray_light'])
        save_btn_row.pack(fill=tk.X, pady=(10, 0))
        create_styled_button(
            save_btn_row, text="沈 Lﾆｰu cﾃi ﾄ黛ｺｷt nﾃ｢ng cao", 
            command=self._save_advanced_settings, colors=self.colors
        ).pack(side=tk.LEFT)

    def setup_file_tab(self):
        """Setup file translation tab"""
        # File selection frame
        frame_file_select = tk.Frame(self.tab_file, bg=self.colors['gray_light'])
        frame_file_select.pack(fill=tk.X, padx=15, pady=10)
        
        label_file_path = tk.Label(
            frame_file_select, text="Ch盻肱 File:",
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
            frame_file_entry, text="Duy盻㏄...", command=self.browse_file, colors=self.colors
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
            frame_src_lang, text="Ngﾃｴn ng盻ｯ ngu盻渡:",
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
            frame_dest_lang, text="Ngﾃｴn ng盻ｯ ﾄ妥ｭch:",
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
            text="Chﾆｰﾆ｡ng trﾃｬnh t盻ｱ ﾄ黛ｻ冢g nh蘯ｭn di盻㌻ vﾃ d盻議h cﾃ｡c lo蘯｡i file:\nExcel (.xlsx, .xls), Word (.docx, .doc), PowerPoint (.pptx, .ppt), Text (.txt), PDF (.pdf)",
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
            text="､・Dﾃｹng AI Vision cho PDF (m蘯｡nh nh蘯･t cho PDF scan, ti蘯ｿng Nh蘯ｭt/Trung)",
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
            text="    S盻・trang/batch:",
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
            text="(4 trang = ti蘯ｿt ki盻㍊ 75% request)",
            bg=self.colors['gray_light'], fg=self.colors['gray_medium'],
            font=('Segoe UI', 8, 'italic')
        )
        label_batch_info.pack(side=tk.LEFT)
        
        # Info tooltip for AI Vision
        label_ai_info = tk.Label(
            frame_ai_option,
            text="    庁 G盻冪 nhi盻「 trang thﾃnh 1 蘯｣nh grid 竊・1 request AI (ti蘯ｿt ki盻㍊ RPD)",
            bg=self.colors['gray_light'], fg=self.colors['gray_medium'],
            font=('Segoe UI', 8, 'italic')
        )
        label_ai_info.pack(anchor=tk.W)

        
        # Buttons frame
        frame_buttons = tk.Frame(self.tab_file, bg=self.colors['gray_light'])
        frame_buttons.pack(fill=tk.X, padx=15, pady=15)
        
        button_translate_file = create_styled_button(
            frame_buttons, text="D盻議h File ﾄ妥｣ ch盻肱",
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
            frame_input, text="Nh蘯ｭp ﾄ塵蘯｡n Vﾄハ:",
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
            frame_src_lang_para, text="Ngﾃｴn ng盻ｯ ngu盻渡:",
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
            frame_dest_lang_para, text="Ngﾃｴn ng盻ｯ ﾄ妥ｭch:",
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
            frame_buttons_para, text="D盻議h ﾄ双蘯｡n vﾄハ ﾄ妥｣ nh蘯ｭp",
            command=self.translate_paragraph, colors=self.colors
        )
        button_translate_paragraph.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        
        button_clear_paragraph = create_styled_button(
            frame_buttons_para, text="Xﾃｳa ﾄ双蘯｡n vﾄハ ﾄ妥｣ nh蘯ｭp",
            command=self.clear_input_paragraph, colors=self.colors
        )
        button_clear_paragraph.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 5))

        # NEW: Analyze button
        button_analyze_paragraph = create_styled_button(
            frame_buttons_para, text="剥 Phﾃ｢n tﾃｭch ﾃｽ nghﾄｩa cﾃ｢u (AI)",
            command=self.analyze_paragraph, colors=self.colors
        )
        # Use a slightly different color or highlight if possible, but keep style consistent
        button_analyze_paragraph.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 0))
        
        # Context frame (NEW)
        frame_context = tk.Frame(self.tab_paragraph, bg=self.colors['gray_light'])
        frame_context.pack(fill=tk.X, padx=15, pady=(5, 0))
        
        tk.Label(frame_context, text="B盻訴 c蘯｣nh/Ghi chﾃｺ thﾃｪm (Tﾃｹy ch盻肱):", 
                 bg=self.colors['gray_light'], font=('Segoe UI', 9, 'italic')).pack(side=tk.LEFT)
        self.entry_paragraph_context = tk.Entry(frame_context, font=('Segoe UI', 10), bg=self.colors['white'])
        self.entry_paragraph_context.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10)
        
        # Output frame
        frame_output = tk.Frame(self.tab_paragraph, bg=self.colors['gray_light'])
        frame_output.pack(fill=tk.BOTH, expand=True, padx=15, pady=10)
        
        label_paragraph_output = tk.Label(
            frame_output, text="ﾄ塵蘯｡n Vﾄハ D盻議h:",
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
            frame_output, text="Sao chﾃｩp ﾄ双蘯｡n vﾄハ ﾄ妥｣ d盻議h",
            command=self.copy_output_paragraph, colors=self.colors
        )
        button_copy_paragraph.pack(fill=tk.X)
    
    def setup_email_tab(self):
        """Setup email translation tab"""
        # Folder frame
        frame_folder = tk.Frame(self.tab_email, bg=self.colors['gray_light'])
        frame_folder.pack(fill=tk.X, padx=15, pady=15)
        
        label_folder_name = tk.Label(
            frame_folder, text="Nh蘯ｭp tﾃｪn thﾆｰ m盻･c trong hﾃｲm thﾆｰ c蘯ｧn d盻議h:",
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
            frame_src_lang_email, text="Ngﾃｴn ng盻ｯ ngu盻渡:",
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
            frame_dest_lang_email, text="Ngﾃｴn ng盻ｯ ﾄ妥ｭch:",
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
            text=f"Chﾆｰﾆ｡ng trﾃｬnh cﾃｳ th盻・d盻議h ﾄ柁ｰ盻｣c {config.max_emails_to_translate} mail m盻嬖 nh蘯･t chﾆｰa ﾄ黛ｻ皇 trong thﾆｰ m盻･c ﾄ柁ｰ盻｣c ch盻・ﾄ黛ｻ杵h",
            bg=self.colors['gray_light'], fg=self.colors['gray_medium'],
            font=('Segoe UI', 9), justify=tk.LEFT
        )
        label_info.pack(padx=15, pady=10)
        
        # Button frame
        frame_button_email = tk.Frame(self.tab_email, bg=self.colors['gray_light'])
        frame_button_email.pack(fill=tk.X, padx=15, pady=15)
        
        button_translate_email = create_styled_button(
            frame_button_email, text="D盻議h Email",
            command=self.translate_email, colors=self.colors
        )
        button_translate_email.pack(fill=tk.X)
    
    def setup_image_tab(self):
        """Setup image translation tab"""
        # Image selection frame
        frame_image_select = tk.Frame(self.tab_image, bg=self.colors['gray_light'])
        frame_image_select.pack(fill=tk.X, padx=15, pady=10)
        
        label_image_path = tk.Label(
            frame_image_select, text="Ch盻肱 File 蘯｢nh:",
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
            frame_image_entry, text="Duy盻㏄...",
            command=self.browse_image, colors=self.colors
        )
        button_browse_image.pack(side=tk.LEFT)
        
        # Paste from clipboard frame
        frame_paste_clipboard = tk.Frame(self.tab_image, bg=self.colors['gray_light'])
        frame_paste_clipboard.pack(fill=tk.X, padx=15, pady=10)
        
        button_paste_clipboard = create_styled_button(
            frame_paste_clipboard, text="Paste t盻ｫ Clipboard (B蘯･m vﾃo nﾃｺt ﾄ黛ｻ・paste 蘯｣nh)",
            command=self.paste_image_from_clipboard, colors=self.colors
        )
        button_paste_clipboard.pack(side=tk.LEFT, padx=(0, 10))
        
        self.label_clipboard_status = tk.Label(
            frame_paste_clipboard,
            text="Chﾆｰa cﾃｳ 蘯｣nh t盻ｫ clipboard",
            bg=self.colors['gray_light'], fg=self.colors['gray_medium'],
            font=('Segoe UI', 9)
        )
        self.label_clipboard_status.pack(side=tk.LEFT)
        
        # Preview frame
        frame_preview = tk.Frame(self.tab_image, bg=self.colors['gray_light'])
        frame_preview.pack(fill=tk.X, padx=15, pady=10)
        
        label_preview_title = tk.Label(
            frame_preview, text="Preview 蘯｢nh:",
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
            frame_src_lang_image, text="Ngﾃｴn ng盻ｯ ngu盻渡:",
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
            frame_dest_lang_image, text="Ngﾃｴn ng盻ｯ ﾄ妥ｭch:",
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
            text="Chﾆｰﾆ｡ng trﾃｬnh s蘯ｽ OCR text trong 蘯｣nh vﾃ d盻議h sang ngﾃｴn ng盻ｯ ﾄ妥ｭch",
            bg=self.colors['gray_light'], fg=self.colors['gray_medium'],
            font=('Segoe UI', 9), justify=tk.LEFT
        )
        label_info_image.pack(padx=15, pady=10)
        
        # Button frame
        frame_button_image = tk.Frame(self.tab_image, bg=self.colors['gray_light'])
        frame_button_image.pack(fill=tk.X, padx=15, pady=10)
        
        button_translate_image = create_styled_button(
            frame_button_image, text="OCR vﾃ D盻議h 蘯｢nh",
            command=self.translate_image, colors=self.colors
        )
        button_translate_image.pack(fill=tk.X, pady=(0, 10))
        
        # Result frame
        frame_result = tk.Frame(self.tab_image, bg=self.colors['gray_light'])
        frame_result.pack(fill=tk.BOTH, expand=True, padx=15, pady=5)
        
        # Context frame for AI Analysis (NEW)
        frame_image_context = tk.Frame(frame_result, bg=self.colors['gray_light'])
        frame_image_context.pack(fill=tk.X, pady=(0, 5))
        
        tk.Label(frame_image_context, text="B盻訴 c蘯｣nh/Ghi chﾃｺ thﾃｪm (AI):", 
                 bg=self.colors['gray_light'], font=('Segoe UI', 9, 'italic')).pack(side=tk.LEFT)
        self.entry_image_context = tk.Entry(frame_image_context, font=('Segoe UI', 10), bg=self.colors['white'])
        self.entry_image_context.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10)
        
        button_analyze_image = create_styled_button(
            frame_image_context, text="剥 Phﾃ｢n tﾃｭch AI",
            command=self.analyze_image_text, colors=self.colors
        )
        button_analyze_image.pack(side=tk.RIGHT)

        # Output area
        
        label_text_output = tk.Label(
            frame_result, text="K蘯ｿt qu蘯｣ OCR vﾃ D盻議h:",
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
            frame_result, text="Lﾆｰu K蘯ｿt Qu蘯｣",
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
            messagebox.showerror("L盻擁", str(e))
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
                "L盻擁",
                f"Lo蘯｡i file '{ext}' khﾃｴng ﾄ柁ｰ盻｣c h盻・tr盻｣.\n\n"
                f"Cﾃ｡c ﾄ黛ｻ杵h d蘯｡ng ﾄ柁ｰ盻｣c h盻・tr盻｣:\n"
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
            update_progress(f"､・ﾄ紳ng chu蘯ｩn b盻・d盻議h AI Vision ({pages_per_batch} trang/batch)...", 2)
        else:
            update_progress(f"ﾄ紳ng chu蘯ｩn b盻・d盻議h '{os.path.basename(file_path)}'...", 2)
        
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
                    self.label_file_status.config(text="笨・Hoﾃn t蘯･t!")
                    messagebox.showinfo(
                        "Thﾃnh cﾃｴng",
                        f"File '{os.path.basename(file_path)}' ﾄ妥｣ ﾄ柁ｰ盻｣c d盻議h{method_info}.\n\n"
                        f"ﾄ静｣ lﾆｰu k蘯ｿt qu蘯｣ t蘯｡i:\n{output_file}"
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
                    error_msg = handle_translation_error(e, "D盻議h file")
                    messagebox.showerror("L盻擁", error_msg)
                
                self.after(0, _on_error)
        
        threading.Thread(target=translate_thread, daemon=True).start()


    
    def translate_paragraph(self):
        """Translate paragraph"""
        input_text = self.entry_paragraph_input.get("1.0", tk.END).strip()
        if not input_text:
            messagebox.showwarning("C蘯｣nh bﾃ｡o", "Vui lﾃｲng nh蘯ｭp ﾄ双蘯｡n vﾄハ ﾄ黛ｻ・d盻議h.")
            return
        
        src_lang = self.src_lang_paragraph.get()
        dest_lang = self.dest_lang_paragraph.get()
        
        try:
            LanguageValidator.validate_language_pair(src_lang, dest_lang)
            translated_text = self.translation_service.translate_text(input_text, src_lang, dest_lang)
            self.entry_paragraph_output.delete("1.0", tk.END)
            self.entry_paragraph_output.insert(tk.END, translated_text)
        except Exception as e:
            error_msg = handle_translation_error(e, "D盻議h ﾄ双蘯｡n vﾄハ")
            messagebox.showerror("L盻擁", error_msg)

    def analyze_paragraph(self):
        """Analyze paragraph meaning using AI"""
        input_text = self.entry_paragraph_input.get("1.0", tk.END).strip()
        context = self.entry_paragraph_context.get().strip()
        
        if not input_text:
            messagebox.showwarning("C蘯｣nh bﾃ｡o", "Vui lﾃｲng nh蘯ｭp ﾄ双蘯｡n vﾄハ ﾄ黛ｻ・phﾃ｢n tﾃｭch.")
            return
        
        src_lang = self.src_lang_paragraph.get()
        dest_lang = self.dest_lang_paragraph.get()
        
        # Show waiting status
        self.entry_paragraph_output.delete("1.0", tk.END)
        self.entry_paragraph_output.insert(tk.END, "売 ﾄ紳ng phﾃ｢n tﾃｭch chuyﾃｪn sﾃ｢u... Vui lﾃｲng ﾄ黛ｻ｣i trong giﾃ｢y lﾃ｡t...")
        self.update()

        def run_analysis():
            try:
                from translation_app.core.ai_service import get_ai_service
                ai_service = get_ai_service()
                
                if not ai_service.is_available():
                    self.after(0, lambda: messagebox.showwarning("Yﾃｪu c蘯ｧu c蘯･u hﾃｬnh", "Vui lﾃｲng c蘯･u hﾃｬnh Gemini API Key trong tab 'C蘯･u hﾃｬnh AI' ﾄ黛ｻ・s盻ｭ d盻･ng tﾃｭnh nﾄハg nﾃy."))
                    self.after(0, lambda: self.entry_paragraph_output.delete("1.0", tk.END))
                    return

                result = ai_service.analyze_sentence(input_text, src_lang, dest_lang, context)
                
                if result.get("status") == "success":
                    analysis_text = result["text"]
                    self.after(0, lambda: self._display_analysis(analysis_text))
                else:
                    self.after(0, lambda: messagebox.showerror("L盻擁 AI", f"Khﾃｴng th盻・phﾃ｢n tﾃｭch: {result.get('text')}"))
                    self.after(0, lambda: self.entry_paragraph_output.delete("1.0", tk.END))
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("L盻擁", f"ﾄ静｣ x蘯｣y ra l盻擁 khi phﾃ｢n tﾃｭch: {str(e)}"))
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
            messagebox.showwarning("C蘯｣nh bﾃ｡o", "Vui lﾃｲng nh蘯ｭp tﾃｪn thﾆｰ m盻･c.")
            return
        
        try:
            LanguageValidator.validate_language_pair(src_lang, dest_lang)
            
            def translate_thread():
                try:
                    count = self.email_handler.translate_latest_unread_emails(
                        folder_name, src_lang, dest_lang
                    )
                    self.after(0, lambda: messagebox.showinfo(
                        "Thﾃnh cﾃｴng",
                        f"{count} email m盻嬖 nh蘯･t chﾆｰa ﾄ黛ｻ皇 ﾄ妥｣ ﾄ柁ｰ盻｣c d盻議h vﾃ g盻ｭi thﾃnh cﾃｴng."
                    ))
                except Exception as e:
                    error_msg = handle_translation_error(e, "D盻議h email")
                    self.after(0, lambda: messagebox.showerror("L盻擁", error_msg))
            
            threading.Thread(target=translate_thread, daemon=True).start()
        except Exception as e:
            messagebox.showerror("L盻擁", str(e))
    
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
            self.label_clipboard_status.config(text="Chﾆｰa cﾃｳ 蘯｣nh t盻ｫ clipboard")
            
            self.entry_image_path.delete(0, tk.END)
            self.entry_image_path.insert(0, file_path)
    
    def paste_image_from_clipboard(self):
        """Paste image from clipboard"""
        try:
            # Get image from clipboard
            clipboard_img = ImageGrab.grabclipboard()
            
            if clipboard_img is None:
                messagebox.showwarning(
                    "C蘯｣nh bﾃ｡o",
                    "Clipboard khﾃｴng ch盻ｩa 蘯｣nh.\n\n"
                    "Vui lﾃｲng copy 蘯｣nh vﾃo clipboard trﾆｰ盻嫩 (screenshot ho蘯ｷc copy 蘯｣nh t盻ｫ 盻ｩng d盻･ng khﾃ｡c)."
                )
                return
            
            # Check if it's actually an image
            if not isinstance(clipboard_img, Image.Image):
                messagebox.showwarning(
                    "C蘯｣nh bﾃ｡o",
                    "Clipboard khﾃｴng ch盻ｩa 蘯｣nh h盻｣p l盻・\n\n"
                    "Vui lﾃｲng copy 蘯｣nh vﾃo clipboard trﾆｰ盻嫩."
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
                text=f"ﾄ静｣ paste 蘯｣nh t盻ｫ clipboard ({width}x{height}px)",
                fg=self.colors['gray_dark']
            )
            
            # Create preview
            self._update_image_preview(clipboard_img)
            
            logger.info(f"Pasted image from clipboard: {width}x{height}px")
            
        except Exception as e:
            error_msg = f"L盻擁 khi l蘯･y 蘯｣nh t盻ｫ clipboard: {str(e)}"
            logger.error(error_msg, exc_info=True)
            messagebox.showerror("L盻擁", error_msg)
    
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
            # Lﾆｰu reference ﾄ黛ｻ・trﾃ｡nh garbage collection - Tkinter c蘯ｧn gi盻ｯ reference
            self.preview_photo = ImageTk.PhotoImage(preview_img)
            self._preview_photo_refs.append(self.preview_photo)  # Gi盻ｯ reference thﾃｪm m盻冲 l蘯ｧn n盻ｯa
            
            # Gi盻嬖 h蘯｡n s盻・lﾆｰ盻｣ng references ﾄ黛ｻ・trﾃ｡nh memory leak
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
                text=f"L盻擁 hi盻ハ th盻・preview: {str(e)}"
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
                messagebox.showerror("L盻擁", "Vui lﾃｲng ch盻肱 file 蘯｣nh ho蘯ｷc paste 蘯｣nh t盻ｫ clipboard ﾄ黛ｻ・d盻議h.")
                return
            
            if not os.path.exists(image_path):
                messagebox.showerror("L盻擁", "File 蘯｣nh khﾃｴng t盻渡 t蘯｡i.")
                return
            
            # Read image from file
            try:
                img = Image.open(image_path)
                image_source = image_path
            except Exception as e:
                messagebox.showerror("L盻擁", f"Khﾃｴng th盻・ﾄ黛ｻ皇 file 蘯｣nh: {str(e)}")
                return
        
        # Validate that we have an image
        if img is None:
            messagebox.showerror("L盻擁", "Khﾃｴng th盻・t蘯｣i 蘯｣nh ﾄ黛ｻ・d盻議h.")
            return
        
        if not self.ocr_handler.is_installed():
            messagebox.showerror(
                "L盻擁",
                "Tesseract OCR chﾆｰa ﾄ柁ｰ盻｣c cﾃi ﾄ黛ｺｷt!\n\n"
                "ﾄ雪ｻ・d盻議h ﾄ柁ｰ盻｣c text trong 蘯｣nh, b蘯｡n c蘯ｧn:\n"
                "1. T蘯｣i vﾃ cﾃi ﾄ黛ｺｷt Tesseract OCR t盻ｫ:\n"
                "   https://github.com/UB-Mannheim/tesseract/wiki\n"
                "2. T蘯｣i language pack phﾃｹ h盻｣p t盻ｫ:\n"
                "   https://github.com/tesseract-ocr/tessdata\n"
                "3. ﾄ雪ｺｷt file traineddata vﾃo thﾆｰ m盻･c tessdata c盻ｧa Tesseract"
            )
            return
        
        def translate_thread():
            try:
                # Work with a local copy to avoid closure issues
                working_img = img.copy() if img is not None else None
                if working_img is None:
                    self.after(0, lambda: messagebox.showerror("L盻擁", "Khﾃｴng th盻・t蘯｣i 蘯｣nh ﾄ黛ｻ・d盻議h."))
                    return
                
                # Ensure image is RGB
                if working_img.mode != 'RGB':
                    working_img = working_img.convert('RGB')
                
                # OCR
                self.after(0, lambda: self.text_output.delete("1.0", tk.END))
                self.after(0, lambda: self.text_output.insert(tk.END, "ﾄ紳ng OCR 蘯｣nh...\n"))
                self.after(0, lambda: self.update())
                
                ocr_lang = self.ocr_handler.get_ocr_language(src_lang)
                try:
                    text = self.ocr_handler.extract_text_from_image(working_img, lang=ocr_lang)
                except Exception:
                    text = self.ocr_handler.extract_text_from_image(working_img, lang='eng')
                
                self.last_ocr_text = text # Save for AI analysis
                
                if not text.strip():
                    self.after(0, lambda: self.text_output.delete("1.0", tk.END))
                    self.after(0, lambda: self.text_output.insert(tk.END, "Khﾃｴng tﾃｬm th蘯･y text trong 蘯｣nh."))
                    self.after(0, lambda: messagebox.showwarning("C蘯｣nh bﾃ｡o", "Khﾃｴng tﾃｬm th蘯･y text trong 蘯｣nh."))
                    return
                
                # Display original text
                self.after(0, lambda: self.text_output.delete("1.0", tk.END))
                self.after(0, lambda: self.text_output.insert(tk.END, f"Text g盻祖 ({src_lang}):\n"))
                self.after(0, lambda: self.text_output.insert(tk.END, "-" * 50 + "\n"))
                self.after(0, lambda: self.text_output.insert(tk.END, text + "\n\n"))
                
                # Translate
                self.after(0, lambda: self.text_output.insert(tk.END, "ﾄ紳ng d盻議h...\n"))
                self.after(0, lambda: self.update())
                
                translated_text = self.translation_service.translate_long_text(text, src_lang, dest_lang)
                
                # Display translated text
                self.after(0, lambda: self.text_output.insert(tk.END, f"Text d盻議h ({dest_lang}):\n"))
                self.after(0, lambda: self.text_output.insert(tk.END, "-" * 50 + "\n"))
                self.after(0, lambda: self.text_output.insert(tk.END, translated_text))
                self.after(0, lambda: messagebox.showinfo("Thﾃnh cﾃｴng", "ﾄ静｣ OCR vﾃ d盻議h 蘯｣nh thﾃnh cﾃｴng!"))
            except Exception as e:
                error_msg = handle_translation_error(e, "OCR vﾃ d盻議h 蘯｣nh")
                self.after(0, lambda: self.text_output.delete("1.0", tk.END))
                self.after(0, lambda: self.text_output.insert(tk.END, error_msg))
                self.after(0, lambda: messagebox.showerror("L盻擁", error_msg))
        
        threading.Thread(target=translate_thread, daemon=True).start()
    
    def save_translated_image_text(self):
        """Save translated image text to file"""
        text = self.text_output.get("1.0", tk.END).strip()
        if not text:
            messagebox.showwarning("C蘯｣nh bﾃ｡o", "Khﾃｴng cﾃｳ n盻冓 dung ﾄ黛ｻ・lﾆｰu.")
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
            messagebox.showinfo("Thﾃnh cﾃｴng", f"ﾄ静｣ lﾆｰu k蘯ｿt qu蘯｣ t蘯｡i:\n{output_file}")
        except Exception as e:
            messagebox.showerror("L盻擁", f"Khﾃｴng th盻・lﾆｰu file: {str(e)}")
    
    def _open_ai_settings(self):
        """Open the AI Settings dialog."""
        from translation_app.ui.ai_settings_dialog import AISettingsDialog
        AISettingsDialog(self)
    
    def analyze_image_text(self):
        """Analyze image OCR text meaning using AI"""
        input_text = self.last_ocr_text.strip()
        context = self.entry_image_context.get().strip()
        
        if not input_text:
            messagebox.showwarning("C蘯｣nh bﾃ｡o", "Vui lﾃｲng 'OCR vﾃ D盻議h 蘯｢nh' trﾆｰ盻嫩 khi yﾃｪu c蘯ｧu phﾃ｢n tﾃｭch.")
            return
        
        src_lang = self.src_lang_image.get()
        dest_lang = self.dest_lang_image.get()
        
        # Show waiting status
        self.text_output.delete("1.0", tk.END)
        self.text_output.insert(tk.END, "売 ﾄ紳ng phﾃ｢n tﾃｭch chuyﾃｪn sﾃ｢u n盻冓 dung 蘯｣nh... Vui lﾃｲng ﾄ黛ｻ｣i trong giﾃ｢y lﾃ｡t...")
        self.update()

        def run_analysis():
            try:
                from translation_app.core.ai_service import get_ai_service
                ai_service = get_ai_service()
                
                if not ai_service.is_available():
                    self.after(0, lambda: messagebox.showwarning("Yﾃｪu c蘯ｧu c蘯･u hﾃｬnh", "Vui lﾃｲng c蘯･u hﾃｬnh Gemini API Key trong tab 'C蘯･u hﾃｬnh AI' ﾄ黛ｻ・s盻ｭ d盻･ng tﾃｭnh nﾄハg nﾃy."))
                    self.after(0, lambda: self.text_output.delete("1.0", tk.END))
                    return

                result = ai_service.analyze_sentence(input_text, src_lang, dest_lang, context)
                
                if result.get("status") == "success":
                    analysis_text = result["text"]
                    self.after(0, lambda: self._display_image_analysis(analysis_text))
                else:
                    self.after(0, lambda: messagebox.showerror("L盻擁 AI", f"Khﾃｴng th盻・phﾃ｢n tﾃｭch: {result.get('text')}"))
                    self.after(0, lambda: self.text_output.delete("1.0", tk.END))
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("L盻擁", f"ﾄ静｣ x蘯｣y ra l盻擁 khi phﾃ｢n tﾃｭch: {str(e)}"))
                self.after(0, lambda: self.text_output.delete("1.0", tk.END))

        threading.Thread(target=run_analysis, daemon=True).start()

    def _display_image_analysis(self, text):
        self.text_output.delete("1.0", tk.END)
        self.text_output.insert(tk.END, "=== B蘯｢N PHﾃ・ Tﾃ垢H ﾃ・NGHﾄｨA CHUYﾃ劾 Sﾃ６ (AI) ===\n\n")
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
        guide_dialog.title("庁 G盻｣i ﾃｽ: D盻議h PDF t盻奏 hﾆ｡n v盻嬖 AI Vision")
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
            text="､・B蘯｡n ﾄ疎ng d盻議h file PDF",
            font=('Segoe UI', 14, 'bold'),
            bg=self.colors['white'], fg=self.colors['gray_dark']
        )
        title_label.pack(anchor=tk.W, pady=(0, 10))
        
        # Why AI Vision is better
        why_frame = tk.LabelFrame(
            main_frame,
            text="東 T蘯｡i sao nﾃｪn dﾃｹng AI Vision?",
            font=('Segoe UI', 10, 'bold'),
            bg=self.colors['white'], fg=self.colors['gray_dark'],
            padx=10, pady=10
        )
        why_frame.pack(fill=tk.X, pady=(0, 10))
        
        why_text = """- PDF thuong rat kho dich chinh xac (bang bi vo, mat format, thieu noi dung)
- AI Vision co the ho tro doc noi dung PDF dang anh hoac scan tot hon OCR thuong trong mot so truong hop
- AI hieu ngu canh va co the giup dich thuat ngu ky thuat tot hon trong mot so tinh huong
- Kha nang giu nguyen layout/format PDF chua duoc audit day du. Vui long kiem tra file dau ra truoc khi su dung chinh thuc."""

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
            status_text = "API Gemini ﾄ妥｣ ﾄ柁ｰ盻｣c c蘯･u hﾃｬnh! B蘯｡n cﾃｳ th盻・s盻ｭ d盻･ng AI Vision ngay."
            status_color = "green"
        else:
            status_icon = "[WARN]"
            status_text = "Chﾆｰa c蘯･u hﾃｬnh API Gemini. Lﾃm theo hﾆｰ盻嬾g d蘯ｫn bﾃｪn dﾆｰ盻嬖 ﾄ黛ｻ・b蘯ｯt ﾄ黛ｺｧu."
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
                text="当 Hﾆｰ盻嬾g d蘯ｫn t盻ｫng bﾆｰ盻嫩 (CHI TI蘯ｾT)",
                font=('Segoe UI', 10, 'bold'),
                bg=self.colors['white'], fg=self.colors['gray_dark'],
                padx=10, pady=10
            )
            guide_frame.pack(fill=tk.X, pady=(0, 10))
            
            steps_text = """Bﾆｯ盻咾 1: L蘯･y API Key t盻ｫ Google AI Studio (MI盻Н PHﾃ・
   笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏
   1.1  Nh蘯･n nﾃｺt "迫 M盻・Google AI Studio" bﾃｪn dﾆｰ盻嬖
   1.2  ﾄ斉ハg nh蘯ｭp b蘯ｱng tﾃi kho蘯｣n Google c盻ｧa b蘯｡n
   1.3  Nh蘯･n nﾃｺt "Get API Key" (L蘯･y API Key)
   1.4  Nh蘯･n "Create API key" (T蘯｡o API key m盻嬖)
   1.5  Ch盻肱 m盻冲 d盻ｱ ﾃ｡n b蘯･t k盻ｳ ho蘯ｷc t蘯｡o m盻嬖
   1.6  COPY mﾃ｣ API key (chu盻擁 dﾃi b蘯ｯt ﾄ黛ｺｧu b蘯ｱng "AIza...")

Bﾆｯ盻咾 2: C蘯･u hﾃｬnh trong 盻ｩng d盻･ng
   笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏
   2.1  Quay l蘯｡i 盻ｩng d盻･ng nﾃy
   2.2  Ch盻肱 tab "C蘯･u hﾃｬnh AI" (ho蘯ｷc nh蘯･n nﾃｺt bﾃｪn dﾆｰ盻嬖)
   2.3  Dﾃ｡n API key vﾃo ﾃｴ "Thﾃｪm API Key"
   2.4  Nh蘯･n nﾃｺt "Thﾃｪm Key" ﾄ黛ｻ・lﾆｰu
   2.5  ﾄ静ｳng c盻ｭa s盻・c蘯･u hﾃｬnh

Bﾆｯ盻咾 3: S盻ｭ d盻･ng AI Vision
   笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏笏
   3.1  Quay l蘯｡i tab "D盻議h File"
   3.2  Tﾃｭch ch盻肱 "､・Dﾃｹng AI Vision cho PDF"
   3.3  Ch盻肱 s盻・trang/batch (4 = ti蘯ｿt ki盻㍊ 75% request)
   3.4  Nh蘯･n "D盻議h File ﾄ妥｣ ch盻肱"
   
庁 M蘯ｸO: B蘯｡n cﾃｳ th盻・thﾃｪm NHI盻U API key ﾄ黛ｻ・xoay vﾃｲng khi h蘯ｿt quota!"""
            
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
                btn_row1, text="迫 M盻・Google AI Studio",
                font=('Segoe UI', 10, 'bold'),
                bg="#4285F4", fg="white",
                command=open_ai_studio,
                cursor="hand2",
                padx=15, pady=5
            )
            btn_ai_studio.pack(side=tk.LEFT, padx=(0, 10))
            
            btn_settings = tk.Button(
                btn_row1, text="笞呻ｸ・M盻・C蘯･u hﾃｬnh AI",
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
                btn_row2, text="笨・B蘯ｭt AI Vision vﾃ D盻議h",
                font=('Segoe UI', 11, 'bold'),
                bg="#34A853", fg="white",
                command=use_ai_vision,
                cursor="hand2",
                padx=20, pady=8
            )
            btn_use_ai.pack(side=tk.LEFT, padx=(0, 10))
        
        btn_continue = tk.Button(
            btn_row2, 
            text="Ti蘯ｿp t盻･c d盻議h thﾆｰ盻拵g" if not ai_configured else "D盻議h thﾆｰ盻拵g (khﾃｴng dﾃｹng AI)",
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
        note_text = """投 Lﾆｰu ﾃｽ v盻・gi盻嬖 h蘯｡n API (mi盻・ phﾃｭ):
窶｢ Gemini 2.5 Flash: ~1500 requests/ngﾃy (RPD)
窶｢ G盻冪 4 trang/batch = ti蘯ｿt ki盻㍊ 75% requests
窶｢ Thﾃｪm nhi盻「 API key ﾄ黛ｻ・tﾄハg gi盻嬖 h蘯｡n"""
        
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
            title_row, text="搭 Danh sach cac translation jobs", 
            font=('Segoe UI', 12, 'bold'), bg=self.colors['gray_light'], fg=self.colors['navy']
        ).pack(side=tk.LEFT)
        
        create_styled_button(
            title_row, text="Refresh", command=self._refresh_jobs_list, colors=self.colors
        ).pack(side=tk.RIGHT)

        # Treeview for jobs list
        columns = ("job_id", "job_type", "status", "progress", "created_at")
        self.jobs_tree = ttk.Treeview(main_frame, columns=columns, show="headings", height=8)
        self.jobs_tree.heading("job_id", text="Job ID")
        self.jobs_tree.heading("job_type", text="Loai")
        self.jobs_tree.heading("status", text="Trang thai")
        self.jobs_tree.heading("progress", text="Tien do (%)")
        self.jobs_tree.heading("created_at", text="Ngay tao")
        
        self.jobs_tree.column("job_id", width=180)
        self.jobs_tree.column("job_type", width=80)
        self.jobs_tree.column("status", width=100)
        self.jobs_tree.column("progress", width=100, anchor=tk.CENTER)
        self.jobs_tree.column("created_at", width=160)
        self.jobs_tree.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        # Detail Panel (LabelFrame)
        self.job_detail_frame = tk.LabelFrame(
            main_frame, text="剥 Chi tiet Job duoc chon", 
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
            action_row, text="Open Folder (Thu muc)", command=self._open_selected_job_folder, colors=self.colors
        ).pack(side=tk.LEFT, padx=(0, 10))

        create_styled_button(
            action_row, text="View Errors (Xem cau loi)", command=self._view_selected_job_errors, colors=self.colors
        ).pack(side=tk.LEFT, padx=(0, 10))

        resume_btn = create_styled_button(
            action_row, text="Resume Job (Disabled)", command=self._resume_selected_job, colors=self.colors
        )
        resume_btn.config(state=tk.DISABLED)
        resume_btn.pack(side=tk.LEFT)
        
        tk.Label(
            action_row, text="* Resume duoc danh rieng cho cac phien ban tuong lai.", 
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
                f"Ngon ngu: {job.get('source_lang', 'auto')} -> {job.get('target_lang', 'vi')}  |  Strategy: {job.get('strategy', 'waterfall')}\n"
                f"Tien do: {progress.get('percent', 0.0)}% ({progress.get('completed_segments', 0)} / {progress.get('total_segments', 0)} segments)  |  Loi: {progress.get('failed_segments', 0)} segments\n"
                f"File dang dich: {progress.get('current_file', 'None')}\n"
                f"Sheet/Tab dang dich: {progress.get('current_sheet', 'None')}\n"
                f"Ghi chu: {job.get('notes', '')}"
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
            messagebox.showwarning("Canh bao", "Vui long chon mot Job tu danh sach!")
            return
            
        job_id = selection[0]
        try:
            job_dir = self.job_manager._get_job_dir(job_id)
            if job_dir.exists():
                os.startfile(str(job_dir))
            else:
                messagebox.showerror("Loi", "Thu muc luu tru cua Job nay khong ton tai.")
        except Exception as e:
            messagebox.showerror("Loi", f"Khong the mo thu muc: {str(e)}")

    def _view_selected_job_errors(self):
        selection = self.jobs_tree.selection()
        if not selection:
            messagebox.showwarning("Canh bao", "Vui long chon mot Job tu danh sach!")
            return
            
        job_id = selection[0]
        try:
            failed_items = self.job_manager.load_failed_items(job_id)
            if not failed_items:
                messagebox.showinfo("Thong tin", "Khong co segments bi loi nao duoc ghi nhan cho Job nay.")
                return
                
            # Create sub window
            err_win = tk.Toplevel(self)
            err_win.title(f"笶・Danh sach segments bi loi - Job: {job_id}")
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
            messagebox.showerror("Loi", f"Khong the tai failed items: {str(e)}")

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

        tk.Label(top_row, text="Ngon ngu nguon:", bg=self.colors['gray_light']).pack(side=tk.LEFT)
        self.glossary_filter_src = tk.StringVar(value="auto")
        glossary_filter_src_combo = ttk.Combobox(
            top_row, textvariable=self.glossary_filter_src, 
            values=["auto"] + list(self.display_languages.keys()), state="readonly", width=8
        )
        glossary_filter_src_combo.pack(side=tk.LEFT, padx=5)

        tk.Label(top_row, text="Ngon ngu dich:", bg=self.colors['gray_light']).pack(side=tk.LEFT, padx=(10, 0))
        self.glossary_filter_tgt = tk.StringVar(value="vi")
        glossary_filter_tgt_combo = ttk.Combobox(
            top_row, textvariable=self.glossary_filter_tgt, 
            values=list(self.display_languages.keys()), state="readonly", width=8
        )
        glossary_filter_tgt_combo.pack(side=tk.LEFT, padx=5)

        create_styled_button(
            top_row, text="Loc", command=self._refresh_glossary_list, colors=self.colors
        ).pack(side=tk.LEFT, padx=10)

        create_styled_button(
            top_row, text="Import CSV", command=self._import_glossary_csv, colors=self.colors
        ).pack(side=tk.RIGHT, padx=5)

        create_styled_button(
            top_row, text="Export CSV", command=self._export_glossary_csv, colors=self.colors
        ).pack(side=tk.RIGHT, padx=5)

        # Treeview for glossary
        columns = ("id", "source_term", "target_term", "source_lang", "target_lang", "domain", "note")
        self.glossary_tree = ttk.Treeview(main_frame, columns=columns, show="headings", height=8)
        self.glossary_tree.heading("id", text="ID")
        self.glossary_tree.heading("source_term", text="Tu goc")
        self.glossary_tree.heading("target_term", text="Tu dich")
        self.glossary_tree.heading("source_lang", text="Lang goc")
        self.glossary_tree.heading("target_lang", text="Lang dich")
        self.glossary_tree.heading("domain", text="Domain")
        self.glossary_tree.heading("note", text="Ghi chu")
        
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
            main_frame, text="筐・Them thuat ngu moi", 
            bg=self.colors['gray_light'], fg=self.colors['navy'], font=('Segoe UI', 10, 'bold'),
            padx=10, pady=10
        )
        add_frame.pack(fill=tk.X, pady=(0, 5))

        # Form fields
        f_row1 = tk.Frame(add_frame, bg=self.colors['gray_light'])
        f_row1.pack(fill=tk.X, pady=2)
        tk.Label(f_row1, text="Tu goc *:", width=12, bg=self.colors['gray_light'], anchor=tk.W).pack(side=tk.LEFT)
        self.glossary_add_src_term = tk.StringVar()
        tk.Entry(f_row1, textvariable=self.glossary_add_src_term, bg=self.colors['white'], width=30).pack(side=tk.LEFT, padx=5)

        tk.Label(f_row1, text="Tu dich *:", width=12, bg=self.colors['gray_light'], anchor=tk.W).pack(side=tk.LEFT, padx=(20, 0))
        self.glossary_add_tgt_term = tk.StringVar()
        tk.Entry(f_row1, textvariable=self.glossary_add_tgt_term, bg=self.colors['white'], width=30).pack(side=tk.LEFT, padx=5)

        f_row2 = tk.Frame(add_frame, bg=self.colors['gray_light'])
        f_row2.pack(fill=tk.X, pady=2)
        tk.Label(f_row2, text="Lang goc *:", width=12, bg=self.colors['gray_light'], anchor=tk.W).pack(side=tk.LEFT)
        self.glossary_add_src_lang = tk.StringVar(value="en")
        glossary_add_src_combo = ttk.Combobox(
            f_row2, textvariable=self.glossary_add_src_lang, 
            values=list(self.display_languages.keys()), state="readonly", width=8
        )
        glossary_add_src_combo.pack(side=tk.LEFT, padx=5)

        tk.Label(f_row2, text="Lang dich *:", width=12, bg=self.colors['gray_light'], anchor=tk.W).pack(side=tk.LEFT, padx=(20, 0))
        self.glossary_add_tgt_lang = tk.StringVar(value="vi")
        glossary_add_tgt_combo = ttk.Combobox(
            f_row2, textvariable=self.glossary_add_tgt_lang, 
            values=list(self.display_languages.keys()), state="readonly", width=8
        )
        glossary_add_tgt_combo.pack(side=tk.LEFT, padx=5)

        f_row3 = tk.Frame(add_frame, bg=self.colors['gray_light'])
        f_row3.pack(fill=tk.X, pady=2)
        tk.Label(f_row3, text="Domain:", width=12, bg=self.colors['gray_light'], anchor=tk.W).pack(side=tk.LEFT)
        self.glossary_add_domain = tk.StringVar()
        tk.Entry(f_row3, textvariable=self.glossary_add_domain, bg=self.colors['white'], width=20).pack(side=tk.LEFT, padx=5)

        tk.Label(f_row3, text="Ghi chu:", width=12, bg=self.colors['gray_light'], anchor=tk.W).pack(side=tk.LEFT, padx=(20, 0))
        self.glossary_add_note = tk.StringVar()
        tk.Entry(f_row3, textvariable=self.glossary_add_note, bg=self.colors['white'], width=35).pack(side=tk.LEFT, padx=5)

        # Form buttons row
        btn_form_row = tk.Frame(main_frame, bg=self.colors['gray_light'])
        btn_form_row.pack(fill=tk.X, pady=5)

        create_styled_button(
            btn_form_row, text="筐・Them thuat ngu", command=self._add_glossary_term, colors=self.colors
        ).pack(side=tk.LEFT, padx=(0, 10))

        create_styled_button(
            btn_form_row, text="卵・・Xoa thuat ngu da chon", command=self._delete_glossary_term, colors=self.colors
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

        tk.Label(filter_row, text="Tim kiem:", bg=self.colors['gray_light']).pack(side=tk.LEFT)
        self.tm_search_query = tk.StringVar()
        tk.Entry(filter_row, textvariable=self.tm_search_query, width=25, bg=self.colors['white']).pack(side=tk.LEFT, padx=5)

        tk.Label(filter_row, text="Nguon:", bg=self.colors['gray_light']).pack(side=tk.LEFT, padx=(10, 0))
        self.tm_filter_src = tk.StringVar(value="auto")
        tm_filter_src_combo = ttk.Combobox(
            filter_row, textvariable=self.tm_filter_src, 
            values=["auto"] + list(self.display_languages.keys()), state="readonly", width=8
        )
        tm_filter_src_combo.pack(side=tk.LEFT, padx=5)

        tk.Label(filter_row, text="Dich:", bg=self.colors['gray_light']).pack(side=tk.LEFT, padx=(10, 0))
        self.tm_filter_tgt = tk.StringVar(value="vi")
        tm_filter_tgt_combo = ttk.Combobox(
            filter_row, textvariable=self.tm_filter_tgt, 
            values=list(self.display_languages.keys()), state="readonly", width=8
        )
        tm_filter_tgt_combo.pack(side=tk.LEFT, padx=5)

        create_styled_button(
            filter_row, text="Tim kiem", command=self._refresh_tm_list, colors=self.colors
        ).pack(side=tk.LEFT, padx=10)

        # Treeview for TM
        columns = ("id", "source_lang", "target_lang", "source_text", "translated_text", "provider", "model", "hit_count", "updated_at")
        self.tm_tree = ttk.Treeview(main_frame, columns=columns, show="headings", height=12)
        self.tm_tree.heading("id", text="ID")
        self.tm_tree.heading("source_lang", text="Lang Nguon")
        self.tm_tree.heading("target_lang", text="Lang Dich")
        self.tm_tree.heading("source_text", text="Chuoi goc (Preview)")
        self.tm_tree.heading("translated_text", text="Chuoi dich (Preview)")
        self.tm_tree.heading("provider", text="Provider")
        self.tm_tree.heading("model", text="Model")
        self.tm_tree.heading("hit_count", text="Hits")
        self.tm_tree.heading("updated_at", text="Cap nhat")

        self.tm_tree.column("id", width=40, anchor=tk.CENTER)
        self.tm_tree.column("source_lang", width=70, anchor=tk.CENTER)
        self.tm_tree.column("target_lang", width=70, anchor=tk.CENTER)
        self.tm_tree.column("source_text", width=180)
        self.tm_tree.column("translated_text", width=180)
        self.tm_tree.column("provider", width=80)
        self.tm_tree.column("model", width=90)
        self.tm_tree.column("hit_count", width=40, anchor=tk.CENTER)
        self.tm_tree.column("updated_at", width=100)
        self.tm_tree.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        # Bottom row action
        action_row = tk.Frame(main_frame, bg=self.colors['gray_light'])
        action_row.pack(fill=tk.X)

        create_styled_button(
            action_row, text="Refresh", command=self._refresh_tm_list, colors=self.colors
        ).pack(side=tk.LEFT, padx=(0, 10))

        create_styled_button(
            action_row, text="Xoa segment da chon", command=self._delete_tm_segment, colors=self.colors
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

    def setup_router_tab(self):
        """Setup the Provider Router tab."""
        main_frame = tk.Frame(self.tab_router, bg=self.colors['gray_light'], padx=15, pady=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Status and Actions row
        status_row = tk.Frame(main_frame, bg=self.colors['gray_light'])
        status_row.pack(fill=tk.X, pady=(0, 10))

        self.router_status_label = tk.Label(
            status_row, text="Smart Router Status: CHECKING...", 
            font=('Segoe UI', 11, 'bold'), bg=self.colors['gray_light']
        )
        self.router_status_label.pack(side=tk.LEFT)

        create_styled_button(
            status_row, text="Refresh Snapshot (Health)", command=self._refresh_router_health, colors=self.colors
        ).pack(side=tk.RIGHT, padx=5)

        create_styled_button(
            status_row, text="Reset Cooldowns (Khoi phuc)", command=self._reset_router_cooldowns, colors=self.colors
        ).pack(side=tk.RIGHT, padx=5)

        # Health Snapshot Table (Treeview)
        snapshot_frame = tk.LabelFrame(
            main_frame, text="投 Dynamic Health Snapshot of AI Providers / Models", 
            bg=self.colors['gray_light'], fg=self.colors['navy'], font=('Segoe UI', 10, 'bold'),
            padx=10, pady=10
        )
        snapshot_frame.pack(fill=tk.BOTH, expand=True)

        columns = ("provider", "model", "available", "cooldown", "failures", "last_error", "latency")
        self.router_tree = ttk.Treeview(snapshot_frame, columns=columns, show="headings", height=12)
        self.router_tree.heading("provider", text="Provider")
        self.router_tree.heading("model", text="Model ID")
        self.router_tree.heading("available", text="Kha dung")
        self.router_tree.heading("cooldown", text="Cooldown")
        self.router_tree.heading("failures", text="Loi lien tiep")
        self.router_tree.heading("last_error", text="Last error type / sanitized error")
        self.router_tree.heading("latency", text="Latency (ms)")

        self.router_tree.column("provider", width=120)
        self.router_tree.column("model", width=160)
        self.router_tree.column("available", width=70, anchor=tk.CENTER)
        self.router_tree.column("cooldown", width=110)
        self.router_tree.column("failures", width=80, anchor=tk.CENTER)
        self.router_tree.column("last_error", width=130)
        self.router_tree.column("latency", width=90, anchor=tk.CENTER)
        self.router_tree.pack(fill=tk.BOTH, expand=True)

        # Bottom warning
        tk.Label(
            main_frame, text="* Credentials editing is reserved and managed safely in 'Cau hinh AI' dialog.", 
            font=('Segoe UI', 8, 'italic'), bg=self.colors['gray_light'], fg=self.colors['gray_medium']
        ).pack(anchor=tk.W, pady=(5, 0))

        self._refresh_router_health()

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
        # Update status indicator
        router_enabled = self.config_manager.use_provider_router
        if router_enabled:
            self.router_status_label.config(text="Smart Router Status: 泙 ACTIVE (AI Waterfall Enabled)", fg="green")
        else:
            self.router_status_label.config(text="Smart Router Status: 閥 DISABLED (Using Legacy Strategy)", fg="red")

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
                
                is_available = "泙 Yes" if entry.get("is_available", True) else "閥 No"
                
                cooldown_val = entry.get("cooldown_until", 0.0)
                cooldown = "None"
                if cooldown_val > 0:
                    cooldown_remaining = max(0, int(cooldown_val - time.time()))
                    if cooldown_remaining > 0:
                        cooldown = f"Wait {cooldown_remaining}s"
                        is_available = "泯 Cooldown"
                
                failures = entry.get("consecutive_failures", 0)
                last_error = self._sanitize_router_error_text(entry.get("last_error_type", ""))
                latency = entry.get("last_latency_ms", 0)

                self.router_tree.insert(
                    "", tk.END,
                    values=(provider, model, is_available, cooldown, failures, last_error, latency)
                )
        except Exception as e:
            logger.error(f"Error loading router health snapshot in UI: {e}")

    def _reset_router_cooldowns(self):
        try:
            from translation_app.core.ai_service import get_ai_service
            router = self.translation_service._get_provider_router(get_ai_service())
            router.reset_cooldowns()
            messagebox.showinfo("Thanh cong", "Da khoi phuc toan bo Providers cooldowns thanh cong!")
            self._refresh_router_health()
        except Exception as e:
            messagebox.showerror("Loi", f"Khong the reset cooldowns: {str(e)}")

    def on_closing(self):
        """Handle window closing"""
        logger.info("Application closing")
        self.translation_service.shutdown()
        self.destroy()


