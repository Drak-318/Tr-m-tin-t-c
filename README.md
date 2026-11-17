# Trạm Tin Tức

Bộ quét văn bản pháp luật tự động. GitHub quản lý danh sách nguồn tại `danh_sach_nguon.csv`; GitHub Actions tự động thu thập và xử lý website; Google Sheets tiếp tục nhận kết quả và lưu bộ nhớ chống trùng.

## 1. Hệ thống có tự chạy không?

**Có.** Workflow `Tram Tin Tuc - Auto Scanner` được đặt lịch tự động 2 lần mỗi giờ:
- 14:07 giờ Việt Nam.
- 14:37 giờ Việt Nam.

Tương đương 30 phút/lần. GitHub Actions có thể bắt đầu trễ hơn lịch dự kiến do cơ chế xếp hàng của GitHub; đây không phải bộ hẹn giờ chính xác từng giây.

Bạn không cần bấm `Run workflow` mỗi lần. Nút này chỉ dùng khi muốn chạy thử hoặc quét ngay.

## 2. Có quét toàn bộ nguồn không?

**Có. Không giới hạn tổng số nguồn ở 5.**

Mỗi lượt chạy thực hiện:
1. Đọc toàn bộ URL đang bật trong file `danh_sach_nguon.csv` trên GitHub.
2. Đưa toàn bộ nguồn trong CSV vào hàng đợi quét.
3. Chạy tối đa 5 nguồn cùng một thời điểm.
4. Khi một nguồn hoàn tất, hệ thống tự lấy nguồn tiếp theo cho đến khi xử lý hết danh sách.

Ví dụ: sheet có 32 nguồn thì hệ thống vẫn xử lý cả 32 nguồn; chỉ có tối đa 5 nguồn hoạt động cùng lúc. Các nguồn còn lại chờ đến lượt.

Mỗi website mặc định được đọc trang nguồn đã nhập. Việc quét nhiều trang phân trang của cùng một website cần cấu hình riêng trong `source_config.json`; quét toàn bộ nguồn không đồng nghĩa tự động đọc mọi trang con của mọi website.

## 3. Thêm nguồn mới có tự nhận không?

**Có.** Bạn thêm một dòng vào file `danh_sach_nguon.csv` trên GitHub, điền tên, URL, nhóm và để `enabled=true`. Ở lượt chạy theo lịch tiếp theo, hệ thống tự đọc file và nhận nguồn mới.

- Không cần sửa mã Python khi thêm một URL thông thường.
- Không cần bấm Run workflow.
- Muốn tạm ngừng nguồn, đổi `enabled=true` thành `enabled=false`.
- Nguồn mới được quét ở lượt kế tiếp theo lịch tự động; GitHub có thể khởi chạy trễ do hàng đợi.

## 4. Kết quả có tự ghi vào Google Sheets không?

**Có, nếu GitHub Secret và Apps Script API đã được thiết lập đúng.**

Quy trình tự động:
1. Thu thập tiêu đề và đường dẫn từ website.
2. Chuẩn hóa tiêu đề/URL.
3. Nhận diện loại văn bản và số hiệu.
4. Phân loại, chấm điểm và loại dữ liệu trùng.
5. Gửi văn bản mới vào sheet `Văn Bản Mới`.
6. Ghi URL/số hiệu vào `_Bộ Nhớ Văn Bản` để tránh thêm lại.
7. Cập nhật số mục và trạng thái của từng nguồn trong `Nguồn Quét Văn Bản`.

Dữ liệu được gửi theo từng lô tối đa 10 văn bản và thời gian chờ phản hồi tối đa 90 giây để giảm nguy cơ timeout. Trạng thái nguồn vẫn được gửi kể cả khi lượt quét không tìm thấy văn bản mới.

## 5. Bảng Google Sheets có tự định dạng không?

