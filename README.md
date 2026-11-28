# Trạm Tin Tức

Hệ thống tự động thu thập văn bản pháp luật, xác minh ngày, phân loại, chống trùng, lưu bộ nhớ bền vững và đồng bộ kết quả sang Google Sheets.

## 1. Kiến trúc vận hành

**GitHub là trung tâm điều hành duy nhất. Google Sheets chỉ là nơi nhận kết quả.**

| Thành phần | Vai trò |
|---|---|
| `danh_sach_nguon.csv` | Danh sách nguồn chính, được quản lý trên GitHub |
| `priority_sources.json` | Chọn nhóm nguồn cần quét ưu tiên |
| `source_config.json` | Cấu hình riêng cho website, RSS, phân trang và bộ chọn HTML |
| GitHub Actions | Lập lịch, điều phối, kiểm tra, hủy job treo và khởi động lượt quét |
| Python `quet_vb.py` | Thu thập, chuẩn hóa, xác minh ngày, phân loại, chống trùng |
| `data/*.json` | Bộ nhớ chống trùng, hàng đợi xuất Sheets, hồ sơ chưa rõ ngày, lịch sử và lỗi nguồn |
| Apps Script `Code.gs` | API nhận kết quả đã xác thực và ghi vào Google Sheets |
| Google Sheets | Hiển thị kết quả, hồ sơ cần xác minh, trạng thái nguồn và cảnh báo |

Apps Script không lập lịch, không gửi lệnh GitHub, không thu thập website và không quyết định nguồn nào được quét. Mã mới cũng tự vô hiệu hóa trigger thanh tra cũ khi GitHub gửi yêu cầu đồng bộ đầu tiên.

## 2. Lịch chạy và thanh tra trên GitHub

Workflow: `.github/workflows/auto_scan.yml`

GitHub chạy bộ điều phối theo lịch 5 phút/lần. Đây là lượt kiểm tra trạng thái, không phải cứ mỗi lần kiểm tra là gửi một lệnh quét.

- **Quét ưu tiên:** chỉ khởi động khi không có lượt quét nào đang chờ/chạy và đã đủ ít nhất 5 phút kể từ lúc lượt quét trước hoàn thành.
- **Quét các nguồn còn lại:** theo chu kỳ 30 phút tính từ lúc lượt quét toàn bộ trước hoàn thành. Nếu lượt toàn bộ thất bại, hệ thống có thể thử lại sau 5 phút.
- **Chống gửi lệnh trùng:** nếu GitHub đã có job `queued`, `pending` hoặc `in_progress`, bộ điều phối chỉ theo dõi, không gửi lệnh mới.
- **Phục hồi job treo:** job chờ quá 20 phút, quét ưu tiên chạy quá 15 phút hoặc quét toàn bộ chạy quá 50 phút sẽ bị xem xét là quá hạn. GitHub hủy workflow cũ rồi đánh giá lại ở vòng điều phối tiếp theo.
- **Không chạy theo push mã nguồn:** commit và cập nhật code chỉ chạy workflow kiểm thử; không tự khởi động quét dữ liệu.
- **Giới hạn xử lý:** Python dùng tối đa 2 luồng nguồn cho nhóm ưu tiên và 3 luồng cho nhóm còn lại. Bộ điều phối không cho hai lượt quét tự động chồng lên nhau.

Lịch GitHub có thể khởi chạy trễ hơn giờ cron do hàng đợi của nền tảng. Cơ chế trên ưu tiên tính đúng trạng thái và tránh quét chồng lấn hơn là bảo đảm thời điểm chạy chính xác từng giây.

## 3. Danh sách nguồn

GitHub là nơi duy nhất quyết định nguồn được quét.

- Thêm hoặc sửa nguồn trong `danh_sach_nguon.csv`.
- `enabled=true`: cho phép quét; `enabled=false`: tạm ngừng.
- Không xóa nguồn chỉ vì website đang lỗi.
- Các URL khác nhau vẫn được giữ riêng, kể cả khi tên nguồn giống nhau.
- Nguồn phát hiện tự động được lưu trong `data/discovered_sources.json`; chỉ kích hoạt sau khi qua bước kiểm tra.
- Website đặc biệt được cấu hình riêng trong `source_config.json`; không tự đoán selector cho trang có cấu trúc riêng.

