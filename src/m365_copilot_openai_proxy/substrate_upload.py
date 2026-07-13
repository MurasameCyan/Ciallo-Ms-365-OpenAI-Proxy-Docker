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
    """
    data_url = f"data:{image.media_type};base64,{image.base64}"
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
