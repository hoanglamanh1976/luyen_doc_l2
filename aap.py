import asyncio
import difflib
import hashlib
import io
import re
import unicodedata
import wave
from datetime import datetime, timedelta, timezone

import numpy as np
import requests
import streamlit as st
import streamlit.components.v1 as components

# =====================================================================
# 1. CẤU HÌNH
# =====================================================================
SCHOOL = "TRƯỜNG TIỂU HỌC THÁI HÒA"
LOCATION = "xã Thái Hòa, tỉnh Tuyên Quang"
VN_TZ = timezone(timedelta(hours=7))   # giờ Việt Nam (máy chủ web chạy giờ UTC nên phải đổi)
AUTHOR = "Hoàng Lâm Anh"
MIN_SECONDS = 3.0                    # ghi âm ngắn hơn mức này -> yêu cầu ghi lại

# ---------------------------------------------------------------------
# MỨC CHẤM THEO TỪNG KHỐI (thầy/cô có thể chỉnh các con số ở đây)
#   full_acc   : đọc đúng từ tỉ lệ này trở lên thì được trọn điểm phần "đọc đúng"
#   near_credit: điểm cho tiếng "gần đúng" (máy nghe lệch dấu/âm)   - càng cao càng dễ
#   near_ratio : độ giống tối thiểu để tính là "gần đúng"           - càng thấp càng dễ
#   w_acc/w_speed: tỉ trọng điểm đọc đúng / tốc độ (cộng lại = 1)
#   t_th / h_th: ngưỡng đọc đúng để đạt mức T (Hoàn thành tốt) / H (Hoàn thành)
#   t_speed    : muốn đạt T thì tốc độ phải đạt tối thiểu bằng ... % mức chuẩn (lớp 1-2 không yêu cầu)
#   comp_cov   : tỉ lệ từ khóa cần nói đúng trong câu trả lời đọc hiểu
#   min_rec    : máy nghe được dưới tỉ lệ này của bài thì không chấm, yêu cầu ghi lại
# ---------------------------------------------------------------------
PROFILES = {
    "1": dict(name="Lớp 1", emoji="🐣", accent="#F97316", soft="#FFEDD5", level="Mức 1 · Nhẹ nhàng, khích lệ",
              full_acc=0.80, near_credit=0.90, near_ratio=0.65, w_acc=0.90, w_speed=0.10,
              t_th=0.70, h_th=0.40, t_speed=0.0, comp_cov=0.50, min_rec=0.15, fs=1),
    "2": dict(name="Lớp 2", emoji="🐥", accent="#0EA5E9", soft="#E0F2FE", level="Mức 2 · Tăng độ chính xác",
              full_acc=0.90, near_credit=0.75, near_ratio=0.75, w_acc=0.85, w_speed=0.15,
              t_th=0.80, h_th=0.50, t_speed=0.0, comp_cov=0.60, min_rec=0.20, fs=0),
    "3": dict(name="Lớp 3", emoji="🦊", accent="#10B981", soft="#D1FAE5", level="Mức 3 · Đọc đúng và trôi chảy",
              full_acc=0.92, near_credit=0.70, near_ratio=0.78, w_acc=0.80, w_speed=0.20,
              t_th=0.85, h_th=0.55, t_speed=0.60, comp_cov=0.60, min_rec=0.20, fs=0),
    "4": dict(name="Lớp 4", emoji="🦉", accent="#8B5CF6", soft="#EDE9FE", level="Mức 4 · Chuẩn xác, đúng tốc độ",
              full_acc=0.94, near_credit=0.65, near_ratio=0.80, w_acc=0.75, w_speed=0.25,
              t_th=0.88, h_th=0.60, t_speed=0.70, comp_cov=0.70, min_rec=0.25, fs=0),
    "5": dict(name="Lớp 5", emoji="🦅", accent="#E11D48", soft="#FFE4E6", level="Mức 5 · Nghiêm ngặt nhất",
              full_acc=0.95, near_credit=0.60, near_ratio=0.82, w_acc=0.70, w_speed=0.30,
              t_th=0.90, h_th=0.65, t_speed=0.75, comp_cov=0.75, min_rec=0.25, fs=0),
}

# Sao thưởng 1-5 theo điểm đọc /4 (làm tròn 0,5)
STAR_INFO = {
    5: ("Xuất sắc! Giọng đọc vàng", "Em đọc rất đúng, rõ ràng và trôi chảy. Cô khen em!"),
    4: ("Rất giỏi!", "Em đọc rất tốt, chỉ còn vài chỗ nhỏ để hoàn hảo hơn."),
    3: ("Giỏi lắm!", "Em đọc khá tốt rồi, cố gắng thêm một chút là được nhiều sao hơn."),
    2: ("Em đang tiến bộ!", "Em đã đọc được nhiều tiếng, luyện thêm để đọc chuẩn hơn nhé."),
    1: ("Cố gắng lên nào!", "Em đã dũng cảm đọc to bài, nghe đọc mẫu rồi đọc lại để được thêm sao nhé."),
}
RANKS = [(0, "Mầm non chăm chỉ", "🌱"), (10, "Chú chim hót hay", "🐦"), (25, "Ngôi sao đang sáng", "🌟"),
         (50, "Siêu sao đọc giỏi", "🚀"), (100, "Vua đọc sách", "👑")]

VOICES = {"Cô Hoài My (giọng nữ, tiếng phổ thông chuẩn)": "vi-VN-HoaiMyNeural",
          "Thầy Nam Minh (giọng nam, tiếng phổ thông chuẩn)": "vi-VN-NamMinhNeural"}
SPEEDS = {"Đọc chậm (cho em tập đọc)": "-20%", "Đọc vừa": "-8%"}

