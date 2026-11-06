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
# Tốc độ đọc chuẩn (tiếng/phút) dùng để tính điểm - thầy/cô có thể chỉnh
TARGET_WPM = {"Học kỳ 1": 30, "Học kỳ 2": 40}
W_ACCURACY, W_SPEED = 0.85, 0.15     # điểm = 85% đọc đúng + 15% tốc độ (ưu tiên đọc đúng, tròn chữ)
FULL_ACCURACY = 0.90                 # đọc đúng từ 90% số tiếng trở lên là đã được trọn điểm phần "đọc đúng"
NEAR_CREDIT = 0.75                   # tiếng đọc gần đúng (máy nghe lệch dấu/âm) được 0.75 tiếng
NEAR_RATIO = 0.75                    # độ giống tối thiểu để tính là "gần đúng"
MIN_SECONDS = 3.0                    # ghi âm ngắn hơn mức này -> yêu cầu ghi lại
MIN_RECOGNIZED = 0.20                # máy nghe được dưới 20% bài -> coi là chưa nghe rõ, không chấm

VOICES = {"Cô Hoài My (giọng nữ, giọng Bắc)": "vi-VN-HoaiMyNeural",
          "Thầy Nam Minh (giọng nam, giọng Bắc)": "vi-VN-NamMinhNeural"}
SPEEDS = {"Đọc chậm (cho em tập đọc)": "-20%", "Đọc vừa": "-8%"}

st.set_page_config(page_title="Luyện đọc Lớp 2 - Tiểu học Thái Hòa", page_icon="✏️", layout="centered")

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
st.title("✏️ Trợ lý Luyện Đọc Tiếng Việt Lớp 2")
st.caption("Dữ liệu chấm điểm được tự động đồng bộ về Bảng tổng hợp của nhà trường")


# =====================================================================
# 2. GHI ĐIỂM VÀO GOOGLE SHEET
# =====================================================================
def _secret(name, default=""):
    try:
        return st.secrets.get(name, default)
    except Exception:
        return default


def save_score_to_sheet(row):
    url = _secret("WEBHOOK_URL")
    if not url:
        return False, "Chưa cấu hình WEBHOOK_URL trong Secrets."
    payload = {
        "key": _secret("WEBHOOK_KEY"),
        "time": row["Thời gian"], "class_name": row["Lớp"], "student_name": row["Họ và tên"],
        "lesson_title": row["Bài đọc"], "wpm": row["Tốc độ (WPM)"], "errors": row["Từ cần rèn"],
        "score": row["Điểm TT27"], "evaluation": row["Đánh giá"],
        "accuracy": row["Độ chính xác (%)"], "heard": row["Nhận dạng được"],
    }
    try:
        r = requests.post(url, json=payload, timeout=20)
        if r.status_code == 200 and r.text.strip().lower().startswith("ok"):
            return True, ""
        return False, f"Máy chủ trả về {r.status_code}: {r.text[:150]}"
    except Exception as e:
        return False, str(e)


# =====================================================================
# 3. GIỌNG ĐỌC MẪU (giọng thần kinh tiếng Việt)
# =====================================================================
@st.cache_data(show_spinner=False, max_entries=60)
def synth_vi(text, voice, rate):
    """Tạo file mp3 đọc mẫu. Lỗi thì raise để không bị lưu vào cache."""
    errors = []
    try:  # Ưu tiên: giọng thần kinh Microsoft (tự nhiên, có giọng nam/nữ)
        import edge_tts

        async def run():
            buf = b""
            comm = edge_tts.Communicate(text, voice, rate=rate)
            async for chunk in comm.stream():
                if chunk["type"] == "audio":
                    buf += chunk["data"]
            return buf

        loop = asyncio.new_event_loop()
        try:
            data = loop.run_until_complete(run())
        finally:
            loop.close()
        if data:
            return data, "edge"
        errors.append("edge-tts không trả về âm thanh")
    except Exception as e:
        errors.append(f"edge-tts: {e}")
    try:  # Dự phòng: Google dịch
        from gtts import gTTS
        buf = io.BytesIO()
        gTTS(text=text, lang="vi").write_to_fp(buf)
        return buf.getvalue(), "gtts"
    except Exception as e:
        errors.append(f"gTTS: {e}")
    raise RuntimeError(" | ".join(errors))


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


def grade(status, credit, speaking_seconds, term):
    total = len(status)
    accuracy = credit / total if total else 0
    read_count = sum(1 for s in status if s in ("ok", "near"))   # số tiếng em đã đọc ra
    wpm = round(read_count / (speaking_seconds / 60)) if speaking_seconds > 0 else 0
    target = TARGET_WPM.get(term, 40)
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


def build_comment(name, lesson_title, res, term):
    """Nhận xét theo tinh thần Thông tư 27/2020/TT-BGDĐT: mức đạt, kết quả, ưu điểm, điểm cần cố gắng, hướng khắc phục."""
    rating = res["rating"]
    pct = round(res["accuracy"] * 100)
    n_read = res["n_ok"] + res["n_near"]
    target = TARGET_WPM.get(term, 30)
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
    elif wpm > 130:
        weaknesses.append("Em đọc hơi nhanh, cần đọc chậm lại để rõ từng tiếng.")
    if not weaknesses:
        weaknesses.append("Chưa thấy hạn chế đáng kể ở bài đọc này.")

    plan = []
    if need:
        plan.append("Đọc chậm từng tiếng còn sai (mỗi tiếng 3 lần), sau đó ghép vào cả câu; nghe đọc mẫu rồi đọc theo.")
    if wpm < target * 0.7:
        plan.append("Đọc thành tiếng bài đọc khoảng 5–10 phút mỗi ngày, tập đọc theo cụm từ để đọc trôi chảy hơn.")
    if wpm > 130:
        plan.append("Đọc chậm hơn, ngắt nghỉ ở dấu phẩy, dấu chấm.")
    if is_t and not plan:
        plan.append("Tiếp tục duy trì, đọc thêm các bài khác để đọc diễn cảm hơn.")
    if not (is_t or is_h):
        plan.append("Nghe đọc mẫu và đọc lại bài; gia đình và giáo viên hỗ trợ em luyện đọc thêm.")
    return dict(level=rating, result=result, strengths=strengths, weaknesses=weaknesses, plan=plan)


