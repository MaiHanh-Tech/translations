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

        for attempt in range(5):
            try:
                response = model.generate_content(prompt)
                if response.text: return response.text
            except Exception as e:
                error_msg = str(e)
                if "429" in error_msg or "Resource has been exhausted" in error_msg:
                    wait_time = 30 + (attempt * 10) # Chờ 30s nếu quá tải
                    time.sleep(wait_time)
                    continue
                elif "500" in error_msg or "503" in error_msg:
                    time.sleep(5)
                    continue
                else:
                    return f"[API Error: {error_msg}]"
        
        return "[System Busy: 429 Quota Exceeded. Please try again later.]"

    def translate_text(self, text, source, target, prompt_template=None):
        if not text.strip(): return ""
        cache_key = f"{text}|{source}|{target}"
        if cache_key in self.cache: return self.cache[cache_key]

        full_prompt = f"{prompt_template or 'Dịch:'}\nNguồn: {source}\nĐích: {target}\nVăn bản: {text}"
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
