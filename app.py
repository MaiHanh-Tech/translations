import streamlit as st
import streamlit.components.v1 as components
from password_manager import PasswordManager
from translator import Translator
from translate_book import translate_file

# Initialize password manager
pm = None

def init_password_manager():
    global pm
    if pm is None:
        try:
            pm = PasswordManager()
            return True
        except Exception as e:
            st.error(f"Error initializing password manager: {str(e)}")
            return False
    return True

def init_translator():
    if 'translator' not in st.session_state:
        st.session_state.translator = Translator()
    return st.session_state.translator

def show_user_interface(user_password=None):
    if not init_password_manager():
        return

    # Logout button
    col1, col2 = st.columns([10, 1])
    with col2:
        if st.button("Logout"):
            st.session_state.user_logged_in = False
            st.session_state.current_user = None
            st.rerun()

    if user_password is None:
        user_password = st.text_input("Enter your access key", type="password")
        if not user_password:
            return
        if not pm.check_password(user_password):
            st.error("Invalid access key")
            return

    st.header("Gemini AI Translator")
    
    # --- Language Settings ---
    st.subheader("Language Settings")
    col_src, col_tgt = st.columns(2)
    
    available_langs = ["Chinese", "English", "Vietnamese"]
    
    with col_src:
        source_language = st.selectbox(
            "Source Language (Ngôn ngữ nguồn)",
            options=available_langs,
            index=0 # Default Chinese
        )
        
    with col_tgt:
        # Filter target lang to avoid same source-target
        target_options = [l for l in available_langs if l != source_language]
        target_language = st.selectbox(
            "Target Language (Ngôn ngữ đích)",
            options=target_options,
            index=1 if source_language == "Chinese" else 0 # Default Vietnamese if Src is Chinese
        )

    # --- Mode & Options ---
    col1, col2 = st.columns(2)
    with col1:
        translation_mode = st.radio(
            "Translation Mode",
            ["Standard Translation", "Interactive Word-by-Word"],
            help="Standard: Dịch cả câu (có Pinyin). Interactive: Click từng từ để xem nghĩa."
        )
    
    with col2:
        include_english = st.checkbox(
            "Include English Reference", 
            value=(target_language != "English" and source_language != "English"),
            help="Hiển thị thêm dòng dịch tiếng Anh tham khảo"
        )

    # --- Input ---
    text_input = st.text_area("Input Text", height=300, placeholder="Paste text here...")

    # --- Processing ---
    if st.button("Translate", type="primary"):
        if not text_input.strip():
            st.warning("Please enter text.")
            return

        translator = init_translator()
        
        # Check usage (Simple char count)
        char_count = len(text_input)
        if not pm.check_usage_limit(st.session_state.current_user, char_count):
             st.error("Daily limit exceeded.")
             return
        pm.track_usage(st.session_state.current_user, char_count)

        try:
            status_text = st.empty()
            progress_bar = st.progress(0)
            
            def update_progress(p):
                progress_bar.progress(int(p))
                status_text.text(f"Translating... {int(p)}%")

            if translation_mode == "Interactive Word-by-Word":
                status_text.text("Analyzing words with Gemini...")
                # Dùng Gemini xử lý toàn bộ segmentation + dịch từ
                processed_words = translator.process_word_by_word(text_input, source_language, target_language)
                
                html_content = translate_file(
                    text_input, None, False, 
                    source_language, target_language, 
                    translation_mode, processed_words
                )
            else:
                # Standard Mode
                html_content = translate_file(
                    text_input, update_progress, include_english,
                    source_language, target_language,
                    translation_mode
                )

            progress_bar.progress(100)
            status_text.text("Completed!")
            
            st.download_button("Download HTML", html_content, "translation.html", "text/html")
            components.html(html_content, height=800, scrolling=True)

        except Exception as e:
            st.error(f"Error: {str(e)}")

def main():
    st.set_page_config(page_title="Gemini Translator", layout="centered")
    
    # CSS fix
    st.markdown("""<style>.stTextArea textarea {font-size: 16px !important;}</style>""", unsafe_allow_html=True)
    
    # Session state init
    if 'user_logged_in' not in st.session_state:
        st.session_state.user_logged_in = False
    
    # Login Logic (Simplified from original)
    if not st.session_state.user_logged_in:
        url_key = st.query_params.get('key', None)
        if url_key and init_password_manager() and pm.check_password(url_key):
             st.session_state.user_logged_in = True
             st.session_state.current_user = url_key
             st.rerun()
             
        show_user_interface()
    else:
        show_user_interface(st.session_state.current_user)

if __name__ == "__main__":
    main()
