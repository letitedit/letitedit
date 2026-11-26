"""Numeric helpers shared by the reference analysis modules: summaries and box overlap."""
import math

import numpy as np


def _r(x, nd=3):
    return None if x is None else round(float(x), nd)


def _stats(vals, nd=3):
    vals = [float(v) for v in vals if v is not None and not (isinstance(v, float) and math.isnan(v))]
    if not vals:
        return None
    return {'n': len(vals), 'median': round(float(np.median(vals)), nd), 'mean': round(float(np.mean(vals)), nd),
            'p25': round(float(np.percentile(vals, 25)), nd), 'p75': round(float(np.percentile(vals, 75)), nd),
            'min': round(min(vals), nd), 'max': round(max(vals), nd)}


def _iou(a, b):
    """Intersection over union of two boxes [x0, y0, x1, y1]; 0.0 when their union has no area."""
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0
