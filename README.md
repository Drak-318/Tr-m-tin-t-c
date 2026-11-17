# Trạm Tin Tức

Bộ quét văn bản pháp luật tự động. GitHub Actions là bộ máy thu thập và xử lý duy nhất; Google Sheets chỉ cung cấp danh sách nguồn, lưu bộ nhớ và nhận kết quả.

## Cách hoạt động

1. GitHub Actions chạy theo lịch 30 phút (phút 07 và 37 mỗi giờ) hoặc chạy thủ công.
2. Python gọi Apps Script Web App bằng action get_sources để lấy toàn bộ nguồn có URL trong sheet Nguồn Quét Văn Bản.
3. Mỗi nguồn được quét bằng chế độ tự nhận diện RSS/XML hoặc HTML; có thể ghi đè cấu hình riêng trong source_config.json.
4. Kết quả được chuẩn hóa, phân loại, chống trùng và gửi về bằng action save_results.
5. Trạng thái nguồn được gửi ở mọi lượt chạy, kể cả khi không có văn bản mới.

## Giữ nguyên cấu trúc Google Sheets

Mã Python giữ nguyên hai action hiện có:
- get_sources: nhận sources, existingLinks, existingNumbers.
- save_results: gửi new_docs và source_status.

Các trường trạng thái hiện có trong sheet Nguồn Quét Văn Bản vẫn được cập nhật theo row, count, status. Sheet Văn Bản Mới và _Bộ Nhớ Văn Bản không cần đổi cấu trúc.

GitHub không dùng Apps Script để quét website. Apps Script chỉ đóng vai trò API đọc/ghi Google Sheets.

## Cấu hình GitHub

Trước khi chạy, bắt buộc vào Settings > Secrets and variables > Actions > New repository secret:
- Name: SHEETS_WEB_APP_URL
- Value: URL Apps Script Web App dùng làm API đọc/ghi Google Sheets.

Không đặt URL này trực tiếp trong mã nguồn. Vì URL Web App cũ từng xuất hiện trong repository công khai và Apps Script hiện xử lý cả thao tác ghi dữ liệu, nên nên tạo một deployment Web App mới, kiểm tra quyền truy cập phù hợp, rồi lưu URL mới vào secret. Không tiếp tục dùng URL cũ đã bị công khai.

## Cấu hình nguồn đặc biệt

Sửa source_config.json. Khóa nguồn có thể là URL (ưu tiên) hoặc tên nguồn chính xác giống cột A của sheet.

Ví dụ:

    {
      "defaults": {
        "mode": "auto",
        "max_pages": 1,
        "max_items": 200
      },
      "sources": {
        "https://example.gov.vn/van-ban": {
          "mode": "html",
          "item_selector": ".document-item",
          "title_selector": ".document-title",
          "link_selector": "a",
          "date_selector": "time",
          "max_pages": 3,
          "pagination_selector": "a.next"
        },
        "Tên nguồn RSS": {
          "mode": "rss",
          "max_items": 300
        }
      }
    }

Các trường cấu hình:
- mode: auto, rss, hoặc html.
- item_selector: CSS selector cho một mục văn bản.
- title_selector: CSS selector lấy tiêu đề bên trong mục.
- link_selector: CSS selector lấy liên kết bên trong mục.
- max_pages: số trang tối đa, mặc định 1.
- pagination_selector: CSS selector của liên kết trang tiếp theo.
- follow_pagination: cho phép tìm liên kết Tiếp/Next nếu không khai báo selector.
- max_items: số mục tối đa lấy từ một nguồn.

Chỉ cấu hình max_pages lớn hơn 1 cho nguồn đã kiểm tra cấu trúc phân trang. Không nên bật quét sâu mặc định cho mọi website.

## Chạy thử tại máy

    pip install -r requirements.txt
    export SHEETS_WEB_APP_URL="URL_WEB_APP_CUA_BAN"
    python quet_vb.py

## Giới hạn và lưu ý

- Mỗi lượt chạy có giới hạn 25 phút; nếu tổng nguồn vượt khả năng xử lý, cần xem GitHub Actions Summary để xác định nguồn chậm.
- Tự nhận diện RSS/HTML là lớp tổng quát, không bảo đảm hiểu chính xác mọi website. Nguồn có cấu trúc riêng cần selector trong source_config.json.
- Không tắt xác minh TLS.
- Một nguồn lỗi không làm dừng các nguồn còn lại; trạng thái và lỗi được ghi trong log GitHub.
- Bộ nhớ số hiệu hiện vẫn dùng existingNumbers từ Apps Script để tương thích dữ liệu cũ. Nếu nhiều cơ quan cùng dùng một số hiệu, cần nâng cấp schema bộ nhớ ở giai đoạn riêng để chống trùng theo tổ hợp cơ quan + số hiệu.
