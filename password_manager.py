import streamlit as st
from datetime import datetime
from collections import defaultdict

class PasswordManager:
    def __init__(self):
        # Lấy danh sách API keys hợp lệ từ secrets
        # Giả sử cấu trúc secrets.toml:
        # [api_keys]
        # user1 = "key_cua_user_1"
        # user2 = "key_cua_user_2"
        self.api_keys = st.secrets.get("api_keys", {})
        self.user_tiers = st.secrets.get("user_tiers", {})
        
        # Limits
        self.default_limit = st.secrets.get("usage_limits", {}).get("default_daily_limit", 30000)
        self.premium_limit = st.secrets.get("usage_limits", {}).get("premium_daily_limit", 100000)
        
        if 'usage_tracking' not in st.session_state:
            st.session_state.usage_tracking = {}

    def check_password(self, password):
        if not password: return False
        
        # Admin check
        if password == st.secrets.get("admin_password"):
            return True
            
        # User check
        return password in self.api_keys.values()

    def is_admin(self, password):
        return password == st.secrets.get("admin_password")

    def get_user_limit(self, user_key):
        if self.is_admin(user_key): return 9999999
        # Tìm key name từ value (ngược)
        key_name = next((k for k, v in self.api_keys.items() if v == user_key), "default")
        tier = self.user_tiers.get(key_name, "default")
        return self.premium_limit if tier == "premium" else self.default_limit

    def check_usage_limit(self, user_key, count):
        current = self.get_daily_usage(user_key)
        limit = self.get_user_limit(user_key)
        return (current + count) <= limit

    def track_usage(self, user_key, count):
        today = datetime.now().date().isoformat()
        if user_key not in st.session_state.usage_tracking:
            st.session_state.usage_tracking[user_key] = {}
        
        current = st.session_state.usage_tracking[user_key].get(today, 0)
        st.session_state.usage_tracking[user_key][today] = current + count

    def get_daily_usage(self, user_key):
        today = datetime.now().date().isoformat()
        if user_key in st.session_state.usage_tracking:
            return st.session_state.usage_tracking[user_key].get(today, 0)
        return 0
    
    def get_usage_stats(self):
        # Hàm hỗ trợ cho Admin dashboard (nếu cần dùng lại)
        return {'total_users': len(st.session_state.usage_tracking)}
