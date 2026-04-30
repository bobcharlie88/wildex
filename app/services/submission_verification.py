from __future__ import annotations

import io
import json
import logging
import math
from datetime import datetime

from app.config import SUBMISSION_CLEAR_THRESHOLD, SUBMISSION_REJECT_THRESHOLD

try:
    from PIL import ExifTags, Image, ImageFilter, ImageStat
except ImportError:  # pragma: no cover
    ExifTags = None
    Image = None
    ImageFilter = None
    ImageStat = None

log = logging.getLogger("wildex.submission_verification")

AI_SOFTWARE_MARKERS = (
    "midjourney",
    "stable diffusion",
    "sdxl",
    "dall-e",
    "openai",
    "firefly",
    "ideogram",
    "leonardo",
    "flux",
    "generative fill",
    "dream",
)

EDIT_SOFTWARE_MARKERS = (
    "photoshop",
    "lightroom",
    "gimp",
    "canva",
    "snapseed",
    "facetune",
    "pixelmator",
    "affinity",
)


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _safe_json(value) -> str:
    return json.dumps(value, ensure_ascii=True)


def _decode_exif(image) -> dict[str, object]:
    if Image is None:
        return {}
    exif_raw = getattr(image, "getexif", lambda: {})() or {}
    decoded = {}
    tag_map = getattr(ExifTags, "TAGS", {}) if ExifTags is not None else {}
    for key, value in exif_raw.items():
        decoded[tag_map.get(key, str(key))] = value
    return decoded


def _gps_dict(decoded_exif: dict[str, object]) -> dict:
    gps = decoded_exif.get("GPSInfo")
    if not gps or ExifTags is None:
        return {}
    gps_tags = getattr(ExifTags, "GPSTAGS", {})
    mapped = {}
    if isinstance(gps, dict):
        for key, value in gps.items():
            mapped[gps_tags.get(key, str(key))] = value
    return mapped


def _to_float_rational(value) -> float | None:
    try:
        if isinstance(value, tuple) and len(value) == 2 and value[1]:
            return float(value[0]) / float(value[1])
        if hasattr(value, "numerator") and hasattr(value, "denominator") and value.denominator:
            return float(value.numerator) / float(value.denominator)
        return float(value)
    except Exception:
        return None


def _gps_to_decimal(coords, ref: str | None) -> float | None:
    if not coords or len(coords) != 3:
        return None
    parts = [_to_float_rational(part) for part in coords]
    if any(part is None for part in parts):
        return None
    degrees = parts[0] + (parts[1] / 60.0) + (parts[2] / 3600.0)
    if ref in {"S", "W"}:
        degrees *= -1
    return round(degrees, 6)


def _parse_capture_datetime(decoded_exif: dict[str, object]) -> tuple[str | None, str]:
    for key in ("DateTimeOriginal", "DateTimeDigitized", "DateTime"):
        value = decoded_exif.get(key)
        if not value:
            continue
        text = str(value).strip()
        for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
            try:
                dt = datetime.strptime(text, fmt)
                if dt > datetime.utcnow():
                    return text, "Capture timestamp appears to be in the future."
                return dt.isoformat(sep=" "), "Capture timestamp present and parseable."
            except Exception:
                continue
        return text, "Capture timestamp present but not in a standard EXIF format."
    return None, "No capture timestamp found in metadata."


def _entropy(image) -> float | None:
    if Image is None:
        return None
    histogram = image.convert("L").histogram()
    total = float(sum(histogram) or 1.0)
    entropy = 0.0
    for count in histogram:
        if count <= 0:
            continue
        probability = count / total
        entropy -= probability * math.log(probability, 2)
    return entropy


def _edge_density(image) -> float | None:
    if Image is None or ImageFilter is None or ImageStat is None:
        return None
    edges = image.convert("L").filter(ImageFilter.FIND_EDGES)
    stats = ImageStat.Stat(edges)
    mean = stats.mean[0] if stats.mean else 0.0
    return float(mean) / 255.0


