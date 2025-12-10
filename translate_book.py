import re
import os
from concurrent.futures import ThreadPoolExecutor
from tqdm import tqdm
import sys
import streamlit as st
import pypinyin
from translator import Translator

# Giữ nguyên Prompt chuyên gia
EXPERT_PROMPT = """Bạn là một chuyên gia dịch thuật có nhiều kinh nghiệm. Hãy dịch tài liệu dưới đây sang ngôn ngữ đích được yêu cầu.
Yêu cầu:
1. Dịch chính xác, giữ nguyên tinh thần và sắc thái.
2. Với thuật ngữ chuyên ngành, dịch phù hợp ngữ cảnh.
3. Giữ nguyên các định dạng đặc biệt (số thứ tự, dấu câu).
4. Văn phong tự nhiên, mượt mà.
"""

def split_sentence(text: str) -> list[str]:
    """Tách câu giữ nguyên logic"""
    text = re.sub(r'\s+', ' ', text.strip())
    # Regex tách câu thông minh
    pattern = r'([。！？.!?\n]+(?:\s*[”"』\'）)]*)?)'
    splits = re.split(pattern, text)
    
    chunks = []
    current_chunk = ""
    
    for part in splits:
        current_chunk += part
        if len(current_chunk) > 20 and any(c in current_chunk for c in "。！？.!?\n"):
             chunks.append(current_chunk.strip())
             current_chunk = ""
             
    if current_chunk:
        chunks.append(current_chunk.strip())
        
    return [c for c in chunks if c]

def convert_to_pinyin(text: str) -> str:
    """Chuyển đổi Pinyin nếu có ký tự tiếng Trung"""
    if any('\u4e00' <= char <= '\u9fff' for char in text):
        try:
            pinyin_list = pypinyin.pinyin(text, style=pypinyin.TONE)
            return ' '.join([item[0] for item in pinyin_list])
        except:
            return ""
    return ""

def process_chunk(chunk: str, index: int, source_lang: str, target_lang: str, include_english: bool) -> tuple:
    """Xử lý dịch bằng Gemini nhưng trả về đúng định dạng tuple cũ"""
    if 'translator' not in st.session_state:
        st.session_state.translator = Translator()
    
    translator = st.session_state.translator
    
    # 1. Xử lý Pinyin (Nếu nguồn hoặc đích là Trung)
    pinyin_text = ""
    if source_lang == "Chinese":
        pinyin_text = convert_to_pinyin(chunk)
    
    # 2. Dịch chính (Second Language)
    main_translation = translator.translate_text(
        chunk, source_lang, target_lang, prompt_template=EXPERT_PROMPT
    )
    
    # Nếu đích là Trung, lấy Pinyin cho bản dịch
    if target_lang == "Chinese" and not pinyin_text:
        pinyin_text = convert_to_pinyin(main_translation)

    # 3. Dịch Anh (Nếu cần)
    english_translation = ""
    if include_english:
        # Nếu đích đã là Anh hoặc Nguồn là Anh thì không cần dịch thêm sang Anh
        if target_lang == "English":
            english_translation = main_translation # Hoặc để trống tùy logic hiển thị
        elif source_lang == "English":
            english_translation = chunk
        else:
            english_translation = translator.translate_text(
                chunk, source_lang, "English", prompt_template="Translate to English concisely."
            )

    # Trả về đúng cấu trúc tuple mà create_html_block mong đợi
    if include_english:
        return (index, chunk, pinyin_text, english_translation, main_translation)
    else:
        return (index, chunk, pinyin_text, main_translation)

def create_html_block(results: tuple, include_english: bool) -> str:
    """
    Tạo HTML giữ nguyên class và cấu trúc cũ để ăn khớp với template.html.
    KHÔNG SỬA cấu trúc thẻ div.
    """
    speak_button = '''
        <button class="speak-button" onclick="speakSentence(this.parentElement.textContent.replace('🔊', ''))">
            <svg viewBox="0 0 24 24">
                <path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z"/>
            </svg>
        </button>
    '''
    
    if include_english:
        # Giải nén tuple 5 phần tử
        index, chunk, pinyin, english, second = results
        # Lưu ý: Các class .original, .pinyin, .english, .second-language là bắt buộc để có màu
        return f'''
            <div class="sentence-part responsive">
                <div class="original">{index + 1}. {chunk}{speak_button}</div>
                <div class="pinyin">{pinyin}</div>
                <div class="english">{english}</div>
                <div class="second-language">{second}</div>
            </div>
        '''
    else:
        # Giải nén tuple 4 phần tử
        index, chunk, pinyin, second = results
        return f'''
            <div class="sentence-part responsive">
                <div class="original">{index + 1}. {chunk}{speak_button}</div>
                <div class="pinyin">{pinyin}</div>
                <div class="second-language">{second}</div>
            </div>
        '''

def create_interactive_html_block(processed_words) -> str:
    """Tạo HTML cho chế độ tương tác (Interactive)"""
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
        with open('template.html', 'r', encoding='utf-8') as f:
            template = f.read()
        content = create_interactive_html_block(processed_words)
        return template.replace('{{content}}', content)

    # Chế độ dịch chuẩn (Standard)
    # Tách dòng để gom nhóm block (Quan trọng cho giao diện đẹp)
    lines = input_text.split('\n')
    translation_content = ''
    global_index = 0
    
    all_results = []
    
    # Dùng ThreadPool để dịch nhanh
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = []
        total_chunks = 0
        
        # Duyệt từng dòng -> từng chunk
        for line_idx, line in enumerate(lines):
            if line.strip():
                chunks = split_sentence(line.strip())
                total_chunks += len(chunks)
                for chunk_idx, chunk in enumerate(chunks):
                    future = executor.submit(
                        process_chunk,
                        chunk,
                        global_index,
                        source_lang,
                        target_lang,
                        include_english
                    )
                    # Lưu lại line_idx để sau này gom nhóm div
                    futures.append((line_idx, chunk_idx, future))
                    global_index += 1
        
        # Thu thập kết quả
        completed = 0
        for line_idx, chunk_idx, future in futures:
            try:
                result = future.result()
                all_results.append((line_idx, chunk_idx, result))
                
                completed += 1
                if progress_callback and total_chunks > 0:
                    progress_callback((completed / total_chunks) * 100)
            except Exception as e:
                print(f"Error: {e}")

    # Sắp xếp lại để đảm bảo đúng thứ tự (dù luồng chạy song song)
    all_results.sort(key=lambda x: (x[0], x[1]))

    # Tạo HTML với cấu trúc Block (Quan trọng: Khôi phục logic translation-block)
    current_line = -1
    for line_idx, chunk_idx, result in all_results:
        # Nếu chuyển sang dòng mới trong file gốc -> tạo block mới (cái khung xám/trắng)
        if line_idx != current_line:
            if current_line != -1:
                translation_content += '</div>' # Đóng block cũ
            translation_content += '<div class="translation-block">' # Mở block mới
            current_line = line_idx

        translation_content += create_html_block(result, include_english)

    if all_results:
        translation_content += '</div>'

    # Đọc template và thay thế
    try:
        with open('template.html', 'r', encoding='utf-8') as f:
            html_content = f.read()
        return html_content.replace('{{content}}', translation_content)
    except FileNotFoundError:
        return f"Error: template.html not found. Content: {translation_content}"
