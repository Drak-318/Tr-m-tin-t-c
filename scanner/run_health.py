"""Run-level health gates: a job is successful only when its work is actually complete."""

def validate_run_outcome(total_sources, failed_sources, pending_exports, sheets_configured):
    """Return blocking errors instead of silently reporting incomplete scans as success."""
    errors = []
    total = max(0, int(total_sources or 0))
    failed = max(0, int(failed_sources or 0))
    pending = max(0, int(pending_exports or 0))

    if total == 0:
        errors.append("Không có nguồn nào được xử lý.")
    elif failed >= total:
        errors.append(f"Tất cả {total} nguồn đều lỗi; không có nguồn truy cập thành công.")

    if pending and not sheets_configured:
        errors.append(
            f"Còn {pending} gói dữ liệu chờ đồng bộ nhưng chưa cấu hình Apps Script URL."
        )
    elif pending:
        errors.append(
            f"Còn {pending} gói dữ liệu chưa được Google Sheets xác nhận; hàng đợi được giữ lại."
        )

    return errors
