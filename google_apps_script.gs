/**
 * NHẬN KẾT QUẢ LUYỆN ĐỌC TỪ WEB STREAMLIT -> GHI VÀO GOOGLE SHEET
 * Trường Tiểu học Thái Hòa - Web được tạo bởi giáo viên Hoàng Lâm Anh
 *
 * Nhớ đổi SECRET cho trùng WEBHOOK_KEY trong Streamlit Secrets.
 */
const SECRET = "DOI_MA_BI_MAT_O_DAY";   // phải giống WEBHOOK_KEY
const SHEET_NAME = "KetQua_V3";          // tab mới (đã bỏ cột Mã bài, Mã bản ghi) - tự được tạo
const HEADERS = [
  "Thời gian", "Lớp", "Khối", "Họ và tên", "Bài đọc",
  "Tốc độ (tiếng/phút)", "Từ cần rèn", "Điểm /4", "Đánh giá (TT27)", "Số sao",
  "Độ chính xác (%)", "Máy nghe được", "Đọc hiểu", "Câu trả lời đọc hiểu"
];
const COL_CLASS = 2, COL_NAME = 4, COL_LESSON = 5;   // các cột dùng để tìm đúng dòng
const COL_COMP = 13;                                  // cột "Đọc hiểu" (cột "Câu trả lời" nằm ngay sau)

function norm_(v) { return String(v || "").trim().toLowerCase(); }

function doPost(e) {
  const lock = LockService.getScriptLock();
  lock.waitLock(25000);                  // nhiều em nộp cùng lúc vẫn không bị ghi chồng
  try {
    const d = JSON.parse(e.postData.contents);
    if (d.key !== SECRET) return out_("error: sai ma bi mat");

    const ss = SpreadsheetApp.getActiveSpreadsheet();
    let sh = ss.getSheetByName(SHEET_NAME);
    if (!sh) {
      sh = ss.insertSheet(SHEET_NAME);
      sh.appendRow(HEADERS);
      sh.setFrozenRows(1);
      sh.getRange(1, 1, 1, HEADERS.length).setFontWeight("bold").setBackground("#DBEAFE");
    }

    if (d.action === "comprehension") {
      // Cập nhật đọc hiểu vào dòng GẦN NHẤT của đúng lớp + họ tên + bài đọc
      const last = sh.getLastRow();
      if (last < 2) return out_("error: chua co dong nao");
      const rows = sh.getRange(2, 1, last - 1, COL_LESSON).getValues();
      let found = -1;
      for (let i = rows.length - 1; i >= 0; i--) {
        if (norm_(rows[i][COL_CLASS - 1]) === norm_(d.class_name) &&
            norm_(rows[i][COL_NAME - 1]) === norm_(d.student_name) &&
            norm_(rows[i][COL_LESSON - 1]) === norm_(d.lesson_title)) { found = i; break; }
      }
      if (found < 0) return out_("error: khong tim thay dong cua em nay");
      sh.getRange(found + 2, COL_COMP, 1, 2).setValues([[d.comprehension || "", d.comprehension_answer || ""]]);
      return out_("ok");
    }

    // Mặc định: ghi 1 dòng kết quả đọc thành tiếng (giờ Việt Nam do web gửi sang)
    sh.appendRow([
      d.time, d.class_name, Number(d.grade), d.student_name, d.lesson_title,
      d.wpm, d.errors, d.score, d.evaluation, Number(d.stars),
      d.accuracy, d.heard, "", ""
    ]);
    return out_("ok");
  } catch (err) {
    return out_("error: " + err);
  } finally {
    lock.releaseLock();
  }
}

function out_(text) {
  return ContentService.createTextOutput(text);   // web kiểm tra phản hồi bắt đầu bằng "ok"
}
