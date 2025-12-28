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
    BASIC_AUTH_USER = os.environ.get("BASIC_AUTH_USER", "")
    BASIC_AUTH_PASS = os.environ.get("BASIC_AUTH_PASS", "")
    BASIC_AUTH_REALM = os.environ.get("BASIC_AUTH_REALM", "英単語テスト")

    # ===== 生成部数の段階制限（Public/認証あり） =====
    PUBLIC_MAX_SETS_PER_REQUEST = int(os.environ.get("PUBLIC_MAX_SETS_PER_REQUEST", "2"))
    PUBLIC_MAX_SETS_PER_DAY = int(os.environ.get("PUBLIC_MAX_SETS_PER_DAY", "10"))

    AUTH_MAX_SETS_PER_REQUEST = int(os.environ.get("AUTH_MAX_SETS_PER_REQUEST", "0"))
    AUTH_MAX_SETS_PER_DAY = int(os.environ.get("AUTH_MAX_SETS_PER_DAY", "0"))

    ABSOLUTE_MAX_SETS_PER_REQUEST = int(os.environ.get("ABSOLUTE_MAX_SETS_PER_REQUEST", "100"))
    ABSOLUTE_MAX_SETS_PER_DAY = int(os.environ.get("ABSOLUTE_MAX_SETS_PER_DAY", "500"))

    # ===== Cookie / Session 安全設定 =====
    # Render(HTTPS)なら基本 "1" 推奨
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "1") == "1"
    SESSION_COOKIE_HTTPONLY = os.environ.get("SESSION_COOKIE_HTTPONLY", "1") == "1"
    # 通常は Lax が無難（Strict は利便性が落ちる場合あり）
    SESSION_COOKIE_SAMESITE = os.environ.get("SESSION_COOKIE_SAMESITE", "Lax")

    # ===== /make POST 短期レート制限（1分あたり）=====
    PUBLIC_MAKE_POSTS_PER_MINUTE = int(os.environ.get("PUBLIC_MAKE_POSTS_PER_MINUTE", "6"))
    AUTH_MAKE_POSTS_PER_MINUTE = int(os.environ.get("AUTH_MAKE_POSTS_PER_MINUTE", "30"))
    ABSOLUTE_MAKE_POSTS_PER_MINUTE = int(os.environ.get("ABSOLUTE_MAKE_POSTS_PER_MINUTE", "60"))

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

    @staticmethod
    def validate_secret_key_or_raise(is_prod: bool) -> None:
        """
        本番で弱い SECRET_KEY だったら落とす（事故防止）
        """
        sk = (Config.SECRET_KEY or "").strip()
        weak = (sk == "") or (sk == "change-me") or (len(sk) < 32)
        if is_prod and weak:
            raise RuntimeError(
                "FLASK_SECRET_KEY が未設定/弱すぎます。Render の Environment Variables に "
                "32文字以上の強い値を設定してください。"
            )

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
        print("[ENV] BASIC_AUTH_REALM:", os.environ.get("BASIC_AUTH_REALM", "(unset)"))
        print("[ENV] PUBLIC_MAX_SETS_PER_REQUEST:", os.environ.get("PUBLIC_MAX_SETS_PER_REQUEST", "2"))
        print("[ENV] PUBLIC_MAX_SETS_PER_DAY:", os.environ.get("PUBLIC_MAX_SETS_PER_DAY", "10"))
        print("[ENV] AUTH_MAX_SETS_PER_REQUEST:", os.environ.get("AUTH_MAX_SETS_PER_REQUEST", "0"))
        print("[ENV] AUTH_MAX_SETS_PER_DAY:", os.environ.get("AUTH_MAX_SETS_PER_DAY", "0"))
        print("[ENV] ABSOLUTE_MAX_SETS_PER_REQUEST:", os.environ.get("ABSOLUTE_MAX_SETS_PER_REQUEST", "100"))
        print("[ENV] ABSOLUTE_MAX_SETS_PER_DAY:", os.environ.get("ABSOLUTE_MAX_SETS_PER_DAY", "500"))
        print("[ENV] SESSION_COOKIE_SECURE:", os.environ.get("SESSION_COOKIE_SECURE", "1"))
        print("[ENV] SESSION_COOKIE_HTTPONLY:", os.environ.get("SESSION_COOKIE_HTTPONLY", "1"))
        print("[ENV] SESSION_COOKIE_SAMESITE:", os.environ.get("SESSION_COOKIE_SAMESITE", "Lax"))
        print("[ENV] PUBLIC_MAKE_POSTS_PER_MINUTE:", os.environ.get("PUBLIC_MAKE_POSTS_PER_MINUTE", "6"))
        print("[ENV] AUTH_MAKE_POSTS_PER_MINUTE:", os.environ.get("AUTH_MAKE_POSTS_PER_MINUTE", "30"))
        print("[ENV] ABSOLUTE_MAKE_POSTS_PER_MINUTE:", os.environ.get("ABSOLUTE_MAKE_POSTS_PER_MINUTE", "60"))
