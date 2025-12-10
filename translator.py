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

# Cấu trúc dữ liệu trả về cho chế độ Word-by-Word
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
            # 1. Tự động tìm API Key
            self.api_key = st.secrets.get("google_genai", {}).get("api_key", "")
            if not self.api_key:
                # Fallback: Thử tìm ở root hoặc biến môi trường
                self.api_key = st.secrets.get("api_key", os.environ.get("GOOGLE_API_KEY", ""))
            
            if self.api_key:
                genai.configure(api_key=self.api_key)
            
            # 2. Cấu hình Model
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
        if not self.api_key:
            return "Error: Chưa cấu hình API Key trong .streamlit/secrets.toml"

        gen_config = {"temperature": 0.3}
        if structured_output:
            gen_config["response_mime_type"] = "application/json"
            gen_config["response_schema"] = structured_output

        model = genai.GenerativeModel(
            model_name=model_name,
            safety_settings=self.safety,
            generation_config=gen_config
        )

        last_error = ""
        # Thử lại tối đa 3 lần
        for attempt in range(3):
            try:
                response = model.generate_content(prompt)
                if response.text:
                    return response.text
            except Exception as e:
                last_error = str(e)
                # Chỉ retry nếu lỗi Quota (429) hoặc Server (5xx)
                if any(x in last_error for x in ["429", "500", "502", "503", "Resource has been exhausted"]):
                    wait_time = (2 ** attempt) + random.uniform(1, 3)
                    time.sleep(wait_time)
                    continue
                else:
                    # Các lỗi khác (400 Invalid Key, 403 Permission) -> Trả về lỗi ngay
                    return f"[API Error: {last_error}]"
        
        return f"[System Busy: {last_error}]"

    def translate_text(self, text, source_lang, target_lang, prompt_template=None):
        if not text.strip(): return ""
        
        # Cache check
        cache_key = f"{text}|{source_lang}|{target_lang}"
        if cache_key in self.cache: return self.cache[cache_key]

        base_prompt = prompt_template or "Dịch đoạn văn sau."
        full_prompt = f"{base_prompt}\n\nThông tin:\n- Nguồn: {source_lang}\n- Đích: {target_lang}\n- Văn bản: {text}"

        # Chiến thuật: Flash -> Pro
        result = self._generate_with_retry(self.model_flash, full_prompt)
        
        # Nếu Flash lỗi (khác lỗi Key), thử sang Pro
        if "API Error" in result or "System Busy" in result:
             # Kiểm tra nếu lỗi do Key thì không thử tiếp
             if "400" not in result and "403" not in result:
                 time.sleep(1)
                 result_pro = self._generate_with_retry(self.model_pro, full_prompt)
                 # Nếu Pro thành công thì lấy, không thì giữ lỗi cũ
                 if "API Error" not in result_pro and "System Busy" not in result_pro:
                     result = result_pro

        if "API Error" not in result and "System Busy" not in result:
            self.cache[cache_key] = result.strip()
            
        return result.strip()

    def process_word_by_word(self, text, source_lang, target_lang):
        prompt = f"Phân tích từ vựng: '{text}' (từ {source_lang} sang {target_lang})."
        res = self._generate_with_retry(self.model_flash, prompt, structured_output=InteractiveTranslation)
        
        try:
            if res and "Error" not in res:
                data = InteractiveTranslation.model_validate_json(res)
                return [w.model_dump() for w in data.words]
        except: pass
        
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
