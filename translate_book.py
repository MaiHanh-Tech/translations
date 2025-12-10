import pypinyin
import re
import os
import sys
import time
import streamlit as st
from translator import Translator

# Prompt
EXPERT_PROMPT = """Bạn là chuyên gia dịch thuật. Hãy dịch đoạn văn bản sau.
Yêu cầu:
1. Nối các từ bị ngắt quãng do lỗi PDF (ví dụ: 'impor tant' -> 'important') trước khi dịch.
2. Dịch thoát ý, tự nhiên.
3. KHÔNG giải thích, chỉ đưa ra kết quả.
"""

def clean_pdf_text(text):
    if not text: return ""
    text = re.sub(r'(\w+)-\s*\n\s*(\w+)', r'\1\2', text) # Nối gạch ngang
    text = re.sub(r'(?<!\n)\n(?!\n)', ' ', text) # Nối dòng đơn
    text = re.sub(r'\s+', ' ', text) # Xóa khoảng trắng thừa
    # Fix lỗi PDF cụ thể
    text = text.replace('•', 'ï').replace('impor tant', 'important')
    return text.strip()

def split_smart_chunks(text, chunk_size=1000):
    if not text: return []
    # Tách câu đơn giản hơn để tránh treo
    sentences = re.split(r'(?<=[.!?])\s+', text)
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

def convert_to_pinyin(text):
    if not text: return ""
    if any('\u4e00' <= char <= '\u9fff' for char in text):
        try:
            return ' '.join([i[0] for i in pypinyin.pinyin(text, style=pypinyin.TONE)])
        except: return ""
    return ""

def create_html_block(index, chunk, pinyin, english, second):
    # Nút loa
    speak_btn = """<button class="speak-button" onclick="speakSentence(this.parentElement.textContent.replace('🔊', ''))"><svg viewBox="0 0 24 24"><path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z"/></svg></button>"""
    
    html = f'<div class="sentence-part responsive">'
    html += f'<div class="original"><strong>[{index + 1}]</strong> {chunk}{speak_btn}</div>'
    
    if pinyin: html += f'<div class="pinyin">{pinyin}</div>'
    if english: html += f'<div class="english">{english}</div>'
    
    # Hiển thị lỗi màu đỏ
    if "[System Busy" in second or "[API Error" in second:
        html += f'<div class="second-language" style="color: red; border: 1px solid red; padding: 5px;">⚠️ {second}</div>'
    else:
        html += f'<div class="second-language">{second}</div>'
    
    html += '</div>'
    return html

def create_interactive_html_block(processed_words):
    html = '<div class="interactive-text"><p class="interactive-paragraph">'
    for item in processed_words:
        word = item.get('word', '')
        if word == '\n':
            html += '</p><p class="interactive-paragraph">'
            continue
        translations = item.get('translations', [])
        meaning = translations[0] if translations else ""
        tooltip = f"{item.get('pinyin','')}\\n{meaning}"
        safe_word = word.replace("'", "\\'")
        html += f"""<span class="interactive-word" onclick="speak('{safe_word}')" data-tooltip="{tooltip}">{word}</span>"""
    html += '</p></div>'
    return html

def translate_file(input_text, status_placeholder=None, progress_bar=None, include_english=True, 
                  source_lang="Chinese", target_lang="Vietnamese", 
                  translation_mode="Standard Translation", processed_words=None):
    
    # 1. Chế độ Interactive
    if translation_mode == "Interactive Word-by-Word" and processed_words:
        try:
            with open('template.html', 'r', encoding='utf-8') as f: template = f.read()
        except: template = "<body>{{content}}</body>"
        content = create_interactive_html_block(processed_words)
        return template.replace('{{content}}', content)

    # 2. Chế độ Standard (Dịch sách)
    translator = Translator()
    
    if status_placeholder: status_placeholder.text("Đang làm sạch văn bản PDF...")
    clean_text = clean_pdf_text(input_text)
    
    if status_placeholder: status_placeholder.text("Đang chia nhỏ văn bản...")
    chunks = split_smart_chunks(clean_text)
    total = len(chunks)
    
    html_body = '<div class="translation-block">'
    
    # --- VÒNG LẶP CHÍNH (Tuần tự để update UI) ---
    for i, chunk in enumerate(chunks):
        # Update Status
        if status_placeholder: 
            status_placeholder.text(f"Đang dịch đoạn {i+1}/{total}...")
        
        # Pinyin
        pinyin_text = convert_to_pinyin(chunk) if source_lang == "Chinese" else ""
        
        # Dịch Chính
        main_trans = translator.translate_text(chunk, source_lang, target_lang, EXPERT_PROMPT)
        
        # Pinyin Đích
        if target_lang == "Chinese" and not pinyin_text:
            pinyin_text = convert_to_pinyin(main_trans)
            
        # Dịch Anh
        eng_trans = ""
        if include_english and target_lang != "English" and source_lang != "English":
            eng_trans = translator.translate_text(chunk, source_lang, "English", "Translate to English.")

        # Tạo HTML Block
        html_body += create_html_block(i, chunk, pinyin_text, eng_trans, main_trans)
        
        # Update Progress Bar
        if progress_bar:
            progress_bar.progress((i + 1) / total)
            
        # Nghỉ nhẹ 1 chút để tránh spam API
        time.sleep(0.5)
            
    html_body += '</div>'

    # Ghép template
    try:
        with open('template.html', 'r', encoding='utf-8') as f: template = f.read()
    except: template = "<body>{{content}}</body>"
    
    # Fix CSS Dark mode
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
