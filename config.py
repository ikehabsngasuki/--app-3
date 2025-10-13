# config.py
import os

def mask(s, keep=4):
    return s[:keep] + "..." if s else "(unset)"

class Config:
    # Flask 基本
    SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "change-me")
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB

    # ディレクトリ
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    TEMPLATE_DIR = os.path.join(BASE_DIR, "templates")
    UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
    FONTS_DIR = os.path.join(BASE_DIR, "fonts")

    # 拡張子
    ALLOWED_UPLOAD_EXTENSIONS = {".xlsx"}
    ALLOWED_DOWNLOAD_EXTENSIONS = {".pdf", ".xlsx"}

    # ストレージ（R2 切り替え）
    USE_R2 = os.environ.get("STORAGE_PROVIDER", "").lower() == "r2"
    PRESIGN_EXPIRES = int(os.getenv("PRESIGN_EXPIRES", "3600"))

    # R2 環境変数（USE_R2=True のときに使用）
    S3_ENDPOINT_URL = os.environ.get("S3_ENDPOINT_URL")
    S3_ACCESS_KEY_ID = os.environ.get("S3_ACCESS_KEY_ID")
    S3_SECRET_ACCESS_KEY = os.environ.get("S3_SECRET_ACCESS_KEY")
    S3_BUCKET = os.environ.get("S3_BUCKET")

    # デバッグログ（任意）
    @staticmethod
    def log_env():
        print("[ENV] STORAGE_PROVIDER:", os.environ.get("STORAGE_PROVIDER"))
        print("[ENV] S3_BUCKET:", os.environ.get("S3_BUCKET"))
        print("[ENV] S3_ENDPOINT_URL:", os.environ.get("S3_ENDPOINT_URL"))
        print("[ENV] S3_ACCESS_KEY_ID:", mask(os.environ.get("S3_ACCESS_KEY_ID")))
        print("[ENV] S3_SECRET_ACCESS_KEY:", mask(os.environ.get("S3_SECRET_ACCESS_KEY")))
