# services/storage.py
import io
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
        out = []
        resp = self.s3.list_objects_v2(Bucket=self.bucket, Prefix=prefix)
        for obj in resp.get("Contents", []):
            key = obj["Key"]
            _, ext = os.path.splitext(key)
            if ext.lower() == ".xlsx":
                out.append((key, obj["LastModified"]))
        out.sort(key=lambda x: x[1], reverse=True)
        return [os.path.basename(k) for k, _ in out]

    def open_xlsx_as_bytes(self, key: str) -> bytes:
        obj = self.s3.get_object(Bucket=self.bucket, Key=key)
        return obj["Body"].read()

# --- ローカル実装 ---
class LocalStorage(Storage):
    def __init__(self, upload_dir: str):
        self.upload_dir = upload_dir

    def upload(self, file_or_bytes, key, content_type="application/octet-stream"):
        # key は "uploads/xxx.xlsx" 想定 → ローカルでは uploads/ 配下に落とす
        filename = os.path.basename(key)
        dst = os.path.join(self.upload_dir, filename)
        if hasattr(file_or_bytes, "read"):
            data = file_or_bytes.read()
        else:
            data = file_or_bytes
        with open(dst, "wb") as f:
            f.write(data)

    def presign_get(self, key, expires=None):
        # ローカルは署名URLなし → 画面側で /download_file に誘導
        return None

    def list_xlsx(self, prefix="uploads/"):
        from utils.files import list_xlsx_local
        return list_xlsx_local(self.upload_dir)

    def open_xlsx_as_bytes(self, key: str) -> bytes:
        # key はファイル名想定（routes で basename 渡す）
        path = os.path.join(self.upload_dir, os.path.basename(key))
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