def render_marked(tokens):
    cls = {"ok": "w-ok", "near": "w-near", "miss": "w-miss"}
    return " ".join(f'<span class="{cls[s]}">{t}</span>' for t, s in tokens)


def evaluate(ref_text, wav_bytes, term):
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
    accuracy, wpm, score, rating = grade(status, credit, speaking, term)
    wrong = [norm_token(t) for t, s in tokens if s == "miss"]
    near = [norm_token(t) for t, s in tokens if s == "near"]
    uniq = lambda xs: list(dict.fromkeys(xs))
    return dict(err="", tokens=tokens, accuracy=accuracy, wpm=wpm, score=score, rating=rating, heard=heard,
                wrong=uniq(wrong), near=uniq(near), total=len(status), speaking=speaking,
                n_ok=sum(1 for s in status if s == "ok"), n_near=sum(1 for s in status if s == "near"),
                n_miss=sum(1 for s in status if s == "miss"))


# =====================================================================
# 5. KHO BÀI ĐỌC 35 TUẦN GDPT 2018
# =====================================================================
curriculum_data = {
    "Tuần 1: Tôi là học sinh lớp 2": {
        "term": "Học kỳ 1", "title": "Ngày đầu năm học mới",
        "text": "Ngày khai trường đã đến. Sáng sớm, mẹ gọi em dậy sớm hơn mọi ngày. Em mặc bộ đồng phục mới tinh, háo hức cùng mẹ bước tới trường trong ánh nắng sớm ấm áp.",
        "word_count": 34, "difficult_words": ["khai trường", "đồng phục", "háo hức"],
        "question": "Sáng sớm ngày khai trường, bạn nhỏ cảm thấy thế nào?", "expected_answer": "háo hức"
    },
    "Tuần 2: Phần thưởng": {
        "term": "Học kỳ 1", "title": "Tấm lòng thơm thảo",
        "text": "Na là một cô bé tốt bụng, luôn sẵn lòng giúp đỡ bạn bè. Giờ ra chơi, thấy Lan bị ngã đau, Na liền chạy tới ân cần đỡ bạn dậy rồi dìu vào phòng y tế.",
        "word_count": 35, "difficult_words": ["tốt bụng", "sẵn lòng", "ân cần"],
        "question": "Khi thấy bạn Lan bị ngã, Na đã làm gì?", "expected_answer": "đỡ bạn dậy và dìu vào phòng y tế"
    },
    "Tuần 3: Làm việc thật là vui": {
        "term": "Học kỳ 1", "title": "Thế giới quanh em bận rộn",
        "text": "Quanh ta, mọi vật, mọi người đều làm việc. Đồng hồ tích tắc báo phút, báo giờ. Con gà trống gáy vang gọi mọi người thức dậy. Bé học bài, quét nhà giúp mẹ.",
        "word_count": 33, "difficult_words": ["tích tắc", "báo giờ", "gáy vang"],
        "question": "Con gà trống làm việc gì mỗi buổi sáng?", "expected_answer": "gáy vang gọi mọi người thức dậy"
    },
    "Tuần 4: Mỗi người một vẻ": {
        "term": "Học kỳ 1", "title": "Nụ cười của bé",
        "text": "Mỗi bạn trong lớp đều có một nét đáng yêu riêng. Bạn Nam có má lúm đồng tiền rất duyên. Bạn Hoa có đôi mắt đen láy và nụ cười tươi như hoa nở.",
        "word_count": 33, "difficult_words": ["đáng yêu", "lúm đồng tiền", "đen láy"],
        "question": "Bạn Hoa có đôi mắt và nụ cười như thế nào?", "expected_answer": "mắt đen láy và nụ cười tươi"
    },
    "Tuần 5: Ngôi trường mới": {
        "term": "Học kỳ 1", "title": "Trường em khang trang",
        "text": "Dưới ánh nắng vàng rực rỡ, ngôi trường mới hiện lên với những bức tường quét vôi vàng, mái ngói đỏ tươi. Hàng cây bàng xanh mướt đu đưa reo vui trong gió thu mát lành.",
        "word_count": 33, "difficult_words": ["rực rỡ", "bức tường", "ngói đỏ"],
        "question": "Ngôi trường mới có mái ngói màu gì?", "expected_answer": "ngói đỏ tươi"
    },
    "Tuần 6: Giờ ra chơi": {
        "term": "Học kỳ 1", "title": "Sân trường rộn rã",
        "text": "Tùng, tùng, tùng! Trống báo giờ ra chơi đã điểm. Từ các cửa lớp, học sinh ùa ra sân như bầy chim non. Dưới bóng râm cây bàng, các bạn nữ đang nhảy dây thoăn thoắt.",
        "word_count": 34, "difficult_words": ["chim non", "bóng râm", "thoăn thoắt"],
        "question": "Dưới bóng râm cây bàng, các bạn nữ đang chơi trò gì?", "expected_answer": "nhảy dây"
    },
    "Tuần 7: Người thầy mẫu mực": {
        "term": "Học kỳ 1", "title": "Thầy giáo của em",
        "text": "Thầy giáo bước vào lớp với nụ cười hiền hậu. Giọng thầy ấm áp, truyền cảm khi hướng dẫn từng nét chữ. Thầy luôn kiên nhẫn uốn nắn bàn tay nhỏ xinh của từng bạn học sinh.",
        "word_count": 34, "difficult_words": ["hiền hậu", "ấm áp", "truyền cảm"],
        "question": "Khi hướng dẫn học sinh viết chữ, giọng thầy giáo như thế nào?", "expected_answer": "ấm áp và truyền cảm"
    },
    "Tuần 8: Bàn tay dịu dàng": {
        "term": "Học kỳ 1", "title": "Lời thầy động viên",
        "text": "Thầy giáo đặt bàn tay dịu dàng lên vai An. Thầy không trách mắng mà nhẹ nhàng khuyên bảo: 'Cố lên em nhé, thầy tin lần sau em sẽ làm bài tốt hơn rất nhiều!'.",
        "word_count": 32, "difficult_words": ["dịu dàng", "trách mắng", "khuyên bảo"],
        "question": "Thầy giáo đã đặt bàn tay lên đâu của bạn An?", "expected_answer": "lên vai An"
    },
    "Tuần 9: Ôn tập giữa học kỳ 1": {
        "term": "Học kỳ 1", "title": "Em chăm chỉ luyện đọc",
        "text": "Hôm nay là buổi ôn tập. Cả lớp trật tự ngồi nghe cô giáo gọi từng bạn đọc bài. Bạn nào cũng cố gắng đọc to, rõ ràng và phát âm tròn vành rõ chữ.",
        "word_count": 33, "difficult_words": ["ôn tập", "trật tự", "tròn vành"],
        "question": "Trong buổi ôn tập, các bạn học sinh cố gắng đọc bài như thế nào?", "expected_answer": "đọc to, rõ ràng và phát âm tròn vành rõ chữ"
    },
    "Tuần 10: Bà nội, bà ngoại": {
        "term": "Học kỳ 1", "title": "Tình thương của bà",
        "text": "Bà em đã nhiều tuổi nhưng vẫn nhanh nhẹn. Mái tóc bà trắng như cước. Mỗi tối, bà thường ngồi bên chiếc chõng tre, quạt mát và kể chuyện cổ tích cho em nghe.",
        "word_count": 33, "difficult_words": ["nhanh nhẹn", "trắng như cước", "chõng tre"],
        "question": "Mái tóc của bà được ví trắng như thứ gì?", "expected_answer": "trắng như cước"
    },
    "Tuần 11: Mẹ": {
        "term": "Học kỳ 1", "title": "Bàn tay của mẹ",
        "text": "Bàn tay mẹ rám nắng vì vất vả sớm hôm chăm sóc gia đình. Những đêm hè oi ả, mẹ ngồi bên giường thức trắng đêm quạt mát cho con say giấc nồng ấm áp.",
        "word_count": 32, "difficult_words": ["rám nắng", "vất vả", "giấc nồng"],
        "question": "Đêm hè oi ả, mẹ làm gì cho con ngủ ngon?", "expected_answer": "quạt mát cho con"
    },
    "Tuần 12: Bố của em": {
        "term": "Học kỳ 1", "title": "Bờ vai vững chãi",
        "text": "Bố là người hùng trong mắt em. Chiều chiều đi làm về, bố thường sửa lại chiếc bàn học, dạy em tập đi xe đạp và dặn dò em phải luôn trung thực, dũng cảm.",
        "word_count": 34, "difficult_words": ["người hùng", "bàn học", "dũng cảm"],
        "question": "Bố đã dạy bạn nhỏ tập đi phương tiện gì?", "expected_answer": "xe đạp"
    },
    "Tuần 13: Anh em một nhà": {
        "term": "Học kỳ 1", "title": "Chia sẻ ngọt bùi",
        "text": "Mẹ đi chợ về mua cho hai anh em chùm nhãn chín mọng, ngọt lịm. Anh nhường quả to cho em, em lại biếu quả mọng cho anh. Cả hai anh em cùng mỉm cười rạng rỡ.",
        "word_count": 35, "difficult_words": ["chín mọng", "ngọt lịm", "rạng rỡ"],
        "question": "Mẹ đi chợ về đã mua loại quả gì cho hai anh em?", "expected_answer": "chùm nhãn chín mọng"
    },
    "Tuần 14: Bữa cơm gia đình": {
        "term": "Học kỳ 1", "title": "Không khí đầm ấm",
        "text": "Bữa cơm tối gia đình luôn đầy ắp tiếng cười vui vẻ. Em giúp mẹ dọn bát đũa sạch sẽ. Cả nhà quây quần bên mâm cơm ấm cúng, vừa ăn vừa chuyện trò rôm rả.",
        "word_count": 33, "difficult_words": ["đầy ắp", "quây quần", "rôm rả"],
        "question": "Trước giờ ăn cơm, bạn nhỏ đã giúp mẹ làm công việc gì?", "expected_answer": "dọn bát đũa"
    },
    "Tuần 15: Bạn trong nhà": {
        "term": "Học kỳ 1", "title": "Chú mèo mướp tinh khôn",
        "text": "Nhà em nuôi một chú mèo mướp rất đáng yêu. Bộ lông của chú mềm như nhung, bốn chân đi lại êm ru. Ban đêm, đôi mắt chú sáng rực như hai hòn ngọc canh gác kho thóc.",
        "word_count": 36, "difficult_words": ["mèo mướp", "mềm như nhung", "êm ru"],
        "question": "Đôi mắt của chú mèo ban đêm được so sánh với thứ gì?", "expected_answer": "hai hòn ngọc"
    },
    "Tuần 16: Con vật nuôi": {
        "term": "Học kỳ 1", "title": "Chú cún Vàng trung thành",
        "text": "Cún Vàng có đôi tai vểnh cao rất thính. Mỗi khi em đi học về đến đầu ngõ, chú đã mừng rỡ chạy xổ ra, ve vẩy chiếc đuôi cong tít đón chào cô chủ nhỏ.",
        "word_count": 34, "difficult_words": ["tai vểnh", "mừng rỡ", "cong tít"],
        "question": "Khi thấy bạn nhỏ đi học về, chú cún đã có hành động gì?", "expected_answer": "chạy ra và ve vẩy chiếc đuôi"
    },
    "Tuần 17: Cây xanh quanh em": {
        "term": "Học kỳ 1", "title": "Cây bàng trường em",
        "text": "Cây bàng sừng sững đứng giữa sân trường che bóng mát. Mùa đông, cành bàng khẳng khiu trút lá. Mùa xuân sang, những búp non xanh biếc bắt đầu nhú ra như những ngọn nến lung linh.",
        "word_count": 34, "difficult_words": ["sừng sững", "khẳng khiu", "lung linh"],
        "question": "Vào mùa xuân, những búp non của cây bàng nhú ra trông giống cái gì?", "expected_answer": "những ngọn nến"
    },
    "Tuần 18: Ôn tập cuối học kỳ 1": {
        "term": "Học kỳ 1", "title": "Mùa đông ấm áp",
        "text": "Gió bấc thổi từng cơn se lạnh trên phố phường. Mọi người đều mặc áo len, quàng khăn ấm. Dưới mái ấm gia đình, ngọn đèn vàng tỏa sáng lung linh sưởi ấm căn phòng nhỏ.",
        "word_count": 33, "difficult_words": ["gió bấc", "se lạnh", "sưởi ấm"],
        "question": "Vào ngày mùa đông se lạnh, mọi người thường mặc trang phục gì?", "expected_answer": "áo len và quàng khăn ấm"
    },
    "Tuần 19: Mùa xuân đến rồi": {
        "term": "Học kỳ 2", "title": "Khúc ca xuân",
        "text": "Mùa xuân mang theo mưa bụi lất phất làm tươi tốt muôn cây. Trên cành xoan, bầy chim sâu ríu rít chuyền cành hát ca. Không gian bừng sáng ngập tràn sắc hoa rực rỡ sắc màu.",
        "word_count": 34, "difficult_words": ["lất phất", "tươi tốt", "ríu rít"],
        "question": "Những hạt mưa xuân được miêu tả như thế nào?", "expected_answer": "mưa bụi lất phất"
    },
    "Tuần 20: Tết quê em": {
        "term": "Học kỳ 2", "title": "Chợ hoa ngày Tết",
        "text": "Sáng ba mươi Tết, chợ hoa tấp nập người qua lại. Những cành đào phai chúm chím nụ hồng, chậu quất trĩu trịt quả vàng ươm hứa hẹn một năm mới bình an, may mắn.",
        "word_count": 32, "difficult_words": ["tấp nập", "chúm chím", "trĩu trịt"],
        "question": "Những chậu quất trong chợ hoa có đặc điểm gì nổi bật?", "expected_answer": "trĩu trịt quả vàng ươm"
    },
    "Tuần 21: Muôn loài chim": {
        "term": "Học kỳ 2", "title": "Tiếng hót chim rừng",
        "text": "Rừng ban mai vang lừng tiếng hót. Chim chích chòe thoăn thoắt chuyền cành. Chú bồ chao liến thoắng hót vang. Tất cả cùng hòa tấu nên một bản hòa ca rộn rã núi rừng.",
        "word_count": 32, "difficult_words": ["vang lừng", "thoăn thoắt", "liến thoắng"],
        "question": "Chú chim nào chuyền cành thoăn thoắt trong rừng ban mai?", "expected_answer": "chim chích chòe"
    },
    "Tuần 22: Rừng xanh muôn màu": {
        "term": "Học kỳ 2", "title": "Bác gấu hiền lành",
        "text": "Trong cánh rừng già rợp bóng cây cổ thụ, muông thú sống rất hòa thuận bên nhau. Bác gấu đen to lớn nhưng tính tình rất hiền lành, luôn chia sẻ mật ong ngọt cho muôn loài.",
        "word_count": 35, "difficult_words": ["cổ thụ", "muông thú", "mật ong"],
        "question": "Bác gấu đen đã chia sẻ món quà gì ngọt ngào cho muôn loài?", "expected_answer": "mật ong ngọt"
    },
    "Tuần 23: Sông nước quê hương": {
        "term": "Học kỳ 2", "title": "Dòng sông tuổi thơ",
        "text": "Dòng sông quê em uốn lượn như dải lụa mềm mại hiền hòa. Nước sông trong vắt in bóng mây trời. Buổi chiều, lũ trẻ rủ nhau tắm mát và ngắm nhìn những cánh buồm căng gió.",
        "word_count": 33, "difficult_words": ["uốn lượn", "dải lụa", "trong vắt"],
        "question": "Dòng sông quê hương được so sánh với vật gì?", "expected_answer": "dải lụa mềm mại"
    },
    "Tuần 24: Biển đảo quê hương": {
        "term": "Học kỳ 2", "title": "Bình minh trên biển",
        "text": "Mặt trời từ từ nhô lên đỏ rực như quả cầu lửa khổng lồ. Từng đoàn thuyền đánh cá nối đuôi nhau hân hoan trở về bến, khoang thuyền đầy ắp những mẻ tôm cá tươi rói.",
        "word_count": 33, "difficult_words": ["nhô lên", "hân hoan", "tươi rói"],
        "question": "Mặt trời mọc trên biển được so sánh với hình ảnh nào?", "expected_answer": "quả cầu lửa khổng lồ"
    },
    "Tuần 25: Bác Hồ kính yêu": {
        "term": "Học kỳ 2", "title": "Tình thương của Bác",
        "text": "Bác Hồ luôn dành tình yêu thương bao la cho các cháu thiếu nhi. Trong vườn Bác, hoa ngát hương thơm. Bác thường dành thời gian chia kẹo và dặn các cháu phải chăm ngoan học giỏi.",
        "word_count": 34, "difficult_words": ["bao la", "thiếu nhi", "ngát hương"],
        "question": "Bác Hồ thường dặn dò các cháu thiếu nhi điều gì?", "expected_answer": "phải chăm ngoan học giỏi"
    },
    "Tuần 26: Ai ngoan sẽ được thưởng": {
        "term": "Học kỳ 2", "title": "Lòng trung thực",
        "text": "Cậu bé Tộ dũng cảm đứng lên nhận lỗi khi vô tình làm vỡ chậu hoa. Thầy giáo mỉm cười xoa đầu khen ngợi vì bạn đã có lòng dũng cảm và đức tính thật thà đáng quý.",
        "word_count": 34, "difficult_words": ["dũng cảm", "nhận lỗi", "thật thà"],
        "question": "Vì sao bạn nhỏ lại được thầy giáo xoa đầu khen ngợi?", "expected_answer": "vì dũng cảm nhận lỗi và thật thà"
    },
    "Tuần 27: Ôn tập giữa học kỳ 2": {
        "term": "Học kỳ 2", "title": "Hội thi hoa xuân",
        "text": "Mùa xuân, các loài hoa cùng nhau đua nhau khoe sắc thắm. Hoa mai vàng rạng rỡ phương Nam, hoa đào phai thắm đượm phương Bắc, dâng tặng hương thơm ngào ngạt cho đời thêm tươi vui.",
        "word_count": 33, "difficult_words": ["khoe sắc", "rạng rỡ", "ngào ngạt"],
        "question": "Loài hoa nào tượng trưng cho mùa xuân ở phương Bắc?", "expected_answer": "hoa đào phai"
    },
    "Tuần 28: Đất nước tươi đẹp": {
        "term": "Học kỳ 2", "title": "Non sông gấm vóc",
        "text": "Đất nước Việt Nam trải dài với bao danh lam thắng cảnh tuyệt đẹp. Có ruộng bậc thang uốn lượn ngút ngàn, có biển xanh cát trắng nắng vàng rực rỡ bốn mùa thân thương.",
        "word_count": 31, "difficult_words": ["danh lam", "thắng cảnh", "ngút ngàn"],
        "question": "Đất nước ta có những thắng cảnh đặc trưng nào được nhắc tới?", "expected_answer": "ruộng bậc thang và biển xanh cát trắng"
    },
    "Tuần 29: Quê hương mến yêu": {
        "term": "Học kỳ 2", "title": "Cánh đồng quê em",
        "text": "Cánh đồng lúa chín vàng rực trải rộng mênh mông bát ngát. Hương lúa mới thoang thoảng bay theo ngọn gió. Các bác nông dân phấn khởi gặt hái những bông lúa trĩu hạt nặng trĩu.",
        "word_count": 32, "difficult_words": ["bát ngát", "thoang thoảng", "trĩu hạt"],
        "question": "Hương lúa mới chín thoang thoảng bay theo thứ gì?", "expected_answer": "ngọn gió"
    },
    "Tuần 30: Nghề nghiệp ước mơ": {
        "term": "Học kỳ 2", "title": "Bác sĩ tương lai",
        "text": "Mai ước mơ sau này lớn lên sẽ trở thành một bác sĩ giỏi. Bạn muốn khoác lên mình chiếc áo blouse trắng tinh khôi, tận tụy chữa lành bệnh và mang lại nụ cười cho mọi người.",
        "word_count": 34, "difficult_words": ["ước mơ", "tinh khôi", "tận tụy"],
        "question": "Bạn Mai ước mơ sau này lớn lên sẽ làm nghề gì?", "expected_answer": "bác sĩ"
    },
    "Tuần 31: Chú bộ đội cụ Hồ": {
        "term": "Học kỳ 2", "title": "Người lính đảo xa",
        "text": "Nơi đảo xa đầu sóng ngọn gió, chú bộ đội hải quân ngày đêm bồng súng đứng gác. Ánh mắt kiên định dõi nhìn ra biển cả, giữ bình yên vững chắc cho đất trời quê hương.",
        "word_count": 33, "difficult_words": ["đầu sóng", "hải quân", "kiên định"],
        "question": "Chú bộ đội hải quân làm nhiệm vụ ở địa bàn nào?", "expected_answer": "nơi đảo xa"
    },
    "Tuần 32: Bầu trời và vũ trụ": {
        "term": "Học kỳ 2", "title": "Vì sao lấp lánh",
        "text": "Đêm hè thanh vắng, bầu trời cao vời vợi thăm thẳm. Hàng ngàn ngôi sao nhấp nháy sáng lung linh như những viên kim cương lấp lánh đính trên tấm thảm nhung xanh thẫm huyền bí.",
        "word_count": 33, "difficult_words": ["vời vợi", "thăm thẳm", "lung linh"],
        "question": "Những ngôi sao ban đêm được ví với đồ vật quý giá nào?", "expected_answer": "viên kim cương"
    },
    "Tuần 33: Trái đất của chúng mình": {
        "term": "Học kỳ 2", "title": "Bảo vệ môi trường xanh",
        "text": "Trái đất là ngôi nhà chung xanh tươi của muôn loài. Em cùng các bạn tích cực nhặt rác sân trường, chăm sóc bồn hoa cây cảnh để giữ cho môi trường học đường luôn trong lành, sạch đẹp.",
        "word_count": 36, "difficult_words": ["ngôi nhà chung", "tích cực", "trong lành"],
        "question": "Để giữ môi trường sạch đẹp, bạn nhỏ cùng các bạn đã làm gì?", "expected_answer": "nhặt rác và chăm sóc bồn hoa"
    },
    "Tuần 34: Mùa hè rực rỡ": {
        "term": "Học kỳ 2", "title": "Tiếng ve gọi hè",
        "text": "Cây phượng vĩ thắp lửa đỏ rực một góc sân trường. Dàn đồng ca ve sầu râm ran cất tiếng hát báo hiệu một mùa hè sôi động, vui tươi và tràn ngập kỷ niệm đã về.",
        "word_count": 34, "difficult_words": ["phượng vĩ", "thắp lửa", "râm ran"],
        "question": "Cây hoa nào nở hoa đỏ rực báo hiệu mùa hè đến?", "expected_answer": "cây phượng vĩ"
    },
    "Tuần 35: Tạm biệt lớp 2": {
        "term": "Học kỳ 2", "title": "Nhớ mãi mái trường",
        "text": "Tiếng trống bế giảng năm học đã điểm. Tạm biệt lớp hai thân thương với bao kỷ niệm vui buồn. Em thầm hứa trong kỳ nghỉ hè sẽ chăm ngoan, chuẩn bị bước vào lớp ba vững vàng.",
        "word_count": 35, "difficult_words": ["bế giảng", "thân thương", "vững vàng"],
        "question": "Bạn nhỏ thầm hứa điều gì trong kỳ nghỉ hè sắp tới?", "expected_answer": "chăm ngoan và chuẩn bị vào lớp ba"
    }
}


