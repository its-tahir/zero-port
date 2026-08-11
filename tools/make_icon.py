"""Generate assets/icon.ico with no third-party imaging library.

The mark is the ZeroPort "Z": a lime glyph on a near-black rounded plate. It is
rendered with 4x supersampling at every Windows icon size, encoded as PNG with
zlib, and packed into a standard .ico container.

    python tools/make_icon.py
"""

from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path
from typing import List, Sequence, Tuple

SIZES = (16, 24, 32, 48, 64, 128, 256)
SUPERSAMPLE = 4

PLATE = (18, 18, 21, 255)  # #121215 — reads as near-black on any background
BORDER = (250, 250, 250, 30)
LIME = (198, 242, 78, 255)

CORNER_RADIUS = 0.22
PLATE_INSET = 0.02

Point = Tuple[float, float]


# --------------------------------------------------------------------- shapes


def z_polygons() -> List[Sequence[Point]]:
    """The Z, in unit coordinates, as three overlapping convex polygons."""
    x0, x1 = 0.265, 0.735
    y0, y1 = 0.275, 0.725
    bar = 0.108           # bar thickness
    slant = bar * 1.62    # horizontal width of the diagonal

    top = [(x0, y0), (x1, y0), (x1, y0 + bar), (x0, y0 + bar)]
    bottom = [(x0, y1 - bar), (x1, y1 - bar), (x1, y1), (x0, y1)]
    diagonal = [
        (x1, y0),
        (x1 - slant, y0),
        (x0, y1),
        (x0 + slant, y1),
    ]
    return [top, bottom, diagonal]


def point_in_polygon(x: float, y: float, polygon: Sequence[Point]) -> bool:
    inside = False
    count = len(polygon)
    j = count - 1
    for i in range(count):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if (yi > y) != (yj > y):
            if x < (xj - xi) * (y - yi) / (yj - yi) + xi:
                inside = not inside
        j = i
    return inside


def rounded_rect_distance(x: float, y: float, inset: float, radius: float) -> float:
    """Signed distance to the plate edge in unit space; negative is inside."""
    left, top = inset, inset
    right, bottom = 1.0 - inset, 1.0 - inset

    cx = min(max(x, left + radius), right - radius)
    cy = min(max(y, top + radius), bottom - radius)

    dx, dy = x - cx, y - cy
    if dx == 0.0 and dy == 0.0:
        # Inside the straight-edged core: distance to the nearest side.
        return -min(x - left, right - x, y - top, bottom - y)
    return (dx * dx + dy * dy) ** 0.5 - radius


# -------------------------------------------------------------------- raster


def render(size: int) -> bytes:
    """Return ``size`` x ``size`` RGBA bytes, top-to-bottom."""
    ss = SUPERSAMPLE
    big = size * ss
    polygons = z_polygons()
    border_width = 1.15 / size  # ~1 device pixel, expressed in unit space

    rows: List[bytearray] = []
    for py in range(size):
        row = bytearray()
        for px in range(size):
            r = g = b = a = 0.0
            for sy in range(ss):
                uy = (py * ss + sy + 0.5) / big
                for sx in range(ss):
                    ux = (px * ss + sx + 0.5) / big
                    sample = _sample(ux, uy, polygons, border_width)
                    if sample is None:
                        continue
                    sr, sg, sb, sa = sample
                    alpha = sa / 255.0
                    r += sr * alpha
                    g += sg * alpha
                    b += sb * alpha
                    a += alpha
            total = ss * ss
            if a <= 0.0:
                row += b"\x00\x00\x00\x00"
                continue
            row += bytes(
                (
                    int(round(r / a)),
                    int(round(g / a)),
                    int(round(b / a)),
                    int(round(a / total * 255)),
                )
            )
        rows.append(row)

    return b"".join(bytes([0]) + bytes(row) for row in rows)


def _sample(x: float, y: float, polygons, border_width: float):
    distance = rounded_rect_distance(x, y, PLATE_INSET, CORNER_RADIUS)
    if distance > 0:
        return None
    for polygon in polygons:
        if point_in_polygon(x, y, polygon):
            return LIME
    if distance > -border_width:
        return _over(BORDER, PLATE)
    return PLATE


def _over(top, bottom):
    alpha = top[3] / 255.0
    return (
        int(top[0] * alpha + bottom[0] * (1 - alpha)),
        int(top[1] * alpha + bottom[1] * (1 - alpha)),
        int(top[2] * alpha + bottom[2] * (1 - alpha)),
        255,
    )


# ----------------------------------------------------------------- encoding


def png(size: int, raw_scanlines: bytes) -> bytes:
    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw_scanlines, 9))
        + chunk(b"IEND", b"")
    )


def ico(images: List[Tuple[int, bytes]]) -> bytes:
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = len(header) + 16 * len(images)

    entries = b""
    payload = b""
    for size, data in images:
        entries += struct.pack(
            "<BBBBHHII",
            size if size < 256 else 0,
            size if size < 256 else 0,
            0,
            0,
            1,
            32,
            len(data),
            offset,
        )
        payload += data
        offset += len(data)

    return header + entries + payload


def main() -> int:
    target = Path(__file__).resolve().parent.parent / "assets" / "icon.ico"
    target.parent.mkdir(parents=True, exist_ok=True)

    images: List[Tuple[int, bytes]] = []
    for size in SIZES:
        print(f"rendering {size}x{size}...", flush=True)
        images.append((size, png(size, render(size))))

    target.write_bytes(ico(images))
    print(f"wrote {target} ({target.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
