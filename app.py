import streamlit as st
import streamlit.components.v1 as components
import jieba
from password_manager import PasswordManager
from translator import Translator
from translate_book import translate_file

# Initialize globals
pm = None

def init_password_manager():
    global pm
    if pm is None:
        try:
            pm = PasswordManager()
            return True
        except: return False
    return True

def show_user_interface(user_password=None):
    if not init_password_manager(): return

    # Logout
    col1, col2 = st.columns([10, 1])
    with col2:
        if st.button("Logout"):
            st.session_state.user_logged_in = False
            st.session_state.current_user = None
            st.rerun()

    # Login Logic (Manual)
    if user_password is None:
        if st.session_state.get("current_user"):
            user_password = st.session_state.current_user
        else:
            pwd = st.text_input("Enter Access Key", type="password")
            if not pwd: return
            if not pm.check_password(pwd):
                st.error("Invalid Key")
                return
            st.session_state.user_logged_in = True
            st.session_state.current_user = pwd
            st.rerun()

    # --- UI CHÍNH ---
    st.header("Gemini Translator (PDF Optimized)")
    
    # 1. Chọn Ngôn ngữ
    c1, c2 = st.columns(2)
    with c1:
        source_lang = st.selectbox("Nguồn (Source)", ["Chinese", "English", "Vietnamese"], index=1)
    with c2:
        target_lang = st.selectbox("Đích (Target)", ["Vietnamese", "English", "Chinese"], index=0)

    # 2. Cấu hình
    mode = st.radio("Chế độ", ["Standard Translation", "Interactive Word-by-Word"])
    include_eng = st.checkbox("Kèm tiếng Anh (Tham khảo)", value=True) if target_lang != "English" else False

    # 3. Input
    text_input = st.text_area("Nhập văn bản (Paste từ PDF thoải mái)", height=300)

    if st.button("Dịch ngay", type="primary"):
        if not text_input.strip(): return
        
        # Check quota
        if not pm.check_usage_limit(user_password, len(text_input)):
            st.error("Hết quota hôm nay!")
            return
        pm.track_usage(user_password, len(text_input))
        
        translator = Translator()
        prog_bar = st.progress(0)
        
        try:
            if mode == "Interactive Word-by-Word":
                st.info("Đang phân tích từ vựng...")
                # Gọi hàm mới trong Translator
                words = translator.process_word_by_word(text_input, source_lang, target_lang)
                html = translate_file(text_input, None, False, source_lang, target_lang, mode, words)
            else:
                st.info("Đang dịch và xử lý lỗi ngắt dòng PDF...")
                html = translate_file(
                    text_input, 
                    lambda p: prog_bar.progress(int(p)),
                    include_eng,
                    source_lang, 
                    target_lang,
                    mode
                )
            
            prog_bar.progress(100)
            st.success("Hoàn tất!")
            st.download_button("Tải HTML", html, "translated.html", "text/html")
            components.html(html, height=800, scrolling=True)
            
        except Exception as e:
            st.error(f"Lỗi: {e}")

def main():
    st.set_page_config(page_title="Gemini Translate", layout="centered")
    
    # Init Session vars
    if 'user_logged_in' not in st.session_state: st.session_state.user_logged_in = False
    if 'current_user' not in st.session_state: st.session_state.current_user = None

    # URL Login
    url_key = st.query_params.get('key', None)
    if url_key and init_password_manager() and pm.check_password(url_key):
        st.session_state.user_logged_in = True
        st.session_state.current_user = url_key

    if st.session_state.user_logged_in:
        show_user_interface(st.session_state.current_user)
    else:
        show_user_interface()

if __name__ == "__main__":
    main()
