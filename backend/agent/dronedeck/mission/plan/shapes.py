"""The 2-D geometry every mission check is built on.

Metres, in the Lighthouse room frame (x and y absolute). Plain functions over
tuples: the shapes are small — a fence has tens of vertices, a room a handful
of obstacles — so clarity beats a geometry library the desktop installer would
have to carry.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

Point = tuple[float, float]

#: Below this, two coordinates are the same point: far under anything the
#: estimator can resolve, far over float rounding on room-sized numbers.
EPS = 1e-9


def cross(o: Point, a: Point, b: Point) -> float:
    """z of (a - o) × (b - o): > 0 when o→a→b turns left."""
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _on_segment(p: Point, a: Point, b: Point) -> bool:
    return (min(a[0], b[0]) - EPS <= p[0] <= max(a[0], b[0]) + EPS
            and min(a[1], b[1]) - EPS <= p[1] <= max(a[1], b[1]) + EPS)


def segments_intersect(a: Point, b: Point, c: Point, d: Point) -> bool:
    """Whether segment ab meets segment cd, touching included."""
    d1, d2 = cross(c, d, a), cross(c, d, b)
    d3, d4 = cross(a, b, c), cross(a, b, d)
    if ((d1 > EPS and d2 < -EPS) or (d1 < -EPS and d2 > EPS)) and \
       ((d3 > EPS and d4 < -EPS) or (d3 < -EPS and d4 > EPS)):
        return True
    return ((abs(d1) <= EPS and _on_segment(a, c, d))
            or (abs(d2) <= EPS and _on_segment(b, c, d))
            or (abs(d3) <= EPS and _on_segment(c, a, b))
            or (abs(d4) <= EPS and _on_segment(d, a, b)))


def segments_cross_properly(a: Point, b: Point, c: Point, d: Point) -> bool:
    """Whether ab and cd cross at a single interior point of both.

    Touching at an end, or lying along each other, is not a proper crossing —
    which is what a fence's adjacent edges do at their shared corner.
    """
    d1, d2 = cross(c, d, a), cross(c, d, b)
    d3, d4 = cross(a, b, c), cross(a, b, d)
    return (((d1 > EPS and d2 < -EPS) or (d1 < -EPS and d2 > EPS))
            and ((d3 > EPS and d4 < -EPS) or (d3 < -EPS and d4 > EPS)))


def point_segment_distance(p: Point, a: Point, b: Point) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length_sq = dx * dx + dy * dy
    if length_sq <= EPS:
        return math.hypot(p[0] - a[0], p[1] - a[1])
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length_sq))
    return math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy))


def segment_segment_distance(a: Point, b: Point, c: Point, d: Point) -> float:
    if segments_intersect(a, b, c, d):
        return 0.0
    return min(point_segment_distance(a, c, d), point_segment_distance(b, c, d),
               point_segment_distance(c, a, b), point_segment_distance(d, a, b))


def edges(vertices: Sequence[Point]) -> list[tuple[Point, Point]]:
    """The closed ring's edges, last vertex back to the first."""
    n = len(vertices)
    return [(vertices[i], vertices[(i + 1) % n]) for i in range(n)]


def signed_area(vertices: Sequence[Point]) -> float:
    """Shoelace. Positive counter-clockwise."""
    return 0.5 * sum(a[0] * b[1] - b[0] * a[1] for a, b in edges(vertices))


def point_in_polygon(p: Point, vertices: Sequence[Point]) -> bool:
    """Inside or on the boundary. Ray casting, with the boundary tested first so
    a point exactly on an edge is never decided by rounding."""
    for a, b in edges(vertices):
        if point_segment_distance(p, a, b) <= EPS:
            return True
    inside = False
    x, y = p
    for (x1, y1), (x2, y2) in edges(vertices):
        if (y1 > y) != (y2 > y):
            x_cross = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < x_cross:
                inside = not inside
    return inside


def distance_to_boundary(p: Point, vertices: Sequence[Point]) -> float:
    return min(point_segment_distance(p, a, b) for a, b in edges(vertices))


def segment_boundary_distance(a: Point, b: Point, vertices: Sequence[Point]) -> float:
    return min(segment_segment_distance(a, b, c, d) for c, d in edges(vertices))


def segment_in_polygon(a: Point, b: Point, vertices: Sequence[Point]) -> bool:
    """Whether the whole segment ab stays inside (or on) the polygon.

    Both ends inside is NOT enough for a room that is not convex: a leg across
    the inside corner of an L-shaped room leaves it with both ends indoors. So:
    no proper crossing with any edge, and the midpoints of every piece between
    the places the leg touches the boundary are inside too.
    """
    if not (point_in_polygon(a, vertices) and point_in_polygon(b, vertices)):
        return False
    for c, d in edges(vertices):
        if segments_cross_properly(a, b, c, d):
            return False
    # Touch points (vertices lying on the leg) split it; each piece's midpoint
    # must be inside, or the leg runs outside along a reflex corner.
    ts = [0.0, 1.0]
    dx, dy = b[0] - a[0], b[1] - a[1]
    length_sq = dx * dx + dy * dy
    if length_sq > EPS:
        for v in vertices:
            if point_segment_distance(v, a, b) <= EPS:
                ts.append(((v[0] - a[0]) * dx + (v[1] - a[1]) * dy) / length_sq)
    ts.sort()
    for t0, t1 in zip(ts, ts[1:], strict=False):
        if t1 - t0 <= EPS:
            continue
        tm = (t0 + t1) / 2
        if not point_in_polygon((a[0] + tm * dx, a[1] + tm * dy), vertices):
            return False
    return True


def self_intersects(vertices: Sequence[Point]) -> bool:
    """Whether any two non-adjacent edges of the ring meet."""
    ring = edges(vertices)
    n = len(ring)
    for i in range(n):
        for j in range(i + 1, n):
            if j == i + 1 or (i == 0 and j == n - 1):
                continue                      # adjacent: they share a corner
            if segments_intersect(*ring[i], *ring[j]):
                return True
    return False


def polygon_in_polygon(inner: Sequence[Point], outer: Sequence[Point]) -> bool:
    """Every edge of `inner` stays inside `outer`."""
    return all(segment_in_polygon(a, b, outer) for a, b in edges(inner))


def bounds(vertices: Sequence[Point]) -> tuple[float, float, float, float]:
    xs = [v[0] for v in vertices]
    ys = [v[1] for v in vertices]
    return min(xs), min(ys), max(xs), max(ys)


def is_finite(*values: float) -> bool:
    return all(math.isfinite(v) for v in values)