Google Sheets không còn là nơi cung cấp danh sách nguồn cho Python. Tab `Nguồn Quét Văn Bản` chỉ nhận cập nhật trạng thái theo URL đối với các dòng đã có, không quyết định lịch hoặc phạm vi quét.

## 4. Quy tắc ngày và bộ lọc 60 ngày

- Ưu tiên ngày ban hành/ngày ký được xác định rõ.
- Chỉ dùng ngày đăng nguồn khi không tìm được ngày ban hành; phải lưu rõ căn cứ ngày là ngày đăng.
- Không dùng ngày quét hoặc ngày đồng bộ làm ngày ban hành.
- Không dùng ngày hiệu lực thay ngày ban hành.
- Nếu không xác định được ngày đáng tin cậy, giữ hồ sơ trong `data/review_queue.json` và chuyển sang Google Sheets để xác minh; không tự loại vì thiếu ngày.
- Hồ sơ chưa rõ ngày được hậu kiểm trang chi tiết theo từng lượt, giữ lại bằng chứng và trạng thái thử lại.
- Chỉ loại theo bộ lọc 60 ngày khi có căn cứ ngày thực tế chứng minh văn bản đã cũ.

## 5. Phân loại và chống trùng

Nhóm phân loại tối thiểu:
- Văn bản Đảng.
- Dự thảo.
- Công văn.
- Văn bản quy phạm pháp luật.
- Văn bản địa phương.
- Văn bản khác.

Công văn được nhận diện riêng, không tự động coi là văn bản quy phạm pháp luật.

Chống trùng:
- Ưu tiên URL chuẩn hóa.
- Định danh văn bản xét số hiệu và cơ quan ban hành.
- Văn bản địa phương bổ sung địa danh/nguồn để phân biệt các tỉnh, thành phố và cơ quan.
- Không dùng số hiệu đơn lẻ làm khóa duy nhất.
- Khi chưa đủ căn cứ xác định trùng, giữ lại để xác minh thay vì xóa nhầm.

Bộ nhớ chính nằm trên GitHub:
- `data/seen_documents.json`: văn bản và URL đã nhận diện.
- `data/review_queue.json`: hồ sơ chưa rõ ngày và bằng chứng xác minh.
- `data/source_retry_queue.json`: nguồn lỗi và lịch thử lại.
- `data/sheets_export_queue.json`: các gói dữ liệu chờ Google Sheets xác nhận.
- `data/scan_history.json`: lịch sử các lượt quét.
- `data/document_relationships.json`: quan hệ/dẫn chiếu văn bản đã phát hiện.

Các tệp bộ nhớ được hợp nhất và lưu lại trên nhánh `main` sau lượt chạy. Hàng đợi xuất Sheets chỉ được xóa sau khi API xác nhận đã nhận các lô dữ liệu.

## 6. Thu thập và chẩn đoán nguồn

Python thu thập trực tiếp từ GitHub runner. Khi website lỗi, hệ thống ghi nhận loại lỗi như HTTP, SSL, timeout, kết nối, parser hoặc lỗi dữ liệu; không đánh đồng website truy cập thành công nhưng không có văn bản với website không truy cập được.

RSS/Atom và nguồn tổng hợp chỉ là phương án bổ sung. Ngày đăng từ RSS/nguồn tổng hợp được lưu làm dữ liệu nguồn, không tự biến thành ngày ban hành. Khi trang chính lỗi SSL hoặc không truy cập được, hệ thống ghi lỗi và đưa nguồn vào hàng đợi thử lại; không dùng Apps Script làm máy chủ thu thập thay thế.

## 7. Đồng bộ Google Sheets

Apps Script hiện ở phiên bản **15.0** và chỉ nhận hành động `save_results`.