Mã Apps Script API hiện tại đã có hàm `formatBatchRows_` để định dạng các dòng mới được chèn vào `Văn Bản Mới`: font Times New Roman, cỡ chữ, màu nền xen kẽ, căn lề, xuống dòng và đường viền. Apps Script cũng gọi hàm này khi nhận dữ liệu từ GitHub.

**Lưu ý:** Phần định dạng Google Sheets nằm trong mã Apps Script, không nằm trong Python/GitHub Actions. Việc thay đổi màu sắc, độ rộng cột, cố định hàng tiêu đề hoặc định dạng các dòng cũ cần chỉnh và triển khai lại Apps Script. GitHub không thể tự thay đổi giao diện Google Sheets chỉ bằng việc sửa workflow.

## 6. Thiết lập bắt buộc một lần

### A. GitHub Secret

Vào repository → **Settings → Secrets and variables → Actions → New repository secret**:
- Name: `SHEETS_WEB_APP_URL`
- Value: URL Apps Script Web App đang dùng làm API đọc/ghi Google Sheets.

Không đưa URL API vào mã nguồn công khai. URL triển khai cũ từng xuất hiện trong lịch sử repository công khai, vì vậy nên tạo deployment mới và dùng URL mới trong Secret.

### B. Tắt bộ quét Apps Script cũ

GitHub không có quyền tự xóa trigger trong tài khoản Google Apps Script. Nếu trigger cũ `quetNhanhTrungUongTuSheet` còn hoạt động, nó sẽ tiếp tục quét độc lập và có thể ghi trùng với GitHub.

Chỉ cần kiểm tra và xóa trigger cũ một lần:
1. Mở dự án Apps Script gắn với Google Sheets.
2. Chọn mục **Triggers / Trình kích hoạt** (biểu tượng đồng hồ ở thanh bên trái).
3. Tìm trigger có tên hàm `quetNhanhTrungUongTuSheet`.
4. Nhấn dấu ba chấm ở dòng đó → **Delete trigger / Xóa trình kích hoạt**.

Không xóa hàm `doPost`: GitHub vẫn cần hàm này để đọc danh sách nguồn và ghi kết quả vào Sheets. Apps Script sau khi tắt trigger chỉ còn làm API nhận/gửi dữ liệu.

## 7. Chạy thử và theo dõi

Sau khi đã thêm Secret:
1. Mở tab **Actions** trong GitHub.
2. Chọn workflow **Tram Tin Tuc - Auto Scanner**.
3. Chọn **Run workflow** nếu muốn kiểm tra ngay.
4. Mở lượt chạy vừa tạo → **Summary** để xem tổng nguồn, số nguồn xử lý xong, số mục thu thập, số văn bản nhận diện, số văn bản mới ghi và nguồn gặp lỗi.

Sau lần kiểm tra đầu tiên, các lượt sau tự chạy theo lịch 30 phút/lần.

## 8. Cấu hình website đặc biệt

Chế độ `auto` tự nhận diện RSS/Atom hoặc HTML thông thường. Một số website dùng JavaScript, cấu trúc HTML riêng hoặc phân trang đặc biệt có thể cần CSS selector.

Ví dụ cấu hình trong `source_config.json`:

```json
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
      "max_pages": 3,
      "pagination_selector": "a.next"
    }
  }
}
```

Danh sách `sources` hiện để trống vì chưa có bản xuất thực tế của sheet nguồn để kiểm tra từng website. Không nên tự đoán selector: website có cấu trúc đặc biệt mà chưa cấu hình có thể chỉ thu được một phần dữ liệu hoặc không nhận diện được văn bản.

## 9. Giới hạn cần biết

- Lịch GitHub có thể bị trễ do hàng đợi của GitHub.
- Mỗi lượt chạy có giới hạn 25 phút. Nếu danh sách nguồn lớn hoặc nhiều website phản hồi chậm, cần xem Summary để xác định nguồn gây chậm.
- Một nguồn lỗi không làm dừng các nguồn còn lại.
- Mặc định quét trang nguồn đã nhập; muốn đọc thêm trang phân trang phải cấu hình riêng.
- Cơ chế chống trùng hiện tương thích với bộ nhớ số hiệu cũ. Trường hợp nhiều cơ quan dùng cùng số hiệu cần nâng cấp khóa chống trùng theo tổ hợp cơ quan + số hiệu.
- Việc nhận diện phụ thuộc vào tiêu đề và cấu trúc website; không thể cam kết nhận diện đúng 100% mọi trang nếu chưa kiểm tra từng nguồn.

