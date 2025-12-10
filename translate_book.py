import pypinyin
import re
import os
import sys
import jieba
import streamlit as st
# Import Translator class
from translator import Translator

# --- PROMPT DỊCH SÁCH (Theo yêu cầu) ---
EXPERT_PROMPT = """Bạn là một chuyên gia dịch thuật và biên tập sách chuyên nghiệp. 
Hãy phân tích và dịch đoạn văn bản sau sang ngôn ngữ đích một cách trôi chảy, giữ đúng văn phong học thuật nhưng vẫn tự nhiên và dễ hiểu.
Yêu cầu:
1. Giữ nguyên ý nghĩa và sắc thái của tác giả.
2. Xử lý các thuật ngữ chuyên ngành chính xác.
3. Nếu văn bản gốc bị ngắt dòng do lỗi PDF, hãy tự động nối ý để dịch thành câu hoàn chỉnh.
4. Không thêm lời bình luận, chỉ trả về kết quả dịch.
"""

def split_sentence(text: str) -> list:
    """Split text into sentences (Logic gốc được giữ nguyên)"""
    # Xử lý sơ bộ khoảng trắng thừa
    text = re.sub(r'\s+', ' ', text.strip())
    
    # Pattern tách câu
    pattern = r'([。！？，：；.!?,][」"』\'）)]*(?:\s*[「""『\'（(]*)?)'
    splits = re.split(pattern, text)

    chunks = []
    current_chunk = ""
    min_length = 20
    quote_count = 0

    for i in range(0, len(splits)-1, 2):
        if splits[i]:
            chunk = splits[i] + (splits[i+1] if i+1 < len(splits) else '')
            # Đếm quote (Logic của bạn)
            quote_count += chunk.count('"') + chunk.count('"') + chunk.count('"')
            quote_count += chunk.count('「') + chunk.count('」')
            quote_count += chunk.count('『') + chunk.count('』')

            if quote_count % 2 == 1 or (len(current_chunk) + len(chunk) < min_length and i < len(splits)-2):
                current_chunk += chunk
            else:
                if current_chunk:
                    chunks.append(current_chunk + chunk)
                    current_chunk = ""
                else:
                    chunks.append(chunk)
                quote_count = 0

    if splits[-1] or current_chunk:
        last_chunk = splits[-1] if splits[-1] else ""
        if current_chunk:
            chunks.append(current_chunk + last_chunk)
        elif last_chunk:
            chunks.append(last_chunk)

    return [chunk.strip() for chunk in chunks if chunk.strip()]


def convert_to_pinyin(text: str) -> str:
    """Chuyển đổi Pinyin nếu là tiếng Trung"""
    if any('\u4e00' <= char <= '\u9fff' for char in text):
        try:
            pinyin_list = pypinyin.pinyin(text, style=pypinyin.TONE)
            return ' '.join([item[0] for item in pinyin_list])
        except:
            return ""
    return ""


def process_chunk(chunk: str, index: int, translator_instance, include_english: bool, 
                 source_lang: str, target_lang: str) -> tuple:
    try:
        # 1. Pinyin (chỉ tạo nếu Nguồn hoặc Đích là Trung)
        pinyin = ""
        if source_lang == "Chinese":
             pinyin = convert_to_pinyin(chunk)

        # 2. Dịch Anh (Tham khảo)
        english = ""
        if include_english:
            if target_lang == "English":
                english = "" # Sẽ hiện ở dòng chính
            elif source_lang == "English":
                english = chunk
            else:
                # Dịch sang Anh (ngắn gọn)
                english = translator_instance.translate_text(
                    chunk, source_lang, "English", 
                    prompt_template="Translate to English accurately."
                )

        # 3. Dịch Ngôn ngữ đích (Dùng Prompt Sách)
        second_trans = translator_instance.translate_text(
            chunk, source_lang, target_lang,
            prompt_template=EXPERT_PROMPT
        )
        
        # Nếu Đích là Trung và chưa có Pinyin, tạo từ bản dịch
        if target_lang == "Chinese" and not pinyin:
            pinyin = convert_to_pinyin(second_trans)

        return (index, chunk, pinyin, english, second_trans)

    except Exception as e:
        print(f"Error chunk {index}: {e}")
        return (index, chunk, "", "[Error]", f"[Sys Error: {str(e)}]")


