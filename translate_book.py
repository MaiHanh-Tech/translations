import pypinyin
import re
import os
import sys
import time
import streamlit as st
from translator import Translator
from concurrent.futures import ThreadPoolExecutor

# Prompt xử lý lỗi ngắt dòng PDF ngay trong quá trình dịch
EXPERT_PROMPT = """Bạn là chuyên gia dịch thuật. Hãy dịch đoạn văn bản sau.
Yêu cầu bắt buộc:
1. Nối các từ bị ngắt quãng do lỗi PDF (ví dụ: 'impor tant' -> 'important', 'na•ve' -> 'naïve') trước khi dịch.
2. Dịch mượt mà, văn phong học thuật tự nhiên.
3. KHÔNG trả lời hay giải thích, chỉ đưa ra bản dịch.
"""

def clean_pdf_text(text: str) -> str:
    """Tiền xử lý văn bản PDF"""
    # 1. Nối từ bị ngắt bằng gạch nối: "impor-\ntant" -> "important"
    text = re.sub(r'(\w+)-\s*\n\s*(\w+)', r'\1\2', text)
    # 2. Xóa xuống dòng đơn (nối dòng)
    text = re.sub(r'(?<!\n)\n(?!\n)', ' ', text)
    # 3. Chuẩn hóa khoảng trắng
    text = re.sub(r'\s+', ' ', text)
    # 4. Fix lỗi PDF cụ thể trong ví dụ của bạn (na•ve -> naive)
    text = text.replace('•', 'ï').replace('impor tant', 'important').replace('scienti c', 'scientific')
    return text.strip()

def split_smart_chunks(text: str, chunk_size=1500) -> list:
    """Tăng kích thước chunk lên 1500 để giảm số lượng request gửi đi"""
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
        # Pinyin
        pinyin_text = convert_to_pinyin(chunk) if source == "Chinese" else ""
        
        # Dịch chính
        main_trans = translator.translate_text(chunk, source, target, EXPERT_PROMPT)
        
        # Nếu lỗi Quota trả về từ translator, giữ nguyên lỗi để hiển thị
        if "[System Busy" in main_trans or "[API Error" in main_trans:
            return (index, chunk, "", "", main_trans)

        # Pinyin đích
        if target == "Chinese" and not pinyin_text:
            pinyin_text = convert_to_pinyin(main_trans)

        # Dịch Anh
        eng_trans = ""
        if include_english:
            if target == "English": eng_trans = "" 
            elif source == "English": eng_trans = chunk
            else: eng_trans = translator.translate_text(chunk, source, "English", "Translate to English.")

        return (index, chunk, pinyin_text, eng_trans, main_trans)
    except Exception as e:
        return (index, chunk, "", "[Error]", f"[Sys Error: {str(e)}]")

def create_html_block(results, include_english):
    index, chunk, pinyin, english, second = results
    speak_btn = '''<button class="speak-button" onclick="speakSentence(this.parentElement.textContent.replace('🔊', ''))"><svg viewBox="0 0 24 24"><path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z"/></svg></button>'''
    
    html = f'<div class="sentence-part responsive">'
    html += f'<div class="original"><strong>[{index + 1}]</strong> {chunk}{speak_btn}</div>'
    
    if pinyin: html += f'<div class="pinyin">{pinyin}</div>'
    if include_english and english: html += f'<div class="english">{english}</div>'
    
    # Hiển thị lỗi màu đỏ
    if "[System Busy" in second or "[API Error" in second:
        html += f'<div class="second-language" style="color: red; border: 1px solid red; padding: 5px;">⚠️ {second}</div>'
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

    # Standard Mode
    translator = Translator()
    clean_text = clean_pdf_text(input_text)
    chunks = split_smart_chunks(clean_text)
    total = len(chunks)
    
    html_body = '<div class="translation-block">'
    
    # --- THAY ĐỔI QUAN TRỌNG: MAX_WORKERS = 1 ---
    # Chạy tuần tự để không bị Google chặn vì spam request
    with ThreadPoolExecutor(max_workers=1) as executor:
        futures = []
        for i, chunk in enumerate(chunks):
            future = executor.submit(process_chunk, chunk, i, translator, include_english, source_lang, target_lang)
            futures.append(future)
        
        results = []
        for i, future in enumerate(futures):
            res = future.result()
            results.append(res)
            # Thêm delay nhỏ để an toàn cho API
            time.sleep(1) 
            if progress_callback: progress_callback((i+1)/total * 100)
            
    # Hiển thị kết quả
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
```

### BƯỚC 3: Cập nhật `translator.py` (Xử lý chờ khi bị chặn)
File này sẽ tự động ngủ (sleep) 30 giây nếu gặp lỗi "429 Quota Exceeded" thay vì chết hẳn.

Copy đè toàn bộ vào `translator.py`:

```python
import streamlit as st
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
import time
import random
import json
import jieba
from pypinyin import pinyin, Style
from pydantic import BaseModel, Field
from typing import List

