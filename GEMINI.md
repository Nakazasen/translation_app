# 0. Quy tắc Ứng xử (Rules of Engagement)

Trợ lý AI **PHẢI** tuân thủ các quy tắc sau trước khi sinh mã:

1. **Hiểu Kiến trúc**: Luôn tuân thủ mô hình phân lớp hiện tại (UI, Core, Utils, Data). Không viết logic xử lý file trực tiếp trong class UI.
2. **Xử lý Đa luồng (Multi-threading)**: Các tác vụ dịch thuật và OCR **PHẢI** chạy trên background thread để không làm treo UI (sử dụng `ThreadPoolExecutor` hoặc `threading`).
3. **An toàn dữ liệu**: Khi dịch file, luôn tạo bản sao hoặc file mới (`_translated`), không bao giờ ghi đè trực tiếp lên file gốc của người dùng trừ khi có yêu cầu đặc biệt.
4. **Ngôn ngữ**: Giao diện, thông báo và log ưu tiên tiếng Việt. Sử dụng các hằng số ngôn ngữ nếu có.
5. **Cấu hình**: Sử dụng `config.py` và `ai_settings.json` cho mọi thiết lập. Không hardcode đường dẫn hoặc API key.
6. **Cập nhật Requirements**: Nếu thêm thư viện 3rd-party mới, **PHẢI** cập nhật vào file `requirements.txt`.
7. **Cập nhật Tài liệu**: Sau mỗi lần thay đổi hoặc thêm tính năng mới, **PHẢI** cập nhật thông tin tương ứng vào file `README.md`.
8. **Tiêu chuẩn Kỹ thuật**: Mã nguồn tạo ra **PHẢI** tuân thủ PEP 8, Clean Code, và đảm bảo an toàn luồng cho giao diện (Tkinter/PySide).

## 1. Tổng quan Dự án

**Ứng dụng Dịch Thuật Tự Động** là công cụ hỗ trợ dịch đa phương thức: văn bản, file (Office, PDF, TXT), email Outlook và hình ảnh (OCR).

* **Công nghệ chính**: Python, Tkinter (hoặc PySide), Google Translate API, Tesseract OCR.
* **Mục tiêu**: Cung cấp giải pháp dịch thuật nhanh chóng, ổn định và dễ sử dụng cho người dùng văn phòng.

## 2. Cấu trúc Thư mục

* `main.py`: Điểm khởi đầu của ứng dụng.
* `config.py`: Quản lý cấu hình và hằng số.
* `core/`: Chứa logic nghiệp vụ lõi.
  * `translator.py`: Các dịch vụ dịch thuật.
  * `ocr_handler.py`: Xử lý nhận dạng ký tự quang học.
  * `file_handlers/`: Xử lý các định dạng file khác nhau.
* `ui/`: Các thành phần giao diện người dùng.
* `utils/`: Các tiện ích dùng chung (Logger, Error Handler, Validators).
* `data/`: Lưu trữ cài đặt (ví dụ: `ai_settings.json`).

## 3. Mô hình Dữ liệu & Cấu hình

* **Cấu hình hệ thống**: Lưu trong `config.py`.
* **Cài đặt AI/API**: Lưu trong `data/ai_settings.json`.
* **Logs**: Lưu trong thư mục `logs/` với cơ chế rotation để tránh tràn ổ đĩa.

## 4. Hướng dẫn Phát triển

* **Thêm ngôn ngữ mới**: Cập nhật danh sách trong `config.py` và kiểm tra hỗ trợ từ phía translator/OCR.
* **Thêm định dạng file mới**: Tạo handler mới trong `core/file_handlers/` và đăng ký với hệ thống.
* **Xử lý Lỗi**: Luôn sử dụng hệ thống `error_handler.py` để log lỗi chi tiết và hiển thị thông báo thân thiện cho người dùng.
* **Hiệu suất**: Tối ưu hóa việc đọc/ghi file và sử dụng bộ nhớ, đặc biệt là khi xử lý các file Office lớn hoặc ảnh độ phân giải cao.

## 5. Tiêu chuẩn Kỹ thuật (Technical Standards)

### A. Quy tắc viết mã (PEP 8 & Coding Style)

* **Naming**:
  * Class dùng `PascalCase`.
  * Function, Method, Variable dùng `snake_case`.
  * Constant dùng `UPPER_SNAKE_CASE`.
* **Type Hinting**: Luôn sử dụng type hint cho tham số và giá trị trả về.
* **Docstrings**: Sử dụng Google Style docstrings cho tất cả Class và Public Method.

### B. Nguyên lý Thiết kế (Clean Code & DRY)

* **SRP (Single Responsibility Principle)**: Mỗi function/class chỉ làm một việc duy nhất.
* **DRY (Don't Repeat Yourself)**: Đưa các logic dùng chung vào `utils/`.
* **KISS (Keep It Simple, Stupid)**: Ưu tiên giải pháp đơn giản và dễ bảo trì.

### C. Xử lý Lỗi và Logging

* **Logging**: Sử dụng module `logger.py` đã được thiết lập sẵn. Không dùng `print` cho production code.
* **Exception Handling**: Luôn bắt cụ thể các exception và cung cấp context hữu ích trong log.

### D. Phản hồi UI (UI Responsiveness)

* **Background Workers**: Mọi tác vụ tốn thời gian > 0.5s đều phải chạy worker thread.
* **Progress Feedback**: Luôn cập nhật thanh tiến trình (progress bar) hoặc thông báo trạng thái cho người dùng trong quá trình xử lý dài.
