import re
import os
from concurrent.futures import ThreadPoolExecutor
from tqdm import tqdm
import sys
import streamlit as st
import pypinyin
from translator import Translator

# Prompt chuyên gia (giữ nguyên)
EXPERT_PROMPT = """Bạn là một chuyên gia dịch thuật. Hãy dịch đoạn văn dưới đây sang ngôn ngữ đích.
Yêu cầu:
1. Dịch mượt mà, thoát ý, nối các câu lại cho tự nhiên (vì văn bản gốc có thể bị ngắt dòng do copy từ PDF).
2. Giữ nguyên các thuật ngữ chuyên ngành.
3. Không tự ý thêm bình luận, chỉ trả về kết quả dịch.
"""

def preprocess_pdf_text(text: str) -> list[str]:
    """
    Hàm tiền xử lý quan trọng:
    1. Nối từ bị ngắt dòng (Hyphenation): 'impor-\ntant' -> 'important'
    2. Nối dòng bị ngắt do PDF: Dòng không kết thúc bằng dấu câu sẽ được nối với dòng sau.
    3. Tách đoạn văn dựa trên 2 dấu xuống dòng (\n\n).
    """
    # 1. Xử lý dấu gạch nối ở cuối dòng (Hyphenation fix)
    # Tìm: chữ + dấu gạch ngang + xuống dòng + chữ thường -> nối lại
    text = re.sub(r'(\w+)-\n(\w+)', r'\1\2', text)
    
    # 2. Chuẩn hóa dòng:
    # Thay thế dấu xuống dòng đơn lẻ (\n) bằng khoảng trắng, TRỪ KHI nó là dấu xuống dòng kép (\n\n - báo hiệu đoạn mới)
    # Logic: Nếu dòng kết thúc bằng dấu câu (.!?) thì có thể là hết câu, nhưng PDF đôi khi ngắt giữa chừng.
    # Cách an toàn nhất cho PDF khoa học: Coi \n đơn lẻ là khoảng trắng.
    
    # Tạm thời thay \n\n (đoạn mới) bằng một ký tự đặc biệt không dùng đến, ví dụ <PARA_BREAK>
    text = re.sub(r'\n\s*\n', '<PARA_BREAK>', text)
    
    # Thay các \n còn lại (xuống dòng vô nghĩa trong câu) bằng khoảng trắng
    text = text.replace('\n', ' ')
    
    # Xử lý khoảng trắng thừa
    text = re.sub(r'\s+', ' ', text)
    
    # Khôi phục đoạn văn
    paragraphs = text.split('<PARA_BREAK>')
    
    # Lọc bỏ đoạn rỗng
    return [p.strip() for p in paragraphs if p.strip()]

def split_smart_chunks(text: str, max_length=600) -> list[str]:
    """
    Chia đoạn văn dài thành các chunks hợp lý (3-5 câu hoặc ~500-600 ký tự).
    Không cắt vụn từng câu ngắn.
    """
    # Tách thành các câu cơ bản trước
    # Regex này bắt dấu chấm câu, nhưng bỏ qua các từ viết tắt phổ biến (Mr., Dr., Fig., v.v. cần xử lý kỹ hơn nhưng tạm thời đơn giản)
    sentences = re.split(r'(?<=[.!?])\s+(?=[A-Z"\'(])', text)
    
    chunks = []
    current_chunk = ""
    
    for sentence in sentences:
        # Nếu chunk hiện tại + câu mới < max_length -> Gom vào
        if len(current_chunk) + len(sentence) < max_length:
            current_chunk += sentence + " "
        else:
            # Nếu chunk đã có dữ liệu, đẩy vào list
            if current_chunk:
                chunks.append(current_chunk.strip())
            current_chunk = sentence + " "
            
    # Đẩy chunk cuối cùng
    if current_chunk:
        chunks.append(current_chunk.strip())
        
    return chunks

def convert_to_pinyin(text: str) -> str:
    if any('\u4e00' <= char <= '\u9fff' for char in text):
        try:
            pinyin_list = pypinyin.pinyin(text, style=pypinyin.TONE)
            return ' '.join([item[0] for item in pinyin_list])
        except:
            return ""
    return ""

def process_chunk(chunk: str, index: int, source_lang: str, target_lang: str, include_english: bool) -> tuple:
    if 'translator' not in st.session_state:
        st.session_state.translator = Translator()
    
    translator = st.session_state.translator
    
    # 1. Pinyin
    pinyin_text = ""
    if source_lang == "Chinese":
        pinyin_text = convert_to_pinyin(chunk)
    
    # 2. Dịch chính
    main_translation = translator.translate_text(
        chunk, source_lang, target_lang, prompt_template=EXPERT_PROMPT
    )
    
    # Nếu đích là Trung, lấy Pinyin
    if target_lang == "Chinese" and not pinyin_text:
        pinyin_text = convert_to_pinyin(main_translation)

    # 3. Dịch Anh
    english_translation = ""
    if include_english:
        if target_lang == "English":
            english_translation = main_translation
        elif source_lang == "English":
            english_translation = chunk
        else:
            english_translation = translator.translate_text(
                chunk, source_lang, "English", prompt_template="Translate to English concisely."
            )

    if include_english:
        return (index, chunk, pinyin_text, english_translation, main_translation)
    else:
        return (index, chunk, pinyin_text, main_translation)

