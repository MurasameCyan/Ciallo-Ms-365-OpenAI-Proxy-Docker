from __future__ import annotations

"""Upload inbound images to M365 Copilot so the model can see them.

Mirrors the M365 web client's UploadFile flow (verified via M365Bridge): the
image is POSTed as multipart/form-data to substrate.office.com/m365Copilot/UploadFile
using the same substrate bearer token already used for chat. The response
carries a ``docId`` that is then attached to the outgoing chat message as a
``messageAnnotations`` entry (type ``ImageFile``), which is how the backend
links an uploaded image to a turn.
"""

import logging

import httpx

from .models import ImageData

_log = logging.getLogger(__name__)

_UPLOAD_URL = "https://substrate.office.com/m365Copilot/UploadFile"
_ORIGIN = "https://m365.cloud.microsoft"
_UPLOAD_TIMEOUT_SECONDS = 30.0
_DOWNLOAD_TIMEOUT_SECONDS = 20.0
# Cap remote image downloads so a hostile/huge URL can't exhaust memory.
_MAX_REMOTE_IMAGE_BYTES = 20 * 1024 * 1024


async def _fetch_remote_image(url: str) -> tuple[str, str] | None:
    """Download a remote http(s) image, returning (base64, media_type).

    Returns None (and logs a warning) on any failure or if the payload is not an
    image / exceeds the size cap, so the caller can skip it gracefully."""
    import base64 as _b64

    try:
        async with httpx.AsyncClient(timeout=_DOWNLOAD_TIMEOUT_SECONDS, follow_redirects=True) as client:
            resp = await client.get(url)
    except Exception as exc:  # noqa: BLE001 - network/transport failures
        _log.warning("remote image download failed (transport): %s", exc)
        return None

    if resp.status_code != 200:
        _log.warning("remote image download failed status=%s url=%s", resp.status_code, url[:200])
        return None

    content = resp.content
    if not content:
        _log.warning("remote image download empty url=%s", url[:200])
        return None
    if len(content) > _MAX_REMOTE_IMAGE_BYTES:
        _log.warning("remote image too large (%d bytes) url=%s", len(content), url[:200])
        return None

    media_type = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
    if not media_type.startswith("image/"):
        _log.warning("remote url is not an image (content-type=%s) url=%s", media_type, url[:200])
        return None

    return _b64.b64encode(content).decode("ascii"), media_type


def _annotation_from_result(result: dict, image: ImageData) -> dict:
    """Build the messageAnnotations entry that links docId to the chat turn."""
    file_type = str(result.get("fileType") or "").lstrip(".") or "png"
    return {
        "id": result.get("docId") or "",
        "messageAnnotationType": "ImageFile",
        "messageAnnotationMetadata": {
            "@type": "File",
            "annotationType": "File",
            "fileType": file_type,
            "fileName": result.get("fileName") or image.file_name,
        },
    }


async def upload_image(
    token: str,
    oid: str,
    tid: str,
    conversation_id: str,
    image: ImageData,
) -> dict | None:
    """Upload one image and return its messageAnnotations entry.

    Returns None (and logs a warning) if the upload does not succeed, so the
    caller can decide whether to continue text-only rather than hard-failing.

    Accepts both inline (base64) and remote (http(s) url) images: remote images
    are downloaded here and turned into base64 before upload, since M365
    UploadFile only accepts inline bytes.
    """
    b64 = image.base64
    media_type = image.media_type
    if not b64 and image.url:
        fetched = await _fetch_remote_image(image.url)
        if not fetched:
            return None
        b64, media_type = fetched
    if not b64:
        _log.warning("image has neither base64 nor a usable url; skipping")
        return None
    data_url = f"data:{media_type};base64,{b64}"
    # All fields are plain multipart form fields (no filename), matching the
    # web client. httpx emits multipart/form-data when using the files= param;
    # the (None, value) form marks a value as a non-file field.
    files = {
        "scenario": (None, "UploadImage"),
        "conversationId": (None, conversation_id),
        "FileBase64": (None, data_url),
        "optionsSets": (None, "gptvnorm2048"),
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Origin": _ORIGIN,
        "x-scenario": "OfficeWebIncludedCopilot",
        "x-variants": "feature.EnableImageSupportInUploadFile",
    }
    if oid and tid:
        headers["x-anchormailbox"] = f"Oid:{oid}@{tid}"

    try:
        async with httpx.AsyncClient(timeout=_UPLOAD_TIMEOUT_SECONDS) as client:
            resp = await client.post(_UPLOAD_URL, files=files, headers=headers)
    except Exception as exc:  # noqa: BLE001 - network/transport failures
        _log.warning("image upload failed (transport): %s", exc)
        return None

    if resp.status_code != 200:
        _log.warning(
            "image upload failed status=%s body=%s",
            resp.status_code,
            resp.text[:300],
        )
        return None

    try:
        result = resp.json()
    except ValueError as exc:
        _log.warning("image upload returned non-JSON: %s", exc)
        return None

    if str((result.get("result") or {}).get("value")) != "Success":
        _log.warning("image upload not successful: %s", str(result)[:300])
        return None

    return _annotation_from_result(result, image)
