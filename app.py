import streamlit as st
import streamlit.components.v1 as components
from core import process_translation

st.set_page_config(page_title="Gemini Translation Book", layout="centered")

st.title("📚 Dịch Thuật Phong Cách Sách")

# 1. Cấu hình Ngôn ngữ
col1, col2 = st.columns(2)

languages = {
    "Tiếng Anh": "en",
    "Tiếng Trung": "zh",
    "Tiếng Việt": "vi"
}

with col1:
    src_lang = st.selectbox("Nguồn", options=list(languages.keys()), index=1) # Mặc định Trung
with col2:
    tgt_lang = st.selectbox("Đích", options=list(languages.keys()), index=2) # Mặc định Việt

# 2. Input
input_text = st.text_area("Nhập văn bản (Tự động tách câu):", height=200, placeholder="Dán văn bản vào đây...")

# 3. Nút Dịch
if st.button("Dịch & Tạo sách", type="primary"):
    if not input_text.strip():
        st.warning("Vui lòng nhập nội dung!")
    else:
        src_code = languages[src_lang]
        tgt_code = languages[tgt_lang]
        
        if src_code == tgt_code:
            st.error("Ngôn ngữ nguồn và đích không được giống nhau!")
        else:
            with st.spinner("Đang phân tích và dịch từng câu..."):
                try:
                    # Gọi hàm xử lý core
                    final_html = process_translation(input_text, src_code, tgt_code)
                    
                    # Hiển thị kết quả
                    st.success("Hoàn tất!")
                    components.html(final_html, height=600, scrolling=True)
                    
                    # Nút tải về
                    st.download_button(
                        label="Tải về file HTML",
                        data=final_html,
                        file_name="translation_book.html",
                        mime="text/html"
                    )
                except Exception as e:
                    st.error(f"Lỗi: {e}")
