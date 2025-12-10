import re
import os
from concurrent.futures import ThreadPoolExecutor
from tqdm import tqdm
import sys
import streamlit as st
import pypinyin
from translator import Translator

# Prompt chuyên gia giữ nguyên
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
    
    # 1. Xử lý Pinyin
    pinyin_text = ""
    if source_lang == "Chinese":
        pinyin_text = convert_to_pinyin(chunk)
    
    # 2. Dịch chính
    main_translation = translator.translate_text(
        chunk, source_lang, target_lang, prompt_template=EXPERT_PROMPT
    )
    
    # Nếu đích là Trung, lấy Pinyin cho bản dịch
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
    # Nút loa giữ nguyên class để ăn CSS cũ
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
                <div class="original">{index + 1}. {chunk}{speak_button}</div>
                <div class="pinyin">{pinyin}</div>
                <div class="english">{english}</div>
                <div class="second-language">{second}</div>
            </div>
        '''
    else:
        index, chunk, pinyin, second = results
        return f'''
            <div class="sentence-part responsive">
                <div class="original">{index + 1}. {chunk}{speak_button}</div>
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
    
    # 1. Chế độ tương tác
    if translation_mode == "Interactive Word-by-Word" and processed_words:
        content = create_interactive_html_block(processed_words)
    
    # 2. Chế độ dịch chuẩn
    else:
        lines = input_text.split('\n')
        translation_content = ''
        global_index = 0
        all_results = []
        
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = []
            total_chunks = 0
            for line_idx, line in enumerate(lines):
                if line.strip():
                    chunks = split_sentence(line.strip())
                    total_chunks += len(chunks)
                    for chunk_idx, chunk in enumerate(chunks):
                        future = executor.submit(process_chunk, chunk, global_index, source_lang, target_lang, include_english)
                        futures.append((line_idx, chunk_idx, future))
                        global_index += 1
            
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

        all_results.sort(key=lambda x: (x[0], x[1]))

        current_line = -1
        for line_idx, chunk_idx, result in all_results:
            if line_idx != current_line:
                if current_line != -1:
                    translation_content += '</div>'
                translation_content += '<div class="translation-block">'
                current_line = line_idx

            translation_content += create_html_block(result, include_english)

        if all_results:
            translation_content += '</div>'
        
        content = translation_content

    # 3. Ghép vào Template & Fix CSS
    try:
        with open('template.html', 'r', encoding='utf-8') as f:
            html_content = f.read()
            
        # [QUAN TRỌNG] Script này sẽ tự động thêm data-theme="dark/light" vào body
        # để CSS trong template.html nhận diện đúng màu sắc và icon
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
