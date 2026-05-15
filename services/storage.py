# services/storage.py
import os
from typing import List, Optional

class Storage:
    """抽象インターフェース"""
    def upload(self, file_or_bytes, key, content_type="application/octet-stream"): ...
    def presign_get(self, key, expires: int) -> Optional[str]: ...
    def list_xlsx(self, prefix: str = "uploads/") -> List[str]: ...
    def open_xlsx_as_bytes(self, key: str) -> bytes: ...


# --- R2 実装 ---
class R2Storage(Storage):
    def __init__(self, bucket, endpoint_url, access_key, secret_key, presign_expires):
        import boto3
        from botocore.config import Config
        self.bucket = bucket
        self.presign_expires = presign_expires
        self.s3 = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name="auto",
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    def upload(self, file_or_bytes, key, content_type="application/octet-stream"):
        body = file_or_bytes.read() if hasattr(file_or_bytes, "read") else file_or_bytes
        self.s3.put_object(Bucket=self.bucket, Key=key, Body=body, ContentType=content_type)

    def presign_get(self, key, expires=None):
        return self.s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires or self.presign_expires,
        )

    def list_xlsx(self, prefix="uploads/"):
        """
        uploads/ 以下の .xlsx を **フルキーのまま** 返す。
        階層を潰さない。大量ファイルに備えて継続トークン対応。
        """
        out = []
        continuation = None
        while True:
            kwargs = {"Bucket": self.bucket, "Prefix": prefix}
            if continuation:
                kwargs["ContinuationToken"] = continuation
            resp = self.s3.list_objects_v2(**kwargs)
            for obj in resp.get("Contents", []):
                key = obj["Key"]
                _, ext = os.path.splitext(key)
                if ext.lower() == ".xlsx":
                    out.append((key, obj["LastModified"]))
            if resp.get("IsTruncated"):
                continuation = resp.get("NextContinuationToken")
            else:
                break
        out.sort(key=lambda x: x[1], reverse=True)
        # ✅ ここで basename にしない
        return [k for k, _ in out]

    def open_xlsx_as_bytes(self, key: str) -> bytes:
        """key は uploads/... を含むフルキー前提"""
        obj = self.s3.get_object(Bucket=self.bucket, Key=key)
        return obj["Body"].read()


# --- ローカル実装 ---
class LocalStorage(Storage):
    """
    ローカルは UPLOAD_FOLDER を uploads/ の実体ディレクトリとみなし、
    返り値・引数ともに 'uploads/...' のキーで扱えるように合わせる。
    """
    def __init__(self, upload_dir: str):
        # 例: cfg.UPLOAD_FOLDER が 実ディレクトリ（…/uploads）を指す
        self.upload_dir = upload_dir

    @staticmethod
    def _strip_prefix(key: str) -> str:
        # 'uploads/aaa/bbb.xlsx' -> 'aaa/bbb.xlsx'
        if key.startswith("uploads/"):
            return key[len("uploads/"):]
        return key.lstrip("/")

    def upload(self, file_or_bytes, key, content_type="application/octet-stream"):
        """
        key 例:
          - 'uploads/中1/Excelデータ/lesson1.xlsx'（推奨）
          - '中1/Excelデータ/lesson1.xlsx'（許容）
        """
        rel = self._strip_prefix(key)  # '中1/Excelデータ/lesson1.xlsx'
        dst = os.path.join(self.upload_dir, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        data = file_or_bytes.read() if hasattr(file_or_bytes, "read") else file_or_bytes
        with open(dst, "wb") as f:
            f.write(data)

    def presign_get(self, key, expires=None):
        # ローカルは署名URLなし → 画面側で /download_file に誘導
        return None

    def list_xlsx(self, prefix="uploads/"):
        """
        uploads/ 配下を再帰で探索して、R2 と同じく **'uploads/...'** で返す。
        更新日時降順（mtime）にソート。
        """
        out: list[str] = []
        base = self.upload_dir  # 実体ディレクトリ（uploads の中身）
        for root, _, files in os.walk(base):
            for name in files:
                if os.path.splitext(name)[1].lower() != ".xlsx":
                    continue
                full = os.path.join(root, name)
                rel = os.path.relpath(full, base).replace("\\", "/")  # '中1/Excelデータ/lesson1.xlsx'
                out.append(rel)
        out.sort(key=lambda rel: os.path.getmtime(os.path.join(base, rel)), reverse=True)
        # ✅ 返り値は 'uploads/...' に揃える
        return [f"uploads/{rel}" for rel in out]

    def open_xlsx_as_bytes(self, key: str) -> bytes:
        """key は 'uploads/...' または相対パスを許容"""
        rel = self._strip_prefix(key)
        path = os.path.join(self.upload_dir, rel)
        with open(path, "rb") as f:
            return f.read()


# --- ファクトリ ---
def get_storage(cfg) -> Storage:
    if cfg.USE_R2:
        return R2Storage(
            bucket=cfg.S3_BUCKET,
            endpoint_url=cfg.S3_ENDPOINT_URL,
            access_key=cfg.S3_ACCESS_KEY_ID,
            secret_key=cfg.S3_SECRET_ACCESS_KEY,
            presign_expires=cfg.PRESIGN_EXPIRES,
        )
    else:
        return LocalStorage(upload_dir=cfg.UPLOAD_FOLDER)
