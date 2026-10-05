"""Presigned S3 playback URLs for call recordings.

The bucket is never public and no URL is stored permanently — recordings
are sensitive (full call audio), so a short-lived signed URL is generated
on demand each time a recording is requested instead. Generating the URL
itself is a local HMAC computation (no network call) — but *constructing*
a boto3 client is not free (botocore loads and parses its service model
JSON, ~100-300ms cold) and is fully synchronous, so building one per
request would block the event loop on every recording playback request.
"""

from typing import Any

import boto3

from app.config import settings

_URL_EXPIRES_IN_SEC = 300

# Cached per (region, access_key, secret) rather than a single global
# singleton — cheap to key on, and correct if credentials are ever rotated
# without a process restart (tests also rely on this: monkeypatched
# settings must produce a client for the new credentials, not a stale one).
_clients: dict[tuple[str, str, str], Any] = {}


def is_configured() -> bool:
    return bool(
        settings.s3_bucket and settings.s3_access_key_id and settings.s3_secret_access_key
    )


def _get_client() -> Any:
    cache_key = (settings.s3_region, settings.s3_access_key_id, settings.s3_secret_access_key)
    client = _clients.get(cache_key)
    if client is None:
        client = boto3.client(
            "s3",
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key_id,
            aws_secret_access_key=settings.s3_secret_access_key,
        )
        _clients.clear()  # a rotated credential makes every older client dead weight
        _clients[cache_key] = client
    return client


def presign_recording_url(key: str) -> str:
    return _get_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.s3_bucket, "Key": key},
        ExpiresIn=_URL_EXPIRES_IN_SEC,
    )
