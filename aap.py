import asyncio
import difflib
import hashlib
import io
import re
import unicodedata
import wave
from datetime import datetime

import numpy as np
import requests
import streamlit as st
import streamlit.components.v1 as components

# =====================================================================
# 1. CẤU HÌNH
# =====================================================================
# Tốc độ đọc chuẩn (tiếng/phút) của từng bài nằm trong file giáo trình (trường "target_wpm")
# -> mỗi khối có mức chuẩn riêng (lớp 1: 35, lớp 2: 55, lớp 3: 75, lớp 4: 85, lớp 5: 100)
W_ACCURACY, W_SPEED = 0.85, 0.15     # điểm = 85% đọc đúng + 15% tốc độ (ưu tiên đọc đúng, tròn chữ)
FULL_ACCURACY = 0.90                 # đọc đúng từ 90% số tiếng trở lên là đã được trọn điểm phần "đọc đúng"
NEAR_CREDIT = 0.75                   # tiếng đọc gần đúng (máy nghe lệch dấu/âm) được 0.75 tiếng
NEAR_RATIO = 0.75                    # độ giống tối thiểu để tính là "gần đúng"
MIN_SECONDS = 3.0                    # ghi âm ngắn hơn mức này -> yêu cầu ghi lại
MIN_RECOGNIZED = 0.20                # máy nghe được dưới 20% bài -> coi là chưa nghe rõ, không chấm

VOICES = {"Cô Hoài My (giọng nữ, giọng Bắc)": "vi-VN-HoaiMyNeural",
          "Thầy Nam Minh (giọng nam, giọng Bắc)": "vi-VN-NamMinhNeural"}
SPEEDS = {"Đọc chậm (cho em tập đọc)": "-20%", "Đọc vừa": "-8%"}

st.set_page_config(page_title="Luyện đọc Tiếng Việt - Tiểu học Thái Hòa", page_icon="✏️", layout="centered")

