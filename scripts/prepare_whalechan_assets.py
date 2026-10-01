"""Prepare the checked-in whalechan atlas (development only; requires Pillow).

The source sheets have uneven margins and slightly overlapping rows. Separate
rows through their transparent gutter, then align each pose on a common canvas.
Original PNGs are never overwritten. Runtime only needs PyQt6 and the atlas.
"""
import json
from pathlib import Path
from statistics import median

from PIL import Image, ImageChops, ImageDraw


ROOT = Path(__file__).resolve().parents[1] / "assets" / "whalechan_sprites"
CELL = (560, 560)
BODY_HEIGHT = 460
BASELINE = 540
GOODBYE_SOURCE = "Whalechan’s Goodbye into a Cosmic Vortex.png"
# Keep the existing public action names for MCP callers.
TRACKS = [
    ("idle", "idle", 3, 6, [500, 500, 600, 500, 500, 600], False, "待机"),
    ("running-right", "walk_right", 4, 8, [300] * 7 + [400], False, "向右行走"),
    ("running-left", "walk_left", 4, 8, [300] * 7 + [400], False, "向左行走"),
    ("waving", "wave", 2, 4, [450] * 4, False, "招手"),
    ("jumping", "jump", 3, 5, [400, 400, 400, 450, 450], False, "跳跃"),
    ("failed", "sad", 4, 8, [550, 550, 550, 600, 650, 700, 550, 550], False, "低落"),
    ("waiting", "happy", 3, 6, [550, 550, 600, 550, 550, 600], False, "开心"),
    ("running", "sleepy", 3, 6, [330] * 5 + [400], False, "困倦"),
    ("review", "think", 3, 6, [650] * 6, False, "思考"),
    ("notification", "notification", 3, 6, [250, 250, 300, 350, 450, 900], False, "新消息提醒"),
    ("head-scratch", "Whalechan’s puzzled head-scratch animation.png", 3, 6,
     [350, 350, 400, 450, 450, 500], False, "扣扣脑袋"),
    ("goodbye", GOODBYE_SOURCE, 4, 8,
     [400, 400, 450, 450, 450, 450, 450, 500], False, "返回潜空间"),
]


def row_seam(alpha):
    """Find a continuous horizontal cut with the least opaque artwork loss.

    Several sheets put feet below the nominal midpoint; the sad sheet has no
    completely empty horizontal gutter. A per-column cut follows the gap between
    the shoes and the next pose's hair instead of slicing at half the height.
    """
    width, height = alpha.size
    middle = height // 2
    candidates = range(middle - 24, middle + 25)
    pixels = alpha.load()
    previous = {y: pixels[0, y] ** 2 + abs(y - middle) * 0.01 for y in candidates}
    parents = []
    for x in range(1, width):
        current, links = {}, {}
        for y in candidates:
            best = min((p for p in (y - 1, y, y + 1) if p in previous),
                       key=lambda p: previous[p] + abs(p - y) * 0.1)
            current[y] = previous[best] + pixels[x, y] ** 2 + abs(y - middle) * 0.01
            links[y] = best
        parents.append(links)
        previous = current
    seam = [min(previous, key=previous.get)]
    for links in reversed(parents):
        seam.append(links[seam[-1]])
    return list(reversed(seam))