def create_html_block(results: tuple, include_english: bool) -> str:
    speak_button = '''
        <button class="speak-button" onclick="speakSentence(this.parentElement.textContent.replace('🔊', ''))">
            <svg viewBox="0 0 24 24">
                <path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z"/>
            </svg>
        </button>
    '''
    
    if include_english:
        index, chunk, pinyin, english, second = results
        return f'''
            <div class="sentence-part responsive">
                <div class="original"><strong>[{index + 1}]</strong> {chunk}{speak_button}</div>
                <div class="pinyin">{pinyin}</div>
                <div class="english">{english}</div>
                <div class="second-language">{second}</div>
            </div>
        '''
    else:
        index, chunk, pinyin, second = results
        return f'''
            <div class="sentence-part responsive">
                <div class="original"><strong>[{index + 1}]</strong> {chunk}{speak_button}</div>
                <div class="pinyin">{pinyin}</div>
                <div class="second-language">{second}</div>
            </div>
        '''

def create_interactive_html_block(processed_words) -> str:
    html = '<div class="interactive-text">'
    html += '<p class="interactive-paragraph">'
    for item in processed_words:
        word = item['word']
        pinyin = item.get('pinyin', '')
        meanings = item.get('translations', [''])
        meaning = meanings[0] if meanings else ''
        
        if word == '\n':
            html += '</p><p class="interactive-paragraph">'
            continue
            
        tooltip = f"{pinyin}\n{meaning}".strip()
        html += f'''<span class="interactive-word" onclick="speak('{word}')" data-tooltip="{tooltip}">{word}</span>'''
    html += '</p></div>'
    return html

def translate_file(input_text: str, progress_callback, include_english, 
                  source_lang="Chinese", target_lang="Vietnamese", 
                  translation_mode="Standard Translation", processed_words=None):
    
    # Chế độ tương tác
    if translation_mode == "Interactive Word-by-Word" and processed_words:
        content = create_interactive_html_block(processed_words)
    
    # Chế độ dịch chuẩn (Cải tiến xử lý PDF)
    else:
        # BƯỚC 1: Tiền xử lý văn bản PDF (Nối dòng, xóa gạch nối)
        paragraphs = preprocess_pdf_text(input_text)
        
        translation_content = ''
        global_index = 0
        all_results = []
        
        # BƯỚC 2: Tạo các chunks lớn hơn (3-5 câu) từ các đoạn văn
        final_chunks = []
        # Mapping để biết chunk nào thuộc paragraph nào (để đóng khung div)
        chunk_map = [] 
        
        for para_idx, para in enumerate(paragraphs):
            # Chia đoạn văn thành các nhóm câu (mỗi nhóm ~500 ký tự)
            sub_chunks = split_smart_chunks(para)
            for sub in sub_chunks:
                final_chunks.append(sub)
                chunk_map.append(para_idx)

        total_chunks = len(final_chunks)
        
        # BƯỚC 3: Xử lý song song
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = []
            for i, chunk in enumerate(final_chunks):
                future = executor.submit(
                    process_chunk, 
                    chunk, 
                    global_index, 
                    source_lang, 
                    target_lang, 
                    include_english
                )
                futures.append((i, future))
                global_index += 1
            
            completed = 0
            for idx, future in futures:
                try:
                    result = future.result()
                    # Lưu lại: (index gốc, paragraph index, result)
                    all_results.append((idx, chunk_map[idx], result))
                    
                    completed += 1
                    if progress_callback and total_chunks > 0:
                        progress_callback((completed / total_chunks) * 100)
                except Exception as e:
                    print(f"Error: {e}")

        # Sắp xếp lại theo thứ tự ban đầu
        all_results.sort(key=lambda x: x[0])

        # BƯỚC 4: Tạo HTML
        current_para = -1
        for _, para_idx, result in all_results:
            # Nếu sang đoạn văn bản gốc mới thì tạo khung mới
            if para_idx != current_para:
                if current_para != -1:
                    translation_content += '</div>'
                translation_content += '<div class="translation-block">'
                current_para = para_idx

            translation_content += create_html_block(result, include_english)

        if all_results:
            translation_content += '</div>'
        
        content = translation_content

    # Fix CSS và trả về
    try:
        with open('template.html', 'r', encoding='utf-8') as f:
            html_content = f.read()
            
        fix_css_script = """
        <script>
            (function() {
                function setTheme() {
                    const isDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
                    document.body.setAttribute('data-theme', isDark ? 'dark' : 'light');
                }
                setTheme();
                window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', setTheme);
            })();
        </script>
        </body>
        """
        
        if "</body>" in html_content:
            html_content = html_content.replace("</body>", fix_css_script)
        else:
            html_content += fix_css_script
            
        return html_content.replace('{{content}}', content)
        
    except FileNotFoundError:
        return f"Error: template.html not found. Content: {content}"
