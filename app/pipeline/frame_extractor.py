import cv2
import numpy as np
from pathlib import Path


def _sharpness(frame: np.ndarray) -> float:
    """Laplacian variance — higher means sharper."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return cv2.Laplacian(gray, cv2.CV_64F).var()


def _is_usable(frame: np.ndarray, min_brightness: int = 30, max_brightness: int = 225) -> bool:
    """Reject frames that are too dark or blown out."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    mean = float(gray.mean())
    return min_brightness < mean < max_brightness


def extract_best_frame(
    video_path: str,
    sample_every_n: int = 3,
) -> tuple[np.ndarray, float, int]:
    """
    Return (frame, sharpness_score, frame_index) for the sharpest usable frame.

    Samples every N frames to stay fast on 3-5 second clips.
    Raises ValueError if the video cannot be opened or contains no usable frames.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"Cannot open video: {video_path}")

    best_frame: np.ndarray | None = None
    best_score = -1.0
    best_index = -1
    frame_index = 0

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            if frame_index % sample_every_n == 0 and _is_usable(frame):
                score = _sharpness(frame)
                if score > best_score:
                    best_score = score
                    best_frame = frame.copy()
                    best_index = frame_index
            frame_index += 1
    finally:
        cap.release()

    if best_frame is None:
        raise ValueError(f"No usable frames found in: {video_path}")

    return best_frame, best_score, best_index


def save_frame(frame: np.ndarray, output_path: str) -> str:
    """Write frame to disk, creating parent dirs as needed. Returns the path."""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(output_path, frame)
    return output_path
