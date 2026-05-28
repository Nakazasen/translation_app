# PDF QA / Regression Report Workflow

## Mục đích

Tài liệu này giải thích khi nào nên dùng `PDF thử nghiệm`, khi nào nên quay về `PDF -> DOCX ổn định`, và cách đọc báo cáo `JSON` / `HTML` sau khi chạy PDF thử nghiệm.

## Chọn đúng chế độ PDF

### 1. PDF -> DOCX ổn định

Nên ưu tiên chế độ này khi:

- Tài liệu quan trọng và cần dễ kiểm tra lại.
- Bạn cần chỉnh sửa thủ công sau khi dịch.
- PDF có nhiều bảng, hình, công thức, nhiều cột, hoặc bố cục phức tạp.

Điểm chính:

- Đây là đường đi ổn định hơn cho công việc hằng ngày.
- Dễ rà soát nội dung trong Word sau khi dịch.
- Phù hợp hơn khi cần người dùng kiểm tra và sửa lại trước khi phát hành.

### 2. PDF thử nghiệm

Chỉ nên dùng khi:

- PDF là PDF text đơn giản.
- Số trang ít và bố cục không quá phức tạp.
- Bạn chấp nhận kiểm tra đầu ra thủ công trước khi dùng chính thức.

Điểm chính:

- Chế độ này cố gắng giữ bố cục tương đối để xuất lại PDF.
- Kết quả có thể hữu ích cho tài liệu đơn giản, nhưng không phải lúc nào cũng phù hợp cho tài liệu phức tạp.
- File quan trọng vẫn cần kiểm tra lại đầu ra trước khi dùng.

## Cách xuất báo cáo PDF thử nghiệm

Sau khi chạy `PDF thử nghiệm`, trong giao diện có thể xuất:

- `Xuất báo cáo JSON`
- `Xuất báo cáo HTML`

Báo cáo này là bản công khai an toàn để hỗ trợ kiểm tra rủi ro. Báo cáo không nên chứa:

- raw source text
- raw translated text
- prompt
- API key
- Authorization header

## Báo cáo dùng để làm gì

Báo cáo `JSON` / `HTML` giúp kiểm tra nhanh:

- số trang đầu vào và đầu ra
- số unit hoặc block đã dịch
- số unit bị bỏ qua
- vùng được bảo vệ
- cảnh báo overflow
- visual diff giữa input và output
- trạng thái `pass` / `warning` / `fail`

## Cách đọc trạng thái

### pass

`pass` nghĩa là bộ metric hiện tại chưa thấy rủi ro lớn.

Điều này không có nghĩa là tài liệu chắc chắn đã đúng hoàn toàn. Nếu tài liệu quan trọng, bạn vẫn nên mở file kết quả và kiểm tra thủ công.

### warning

`warning` nghĩa là có dấu hiệu nên xem lại trước khi dùng.

Ví dụ:

- visual diff khá cao
- có overflow
- có nhiều vùng bị skip
- có warning từ protected regions hoặc threshold

Khi gặp `warning`, nên mở PDF đầu ra, so lại các trang quan trọng, rồi quyết định có dùng tiếp hay quay về `DOCX ổn định`.

### fail

`fail` nghĩa là có rủi ro lớn theo threshold hiện tại.

Ví dụ:

- page count mismatch
- dimension mismatch
- visual drift vượt threshold fail

Khi gặp `fail`, không nên dùng output chính thức nếu chưa kiểm tra và sửa lại.

## Các metric quan trọng

### translated_units

Số translation unit đã được dịch. Với PDF thử nghiệm mới hơn, đây là chỉ số quan trọng hơn dịch theo block rời rạc vì một unit có thể là cả paragraph hoặc caption.

### skipped_units

Số unit bị bỏ qua vì không an toàn để dịch hoặc không phù hợp cho đường đi thử nghiệm.

### skipped_protected_blocks

Số block bị bỏ qua vì thuộc vùng được bảo vệ. Đây thường là công thức, bảng, hình, chart, drawing, hoặc vùng cần giữ nguyên để tránh phá bố cục.

### overflow_units / overflow_blocks

Cho biết có bao nhiêu unit hoặc block bị tràn khi fit text vào bbox.

Nếu các chỉ số này tăng, cần xem lại:

- câu dịch có quá dài không
- bố cục block gốc có quá chặt không
- có nên quay về `DOCX ổn định` không

### protected_regions_by_kind

Cho biết số vùng được bảo vệ theo loại, ví dụ:

- `formula`
- `table`
- `image`
- `chart`
- `caption`
- `scanned_page`

Metric này giúp giải thích vì sao có vùng không được dịch trực tiếp trong PDF thử nghiệm.

### visual_status

Trạng thái tổng quát của phần visual QA:

- `pass`
- `warning`
- `fail`

### visual_mean_diff_ratio

Mức chênh lệch thị giác trung bình giữa input và output. Đây là rough metric, không phải đánh giá ngữ nghĩa.

### visual_max_diff_ratio

Mức chênh lệch thị giác lớn nhất trong các trang đã so sánh. Chỉ số này hữu ích để phát hiện một trang bị drift mạnh dù trung bình toàn tài liệu chưa quá cao.

### warnings / failures

Danh sách cảnh báo hoặc lỗi threshold đã kích hoạt, ví dụ:

- `page_count_mismatch`
- `page_dimension_mismatch`
- `high_mean_visual_diff`
- `high_max_visual_diff`

## Quy trình khuyến nghị cho người dùng

1. Nếu tài liệu quan trọng hoặc bố cục phức tạp, ưu tiên `PDF -> DOCX ổn định`.
2. Chỉ dùng `PDF thử nghiệm` cho PDF text đơn giản khi muốn giữ bố cục tương đối.
3. Sau khi chạy `PDF thử nghiệm`, xuất `JSON` hoặc `HTML` report.
4. Kiểm tra `translated_units`, `skipped_units`, `overflow_units`, `protected_regions_by_kind`, `visual_status`.
5. Nếu `warning` hoặc `fail`, mở file đầu ra để kiểm tra thủ công.
6. Nếu rủi ro cao hoặc tài liệu quan trọng, quay về `DOCX ổn định`.

## Giới hạn cần hiểu rõ

- PDF thử nghiệm không đảm bảo giữ layout tuyệt đối.
- Kết quả không tương đương Google Document Translation.
- Báo cáo không phải chứng nhận enterprise.
- Visual QA là rough QA, không phải semantic layout guarantee.
- File quan trọng phải được kiểm tra thủ công trước khi dùng chính thức.
