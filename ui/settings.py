"""Serialize settings read/modify/write operations across GUI workers."""
from threading import RLock
from app_settings import save_setting as _save_setting

_lock = RLock()


def save_setting(key, value):
    with _lock:
        _save_setting(key, value)