def create_html_block(results: tuple, include_english: bool) -> str:
    speak_button = '''<button class="speak-button" onclick="speakSentence(this.parentElement.textContent.replace('🔊', ''))"><svg viewBox="0 0 24 24"><path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z"/></svg></button>'''
    
    try:
        # Giải nén tuple (đã chuẩn hóa 5 phần tử từ process_chunk)
        index, chunk, pinyin, english, second = results
        
        html = f'<div class="sentence-part responsive">'
        html += f'<div class="original">{index + 1}. {chunk}{speak_button}</div>'
        
        if pinyin:
            html += f'<div class="pinyin">{pinyin}</div>'
            
        if include_english and english:
            html += f'<div class="english">{english}</div>'
            
        html += f'<div class="second-language">{second}</div>'
        html += '</div>'
        
        return html
    except Exception as e:
        return f"<div>Error displaying block {results[1]}: {str(e)}</div>"


def create_interactive_html_block(results: tuple, include_english: bool) -> str:
    # Logic cũ cho interactive mode
    if isinstance(results, tuple) and len(results) == 2:
        chunk, word_data = results
    else:
        return ""

    content_html = '<div class="interactive-text">'
    
    current_paragraph = []
    paragraphs = []
    
    for word in word_data:
        if isinstance(word, dict) and word.get('word') == '\n':
            if current_paragraph:
                paragraphs.append(current_paragraph)
                current_paragraph = []
        else:
            current_paragraph.append(word)
    if current_paragraph: paragraphs.append(current_paragraph)
    
    for paragraph in paragraphs:
        content_html += '<p class="interactive-paragraph">'
        for word_data in paragraph:
            if word_data.get('translations'):
                tooltip = f"{word_data.get('pinyin', '')}\n{word_data['translations'][-1]}"
                content_html += f'<span class="interactive-word" onclick="speak(\'{word_data["word"]}\')" data-tooltip="{tooltip}">{word_data["word"]}</span>'
            else:
                content_html += f'<span class="non-chinese">{word_data.get("word", "")}</span>'
        content_html += '</p>'
    
    return content_html + '</div>'


def translate_file(input_text: str, progress_callback=None, include_english=True, 
                  source_lang="Chinese", target_lang="Vietnamese", 
                  translation_mode="Standard Translation", processed_words=None):
    try:
        text = input_text.strip()
        
        # Khởi tạo Translator
        translator_instance = Translator()

        # Mode: Interactive
        if translation_mode == "Interactive Word-by-Word" and processed_words:
            with open('template.html', 'r', encoding='utf-8') as f: html_template = f.read()
            content = create_interactive_html_block((text, processed_words), include_english)
            return html_template.replace('{{content}}', content)
        
        # Mode: Standard
        else:
            chunks = split_sentence(text)
            total = len(chunks)
            translation_content = ""
            
            if progress_callback: progress_callback(0)

            # Chạy tuần tự để ổn định
            for i, chunk in enumerate(chunks):
                result = process_chunk(
                    chunk, i, 
                    translator_instance, 
                    include_english, source_lang, target_lang
                )
                translation_content += create_html_block(result, include_english)
                
                if progress_callback:
                    progress_callback(min(100, ((i+1)/total)*100))

            with open('template.html', 'r', encoding='utf-8') as f: 
                html_template = f.read()
            
            # Script fix CSS dark mode
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
            
            if "</body>" in html_template:
                html_template = html_template.replace("</body>", fix_css_script)
            else:
                html_template += fix_css_script

            return html_template.replace('{{content}}', translation_content)

    except Exception as e:
        return f"<h3>Critical Error: {str(e)}</h3>"

if __name__ == "__main__":
    if len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
        print(translate_file(open(sys.argv[1], 'r', encoding='utf-8').read()))