st.markdown("""
<style>
    html, body, [class*="css"] { translate: no !important; }
    .skiptranslate { display: none !important; }
    .reading-box {
        font-size: 26px !important; font-weight: 600; color: #1E3A8A; line-height: 1.8;
        background-color: #F8FAFC; padding: 20px; border-radius: 12px;
        border: 2px solid #E2E8F0; margin-bottom: 15px;
    }
    .school-header { text-align: center; color: #B91C1C; font-weight: bold; font-size: 20px;
        margin-bottom: 5px; text-transform: uppercase; }
    .w-ok { color: #166534; }
    .w-near { color: #B45309; background: #FEF3C7; border-radius: 6px; padding: 0 4px; }
    .w-miss { color: #B91C1C; background: #FEE2E2; border-radius: 6px; padding: 0 4px; text-decoration: underline wavy; }
    .comment { background:#F0F9FF; border-left: 5px solid #0EA5E9; border-radius: 10px; padding: 8px 18px; font-size: 17px; line-height: 1.7; color:#0F172A; }
    .comment p { margin: 8px 0; }
    .heard { color:#475569; font-size:15px; background:#F8FAFC; border-radius:10px; padding:10px 14px; border:1px dashed #CBD5E1; }
    @media (max-width: 640px) { .reading-box { font-size: 22px !important; padding: 14px; } }
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="school-header" translate="no">TRƯỜNG TIỂU HỌC THÁI HÒA</div>', unsafe_allow_html=True)
st.title("✏️ Trợ lý Luyện Đọc Tiếng Việt Lớp 1 - 5")
st.caption("Dữ liệu chấm điểm được tự động đồng bộ về Bảng tổng hợp của nhà trường")


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
        "action": "reading", "record_id": row["Mã bản ghi"],
        "time": row["Thời gian"], "class_name": row["Lớp"], "grade": row["Khối"],
        "student_name": row["Họ và tên"], "lesson_code": row["Mã bài"], "lesson_title": row["Bài đọc"],
        "wpm": row["Tốc độ (WPM)"], "errors": row["Từ cần rèn"],
        "score": row["Điểm TT27"], "evaluation": row["Đánh giá"],
        "accuracy": row["Độ chính xác (%)"], "heard": row["Nhận dạng được"],
    })


def save_comprehension_to_sheet(record_id, answer, level_text):
    """Cập nhật kết quả đọc hiểu vào ĐÚNG dòng đã ghi trước đó (tìm theo record_id)."""
    return _post_webhook({"action": "comprehension", "record_id": record_id,
                          "comprehension": level_text, "comprehension_answer": answer})


# =====================================================================
# 3. GIỌNG ĐỌC MẪU (giọng thần kinh tiếng Việt)
# =====================================================================
@st.cache_data(show_spinner=False, max_entries=60)
def synth_edge(text, voice, rate):
    """Giọng thần kinh Microsoft (giọng Bắc). Lỗi thì raise để không bị lưu vào cache."""
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


def align(ref_text, heard_text):
    """So khớp từng tiếng. Trả về (danh sách (hiển thị, trạng thái), điểm 'đúng' đã tính)."""
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
            # Ghép từng tiếng với tiếng nghe được giống nhất trong cùng đoạn.
            # Giống nhau khi bỏ dấu, hoặc rất gần nhau -> "gần đúng" (giọng trẻ em máy dễ nghe lệch).
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
                if best_j is not None and best_r >= NEAR_RATIO:
                    status[k] = "near"
                    used.add(best_j)
    credit = sum(1.0 if s == "ok" else NEAR_CREDIT if s == "near" else 0 for s in status)
    full = {i: s for i, s in zip(idx, status)}
    out = [(ref_tokens[i], full.get(i, "ok")) for i in range(len(ref_tokens))]
    return out, credit, status


def round_half(x):
    return round(x * 2) / 2


def grade(status, credit, speaking_seconds, target):
    total = len(status)
    accuracy = credit / total if total else 0
    read_count = sum(1 for s in status if s in ("ok", "near"))   # số tiếng em đã đọc ra
    wpm = round(read_count / (speaking_seconds / 60)) if speaking_seconds > 0 else 0
    speed = min(wpm / target, 1.0) if target else 0
    eff = min(accuracy / FULL_ACCURACY, 1.0)          # đọc đúng >= 90% là trọn điểm phần đọc đúng
    score = max(0.0, min(4.0, round_half(4 * (W_ACCURACY * eff + W_SPEED * speed))))
    if accuracy < 0.5:
        score = min(score, 1.5)                        # đọc đúng chưa tới một nửa thì chưa thể hoàn thành
    elif accuracy < 0.8:
        score = min(score, 3.0)                        # chưa đạt mức "tốt" thì tối đa 3 điểm
    if score >= 3.5 and accuracy >= 0.8:
        rating = "Hoàn thành tốt (T)"
    elif score >= 2.0 and accuracy >= 0.5:
        rating = "Hoàn thành (H)"
    else:
        rating = "Chưa hoàn thành (C)"
    return accuracy, wpm, score, rating


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


def evaluate(ref_text, wav_bytes, target_wpm):
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
        tokens, credit, status = align(ref_text, a)
        if best is None or credit > best[1]:
            best = (tokens, credit, status, a)
    tokens, credit, status, heard = best

    if status and sum(1 for s in status if s != "miss") / len(status) < MIN_RECOGNIZED:
        return {"err": "Máy chưa nghe đủ rõ để chấm công bằng. Con ghi âm lại một lần nữa nhé. "
                       "Nếu vẫn chưa được, con đọc trực tiếp cho cô giáo nghe."}
    accuracy, wpm, score, rating = grade(status, credit, speaking, target_wpm)
    wrong = [norm_token(t) for t, s in tokens if s == "miss"]
    near = [norm_token(t) for t, s in tokens if s == "near"]
    uniq = lambda xs: list(dict.fromkeys(xs))
    return dict(err="", tokens=tokens, accuracy=accuracy, wpm=wpm, score=score, rating=rating, heard=heard,
                wrong=uniq(wrong), near=uniq(near), total=len(status), speaking=speaking,
                n_ok=sum(1 for s in status if s == "ok"), n_near=sum(1 for s in status if s == "near"),
                n_miss=sum(1 for s in status if s == "miss"))


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


def check_answer(answer, lesson_text, expected):
    words = _words(answer)
    ideas = _split_ideas(expected)
    hit, missing, no_dau, typo = [], [], False, False
    for idea in ideas:
        kws = _keywords(idea)
        ms = [_word_match(k, words) for k in kws]
        ok = sum(1 for m in ms if m)
        if kws and ok / len(kws) >= 0.6:
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
col_class, col_name = st.columns([1, 2])
with col_class:
    selected_class = st.text_input("Lớp học:", placeholder="Ví dụ: 2A1").strip().upper()
with col_name:
    student_name = st.text_input("Họ và tên học sinh:", placeholder="Ví dụ: Nguyễn Văn An")

# Tự gợi ý khối theo số đầu của tên lớp (2A1 -> Lớp 2); em vẫn có thể đổi tay
grade_labels = list(GRADES)
guess = f"Lớp {selected_class[0]}" if selected_class[:1] in GRADE_OF.values() else None
default_idx = grade_labels.index(guess) if guess in grade_labels else 0

col_grade, col_term, col_week = st.columns([1, 1.3, 2])
with col_grade:
    grade_label = st.selectbox("Khối:", grade_labels, index=default_idx, key=f"grade_{selected_class[:1]}")
grade_key = GRADES[grade_label]
grade_num = GRADE_OF[grade_key]
weeks = CURRICULUM[grade_key]

with col_term:
    selected_term = st.selectbox("Kỳ học:", ["Học kỳ 1 (Tuần 1 - 18)", "Học kỳ 2 (Tuần 19 - 35)"])
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

st.markdown("---")
st.markdown(f"### 📖 {lesson['title']}")
st.markdown(f'<div class="reading-box" translate="no">{lesson["text"]}</div>', unsafe_allow_html=True)
if lesson.get("difficult_words"):
    st.caption("Từ cần chú ý khi đọc: " + " · ".join(lesson["difficult_words"]))

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
            st.warning("Giọng Bắc chất lượng cao đang không kết nối được, app tạm dùng giọng dự phòng của Google.")
            st.caption(f"Chi tiết kỹ thuật: {edge_err[:300]}")
    except Exception:
        st.warning("Chưa tạo được giọng đọc chất lượng cao, tạm dùng giọng của trình duyệt.")
        browser_tts_button(lesson["text"])

# ---- Ghi âm và chấm điểm ----
st.markdown("---")
st.markdown("### 🎙️ Luyện đọc và Đánh giá kết quả")
st.caption("Bấm micro, đọc to cả đoạn văn ở nơi yên tĩnh, rồi bấm dừng.")
st.session_state.setdefault("rec_n", 0)


def reset_recording():
    """Xóa bản ghi âm cũ để học sinh ghi âm lại mà không cần tải lại trang."""
    st.session_state["rec_n"] += 1
    st.session_state.pop("result_key", None)
    st.session_state.pop("result", None)


# key có mã bài -> đổi bài/đổi khối thì ô ghi âm tự làm mới, không chấm nhầm bản ghi của bài trước
audio_file = st.audio_input("Ghi âm giọng đọc của học sinh:", key=f"audio_{st.session_state['rec_n']}_{lesson_id}")

if audio_file:
    if not student_name.strip() or not selected_class:
        st.warning("⚠️ Con hãy nhập đầy đủ Lớp và Họ và tên ở phía trên trước khi nộp bài nhé!")
        st.stop()

    wav_bytes = audio_file.getvalue()
    key = hashlib.md5(wav_bytes + student_name.strip().encode() + lesson_id.encode()).hexdigest()

    # Chỉ chấm và ghi 1 lần cho mỗi bản ghi âm (tránh trùng khi app chạy lại)
    if st.session_state.get("result_key") != key:
        with st.spinner("Bạn Bút Chì đang lắng nghe và chấm bài..."):
            res = evaluate(lesson["text"], wav_bytes, target_wpm)
            if not res["err"]:
                record_id = key[:10] + datetime.now().strftime("%y%m%d%H%M%S")
                res["record_id"] = record_id
                row = {
                    "Mã bản ghi": record_id,
                    "Thời gian": datetime.now().strftime("%d/%m/%Y %H:%M"),
                    "Lớp": selected_class, "Khối": grade_num, "Họ và tên": student_name.strip(),
                    "Mã bài": lesson_id, "Bài đọc": lesson["title"],
                    "Tốc độ (WPM)": res["wpm"],
                    "Từ cần rèn": ", ".join((res["wrong"] + res["near"])[:8]) or "Không có",
                    "Điểm TT27": res["score"], "Đánh giá": res["rating"],
                    "Độ chính xác (%)": round(res["accuracy"] * 100), "Nhận dạng được": res["heard"],
                }
                res["saved"], res["save_err"] = save_score_to_sheet(row)
            st.session_state["result_key"], st.session_state["result"] = key, res
            if not res["err"]:
                st.balloons()

    res = st.session_state["result"]
    if res["err"]:
        st.error(res["err"])
        st.button("🔄 Ghi âm lại", type="primary", on_click=reset_recording, key="retry_err")
        st.stop()

    st.markdown("## 🌟 Kết quả Đánh giá Tiếng Việt")
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
    st.button("🔄 Ghi âm lại (đọc lần nữa)", type="primary" if res["rating"].startswith("Chưa") else "secondary",
              on_click=reset_recording, key="retry_ok")

    st.markdown("### 💬 Bài đọc của em")
    st.markdown(f'<div class="reading-box" translate="no">{render_marked(res["tokens"])}</div>', unsafe_allow_html=True)
    st.caption("Màu xanh: đọc đúng · Nền vàng: đọc gần đúng (chưa chuẩn dấu) · Nền đỏ: cần đọc lại")
    st.markdown("### 📝 Nhận xét (theo Thông tư 27/2020/TT-BGDĐT)")
    cm = build_comment(student_name.strip(), lesson["title"], res, target_wpm)
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

    with st.expander("Cách chấm điểm (để thầy cô và phụ huynh tham khảo)"):
        st.markdown(f"""
- **Điểm = {int(W_ACCURACY*100)}% đọc đúng + {int(W_SPEED*100)}% tốc độ**, làm tròn đến 0,5 điểm. Chủ yếu chấm việc đọc đúng, tròn vành rõ chữ.
- **Đọc đúng:** đọc đúng từ {int(FULL_ACCURACY*100)}% số tiếng trở lên là được trọn điểm phần này. Tiếng đúng được 1; tiếng gần đúng (máy có thể nghe lệch dấu hoặc âm do giọng trẻ em) được {NEAR_CREDIT}; tiếng sót hoặc sai được 0. Đọc thêm hoặc lặp từ không bị trừ điểm.
- **Tốc độ:** tính trên thời gian em thực sự đọc (đã bỏ khoảng lặng lúc bắt đầu và kết thúc). Mức chuẩn của {grade_label} là **{target_wpm} tiếng/phút**.
- Máy được xét nhiều cách nghe khác nhau và lấy cách khớp bài nhất để tránh phạt oan. Nếu máy nghe không rõ, bài sẽ **không được chấm** để em ghi âm lại.
- **Mức đánh giá** theo Thông tư 27: **Hoàn thành tốt (T)** khi đọc đúng từ 80% số tiếng; **Hoàn thành (H)** khi đọc đúng từ 50%; dưới 50% là **Chưa hoàn thành (C)**. Điểm /4 chỉ để tham khảo.
- Kết quả do máy chấm chỉ mang tính **gợi ý**; giáo viên là người đánh giá cuối cùng.""")
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
            cr = check_answer(answer_input, lesson["text"], lesson["expected_answer"])
            kind, paras = comprehension_feedback(cr, student_name.strip())
            body = "".join(f"<p>{p}</p>" for p in paras)
            (st.success if kind == "success" else st.warning)("🎉 Con trả lời đúng rồi!" if kind == "success"
                                                              else "Con thử lại nhé!")
            st.markdown(f'<div class="comment">{body}</div>', unsafe_allow_html=True)
            # Ghi kết quả đọc hiểu vào đúng dòng của bài đọc này trong Google Sheet
            if res.get("record_id"):
                ok, err = save_comprehension_to_sheet(res["record_id"], answer_input.strip(), COMP_LABEL[cr["level"]])
                if not ok and err:
                    st.caption(f"(Chưa ghi được kết quả đọc hiểu vào Sheet: {err})")
            if cr["level"] != "sai":
                with st.expander("Xem câu trả lời mẫu"):
                    st.markdown(cr["sample"])