def verify_submission_image(
    *,
    data: bytes,
    filename: str,
    content_type: str | None,
    observed_date: str | None = None,
) -> dict:
    suspicious_findings: list[str] = []
    authenticity = 0.58
    ai_suspicion = 0.10
    metadata_present = False
    gps_present = False
    gps_summary = None
    device_info = "Unavailable"
    image_format = "unknown"
    width = None
    height = None
    software = None
    metadata_summary: dict[str, object] = {"filename": filename, "content_type": content_type}

    if Image is None:
        suspicious_findings.append("Advanced image inspection is unavailable on this server; verification relied on limited file checks.")
        authenticity -= 0.08
        ai_suspicion += 0.05
        capture_datetime, date_time_check = None, "Image library unavailable for EXIF inspection."
    else:
        try:
            image = Image.open(io.BytesIO(data))
            image.load()
        except Exception as exc:
            log.warning("Submission image could not be decoded filename=%s error=%s", filename, exc)
            suspicious_findings.append("Uploaded file could not be decoded as a trustworthy image; it may be corrupt, incomplete, or invalid.")
            authenticity -= 0.42
            ai_suspicion += 0.18
            capture_datetime, date_time_check = None, "Image data could not be decoded for EXIF inspection."
            metadata_summary.update(
                {
                    "decode_error": str(exc),
                    "metadata_present": False,
                    "gps_present": False,
                    "device_info": device_info,
                    "image_format": image_format,
                    "dimensions": None,
                }
            )
            image = None
        if image is None:
            metadata_present = False
        else:
            image_format = str(getattr(image, "format", "unknown") or "unknown").upper()
            width, height = image.size
            decoded_exif = _decode_exif(image)
            metadata_present = bool(decoded_exif)
            gps_info = _gps_dict(decoded_exif)
            gps_lat = _gps_to_decimal(gps_info.get("GPSLatitude"), gps_info.get("GPSLatitudeRef"))
            gps_lon = _gps_to_decimal(gps_info.get("GPSLongitude"), gps_info.get("GPSLongitudeRef"))
            gps_present = gps_lat is not None and gps_lon is not None
            if gps_present:
                gps_summary = {"latitude": gps_lat, "longitude": gps_lon}
            capture_datetime, date_time_check = _parse_capture_datetime(decoded_exif)
            make = str(decoded_exif.get("Make") or "").strip()
            model = str(decoded_exif.get("Model") or "").strip()
            software = str(decoded_exif.get("Software") or "").strip().lower() or None
            device_info = " / ".join(part for part in (make, model) if part) or "Unavailable"

            metadata_summary.update(
                {
                    "format": image_format,
                    "dimensions": {"width": width, "height": height},
                    "metadata_keys": sorted(decoded_exif.keys()),
                    "software": software,
                    "gps": gps_summary,
                }
            )

            if metadata_present:
                authenticity += 0.10
            else:
                authenticity += 0.03
                authenticity -= 0.12
                suspicious_findings.append("No EXIF metadata was present; the file may have been re-exported or stripped.")

            if make or model:
                authenticity += 0.10
            else:
                authenticity -= 0.05
                suspicious_findings.append("No camera or device information was found in the metadata.")

            if capture_datetime:
                authenticity += 0.09
            else:
                authenticity -= 0.07

            if gps_present:
                authenticity += 0.05
            else:
                suspicious_findings.append("No GPS coordinates were present in the image metadata.")

            if software:
                if any(marker in software for marker in AI_SOFTWARE_MARKERS):
                    ai_suspicion += 0.55
                    authenticity -= 0.35
                    suspicious_findings.append(f"Metadata software tag references AI or generative tooling: {software}.")
                elif any(marker in software for marker in EDIT_SOFTWARE_MARKERS):
                    ai_suspicion += 0.18
                    authenticity -= 0.14
                    suspicious_findings.append(f"Metadata software tag suggests editing or re-export: {software}.")
                else:
                    authenticity -= 0.03
            else:
                authenticity += 0.03

            if image_format in {"PNG", "WEBP"}:
                authenticity -= 0.08
                ai_suspicion += 0.08
                suspicious_findings.append(f"Image is stored as {image_format}, which is less typical than JPEG/HEIC for untouched phone camera photos.")

            if width and height:
                if width == height and width in {1024, 1536, 2048, 3072, 4096}:
                    authenticity -= 0.08
                    ai_suspicion += 0.12
                    suspicious_findings.append("Image dimensions are an exact square export size commonly seen in generated or heavily processed images.")
                if min(width, height) < 640:
                    authenticity -= 0.05
                    suspicious_findings.append("Image resolution is relatively small for an original modern phone photo.")

            entropy = _entropy(image)
            if entropy is not None:
                metadata_summary["luminance_entropy"] = round(entropy, 3)
                if entropy < 4.2:
                    authenticity -= 0.10
                    ai_suspicion += 0.10
                    suspicious_findings.append("Image has unusually low tonal entropy, which can indicate over-processing or synthetic generation.")
                elif entropy > 7.3:
                    authenticity += 0.03

            edge_density = _edge_density(image)
            if edge_density is not None:
                metadata_summary["edge_density"] = round(edge_density, 4)
                if edge_density < 0.045:
                    authenticity -= 0.06
                    ai_suspicion += 0.06
                    suspicious_findings.append("Image edge density is unusually low, suggesting smoothing or non-photographic content.")

            if observed_date and capture_datetime:
                try:
                    observed = datetime.fromisoformat(observed_date).date()
                    captured = datetime.fromisoformat(capture_datetime.replace(" ", "T")).date()
                    if observed != captured:
                        authenticity -= 0.04
                        suspicious_findings.append("Submitted observed date does not match the image capture date in metadata.")
                except Exception:
                    pass

    metadata_summary.update(
        {
            "metadata_present": metadata_present,
            "gps_present": gps_present,
            "device_info": device_info,
            "image_format": image_format,
            "dimensions": {"width": width, "height": height} if width and height else None,
        }
    )

    authenticity = _clamp(authenticity)
    ai_suspicion = _clamp(ai_suspicion)

    if authenticity >= SUBMISSION_CLEAR_THRESHOLD and ai_suspicion < 0.35:
        recommendation = "cleared"
        status = "cleared"
        verification_reason = "High-confidence submission with limited suspicious indicators."
    elif authenticity <= SUBMISSION_REJECT_THRESHOLD or ai_suspicion >= 0.78:
        recommendation = "rejected_or_hold"
        status = "manual_review"
        verification_reason = "High suspicion or very low authenticity confidence. Hold for manual review before any downstream use."
    else:
        recommendation = "manual_review"
        status = "manual_review"
        verification_reason = "Confidence fell below the auto-clear threshold or suspicious indicators were detected."

    if not suspicious_findings:
        suspicious_findings.append("No major authenticity red flags were detected, but this remains a screening score rather than proof.")

    report = {
        "authenticity_confidence": round(authenticity, 4),
        "ai_suspicion_score": round(ai_suspicion, 4),
        "metadata_present": metadata_present,
        "gps_present": gps_present,
        "capture_datetime": capture_datetime,
        "date_time_check_result": date_time_check,
        "device_info": device_info,
        "metadata_summary": metadata_summary,
        "suspicious_findings": suspicious_findings,
        "recommendation": recommendation,
        "status": status,
        "verification_reason": verification_reason,
        "raw_report": {
            "filename": filename,
            "content_type": content_type,
            "clear_threshold": SUBMISSION_CLEAR_THRESHOLD,
            "reject_threshold": SUBMISSION_REJECT_THRESHOLD,
            "metadata_summary": metadata_summary,
            "suspicious_findings": suspicious_findings,
        },
    }
    log.info(
        "Submission verification complete filename=%s authenticity=%.3f ai=%.3f recommendation=%s",
        filename,
        report["authenticity_confidence"],
        report["ai_suspicion_score"],
        recommendation,
    )
    return report


def serialize_report_fields(report: dict) -> dict:
    return {
        "authenticity_confidence": report["authenticity_confidence"],
        "ai_suspicion_score": report["ai_suspicion_score"],
        "metadata_present": bool(report["metadata_present"]),
        "gps_present": bool(report["gps_present"]),
        "capture_datetime": report.get("capture_datetime"),
        "date_time_check_result": report.get("date_time_check_result"),
        "device_info": report.get("device_info"),
        "metadata_summary_json": _safe_json(report.get("metadata_summary") or {}),
        "suspicious_findings_json": _safe_json(report.get("suspicious_findings") or []),
        "recommendation": report.get("recommendation") or "manual_review",
        "raw_report_json": _safe_json(report.get("raw_report") or report),
    }
