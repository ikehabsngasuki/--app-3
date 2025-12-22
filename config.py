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

    # ===== Optional Basic 認証（Public/認証ありの段階運用） =====
    # Render の Environment Variables に設定してください。
    # - BASIC_AUTH_USER
    # - BASIC_AUTH_PASS
    # - BASIC_AUTH_REALM (任意)
    BASIC_AUTH_USER = os.environ.get("BASIC_AUTH_USER", "")
    BASIC_AUTH_PASS = os.environ.get("BASIC_AUTH_PASS", "")
    BASIC_AUTH_REALM = os.environ.get("BASIC_AUTH_REALM", "英単語テスト")

    # ===== 生成部数の段階制限（Public/認証あり） =====
    # Public: 誰でも利用できる範囲（濫用対策で上限あり）
    PUBLIC_MAX_SETS_PER_REQUEST = int(os.environ.get("PUBLIC_MAX_SETS_PER_REQUEST", "2"))
    PUBLIC_MAX_SETS_PER_DAY = int(os.environ.get("PUBLIC_MAX_SETS_PER_DAY", "10"))

    # Auth: 認証できるユーザー向け（0以下は「上限なし」扱い）
    AUTH_MAX_SETS_PER_REQUEST = int(os.environ.get("AUTH_MAX_SETS_PER_REQUEST", "0"))
    AUTH_MAX_SETS_PER_DAY = int(os.environ.get("AUTH_MAX_SETS_PER_DAY", "0"))

    # 事故防止のための絶対上限（全員共通）
    ABSOLUTE_MAX_SETS_PER_REQUEST = int(os.environ.get("ABSOLUTE_MAX_SETS_PER_REQUEST", "100"))
    ABSOLUTE_MAX_SETS_PER_DAY = int(os.environ.get("ABSOLUTE_MAX_SETS_PER_DAY", "500"))

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
    
    # 生成されたpdfの保管場所　ローカル
    PDF_FOLDER = os.path.join(BASE_DIR, "generated_pdfs")

    # デバッグログ（任意）
    @staticmethod
    def log_env():
        print("[ENV] STORAGE_PROVIDER:", os.environ.get("STORAGE_PROVIDER"))
        print("[ENV] S3_BUCKET:", os.environ.get("S3_BUCKET"))
        print("[ENV] S3_ENDPOINT_URL:", os.environ.get("S3_ENDPOINT_URL"))
        print("[ENV] S3_ACCESS_KEY_ID:", mask(os.environ.get("S3_ACCESS_KEY_ID")))
        print("[ENV] S3_SECRET_ACCESS_KEY:", mask(os.environ.get("S3_SECRET_ACCESS_KEY")))
        print("[ENV] BASIC_AUTH_USER:", mask(os.environ.get("BASIC_AUTH_USER")))
        print("[ENV] BASIC_AUTH_PASS:", "(set)" if os.environ.get("BASIC_AUTH_PASS") else "(unset)")
        print("[ENV] PUBLIC_MAX_SETS_PER_REQUEST:", os.environ.get("PUBLIC_MAX_SETS_PER_REQUEST", "2"))
        print("[ENV] PUBLIC_MAX_SETS_PER_DAY:", os.environ.get("PUBLIC_MAX_SETS_PER_DAY", "10"))
        print("[ENV] AUTH_MAX_SETS_PER_REQUEST:", os.environ.get("AUTH_MAX_SETS_PER_REQUEST", "0"))
        print("[ENV] AUTH_MAX_SETS_PER_DAY:", os.environ.get("AUTH_MAX_SETS_PER_DAY", "0"))
        print("[ENV] ABSOLUTE_MAX_SETS_PER_REQUEST:", os.environ.get("ABSOLUTE_MAX_SETS_PER_REQUEST", "100"))
        print("[ENV] ABSOLUTE_MAX_SETS_PER_DAY:", os.environ.get("ABSOLUTE_MAX_SETS_PER_DAY", "500"))
