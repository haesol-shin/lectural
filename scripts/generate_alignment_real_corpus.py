#!/usr/bin/env python3
"""Generate the committed, pixel-backed Issue #22 sequence calibration corpus.

Recipes, labels, content IDs, and seeds are selected before measurements.  The
generator is deliberately small and deterministic: it makes the corpus
auditable and lets ``manifest.json`` bind every decoded frame by SHA-256.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from scripts.calibrate_alignment import REQUIRED_TRANSFORM_CLASSES


DEFAULT_OUT = REPO_ROOT / "tests" / "fixtures" / "visual_alignment" / "real_sequence_v1"
GENERATOR_VERSION = "issue-22-real-sequence-v26"
SIZE = (640, 360)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canvas(seed: int, content_id: str) -> Image.Image:
    """Create a feature-rich authored slide without external assets."""
    image = Image.new("RGB", SIZE, "#f7f3e8")
    draw = ImageDraw.Draw(image)
    palette = ("#254d70", "#d35d4f", "#e6a23c", "#3b8c6e", "#7257a6")
    # Stable, seed-separated micro geometry gives ORB genuine image features.
    for index in range(90):
        value = (seed * 1103515245 + index * 12345) & 0x7FFFFFFF
        x = 12 + value % 610
        y = 48 + (value // 619) % 292
        radius = 2 + (value // 43) % 8
        color = palette[(value // 13) % len(palette)]
        draw.rectangle((x, y, x + radius, y + radius), outline=color, width=1)
        if index % 3 == 0:
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), outline=color, width=1)
    draw.rectangle((0, 0, SIZE[0], 36), fill="#254d70")
    draw.text((16, 11), f"Alignment corpus {content_id}", fill="white")
    draw.rectangle((35, 80, 605, 290), outline="#254d70", width=3)
    draw.line((60, 235, 570, 115), fill="#d35d4f", width=4)
    draw.line((60, 115, 570, 235), fill="#3b8c6e", width=3)
    draw.text((70, 305), f"semantic content {content_id}", fill="#254d70")
    return image


def _sparse_canvas(seed: int, content_id: str, density: int) -> Image.Image:
    """Create a sparse but ORB-rich canvas for direct-true fallback cases."""
    image = Image.new("RGB", SIZE, "#f7f3e8")
    draw = ImageDraw.Draw(image)
    palette = ("#254d70", "#d35d4f", "#3b8c6e")
    for index in range(density):
        value = (seed * 1103515245 + index * 12345) & 0x7FFFFFFF
        x = 70 + value % 500
        y = 60 + (value // 503) % 240
        width = 8 + (value // 43) % 23
        height = 5 + (value // 97) % 12
        color = palette[(value // 13) % len(palette)]
        if index % 3 == 0:
            draw.rectangle((x, y, x + width, y + height), outline=color, width=2)
        elif index % 3 == 1:
            draw.ellipse((x, y, x + height, y + height), fill=color)
        else:
            draw.line((x, y, x + width, y + height // 2), fill=color, width=2)
    draw.text((16, 16), content_id, fill="#254d70")
    return image


def _shift(image: Image.Image, dx: int, dy: int) -> Image.Image:
    return image.transform(SIZE, Image.AFFINE, (1, 0, -dx, 0, 1, -dy), resample=Image.Resampling.BILINEAR, fillcolor="#f7f3e8")


def _zoom(image: Image.Image, scale: float, dx: int = 0, dy: int = 0) -> Image.Image:
    width, height = SIZE
    crop_w, crop_h = int(width / scale), int(height / scale)
    left = max(0, min(width - crop_w, (width - crop_w) // 2 + dx))
    top = max(0, min(height - crop_h, (height - crop_h) // 2 + dy))
    return image.crop((left, top, left + crop_w, top + crop_h)).resize(SIZE, Image.Resampling.BILINEAR)


def _zoom_out(image: Image.Image, scale: float, dx: int = 0, dy: int = 0) -> Image.Image:
    width, height = SIZE
    reduced = image.resize((round(width * scale), round(height * scale)), Image.Resampling.BILINEAR)
    result = Image.new("RGB", SIZE, "#f7f3e8")
    result.paste(reduced, ((width - reduced.width) // 2 + dx, (height - reduced.height) // 2 + dy))
    return result


def _luminance_matched_colorize(image: Image.Image) -> Image.Image:
    """Change RGB histogram bins while preserving OpenCV grayscale luminance."""
    gray = image.convert("L")
    red = []
    green = []
    blue = []
    for value in range(256):
        delta = min(12, value // 8, 255 - value)
        red.append(value + delta)
        green.append(value + delta)
        blue.append(max(0, min(255, round(value - ((0.299 + 0.587) / 0.114) * delta))))
    return Image.merge("RGB", (gray.point(red), gray.point(green), gray.point(blue)))


def _semantic_change(
    image: Image.Image,
    label: str,
    *,
    large: bool = True,
    offset: tuple[int, int] = (0, 0),
) -> Image.Image:
    changed = image.copy()
    draw = ImageDraw.Draw(changed)
    base_box = (385, 175, 570, 265) if large else (520, 290, 555, 320)
    dx, dy = offset
    box = tuple(value + (dx if index % 2 == 0 else dy) for index, value in enumerate(base_box))
    draw.rectangle(box, fill="#d35d4f", outline="#4a2020", width=3)
    draw.text((box[0] + 8, box[1] + 18), label, fill="white")
    return changed


def _fallback_content_change(
    image: Image.Image,
    label: str,
    *,
    offset: tuple[int, int] = (0, 0),
) -> Image.Image:
    """Add a bounded semantic patch while preserving the direct similarity gate."""
    changed = image.copy()
    draw = ImageDraw.Draw(changed)
    dx, dy = offset
    box = (455 + dx, 243 + dy, 565 + dx, 291 + dy)
    draw.rectangle(box, fill="#d35d4f", outline="#4a2020", width=2)
    draw.text((box[0] + 6, box[1] + 10), label, fill="white")
    return changed


def _candidate(
    transform_class: str,
    base: Image.Image,
    seed: int,
    content_id: str,
    split: str,
    fallback_variant: bool,
) -> tuple[Image.Image, bool, bool, str | None, dict[str, Any]]:
    """Return pixels, authored truth, fallback contract, and exact recipe."""
    held_out = split == "held_out"
    edge_fit_variant = not held_out and not fallback_variant and seed % 10 == 3
    if transform_class == "static_duplicate":
        if not held_out and seed % 10 == 1:
            image = base.copy()
            draw = ImageDraw.Draw(image)
            draw.rectangle((0, 0, 51, 49), fill="black")
            return image, True, False, None, {"nuisance_overlay": [0, 0, 51, 49]}
        params = {"dx": 32 if held_out else 16, "dy": -16 if held_out else -8}
        return _shift(base, **params), True, False, None, params
    if transform_class == "static_shift":
        params = {"dx": 26 if held_out else 20, "dy": -13 if held_out else -10}
        return _shift(base, **params), True, False, None, params
    if transform_class == "pan_zoom":
        params = {
            "scale": 1.22 if edge_fit_variant else 1.15,
            "dx": 26 if edge_fit_variant else (14 if held_out else (12 if fallback_variant else 13)),
            "dy": -13 if edge_fit_variant else (-5 if held_out else (-7 if fallback_variant else -6)),
        }
        image = _zoom(base, **params)
        if edge_fit_variant:
            shear = 0.025
            params = {**params, "shear": shear, "photometric": "luminance_matched_colorize"}
            image = image.transform(
                SIZE,
                Image.Transform.AFFINE,
                (1, shear, -shear * SIZE[1] / 2, 0, 1, 0),
                resample=Image.Resampling.BILINEAR,
                fillcolor="#f7f3e8",
            )
            image = _luminance_matched_colorize(image)
        return image, True, fallback_variant, "zoom_in" if fallback_variant else None, params
    if transform_class == "pan_zoom_incremental":
        params = {
            "scale": 1.15,
            "dx": 20 if held_out else 12,
            "dy": -8 if held_out else -7,
        }
        patch_offset = (-16, -8) if held_out else (0, 0)
        image = _zoom(base, **params)
        params = {**params, "semantic_patch_offset": list(patch_offset)}
        return _fallback_content_change(image, "added", offset=patch_offset), False, fallback_variant, "zoom_in" if fallback_variant else None, params
    if transform_class == "pan_zoom_reverse":
        params = {
            "scale": 0.82 if edge_fit_variant else 0.87,
            "dx": 34 if edge_fit_variant else (32 if held_out else 18),
            "dy": -17 if edge_fit_variant else (-16 if held_out else -9),
        }
        image = _zoom_out(base, **params)
        if edge_fit_variant:
            params = {**params, "photometric": "luminance_matched_colorize"}
            image = _luminance_matched_colorize(image)
        return image, True, fallback_variant, "zoom_out" if fallback_variant else None, params
    if transform_class == "pan_zoom_shared_template":
        params = {
            "scale": 0.88 if held_out else 0.87,
            "dx": 24 if held_out else 18,
            "dy": -12 if held_out else -9,
        }
        patch_offset = (-16, -8) if held_out else (0, 0)
        image = _zoom_out(base, **params)
        params = {**params, "semantic_patch_offset": list(patch_offset)}
        return _fallback_content_change(image, "other", offset=patch_offset), False, fallback_variant, "zoom_out" if fallback_variant else None, params
    semantic_offset = (-24, -12) if held_out else (0, 0)
    if transform_class == "incremental_build":
        params = {"semantic_patch_offset": list(semantic_offset)}
        return _semantic_change(base, "added", offset=semantic_offset), False, False, None, params
    if transform_class == "same_palette_different_layout":
        transpose = Image.Transpose.FLIP_TOP_BOTTOM if held_out else Image.Transpose.FLIP_LEFT_RIGHT
        params = {"transpose": "vertical" if held_out else "horizontal"}
        return base.transpose(transpose), False, False, None, params
    if transform_class == "out_of_scale":
        params = {"scale": 1.38 if held_out else 1.42}
        return _semantic_change(_zoom(base, **params), "scale", offset=semantic_offset), False, False, None, params
    if transform_class == "one_way_coverage":
        params = {
            "scale": 1.22 if held_out else 1.20,
            "dx": 95 if held_out else 105,
            "dy": 40 if held_out else 45,
        }
        return _semantic_change(_zoom(base, **params), "edge", offset=semantic_offset), False, False, None, params
    if transform_class == "low_masked_ssim":
        params = {"dx": 58 if held_out else 65, "dy": 34 if held_out else 28}
        return _semantic_change(_shift(base, **params), "noise", offset=semantic_offset), False, False, None, params
    if transform_class == "collinear_inliers":
        line_y = 165 if held_out else 180
        image = Image.new("RGB", SIZE, "#f7f3e8")
        draw = ImageDraw.Draw(image)
        draw.line((20, line_y, 620, line_y), fill="#254d70", width=5)
        for x in range(30, 620, 35):
            draw.ellipse((x, line_y - 7, x + 14, line_y + 7), fill="#d35d4f")
        return image, False, False, None, {"line_y": line_y}
    if transform_class == "too_few_descriptors":
        background = "#ededed" if held_out else "#eeeeee"
        image = Image.new("RGB", SIZE, background)
        return image, False, False, None, {"background": background}
    if transform_class == "ransac_failure":
        params = {"dx": 110 if held_out else 120, "dy": 15 if held_out else 0}
        return _semantic_change(_shift(base, **params), "affine", offset=semantic_offset), False, False, None, params
    if transform_class == "outlier_heavy":
        seed_offset = 503 if held_out else 303
        params = {"seed_offset": seed_offset, "semantic_patch_offset": list(semantic_offset)}
        image = _canvas(seed + seed_offset, f"outliers-{content_id}")
        return _semantic_change(image, "outlier", offset=semantic_offset), False, False, None, params
    if transform_class == "high_residual":
        params = {
            "scale": 1.20 if held_out else 1.18,
            "dx": 38 if held_out else 45,
            "dy": -30 if held_out else -35,
        }
        return _semantic_change(_zoom(base, **params), "residual", offset=semantic_offset), False, False, None, params
    seed_offset = 901 if held_out else 701
    params = {"seed_offset": seed_offset, "semantic_patch_offset": list(semantic_offset)}
    image = _canvas(seed + seed_offset, f"transition-{content_id}")
    return _semantic_change(image, "transition", offset=semantic_offset), False, False, None, params


def _write(path: Path, image: Image.Image) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG", optimize=False, compress_level=9)


def _sequence(split: str, transform_class: str, seed: int, ordinal: int, root: Path) -> dict[str, Any]:
    content_id = f"{split}-content-{seed}"
    fallback_classes = {
        "pan_zoom",
        "pan_zoom_incremental",
        "pan_zoom_reverse",
        "pan_zoom_shared_template",
    }
    fallback_variant = transform_class in fallback_classes and (
        split == "held_out" or seed % 10 in {0, 2}
    )
    edge_fit_variant = (
        split == "development"
        and transform_class in {"pan_zoom", "pan_zoom_reverse"}
        and not fallback_variant
        and seed % 10 == 3
    )
    sparse_density = 12 if edge_fit_variant else (
        {
            "static_duplicate": 8,
            "static_shift": 45,
            "pan_zoom": 18 if split == "held_out" else 16,
            "pan_zoom_reverse": 22 if split == "held_out" else 20,
            "pan_zoom_incremental": 8,
            "pan_zoom_shared_template": 8,
        }.get(transform_class)
        if transform_class not in fallback_classes or fallback_variant
        else None
    )
    base = _sparse_canvas(seed, content_id, sparse_density) if sparse_density else _canvas(seed, content_id)
    candidate, same, fallback, direction, transform_parameters = _candidate(
        transform_class, base, seed, content_id, split, fallback_variant
    )
    sequence_id = f"{split}-{transform_class}-{seed}"
    frame_dir = root / split / sequence_id
    paths = (frame_dir / "frame_00.png", frame_dir / "frame_01.png", frame_dir / "frame_02.png")
    _write(paths[0], base)
    _write(paths[1], candidate)
    _write(paths[2], candidate)
    repo_paths = [str(path.relative_to(REPO_ROOT)).replace("\\", "/") for path in paths]
    visual_id = content_id if same else f"{content_id}-different"
    recipe = {
        "generator_version": GENERATOR_VERSION,
        "source_content_id": content_id,
        "generator_seed": seed,
        "transform_class": transform_class,
        "expected_label": "same" if same else "different",
        "required_fallback": fallback,
        "fallback_direction": direction,
        "transform_parameters": transform_parameters,
    }
    return {
        "sequence_id": sequence_id,
        "transform_class": transform_class,
        "source_content_id": content_id,
        "generator_seed": seed,
        "required_fallback": fallback,
        "fallback_direction": direction,
        "recipe": recipe,
        "recipe_sha256": hashlib.sha256(json.dumps(recipe, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "frames": [
            {"timestamp": 0.0, "expected_visual_id": content_id, "path": repo_paths[0], "sha256": _sha256(paths[0])},
            {"timestamp": 1.0, "expected_visual_id": visual_id, "path": repo_paths[1], "sha256": _sha256(paths[1])},
            {"timestamp": 2.0, "expected_visual_id": visual_id, "path": repo_paths[2], "sha256": _sha256(paths[2])},
        ],
    }


def build_real_sequence_manifest(root: Path = DEFAULT_OUT) -> dict[str, Any]:
    """Build independently seeded development and held-out content per class."""
    classes = sorted(REQUIRED_TRANSFORM_CLASSES)
    development_replica_counts = {
        name: 4 if name in {"pan_zoom", "pan_zoom_reverse"} else 2
        for name in classes
    }
    development = [
        _sequence("development", name, 1100 + 10 * index + replica, index, root)
        for index, name in enumerate(classes)
        for replica in range(development_replica_counts[name])
    ]
    held_out_replica_counts = {name: 1 for name in classes}
    held_out = [_sequence("held_out", name, 259100 + 10 * index, index, root) for index, name in enumerate(classes)]
    retired_holdouts = [
        {
            "manifest_sha256": "619379c53bdbd88e4eebfd9a7f4e6692a5ac0e26764e7c83fd28f6966dc56fe5",
            "generator_version": "issue-22-real-sequence-v1",
            "held_out_seed_start": 9100,
            "reason": "observed before corpus remediation",
        },
        {
            "manifest_sha256": "2ff3ff0a86c012d111c2740f0c1b3ba61891b5c6457a3c37eac38b207fa21ffd",
            "generator_version": "issue-22-real-sequence-v1-remediation-draft",
            "held_out_seed_start": 9100,
            "reason": "consumed while validating final branch coverage",
        },
        {
            "manifest_sha256": "3cc92a9b74f76a4443efa2bf4b29f8520539140253df8a194d00ec67b3484bff",
            "generator_version": "issue-22-real-sequence-v2",
            "held_out_seed_start": 19100,
            "reason": "consumed before held-out transform independence review",
        },
        {
            "manifest_sha256": "93384a0648e384527f054449b9b495f2930e2b6385bbf060fc050a13a3560dc2",
            "generator_version": "issue-22-real-sequence-v3",
            "held_out_seed_start": 29100,
            "reason": "consumed by first independent-transform validation",
        },
        {
            "manifest_sha256": "eb1c01b8081ce8b252f1bb1bc9d075b86f7849e5dd4bcb3df81c316d6b7fe809",
            "generator_version": "issue-22-real-sequence-v4",
            "held_out_seed_start": 39100,
            "reason": "consumed by second independent-transform validation",
        },
        {
            "manifest_sha256": "2dd21ea3febbb13961a4e79689823c15a7da8f81290c93bc9bf53196838b8bf7",
            "generator_version": "issue-22-real-sequence-v5",
            "held_out_seed_start": 49100,
            "reason": "consumed by residual and persistence validation",
        },
        {
            "manifest_sha256": "9ded9355d168daea669dec9ca6ff6c801f4e2f77311f7efd31513b45bf1c120c",
            "generator_version": "issue-22-real-sequence-v6",
            "held_out_seed_start": 59100,
            "reason": "consumed by ratio and reverse-persistence validation",
        },
        {
            "manifest_sha256": "d17c2e514f19e66240b42dbff9289c8af179cba5b20c8a9e437cb8d7e28e9d17",
            "generator_version": "issue-22-real-sequence-v7",
            "held_out_seed_start": 69100,
            "reason": "consumed before broadening development alignment-fit coverage",
        },
        {
            "manifest_sha256": "19949f95bb4567286320bd80f2b080a7781be1b751b4c8b5bd557e5ddd895159",
            "generator_version": "issue-22-real-sequence-v8",
            "held_out_seed_start": 79100,
            "reason": "superseded before held-out observation by broader development coverage",
        },
        {
            "manifest_sha256": "f4af923d505b6df6333a5d31e1f36e179f8d112d08fe75714936ff5fcbb687e7",
            "generator_version": "issue-22-real-sequence-v9",
            "held_out_seed_start": 89100,
            "reason": "superseded before held-out observation by final development envelope",
        },
        {
            "manifest_sha256": "0bf6accb1690603f1581232574cdb894a1a84657f7e1b6fb682db2627cb6c136",
            "generator_version": "issue-22-real-sequence-v10",
            "held_out_seed_start": 99100,
            "reason": "consumed before broadening low-feature development positives",
        },
        {
            "manifest_sha256": "b7fe3b35f96c5ce90976c8d31bbcdfb92d76f85eace8dbf3f10c6a5bd9b5b18c",
            "generator_version": "issue-22-real-sequence-v11",
            "held_out_seed_start": 109100,
            "reason": "superseded before held-out observation by expanded development sampling",
        },
        {
            "manifest_sha256": "1449888152824c20eb7e3eaabe6eceda0bbab58c81758695ff0e7b0ce51572d0",
            "generator_version": "issue-22-real-sequence-v12",
            "held_out_seed_start": 119100,
            "reason": "superseded before held-out observation by independent fallback replicas",
        },
        {
            "manifest_sha256": "80db87013d5d3ab2816dfd95987abed136d55c22f43cc82b1604d7c8b9821829",
            "generator_version": "issue-22-real-sequence-v13",
            "held_out_seed_start": 129100,
            "reason": "superseded before held-out observation by separable semantic patches",
        },
        {
            "manifest_sha256": "3b4877e37e091a7c64101abae5fe0c3522f29da676b3ffca99580da32f3450c6",
            "generator_version": "issue-22-real-sequence-v14",
            "held_out_seed_start": 139100,
            "reason": "superseded before held-out observation by sparse semantic negatives",
        },
        {
            "manifest_sha256": "9b6fd290fb2d950a101d3aa08244410d4ea2566640b507d1860f458af7221580",
            "generator_version": "issue-22-real-sequence-v15",
            "held_out_seed_start": 149100,
            "reason": "superseded before held-out observation by low-feature alignment-fit positives",
        },
        {
            "manifest_sha256": "d15137e5812592094e47bc3cb60572624e5658ce50a2e17574a94fa45da0d47e",
            "generator_version": "issue-22-real-sequence-v16",
            "held_out_seed_start": 159100,
            "reason": "superseded before held-out observation by direct-false edge-fit positives",
        },
        {
            "manifest_sha256": "756d8fc14f31597a508ff429967fbebf0b7092677911c4f35a6264d14145d783",
            "generator_version": "issue-22-real-sequence-v17",
            "held_out_seed_start": 169100,
            "reason": "superseded before held-out observation by photometric alignment-fit positives",
        },
        {
            "manifest_sha256": "a3774cb46be846d5a4059d2b86c16f423976e9ede538a9a2f660654c3c518be1",
            "generator_version": "issue-22-real-sequence-v18",
            "held_out_seed_start": 179100,
            "reason": "superseded before held-out observation by histogram-distinct fit positives",
        },
        {
            "manifest_sha256": "a3c2cf783cd33947ec37d7fd4dc10742308e40f4a02adcaf9863436122757fff",
            "generator_version": "issue-22-real-sequence-v19",
            "held_out_seed_start": 189100,
            "reason": "superseded before held-out observation by luminance-preserving fit positives",
        },
        {
            "manifest_sha256": "b37f1fadc6e62d6c46456183994ec9da5ab91ad5db47b2428e21204f6a3dc73f",
            "generator_version": "issue-22-real-sequence-v20",
            "held_out_seed_start": 199100,
            "reason": "superseded before held-out observation by non-rigid fit coverage",
        },
        {
            "manifest_sha256": "5f94c9e4a584d41204d9b61b1fe551ee25306870713eda80a4d48a48b90d0d2e",
            "generator_version": "issue-22-real-sequence-v21",
            "held_out_seed_start": 209100,
            "reason": "superseded before held-out observation by wider non-rigid fit coverage",
        },
        {
            "manifest_sha256": "ffd398a9b04eafa2d5cc0fa1f710618b4f5cd268f52679b494ed847086a5a62b",
            "generator_version": "issue-22-real-sequence-v22",
            "held_out_seed_start": 219100,
            "reason": "consumed before adding the predeclared nuisance-overlay regression",
        },
        {
            "manifest_sha256": "45a812a093184d4ffc0ab614636e89e1fd073d52013089d4f39d9def1d89364e",
            "generator_version": "issue-22-real-sequence-v23",
            "held_out_seed_start": 229100,
            "reason": "superseded before held-out observation by the full nuisance-overlay extent",
        },
        {
            "manifest_sha256": "f5b4d43a0b131912bc6b6d0a90647a09715c9ddb399f10f7928b8cdf0f2d79a5",
            "generator_version": "issue-22-real-sequence-v24",
            "held_out_seed_start": 239100,
            "reason": "consumed by a calibration invalidated when worker metadata source changed mid-run",
        },
        {
            "manifest_sha256": "9db007648be4e2ef95b71bf1c60f1f8245dc51b6b2a8e87b2c118770d3b88900",
            "generator_version": "issue-22-real-sequence-v25",
            "held_out_seed_start": 249100,
            "reason": "consumed before calibrating the exact production OpenCV provider set",
        },
    ]
    return {
        "manifest_version": 3,
        "generator_version": GENERATOR_VERSION,
        "corpus_kind": "real_image_sequence",
        "development_replica_counts": development_replica_counts,
        "held_out_replica_counts": held_out_replica_counts,
        "development_sequences": development,
        "held_out_sequences": held_out,
        "retired_holdouts": retired_holdouts,
        "lineage": {
            "development_protocol": "frozen-before-final-held-out-generation",
            "held_out_protocol": "fresh-after-generator-and-search-protocol-freeze",
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    root = args.out.resolve()
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    manifest = build_real_sequence_manifest(root)
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
