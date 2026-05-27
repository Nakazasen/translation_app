# -*- coding: utf-8 -*-
"""
Programmatic repair tool for Shift_JIS Mojibake strings in ui/main_window.py.
"""
import os
import sys

def safe_print(msg):
    try:
        print(msg)
    except UnicodeEncodeError:
        try:
            enc = sys.stdout.encoding or 'ascii'
            print(msg.encode(enc, errors='replace').decode(enc))
        except Exception:
            print(msg.encode('ascii', errors='replace').decode('ascii'))

def main():
    ui_path = "ui/main_window.py"
    if not os.path.exists(ui_path):
        print("Error: ui/main_window.py not found!")
        sys.exit(1)
        
    with open(ui_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Repair mapping of actual Mojibake sequences to standard strings
    rep = {
        # General Title and tabs
        'self.title(f"D\\u76fb\\u8b70h t\\u76fb\\uff71 \\uff84\\u9edb\\uff7b\\u51a2g v{__version__}_B\\uff83\\uff79i \\uff84\\u96ea\\uff7b\\uff69c Vinh_Ph\\uff83\\uff72ng ph\\uff83\\uff61t tri\\u76fb\\u30cf h\\u76fb\\u30fbth\\u76fb\\u5275g ch\\u862f\\uff7f t\\u862f\\uff61o")':
        'self.title(f"Dịch tự động v{__version__} - Bùi Đức Vinh - Phòng phát triển hệ thống chế tạo")',
        'self.title(f"D\\u76fb\\u8b70h t\\u76fb\\uff71 \\uff84\\u9edb\\uff7b\\u51a2g v{__version__}_B\\uff83\\uff79i \\uff84\\u96ea\\uff7b\\uff69c Vinh_Ph\\uff83\\uff72ng ph\\uff83\\uff61t tri\\u76fb\\u30cf h\\u76fb\\u30fbth\\u76fb\\u5275g ch\\u862f\\uff7f t\\u862f\\uff61o")':
        'self.title(f"Dịch tự động v{__version__} - Bùi Đức Vinh - Phòng phát triển hệ thống chế tạo")',
        
        # We can also map using exact character strings since we parsed their unicode values
        # Title of main window
        'self.title(f"D\u76fb\u8b70h t\u76fb\uff71 \uff84\u9edb\uff7b\u51a2g v{__version__}_B\uff83\uff79i \uff84\u96ea\uff7b\uff69c Vinh_Ph\uff83\uff72ng ph\uff83\uff61t tri\u76fb\u30cf h\u76fb\u30fbth\u76fb\u5275g ch\u862f\uff7f t\u862f\uff61o")':
        'self.title(f"Dịch tự động v{__version__} - Bùi Đức Vinh - Phòng phát triển hệ thống chế tạo")',

        'L\uff86\uff70u references \uff84\u9edb\uff7b\u30fbtr\uff83\uff61nh garbage collection': 'Lưu references để tránh garbage collection',
        'self.notebook.add(self.tab_ai, text="C\u862f\uff65u h\uff83\uff6cnh AI")': 'self.notebook.add(self.tab_ai, text="Cấu hình AI")',
        
        # Advanced settings panel
        'scrollable_frame, text="\ue05e\uff64\u30fbC\u862f\uff65u h\uff83\uff6cnh D\u76fb\u8b70h thu\u862f\uff6dt & AI",':
        'scrollable_frame, text="⚙️ Cấu hình Dịch thuật & AI",',
        
        'google_frame = tk.LabelFrame(scrollable_frame, text="\ue05e\u5039 Google Translate (D\u76fb\u8b70h v\u76fb\uff65 ch\uff83\uff6dnh)",':
        'google_frame = tk.LabelFrame(scrollable_frame, text="🌐 Google Translate (Dịch chính)",',
        
        'tk.Label(google_frame, text="\uff84\u9759\uff62y l\uff83\uf8f0 d\u76fb\u8b70h v\u76fb\uff65 d\u76fb\u8b70h thu\u862f\uff6dt mi\u76fb\u30fb ph\uff83\uff6d m\u862f\uff77c \uff84\u9edb\uff7b\u6775h c\u76fb\uff67a \u76fb\uff69ng d\u76fb\uff65ng.",':
        'tk.Label(google_frame, text="Đây là dịch vụ dịch thuật miễn phí mặc định của ứng dụng.",',
        
        'tk.Label(google_frame, text="Tr\u862f\uff61ng th\uff83\uff61i: \u7b28\u30fb\uff84\u7d33ng ho\u862f\uff61t \uff84\u9edb\uff7b\u51a2g",':
        'tk.Label(google_frame, text="Trạng thái: 🟢 Hoạt động",',
        
        '            "H\u76fb\u30fbth\u76fb\u5275g s\u862f\uff7d t\u76fb\uff71 \uff84\u9edb\uff7b\u51a2g k\uff83\uff6dch ho\u862f\uff61t Gemini n\u862f\uff7fu Google Translate b\u76fb\u30fbqu\uff83\uff61 t\u862f\uff63i\\n"':
        '            "Hệ thống sẽ tự động kích hoạt Gemini nếu Google Translate bị quá tải\\n"',
        '            "ho\u862f\uff77c tr\u862f\uff63 v\u76fb\u30fbl\u76fb\u64c1. \uff84\u9032\u76fb\u300c n\uff83\uf8f0y gi\uff83\uff7ap qu\uff83\uff61 tr\uff83\uff6cnh d\u76fb\u8b70h kh\uff83\uff74ng b\u76fb\u30fbgi\uff83\uff61n \uff84\u53cc\u862f\uff61n."':
        '            "hoặc trả về lỗi. Tiến trình này giúp quá trình dịch không bị gián đoạn."',
        
        '            gemini_frame, text="\u7b1e\u547b\uff78\u30fbC\u862f\uff65u h\uff83\uff6cnh API Key & Qu\u862f\uff63n l\uff83\uff7d Model Gemini",':
        '            gemini_frame, text="⚙️ Cấu hình API Key & Quản lý Model Gemini",',
        
        '        tk.Label(link_frame, text="\ue05e\u6cca Ch\uff86\uff70a c\uff83\uff73 API Key?",':
        '        tk.Label(link_frame, text="💡 Chưa có API Key?",',
        
        '        strat_frame = tk.LabelFrame(scrollable_frame, text="\ue05e\u5c4f\u30fb\u30fbC\uff83\uf8f0i \uff84\u9edb\uff7a\uff77t m\uff83\uff61y d\u76fb\u8b70h thu\u862f\uff6dt",':
        '        strat_frame = tk.LabelFrame(scrollable_frame, text="🎯 Cài đặt máy dịch thuật",',
        
        '"Gemini AI (Ch\u76fb\u30fbd\uff83\uff79ng AI)"': '"Gemini AI (Chỉ dùng AI)"',
        
        '        tk.Label(strat_frame, text="\ue05e\u5e81 Khuy\u862f\uff7fn ngh\u76fb\u30fbd\uff83\uff79ng: Google Translate -> Gemini AI",':
        '        tk.Label(strat_frame, text="💡 Khuyến nghị dùng: Google Translate -> Gemini AI",',
        
        '        adv_frame = tk.LabelFrame(scrollable_frame, text="\u7b1e\u547b\uff78\u30fbC\uff83\uf8f0i \uff84\u9edb\uff7a\uff77t n\uff83\uff62ng cao (TM / Glossary / Router)",':
        '        adv_frame = tk.LabelFrame(scrollable_frame, text="⚙️ Cài đặt nâng cao (TM / Glossary / Router)",',
        
        '            tm_row, text="B\u862f\uff6dt B\u76fb\u30fbnh\u76fb\u30fbd\u76fb\u8b70h (Translation Memory)",':
        '            tm_row, text="Bật Bộ nhớ dịch (Translation Memory)",',
        
        '        tk.Label(tm_row, text="\uff84\u96ea\uff7b\u30fbd\uff83\uf8f0i t\u76fb\u8a34 thi\u76fb\u30d6 segment l\uff86\uff70u cache:", bg=self.colors[\'gray_light\']).pack(side=tk.LEFT, padx=(20, 5))':
        '        tk.Label(tm_row, text="Độ dài tối thiểu segment lưu cache:", bg=self.colors[\'gray_light\']).pack(side=tk.LEFT, padx=(20, 5))',
        
        '        tk.Label(glossary_row, text="C\u862f\uff65p \uff84\u9edb\uff7b\u30fbth\u76fb\uff71c thi:", bg=self.colors[\'gray_light\']).pack(side=tk.LEFT, padx=(20, 5))':
        '        tk.Label(glossary_row, text="Cấp độ thực thi:", bg=self.colors[\'gray_light\']).pack(side=tk.LEFT, padx=(20, 5))',
        
        '                self.glossary_note_label.config(text="\ue05e\u5e81 Note: \'validate\' \uff84\u67c1\uff70\u76fb\uff63c d\uff83\uf8f0nh ri\uff83\uff6ang cho c\uff83\uff61c t\uff83\uff6dnh n\uff84\u30cfg t\uff86\uff70\uff86\uff61ng lai.", fg="orange")':
        '                self.glossary_note_label.config(text="💡 Note: \'validate\' được dành riêng cho các tính năng tương lai.", fg="orange")',
        
        '                self.glossary_note_label.config(text="\ue05e\u5e81 C\uff83\uf8f0i \uff84\u9edb\uff7a\uff77t th\u76fb\uff71c thi thu\u862f\uff6dt ng\u76fb\uff6f th\uff83\uf8f0nh c\uff83\uff74ng.", fg="green")':
        '                self.glossary_note_label.config(text="💡 Cài đặt thực thi thuật ngữ thành công.", fg="green")',
        
        '            adv_frame, text="\ue05e\u5e81 Thu\u862f\uff6dt ng\u76fb\uff6f gi\uff83\uff7ap chu\u862f\uff69n h\uff83\uff73a c\uff83\uff61c c\u76fb\uff65m t\u76fb\uff6b chuy\uff83\uff6an ng\uff83\uf8f0nh.",':
        '            adv_frame, text="💡 Thuật ngữ giúp chuẩn hóa các cụm từ chuyên ngành.",',
        
        '            router_row, text="B\u862f\uff6dt B\u76fb\u30fb\uff84\u9edb\uff7b\u6775h tuy\u862f\uff7fn th\uff83\uff74ng minh (Provider Router)",':
        '            router_row, text="Bật Bộ định tuyến thông minh (Provider Router)",',
        
        '            save_btn_row, text="\ue05e\u6c88 L\uff86\uff70u c\uff83\uf8f0i \uff84\u9edb\uff7a\uff77t n\uff83\uff62ng cao",':
        '            save_btn_row, text="💾 Lưu cài đặt nâng cao",',
        
        # PDF vision option
        '            text="Ch\uff86\uff70\uff86\uff61ng tr\uff83\uff6cnh t\u76fb\uff71 \uff84\u9edb\uff7b\u51a2g nh\u862f\uff6dn di\u76fb\u333b v\uff83\uf8f0 d\u76fb\u8b70h c\uff83\uff61c lo\u862f\uff61i file:\\nExcel (.xlsx, .xls), Word (.docx, .doc), PowerPoint (.pptx, .ppt), Text (.txt), PDF (.pdf)",':
        '            text="Chương trình tự động nhận diện và dịch các loại file:\\nExcel (.xlsx, .xls), Word (.docx, .doc), PowerPoint (.pptx, .ppt), Text (.txt), PDF (.pdf)",',
        
        '            text="\ue05e\uff64\u30fbD\uff83\uff79ng AI Vision cho PDF (m\u862f\uff61nh nh\u862f\uff65t cho PDF scan, ti\u862f\uff7fng Nh\u862f\uff6dt/Trung)",':
        '            text="🤖 Dùng AI Vision cho PDF (mạnh nhất cho PDF scan, tiếng Nhật/Trung)",',
        
        '            text="    S\u76fb\u30fbtrang/batch:",':
        '            text="    Số trang/batch:",',
        
        '            text="    \ue05e\u5e81 G\u76fb\u51aa nhi\u76fb\u300c trang th\uff83\uf8f0nh 1 \u862f\uff63nh grid \u7aca\u30fb1 request AI (ti\u862f\uff7ft ki\u76fb\u334a RPD)",':
        '            text="    💡 Ghép nhiều trang thành 1 ảnh grid = tiết kiệm 75% requests AI (giảm RPD)",',
        
        '            frame_buttons_para, text="\ue05e\u5265 Ph\uff83\uff62n t\uff83\uff6dch \uff83\uff7d ngh\uff84\uff69a c\uff83\uff62u (AI)",':
        '            frame_buttons_para, text="🔍 Phân tích ý nghĩa câu (AI)",',
        
        '            frame_folder, text="Nh\u862f\uff6dp t\uff83\uff6an th\uff86\uff70 m\u76fb\uff65c trong h\uff83\uff72m th\uff86\uff70 c\u862f\uff67n d\u76fb\u8b70h:",':
        '            frame_folder, text="Nhập tên thư mục trong hòm thư cần dịch:",',
        
        '            text=f"Ch\uff86\uff70\uff86\uff61ng tr\uff83\uff6cnh c\uff83\uff73 th\u76fb\u30fbd\u76fb\u8b70h \uff84\u67c1\uff70\u76fb\uff63c {config.max_emails_to_translate} mail m\u76fb\u5b16 nh\u862f\uff65t ch\uff86\uff70a \uff84\u9edb\uff7b\u7687 trong th\uff86\uff70 m\u76fb\uff65c \uff84\u67c1\uff70\u76fb\uff63c ch\u76fb\u30fb\uff84\u9edb\uff7b\u6775h",':
        '            text=f"Chương trình có thể dịch được {config.max_emails_to_translate} mail mới nhất chứa bộ lọc trong thư mục được cấu hình",',
        
        '            frame_paste_clipboard, text="Paste t\u76fb\uff6b Clipboard (B\u862f\uff65m v\uff83\uf8f0o n\uff83\uff7at \uff84\u9edb\uff7b\u30fbpaste \u862f\uff63nh)",':
        '            frame_paste_clipboard, text="Dán từ Clipboard (Bấm vào nút để dán ảnh)",',
        
        '            text="Ch\uff86\uff70\uff86\uff61ng tr\uff83\uff6cnh s\u862f\uff7d OCR text trong \u862f\uff63nh v\uff83\uf8f0 d\u76fb\u8b70h sang ng\uff83\uff74n ng\u76fb\uff6f \uff84\u59a5\uff6dch",':
        '            text="Chương trình sẽ OCR text trong ảnh và dịch sang ngôn ngữ đích",',
        
        '            frame_button_image, text="OCR v\uff83\uf8f0 D\u76fb\u8b70h \u862f\uff62nh",':
        '            frame_button_image, text="OCR và Dịch ảnh",',
        
        '            frame_image_context, text="\ue05e\u5265 Ph\uff83\uff62n t\uff83\uff6dch AI",':
        '            frame_image_context, text="🔍 Phân tích AI",',
        
        '            frame_result, text="K\u862f\uff7ft qu\u862f\uff63 OCR v\uff83\uf8f0 D\u76fb\u8b70h:",':
        '            frame_result, text="Kết quả OCR và Dịch:",',
        
        '                f"Lo\u862f\uff61i file \'{ext}\' kh\uff83\uff74ng \uff84\u67c1\uff70\u76fb\uff63c h\u76fb\u30fbtr\u76fb\uff63.\\n\\n"':
        '                f"Loại file \'{ext}\' không được hỗ trợ.\\n\\n"',
        '                f"C\uff83\uff61c \uff84\u9edb\uff7b\u6775h d\u862f\uff61ng \uff84\u67c1\uff70\u76fb\uff63c h\u76fb\u30fbtr\u76fb\uff63:\\n"':
        '                f"Các định dạng được hỗ trợ:\\n"',
        
        '            update_progress(f"\ue05e\uff64\u30fb\uff84\u7d33ng chu\u862f\uff69n b\u76fb\u30fbd\u76fb\u8b70h AI Vision ({pages_per_batch} trang/batch)...", 2)':
        '            update_progress(f"⚙️ Đang chuẩn bị dịch AI Vision ({pages_per_batch} trang/batch)...", 2)',
        
        '            update_progress(f"\uff84\u7d33ng chu\u862f\uff69n b\u76fb\u30fbd\u76fb\u8b70h \'{os.path.basename(file_path)}\'...", 2)':
        '            update_progress(f"Đang chuẩn bị dịch \'{os.path.basename(file_path)}\'...", 2)',
        
        '                    self.label_file_status.config(text="\u7b28\u30fbHo\uff83\uf8f0n t\u862f\uff65t!")':
        '                    self.label_file_status.config(text="🟢 Hoàn tất!")',
        
        '                        "Th\uff83\uf8f0nh c\uff83\uff74ng",': '"Thành công",',
        '            messagebox.showwarning("C\u862f\uff63nh b\uff83\uff61o", "Vui l\uff83\uff72ng nh\u862f\uff6dp \uff84\u53cc\u862f\uff61n v\uff84\u30cf \uff84\u9edb\uff7b\u30fbd\u76fb\u8b70h.")':
        '            messagebox.showwarning("Cảnh báo", "Vui lòng nhập đoạn văn để dịch.")',
        
        '            messagebox.showwarning("C\u862f\uff63nh b\uff83\uff61o", "Vui l\uff83\uff72ng nh\u862f\uff6dp \uff84\u53cc\u862f\uff61n v\uff84\u30cf \uff84\u9edb\uff7b\u30fbph\uff83\uff62n t\uff83\uff6dch.")':
        '            messagebox.showwarning("Cảnh báo", "Vui lòng nhập đoạn văn để phân tích.")',
        
        '        self.entry_paragraph_output.insert(tk.END, "\ue05e\u58f2 \uff84\u7d33ng ph\uff83\uff62n t\uff83\uff6dch chuy\uff83\uff6an s\uff83\uff62u... Vui l\uff83\uff72ng \uff84\u9edb\uff7b\uff63i trong gi\uff83\uff62y l\uff83\uff61t...")':
        '        self.entry_paragraph_output.insert(tk.END, "⏳ Đang phân tích chuyên sâu... Vui lòng đợi trong giây lát...")',
        
        '                    self.after(0, lambda: messagebox.showwarning("Y\uff83\uff6au c\u862f\uff67u c\u862f\uff65u h\uff83\uff6cnh", "Vui l\uff83\uff72ng c\u862f\uff65u h\uff83\uff6cnh Gemini API Key trong tab \'C\u862f\uff65u h\uff83\uff6cnh AI\' \uff84\u9edb\uff7b\u30fbs\u76fb\uff6d d\u76fb\uff65ng t\uff83\uff6dnh n\uff84\u30cfg n\uff83\uf8f0y."))':
        '                    self.after(0, lambda: messagebox.showwarning("Yêu cầu cấu hình", "Vui lòng cấu hình Gemini API Key trong tab \'Cấu hình AI\' để sử dụng tính năng này."))',
        
        '                    self.after(0, lambda: messagebox.showerror("L\u76fb\u64c1 AI", f"Kh\uff83\uff74ng th\u76fb\u30fbph\uff83\uff62n t\uff83\uff6dch: {result.get(\'text\')}"))':
        '                    self.after(0, lambda: messagebox.showerror("Lỗi AI", f"Không thể phân tích: {result.get(\'text\')}"))',
        
        '            messagebox.showwarning("C\u862f\uff63nh b\uff83\uff61o", "Vui l\uff83\uff72ng nh\u862f\uff6dp t\uff83\uff6an th\uff86\uff70 m\u76fb\uff65c.")':
        '            messagebox.showwarning("Cảnh báo", "Vui lòng nhập tên thư mục.")',
        
        '                        f"{count} email m\u76fb\u5b16 nh\u862f\uff65t ch\uff86\uff70a \uff84\u9edb\uff7b\u7687 \uff84\u59a5\uff63 \uff84\u67c1\uff70\u76fb\uff63c d\u76fb\u8b70h v\uff83\uf8f0 g\u76fb\uff6di th\uff83\uf8f0nh c\uff83\uff74ng."':
        '                        f"{count} email mới nhất chứa bộ lọc đã được dịch và gửi thành công."',
        
        '                    "Vui l\uff83\uff72ng copy \u862f\uff63nh v\uff83\uf8f0o clipboard tr\uff86\uff70\u76fb\u5ae9 (screenshot ho\u862f\uff77c copy \u862f\uff63nh t\u76fb\uff6b \u76fb\uff69ng d\u76fb\uff65ng kh\uff83\uff61c)."':
        '                    "Vui lòng copy ảnh vào clipboard trước (screenshot hoặc copy ảnh từ ứng dụng khác)."',
        
        '                    "Clipboard kh\uff83\uff74ng ch\u76fb\uff69a \u862f\uff63nh h\u76fb\uff63p l\u76fb\u30fb\\n\\n"':
        '                    "Clipboard không chứa ảnh hợp lệ.\\n\\n"',
        '                    "Vui l\uff83\uff72ng copy \u862f\uff63nh v\uff83\uf8f0o clipboard tr\uff86\uff70\u76fb\u5ae9."':
        '                    "Vui lòng copy ảnh vào clipboard trước."',
        
        '            error_msg = f"L\u76fb\u64c1 khi l\u862f\uff65y \u862f\uff63nh t\u76fb\uff6b clipboard: {str(e)}"':
        '            error_msg = f"Lỗi khi lấy ảnh từ clipboard: {str(e)}"',
        
        '        self._preview_photo_refs: list = []  # L\uff86\uff70u references \uff84\u9edb\uff7b\u30fbtr\uff83\uff61nh garbage collection':
        '        self._preview_photo_refs: list = []  # Lưu references để tránh garbage collection',
        
        '            # L\uff86\uff70u reference \uff84\u9edb\uff7b\u30fbtr\uff83\uff61nh garbage collection - Tkinter c\u862f\uff67n gi\u76fb\uff6f reference':
        '            # Lưu reference để tránh garbage collection - Tkinter cần giữ reference',
        
        '            # Gi\u76fb\u5b16 h\u862f\uff61n s\u76fb\u30fbl\uff86\uff70\u76fb\uff63ng references \uff84\u9edb\uff7b\u30fbtr\uff83\uff61nh memory leak':
        '            # Giới hạn số lượng references để tránh memory leak',
        
        '                text=f"L\u76fb\u64c1 hi\u76fb\u30cf th\u76fb\u30fbpreview: {str(e)}"':
        '                text=f"Lỗi hiển thị preview: {str(e)}"',
        
        '                messagebox.showerror("L\u76fb\u64c1", "Vui l\uff83\uff72ng ch\u76fb\u80b1 file \u862f\uff63nh ho\u862f\uff77t copy \u862f\uff63nh t\u76fb\uff6b clipboard \uff84\u9edb\uff7b\u30fbd\u76fb\u8b70h.")':
        '                messagebox.showerror("Lỗi", "Vui lòng chọn file ảnh hoặc dán ảnh từ clipboard để dịch.")',
        
        '                messagebox.showerror("L\u76fb\u64c1", f"Kh\uff83\uff74ng th\u76fb\u30fb\uff84\u9edb\uff7b\u7687 file \u862f\uff63nh: {str(e)}")':
        '                messagebox.showerror("Lỗi", f"Không thể đọc file ảnh: {str(e)}")',
        
        '            messagebox.showerror("L\u76fb\u64c1", "Kh\uff83\uff74ng th\u76fb\u30fbt\u862f\uff63i \u862f\uff63nh \uff84\u9edb\uff7b\u30fbd\u76fb\u8b70h.")':
        '            messagebox.showerror("Lỗi", "Không thể tải ảnh để dịch.")',
        
        '                "Tesseract OCR ch\uff86\uff70a \uff84\u67c1\uff70\u76fb\uff63c c\uff83\uf8f0i \uff84\u9edb\uff7a\uff77t!\\n\\n"':
        '                "Tesseract OCR chưa được cài đặt!\\n\\n"',
        '                "\\uff84\\u96ea\\uff7b\\u30fbd\\u76fb\\u8b70h \\uff84\\u67c1\\uff70\\u76fb\\uff63c text trong \\u862f\\uff63nh, b\\u862f\\uff61n c\\u862f\\uff67n:\\n"':
        '                "Để dịch được text trong ảnh, bạn cần:\\n"',
        '                "1. T\\u862f\\uff63i v\\uff83\\uf8f0 c\\uff83\\uf8f0i \\uff84\\u9edb\\uff7b\\uff77t Tesseract OCR t\\u76fb\\uff6b:\\n"':
        '                "1. Tải và cài đặt Tesseract OCR từ:\\n"',
        '                "3. \\uff84\\u96ea\\uff7a\\uff77t file traineddata v\\uff83\\uf8f0o th\\uff86\\uff70 m\\u76fb\\uff65c tessdata c\\u76fb\\uff67a Tesseract"':
        '                "3. Đặt file traineddata vào thư mục tessdata của Tesseract"',
        
        '                    self.after(0, lambda: messagebox.showerror("L\u76fb\u64c1", "Kh\uff83\uff74ng th\u76fb\u30fbt\u862f\uff63i \u862f\uff63nh \uff84\u9edb\uff7b\u30fbd\u76fb\u8b70h."))':
        '                    self.after(0, lambda: messagebox.showerror("Lỗi", "Không thể tải ảnh để dịch."))',
        
        '                    self.after(0, lambda: self.text_output.insert(tk.END, "Kh\uff83\uff74ng t\uff83\uff6cm th\u862f\uff65y text trong \u862f\uff63nh."))':
        '                    self.after(0, lambda: self.text_output.insert(tk.END, "Không tìm thấy text trong ảnh."))',
        
        '                    self.after(0, lambda: messagebox.showwarning("C\u862f\uff63nh b\uff83\uff61o", "Kh\uff83\uff74ng t\uff83\uff6cm th\u862f\uff65y text trong \u862f\uff63nh."))':
        '                    self.after(0, lambda: messagebox.showwarning("Cảnh báo", "Không tìm thấy text trong ảnh."))',
        
        '                self.after(0, lambda: messagebox.showinfo("Th\uff83\uf8f0nh c\uff83\uff74ng", "\uff84\u9759\uff63 OCR v\uff83\uf8f0 d\u76fb\u8b70h \u862f\uff63nh th\uff83\uf8f0nh c\uff83\uff74ng!"))':
        '                self.after(0, lambda: messagebox.showinfo("Thành công", "Đã OCR và dịch ảnh thành công!"))',
        
        '                error_msg = handle_translation_error(e, "OCR v\uff83\uf8f0 d\u76fb\u8b70h \u862f\uff63nh")':
        '                error_msg = handle_translation_error(e, "OCR và dịch ảnh")',
        
        '            messagebox.showwarning("C\u862f\uff63nh b\uff83\uff61o", "Kh\uff83\uff74ng c\uff83\uff7a n\u76fb\u5193 dung \uff84\u9edb\uff7b\u30fbl\uff86\uff70u.")':
        '            messagebox.showwarning("Cảnh báo", "Không có nội dung để lưu.")',
        
        '            messagebox.showinfo("Th\uff83\uf8f0nh c\uff83\uff74ng", f"\uff84\u9759\uff63 l\uff86\uff70u k\u862f\uff7ft qu\u862f\uff63 t\u862f\uff61i:\\n{output_file}")':
        '            messagebox.showinfo("Thành công", f"Đã lưu kết quả tại:\\n{output_file}")',
        
        '            messagebox.showerror("L\u76fb\u64c1", f"Kh\uff83\uff74ng th\u76fb\u30fbl\uff86\uff70u file: {str(e)}")':
        '            messagebox.showerror("Lỗi", f"Không thể lưu file: {str(e)}")',
        
        '            messagebox.showwarning("C\u862f\uff63nh b\uff83\uff61o", "Vui l\uff83\uff72ng \'OCR v\uff83\uf8f0 D\u76fb\u8b70h \u862f\uff62nh\' tr\uff86\uff70\u76fb\u5ae9 khi y\uff83\uff6au c\u862f\uff67u ph\uff83\uff62n t\uff83\uff6dch.")':
        '            messagebox.showwarning("Cảnh báo", "Vui lòng \'OCR và Dịch ảnh\' trước khi yêu cầu phân tích.")',
        
        '        self.text_output.insert(tk.END, "\\ue05e\\u58f2 \\uff84\\u7d33ng ph\\uff83\\uff62n t\\uff83\\uff6dch chuy\\uff83\\uff6an s\\uff83\\uff62u n\\u76fb\\u5193 dung \\u862f\\uff63nh... Vui l\\uff83\\uff72ng \\uff84\\u9edb\\uff7b\\uff63i trong gi\\uff83\\uff62y l\\uff83\\uff61t...")':
        '        self.text_output.insert(tk.END, "⏳ Đang phân tích chuyên sâu nội dung ảnh... Vui lòng đợi trong giây lát...")',
        
        '                    self.after(0, lambda: messagebox.showwarning("Y\uff83\uff6au c\u862f\uff67u c\u862f\uff65u h\uff83\uff6cnh", "Vui l\uff83\uff72ng c\u862f\uff65u h\uff83\uff6cnh Gemini API Key trong tab \'C\u862f\uff65u h\uff83\uff6cnh AI\' \uff84\u9edb\uff7b\u30fbs\u76fb\uff6d d\u76fb\uff65ng t\uff83\uff6dnh n\uff84\u30cfg n\uff83\uf8f0y."))':
        '                    self.after(0, lambda: messagebox.showwarning("Yêu cầu cấu hình", "Vui lòng cấu hình Gemini API Key trong tab \'Cấu hình AI\' để sử dụng tính năng này."))',
        
        '                    self.after(0, lambda: messagebox.showerror("L\u76fb\u64c1 AI", f"Kh\uff83\uff74ng th\u76fb\u30fbph\uff83\uff62n t\uff83\uff6dch: {result.get(\'text\')}"))':
        '                    self.after(0, lambda: messagebox.showerror("Lỗi AI", f"Không thể phân tích: {result.get(\'text\')}"))',
        
        '        self.text_output.insert(tk.END, "=== B\u862f\uff62N PH\uff83\u30fb T\uff83\u57a2H \uff83\u30fbNGH\uff84\uff68A CHUY\uff83\u52be S\uff83\uff16 (AI) ===\\n\\n")':
        '        self.text_output.insert(tk.END, "=== BẢN PHÂN TÍCH NGHĨA CHUYÊN SÂU (AI) ===\\n\\n")',
        
        '        guide_dialog.title("\ue05e\u5e81 G\u76fb\uff63i \uff83\uff7d: D\u76fb\u8b70h PDF t\u76fb\u594f h\uff86\uff61n v\u76fb\u5b16 AI Vision")':
        '        guide_dialog.title("💡 Gợi ý: Dịch PDF tốt hơn với AI Vision")',
        
        '            text="\ue05e\uff64\u30fbB\u862f\uff61n \uff84\u758eng d\u76fb\u8b70h file PDF",':
        '            text="🤖 Bạn đang dịch file PDF",',
        
        '            text="\ue05e\u6771 T\u862f\uff61i sao n\uff83\uff6an d\uff83\uff79ng AI Vision?",':
        '            text="📊 Tại sao nên dùng AI Vision?",',
        
        '            status_text = "API Gemini \uff84\u59a5\uff63 \uff84\u67c1\uff70\u76fb\uff63c c\u862f\uff65u h\uff83\uff6cnh! B\u862f\uff61n c\uff83\uff73 th\u76fb\u30fbs\u76fb\uff6d d\u76fb\uff65ng AI Vision ngay."':
        '            status_text = "API Gemini đã được cấu hình! Bạn có thể sử dụng AI Vision ngay."',
        
        '            status_text = "Ch\uff86\uff70a c\u862f\uff65u h\uff83\uff6cnh API Gemini. L\uff83\uf8f0m theo h\uff86\uff70\u76fb\u5b3eg d\u862f\uff6bn b\uff83\uff6an d\uff86\uff70\u76fb\u5b16 \uff84\u9edb\uff7b\u30fbb\u862f\uff6ft \uff84\u9edb\uff7a\uff67u."':
        '            status_text = "Chưa cấu hình API Gemini. Làm theo hướng dẫn bên dưới để bắt đầu."',
        
        '                text="\ue05e\u5f53 H\uff86\uff70\u76fb\u5b3eg d\u862f\uff6bn t\u76fb\uff6bng b\uff86\uff70\u76fb\u5ae9 (CHI TI\u862f\uff7eT)",':
        '                text="📖 Hướng dẫn từng bước (CHI TIẾT)",',
        
        'B\uff86\uff6f\u76fb\u54be 1: L\u862f\uff65y API Key t\u76fb\uff6b Google AI Studio (MI\u76fb\u041d PH\uff83\u30fb':
        'Bước 1: Lấy API Key từ Google AI Studio (MIỄN PHÍ)',
        
        '    1.1  Nh\u862f\uff65n n\uff83\uff7at "\ue05e\u8feb M\u76fb\u30fbGoogle AI Studio" b\uff83\uff6an d\uff86\uff70\u76fb\u5b16':
        '    1.1  Nhấn nút "🔗 Mở Google AI Studio" bên dưới',
        
        '    1.2  \uff84\u6589\u30cfg nh\u862f\uff6dp b\u862f\uff71ng t\uff83\uf8f0i kho\u862f\uff63n Google c\u76fb\uff67a b\u862f\uff61n':
        '    1.2  Đăng nhập bằng tài khoản Google của bạn',
        
        '    1.3  Nh\u862f\uff65n n\uff83\uff7at "Get API Key" (L\u862f\uff65y API Key)':
        '    1.3  Nhấn nút "Get API Key" (Lấy API Key)',
        
        '    1.4  Nh\u862f\uff65n "Create API key" (T\u862f\uff61o API key m\u76fb\u5b16)':
        '    1.4  Nhấn "Create API key" (Tạo API key mới)',
        
        '    1.5  Ch\u76fb\u80b1 m\u76fb\u51b2 d\u76fb\uff71 \uff83\uff61n b\u862f\uff65t k\u76fb\uff73 ho\u862f\uff77c t\u862f\uff61o m\u76fb\u5b16':
        '    1.5  Chọn một dự án bất kỳ hoặc tạo mới',
        
        '    1.6  COPY m\uff83\uff63 API key (chu\u76fb\u64c1 d\uff83\uf8f0i b\u862f\uff6ft \uff84\u9edb\uff7a\uff67u b\u862f\uff71ng "AIza...")':
        '    1.6  COPY mã API key (chuỗi dài bắt đầu bằng "AIza...")',
        
        'B\uff86\uff6f\u76fb\u54be 2: C\u862f\uff65u h\uff83\uff6cnh trong \u76fb\uff69ng d\u76fb\uff65ng':
        'Bước 2: Cấu hình trong ứng dụng',
        
        '    2.1  Quay l\u862f\uff61i \u76fb\uff69ng d\u76fb\uff65ng n\uff83\uf8f0y':
        '    2.1  Quay lại ứng dụng này',
        
        '    2.2  Ch\u76fb\u80b1 tab "C\u862f\uff65u h\uff83\uff6cnh AI" (ho\u862f\uff77c nh\u862f\uff65n n\uff83\uff7at b\uff83\uff6an d\uff86\uff70\u76fb\u5b16)':
        '    2.2  Chọn tab "Cấu hình AI" (hoặc nhấn nút bên dưới)',
        
        '    2.3  D\uff83\uff61n API key v\uff83\uf8f0o \uff83\uff74 "Th\uff83\uff6am API Key"':
        '    2.3  Dán API key vào ô "Thêm API Key"',
        
        '    2.4  Nh\u862f\uff65n n\uff83\uff7at "Th\uff83\uff6am Key" \uff84\u9edb\uff7b\u30fbl\uff86\uff70u':
        '    2.4  Nhấn nút "Thêm Key" để lưu',
        
        '    2.5  \uff84\u9759\uff73ng c\u76fb\uff6da s\u76fb\u30fbc\u862f\uff65u h\uff83\uff6cnh':
        '    2.5  Đóng cửa sổ cấu hình',
        
        'B\uff86\uff6f\u76fb\u54be 3: S\u76fb\uff6d d\u76fb\uff65ng AI Vision':
        'Bước 3: Sử dụng AI Vision',
        
        '    3.2  T\uff83\uff6dch ch\u76fb\u80b1 "\ue05e\uff64\u30fbD\uff83\uff79ng AI Vision cho PDF"':
        '    3.2  Tích chọn "🤖 Dùng AI Vision cho PDF"',
        
        '    3.3  Ch\u76fb\u80b1 s\u76fb\u30fbtrang/batch (4 = ti\u862f\uff7ft ki\u76fb\u334a 75% request)':
        '    3.3  Chọn số trang/batch (4 = tiết kiệm 75% request)',
        
        '    3.4  Nh\u862f\uff65n "D\u76fb\u8b70h File \uff84\u59a5\uff63 ch\u76fb\u80b1"':
        '    3.4  Nhấn "Dịch File đã chọn"',
        
        '\ue05e\u5e81 M\u862f\uff78O: B\u862f\uff61n c\uff83\uff73 th\u76fb\u30fbth\uff83\uff6am NHI\u76fb\x80U API key \uff84\u9edb\uff7b\u30fbxoay v\uff83\uff72ng khi h\u862f\uff7ft quota!"""':
        '💡 MẸO: Bạn có thể thêm NHIỀU API key để xoay vòng khi hết quota!"""',
        
        'btn_row1, text="\ue05e\u8feb M\u76fb\u30fbGoogle AI Studio",':
        'btn_row1, text="🔗 Mở Google AI Studio",',
        
        'btn_row1, text="\u7b1e\u547b\uff78\u30fbM\u76fb\u30fbC\u862f\uff65u h\uff83\uff6cnh AI",':
        'btn_row1, text="⚙️ Mở Cấu hình AI",',
        
        'btn_row2, text="\u7b28\u30fbB\u862f\uff6dt AI Vision v\uff83\uf8f0 D\u76fb\u8b70h",':
        'btn_row2, text="🚀 Bật AI Vision và Dịch",',
        
        'text="Ti\u862f\uff7fp t\u76fb\uff65c d\u76fb\u8b70h th\uff86\uff70\u76fb\u62f5g" if not ai_configured else "D\u76fb\u8b70h th\uff86\uff70\u76fb\u62f5g (kh\uff83\uff74ng d\uff83\uff79ng AI)",':
        'text="Tiếp tục dịch thường" if not ai_configured else "Dịch thường (không dùng AI)",',
        
        'note_text = """\ue05e\u6295 L\uff86\uff70u \uff83\uff7d v\u76fb\u30fbgi\u76fb\u5b16 h\u862f\uff61n API (mi\u76fb\u30fb ph\uff83\uff6d):':
        'note_text = """📊 Lưu ý về giới hạn API (miễn phí):',
        
        '\u7ab6\uff62 Gemini 2.5 Flash: ~1500 requests/ng\uff83\uf8f0y (RPD)':
        '• Gemini 2.5 Flash: ~1500 requests/ngày (RPD)',
        
        '\u7ab6\uff62 Th\uff83\uff6am nhi\u76fb\u300c API key \uff84\u9edb\uff7b\u30fbt\uff84\u30cfg gi\u76fb\u5b16 h\u862f\uff61n"""':
        '• Thêm nhiều API key để tăng giới hạn"""',
        
        '            title_row, text="\ue05e\u642d Danh sach cac translation jobs",':
        '            title_row, text="📋 Danh sách các translation jobs",',
        
        '            main_frame, text="\ue05e\u5265 Chi tiet Job duoc chon",':
        '            main_frame, text="🔍 Chi tiết Job được chọn",',
        
        'err_win.title(f"\u7b36\u30fbDanh sach segments bi loi - Job: {job_id}")':
        'err_win.title(f"⚠️ Danh sách phân đoạn bị lỗi - Job: {job_id}")',
        
        '            main_frame, text="\u7b50\u30fbThem thuat ngu moi",':
        '            main_frame, text="➕ Thêm thuật ngữ mới",',
        
        '            btn_form_row, text="\u7b50\u30fbThem thuat ngu", command=self._add_glossary_term, colors=self.colors':
        '            btn_form_row, text="➕ Thêm thuật ngữ", command=self._add_glossary_term, colors=self.colors',
        
        '            btn_form_row, text="\ue05e\u5375\u30fb\u30fbXoa thuat ngu da chon", command=self._delete_glossary_term, colors=self.colors':
        '            btn_form_row, text="🗑️ Xóa thuật ngữ đã chọn", command=self._delete_glossary_term, colors=self.colors',
        
        '            main_frame, text="\ue05e\u6295 Dynamic Health Snapshot of AI Providers / Models",':
        '            main_frame, text="📊 Bảng thống kê trạng thái AI Providers / Models",',
        
        '            self.router_status_label.config(text="Smart Router Status: \ue05e\u6cd9 ACTIVE (AI Waterfall Enabled)", fg="green")':
        '            self.router_status_label.config(text="Smart Router Status: 🟢 ACTIVE (AI Waterfall Enabled)", fg="green")',
        
        '            self.router_status_label.config(text="Smart Router Status: \ue05e\u95a5 DISABLED (Using Legacy Strategy)", fg="red")':
        '            self.router_status_label.config(text="Smart Router Status: 🔴 DISABLED (Using Legacy Strategy)", fg="red")',
        
        '                is_available = "\ue05e\u6cd9 Yes" if entry.get("is_available", True) else "\ue05e\u95a5 No"':
        '                is_available = "🟢 Yes" if entry.get("is_available", True) else "🔴 No"',
        
        '                        is_available = "\ue05e\u6cef Cooldown"':
        '                        is_available = "🟡 Cooldown"',
    }

    # Apply all replacements
    for old, new in rep.items():
        if old in content:
            content = content.replace(old, new)
            safe_print(f"[OK] Repaired string: {repr(old)[:60]} -> {repr(new)[:60]}")
        else:
            # Try to match raw byte/codepoint representation if literal doesn't match directly
            safe_print(f"[WARN] String not found in file: {repr(old)[:60]}")

    with open(ui_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
        
    safe_print("Done repairing ui/main_window.py.")

if __name__ == "__main__":
    main()