# =====================================================================
# 5b. KHÓA ĐÁP ÁN ĐỌC HIỂU (mỗi bài: các ý cần có, mỗi ý có nhiều cách nói đúng)
#     "groups": mỗi nhóm là 1 ý; học sinh nói đúng 1 trong các cách của nhóm là được ý đó.
#     Trả lời được ít nhất 1 ý là ĐÚNG; được tất cả các ý là ĐẦY ĐỦ.
# =====================================================================
ANSWER_KEYS = {
    "Tuần 1: Tôi là học sinh lớp 2": {"sample": "Bạn nhỏ cảm thấy háo hức.",
        "groups": [["háo hức", "hào hứng", "phấn khởi", "vui mừng", "hồ hởi", "vui", "mừng"]]},
    "Tuần 2: Phần thưởng": {"sample": "Na đỡ bạn dậy và dìu bạn vào phòng y tế.",
        "groups": [["đỡ bạn dậy", "đỡ bạn", "đỡ lan", "đỡ", "nâng bạn", "giúp bạn đứng dậy"],
                   ["dìu bạn", "dìu", "phòng y tế", "y tế", "đưa bạn vào"]]},
    "Tuần 3: Làm việc thật là vui": {"sample": "Con gà trống gáy vang gọi mọi người thức dậy.",
        "groups": [["gáy vang", "gáy", "gọi mọi người thức dậy", "gọi mọi người dậy", "đánh thức mọi người"]]},
    "Tuần 4: Mỗi người một vẻ": {"sample": "Bạn Hoa có đôi mắt đen láy và nụ cười tươi như hoa nở.",
        "groups": [["đen láy", "mắt đen", "đôi mắt đen"],
                   ["nụ cười tươi", "cười tươi", "tươi như hoa", "hoa nở"]]},
    "Tuần 5: Ngôi trường mới": {"sample": "Ngôi trường mới có mái ngói màu đỏ tươi.",
        "groups": [["đỏ tươi", "màu đỏ", "đỏ"]]},
    "Tuần 6: Giờ ra chơi": {"sample": "Các bạn nữ đang nhảy dây.",
        "groups": [["nhảy dây"]]},
    "Tuần 7: Người thầy mẫu mực": {"sample": "Giọng thầy giáo ấm áp và truyền cảm.",
        "groups": [["ấm áp", "ấm", "dịu dàng"], ["truyền cảm"]]},
    "Tuần 8: Bàn tay dịu dàng": {"sample": "Thầy giáo đặt bàn tay lên vai bạn An.",
        "groups": [["vai bạn an", "vai an", "lên vai", "vai"]]},
    "Tuần 9: Ôn tập giữa học kỳ 1": {"sample": "Các bạn cố gắng đọc to, rõ ràng và phát âm tròn vành rõ chữ.",
        "groups": [["đọc to"], ["rõ ràng", "tròn vành rõ chữ", "tròn vành", "rõ chữ"]]},
    "Tuần 10: Bà nội, bà ngoại": {"sample": "Mái tóc bà trắng như cước.",
        "groups": [["trắng như cước", "như cước", "cước"]]},
    "Tuần 11: Mẹ": {"sample": "Mẹ ngồi bên giường quạt mát cho con.",
        "groups": [["quạt mát", "quạt cho con", "quạt"], ["thức trắng đêm", "thức trắng", "ngồi bên giường"]]},
    "Tuần 12: Bố của em": {"sample": "Bố dạy bạn nhỏ tập đi xe đạp.",
        "groups": [["xe đạp"]]},
    "Tuần 13: Anh em một nhà": {"sample": "Mẹ mua cho hai anh em chùm nhãn chín mọng.",
        "groups": [["chùm nhãn", "quả nhãn", "nhãn"]]},
    "Tuần 14: Bữa cơm gia đình": {"sample": "Bạn nhỏ giúp mẹ dọn bát đũa.",
        "groups": [["dọn bát đũa", "dọn bát", "bát đũa", "bát", "đũa"]]},
    "Tuần 15: Bạn trong nhà": {"sample": "Đôi mắt chú mèo được so sánh với hai hòn ngọc.",
        "groups": [["hai hòn ngọc", "hòn ngọc", "ngọc"]]},
    "Tuần 16: Con vật nuôi": {"sample": "Chú cún chạy ra và ve vẩy chiếc đuôi đón bạn nhỏ.",
        "groups": [["chạy xổ ra", "chạy ra", "chạy", "mừng rỡ", "chạy ra đón"],
                   ["ve vẩy", "vẫy đuôi", "vẩy đuôi", "đuôi"]]},
    "Tuần 17: Cây xanh quanh em": {"sample": "Những búp non nhú ra giống như những ngọn nến.",
        "groups": [["ngọn nến", "những ngọn nến", "nến"]]},
    "Tuần 18: Ôn tập cuối học kỳ 1": {"sample": "Mọi người mặc áo len và quàng khăn ấm.",
        "groups": [["áo len", "len"], ["quàng khăn", "khăn ấm", "khăn"]]},
    "Tuần 19: Mùa xuân đến rồi": {"sample": "Những hạt mưa xuân là mưa bụi lất phất.",
        "groups": [["mưa bụi", "lất phất", "mưa phùn"]]},
    "Tuần 20: Tết quê em": {"sample": "Những chậu quất trĩu trịt quả vàng ươm.",
        "groups": [["trĩu trịt", "trĩu", "vàng ươm", "quả vàng", "nhiều quả"]]},
    "Tuần 21: Muôn loài chim": {"sample": "Chim chích chòe chuyền cành thoăn thoắt.",
        "groups": [["chích chòe", "chim chích chòe", "chích choè"]]},
    "Tuần 22: Rừng xanh muôn màu": {"sample": "Bác gấu đen chia sẻ mật ong ngọt cho muôn loài.",
        "groups": [["mật ong ngọt", "mật ong", "mật"]]},
    "Tuần 23: Sông nước quê hương": {"sample": "Dòng sông được so sánh với dải lụa mềm mại.",
        "groups": [["dải lụa", "giải lụa", "lụa"]]},
    "Tuần 24: Biển đảo quê hương": {"sample": "Mặt trời mọc được so sánh với quả cầu lửa khổng lồ.",
        "groups": [["quả cầu lửa", "cầu lửa", "quả cầu"]]},
    "Tuần 25: Bác Hồ kính yêu": {"sample": "Bác dặn các cháu phải chăm ngoan, học giỏi.",
        "groups": [["chăm ngoan", "ngoan", "chăm chỉ"], ["học giỏi", "học tốt"]]},
    "Tuần 26: Ai ngoan sẽ được thưởng": {"sample": "Vì bạn dũng cảm nhận lỗi và thật thà.",
        "groups": [["dũng cảm", "nhận lỗi", "dám nhận lỗi"], ["thật thà", "trung thực", "thành thật"]]},
    "Tuần 27: Ôn tập giữa học kỳ 2": {"sample": "Ở phương Bắc là hoa đào phai.",
        "groups": [["hoa đào phai", "đào phai", "hoa đào", "đào"]]},
    "Tuần 28: Đất nước tươi đẹp": {"sample": "Đó là ruộng bậc thang và biển xanh cát trắng.",
        "groups": [["ruộng bậc thang", "bậc thang"], ["biển xanh", "cát trắng", "biển"]]},
    "Tuần 29: Quê hương mến yêu": {"sample": "Hương lúa mới bay theo ngọn gió.",
        "groups": [["ngọn gió", "gió"]]},
    "Tuần 30: Nghề nghiệp ước mơ": {"sample": "Bạn Mai ước mơ làm bác sĩ.",
        "groups": [["bác sĩ", "bác sỹ"]]},
    "Tuần 31: Chú bộ đội cụ Hồ": {"sample": "Chú bộ đội làm nhiệm vụ nơi đảo xa, đầu sóng ngọn gió.",
        "groups": [["đảo xa", "ngoài đảo", "hải đảo", "đầu sóng ngọn gió", "đảo"]]},
    "Tuần 32: Bầu trời và vũ trụ": {"sample": "Những ngôi sao được ví như những viên kim cương.",
        "groups": [["viên kim cương", "kim cương"]]},
    "Tuần 33: Trái đất của chúng mình": {"sample": "Bạn nhỏ cùng các bạn nhặt rác và chăm sóc bồn hoa.",
        "groups": [["nhặt rác", "dọn rác", "rác"], ["bồn hoa", "chăm sóc bồn hoa", "chăm sóc cây", "cây cảnh"]]},
    "Tuần 34: Mùa hè rực rỡ": {"sample": "Cây phượng vĩ nở hoa đỏ rực.",
        "groups": [["phượng vĩ", "hoa phượng", "cây phượng", "phượng"]]},
    "Tuần 35: Tạm biệt lớp 2": {"sample": "Bạn nhỏ hứa sẽ chăm ngoan và chuẩn bị bước vào lớp ba.",
        "groups": [["chăm ngoan", "ngoan", "chăm chỉ"], ["lớp ba", "lớp 3", "chuẩn bị", "bước vào lớp"]]},
}


