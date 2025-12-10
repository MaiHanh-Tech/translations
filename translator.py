import streamlit as st
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
import time
import jieba
from pypinyin import pinyin, Style
import os
from typing import List, Optional
from pydantic import BaseModel, Field

# Định nghĩa cấu trúc dữ liệu trả về cho chế độ Word-by-word dùng Pydantic
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
            # Lấy API Key từ secrets
            self.api_key = st.secrets.get("google_genai", {}).get("api_key", "")
            if not self.api_key:
                # Fallback nếu user để key ở tầng ngoài cùng
                self.api_key = st.secrets.get("api_key", "")
            
            if self.api_key:
                genai.configure(api_key=self.api_key)
            
            # Cấu hình Model
            self.model_pro_name = st.secrets.get("google_genai", {}).get("model_pro", "gemini-1.5-pro")
            self.model_flash_name = st.secrets.get("google_genai", {}).get("model_flash", "gemini-1.5-flash")
            
            # Cấu hình an toàn (Tắt chặn để dịch thoải mái hơn)
            self.safety_settings = {
                HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
            }

            self.generation_config = {
                "temperature": 0.3, # Thấp để dịch chính xác
                "top_p": 0.95,
                "top_k": 64,
                "max_output_tokens": 8192,
            }

            self.translated_cache = {}
            self.initialized = True

    def get_model(self, use_flash=False, structured_output=None):
        model_name = self.model_flash_name if use_flash else self.model_pro_name
        
        # Nếu dùng structured output (Pydantic mode)
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

    def _generate_content_with_fallback(self, prompt, structured_output=None):
        """Thử dùng Pro, nếu thất bại thì trượt về Flash"""
        try:
            # Thử Model Pro/Chính
            model = self.get_model(use_flash=False, structured_output=structured_output)
            response = model.generate_content(prompt)
            return response.text
        except Exception as e:
            print(f"Primary model failed ({str(e)}). Switching to Flash...")
            try:
                # Fallback sang Flash
                model = self.get_model(use_flash=True, structured_output=structured_output)
                response = model.generate_content(prompt)
                return response.text
            except Exception as e2:
                print(f"Backup model also failed: {str(e2)}")
                return ""

    def translate_text(self, text, source_lang, target_lang, prompt_template=None):
        """Dịch văn bản thông thường"""
        if not text.strip():
            return ""
            
        cache_key = f"{text}_{source_lang}_{target_lang}"
        if cache_key in self.translated_cache:
            return self.translated_cache[cache_key]

        # Xây dựng prompt
        base_prompt = prompt_template if prompt_template else "Dịch đoạn văn bản sau."
        
        full_prompt = f"""
        {base_prompt}
        
        Thông tin dịch thuật:
        - Ngôn ngữ nguồn: {source_lang}
        - Ngôn ngữ đích: {target_lang}
        
        Văn bản cần dịch:
        {text}
        
        Chỉ trả về kết quả dịch, không bao gồm giải thích hay đánh dấu markdown (trừ khi văn bản gốc có).
        """

        translation = self._generate_content_with_fallback(full_prompt)
        
        if translation:
            self.translated_cache[cache_key] = translation.strip()
            return translation.strip()
        return "[Translation Error]"

    def process_word_by_word(self, text, source_lang, target_lang):
        """
        Sử dụng Gemini để phân tích từ vựng và dịch từng từ (Thay thế Jieba+Azure cũ).
        Trả về danh sách dict chuẩn.
        """
        prompt = f"""
        Phân tích đoạn văn bản sau để học ngôn ngữ.
        Văn bản gốc ({source_lang}): "{text}"
        Ngôn ngữ đích để giải nghĩa: {target_lang}

        Hãy chia văn bản thành các từ hoặc cụm từ có nghĩa (segmentation).
        Với mỗi từ:
        1. Xác định từ gốc.
        2. Nếu là tiếng Trung, cung cấp Pinyin (kèm thanh điệu). Nếu không phải tiếng Trung, để trống pinyin.
        3. Cung cấp nghĩa ngắn gọn trong ngữ cảnh này.
        """

        try:
            # Sử dụng Structured Output với Pydantic
            model = self.get_model(use_flash=True, structured_output=InteractiveTranslation) # Dùng Flash cho nhanh
            response = model.generate_content(prompt)
            
            # Parse kết quả
            import json
            result_json = json.loads(response.text)
            
            processed_words = []
            for item in result_json.get('words', []):
                processed_words.append({
                    'word': item['word'],
                    'pinyin': item['pinyin'],
                    'translations': [item['translation']]
                })
            return processed_words

        except Exception as e:
            print(f"Error in interactive mode via Gemini: {e}")
            # Fallback về cách cũ (Jieba) nếu Gemini lỗi JSON, nhưng ở đây ta dùng logic đơn giản để tránh crash
            return self._fallback_local_segmentation(text)

    def _fallback_local_segmentation(self, text):
        """Fallback dùng Jieba nội bộ nếu API lỗi"""
        words = list(jieba.cut(text))
        results = []
        for word in words:
            py = ""
            if '\u4e00' <= word <= '\u9fff':
                 py = ' '.join([item[0] for item in pinyin(word, style=Style.TONE)])
            results.append({
                'word': word,
                'pinyin': py,
                'translations': []
            })
        return results
