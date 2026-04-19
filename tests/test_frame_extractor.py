"""
Synthetic video test for frame_extractor.py.

Creates a video with:
  - frames 0-9:  blurry (heavy Gaussian blur)
  - frames 10-19: sharp (high-contrast checkerboard)
  - frames 20-29: blurry again

Asserts that extract_best_frame returns a frame from the sharp section.
"""

import cv2
import numpy as np
import tempfile
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.pipeline.frame_extractor import extract_best_frame, save_frame


FRAME_W, FRAME_H = 640, 480
FPS = 30
SHARP_SECTION = range(10, 20)


def _blurry_frame(index: int) -> np.ndarray:
    """Solid mid-grey with heavy blur — low Laplacian variance."""
    frame = np.full((FRAME_H, FRAME_W, 3), 128, dtype=np.uint8)
    frame[200, 320] = [0, 0, 255]  # tiny dot, gets smeared by blur
    return cv2.GaussianBlur(frame, (51, 51), 30)


def _sharp_frame(index: int) -> np.ndarray:
    """High-contrast checkerboard — very high Laplacian variance."""
    frame = np.zeros((FRAME_H, FRAME_W, 3), dtype=np.uint8)
    tile = 40
    for y in range(0, FRAME_H, tile):
        for x in range(0, FRAME_W, tile):
            if (x // tile + y // tile) % 2 == 0:
                frame[y:y+tile, x:x+tile] = 255
    return frame


def make_test_video(path: str) -> int:
    """Write 30 frames to path. Returns the index of the sharpest frame section start."""
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(path, fourcc, FPS, (FRAME_W, FRAME_H))
    for i in range(30):
        frame = _sharp_frame(i) if i in SHARP_SECTION else _blurry_frame(i)
        writer.write(frame)
    writer.release()
    return SHARP_SECTION.start


def test_picks_sharpest_frame():
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
        video_path = f.name

    try:
        make_test_video(video_path)
        frame, score, index = extract_best_frame(video_path, sample_every_n=1)

        print(f"  Best frame index : {index}")
        print(f"  Sharpness score  : {score:.2f}")
        print(f"  Frame shape      : {frame.shape}")

        assert index in SHARP_SECTION, (
            f"Expected frame from sharp section {list(SHARP_SECTION)}, got frame {index}"
        )
        assert score > 100, f"Expected high sharpness score, got {score:.2f}"
        assert frame.shape == (FRAME_H, FRAME_W, 3)
        print("  PASS — correct frame selected")

    finally:
        os.unlink(video_path)


def test_save_frame():
    with tempfile.TemporaryDirectory() as tmpdir:
        frame = _sharp_frame(0)
        out_path = os.path.join(tmpdir, "subdir", "best.jpg")
        result = save_frame(frame, out_path)

        assert result == out_path
        assert os.path.exists(out_path)
        loaded = cv2.imread(out_path)
        assert loaded is not None
        assert loaded.shape == frame.shape
        print("  PASS — frame saved and reloaded correctly")


def test_bad_video_raises():
    try:
        extract_best_frame("/nonexistent/fake.mp4")
        print("  FAIL — should have raised ValueError")
    except ValueError as e:
        print(f"  PASS — raised ValueError: {e}")


if __name__ == "__main__":
    print("\n[test_picks_sharpest_frame]")
    test_picks_sharpest_frame()

    print("\n[test_save_frame]")
    test_save_frame()

    print("\n[test_bad_video_raises]")
    test_bad_video_raises()

    print("\nAll tests passed.")