st.set_page_config(page_title="Luyện đọc Tiếng Việt - Tiểu học Thái Hòa", page_icon="✏️", layout="centered")

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Nunito:wght@500;700;800&display=swap');
    html, body, [class*="css"] { translate: no !important; font-family: 'Nunito', 'Segoe UI', sans-serif; }
    .skiptranslate { display: none !important; }
    .block-container { padding-top: 1.2rem; max-width: 880px; }

    .hero { background: linear-gradient(135deg, #1E3A8A 0%, #6D28D9 55%, #DB2777 100%); color: #fff;
        border-radius: 22px; padding: 22px 24px; text-align: center; margin-bottom: 14px;
        box-shadow: 0 10px 28px rgba(79,70,229,.28); position: relative; overflow: hidden; }
    .hero::after { content: "✏️ 📖 ⭐ 🎈 📚"; position: absolute; right: 14px; bottom: 6px; opacity: .22; font-size: 26px; letter-spacing: 6px; }
    .hero .school { font-size: 23px; letter-spacing: 3px; font-weight: 800; opacity: .98; text-shadow: 0 2px 6px rgba(0,0,0,.25); }
    .hero h1 { margin: 6px 0 4px; font-size: 30px; font-weight: 800; color: #fff; padding: 0; }
    .hero p { margin: 0; opacity: .92; font-size: 15px; }

    .steps { display: flex; gap: 8px; margin: 6px 0 14px; flex-wrap: wrap; }
    .steps div { flex: 1; min-width: 150px; background: #fff; border: 2px solid #E2E8F0; border-radius: 14px;
        padding: 8px 12px; font-weight: 700; font-size: 14px; color: #334155; }
    .steps b { display: inline-block; background: #6D28D9; color: #fff; border-radius: 50%; width: 24px; height: 24px;
        text-align: center; line-height: 24px; margin-right: 6px; }

    .reading-box { font-size: 26px !important; font-weight: 700; color: #1E3A8A; line-height: 1.85;
        background: linear-gradient(180deg, #FFFFFF, #F8FAFC); padding: 22px; border-radius: 18px;
        border: 3px solid #BFDBFE; margin-bottom: 15px; box-shadow: 0 4px 14px rgba(30,58,138,.08); }
    .w-ok { color: #166534; }
    .w-near { color: #B45309; background: #FEF3C7; border-radius: 6px; padding: 0 4px; }
    .w-miss { color: #B91C1C; background: #FEE2E2; border-radius: 6px; padding: 0 4px; text-decoration: underline wavy; }

    .comment { background:#F0F9FF; border-left: 5px solid #0EA5E9; border-radius: 12px; padding: 8px 18px;
        font-size: 17px; line-height: 1.7; color:#0F172A; }
    .comment p { margin: 8px 0; }
    .heard { color:#475569; font-size:15px; background:#F8FAFC; border-radius:10px; padding:10px 14px; border:1px dashed #CBD5E1; }

    .badge { display:inline-block; border-radius: 999px; padding: 4px 14px; font-weight: 800; font-size: 14px; }
    .tags span { display:inline-block; background:#EEF2FF; color:#3730A3; border-radius:999px; padding:3px 12px;
        margin: 2px 4px 2px 0; font-weight:700; font-size:14px; }

    .reward { text-align:center; border-radius: 22px; padding: 18px 12px 16px; margin: 10px 0 16px;
        background: radial-gradient(circle at 50% 0%, #FEF9C3, #FDE68A 60%, #FCD34D); border: 3px solid #F59E0B;
        box-shadow: 0 10px 26px rgba(245,158,11,.35); }
    .reward .big { font-size: 22px; font-weight: 800; color: #92400E; }
    .reward .sub { color: #78350F; font-size: 16px; margin-top: 4px; }
    .star { font-size: 46px; display:inline-block; margin: 0 2px; }
    .star.on { animation: pop .6s cubic-bezier(.2,1.6,.4,1) both; filter: drop-shadow(0 3px 4px rgba(217,119,6,.45)); }
    .star.off { filter: grayscale(1); opacity: .25; }
    @keyframes pop { 0% { transform: scale(0) rotate(-40deg); opacity: 0; } 100% { transform: scale(1) rotate(0); opacity: 1; } }

    [data-testid="stMetric"] { background: #fff; border: 2px solid #E2E8F0; border-radius: 14px; padding: 10px 14px; }
    div.stButton > button, div.stFormSubmitButton > button { border-radius: 12px; font-weight: 800; }
    .footer { text-align:center; margin: 34px 0 8px; padding: 14px; border-radius: 16px; color:#475569;
        background: linear-gradient(90deg, #EEF2FF, #FDF2F8); font-weight: 700; }
    .footer b { color: #BE185D; }
    @media (max-width: 640px) { .reading-box { font-size: 22px !important; padding: 14px; } .hero h1 { font-size: 24px; } .hero .school { font-size: 17px; letter-spacing: 1px; } }
</style>
""", unsafe_allow_html=True)

st.markdown(f"""
<div class="hero" translate="no">
  <div class="school">{SCHOOL}</div>
  <h1> ✏️ BẠN BÚT CHÌ - TRỢ LÝ AI LUYỆN ĐỌC TIẾNG VIỆT </h1>
  <p> DÀNH CHO HỌC SINH LỚP 1 ĐẾN LỚP 5 
  Được tạo bởi Thầy giáo Hoàng Lâm Anh⭐ </p>
</div>
""", unsafe_allow_html=True)


# =====================================================================
# 2. GHI ĐIỂM VÀO GOOGLE SHEET
# =====================================================================
def _secret(name, default=""):
    try:
        return st.secrets.get(name, default)
    except Exception:
        return default


def _post_webhook(payload):
    url = _secret("WEBHOOK_URL")
    if not url:
        return False, "Chưa cấu hình WEBHOOK_URL trong Secrets."
    payload = {"key": _secret("WEBHOOK_KEY"), **payload}
    try:
        r = requests.post(url, json=payload, timeout=20)
        if r.status_code == 200 and r.text.strip().lower().startswith("ok"):
            return True, ""
        return False, f"Máy chủ trả về {r.status_code}: {r.text[:150]}"
    except Exception as e:
        return False, str(e)


def save_score_to_sheet(row):
    """Ghi 1 dòng kết quả đọc thành tiếng (tạo dòng mới trong Google Sheet)."""
    return _post_webhook({
        "action": "reading",
        "time": row["Thời gian"], "class_name": row["Lớp"], "grade": row["Khối"],
        "student_name": row["Họ và tên"], "lesson_title": row["Bài đọc"],
        "wpm": row["Tốc độ (WPM)"], "errors": row["Từ cần rèn"],
        "score": row["Điểm TT27"], "evaluation": row["Đánh giá"], "stars": row["Số sao"],
        "accuracy": row["Độ chính xác (%)"], "heard": row["Nhận dạng được"],
    })


def save_comprehension_to_sheet(class_name, student_name, lesson_title, answer, level_text):
    """Cập nhật đọc hiểu vào dòng gần nhất của đúng em đó, đúng bài đó (tìm theo lớp + tên + bài)."""
    return _post_webhook({"action": "comprehension", "class_name": class_name, "student_name": student_name,
                          "lesson_title": lesson_title, "comprehension": level_text, "comprehension_answer": answer})


# =====================================================================
# 3. GIỌNG ĐỌC MẪU (giọng thần kinh tiếng Việt)
# =====================================================================
@st.cache_data(show_spinner=False, max_entries=60)
def synth_edge(text, voice, rate):
    """Giọng thần kinh Microsoft (tiếng phổ thông chuẩn). Lỗi thì raise để không bị lưu vào cache."""
    import edge_tts

    async def run():
        buf = b""
        async for chunk in edge_tts.Communicate(text, voice, rate=rate).stream():
            if chunk["type"] == "audio":
                buf += chunk["data"]
        return buf

    loop = asyncio.new_event_loop()
    try:
        data = loop.run_until_complete(run())
    finally:
        loop.close()
    if not data:
        raise RuntimeError("edge-tts không trả về âm thanh")
    return data


@st.cache_data(show_spinner=False, max_entries=60)
def synth_gtts(text):
    """Giọng dự phòng của Google."""
    from gtts import gTTS
    buf = io.BytesIO()
    gTTS(text=text, lang="vi").write_to_fp(buf)
    return buf.getvalue()


def synth_vi(text, voice, rate):
    """Trả về (âm thanh mp3, tên giọng đang dùng, lỗi của giọng chính nếu có)."""
    try:
        return synth_edge(text, voice, rate), "edge", ""
    except Exception as e:
        edge_err = str(e) or e.__class__.__name__
    return synth_gtts(text), "gtts", edge_err


def browser_tts_button(text):
    """Phương án cuối: giọng có sẵn trong trình duyệt."""
    safe = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
    components.html(f"""
<!DOCTYPE html><html lang="vi" translate="no"><head><meta charset="utf-8">
<style>body{{margin:0;font-family:sans-serif}}
.b{{background:linear-gradient(135deg,#10B981,#059669);color:#fff;border:none;padding:11px 20px;
border-radius:8px;cursor:pointer;font-size:15px;font-weight:600}}</style></head><body>
<button class="b" onclick="p()">🔊 Nghe đọc mẫu (giọng trình duyệt)</button>
<script>
function p(){{speechSynthesis.cancel();const m=new SpeechSynthesisUtterance("{safe}");
const v=speechSynthesis.getVoices().filter(x=>x.lang.toLowerCase().startsWith('vi'));
if(v.length)m.voice=v[0];m.lang='vi-VN';m.rate=0.82;speechSynthesis.speak(m);}}
</script></body></html>""", height=52)


# =====================================================================
# 4. CHẤM ĐIỂM GIỌNG ĐỌC (công bằng, minh bạch)
# =====================================================================
def strip_marks(w):
    w = w.replace("đ", "d").replace("Đ", "D")
    return "".join(c for c in unicodedata.normalize("NFD", w) if not unicodedata.combining(c))


def norm_token(tok):
    tok = re.sub(r"[^\w]", "", tok.lower(), flags=re.UNICODE).replace("_", "")
    return tok


def analyze_audio(wav_bytes):
    """Trả về (thời lượng nói thực tế, tổng thời lượng, mức âm lượng) - đã cắt khoảng lặng đầu/cuối."""
    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as w:
            sr_, ch, sw, n = w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()
            raw = w.readframes(n)
        total = n / float(sr_)
        if sw != 2:
            return total, total, None
        x = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
        if ch > 1:
            x = x[::ch]
        frame = max(1, int(sr_ * 0.02))
        m = len(x) // frame
        if m < 5:
            return total, total, 0.0
        rms = np.sqrt((x[: m * frame].reshape(m, frame) ** 2).mean(axis=1))
        level = float(np.percentile(rms, 95))
        thr = max(150.0, 0.12 * level)
        voiced = np.where(rms > thr)[0]
        if len(voiced) == 0:
            return total, total, level
        speaking = (voiced[-1] - voiced[0] + 1) * frame / float(sr_)
        return max(speaking, 0.5), total, level
    except Exception:
        return 0.0, 0.0, None


def transcribe_alternatives(wav_bytes):
    """Nhận dạng tiếng Việt, trả về (danh sách các cách nghe có thể, lỗi)."""
    try:
        import speech_recognition as sr
    except Exception:
        return [], "Thiếu thư viện SpeechRecognition (kiểm tra requirements.txt)."
    try:
        rec = sr.Recognizer()
        with sr.AudioFile(io.BytesIO(wav_bytes)) as src:
            audio = rec.record(src)
        res = rec.recognize_google(audio, language="vi-VN", show_all=True)
        alts = [a.get("transcript", "") for a in (res.get("alternative", []) if isinstance(res, dict) else [])]
        return [a for a in alts if a.strip()][:5], ""
    except sr.RequestError as e:
        return [], f"Dịch vụ nhận dạng giọng nói đang bận ({e}). Con thử lại sau nhé."
    except Exception as e:
        return [], f"Lỗi xử lý âm thanh: {e}"


def align(ref_text, heard_text, P):
    """So khớp từng tiếng. Trả về (danh sách (hiển thị, trạng thái), điểm 'đúng' đã tính, trạng thái)."""
    ref_tokens = ref_text.split()
    ref_norm = [norm_token(t) for t in ref_tokens]
    got = [norm_token(t) for t in heard_text.split()]
    got = [g for g in got if g]
    idx = [i for i, w in enumerate(ref_norm) if w]
    ref = [ref_norm[i] for i in idx]

    status = ["miss"] * len(ref)
    sm = difflib.SequenceMatcher(a=ref, b=got, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i1, i2):
                status[k] = "ok"
        elif tag == "replace":
            # Ghép từng tiếng với tiếng nghe được giống nhất trong cùng đoạn -> "gần đúng"
            used = set()
            for k in range(i1, i2):
                a = strip_marks(ref[k])
                best_j, best_r = None, 0.0
                for j in range(j1, j2):
                    if j in used:
                        continue
                    b = strip_marks(got[j])
                    r = 1.0 if a == b else difflib.SequenceMatcher(a=a, b=b).ratio()
                    if r > best_r:
                        best_j, best_r = j, r
                if best_j is not None and best_r >= P["near_ratio"]:
                    status[k] = "near"
                    used.add(best_j)
    credit = sum(1.0 if s == "ok" else P["near_credit"] if s == "near" else 0 for s in status)
    full = {i: s for i, s in zip(idx, status)}
    out = [(ref_tokens[i], full.get(i, "ok")) for i in range(len(ref_tokens))]
    return out, credit, status


def stars_from(score, rating):
    """Điểm đọc /4 -> số sao 1..5 (luôn có ít nhất 1 sao khích lệ)."""
    if rating.startswith("Chưa"):
        return 1
    n = 5 if score >= 4.0 else 4 if score >= 3.5 else 3 if score >= 3.0 else 2 if score >= 2.0 else 1
    if not rating.startswith("Hoàn thành tốt"):
        n = min(n, 3)
    return n


def grade(status, credit, speaking_seconds, target, P):
    total = len(status)
    accuracy = credit / total if total else 0
    read_count = sum(1 for s in status if s in ("ok", "near"))   # số tiếng em đã đọc ra
    wpm = round(read_count / (speaking_seconds / 60)) if speaking_seconds > 0 else 0
    speed = min(wpm / target, 1.0) if target else 0
    eff = min(accuracy / P["full_acc"], 1.0)
    score = max(0.0, min(4.0, round_half(4 * (P["w_acc"] * eff + P["w_speed"] * speed))))
    if accuracy < P["h_th"]:
        score = min(score, 1.5)          # đọc đúng chưa tới ngưỡng "hoàn thành" thì chưa thể hoàn thành
    elif accuracy < P["t_th"]:
        score = min(score, 3.0)          # chưa đạt mức "tốt" thì tối đa 3 điểm
    if score >= 3.5 and accuracy >= P["t_th"] and speed >= P["t_speed"]:
        rating = "Hoàn thành tốt (T)"
    elif score >= 2.0 and accuracy >= P["h_th"]:
        rating = "Hoàn thành (H)"
    else:
        rating = "Chưa hoàn thành (C)"
    return accuracy, wpm, score, rating


def evaluate(ref_text, wav_bytes, target_wpm, P):
    """Chấm 1 bài đọc. Trả về dict kết quả hoặc {'err': ...} nếu cần ghi âm lại."""
    speaking, total, level = analyze_audio(wav_bytes)
    if total < MIN_SECONDS:
        return {"err": "Bản ghi âm quá ngắn. Con hãy đọc cả đoạn văn rồi mới bấm dừng nhé."}
    if level is not None and level < 150:
        return {"err": "Âm thanh quá nhỏ. Con hãy đọc to hơn hoặc ngồi gần micro hơn rồi ghi âm lại nhé."}
    alts, err = transcribe_alternatives(wav_bytes)
    if err:
        return {"err": err}
    if not alts:
        return {"err": "Máy chưa nghe rõ giọng đọc. Con hãy đọc to, rõ, ở nơi yên tĩnh rồi ghi âm lại nhé."}

    # Chọn cách nghe khớp với bài nhất trong các khả năng máy đưa ra (tránh phạt oan khi máy nghe nhầm)
    best = None
    for a in alts:
        tokens, credit, status = align(ref_text, a, P)
        if best is None or credit > best[1]:
            best = (tokens, credit, status, a)
    tokens, credit, status, heard = best

    if status and sum(1 for s in status if s != "miss") / len(status) < P["min_rec"]:
        return {"err": "Máy chưa nghe đủ rõ để chấm công bằng. Con ghi âm lại một lần nữa nhé. "
                       "Nếu vẫn chưa được, con đọc trực tiếp cho cô giáo nghe."}
    accuracy, wpm, score, rating = grade(status, credit, speaking, target_wpm, P)
    wrong = [norm_token(t) for t, s in tokens if s == "miss"]
    near = [norm_token(t) for t, s in tokens if s == "near"]
    uniq = lambda xs: list(dict.fromkeys(xs))
    return dict(err="", tokens=tokens, accuracy=accuracy, wpm=wpm, score=score, rating=rating, heard=heard,
                stars=stars_from(score, rating),
                wrong=uniq(wrong), near=uniq(near), total=len(status), speaking=speaking,
                n_ok=sum(1 for s in status if s == "ok"), n_near=sum(1 for s in status if s == "near"),
                n_miss=sum(1 for s in status if s == "miss"))


def round_half(x):
    return round(x * 2) / 2


def build_comment(name, lesson_title, res, target):
    """Nhận xét theo tinh thần Thông tư 27/2020/TT-BGDĐT: mức đạt, kết quả, ưu điểm, điểm cần cố gắng, hướng khắc phục."""
    rating = res["rating"]
    pct = round(res["accuracy"] * 100)
    n_read = res["n_ok"] + res["n_near"]
    need = (res["wrong"] + res["near"])[:6]
    wpm = res["wpm"]
    is_t, is_h = rating.startswith("Hoàn thành tốt"), rating.startswith("Hoàn thành (")

    result = f"Em đọc đúng {n_read}/{res['total']} tiếng ({pct}%), tốc độ khoảng {wpm} tiếng/phút."

    strengths = []
    if is_t:
        strengths.append(f"Em {name} đọc bài “{lesson_title}” đúng, rõ ràng, phát âm chính xác hầu hết các tiếng.")
    elif is_h:
        strengths.append(f"Em {name} đã đọc được phần lớn bài “{lesson_title}”, đọc đúng nhiều tiếng.")
    else:
        strengths.append(f"Em {name} mạnh dạn đọc to bài “{lesson_title}”, đây là điểm đáng ghi nhận.")
    if wpm >= target and not rating.startswith("Chưa"):
        strengths.append("Tốc độ đọc đáp ứng yêu cầu.")

    weaknesses = []
    if need:
        weaknesses.append("Còn đọc chưa chính xác các tiếng: <b>" + ", ".join(need) + "</b>.")
    if wpm < target * 0.7:
        weaknesses.append("Tốc độ đọc còn chậm, chưa trôi chảy.")
    elif wpm > max(130, target * 2.5):
        weaknesses.append("Em đọc hơi nhanh, cần đọc chậm lại để rõ từng tiếng.")
    if not weaknesses:
        weaknesses.append("Chưa thấy hạn chế đáng kể ở bài đọc này.")

    plan = []
    if need:
        plan.append("Đọc chậm từng tiếng còn sai (mỗi tiếng 3 lần), sau đó ghép vào cả câu; nghe đọc mẫu rồi đọc theo.")
    if wpm < target * 0.7:
        plan.append("Đọc thành tiếng bài đọc khoảng 5–10 phút mỗi ngày, tập đọc theo cụm từ để đọc trôi chảy hơn.")
    if wpm > max(130, target * 2.5):
        plan.append("Đọc chậm hơn, ngắt nghỉ ở dấu phẩy, dấu chấm.")
    if is_t and not plan:
        plan.append("Tiếp tục duy trì, đọc thêm các bài khác để đọc diễn cảm hơn.")
    if not (is_t or is_h):
        plan.append("Nghe đọc mẫu và đọc lại bài; gia đình và giáo viên hỗ trợ em luyện đọc thêm.")
    return dict(level=rating, result=result, strengths=strengths, weaknesses=weaknesses, plan=plan)


def render_marked(tokens):
    cls = {"ok": "w-ok", "near": "w-near", "miss": "w-miss"}
    return " ".join(f'<span class="{cls[s]}">{t}</span>' for t, s in tokens)




# =====================================================================
# 5. KHO BÀI ĐỌC LỚP 1 - 5 (35 tuần x 2 bài / tuần) - đọc từ file giáo trình
#    Đặt file curriculum_full_grades_1_to_5.py (hoặc .json) cùng thư mục với aap.py
# =====================================================================
@st.cache_data(show_spinner=False)
def load_curriculum():
    """Trả về {'Lop_1': {'Tuần 01': {'term':..., 'readings':[...]}, ...}, ...}"""
    try:
        from curriculum_full_grades_1_to_5 import CURRICULUM_DATA
        return CURRICULUM_DATA
    except Exception:
        import json
        import os
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "curriculum_full_grades_1_to_5.json")
        with open(path, encoding="utf-8") as f:
            return json.load(f)


CURRICULUM = load_curriculum()
GRADES = {f"Lớp {k.split('_')[1]}": k for k in CURRICULUM}          # {'Lớp 1': 'Lop_1', ...}
GRADE_OF = {v: k.split()[1] for k, v in GRADES.items()}             # {'Lop_1': '1', ...}


# =====================================================================
# 5b. CHẤM CÂU TRẢ LỜI ĐỌC HIỂU
#     Đáp án của từng bài là 1 cụm (expected_answer), ví dụ "Hoàng Liên Sơn và đồng bằng sông Cửu Long".
#     Tự tách thành các "ý" (cắt theo "và" / dấu phẩy); mỗi ý có các từ khóa chính.
#     Em nói đúng >= 60% từ khóa của một ý là được ý đó. Được >=1 ý là ĐÚNG, được hết các ý là ĐẦY ĐỦ.
# =====================================================================
STOP_WORDS = {"và", "là", "của", "có", "những", "các", "một", "được", "cho", "ở", "với", "như", "rất",
              "đã", "để", "thì", "mà", "khi", "trong", "cùng", "bởi", "vì", "nên", "ra", "vào", "lên", "hay"}


def _words(text):
    return [w for w in (norm_token(t) for t in text.split()) if w]


def _split_ideas(expected):
    parts = re.split(r"\s+và\s+|,|;", expected)
    ideas = [p.strip() for p in parts if p.strip()]
    return ideas or ([expected.strip()] if expected.strip() else [])


def _keywords(idea):
    ws = _words(idea)
    kw = [w for w in ws if w not in STOP_WORDS]
    return kw or ws


def _word_match(a, answer_words):
    """a: từ khóa. Trả về 'exact' | 'nodau' | 'typo' | None"""
    if a in answer_words:
        return "exact"
    sa = strip_marks(a)
    best = None
    for w in answer_words:
        sw = strip_marks(w)
        if sw == sa:
            best = best or "nodau"
        elif len(sa) >= 3 and difflib.SequenceMatcher(a=sw, b=sa).ratio() >= 0.85:
            best = best or "typo"
    return best


def check_answer(answer, lesson_text, expected, cov=0.6):
    words = _words(answer)
    ideas = _split_ideas(expected)
    hit, missing, no_dau, typo = [], [], False, False
    for idea in ideas:
        kws = _keywords(idea)
        ms = [_word_match(k, words) for k in kws]
        ok = sum(1 for m in ms if m)
        if kws and ok / len(kws) >= cov:
            hit.append(idea)
            no_dau |= any(m == "nodau" for m in ms)
            typo |= any(m == "typo" for m in ms)
        else:
            missing.append(idea)
    level = "sai" if not hit else ("daydu" if not missing else "dung")
    # Câu trong bài chứa đáp án -> dùng làm gợi ý khi em trả lời chưa đúng
    hint, best_n = None, 0
    kw_all = {strip_marks(k) for idea in ideas for k in _keywords(idea)}
    for sent in re.split(r"(?<=[.!?])\s+", lesson_text):
        n = len(kw_all & {strip_marks(w) for w in _words(sent)})
        if n > best_n:
            hint, best_n = sent, n
    sample_len = max(1, len(_words(expected)))
    return dict(level=level, hit=hit, missing=missing, no_dau=no_dau, typo=typo,
                too_long=len(words) > max(10, int(1.5 * sample_len) + 2), too_short=len(words) == 0,
                sample=expected, hint=hint)


def comprehension_feedback(r, name):
    """Lời nhận xét cho câu trả lời đọc hiểu. Trả về (loại thông báo, danh sách đoạn)."""
    out = []
    if r["too_long"] and r["level"] != "sai":
        out.append(f"Em {name} đã tìm đúng ý trong bài, nhưng câu trả lời của em hơi dài.")
        out.append("Em chỉ cần trả lời <b>ngắn gọn</b> vào đúng ý câu hỏi, không cần chép cả đoạn văn nhé.")
        if r["no_dau"]:
            out.append("Em cũng nhớ gõ <b>đủ dấu</b> khi viết câu trả lời nhé.")
        return "success", out
    if r["level"] == "daydu":
        out.append(f"Chính xác rồi em {name}! Câu trả lời của em đúng và đầy đủ ý.")
    elif r["level"] == "dung":
        out.append(f"Em {name} trả lời đúng rồi! Em đã tìm được ý: <b>{'; '.join(r['hit'])}</b>.")
        out.append("Để câu trả lời đầy đủ hơn, em có thể bổ sung thêm ý: <b>" + "; ".join(r["missing"]) + "</b>.")
    else:
        out.append("Chưa đúng ý của câu hỏi rồi em ạ. Em đừng nản nhé!")
        if r["hint"]:
            out.append(f"Gợi ý: em đọc kĩ lại câu này trong bài: <i>“{r['hint']}”</i> rồi trả lời lại nhé.")
        else:
            out.append("Em hãy đọc lại đoạn văn thật kĩ rồi trả lời lại nhé.")
    if r["level"] != "sai" and r["no_dau"]:
        out.append("Ý của em đúng, nhưng em nhớ gõ <b>đủ dấu</b> khi viết câu trả lời nhé.")
    elif r["level"] != "sai" and r["typo"]:
        out.append("Em đúng ý rồi, nhưng có chữ em gõ chưa chính xác. Em kiểm tra lại chính tả nhé.")
    if r["too_long"]:
        out.append("Em chỉ cần trả lời <b>ngắn gọn</b> vào đúng ý câu hỏi, không cần chép cả đoạn văn.")
    return ("success" if r["level"] != "sai" else "warning"), out


COMP_LABEL = {"daydu": "Đúng, đầy đủ ý", "dung": "Đúng một phần ý", "sai": "Chưa đúng"}


# =====================================================================
# 6. GIAO DIỆN
# =====================================================================
def stars_html(n):
    on = "".join(f'<span class="star on" style="animation-delay:{i * 0.18:.2f}s">⭐</span>' for i in range(n))
    off = "".join('<span class="star off">⭐</span>' for _ in range(5 - n))
    return on + off


def rank_of(total):
    cur = RANKS[0]
    for r in RANKS:
        if total >= r[0]:
            cur = r
    nxt = next((r for r in RANKS if r[0] > total), None)
    return cur, nxt


def student_total_stars(history, name, cls):
    """Tổng sao = sao cao nhất của mỗi bài (đọc lại để cải thiện, không cộng dồn lặp)."""
    best = {}
    for h in history:
        if h["Họ và tên"].lower() == name.lower() and h["Lớp"] == cls:
            best[h["Mã bài"]] = max(best.get(h["Mã bài"], 0), h["Sao"])
    return sum(best.values()), len(best)


st.session_state.setdefault("history", [])
st.session_state.setdefault("rec_n", 0)

# ---- Thông tin học sinh ----
with st.container(border=True):
    col_class, col_name = st.columns([1, 2])
    with col_class:
        selected_class = st.text_input("🏫 Lớp học:", placeholder="Ví dụ: 2A1").strip().upper()
    with col_name:
        student_name = st.text_input("🧒 Họ và tên học sinh:", placeholder="Ví dụ: Nguyễn Văn An").strip()

    # Tự gợi ý khối theo số đầu của tên lớp (2A1 -> Lớp 2); em vẫn có thể đổi tay
    grade_labels = list(GRADES)
    guess = f"Lớp {selected_class[0]}" if selected_class[:1] in GRADE_OF.values() else None
    default_idx = grade_labels.index(guess) if guess in grade_labels else 0

    col_grade, col_term, col_week = st.columns([1, 1.3, 2])
    with col_grade:
        grade_label = st.selectbox("🎒 Khối:", grade_labels, index=default_idx, key=f"grade_{selected_class[:1]}")
    grade_key = GRADES[grade_label]
    grade_num = GRADE_OF[grade_key]
    P = PROFILES[grade_num]
    weeks = CURRICULUM[grade_key]
    with col_term:
        selected_term = st.selectbox("🗓️ Kỳ học:", ["Học kỳ 1 (Tuần 1 - 18)", "Học kỳ 2 (Tuần 19 - 35)"])
    term_filter = "Học kỳ 1" if "Học kỳ 1" in selected_term else "Học kỳ 2"
    week_names = [w for w, v in weeks.items() if v["term"] == term_filter]
    with col_week:
        selected_week = st.selectbox("📅 Chọn tuần:", week_names)
    readings = weeks[selected_week]["readings"]
    reading_titles = [r["title"] for r in readings]
    picked_title = st.selectbox("📚 Chọn bài đọc:", reading_titles)

lesson = readings[reading_titles.index(picked_title)]
target_wpm = lesson.get("target_wpm", 40)
lesson_id = lesson.get("lesson_code", lesson["title"])

# Màu chủ đề theo khối + cỡ chữ
FONT_SIZES = {"Vừa": 24, "Lớn": 30, "Rất lớn": 38}
font_label = st.session_state.get(f"fs_{grade_num}", list(FONT_SIZES)[P["fs"]])
st.markdown(f"""<style>
div.reading-box {{ border-color: {P['accent']}66 !important;
    font-size: clamp(20px, 5.4vw, {FONT_SIZES.get(font_label, 24)}px) !important; }}
</style>""", unsafe_allow_html=True)

tab_read, tab_prog, tab_help = st.tabs(["📖 Đọc bài", "🏆 Thành tích của em", "ℹ️ Hướng dẫn & cách chấm"])


def reading_flow():
    st.markdown(f"""
<div class="steps" translate="no">
  <div><b>1</b>Nghe cô đọc mẫu</div><div><b>2</b>Bấm micro, đọc to cả bài</div><div><b>3</b>Nhận nhận xét và ⭐</div>
</div>""", unsafe_allow_html=True)

    st.markdown(f"### {P['emoji']} {lesson['title']}")
    st.markdown(f'<span class="badge" style="background:{P["soft"]};color:{P["accent"]}">{grade_label} · {P["level"]}</span>',
                unsafe_allow_html=True)
    st.write("")
    st.radio("🔎 Cỡ chữ bài đọc", list(FONT_SIZES), index=P["fs"], horizontal=True, key=f"fs_{grade_num}")
    st.markdown(f'<div class="reading-box" translate="no">{lesson["text"]}</div>', unsafe_allow_html=True)
    if lesson.get("difficult_words"):
        tags = "".join(f"<span>{w}</span>" for w in lesson["difficult_words"])
        st.markdown(f'<div class="tags" translate="no">🔔 Từ cần chú ý khi đọc: {tags}</div>', unsafe_allow_html=True)

    # ---- Nghe đọc mẫu ----
    st.markdown("#### 🔊 Nghe Bạn Bút Chì đọc mẫu")
    v1, v2 = st.columns(2)
    with v1:
        voice_label = st.radio("Giọng đọc", list(VOICES), horizontal=False)
    with v2:
        speed_label = st.radio("Tốc độ", list(SPEEDS), horizontal=False)

    tts_key = f"{lesson_id}|{voice_label}|{speed_label}"
    if st.button("▶️ Nghe đọc mẫu", type="primary"):
        st.session_state["tts_play"] = tts_key
    if st.session_state.get("tts_play") == tts_key:
        try:
            with st.spinner("Bạn Bút Chì đang chuẩn bị giọng đọc..."):
                audio_bytes, engine, edge_err = synth_vi(lesson["text"], VOICES[voice_label], SPEEDS[speed_label])
            try:
                st.audio(audio_bytes, format="audio/mp3", autoplay=True)
            except TypeError:
                st.audio(audio_bytes, format="audio/mp3")
            if engine == "edge":
                st.caption(f"Đang dùng giọng: {voice_label}")
            else:
                st.warning("Giọng phổ thông chất lượng cao đang không kết nối được, app tạm dùng giọng dự phòng của Google.")
                st.caption(f"Chi tiết kỹ thuật: {edge_err[:300]}")
        except Exception:
            st.warning("Chưa tạo được giọng đọc chất lượng cao, tạm dùng giọng của trình duyệt.")
            browser_tts_button(lesson["text"])

    # ---- Ghi âm và chấm điểm ----
    st.markdown("---")
    st.markdown("### 🎙️ Luyện đọc và nhận sao thưởng")
    st.caption("Bấm micro, đọc to cả đoạn văn ở nơi yên tĩnh, rồi bấm dừng.")

    def reset_recording():
        st.session_state["rec_n"] += 1
        st.session_state.pop("result_key", None)
        st.session_state.pop("result", None)

    # key có mã bài -> đổi bài/đổi khối thì ô ghi âm tự làm mới, không chấm nhầm bản ghi của bài trước
    audio_file = st.audio_input("Ghi âm giọng đọc của học sinh:", key=f"audio_{st.session_state['rec_n']}_{lesson_id}")
    if not audio_file:
        return
    if not student_name or not selected_class:
        st.warning("⚠️ Con hãy nhập đầy đủ Lớp và Họ và tên ở phía trên trước khi nộp bài nhé!")
        return

    wav_bytes = audio_file.getvalue()
    key = hashlib.md5(wav_bytes + student_name.encode() + lesson_id.encode()).hexdigest()

    # Chỉ chấm và ghi 1 lần cho mỗi bản ghi âm (tránh trùng khi app chạy lại)
    if st.session_state.get("result_key") != key:
        with st.spinner("Bạn Bút Chì đang lắng nghe và chấm bài..."):
            res = evaluate(lesson["text"], wav_bytes, target_wpm, P)
            if not res["err"]:
                now = datetime.now(VN_TZ)
                record_id = key[:10] + now.strftime("%y%m%d%H%M%S")
                res["record_id"] = record_id
                row = {
                    "Thời gian": now.strftime("%d/%m/%Y %H:%M"),
                    "Lớp": selected_class, "Khối": grade_num, "Họ và tên": student_name,
                    "Bài đọc": lesson["title"], "Tốc độ (WPM)": res["wpm"],
                    "Từ cần rèn": ", ".join((res["wrong"] + res["near"])[:8]) or "Không có",
                    "Điểm TT27": res["score"], "Đánh giá": res["rating"], "Số sao": res["stars"],
                    "Độ chính xác (%)": round(res["accuracy"] * 100), "Nhận dạng được": res["heard"],
                }
                res["saved"], res["save_err"] = save_score_to_sheet(row)
                st.session_state["history"].append({
                    "Thời gian": now.strftime("%H:%M"), "Họ và tên": student_name, "Lớp": selected_class,
                    "Mã bài": lesson_id, "Bài đọc": lesson["title"], "Đánh giá": res["rating"],
                    "Điểm": res["score"], "Sao": res["stars"], "Chính xác (%)": round(res["accuracy"] * 100)})
            st.session_state["result_key"], st.session_state["result"] = key, res
            if not res["err"]:
                if res["stars"] >= 4:
                    st.balloons()

    res = st.session_state["result"]
    if res["err"]:
        st.error(res["err"])
        st.button("🔄 Ghi âm lại", type="primary", on_click=reset_recording, key="retry_err")
        return

    # ---- Thẻ thưởng sao ----
    n = res["stars"]
    title, sub = STAR_INFO[n]
    total, n_lessons = student_total_stars(st.session_state["history"], student_name, selected_class)
    st.markdown(f"""
<div class="reward" translate="no">
  <div>{stars_html(n)}</div>
  <div class="big">{title} · {n}/5 sao</div>
  <div class="sub">{sub}</div>
  <div class="sub" style="margin-top:8px"><b>🌟 Tổng sao của em: {total}</b> (qua {n_lessons} bài)</div>
</div>""", unsafe_allow_html=True)

    st.markdown("## 🌟 Kết quả đánh giá Tiếng Việt")
    c1, c2, c3 = st.columns(3)
    c1.metric("Mức đánh giá (TT27)", res["rating"])
    c2.metric("Đọc đúng", f"{res['n_ok'] + res['n_near']}/{res['total']} tiếng")
    c3.metric("Tốc độ đọc", f"{res['wpm']} tiếng/phút")
    st.caption(f"Điểm đọc thành tiếng tham khảo: {res['score']}/4,0 · Tốc độ chuẩn của {grade_label}: {target_wpm} tiếng/phút")

    if res["saved"]:
        st.success("📊 Kết quả của em đã được ghi nhận tự động vào Sổ theo dõi của nhà trường!")
    else:
        st.info("ℹ️ Kết quả đã được chấm trên màn hình, chưa ghi được vào Sổ. Con báo cô giáo nhé.")
        if res.get("save_err"):
            st.caption(f"(Chi tiết lỗi ghi Sheet: {res['save_err']})")

    if res["rating"].startswith("Chưa"):
        st.warning("Lần đọc này em cần cố gắng thêm. Con nghe đọc mẫu rồi bấm “Ghi âm lại” để đọc thêm một lần nhé!")
    elif n < 5:
        st.info("💡 Đọc lại để cải thiện, em sẽ được tối đa 5 sao cho bài này. Sao của mỗi bài tính theo lần đọc tốt nhất.")
    st.button("🔄 Ghi âm lại (đọc lần nữa)", type="primary" if res["rating"].startswith("Chưa") else "secondary",
              on_click=reset_recording, key="retry_ok")

    st.markdown("### 💬 Bài đọc của em")
    st.markdown(f'<div class="reading-box" translate="no">{render_marked(res["tokens"])}</div>', unsafe_allow_html=True)
    st.caption("Màu xanh: đọc đúng · Nền vàng: đọc gần đúng (chưa chuẩn dấu) · Nền đỏ: cần đọc lại")
    st.markdown("### 📝 Nhận xét (theo Thông tư 27/2020/TT-BGDĐT)")
    cm = build_comment(student_name, lesson["title"], res, target_wpm)
    li = lambda xs: "<br>".join("• " + x for x in xs)
    st.markdown(
        '<div class="comment">'
        f'<p><b>Mức đạt được:</b> {cm["level"]}</p>'
        f'<p><b>Kết quả:</b> {cm["result"]}</p>'
        f'<p><b>Ưu điểm:</b><br>{li(cm["strengths"])}</p>'
        f'<p><b>Điểm cần cố gắng:</b><br>{li(cm["weaknesses"])}</p>'
        f'<p><b>Hướng khắc phục:</b><br>{li(cm["plan"])}</p>'
        '<p style="font-size:14px;color:#64748B;margin-top:12px">Nhận xét do máy hỗ trợ, '
        'giáo viên xem lại và điều chỉnh khi ghi vào sổ theo dõi.</p>'
        '</div>', unsafe_allow_html=True)
    with st.expander("Xem máy nghe được gì"):
        st.markdown(f'<div class="heard">{res["heard"]}</div>', unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("### ❓ Câu hỏi đọc hiểu")
    st.markdown(f"**{lesson['question']}**")
    with st.form(key=f"form_{key}"):
        answer_input = st.text_input("Con gõ câu trả lời ngắn vào đây:", placeholder="Ví dụ: Bạn nhỏ cảm thấy ...")
        submitted = st.form_submit_button("✅ Kiểm tra câu trả lời", type="primary")
    if submitted:
        if not answer_input.strip():
            st.warning("Con hãy gõ câu trả lời rồi bấm “Kiểm tra câu trả lời” nhé.")
        else:
            cr = check_answer(answer_input, lesson["text"], lesson["expected_answer"], P["comp_cov"])
            kind, paras = comprehension_feedback(cr, student_name)
            body = "".join(f"<p>{p}</p>" for p in paras)
            (st.success if kind == "success" else st.warning)("🎉 Con trả lời đúng rồi!" if kind == "success"
                                                              else "Con thử lại nhé!")
            st.markdown(f'<div class="comment">{body}</div>', unsafe_allow_html=True)
            if res.get("record_id"):
                ok, err = save_comprehension_to_sheet(selected_class, student_name, lesson["title"], answer_input.strip(), COMP_LABEL[cr["level"]])
                if not ok and err:
                    st.caption(f"(Chưa ghi được kết quả đọc hiểu vào Sheet: {err})")
            if cr["level"] != "sai":
                with st.expander("Xem câu trả lời mẫu"):
                    st.markdown(cr["sample"])


with tab_read:
    reading_flow()

# ---- Tab thành tích ----
with tab_prog:
    if not student_name or not selected_class:
        st.info("Con nhập Lớp và Họ tên ở phía trên để xem thành tích nhé.")
    else:
        mine = [h for h in st.session_state["history"]
                if h["Họ và tên"].lower() == student_name.lower() and h["Lớp"] == selected_class]
        total, n_lessons = student_total_stars(st.session_state["history"], student_name, selected_class)
        (cur, nxt) = rank_of(total)
        st.markdown(f"## {cur[2]} {student_name} · {cur[1]}")
        m1, m2, m3 = st.columns(3)
        m1.metric("⭐ Tổng sao", total)
        m2.metric("📚 Số bài đã đọc", n_lessons)
        m3.metric("🎯 Lượt đọc", len(mine))
        if nxt:
            st.progress(min(1.0, (total - cur[0]) / (nxt[0] - cur[0])),
                        text=f"Còn {nxt[0] - total} sao nữa để đạt danh hiệu {nxt[2]} {nxt[1]}")
        else:
            st.success("👑 Em đã đạt danh hiệu cao nhất. Tuyệt vời!")
        if mine:
            st.markdown("#### Các lần đọc hôm nay")
            st.dataframe([{"Giờ": h["Thời gian"], "Bài đọc": h["Bài đọc"], "Mức": h["Đánh giá"], "Điểm /4": h["Điểm"],
                           "Sao": "⭐" * h["Sao"], "Chính xác (%)": h["Chính xác (%)"]} for h in reversed(mine)],
                         hide_index=True, use_container_width=True)
        else:
            st.caption("Em chưa có lần đọc nào trong phiên này. Sang tab “Đọc bài” để bắt đầu nhé!")
        st.caption("Thành tích ở đây tính trong lần mở web này. Toàn bộ kết quả được lưu lâu dài trong Sổ theo dõi của nhà trường.")

# ---- Tab hướng dẫn ----
with tab_help:
    st.markdown("### 🌈 Cách dùng")
    st.markdown("""
1. Nhập **Lớp** và **Họ tên**, chọn **Khối, Kỳ học, Tuần, Bài đọc**.
2. Bấm **Nghe đọc mẫu** để nghe cô đọc trước.
3. Bấm **micro**, đọc to cả đoạn văn rồi bấm dừng (ngồi nơi yên tĩnh, đọc rõ từng tiếng).
4. Xem **sao thưởng**, nhận xét và trả lời **câu hỏi đọc hiểu**. Đọc lại nhiều lần để được thêm sao!""")

    st.markdown("### ⭐ Sao thưởng")
    st.dataframe([
        {"Số sao": "⭐" * 5, "Điểm đọc /4": "4,0", "Ý nghĩa": "Xuất sắc, giọng đọc vàng"},
        {"Số sao": "⭐" * 4, "Điểm đọc /4": "3,5", "Ý nghĩa": "Rất giỏi"},
        {"Số sao": "⭐" * 3, "Điểm đọc /4": "3,0", "Ý nghĩa": "Giỏi"},
        {"Số sao": "⭐" * 2, "Điểm đọc /4": "2,0 - 2,5", "Ý nghĩa": "Đang tiến bộ"},
        {"Số sao": "⭐", "Điểm đọc /4": "dưới 2,0", "Ý nghĩa": "Cố gắng thêm (em luôn được ít nhất 1 sao)"},
    ], hide_index=True, use_container_width=True)
    st.caption("Sao của mỗi bài tính theo lần đọc tốt nhất. Chưa đạt mức “Hoàn thành tốt” thì tối đa 3 sao.")

    st.markdown("### 📏 Mức chấm của từng khối (để thầy cô và phụ huynh tham khảo)")
    st.dataframe([{
        "Khối": p["name"], "Mức chấm": p["level"].split("·")[1].strip(),
        "Đọc đúng để trọn điểm": f"{round(p['full_acc'] * 100)}%",
        "Tiếng gần đúng được": f"{p['near_credit']:.2f} tiếng",
        "Tỉ trọng đúng / tốc độ": f"{round(p['w_acc'] * 100)} / {round(p['w_speed'] * 100)}",
        "Đạt T khi đúng ≥": f"{round(p['t_th'] * 100)}%",
        "Đạt H khi đúng ≥": f"{round(p['h_th'] * 100)}%",
        "Tốc độ tối thiểu để đạt T": "không yêu cầu" if not p["t_speed"] else f"{round(p['t_speed'] * 100)}% mức chuẩn",
    } for p in PROFILES.values()], hide_index=True, use_container_width=True)
    st.markdown(f"""
- **Điểm /4 = tỉ trọng đọc đúng + tỉ trọng tốc độ**, làm tròn 0,5. Lớp càng cao càng yêu cầu đọc chính xác và đúng tốc độ.
- Tiếng đúng được 1; tiếng **gần đúng** (máy có thể nghe lệch dấu hoặc âm do giọng trẻ em) được một phần điểm; tiếng sót hoặc sai được 0. Đọc thêm hoặc lặp từ không bị trừ điểm.
- Tốc độ tính trên thời gian em thực sự đọc (đã bỏ khoảng lặng đầu và cuối). Mức chuẩn của **{grade_label}: {target_wpm} tiếng/phút**.
- Máy xét nhiều cách nghe và lấy cách khớp bài nhất để tránh phạt oan. Nếu máy nghe không rõ, bài **không được chấm** để em ghi âm lại.
- Mức đánh giá theo Thông tư 27: **T** Hoàn thành tốt · **H** Hoàn thành · **C** Chưa hoàn thành. Điểm và sao chỉ để tham khảo, **giáo viên là người đánh giá cuối cùng**.""")

st.markdown(f"""
<div class="footer" translate="no">
  💛 "✏️BẠN BÚT CHÌ" được tạo bởi giáo viên <b>{AUTHOR}</b><br>
  <span style="font-weight:700;font-size:15px">Trường Tiểu học Thái Hòa , {LOCATION}</span>
</div>""", unsafe_allow_html=True)
