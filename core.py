mport google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
import streamlit as st
from pypinyin import pinyin, Style
import jieba
import re
from tenacity import retry, stop_after_attempt, wait_fixed

# 1. Khởi tạo Gemini
def get_model():
    try:
        api_key = st.secrets["gemini"]["api_key"]
        genai.configure(api_key=api_key)
        safety_settings = {
            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
        }
        return genai.GenerativeModel('gemini-1.5-flash', safety_settings=safety_settings)
    except Exception as e:
        return None

# 2. Xử lý văn bản (Cắt câu, Pinyin)
def split_sentences(text):
    # Regex cắt câu cho cả tiếng Trung và tiếng Anh/Việt
    text = re.sub(r'\s+', ' ', text.strip())
    pattern = r'([。！？.!?][”"’\'）)]*)'
    chunks = re.split(pattern, text)
    sentences = []
    current = ""
    
    for chunk in chunks:
        current += chunk
        # Nếu chunk kết thúc bằng dấu câu, coi là 1 câu hoàn chỉnh
        if re.search(r'[。！？.!?]$', chunk) or len(current) > 50:
            sentences.append(current.strip())
            current = ""
            
    if current: sentences.append(current.strip())
    return [s for s in sentences if s]

def get_pinyin(text):
    """Lấy Pinyin nếu là tiếng Trung"""
    # Kiểm tra xem có ký tự tiếng Trung không
    if not any('\u4e00' <= char <= '\u9fff' for char in text):
        return ""
    
    py_list = pinyin(text, style=Style.TONE)
    return ' '.join([x[0] for x in py_list])

def get_speaker_btn(text, lang_code):
    """Tạo nút loa HTML (chỉ cho EN và ZH)"""
    if lang_code not in ['en', 'zh']:
        return ""
    
    # Escape single quotes for JS
    safe_text = text.replace("'", "\\'").replace('"', '&quot;')
    
    return f'''
    <button class="speak-btn" onclick="speak('{safe_text}', '{lang_code}')" title="Nghe đọc">
        <svg viewBox="0 0 24 24"><path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z"/></svg>
    </button>
    '''

# 3. Hàm Dịch chính
@retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
def translate_chunk(model, text, src_lang, tgt_lang):
    prompt = (
        f"Translate from {src_lang} to {tgt_lang}. "
        "Output ONLY the translation. No explanations."
        f"\n\nText: {text}"
    )
    response = model.generate_content(prompt)
    return response.text.strip()

def process_translation(input_text, src_code, tgt_code):
    model = get_model()
    if not model: return "Error: API Key Config"

    # Map code sang tên đầy đủ cho Gemini
    lang_names = {"en": "English", "zh": "Chinese", "vi": "Vietnamese"}
    
    sentences = split_sentences(input_text)
    html_blocks = ""

    # Progress bar trong Streamlit
    prog_bar = st.progress(0)
    
    for i, sentence in enumerate(sentences):
        # 1. Xử lý phần Gốc
        orig_pinyin = get_pinyin(sentence) if src_code == 'zh' else ""
        orig_speaker = get_speaker_btn(sentence, src_code)
        
        # 2. Dịch
        translated = translate_chunk(model, sentence, lang_names[src_code], lang_names[tgt_code])
        
        # 3. Xử lý phần Đích
        trans_pinyin = get_pinyin(translated) if tgt_code == 'zh' else ""
        trans_speaker = get_speaker_btn(translated, tgt_code)
        
        # 4. Tạo HTML Block
        block = f'<div class="sentence-block">'
        
        # Dòng 1: Gốc
        block += f'<div class="line original-text">{sentence} {orig_speaker}</div>'
        
        # Dòng 2: Pinyin Gốc (nếu có)
        if orig_pinyin:
            block += f'<div class="line pinyin-text">{orig_pinyin}</div>'
            
        # Dòng 3: Dịch
        block += f'<div class="line translated-text">{translated} {trans_speaker}</div>'
        
        # Dòng 4: Pinyin Dịch (nếu có)
        if trans_pinyin:
            block += f'<div class="line pinyin-text">{trans_pinyin}</div>'
            
        block += '</div>'
        html_blocks += block
        
        # Update progress
        prog_bar.progress((i + 1) / len(sentences))

    # Đọc template và nhúng nội dung vào
    with open('template.html', 'r', encoding='utf-8') as f:
        template = f.read()
        
    return template.replace('{{content}}', html_blocks)
