"""Cloud-ready file storage adapter with a local development backend."""
import uuid
from pathlib import Path

import boto3
from flask import current_app
from werkzeug.utils import secure_filename

MAX_UPLOAD_BYTES = 100 * 1024 * 1024


def _s3_client():
    return boto3.client(
        "s3",
        endpoint_url=current_app.config.get("S3_ENDPOINT_URL") or None,
        region_name=current_app.config["AWS_REGION"],
    )


def upload_size_bytes(file):
    stream = file.stream
    position = stream.tell()
    stream.seek(0, 2)
    size = stream.tell()
    stream.seek(position)
    return size


def save_upload(file, allowed_extensions=None, category="resources"):
    name = secure_filename(file.filename or "")
    if not name:
        raise ValueError("Choose a file with a valid filename.")
    allowed_extensions = allowed_extensions or {".pdf", ".doc", ".docx", ".ppt", ".pptx"}
    if Path(name).suffix.lower() not in allowed_extensions:
        raise ValueError("This file type is not supported.")
    if upload_size_bytes(file) > MAX_UPLOAD_BYTES:
        raise ValueError("This file exceeds the 100 MB upload limit.")
    key = f"{category}/{uuid.uuid4().hex}/{name}"
    bucket = current_app.config["S3_BUCKET"]
    if bucket:
        client = _s3_client()
        client.upload_fileobj(file, bucket, key, ExtraArgs={"ContentType": file.mimetype or "application/octet-stream"})
    else:
        target = current_app.config["UPLOAD_FOLDER"] / key
        target.parent.mkdir(parents=True, exist_ok=True)
        file.save(target)
    return key, name


def upload_url(key):
    bucket = current_app.config["S3_BUCKET"]
    if bucket:
        client = _s3_client()
        return client.generate_presigned_url("get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=900)
    return f"/resources/{key}"


def local_path(key):
    root = current_app.config["UPLOAD_FOLDER"].resolve()
    path = (root / key).resolve()
    if root not in path.parents:
        raise ValueError("Invalid storage key")
    return path


def delete_upload(key):
    bucket = current_app.config["S3_BUCKET"]
    if bucket:
        client = _s3_client()
        client.delete_object(Bucket=bucket, Key=key)
        return
    path = local_path(key)
    if path.is_file():
        path.unlink()
