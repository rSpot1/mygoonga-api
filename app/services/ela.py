"""
Error Level Analysis (ELA) : technique classique de traitement d'image (pas d'IA) qui
réenregistre l'image à une qualité JPEG connue et compare la différence pixel à pixel
avec l'original. Des zones nettement plus "chaudes" que le reste de l'image peuvent
indiquer une zone retouchée ou recompressée séparément — un indice, jamais une preuve.
"""
from __future__ import annotations

import io
from typing import Any, Dict

import numpy as np
from PIL import Image, ImageChops

from app.config import get_settings

settings = get_settings()


def compute_ela(image_bytes: bytes, quality: int | None = None) -> Dict[str, Any]:
    quality = quality or settings.ELA_QUALITY

    try:
        original = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception:
        return {"applicable": False, "reason": "Format d'image non pris en charge pour l'ELA."}

    buffer = io.BytesIO()
    original.save(buffer, "JPEG", quality=quality)
    buffer.seek(0)
    recompressed = Image.open(buffer)

    diff = ImageChops.difference(original, recompressed)
    diff_array = np.asarray(diff).astype(np.float32)

    mean_score = float(diff_array.mean())
    max_score = float(diff_array.max())

    # Repère les régions (grille 8x8) dont l'erreur moyenne dépasse largement la moyenne
    # globale de l'image : signal de zone potentiellement retouchée séparément.
    h, w, _ = diff_array.shape
    grid_x, grid_y = 8, 8
    suspicious_regions = []
    cell_h, cell_w = max(h // grid_y, 1), max(w // grid_x, 1)
    for gy in range(grid_y):
        for gx in range(grid_x):
            cell = diff_array[gy * cell_h: (gy + 1) * cell_h, gx * cell_w: (gx + 1) * cell_w]
            if cell.size == 0:
                continue
            cell_mean = float(cell.mean())
            if cell_mean > settings.ELA_ANOMALY_THRESHOLD and cell_mean > mean_score * 2:
                suspicious_regions.append(
                    {
                        "gridX": gx,
                        "gridY": gy,
                        "score": round(cell_mean, 2),
                    }
                )

    anomaly_detected = len(suspicious_regions) > 0

    return {
        "applicable": True,
        "meanScore": round(mean_score, 2),
        "maxScore": round(max_score, 2),
        "anomalyDetected": anomaly_detected,
        "suspiciousRegions": suspicious_regions[:10],
        "explanation": (
            "Des zones de compression sensiblement différentes du reste de l'image ont été "
            "détectées : ceci peut indiquer une retouche localisée, mais peut aussi provenir "
            "d'une simple recompression globale (partage sur un réseau social par exemple)."
            if anomaly_detected
            else "Aucune zone de compression anormale détectée. Ceci ne garantit pas "
            "l'authenticité du contenu."
        ),
    }
