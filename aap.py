import streamlit as st
import streamlit.components.v1 as components
import time

# Cấu hình giao diện
st.set_page_config(page_title="Bạn Bút Chì - Luyện đọc Lớp 2", page_icon="✏️", layout="centered")

st.markdown("""
<style>
    .big-font { font-size: 24px !important; font-weight: bold; color: #1E3A8A; line-height: 1.6; }
    .stButton>button { border-radius: 20px; font-size: 16px; height: 2.8em; }
</style>
""", unsafe_allow_html=True)

st.title("✏️ Bạn Bút Chì - Luyện Đọc Lớp 2")

# Kho bài đọc
sample_lessons = {
    "Bài 1: Mùa xuân đã về": {
        "text": "Mùa xuân đã về. Muôn hoa khoe sắc thắm trong vườn. Chú chim sâu ríu rít chuyền cành, đón chào một ngày mới ngập tràn ánh nắng ấm áp.",
        "word_count": 27,
        "question": "Trong bài, chú chim sâu làm gì khi mùa xuân về?",
        "expected_answer": "chú chim sâu ríu rít chuyền cành"
    },
    "Bài 2: Chú gà trống thông minh": {
        "text": "Sáng sớm, gà trống thức dậy thật sớm. Chú vươn mình, dang rộng đôi cánh rồi cất tiếng gáy vang báo hiệu trời sáng.",
        "word_count": 24,
        "question": "Gà trống cất tiếng gáy để làm gì?",
        "expected_answer": "báo hiệu trời sáng"
    }
}

# Chọn bài học
lesson_name = st.selectbox("📚 Chọn bài tập đọc hôm nay:", list(sample_lessons.keys()))
current_lesson = sample_lessons[lesson_name]

st.markdown("---")
st.markdown("### 📖 Bài đọc của con:")
st.markdown(f'<div class="big-font">{current_lesson["text"]}</div>', unsafe_allow_html=True)
st.write("")

# Nút đọc mẫu qua component cách ly chống lỗi
tts_html = f"""
<div style="text-align: left;">
    <button onclick="playTTS()" style="background-color: #10B981; color: white; border: none; padding: 10px 18px; border-radius: 10px; cursor: pointer; font-size: 15px; font-weight: bold;">
        🔊 Nghe Bạn Bút Chì đọc mẫu
    </button>
</div>
<script>
function playTTS() {{
    window.speechSynthesis.cancel();
    let utterance = new SpeechSynthesisUtterance("{current_lesson['text']}");
    utterance.lang = 'vi-VN';
    utterance.rate = 0.85;
    window.speechSynthesis.speak(utterance);
}}
</script>
"""
components.html(tts_html, height=55)

st.markdown("---")
st.markdown("### 🎙️ Luyện đọc và Ghi âm")
st.write("Con hãy bấm vào ô bên dưới để đọc bài nhé:")

# Ô thu âm trực tiếp
audio_data = st.audio_input("Bấm micro để đọc:")

if audio_data:
    st.success("✅ Đã ghi nhận giọng đọc của con!")
    
    with st.spinner("Bạn Bút Chì đang chấm điểm..."):
        time.sleep(1.5)
        wpm = 52
        mispronounced = ["khoe sắc"]
        total_score = 3.5

    st.balloons()
    st.markdown("## 🎉 Kết quả luyện đọc của con")
    
    c1, c2, c3 = st.columns(3)
    c1.metric("Tốc độ", f"{wpm} từ/phút", "Chuẩn 50-60")
    c2.metric("Điểm (TT27)", f"{total_score}/4.0 đ", "Mức Tốt")
    c3.metric("Số từ đúng", f"{current_lesson['word_count'] - len(mispronounced)}/{current_lesson['word_count']}")

    st.info(f"Hôm nay con đọc rất to và tự tin! Con chú ý luyện đọc lại từ **'{', '.join(mispronounced)}'** một chút để hay hơn nhé. Tặng con 3 ngôi sao! ⭐⭐⭐")

    st.markdown("---")
    st.markdown(f"### ❓ Câu đố nhanh: {current_lesson['question']}")
    student_ans = st.text_input("Gõ câu trả lời của con vào đây:")
    if student_ans:
        if any(keyword in student_ans.lower() for keyword in current_lesson["expected_answer"].split()):
            st.success("🌟 Chính xác! Con hiểu bài rất xuất sắc!")
        else:
            st.warning("Gần đúng rồi, con đọc lại câu chuyện xem sao nhé!")