def split_frames(sheet, columns, count):
    frames = []
    for index in range(count):
        column, row = index % columns, index // columns
        left = round(column * sheet.width / columns)
        right = round((column + 1) * sheet.width / columns)
        if sheet.info["action"] == GOODBYE_SOURCE and row == 1:
            # Frame 5's vortex extends eight pixels into the nominal next cell.
            # Assign that strip to frame 5 instead of leaving a ghost in frame 6.
            if column == 0:
                right += 8
            elif column == 1:
                left += 8
        strip = sheet.crop((left, 0, right, sheet.height))
        alpha = strip.getchannel("A")
        seam = row_seam(alpha)
        region = Image.new("L", strip.size)
        draw = ImageDraw.Draw(region)
        for x, cut in enumerate(seam):
            draw.line((x, 0 if row == 0 else cut, x, cut - 1 if row == 0 else strip.height - 1), fill=255)
        alpha = ImageChops.multiply(alpha, region)
        opaque = alpha.point(lambda value: 255 if value >= 128 else 0)
        bounds = opaque.getbbox()
        if bounds is None:
            raise ValueError(f"Empty source frame {index}")
        x0, y0, x1, y1 = bounds
        # The shoe midpoint anchors front-facing poses. For side walks the head
        # midpoint is stable while the feet alternate on either side of the body.
        band = (y0 + round((y1 - y0) * 0.15), y0 + round((y1 - y0) * 0.3)) if "walk" in sheet.info["action"] else (y1 - 20, y1)
        anchor_bounds = opaque.crop((0, band[0], strip.width, band[1])).getbbox()
        anchor_x = (anchor_bounds[0] + anchor_bounds[2]) / 2
        strip.putalpha(alpha)
        crop = (max(0, x0 - 3), max(0, y0 - 3), min(strip.width, x1 + 3), min(strip.height, y1 + 3))
        frames.append((strip.crop(crop), crop, anchor_x, y1, y1 - y0, row))
    return frames


def prepare():
    atlas = Image.new("RGBA", (CELL[0] * 8, CELL[1] * len(TRACKS)))
    configs, labels = {}, {}
    for row, (action, source, columns, count, durations, loop, label) in enumerate(TRACKS):
        filename = source if source.endswith(".png") else f"whalechan_{source}.png"
        sheet = Image.open(ROOT / filename).convert("RGBA")
        sheet.info["action"] = source
        frames = split_frames(sheet, columns, count)
        # One scale per action keeps breathing, tilts and the jump's crouch intact.
        reference_height = (frames[0][4] if action == "goodbye" else frames[-1][4] if action == "jumping"
                            else median(frame[4] for frame in frames))
        scale = BODY_HEIGHT / reference_height
        for index, (image, crop, anchor_x, bottom, _, source_row) in enumerate(frames):
            frame = Image.new("RGBA", CELL)
            resized = image.resize((round(image.width * scale), round(image.height * scale)), Image.Resampling.LANCZOS)
            baseline = bottom
            if action == "jumping":
                # Preserve the airborne frame's actual rise above the source floor.
                baseline = frames[0][3] + source_row * sheet.height / 2
            elif action == "goodbye":
                # Keep a fixed cell origin and scale: the vortex's shrinking and
                # character movement are part of the animation, not trim margins.
                anchor_x = frames[0][2]
                if index == 5:
                    anchor_x -= 8
                baseline = frames[0][3] + source_row * sheet.height / 2
            x = round(CELL[0] / 2 + (crop[0] - anchor_x) * scale)
            y = round(BASELINE + (crop[1] - baseline) * scale)
            if x < 0 or y < 0 or x + resized.width > CELL[0] or y + resized.height > CELL[1]:
                raise ValueError(f"Normalized frame exceeds canvas: {action}[{index}]")
            frame.alpha_composite(resized, (x, y))
            atlas.paste(frame, (index * CELL[0], row * CELL[1]))
        configs[action] = {"durations": durations, "loop": loop, "fallback": "idle"}
        labels[action] = label
        print(f"Prepared {action}: {count} frames")
    atlas.save(ROOT / "spritesheet.webp", lossless=True, method=6, exact=True)
    manifest = {
        "petManifestVersion": 2, "id": "whalechan-redrawn", "displayName": "鲸鱼娘（重绘版）",
        "description": "使用 whalechan 重绘动作图，包含独立的新消息提醒动画。",
        "renderer": "sprite2d", "labels": labels,
        "idleGroup": [t[0] for t in TRACKS if t[0] not in ("failed", "running", "notification", "goodbye")],
        "sprite2d": {"spritesheetPath": "spritesheet.webp", "cell": {"width": CELL[0], "height": CELL[1]},
                     "columns": 8, "atlasRows": len(TRACKS), "actions": [t[0] for t in TRACKS],
                     "frames": [t[3] for t in TRACKS], "tracks": configs},
    }
    (ROOT / "pet.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    prepare()
