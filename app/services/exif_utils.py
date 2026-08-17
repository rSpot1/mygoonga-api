"""
Extraction de métadonnées EXIF pour les images, et heuristiques d'assistance à la modération
décrites au §7.2 du cahier des charges. Ne prend jamais de décision automatique : ne fait
que produire des signaux ("flags") que le modérateur examine et tranche lui-même.
"""
from __future__ import annotations

import io
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from PIL import ExifTags, Image


def _convert_gps(value, ref) -> Optional[float]:
    try:
        degrees, minutes, seconds = value
        result = float(degrees) + float(minutes) / 60 + float(seconds) / 3600
        if ref in ("S", "W"):
            result = -result
        return result
    except Exception:
        return None


def extract_exif(image_bytes: bytes) -> Dict[str, Any]:
    """Renvoie un dict de métadonnées lisibles : dateTimeOriginal, gps, camera, software..."""
    result: Dict[str, Any] = {
        "hasExif": False,
        "dateTimeOriginal": None,
        "cameraModel": None,
        "software": None,
        "gps": None,
        "looksLikeScreenshot": False,
    }
    try:
        img = Image.open(io.BytesIO(image_bytes))
        raw_exif = img.getexif()
    except Exception:
        return result

    if not raw_exif:
        # Beaucoup de captures d'écran et d'images réenregistrées perdent tout EXIF.
        result["looksLikeScreenshot"] = True
        return result

    tags = {ExifTags.TAGS.get(k, k): v for k, v in raw_exif.items()}
    result["hasExif"] = True
    result["cameraModel"] = tags.get("Model")
    result["software"] = tags.get("Software")

    dt = tags.get("DateTimeOriginal") or tags.get("DateTime")
    if dt:
        result["dateTimeOriginal"] = str(dt)

    gps_info = tags.get("GPSInfo")
    if gps_info:
        try:
            gps_tags = {ExifTags.GPSTAGS.get(k, k): v for k, v in gps_info.items()}
            lat = _convert_gps(gps_tags.get("GPSLatitude"), gps_tags.get("GPSLatitudeRef"))
            lon = _convert_gps(gps_tags.get("GPSLongitude"), gps_tags.get("GPSLongitudeRef"))
            if lat is not None and lon is not None:
                result["gps"] = {"lat": lat, "lng": lon}
        except Exception:
            pass

    # Une image sans appareil photo ni logiciel connu, sans GPS, ressemble souvent à une
    # capture d'écran ou à un export web (compression/recompression).
    if not result["cameraModel"] and not result["gps"]:
        result["looksLikeScreenshot"] = True

    return result


def moderation_metadata_flags(
    exif: Dict[str, Any],
    declared_city_coords: Optional[Tuple[float, float]] = None,
    max_distance_km: float = 80.0,
) -> List[str]:
    """Applique la logique métier du §7.2 : signale sans jamais décider seul."""
    flags: List[str] = []

    if not exif.get("hasExif"):
        flags.append("missingExif")

    if exif.get("looksLikeScreenshot"):
        flags.append("possibleScreenshot")

    dt = exif.get("dateTimeOriginal")
    if dt:
        try:
            parsed = datetime.strptime(dt, "%Y:%m:%d %H:%M:%S")
            age_days = (datetime.utcnow() - parsed).days
            if age_days > 365:
                flags.append("suspiciousDate")
        except Exception:
            flags.append("unparsableDate")

    gps = exif.get("gps")
    if gps and declared_city_coords:
        from app.services.scoring import haversine_km

        distance = haversine_km(gps["lat"], gps["lng"], declared_city_coords[0], declared_city_coords[1])
        if distance > max_distance_km:
            flags.append("locationMismatch")

    return flags
