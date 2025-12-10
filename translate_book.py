import streamlit as st
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
import time
import random
import jieba
from pypinyin import pinyin, Style
import os
from typing import List, Optional
from pydantic import BaseModel, Field
import json

class WordDefinition(BaseModel):
    word: str = Field(description="Từ gốc hoặc cụm từ")
    pinyin: str = Field(description="Phiên âm Pinyin (nếu là tiếng Trung), hoặc để trống")
    translation: str = Field(description="Nghĩa của từ trong ngữ cảnh này")

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
            # Lấy API Key
            self.api_key = st.secrets.get("google_genai", {}).get("api_key", "")
            if not self.api_key:
                self.api_key = st.secrets.get("api_key", "")
            
            if self.api_key:
                genai.configure(api_key=self.api_key)
            
            self.model_pro_name = st.secrets.get("google_genai", {}).get("model_pro", "gemini-1.5-pro")
            self.model_flash_name = st.secrets.get("google_genai", {}).get("model_flash", "gemini-1.5-flash")
            
            self.safety_settings = {
                HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
            }

            self.generation_config = {
                "temperature": 0.3,
                "top_p": 0.95,
                "top_k": 64,
                "max_output_tokens": 8192,
            }

            self.translated_cache = {}
            self.initialized = True

    def get_model(self, use_flash=False, structured_output=None):
        model_name = self.model_flash_name if use_flash else self.model_pro_name
        
        if structured_output:
            return genai.GenerativeModel(
                model_name=model_name,
                generation_config=genai.GenerationConfig(
                    response_mime_type="application/json",
                    response_schema=structured_output
                ),
                safety_settings=self.safety_settings
            )
        
        return genai.GenerativeModel(
            model_name=model_name,
            generation_config=self.generation_config,
            safety_settings=self.safety_settings
        )

    def _generate_with_retry(self, model, prompt, retries=3):
        """Cơ chế thử lại khi gặp lỗi"""
        last_error = None
        for i in range(retries):
            try:
                response = model.generate_content(prompt)
                if response.text:
                    return response.text
            except Exception as e:
                error_str = str(e)
                last_error = e
                # Nếu lỗi 429 (Resource Exhausted) hoặc lỗi mạng thì chờ rồi thử lại
                if "429" in error_str or "Resource has been exhausted" in error_str or "500" in error_str:
                    wait_time = (2 ** i) + random.uniform(0, 1) # Chờ 1s, 2s, 4s...
                    print(f"API Busy/Error. Retrying in {wait_time:.1f}s... (Attempt {i+1}/{retries})")
                    time.sleep(wait_time)
                    continue
                else:
                    # Các lỗi khác (như sai Key, Blocked) thì dừng ngay
                    print(f"Non-retriable error: {error_str}")
                    break
        
        print(f"Failed after {retries} attempts. Last error: {last_error}")
        return None

    def _generate_content_with_fallback(self, prompt, structured_output=None):
        # Ưu tiên 1: Dùng Flash cho nhanh và rẻ (tránh lỗi quota của Pro)
        # Nếu bạn muốn Pro, hãy đổi False thành True ở dòng dưới
        try:
            model = self.get_model(use_flash=True, structured_output=structured_output)
            result = self._generate_with_retry(model, prompt)
            if result: return result
            
            # Ưu tiên 2: Nếu Flash lỗi, thử sang Pro (Fallback ngược)
            print("Flash model failed, trying Pro...")
            model = self.get_model(use_flash=False, structured_output=structured_output)
            result = self._generate_with_retry(model, prompt)
            return result
            
        except Exception as e:
            print(f"All models failed: {str(e)}")
            return None

    def translate_text(self, text, source_lang, target_lang, prompt_template=None):
        if not text.strip(): return ""
            
        cache_key = f"{text}_{source_lang}_{target_lang}"
        if cache_key in self.translated_cache:
            return self.translated_cache[cache_key]

        base_prompt = prompt_template if prompt_template else "Dịch văn bản sau."
        full_prompt = f"""
        {base_prompt}
        
        [Thông tin]
        - Nguồn: {source_lang}
        - Đích: {target_lang}
        
        [Văn bản]
        {text}
        
        [Yêu cầu]
        Chỉ trả về bản dịch.
        """

        translation = self._generate_content_with_fallback(full_prompt)
        
        if translation:
            self.translated_cache[cache_key] = translation.strip()
            return translation.strip()
        
        # Trả về chuỗi rỗng thay vì "[Translation Error]" để UI trông đỡ xấu nếu lỗi nhẹ
        return "[Lỗi kết nối API - Vui lòng thử lại]"

    def process_word_by_word(self, text, source_lang, target_lang):
        prompt = f"""
        Phân tích văn bản ({source_lang}) sang ({target_lang}).
        Tách từ, Pinyin (nếu Trung), Nghĩa.
        Văn bản: "{text}"
        """
        try:
            model = self.get_model(use_flash=True, structured_output=InteractiveTranslation)
            response_text = self._generate_with_retry(model, prompt)
            
            if response_text:
                result_json = json.loads(response_text)
                return [{
                    'word': item['word'],
                    'pinyin': item['pinyin'],
                    'translations': [item['translation']]
                } for item in result_json.get('words', [])]
            
        except Exception as e:
            print(f"Gemini interactive failed: {e}")
        
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
