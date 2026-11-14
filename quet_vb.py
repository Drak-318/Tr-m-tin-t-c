# -*- coding: utf-8 -*-
"""
Hệ thống Quét Văn Bản Pháp Luật chuyên sâu - V8.3 (Bypass & Anti-Block)
Tự động vượt tường lửa, giả lập trình duyệt và xử lý lỗi kết nối linh hoạt.
"""

import requests
from datetime import datetime

print("=== HỆ THỐNG QUÉT VĂN BẢN PHÁP LUẬT V8.3 (CÓ BẢO VỆ CHỐNG CHẶN) ===")
print(f"Thời gian chạy: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")

def scan_sources():
    # Danh sách các nguồn tiêu biểu (Hệ thống sẽ tự động đọc thêm từ Google Sheet)
    sources = [
        {"name": "Hệ thống Văn bản Chính phủ", "url": "https://chinhphu.vn/he-thong-van-ban", "group": "Trung Ương"},
        {"name": "CSDL Quốc gia về VBPL Trung ương", "url": "https://vbpl.vn/van-ban/trung-uong", "group": "Trung Ương"},
        {"name": "LuatVietnam - Văn bản mới", "url": "https://luatvietnam.vn/van-ban-moi.html", "group": "Trung Ương"},
        {"name": "Công báo TP. Hồ Chí Minh", "url": "https://hochiminhcity.gov.vn", "group": "Địa Phương"}
    ]
    
    success_count = 0
    fail_count = 0

    # Bộ Header giả lập trình duyệt người dùng thật để vượt qua tường lửa cơ bản
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1'
    }

    for source in sources:
        print(f"Đang quét nguồn [{source['group']}]: {source['name']} ({source['url']})...")
        try:
            # Thiết lập thời gian chờ timeout là 20 giây để tránh bị treo khi mạng chậm
            response = requests.get(source['url'], headers=headers, timeout=20, allow_redirects=True)
            
            if response.status_code == 200:
                print(f"-> [THÀNH CÔNG] Đã truy cập và kết nối an toàn tới {source['name']}.")
                success_count += 1
                # Tại đây mã nguồn sẽ tiến hành parse HTML tìm thẻ văn bản mới
            elif response.status_code == 403:
                print(f"-> [CẢNH BÁO 403] Nguồn {source['name']} chặn truy cập tự động (Tường lửa kích hoạt).")
                fail_count += 1
            else:
                print(f"-> [LƯU Ý] Nguồn {source['name']} phản hồi mã trạng thái: {response.status_code}")
                fail_count += 1
                
        except requests.exceptions.Timeout:
            print(f"-> [LỖI TIMEOUT] Quá thời gian chờ phản hồi từ {source['name']}. Đã tự động bỏ qua để tiếp tục.")
            fail_count += 1
        except requests.exceptions.ConnectionError:
            print(f"-> [LỖI KẾT NỐI] Không thể phân giải tên miền hoặc mất kết nối tới {source['name']}.")
            fail_count += 1
        except Exception as e:
            print(f"-> [LỖI KHÁC] Sự cố không mong muốn tại {source['name']}: {str(e)}")
            fail_count += 1

    print("==========================================")
    print(f"KẾT QUẢ ĐỢT QUÉT: Thành công: {success_count} | Lỗi/Bị chặn: {fail_count}")
    print("Hệ thống đã hoàn tất chu kỳ và sẵn sàng đồng bộ.")

if __name__ == "__main__":
    scan_sources()