class WordDefinition(BaseModel):
    word: str
    pinyin: str
    translation: str

class InteractiveTranslation(BaseModel):
    words: List[WordDefinition]

class Translator:
    _instance = None
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.initialized = False
        return cls._instance

    def __init__(self):
        if not self.initialized:
            self.api_key = st.secrets.get("google_genai", {}).get("api_key", "") or st.secrets.get("api_key", "")
            if self.api_key: genai.configure(api_key=self.api_key)
            self.model_flash = st.secrets.get("google_genai", {}).get("model_flash", "gemini-2.5-flash")
            self.model_pro = st.secrets.get("google_genai", {}).get("model_pro", "gemini-2.5-pro")
            self.safety = {HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE, HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE, HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE, HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE}
            self.cache = {}
            self.initialized = True

    def _generate_with_retry(self, model_name, prompt, structured_output=None):
        if not self.api_key: return "Error: Missing API Key"
        
        gen_config = {"temperature": 0.3}
        if structured_output:
            gen_config.update({"response_mime_type": "application/json", "response_schema": structured_output})

        model = genai.GenerativeModel(model_name=model_name, safety_settings=self.safety, generation_config=gen_config)

        # Thử lại 5 lần, thời gian chờ tăng dần
        for attempt in range(5):
            try:
                response = model.generate_content(prompt)
                if response.text: return response.text
            except Exception as e:
                error_msg = str(e)
                # Nếu lỗi 429 (Quota) -> Chờ lâu (30s trở lên vì Google phạt block time)
                if "429" in error_msg or "Resource has been exhausted" in error_msg:
                    wait_time = 30 + (attempt * 10)
                    print(f"Quota exceeded. Waiting {wait_time}s...")
                    time.sleep(wait_time)
                    continue
                # Lỗi Server -> Chờ ngắn
                elif "500" in error_msg or "503" in error_msg:
                    time.sleep(5)
                    continue
                else:
                    return f"[API Error: {error_msg}]"
        
        return "[System Busy: 429 You exceeded your current quota. Please try again later or switch API Key]"

    def translate_text(self, text, source, target, prompt_template=None):
        if not text.strip(): return ""
        cache_key = f"{text}|{source}|{target}"
        if cache_key in self.cache: return self.cache[cache_key]

        full_prompt = f"{prompt_template or 'Dịch đoạn này:'}\n\nNguồn: {source}\nĐích: {target}\nVăn bản: {text}"
        
        # Luôn dùng Flash trước
        res = self._generate_with_retry(self.model_flash, full_prompt)
        
        if "API Error" not in res and "System Busy" not in res:
            self.cache[cache_key] = res.strip()
            
        return res.strip()

    def process_word_by_word(self, text, source, target):
        prompt = f"Phân tích từ vựng: '{text}' ({source}->{target})."
        res = self._generate_with_retry(self.model_flash, prompt, structured_output=InteractiveTranslation)
        try:
            return [w.model_dump() for w in InteractiveTranslation.model_validate_json(res).words]
        except:
            return [{'word': w, 'pinyin': '', 'translations': []} for w in jieba.cut(text)]