def _words(text):
    return [w for w in (norm_token(t) for t in text.split()) if w]


def _phrase_match(phrase, words):
    """Tìm cụm từ trong câu trả lời. Trả về 'exact' | 'nodau' | 'typo' | None."""
    p = _words(phrase)
    n = len(p)
    if n == 0 or len(words) < n:
        return None
    best = None
    for i in range(len(words) - n + 1):
        win = words[i:i + n]
        if win == p:
            return "exact"
        if [strip_marks(x) for x in win] == [strip_marks(x) for x in p]:
            best = best or "nodau"
        elif all(strip_marks(a) == strip_marks(b) or (len(b) >= 3 and
                 difflib.SequenceMatcher(a=strip_marks(a), b=strip_marks(b)).ratio() >= 0.85)
                 for a, b in zip(win, p)):
            best = best or "typo"
    return best


def check_answer(answer, lesson_title, lesson_text, fallback_expected=""):
    words = _words(answer)
    key = ANSWER_KEYS.get(lesson_title)
    if key is None:   # bài chưa có khóa: dùng đáp án cũ
        key = {"sample": fallback_expected, "groups": [[fallback_expected]] if fallback_expected else []}
    hit, missing, no_dau, typo = [], [], False, False
    for g in key["groups"]:
        found = None
        for variant in g:
            m = _phrase_match(variant, words)
            if m == "exact":
                found = "exact"
                break
            if m and not found:
                found = m
        if found:
            hit.append(g[0])
            no_dau |= found == "nodau"
            typo |= found == "typo"
        else:
            missing.append(g[0])
    level = "sai" if not hit else ("daydu" if not missing else "dung")
    # Câu trong bài chứa đáp án -> dùng làm gợi ý khi em trả lời chưa đúng
    hint = None
    for sent in re.split(r"(?<=[.!?])\s+", lesson_text):
        sw = [strip_marks(w) for w in _words(sent)]
        if any(all(strip_marks(w) in sw for w in _words(v)) for g in key["groups"] for v in g if _words(v)):
            hint = sent
            break
    sample_len = max(1, len(_words(key["sample"])))
    return dict(level=level, hit=hit, missing=missing, no_dau=no_dau, typo=typo,
                too_long=len(words) > max(10, int(1.5 * sample_len) + 2), too_short=len(words) == 0,
                sample=key["sample"], hint=hint)


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


