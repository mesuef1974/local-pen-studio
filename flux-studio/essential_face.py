"""Experimental subset of MediaPipe's 478 landmarks; not an identity score."""
import numpy as np

VERSION = 'essential-face/1.0'
GROUPS = {
    'eyes': [33, 159, 133, 145, 263, 386, 362, 374],
    'brows': [70, 105, 107, 336, 334, 300],
    'nose': [168, 4, 1, 98, 327],
    'mouth': [61, 37, 0, 267, 291, 314, 17, 84],
    'jaw': [234, 172, 136, 152, 365, 397, 454],
}
INDICES = sorted({i for group in GROUPS.values() for i in group})
CHAINS = [[33,159,133,145,33], [263,386,362,374,263],
          [70,105,107], [336,334,300], [168,4,1], [98,1,327],
          [61,37,0,267,291,314,17,84,61], GROUPS['jaw']]
EDGES = [(a,b) for chain in CHAINS for a,b in zip(chain,chain[1:])]


def compare(a, b):
    """Normalize with selected points only; no rotation or independent x/y scaling."""
    selected = []
    for face in (a, b):
        points = np.asarray(face, dtype=float)
        if points.shape != (478, 2) or not np.isfinite(points).all():
            raise ValueError('Expected 478 finite 2D landmarks.')
        subset = points[INDICES]
        span = np.ptp(subset, axis=0).max()
        if span <= 1e-8:
            raise ValueError('Degenerate selected landmarks.')
        selected.append((subset-subset.min(axis=0))/span)
    distances = np.linalg.norm(selected[0]-selected[1], axis=1)
    lookup = {idx: offset for offset, idx in enumerate(INDICES)}
    groups = {name: float(np.sqrt(np.mean(distances[[lookup[i] for i in ids]]**2)))
              for name, ids in GROUPS.items()}
    return {'state': 'raw_only', 'profile': VERSION, 'points': len(INDICES),
            'rms': float(np.sqrt(np.mean(distances**2))),
            'median': float(np.median(distances)), 'maximum': float(distances.max()),
            'groupRMS': groups, 'equalGroupMeanRMS': float(np.mean(list(groups.values()))),
            'score': None, 'automaticApproval': False}
