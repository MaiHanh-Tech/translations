import re
import os
from concurrent.futures import ThreadPoolExecutor
from tqdm import tqdm
import sys
import streamlit as st
import pypinyin

# Prompt chuyên gia bạn yêu cầu
EXPERT_PROMPT = """Bạn là một chuyên gia dịch thuật có nhiều kinh nghiệm trong việc chuyển ngữ các văn bản phức tạp. Hãy phân tích và dịch tài liệu dưới đây sang tiếng Việt (hoặc ngôn ngữ đích được yêu cầu) với độ chính xác cao, đảm bảo giữ nguyên tinh thần, ý nghĩa, văn phong và sắc thái ngữ nghĩa của tác giả.
Các yêu cầu cụ thể:
1. Nếu có các thuật ngữ chuyên ngành, hãy dịch một cách phù hợp với ngữ cảnh.
2. Nếu có điển tích, thành ngữ hoặc cách diễn đạt khó, hãy tìm cách chuyển tải sao cho phù hợp với văn hóa của ngôn ngữ đích mà vẫn giữ được tinh thần nguyên bản.
3. Nếu có từ hoặc cụm từ đa nghĩa, hãy chọn nghĩa phù hợp nhất với ngữ cảnh.
4. Giữ nguyên cấu trúc của tài liệu gốc, bao gồm tiêu đề, danh sách. Có thể bỏ bớt các từ thừa, từ lặp trong câu để câu văn được mượt mà tự nhiên.
"""

def split_sentence(text: str) -> list[str]:
    """Tách câu thông minh, giữ nguyên dấu câu"""
    text = re.sub(r'\s+', ' ', text.strip())
    # Regex tách câu dựa trên dấu kết thúc câu phổ biến của Anh/Việt/Trung
    pattern = r'([。！？.!?\n]+(?:\s*[”"』\'）)]*)?)'
    splits = re.split(pattern, text)
    
    chunks = []
    current_chunk = ""
    
    for part in splits:
        current_chunk += part
        # Nếu chunk đủ dài hoặc kết thúc bằng dấu câu, ngắt chunk
        if len(current_chunk) > 20 and any(c in current_chunk for c in "。！？.!?\n"):
             chunks.append(current_chunk.strip())
             current_chunk = ""
             
    if current_chunk:
        chunks.append(current_chunk.strip())
        
    return [c for c in chunks if c]

def convert_to_pinyin(text: str) -> str:
    """Chuyển đổi sang Pinyin nếu là tiếng Trung"""
    # Kiểm tra xem có ký tự tiếng Trung không
    if any('\u4e00' <= char <= '\u9fff' for char in text):
        try:
            pinyin_list = pypinyin.pinyin(text, style=pypinyin.TONE)
            return ' '.join([item[0] for item in pinyin_list])
        except:
            return ""
    return ""

def process_chunk(chunk: str, index: int, source_lang: str, target_lang: str, include_english: bool) -> tuple:
    if 'translator' not in st.session_state:
        from translator import Translator
        st.session_state.translator = Translator()
    
    translator = st.session_state.translator
    
    # 1. Pinyin Logic: 
    # Nếu nguồn là Trung -> Lấy Pinyin nguồn.
    # Nếu đích là Trung -> Lấy Pinyin đích (sau khi dịch).
    # Hiện tại app hiển thị Pinyin ở dòng 2. Ta ưu tiên Pinyin của văn bản gốc nếu là tiếng Trung.
    pinyin_text = convert_to_pinyin(chunk)
    
    # 2. Dịch sang ngôn ngữ đích
    main_translation = translator.translate_text(
        chunk, source_lang, target_lang, prompt_template=EXPERT_PROMPT
    )
    
    # Nếu đích là tiếng Trung và nguồn không phải, tạo Pinyin cho bản dịch
    if not pinyin_text and target_lang == "Chinese":
         pinyin_text = convert_to_pinyin(main_translation)

    # 3. Dịch sang tiếng Anh (nếu được yêu cầu và ngôn ngữ đích không phải là Anh)
    english_translation = ""
    if include_english and target_lang != "English" and source_lang != "English":
        english_translation = translator.translate_text(
            chunk, source_lang, "English", prompt_template="Translate to English concisely."
        )

    return (index, chunk, pinyin_text, english_translation, main_translation)

def create_html_block(results: tuple, include_english: bool) -> str:
    index, chunk, pinyin, english, translation = results
    
    speak_button = '''
        <button class="speak-button" onclick="speakSentence(this.parentElement.textContent.replace('🔊', ''))">
            <svg viewBox="0 0 24 24" style="width:16px;height:16px;fill:currentColor">
                <path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z"/>
            </svg>
        </button>
    '''
    
    # Logic hiển thị:
    # Dòng 1: Gốc
    # Dòng 2: Pinyin (nếu có)
    # Dòng 3: Tiếng Anh (nếu có)
    # Dòng 4: Bản dịch chính
    
    html = f'<div class="sentence-part responsive">'
    html += f'<div class="original"><span class="sentence-index">{index + 1}.</span> {chunk}{speak_button}</div>'
    
    if pinyin:
        html += f'<div class="pinyin">{pinyin}</div>'
    
    if english:
        html += f'<div class="english">{english}</div>'
        
    html += f'<div class="second-language">{translation}</div>'
    html += '</div>'
    
    return html

def translate_file(input_text: str, progress_callback, include_english, 
                  source_lang, target_lang, translation_mode, processed_words=None):
    
    # Chế độ tương tác từng từ
    if translation_mode == "Interactive Word-by-Word" and processed_words:
        with open('template.html', 'r', encoding='utf-8') as f:
            template = f.read()
        
        # Tái sử dụng hàm tạo HTML khối tương tác (đã có trong app cũ hoặc copy logic vào đây)
        # Để ngắn gọn, tôi giả định logic tạo HTML cho word-by-word nằm ở create_interactive_html_block bên dưới
        from translate_book import create_interactive_html_block
        content = create_interactive_html_block(processed_words)
        return template.replace('{{content}}', content)

    # Chế độ dịch chuẩn (Standard)
    chunks = split_sentence(input_text)
    total = len(chunks)
    results_html = ""
    
    # Xử lý song song
    with ThreadPoolExecutor(max_workers=5) as executor: # Tăng worker vì Gemini xử lý khá nhanh
        futures = []
        for i, chunk in enumerate(chunks):
            future = executor.submit(process_chunk, chunk, i, source_lang, target_lang, include_english)
            futures.append(future)
            
        # Thu thập kết quả theo thứ tự
        for i, future in enumerate(futures):
            try:
                result = future.result()
                results_html += create_html_block(result, include_english)
                if progress_callback:
                    progress_callback((i + 1) / total * 100)
            except Exception as e:
                print(f"Error chunk {i}: {e}")

    with open('template.html', 'r', encoding='utf-8') as f:
        template = f.read()
        
    return template.replace('{{content}}', results_html)

def create_interactive_html_block(processed_words) -> str:
    """Tạo HTML cho chế độ tương tác từ vựng"""
    html = '<div class="interactive-text">'
    
    # Gom nhóm theo đoạn (Logic đơn giản hóa: cứ mỗi từ là 1 span, xuống dòng là thẻ br hoặc p mới)
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
        
        html += f'''
        <span class="interactive-word" 
              onclick="speak('{word}')"
              data-tooltip="{tooltip}">
            {word}
        </span>
        '''
    html += '</p></div>'
    return html
