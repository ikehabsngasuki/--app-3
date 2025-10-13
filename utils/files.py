# utils/files.py
import os
import re

def safe_filename(name: str) -> str:
    name = os.path.basename(name)           # パストラバーサル対策
    name = name.replace("\x00", "")         # ヌルバイト除去
    name = re.sub(r'[\\/:*?"<>|]+', "_", name)  # 危険記号を _
    return name.strip()

def list_xlsx_local(upload_dir: str):
    files = []
    for f in os.listdir(upload_dir):
        full = os.path.join(upload_dir, f)
        if os.path.isfile(full) and os.path.splitext(f)[1].lower() == ".xlsx":
            files.append(f)
    files.sort(key=lambda x: os.path.getctime(os.path.join(upload_dir, x)), reverse=True)
    return files
