#!/usr/bin/env python3
"""Encode rendered PNG frames as a verified, continuously looping GIF.

Example, from brick-planner/ after installing requirements-demo.txt:
    .venv/bin/python scripts/demo_gif.py --frames-dir /tmp/frames --output demo.gif

Frames must be opaque PNGs named frame-000.png, frame-001.png, and so on, with
contiguous numeric indices starting at zero and identical dimensions. Output
frames are never resized. The renderer supplies one turn without a repeated
360-degree endpoint; an exact repeated final image is also removed defensively.
The encoder cannot infer camera angles from pixels or certify angular coverage.

A single palette is trained from samples across all frames. Quantization uses
no dithering, avoiding moving stipple noise on the rendered surfaces. Optimized
delta frames retain the previous image (GIF disposal 1); the first frame covers
the whole canvas, including when the animation loops. Decoded GIF frames are
compared against every quantized source frame before the output is published.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import re
import tempfile

from PIL import Image, ImageChops


MAX_PALETTE_SAMPLES = 1_048_576
FRAME_NAME = re.compile(r"frame-(\d+)\.png")


def discover_frames(directory: Path) -> list[Path]:
    if not directory.is_dir():
        raise ValueError(f"Frame directory does not exist: {directory}")
    numbered = []
    for path in directory.glob("frame-*.png"):
        match = FRAME_NAME.fullmatch(path.name)
        if match is None:
            raise ValueError(f"Invalid frame name: {path.name}; use frame-000.png, frame-001.png, ...")
        numbered.append((int(match.group(1)), path))
    numbered.sort()
    if len(numbered) < 2:
        raise ValueError("A looping animation needs at least two numbered PNG frames.")
    if [index for index, _ in numbered] != list(range(len(numbered))):
        raise ValueError("Frame numbers must be unique, contiguous, and start at zero.")
    return [path for _, path in numbered]


def read_frame(path: Path, expected_size=None) -> Image.Image:
    with Image.open(path) as source:
        if source.format != "PNG":
            raise ValueError(f"Frame is not a PNG: {path}")
        if expected_size is not None and source.size != expected_size:
            raise ValueError(f"Frame {path.name} has size {source.size}; expected {expected_size}.")
        rgba = source.convert("RGBA")
        try:
            if rgba.getextrema()[3] != (255, 255):
                raise ValueError(f"Frame {path.name} is transparent; render an explicit opaque background.")
            return rgba.convert("RGB")
        finally:
            rgba.close()


def shared_palette(paths: list[Path], size) -> Image.Image:
    """Uniform pixel samples from every view, without resizing output images."""
    width, height = size
    samples_per_frame = max(1, MAX_PALETTE_SAMPLES // len(paths))
    stride = max(1, math.ceil(math.sqrt(width * height / samples_per_frame)))
    samples = bytearray()
    for index, path in enumerate(paths):
        with read_frame(path, size) as frame:
            pixels = frame.tobytes()
            # Shift the sample lattice between views to cover thin edges as well
            # as broad surfaces without any random sampling or color averaging.
            x_offset = index % min(stride, width)
            y_offset = (index // stride) % min(stride, height)
            for y in range(y_offset, height, stride):
                for x in range(x_offset, width, stride):
                    offset = 3 * (y * width + x)
                    samples.extend(pixels[offset:offset + 3])
    sample_count = len(samples) // 3
    # A compact rectangular image is just a container for the color samples.
    sample_width = min(1024, sample_count)
    sample_height = math.ceil(sample_count / sample_width)
    samples.extend(samples[-3:] * (sample_width * sample_height - sample_count))
    with Image.frombytes("RGB", (sample_width, sample_height), bytes(samples)) as sample_image:
        return sample_image.quantize(colors=256, method=Image.Quantize.MEDIANCUT,
                                     dither=Image.Dither.NONE)


def verify_gif(path: Path, frames, durations, size) -> dict:
    """Verify timing, loop metadata, and fully composited decoded frame pixels."""
    with Image.open(path) as animation:
        if animation.format != "GIF" or animation.size != size:
            raise ValueError("Encoded output has the wrong format or canvas size.")
        if animation.n_frames != len(frames):
            raise ValueError(f"Encoded frame count is {animation.n_frames}, expected {len(frames)}.")
        if animation.info.get("loop") != 0:
            raise ValueError("Encoded GIF is not configured to loop continuously.")
        actual_durations = []
        for index, (expected, duration) in enumerate(zip(frames, durations)):
            animation.seek(index)
            actual = animation.info.get("duration")
            if actual != duration:
                raise ValueError(f"Frame {index} has duration {actual} ms, expected {duration} ms.")
            actual_durations.append(actual)
            with animation.convert("RGB") as decoded, expected.convert("RGB") as reference:
                with ImageChops.difference(decoded, reference) as difference:
                    if difference.getbbox() is not None:
                        raise ValueError(f"Decoded frame {index} differs from its quantized source.")
        return {"frame_count": animation.n_frames, "width": size[0], "height": size[1],
                "total_duration_ms": sum(actual_durations), "loop": animation.info["loop"],
                "decoded_frames_verified": True}


def encode_gif(frames_dir: Path, output: Path, duration_ms: int = 80) -> dict:
    if duration_ms < 10 or duration_ms > 655350 or duration_ms % 10:
        raise ValueError("GIF duration must be a multiple of 10 ms between 10 and 655350 ms.")
    if output.suffix.lower() != ".gif":
        raise ValueError("Output filename must end in .gif.")
    paths = discover_frames(frames_dir)
    input_frame_count = len(paths)
    dropped_endpoint = False
    with read_frame(paths[0]) as first:
        size = first.size
        with read_frame(paths[-1], size) as last, ImageChops.difference(first, last) as difference:
            if difference.getbbox() is None:
                paths.pop()
                dropped_endpoint = True
    if len(paths) < 2:
        raise ValueError("There are fewer than two frames after removing a repeated endpoint.")

    palette = shared_palette(paths, size)
    frames, durations = [], []
    previous_pixels = None
    temporary_path = None
    try:
        for path in paths:
            with read_frame(path, size) as rgb:
                quantized = rgb.quantize(palette=palette, dither=Image.Dither.NONE)
            pixels = quantized.tobytes()
            if frames and pixels == previous_pixels:
                durations[-1] += duration_ms
                quantized.close()
                if durations[-1] > 655350:
                    raise ValueError("A repeated-frame hold exceeds the GIF duration limit.")
            else:
                frames.append(quantized)
                durations.append(duration_ms)
                previous_pixels = pixels
        if len(frames) < 2:
            raise ValueError("All rendered frames become identical after GIF quantization.")
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix=f".{output.stem}-", suffix=".gif",
                                         dir=output.parent, delete=False) as temporary:
            temporary_path = Path(temporary.name)
        frames[0].save(temporary_path, format="GIF", save_all=True,
                       append_images=frames[1:], duration=durations, loop=0,
                       disposal=1, optimize=True, palette=palette.getpalette())
        report = verify_gif(temporary_path, frames, durations, size)
        expected_total = len(paths) * duration_ms
        if report["total_duration_ms"] != expected_total:
            raise ValueError("GIF timing does not cover the supplied frame timeline exactly.")
        report.update(input_frame_count=input_frame_count, timeline_frame_count=len(paths),
                      duration_ms=duration_ms, dropped_duplicate_endpoint=dropped_endpoint,
                      coalesced_frames=len(paths) - len(frames),
                      file_bytes=temporary_path.stat().st_size, output=str(output.resolve()))
        temporary_path.replace(output)
        return report
    finally:
        palette.close()
        for frame in frames:
            frame.close()
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--frames-dir", type=Path, required=True, help="Directory containing frame-000.png onward")
    parser.add_argument("--output", type=Path, required=True, help="Destination .gif (replaced only after validation)")
    parser.add_argument("--duration-ms", type=int, default=80, help="Duration of each source frame in milliseconds; default 80")
    args = parser.parse_args()
    try:
        report = encode_gif(args.frames_dir.expanduser(), args.output.expanduser(), args.duration_ms)
    except (OSError, ValueError) as error:
        parser.exit(2, f"GIF encoding failed: {error}\n")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
