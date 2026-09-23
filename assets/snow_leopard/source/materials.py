"""Exportable snow-leopard/chapan materials; no external Python packages required.

Inside Blender 5.2:
    materials = build_materials(Path("assets/snow_leopard/textures"))

The fur uses ordinary UVs. For trim, U runs across the ribbon and V along it.
All texture artwork is generated here; no reference-image pixels are sampled.
To generate/inspect the PNGs without Blender:
    python materials.py --textures-only ../textures
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path
import random
import struct
import zlib


TAU = math.tau
TEXTURE_VERSION = "cq-snow-leopard-materials-v1"
TEXTURE_SIZES = {"fur": 2048, "muzzle": 1024, "coat": 1024, "trim": 1024,
                 "sweater": 1024, "trousers": 1024}


def _byte(value):
    return max(0, min(255, round(value)))


def _png(path, width, height, pixels):
    """Write standard lossless RGBA PNG, including an sRGB colour-space tag."""
    def chunk(kind, payload):
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)

    rows = b"".join(b"\x00" + pixels[row * width * 4:(row + 1) * width * 4] for row in range(height))
    data = b"\x89PNG\r\n\x1a\n"
    data += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
    data += chunk(b"sRGB", b"\x00")
    data += chunk(b"tEXt", b"Software\x00" + TEXTURE_VERSION.encode("ascii"))
    data += chunk(b"IDAT", zlib.compress(rows, 6))
    data += chunk(b"IEND", b"")
    Path(path).write_bytes(data)


def _cloth(size, colour, seed, *, ribs=False):
    rng = random.Random(seed)
    pixels = bytearray(size * size * 4)
    horizontal = [math.sin(x * TAU / 3.0) for x in range(size)]
    vertical = [math.sin(y * TAU / 4.0) for y in range(size)]
    for y in range(size):
        for x in range(size):
            i = (y * size + x) * 4
            weave = horizontal[x] * 0.75 + vertical[y] * 0.65
            variation = (rng.random() - 0.5) * 3.0 + weave
            if ribs:
                # Raised knitted columns and tiny diagonal stitch catches.
                rib = (math.cos(x * TAU / 23.0) + 1.0) * 0.5
                variation += 7.5 * rib - 3.0 + 1.3 * math.sin(y * TAU / 8.0 + x * 0.6)
            for channel in range(3):
                pixels[i + channel] = _byte(colour[channel] + variation)
            pixels[i + 3] = 255
    return pixels


def _fur(size, *, spotted=True):
    rng = random.Random(170926)
    pixels = bytearray(size * size * 4)
    for y in range(size):
        for x in range(size):
            i = (y * size + x) * 4
            fibre = math.sin(y * 1.25 + 1.6 * math.sin(x * 0.16)) * 1.2
            cloud = 2.7 * math.sin(x * TAU / size * 5) * math.cos(y * TAU / size * 3)
            variation = (rng.random() - 0.5) * 6.0 + fibre + cloud
            base = (226, 225, 218) if spotted else (241, 237, 223)
            pixels[i:i + 4] = bytes((_byte(base[0] + variation), _byte(base[1] + variation), _byte(base[2] + variation), 255))
    if not spotted:
        return pixels

    # Jittered spacing avoids both rows of dots and the random clumps of a cow hide.
    # Broken, asymmetrical, soft-edged rings surround faint warm-grey centres.
    columns, rows = 17, 13
    for row in range(rows):
        for column in range(columns):
            cx = ((column + 0.5 + rng.uniform(-0.28, 0.28)) / columns * size) % size
            cy = ((row + 0.5 + rng.uniform(-0.27, 0.27)) / rows * size) % size
            radius = size * rng.uniform(0.015, 0.025)
            rx, ry = radius * rng.uniform(0.75, 1.18), radius * rng.uniform(0.78, 1.3)
            phase, rotate = rng.uniform(0, TAU), rng.uniform(0, TAU)
            solid = rng.random() < 0.12
            if solid:
                rx *= 0.6
                ry *= 0.6
            reach = math.ceil(max(rx, ry) * 1.55)
            cosine, sine = math.cos(rotate), math.sin(rotate)
            pigment = rng.uniform(-4, 8)
            for py in range(math.floor(cy) - reach, math.floor(cy) + reach + 1):
                for px in range(math.floor(cx) - reach, math.floor(cx) + reach + 1):
                    dx, dy = px - cx, py - cy
                    xx, yy = (dx * cosine - dy * sine) / rx, (dx * sine + dy * cosine) / ry
                    angle = math.atan2(yy, xx)
                    distance = math.hypot(xx, yy)
                    irregular = 1 + 0.12 * math.sin(3 * angle + phase) + 0.07 * math.sin(5 * angle - phase)
                    distance /= irregular
                    if distance > 1.36:
                        continue
                    fibre = 0.045 * math.sin(px * 0.57 + py * 2.15)
                    if solid:
                        ring = max(0.0, min(1.0, (1.09 - distance + fibre) / 0.24))
                    else:
                        ring = max(0.0, min(1.0, (0.31 - abs(distance - 0.89) + fibre) / 0.13))
                        breaks = 0.58 + 0.42 * math.sin(3 * angle + phase) * math.sin(2 * angle - phase * 0.7)
                        ring *= max(0.12, min(1.0, breaks * 1.8))
                    centre = max(0.0, (0.65 - distance) / 0.65) * 0.17 if not solid else 0
                    alpha = min(0.92, ring * 0.83 + centre)
                    i = ((py % size) * size + (px % size)) * 4
                    fur_noise = 2.8 * math.sin(px * 0.9 + py * 2.7)
                    dark = (53 + pigment + fur_noise, 52 + pigment + fur_noise, 48 + pigment + fur_noise)
                    for channel in range(3):
                        pixels[i + channel] = _byte(pixels[i + channel] * (1 - alpha) + dark[channel] * alpha)
    return pixels


def _disc(mask, size, cx, cy, radius):
    lo_x, hi_x = max(0, math.floor(cx - radius - 1)), min(size - 1, math.ceil(cx + radius + 1))
    lo_y, hi_y = max(0, math.floor(cy - radius - 1)), min(size - 1, math.ceil(cy + radius + 1))
    for y in range(lo_y, hi_y + 1):
        for x in range(lo_x, hi_x + 1):
            alpha = _byte((radius + 0.65 - math.hypot(x - cx, y - cy)) * 255)
            index = y * size + x
            if alpha > mask[index]:
                mask[index] = alpha


def _stroke(mask, size, points, width):
    previous = points[0]
    for point in points[1:]:
        count = max(1, math.ceil(math.dist(previous, point) / 2.1))
        for i in range(count + 1):
            t = i / count
            _disc(mask, size, previous[0] + (point[0] - previous[0]) * t, previous[1] + (point[1] - previous[1]) * t, width / 2)
        previous = point


def _bezier(a, b, c, d, samples=32):
    points = []
    for i in range(samples + 1):
        t, q = i / samples, 1 - i / samples
        points.append((q ** 3 * a[0] + 3 * q * q * t * b[0] + 3 * q * t * t * c[0] + t ** 3 * d[0],
                       q ** 3 * a[1] + 3 * q * q * t * b[1] + 3 * q * t * t * c[1] + t ** 3 * d[1]))
    return points


def _trim(size):
    pixels = _cloth(size, (12, 71, 57), 4703)
    mask = bytearray(size * size)
    # An original interpretation of mirrored qoshqar-muiz/ram-horn scrollwork.
    # The flattened motif becomes balanced when UV-mapped to a tall narrow lapel.
    repeats = 7
    height = size / repeats
    for tile in range(repeats):
        top = tile * height
        for sign in (-1, 1):
            centre_x, centre_y = size * (0.5 + sign * 0.21), top + height * 0.41
            spiral = []
            for step in range(100):
                t = step / 99
                angle = math.pi * 0.5 + t * TAU * 1.12
                radius = 1 - 0.82 * t
                spiral.append((centre_x + sign * math.cos(angle) * size * 0.18 * radius,
                               centre_y + math.sin(angle) * height * 0.32 * radius))
            stem = _bezier((size * 0.5, top + height * 0.91),
                           (size * (0.5 + sign * 0.15), top + height * 0.82),
                           (size * (0.5 + sign * 0.24), top + height * 0.72), spiral[0])
            _stroke(mask, size, stem + spiral, size * 0.018)
        diamond_y = top + height * 0.13
        _stroke(mask, size, [(size * 0.5, diamond_y - height * 0.1),
                            (size * 0.565, diamond_y), (size * 0.5, diamond_y + height * 0.1),
                            (size * 0.435, diamond_y), (size * 0.5, diamond_y - height * 0.1)], size * 0.013)
    for x, width in ((0.055, 0.01), (0.086, 0.004), (0.914, 0.004), (0.945, 0.01)):
        _stroke(mask, size, [(size * x, 0), (size * x, size - 1)], size * width)
    rng = random.Random(2319)
    for y in range(size):
        for x in range(size):
            idx = y * size + x
            alpha = mask[idx] / 255
            if not alpha:
                continue
            # Embroidery catches light on one edge; no non-exportable shader nodes.
            neighbour = mask[max(0, y - 2) * size + max(0, x - 2)] / 255
            relief = (alpha - neighbour) * 27 + math.sin(x * 1.8 + y * 0.6) * 2.5 + (rng.random() - 0.5) * 3
            gold = (192 + relief, 164 + relief, 91 + relief)
            for channel in range(3):
                index = idx * 4 + channel
                pixels[index] = _byte(pixels[index] * (1 - alpha) + gold[channel] * alpha)
    return pixels


def generate_textures(output_dir):
    """Generate deterministic PNGs and a contact sheet; return texture paths."""
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    specifications = {
        "fur": (2048, lambda: _fur(2048)),
        "muzzle": (1024, lambda: _fur(1024, spotted=False)),
        "coat": (1024, lambda: _cloth(1024, (10, 65, 51), 641)),
        "trim": (1024, lambda: _trim(1024)),
        "sweater": (1024, lambda: _cloth(1024, (225, 218, 197), 148, ribs=True)),
        "trousers": (1024, lambda: _cloth(1024, (44, 50, 40), 770)),
    }
    paths, previews = {}, {}
    for name, (size, factory) in specifications.items():
        pixels = factory()
        path = output / f"snow_leopard_{name}_basecolor.png"
        _png(path, size, size, pixels)
        paths[name] = path
        # Retain small nearest-neighbour images for an unambiguous texture contact sheet.
        small = bytearray(384 * 384 * 4)
        for y in range(384):
            source_y = y * size // 384
            for x in range(384):
                source = (source_y * size + x * size // 384) * 4
                dest = (y * 384 + x) * 4
                small[dest:dest + 4] = pixels[source:source + 4]
        previews[name] = small
    sheet = bytearray(1152 * 768 * 4)
    # Top row: fur / coat / ornament. Bottom row: muzzle / sweater / trousers.
    for index, name in enumerate(("fur", "coat", "trim", "muzzle", "sweater", "trousers")):
        ox, oy = (index % 3) * 384, (index // 3) * 384
        for y in range(384):
            destination = ((oy + y) * 1152 + ox) * 4
            sheet[destination:destination + 384 * 4] = previews[name][y * 384 * 4:(y + 1) * 384 * 4]
    _png(output / "materials_preview.png", 1152, 768, sheet)
    return paths


def _linear(value):
    value /= 255
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def _cached_textures(output_dir):
    """Reuse this version's complete PNGs when rebuilding geometry repeatedly."""
    output = Path(output_dir).resolve()
    paths = {name: output / f"snow_leopard_{name}_basecolor.png" for name in TEXTURE_SIZES}
    try:
        for name, path in paths.items():
            with path.open("rb") as stream:
                header = stream.read(128)
                stream.seek(-12, 2)
                ending = stream.read(12)
            if (header[:8] != b"\x89PNG\r\n\x1a\n"
                    or struct.unpack(">II", header[16:24]) != (TEXTURE_SIZES[name],) * 2
                    or TEXTURE_VERSION.encode("ascii") not in header
                    or ending[4:8] != b"IEND"):
                return generate_textures(output)
    except (OSError, struct.error):
        return generate_textures(output)
    return paths


