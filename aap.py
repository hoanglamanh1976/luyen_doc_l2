import streamlit as st
import json
import time

# Cấu hình giao diện chuẩn cho học sinh tiểu học
st.set_page_config(page_title="Bạn Bút Chì - Luyện đọc Lớp 2", page_icon="✏️", layout="centered")

# CSS tùy biến giao diện thân thiện, chữ to, màu sắc tươi sáng
st.markdown("""
<style>
    .big-font { font-size: 26px !important; font-weight: bold; color: #1E3A8A; line-height: 1.6; }
    .instruction { font-size: 18px; color: #4B5563; }
    .stButton>button { border-radius: 20px; font-size: 18px; height: 3em; background-color: #3B82F6; color: white; }
</style>
""", unsafe_allow_html=True)

st.title("✏️ Bạn Bút Chì - Luyện Đọc Tiếng Việt Lớp 2")

# 1. Kho bài đọc chuẩn lớp 2 (Có thể kết nối từ Google Sheets)
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

# Đọc mẫu bằng Web Speech API của trình duyệt
st.markdown(f"""
<button onclick="
    let utterance = new SpeechSynthesisUtterance('{current_lesson['text']}');
    utterance.lang = 'vi-VN';
    utterance.rate = 0.85;
    window.speechSynthesis.speak(utterance);
" style="background-color: #10B981; color: white; border: none; padding: 10px 20px; border-radius: 12px; cursor: pointer; font-size: 16px; margin-top: 10px;">
    🔊 Nghe Bạn Bút Chì đọc mẫu
</button>
""", unsafe_allow_html=True)

st.markdown("---")
st.markdown("### 🎙️ Luyện đọc và Ghi âm")
st.write("Con hãy bấm vào ô ghi âm dưới đây và đọc thật to, rõ ràng nhé:")

# Thu âm trực tiếp bằng tính năng audio_input của Streamlit Web
audio_data = st.audio_input("Bấm micro để bắt đầu đọc:")

if audio_data:
    st.success("✅ Đã ghi nhận giọng đọc của con! Bạn Bút Chì đang chấm bài...")
    
    # Giả lập thời gian xử lý và phân tích ASR + LLM trên Cloud
    with st.spinner("Đang tính tốc độ và phát hiện lỗi đọc..."):
        time.sleep(1.5)
        
        # Dữ liệu mô phỏng kết quả phân tích theo thang 4 Thông tư 27
        wpm = 52 # Tốc độ từ/phút
        mispronounced = ["khoe sắc"]
        pause_score = 1.5
        pronunciation_speed_score = 1.5
        comprehension_score = 0.5
        total_score = pronunciation_speed_score + pause_score + comprehension_score

    # Hiển thị bảng tổng kết trực quan cho học sinh
    st.balloons() # Hiệu ứng bóng bay khen ngợi
    st.markdown("## 🎉 Kết quả luyện đọc của con")
    
    col1, col2, col3 = st.columns(3)
    col1.metric("Tốc độ đọc", f"{wpm} từ/phút", "Chuẩn 50-60 wpm")
    col2.metric("Điểm đọc (TT27)", f"{total_score}/4.0 điểm", "Mức Tốt")
    col3.metric("Số từ đọc đúng", f"{current_lesson['word_count'] - len(mispronounced)}/{current_lesson['word_count']}")

    st.markdown("### 💬 Lời nhắn từ Bạn Bút Chì:")
    st.info(f"Hôm nay con đọc rất to, rõ ràng và tự tin! Con chú ý luyện đọc lại từ **'{', '.join(mispronounced)}'** một chút xíu để giọng đọc hay hơn nữa nhé. Con xứng đáng được 3 ngôi sao chăm chỉ! ⭐⭐⭐")

    # Câu hỏi đọc hiểu nhanh tương tác
    st.markdown("---")
    st.markdown(f"### ❓ Câu đố nhanh: {current_lesson['question']}")
    student_ans = st.text_input("Gõ hoặc đọc câu trả lời của con:")
    if student_ans:
        if any(keyword in student_ans.lower() for keyword in current_lesson["expected_answer"].split()):
            st.success("🌟 Chính xác! Con hiểu bài rất xuất sắc!")
        else:
            st.warning("Gần đúng rồi, con nhìn lại đoạn văn một lần nữa xem nhé!")