## 10. Chạy tại máy (tùy chọn)

```bash
pip install -r requirements.txt
export SHEETS_WEB_APP_URL="URL_WEB_APP_CUA_BAN"
python quet_vb.py
```


## Quản lý danh sách nguồn bằng GitHub

Danh sách nguồn chính hiện được lưu tại `danh_sach_nguon.csv` ở thư mục gốc repository. File đã được điền 64 URL do người dùng cung cấp.

Các cột:
- `name`: tên nguồn.
- `url`: URL cần quét (bắt buộc).
- `group`: nhóm nguồn, ví dụ `Văn Bản TW` hoặc `Văn Bản địa phương`.
- `enabled`: `true` để quét; `false` để tạm bỏ qua.

Khi CSV có ít nhất một URL hợp lệ, bộ quét dùng danh sách trong GitHub. Nếu CSV chưa có URL, hệ thống tạm dùng danh sách Google Sheets làm phương án dự phòng.

Lưu ý: Google Sheets vẫn được dùng để lưu kết quả và bộ nhớ chống trùng. Vì API Apps Script hiện tại trả danh sách nguồn cùng bộ nhớ trong một phản hồi, lượt chạy vẫn gọi API để lấy bộ nhớ chống trùng; tuy nhiên, khi CSV đã được điền, danh sách CSV mới là danh sách quyết định nguồn nào được quét.

Danh sách GitHub hiện có 64 dòng nguồn từ danh sách bạn gửi. Chưa xóa danh sách cũ trong Google Sheets; nên giữ làm bản đối chiếu dự phòng cho đến khi lượt quét mới hoạt động ổn định.


## 11. Bộ nhớ chống trùng và nguyên tắc ngày tháng

- `data/seen_documents.json` là bộ nhớ bền vững của GitHub, được cập nhật sau khi đồng bộ Google Sheets thành công. `data/scan_history.json` lưu lịch sử tối đa 1.000 lượt quét gần nhất.
- Chống trùng theo URL chuẩn hóa và định danh số hiệu kèm ký hiệu cơ quan ban hành; với nhóm địa phương, bổ sung địa danh nhận diện được từ tiêu đề/tên nguồn. Không dùng số hiệu đơn lẻ làm khóa duy nhất.
- Bộ lọc 60 ngày ưu tiên ngày ban hành ghi rõ trong tiêu đề; nếu không có thì dùng ngày đăng từ RSS/Atom hoặc ngày hiển thị cạnh bài trong danh sách nguồn. Ngày hiệu lực không được dùng thay ngày ban hành.
- Một bài đăng lại có ngày đăng mới nhưng tiêu đề thể hiện ngày ban hành cũ sẽ bị loại. Nếu website không cung cấp ngày ban hành và ngày đăng đáng tin cậy, bộ lọc chưa thể xác định chắc chắn tuổi văn bản; trường hợp này cần cải thiện bộ đọc chi tiết riêng theo từng website.
- Phân nhóm nhận diện gồm: Dự thảo, Văn bản Đảng, Công văn, Văn bản quy phạm pháp luật, Văn bản địa phương và Văn bản khác. Công văn được ưu tiên riêng; không coi công văn là văn bản quy phạm pháp luật.
- Lịch quét tự động vẫn đặt 2 lần/giờ theo cron. Tuy nhiên, GitHub Actions có thể trì hoãn hoặc bỏ lỡ lượt theo lịch; cần theo dõi lịch sử workflow để xác nhận lượt thực tế, không chỉ dựa vào cấu hình cron.