def build_materials(output_dir):
    """Return 14 bpy materials with image-to-Principled, glTF-compatible nodes."""
    import bpy

    paths = _cached_textures(output_dir)
    definitions = {
        "fur": ((226, 225, 218), 0.87, 0.0),
        "muzzle": ((241, 237, 223), 0.9, 0.0),
        "nose": ((104, 75, 70), 0.58, 0.0),
        "inner_ear": ((178, 157, 151), 0.88, 0.0),
        "coat": ((10, 65, 51), 0.78, 0.0),
        "trim": ((192, 164, 91), 0.65, 0.16),
        "gold": ((202, 171, 91), 0.35, 0.65),
        "sweater": ((225, 218, 197), 0.88, 0.0),
        "trousers": ((44, 50, 40), 0.86, 0.0),
        "eye_white": ((239, 238, 224), 0.24, 0.0),
        "iris": ((85, 124, 77), 0.28, 0.0),
        "pupil": ((7, 11, 9), 0.2, 0.0),
        "mouth": ((49, 39, 36), 0.76, 0.0),
        "whisker": ((229, 229, 217), 0.8, 0.0),
    }
    materials = {}
    for name, (colour, roughness, metallic) in definitions.items():
        material_name = "CQ_SnowLeopard_" + name
        material = bpy.data.materials.get(material_name) or bpy.data.materials.new(material_name)
        material.use_nodes = True
        material.diffuse_color = (*(_linear(value) for value in colour), 1)
        nodes = material.node_tree.nodes
        nodes.clear()
        output = nodes.new("ShaderNodeOutputMaterial")
        output.location = (300, 0)
        shader = nodes.new("ShaderNodeBsdfPrincipled")
        shader.location = (0, 0)
        shader.inputs["Base Color"].default_value = material.diffuse_color
        shader.inputs["Roughness"].default_value = roughness
        shader.inputs["Metallic"].default_value = metallic
        if "Specular IOR Level" in shader.inputs:
            shader.inputs["Specular IOR Level"].default_value = 0.3 if name not in {"eye_white", "iris", "pupil"} else 0.5
        material.node_tree.links.new(shader.outputs["BSDF"], output.inputs["Surface"])
        if name in paths:
            texture = nodes.new("ShaderNodeTexImage")
            texture.location = (-330, 30)
            texture.label = "Original procedural artwork · exportable PNG"
            texture.image = bpy.data.images.load(str(paths[name]), check_existing=True)
            texture.image.reload()
            texture.image.colorspace_settings.name = "sRGB"
            texture.image.pack()
            texture.extension = "REPEAT"
            material.node_tree.links.new(texture.outputs["Color"], shader.inputs["Base Color"])
        material["artwork_source"] = TEXTURE_VERSION
        materials[name] = material
    return materials


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--textures-only", type=Path, required=True)
    options = parser.parse_args()
    for label, texture_path in generate_textures(options.textures_only).items():
        print(f"{label}: {texture_path}")