# =====================================================================
# 6. GIAO DIỆN
# =====================================================================
col_class, col_name = st.columns([1, 2])
with col_class:
    selected_class = st.text_input("Lớp học:", placeholder="Ví dụ: 2A1").strip().upper()
with col_name:
    student_name = st.text_input("Họ và tên học sinh:", placeholder="Ví dụ: Nguyễn Văn An")

col_term, col_week = st.columns([1, 2])
with col_term:
    selected_term = st.selectbox("Kỳ học:", ["Học kỳ 1 (Tuần 1 - 18)", "Học kỳ 2 (Tuần 19 - 35)"])
term_filter = "Học kỳ 1" if "Học kỳ 1" in selected_term else "Học kỳ 2"
filtered_lessons = [k for k, v in curriculum_data.items() if v["term"] == term_filter]
with col_week:
    selected_week = st.selectbox("📚 Chọn bài đọc:", filtered_lessons)
lesson = curriculum_data[selected_week]

st.markdown("---")
st.markdown(f"### 📖 Bài đọc: {lesson['title']}")
st.markdown(f'<div class="reading-box" translate="no">{lesson["text"]}</div>', unsafe_allow_html=True)

# ---- Nghe đọc mẫu ----
st.markdown("#### 🔊 Nghe Bạn Bút Chì đọc mẫu")
v1, v2 = st.columns(2)
with v1:
    voice_label = st.radio("Giọng đọc", list(VOICES), horizontal=False)
