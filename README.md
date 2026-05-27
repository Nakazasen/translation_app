# 🚀 Ứng dụng Dịch Thuật Tự Động (Auto-Translator)

[![Python Version](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-Copyright-green.svg)](#license)
[![Platform](https://img.shields.io/badge/platform-Windows-lightgrey.svg)](https://www.microsoft.com/windows/)

Ứng dụng dịch thuật đa phương thức mạnh mẽ, hỗ trợ dịch File (Excel, Word, PowerPoint, PDF), Văn bản, Email Outlook và Hình ảnh (OCR). Tích hợp công nghệ **Google Translate** và **Gemini AI** với cơ chế **Waterfall Fallback** thông minh.

---

## ✨ Điểm nổi bật (Highlights)

- ⚡ **Multi-engine**: Kết hợp Google Translate (miễn phí) và Gemini AI (chất lượng cao).
- 🔄 **Waterfall Logic**: Tự động chuyển đổi máy dịch nếu máy chính gặp lỗi hoặc giới hạn.
- 📄 **Preserve Formatting**: Dịch file giữ nguyên định dạng (Styles, Images, Layouts).
- 👁️ **AI Vision**: Sử dụng Prompt đặc biệt để dịch các file PDF "khó nhằn" (PDF Scan, bảng biểu phức tạp).
- 📧 **Outlook Integration**: Dịch trực tiếp email từ Outlook chỉ với một click.
- 🖼️ **Advanced OCR**: Nhận diện chữ viết từ ảnh (Ja, En, Vi, Zh) độ chính xác cao.

---

## 🛠️ Tính năng chi tiết

| Tính năng | Mô tả | Định dạng hỗ trợ |
| :--- | :--- | :--- |
| **Dịch File** | Dịch toàn bộ nội dung file, giữ nguyên cấu trúc. | `.xlsx`, `.docx`, `.pptx`, `.pdf`, `.txt` |
| **Dịch Đoạn Văn** | Dịch nhanh các đoạn văn bản với phân tích AI. | Plain Text |
| **Dịch Email** | Quét và dịch các email mới nhất từ Outlook. | Microsoft Outlook |
| **Dịch Ảnh (OCR)** | Nhận diện và dịch văn bản từ hình ảnh. | `.png`, `.jpg`, `.jpeg`, `.bmp`, `.webp` |
| **Phân tích AI** | Giải thích ý nghĩa, ngữ pháp câu qua Gemini AI. | Text/Images |

---

## 🚀 Hướng dẫn cài đặt

### 1. Cài đặt Python Dependencies
Yêu cầu Python 3.8+.
```bash
pip install -r requirements.txt
```

### 2. Cài đặt Tesseract OCR (Cho tính năng Dịch Ảnh)
- **Tải và cài đặt**: [Tesseract OCR Windows](https://github.com/UB-Mannheim/tesseract/wiki)
- **Lưu ý**: Chương trình sẽ tự động tìm đường dẫn Tesseract trong các thư mục mặc định hoặc thư mục `OCR` cùng cấp với ứng dụng.

---

## 📖 Cách sử dụng

1. **Khởi động**: Chạy file `main.py` hoặc double-click `run_app.bat`.
2. **Cấu hình AI**: Vào tab **Cấu hình AI** để nhập Gemini API Key (nếu muốn sử dụng tính năng nâng cao).
3. **Thao tác**:
   - Chọn tab tương ứng với nhu cầu (File, Văn bản, Email, Ảnh).
   - Chọn ngôn ngữ Nguồn (Source) và Đích (Target).
   - Nhấn nút thực hiện và theo dõi tiến trình qua Progress Bar.

---

## 📁 Cấu trúc thư mục

```text
translation_app/
├── main.py                # Điểm khởi đầu ứng dụng
├── config.py              # Quản lý cấu hình & Hằng số
├── ui/                    # Giao diện người dùng (Tkinter)
│   ├── main_window.py     # Cửa sổ chính & Logic UI
│   ├── theme.py           # Hệ thống màu sắc & Styles
│   └── components.py      # Các widget tùy chỉnh
├── core/                  # Logic nghiệp vụ lõi
│   ├── translator.py      # Dịch vụ dịch thuật (Google/Gemini)
│   ├── file_handlers/     # Xử lý Excel, Word, PPT, PDF
│   └── ocr_handler.py     # Xử lý nhận dạng ảnh
└── utils/                 # Tiện ích dùng chung
    ├── logger.py          # Hệ thống ghi log
    └── validators.py      # Kiểm tra dữ liệu đầu vào
```

---

## 🐛 Troubleshooting

- **Lỗi PDF Scan**: Bật tùy chọn "🤖 Dùng AI Vision" để xử lý bằng AI thay vì engine truyền thống.
- **Portability**: Để dùng portable, hãy giải nén Tesseract vào thư mục `Tesseract-OCR` nằm cùng thư mục gốc của app.
- **Email**: Đảm bảo Microsoft Outlook đang được mở và đã đăng nhập.

---

## 📄 License

Copyright (c) 2026 **Bùi Đức Vinh** - Phòng Phát triển Hệ thống Chế tạo.

*Lưu ý: Ứng dụng này được phát triển phục vụ mục đích học tập và hỗ trợ công việc nội bộ.*

---

## 👤 Tác giả

**Bùi Đức Vinh** - *KTCT cơ 3.2*
Email support: [vinh.bd@kdtvn.local]

---

## 📅 Nhật ký cập nhật (Changelog)

### v6.0.4 (2026-05-27)

- **Đơn giản hóa và Việt hóa giao diện (UI/UX Simplification)**: Toàn bộ tên tab được dịch sang tiếng Việt thống nhất ("Dịch file", "Dịch văn bản", "Dịch email", "Dịch ảnh", "Cấu hình AI", "Công việc", "Thuật ngữ", "Bộ nhớ dịch"). Không còn tab tiếng Anh "Jobs", "Glossary", "Translation Memory", "Provider Router".
- **Hợp nhất Cấu hình AI & Bộ định tuyến (Unified AI Provider Settings)**: Tích hợp bảng trạng thái hoạt động của Smart Router và bảng điều khiển chi tiết từng nhà cung cấp AI (Gemini, ChatAnyWhere, DeepSeek, NVIDIA NIM, OpenAI tùy chỉnh) vào tab "Cấu hình AI".
- **Quản lý Credentials bảo mật**: Cho phép thêm/xóa nhiều API key cho từng provider riêng biệt. API key được lưu trữ và hiển thị an toàn bằng cơ chế che giấu (masking), không in ra log hay hiển thị raw key trên giao diện.
- **Nhãn cảnh báo định dạng an toàn (Safe Format Labels)**: Cập nhật nhãn thông tin hỗ trợ file trung thực, không quảng cáo quá mức: Excel (Hỗ trợ tốt nhất), Word/PPT (Cần kiểm chứng định dạng), PDF (Cần audit layout), tránh các khẳng định tuyệt đối chưa được kiểm chứng.

### v6.0.3 (2026-05-27)

### v6.0.2 (2026-01-12)

- **Sửa lỗi nghiêm trọng (Critical)**: Sửa lỗi crash khi dịch PDF do ứng dụng cố gắng ghi log vào `sys.stderr` bị thiếu trong môi trường đóng gói (PyInstaller onefile/noconsole).
- **Ổn định**: Cải thiện cơ chế `suppress_pdf_warnings` để an toàn hơn với các thư viện bên thứ 3.

### v6.0.1 (2026-01-12)

- **Sửa lỗi PDF (Onefile)**: Khắc phục lỗi không dịch được file PDF sau khi click hộp thoại gợi ý AI Vision khi chạy file .exe đóng gói.
- **Cải tiến Dialog**: Chuyển hộp thoại gợi ý PDF sang dạng modal blocking (`wait_window`), đảm bảo chương trình chờ lựa chọn của người dùng trước khi bắt đầu dịch.
- **Tối ưu hóa COM**: Sử dụng cơ chế Lazy Initialization cho Microsoft Word COM, giúp tăng tính ổn định khi chạy trong môi trường đóng gói (PyInstaller).
- **Đóng gói**: Cập nhật file spec và đóng gói phiên bản mới nhất ver 6.0.1.

## License

Copyright (c) 2025 Bùi Đức Vinh

## Author

Bùi Đức Vinh - KTCT cơ 3.2
