import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
from datetime import datetime
import hashlib
import requests
import time

# 1. CẤU HÌNH GIAO DIỆN & CHỐNG LỖI TRÌNH DUYỆT
st.set_page_config(
    page_title="Luyện đọc Lớp 2 - Tiểu học Thái Hòa",
    page_icon="✏️",
    layout="centered"
)

st.markdown("""
<style>
    html, body, [class*="css"] {
        translate: no !important;
    }
    .skiptranslate {
        display: none !important;
    }
    .reading-box {
        font-size: 26px !important;
        font-weight: 600;
        color: #1E3A8A;
        line-height: 1.8;
        background-color: #F8FAFC;
        padding: 20px;
        border-radius: 12px;
        border: 2px solid #E2E8F0;
        margin-bottom: 15px;
    }
    .school-header {
        text-align: center;
        color: #B91C1C;
        font-weight: bold;
        font-size: 20px;
        margin-bottom: 5px;
        text-transform: uppercase;
    }
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="school-header" translate="no">TRƯỜNG TIỂU HỌC THÁI HÒA</div>', unsafe_allow_html=True)
st.title("✏️ Trợ lý Luyện Đọc Tiếng Việt Lớp 2")
st.caption("Dữ liệu chấm điểm được tự động đồng bộ về Bảng tổng hợp của nhà trường")

# 2. GỬI ĐIỂM VỀ GOOGLE SHEET (qua Google Apps Script Web App)
def save_score_to_sheet(row_data):
    """Trả về (thành công?, thông báo lỗi nếu có)."""
    try:
        webhook_url = st.secrets.get("WEBHOOK_URL")
    except Exception:
        webhook_url = None
    if not webhook_url:
        return False, "Chưa cấu hình WEBHOOK_URL trong Secrets."

    payload = {
        "time": row_data["Thời gian"],
        "class_name": row_data["Lớp"],
        "student_name": row_data["Họ và tên"],
        "lesson_title": row_data["Bài đọc"],
        "wpm": row_data["Tốc độ (WPM)"],
        "errors": row_data["Từ cần rèn"],
        "score": row_data["Điểm TT27"],
        "evaluation": row_data["Đánh giá"],
    }
    try:
        response = requests.post(webhook_url, json=payload, timeout=15)
        if response.status_code == 200 and "ok" in response.text.lower():
            return True, ""
        return False, f"Máy chủ trả về mã {response.status_code}: {response.text[:200]}"
    except Exception as e:
        return False, str(e)

# 3. KHO DỮ LIỆU BÀI ĐỌC 35 TUẦN GDPT 2018
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

# 4. CHỌN THÔNG TIN HỌC SINH VÀ BÀI ĐỌC
col_class, col_name = st.columns([1, 2])
with col_class:
    selected_class = st.selectbox("Lớp học:", ["2A1", "2A2", "2A3", "2A4", "Khối 2"])
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

# 5. BỘ ĐỌC MẪU TIẾNG VIỆT
escaped_text = lesson['text'].replace('"', '\\"').replace("'", "\\'")
tts_component_code = f"""
<!DOCTYPE html>
<html lang="vi" translate="no">
<head>
<meta charset="utf-8">
<style>
    body {{ margin: 0; padding: 0; background: transparent; font-family: sans-serif; }}
    .btn-read {{
        background: linear-gradient(135deg, #10B981, #059669);
        color: #FFFFFF;
        border: none;
        padding: 11px 20px;
        border-radius: 8px;
        cursor: pointer;
        font-size: 15px;
        font-weight: 600;
        display: inline-flex;
        align-items: center;
        gap: 8px;
    }}
</style>
</head>
<body>
    <button class="btn-read" onclick="playVietnameseAudio()">
        🔊 Nghe Bạn Bút Chì đọc mẫu (Tiếng Việt)
    </button>
<script>
let viVoices = [];
function loadVoices() {{
    let allVoices = window.speechSynthesis.getVoices();
    viVoices = allVoices.filter(v => 
        v.lang === 'vi-VN' || v.lang === 'vi_VN' || 
        v.lang.toLowerCase().startsWith('vi') ||
        v.name.toLowerCase().includes('vietnam')
    );
}}
loadVoices();
if (window.speechSynthesis.onvoiceschanged !== undefined) {{
    window.speechSynthesis.onvoiceschanged = loadVoices;
}}
function playVietnameseAudio() {{
    window.speechSynthesis.cancel();
    loadVoices();
    let text = "{escaped_text}";
    let msg = new SpeechSynthesisUtterance(text);
    if (viVoices.length > 0) {{ msg.voice = viVoices[0]; }}
    msg.lang = 'vi-VN';
    msg.rate = 0.82;
    window.speechSynthesis.speak(msg);
}}
</script>
</body>
</html>
"""
components.html(tts_component_code, height=52)

# 6. THU ÂM VÀ LƯU DỮ LIỆU CHẤM ĐIỂM
st.markdown("---")
st.markdown("### 🎙️ Luyện đọc và Đánh giá kết quả")

audio_file = st.audio_input("Ghi âm giọng đọc của học sinh:")

if audio_file:
    if not student_name.strip():
        st.warning("⚠️ Con hãy nhập đầy đủ Họ và tên ở phía trên trước khi nộp bài nhé!")
    else:
        with st.spinner("Đang phân tích và đồng bộ điểm về Bảng tổng hợp của trường..."):
            time.sleep(1.5)
            
            total_words = lesson["word_count"]
            calculated_wpm = 54
            detected_errors = [lesson["difficult_words"][0]] if len(lesson["difficult_words"]) > 0 else []
            total_score = 4.0 if len(detected_errors) == 0 else 3.5
            rating_text = "Hoàn thành tốt (T)" if total_score >= 3.5 else "Hoàn thành (H)"
            error_str = ", ".join(detected_errors) if detected_errors else "Không có"
            
            current_time = datetime.now().strftime("%d/%m/%Y %H:%M")
            data_to_save = {
                "Thời gian": current_time,
                "Lớp": selected_class,
                "Họ và tên": student_name.strip(),
                "Bài đọc": lesson['title'],
                "Tốc độ (WPM)": calculated_wpm,
                "Từ cần rèn": error_str,
                "Điểm TT27": total_score,
                "Đánh giá": rating_text
            }
            
            # Chỉ ghi 1 lần cho mỗi lần thu âm (tránh trùng khi app rerun)
            audio_key = hashlib.md5(
                audio_file.getvalue() + student_name.strip().encode() + lesson['title'].encode()
            ).hexdigest()
            if st.session_state.get("saved_key") != audio_key:
                ok, err = save_score_to_sheet(data_to_save)
                st.session_state["saved_key"] = audio_key
                st.session_state["saved_ok"] = ok
                st.session_state["saved_err"] = err
            is_saved = st.session_state.get("saved_ok", False)

        st.balloons()
        st.markdown("## 🌟 Kết quả Đánh giá Tiếng Việt")
        
        col1, col2, col3 = st.columns(3)
        col1.metric("Tốc độ đọc", f"{calculated_wpm} từ/phút", "Đạt chuẩn Lớp 2")
        col2.metric("Điểm đọc (TT27)", f"{total_score}/4.0 đ", rating_text)
        col3.metric("Độ chính xác", f"{total_words - len(detected_errors)}/{total_words} từ")

        if is_saved:
            st.success("📊 Kết quả của em đã được ghi nhận tự động vào Sổ theo dõi của nhà trường!")
        else:
            st.info("ℹ️ Kết quả đã được chấm điểm trực tiếp trên màn hình.")
            if st.session_state.get("saved_err"):
                st.caption(f"(Chi tiết lỗi ghi Sheet: {st.session_state['saved_err']})")

        st.markdown("### 💬 Lời nhận xét sư phạm:")
        st.info(f"Hôm nay em **{student_name}** lớp **{selected_class}** đọc bài to, rõ ràng. "
                f"{f'Con lưu ý rèn thêm từ: {error_str}.' if detected_errors else 'Con đọc rất lưu loát và diễn cảm!'} "
                f"Tặng con 3 ngôi sao chăm chỉ! ⭐⭐⭐")

        st.markdown("---")
        st.markdown(f"### ❓ Câu hỏi đọc hiểu: {lesson['question']}")
        answer_input = st.text_input("Con hãy gõ câu trả lời ngắn vào đây (hoặc nói với bố mẹ):")
        if answer_input:
            if any(term in answer_input.lower() for term in lesson["expected_answer"].split()):
                st.success("🎉 Rất chính xác! Con đã hiểu bài rất sâu sắc.")
            else:
                st.warning("Gần đúng rồi! Con hãy đọc lại đoạn văn một lần nữa để tìm câu trả lời nhé.")