with v2:
    speed_label = st.radio("Tốc độ", list(SPEEDS), horizontal=False)

tts_key = f"{lesson['title']}|{voice_label}|{speed_label}"
if st.button("▶️ Nghe đọc mẫu", type="primary"):
    st.session_state["tts_play"] = tts_key
if st.session_state.get("tts_play") == tts_key:
    try:
        with st.spinner("Bạn Bút Chì đang chuẩn bị giọng đọc..."):
            audio_bytes, engine = synth_vi(lesson["text"], VOICES[voice_label], SPEEDS[speed_label])
        try:
            st.audio(audio_bytes, format="audio/mp3", autoplay=True)
        except TypeError:
            st.audio(audio_bytes, format="audio/mp3")
    except Exception as e:
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


audio_file = st.audio_input("Ghi âm giọng đọc của học sinh:", key=f"audio_{st.session_state['rec_n']}")

if audio_file:
    if not student_name.strip() or not selected_class:
        st.warning("⚠️ Con hãy nhập đầy đủ Lớp và Họ và tên ở phía trên trước khi nộp bài nhé!")
        st.stop()

    wav_bytes = audio_file.getvalue()
    key = hashlib.md5(wav_bytes + student_name.strip().encode() + lesson["title"].encode()).hexdigest()

    # Chỉ chấm và ghi 1 lần cho mỗi bản ghi âm (tránh trùng khi app chạy lại)
    if st.session_state.get("result_key") != key:
        with st.spinner("Bạn Bút Chì đang lắng nghe và chấm bài..."):
            res = evaluate(lesson["text"], wav_bytes, term_filter)
            if not res["err"]:
                row = {
                    "Thời gian": datetime.now().strftime("%d/%m/%Y %H:%M"),
                    "Lớp": selected_class, "Họ và tên": student_name.strip(), "Bài đọc": lesson["title"],
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
    st.caption(f"Điểm đọc thành tiếng tham khảo: {res['score']}/4,0")

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
    cm = build_comment(student_name.strip(), lesson["title"], res, term_filter)
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
- **Tốc độ:** tính trên thời gian em thực sự đọc (đã bỏ khoảng lặng lúc bắt đầu và kết thúc). Mức chuẩn là {TARGET_WPM['Học kỳ 1']} tiếng/phút (học kỳ 1) và {TARGET_WPM['Học kỳ 2']} tiếng/phút (học kỳ 2).
- Máy được xét nhiều cách nghe khác nhau và lấy cách khớp bài nhất để tránh phạt oan. Nếu máy nghe không rõ, bài sẽ **không được chấm** để em ghi âm lại.
- **Mức đánh giá** theo Thông tư 27: **Hoàn thành tốt (T)** khi đọc đúng từ 80% số tiếng; **Hoàn thành (H)** khi đọc đúng từ 50%; dưới 50% là **Chưa hoàn thành (C)**. Điểm /4 chỉ để tham khảo.
- Kết quả do máy chấm chỉ mang tính **gợi ý**; giáo viên là người đánh giá cuối cùng.""")
    with st.expander("Xem máy nghe được gì"):
        st.markdown(f'<div class="heard">{res["heard"]}</div>', unsafe_allow_html=True)

    st.markdown("---")
    st.markdown(f"### ❓ Câu hỏi đọc hiểu")
    st.markdown(f"**{lesson['question']}**")
    with st.form(key=f"form_{key}"):
        answer_input = st.text_input("Con gõ câu trả lời ngắn vào đây:", placeholder="Ví dụ: Bạn nhỏ cảm thấy ...")
        submitted = st.form_submit_button("✅ Kiểm tra câu trả lời", type="primary")
    if submitted:
        if not answer_input.strip():
            st.warning("Con hãy gõ câu trả lời rồi bấm “Kiểm tra câu trả lời” nhé.")
        else:
            cr = check_answer(answer_input, selected_week, lesson["text"], lesson["expected_answer"])
            kind, paras = comprehension_feedback(cr, student_name.strip())
            body = "".join(f"<p>{p}</p>" for p in paras)
            (st.success if kind == "success" else st.warning)("🎉 Con trả lời đúng rồi!" if kind == "success"
                                                              else "Con thử lại nhé!")
            st.markdown(f'<div class="comment">{body}</div>', unsafe_allow_html=True)
            if cr["level"] != "sai":
                with st.expander("Xem câu trả lời mẫu"):
                    st.markdown(cr["sample"])
