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

# --- Cấu trúc dữ liệu cho chế độ Word-by-Word ---
class WordDefinition(BaseModel):
    word: str = Field(description="Từ gốc")
    pinyin: str = Field(description="Phiên âm (nếu có)", default="")
    translation: str = Field(description="Nghĩa trong ngữ cảnh")

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
            # Lấy API Key an toàn từ nhiều nguồn
            self.api_key = st.secrets.get("google_genai", {}).get("api_key", "")
            if not self.api_key:
                self.api_key = st.secrets.get("api_key", "")
            
            if self.api_key:
                genai.configure(api_key=self.api_key)
            
            # Config Model
            self.model_pro = st.secrets.get("google_genai", {}).get("model_pro", "gemini-1.5-pro")
            self.model_flash = st.secrets.get("google_genai", {}).get("model_flash", "gemini-1.5-flash")
            
            self.safety = {
                HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
            }
            self.cache = {}
            self.initialized = True

    def _generate_with_retry(self, model_name, prompt, structured_output=None):
        """Gọi API với cơ chế thử lại (Retry) khi gặp lỗi mạng/quota"""
        if not self.api_key:
            return None

        # Cấu hình trả về JSON nếu cần
        gen_config = {"temperature": 0.3}
        if structured_output:
            gen_config["response_mime_type"] = "application/json"
            gen_config["response_schema"] = structured_output

        model = genai.GenerativeModel(
            model_name=model_name,
            safety_settings=self.safety,
            generation_config=gen_config
        )

        for attempt in range(3):
            try:
                response = model.generate_content(prompt)
                return response.text
            except Exception as e:
                err = str(e)
                # Nếu lỗi 429 (Quota) hoặc 5xx (Server), chờ rồi thử lại
                if "429" in err or "500" in err or "503" in err:
                    sleep_time = (2 ** attempt) + random.random()
                    time.sleep(sleep_time)
                    continue
                else:
                    print(f"Non-retriable error: {err}")
                    return None
        return None

    def translate_text(self, text, source_lang, target_lang, prompt_template=None):
        """Hàm dịch chính"""
        if not text.strip(): return ""
        
        # Check cache
        cache_key = f"{text}|{source_lang}|{target_lang}"
        if cache_key in self.cache: return self.cache[cache_key]

        base_prompt = prompt_template or "Dịch đoạn văn sau."
        full_prompt = f"""
        {base_prompt}
        Thông tin:
        - Nguồn: {source_lang}
        - Đích: {target_lang}
        - Văn bản: {text}
        """

        # Ưu tiên dùng Flash cho nhanh, nếu lỗi mới sang Pro
        result = self._generate_with_retry(self.model_flash, full_prompt)
        if not result:
            result = self._generate_with_retry(self.model_pro, full_prompt)

        if result:
            self.cache[cache_key] = result.strip()
            return result.strip()
        
        return "[Error: API Connection Failed]"

    def process_word_by_word(self, text, source_lang, target_lang):
        """Phân tích từ vựng (Thay thế Jieba+Azure cũ)"""
        prompt = f"""
        Phân tích văn bản dưới đây để học ngoại ngữ.
        Văn bản ({source_lang}): "{text}"
        Yêu cầu: Tách từ, cung cấp Pinyin (nếu là tiếng Trung), và nghĩa ({target_lang}).
        """
        
        # Dùng Flash với Structured Output (Pydantic)
        res = self._generate_with_retry(self.model_flash, prompt, structured_output=InteractiveTranslation)
        
        if res:
            try:
                # Parse JSON từ Gemini
                data = InteractiveTranslation.model_validate_json(res)
                return [w.model_dump() for w in data.words]
            except:
                pass
        
        # Fallback về Jieba nếu Gemini lỗi
        return self._fallback_local_segmentation(text)

    def _fallback_local_segmentation(self, text):
        words = list(jieba.cut(text))
        results = []
        for word in words:
            py = ""
            if '\u4e00' <= word <= '\u9fff':
                 py = ' '.join([item[0] for item in pinyin(word, style=Style.TONE)])
            results.append({'word': word, 'pinyin': py, 'translations': []})
        return results
