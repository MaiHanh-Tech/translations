import pypinyin
import re
import os
import sys
import streamlit as st
from translator import Translator
from concurrent.futures import ThreadPoolExecutor

# Prompt chuyên gia dịch thuật
EXPERT_PROMPT = """Bạn là biên dịch viên chuyên nghiệp. Hãy dịch đoạn văn bản sau.
Yêu cầu quan trọng:
1. Tự động sửa lỗi chính tả do copy từ PDF (ví dụ: nối các từ bị ngắt quãng như 'impor tant' -> 'important').
2. Dịch thoát ý, văn phong tự nhiên, trôi chảy.
3. Chỉ trả về kết quả dịch.
"""

def clean_pdf_text(text: str) -> str:
    """Xử lý văn bản PDF bị lỗi ngắt dòng"""
    # 1. Nối từ bị ngắt bằng dấu gạch ngang: "impor-\ntant" -> "important"
    text = re.sub(r'(\w+)-\s*\n\s*(\w+)', r'\1\2', text)
    
    # 2. [MỚI] Nối từ bị ngắt bởi khoảng trắng (lỗi PDF phổ biến): "impor tant" -> "important"
    # Logic: Tìm chữ thường + khoảng trắng + chữ thường -> Nối lại nếu có vẻ là từ bị ngắt
    # Regex này chỉ nối nếu ký tự liền kề là chữ cái, cẩn thận kẻo dính 2 từ đơn.
    # Tuy nhiên, để an toàn, ta dùng Prompt của AI để fix lỗi chính tả này thay vì regex cứng có thể sai.
    # Nhưng ta sẽ xử lý lỗi xuống dòng:
    
    # 3. Xóa xuống dòng đơn lẻ (nối dòng)
    text = re.sub(r'(?<!\n)\n(?!\n)', ' ', text)
    
    # 4. Chuẩn hóa khoảng trắng
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def split_smart_chunks(text: str, chunk_size=1000) -> list:
    """Chia văn bản thành các khối lớn (~1000 ký tự)"""
    # Tách câu dựa trên dấu chấm/hỏi/than
    sentences = re.split(r'(?<=[.!?])\s+(?=[A-Z"\'(])', text)
    chunks = []
    current_chunk = ""
    
    for sentence in sentences:
        if len(current_chunk) + len(sentence) < chunk_size:
            current_chunk += sentence + " "
        else:
            if current_chunk: chunks.append(current_chunk.strip())
            current_chunk = sentence + " "
            
    if current_chunk: chunks.append(current_chunk.strip())
    return chunks

def convert_to_pinyin(text: str) -> str:
    if any('\u4e00' <= char <= '\u9fff' for char in text):
        try:
            return ' '.join([i[0] for i in pypinyin.pinyin(text, style=pypinyin.TONE)])
        except: return ""
    return ""

def process_chunk(chunk, index, translator, include_english, source, target):
    try:
        # Pinyin (Nếu nguồn là Trung)
        pinyin_text = convert_to_pinyin(chunk) if source == "Chinese" else ""
        
        # Dịch chính
        main_trans = translator.translate_text(chunk, source, target, EXPERT_PROMPT)
        
        # Pinyin (Nếu đích là Trung)
        if target == "Chinese" and not pinyin_text:
            pinyin_text = convert_to_pinyin(main_trans)

        # Dịch Anh (Tham khảo)
        eng_trans = ""
        if include_english:
            if target == "English": eng_trans = "" 
            elif source == "English": eng_trans = chunk
            else: eng_trans = translator.translate_text(chunk, source, "English", "Translate to English.")

        return (index, chunk, pinyin_text, eng_trans, main_trans)
    except Exception as e:
        return (index, chunk, "", "[Error]", f"[System Error: {str(e)}]")

def create_html_block(results, include_english):
    index, chunk, pinyin, english, second = results
    
    speak_btn = '''<button class="speak-button" onclick="speakSentence(this.parentElement.textContent.replace('🔊', ''))"><svg viewBox="0 0 24 24"><path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z"/></svg></button>'''
    
    html = f'<div class="sentence-part responsive">'
    html += f'<div class="original"><strong>[{index + 1}]</strong> {chunk}{speak_btn}</div>'
    
    if pinyin: html += f'<div class="pinyin">{pinyin}</div>'
    if include_english and english: html += f'<div class="english">{english}</div>'
    
    # Hiển thị lỗi màu đỏ nếu có
    if "[API Error" in second or "[System Busy" in second:
        html += f'<div class="second-language" style="color: red; font-weight: bold;">{second}</div>'
    else:
        html += f'<div class="second-language">{second}</div>'
    
    html += '</div>'
    return html

def create_interactive_html_block(processed_words) -> str:
    html = '<div class="interactive-text"><p class="interactive-paragraph">'
    for item in processed_words:
        word = item['word']
        if word == '\n':
            html += '</p><p class="interactive-paragraph">'
            continue
        meaning = item['translations'][0] if item['translations'] else ""
        tooltip = f"{item['pinyin']}\n{meaning}".strip()
        html += f'<span class="interactive-word" onclick="speak(\'{word}\')" data-tooltip="{tooltip}">{word}</span>'
    html += '</p></div>'
    return html

def translate_file(input_text, progress_callback=None, include_english=True, 
                  source_lang="Chinese", target_lang="Vietnamese", 
                  translation_mode="Standard Translation", processed_words=None):
    
    if translation_mode == "Interactive Word-by-Word" and processed_words:
        with open('template.html', 'r', encoding='utf-8') as f: template = f.read()
        content = create_interactive_html_block(processed_words)
        return template.replace('{{content}}', content)

    # Standard Translation
    translator = Translator()
    clean_text = clean_pdf_text(input_text)
    chunks = split_smart_chunks(clean_text)
    total = len(chunks)
    
    html_body = '<div class="translation-block">'
    
    # Giảm xuống 2 workers để API ổn định hơn
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = []
        for i, chunk in enumerate(chunks):
            future = executor.submit(process_chunk, chunk, i, translator, include_english, source_lang, target_lang)
            futures.append((i, future))
        
        results = []
        completed = 0
        for i, future in futures:
            res = future.result()
            results.append(res)
            completed += 1
            if progress_callback: progress_callback(completed/total * 100)
            
        results.sort(key=lambda x: x[0])
        for res in results:
            html_body += create_html_block(res, include_english)
            
    html_body += '</div>'

    try:
        with open('template.html', 'r', encoding='utf-8') as f: template = f.read()
    except: template = "<body>{{content}}</body>"
    
    css_fix = """<script>
    (function(){
        function s(){document.body.setAttribute('data-theme', window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');}
        s(); window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', s);
    })();
    </script></body>"""
    
    full_html = template.replace('{{content}}', html_body)
    if "</body>" in full_html:
        full_html = full_html.replace("</body>", css_fix)
    else:
        full_html += css_fix
        
    return full_html