- GitHub gửi văn bản và trạng thái nguồn theo từng lô.
- API yêu cầu `SHEETS_API_TOKEN` hợp lệ; thiếu token hoặc sai token thì từ chối ghi.
- Apps Script có khóa chống hai yêu cầu ghi cùng lúc.
- Cơ chế ghi có thể sửa trạng thái ghi dở giữa bảng kết quả và bảng bộ nhớ khi GitHub gửi lại cùng dữ liệu.
- Python giữ gói trong `data/sheets_export_queue.json` nếu đồng bộ thất bại; lượt sau thử gửi lại.
- Bộ nhớ GitHub là nguồn dữ liệu chuẩn. Tab `_Bộ Nhớ Văn Bản` trong Sheets chỉ là lớp chống ghi lặp ở phía nhận và bản phản chiếu phục vụ bảng tính.

## 8. Thiết lập một lần

### GitHub Secrets

Trong repository → **Settings → Secrets and variables → Actions**, cần có:

- `SHEETS_WEB_APP_URL`: URL Web App Apps Script đang gắn với Google Sheets.
- `SHEETS_API_TOKEN`: cùng giá trị với Script Property `SHEETS_API_TOKEN` trong Apps Script.

Không đưa URL triển khai, token hoặc thông tin bí mật vào repository.

### Cập nhật Apps Script

Sau khi GitHub hoàn thiện kiểm thử:

1. Mở dự án Apps Script đang gắn với Google Sheets.
2. Thay toàn bộ nội dung `Code.gs` bằng bản tại `apps_script/Code.gs` trên nhánh `main`.
3. Chọn **Deploy → Manage deployments → Edit → New version → Deploy**.
4. Giữ URL Web App hiện tại nếu cập nhật đúng deployment; bảo đảm GitHub Secret `SHEETS_WEB_APP_URL` trỏ đến URL đó.
5. Trong **Project Settings → Script Properties**, giữ `SHEETS_API_TOKEN` đúng với GitHub Secret.
6. Mở URL Web App bằng trình duyệt; phản hồi GET phải có `"version":"15.0"`.

Không cần tạo `GITHUB_PAT`, không cần cài trigger thanh tra và không cần chạy hàm cài lịch trong Apps Script. Khi GitHub gửi lần đồng bộ đầu tiên sau triển khai, mã mới sẽ thử xóa các trigger thanh tra cũ. Nếu quyền Apps Script không cho phép xóa tự động, trigger cũ chỉ còn gọi hàm tương thích không có chức năng gửi lệnh GitHub.

## 9. Kiểm thử và theo dõi

- Workflow **Scanner Tests** chạy khi có commit: kiểm tra biên dịch Python, JSON, cú pháp JavaScript Apps Script và unit tests.
- Workflow **Tram Tin Tuc - Auto Scanner** là quy trình vận hành dữ liệu.
- Xem **Actions → Tram Tin Tuc - Auto Scanner → Summary** để kiểm tra số nguồn, mục thu thập, văn bản nhận diện, hồ sơ chưa rõ ngày, văn bản mới, nguồn lỗi và gói Sheets còn chờ.
- Mở từng lượt `schedule-watchdog` trong GitHub Actions và xem **Summary** để kiểm tra quyết định điều phối, thời điểm hoàn thành và lý do chờ/gửi lệnh.
- Xem `data/scan_history.json` và `data/source_retry_queue.json` để phân tích kết quả theo lượt và lỗi từng nguồn.

Workflow màu xanh chỉ chứng minh các bước của workflow đạt điều kiện kết thúc. Chất lượng và độ đầy đủ dữ liệu vẫn phải đánh giá bằng số nguồn phản hồi, số mục thu thập, danh sách lỗi, hàng đợi xác minh ngày và xác nhận đồng bộ Sheets.

## 10. Chạy thủ công

Trong GitHub → **Actions** → **Tram Tin Tuc - Auto Scanner** → **Run workflow**:

- `priority`: chạy nhóm nguồn ưu tiên.
- `full`: chạy ưu tiên trước, sau đó chạy các nguồn còn lại.
- `priority_only` và `full_only`: dành cho bộ điều phối GitHub tự động.

Không cần chạy thủ công trong vận hành bình thường.
