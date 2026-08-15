"""Local pre-submit text recovery for the legacy Kim desktop client."""

import re
import threading
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable


LEGACY_KIM_BUNDLE_ID = "Kem"
KIM_CHROME_LABELS = frozenset(
    {
        "↩︎ 发送 / ⌘↩︎ 换行",
        "↩ 发送 / ⌘↩ 换行",
        "B I S",
        "B I 8",
    }
)
MIN_WATERMARK_SLANT_RATIO = 0.5
KIM_CHAT_SIDEBAR_FRACTION = 0.28
KIM_CHAT_COMPOSER_FRACTION = 0.20
KIM_CHAT_HEADER_FRACTION = 0.09
KIM_CHAT_RIGHT_MARGIN_FRACTION = 0.02


@dataclass(frozen=True)
class NormalizedRect:
    x: float
    y: float
    width: float
    height: float


@dataclass(frozen=True)
class RecognizedLine:
    text: str
    x: float
    y: float
    width: float
    height: float
    slant_ratio: float = 0.0


def recognized_content_lines(lines) -> tuple[RecognizedLine, ...]:
    """Remove composer chrome and tiled watermarks from OCR observations."""
    usable = [
        line
        for line in lines
        if line.text.strip()
        and line.text.strip() not in KIM_CHROME_LABELS
        and any(character.isalnum() for character in line.text)
    ]
    grouped: dict[str, list[RecognizedLine]] = defaultdict(list)
    for line in usable:
        grouped[line.text.strip().casefold()].append(line)
    tiled_watermarks = {
        normalized_text
        for normalized_text, repeated_lines in grouped.items()
        if len(repeated_lines) >= 4
        and all(
            line.slant_ratio >= MIN_WATERMARK_SLANT_RATIO for line in repeated_lines
        )
        and max(line.x for line in repeated_lines)
        - min(line.x for line in repeated_lines)
        > max(line.width for line in repeated_lines) * 1.5
        and max(line.y for line in repeated_lines)
        - min(line.y for line in repeated_lines)
        > max(line.height for line in repeated_lines) * 1.5
    }

    def is_tiled_watermark_variant(line: RecognizedLine) -> bool:
        candidate = line.text.strip().casefold()
        matches_tiled_watermark = any(
            candidate == watermark
            or (
                min(len(candidate), len(watermark)) >= 4
                and abs(len(candidate) - len(watermark)) <= 2
                and watermark.startswith(candidate)
            )
            for watermark in tiled_watermarks
        )
        if matches_tiled_watermark:
            return True
        return (
            line.slant_ratio >= MIN_WATERMARK_SLANT_RATIO
            and re.fullmatch(r"[a-z]{4,}", candidate) is not None
        )

    return tuple(line for line in usable if not is_tiled_watermark_variant(line))


class VisionTextRecognizer:
    """Callable Vision bridge with cooperative request cancellation."""

    def __init__(self):
        self._lock = threading.Lock()
        self._active_request = None

    def __call__(
        self,
        image,
        roi: NormalizedRect,
    ) -> Iterable[RecognizedLine]:
        import Quartz

        request_class, handler_class = _vision_classes()
        request = request_class.alloc().init()
        request.setRecognitionLevel_(0)  # VNRequestTextRecognitionLevelAccurate
        request.setRecognitionLanguages_(["zh-Hans", "en-US"])
        request.setUsesLanguageCorrection_(True)
        request.setRegionOfInterest_(
            Quartz.CGRectMake(roi.x, roi.y, roi.width, roi.height)
        )
        handler = handler_class.alloc().initWithCGImage_options_(image, {})
        with self._lock:
            self._active_request = request
        try:
            if not handler.performRequests_error_([request], None):
                raise RuntimeError("Vision text recognition failed")
        finally:
            with self._lock:
                self._active_request = None

        lines = []
        for observation in request.results() or ():
            candidates = observation.topCandidates_(1) or ()
            if not candidates:
                continue
            candidate = candidates[0]
            if candidate.confidence() < 0.35:
                continue
            bounds = observation.boundingBox()
            top_left = observation.topLeft()
            top_right = observation.topRight()
            slant_ratio = abs(float(top_right.y) - float(top_left.y)) / max(
                abs(float(top_right.x) - float(top_left.x)),
                0.0001,
            )
            lines.append(
                RecognizedLine(
                    text=str(candidate.string()),
                    x=roi.x + float(bounds.origin.x) * roi.width,
                    y=roi.y + float(bounds.origin.y) * roi.height,
                    width=float(bounds.size.width) * roi.width,
                    height=float(bounds.size.height) * roi.height,
                    slant_ratio=slant_ratio,
                )
            )
        return tuple(lines)

    def cancel(self) -> None:
        with self._lock:
            request = self._active_request
        if request is not None:
            request.cancel()


@lru_cache(maxsize=1)
def _vision_classes():
    import objc

    objc.loadBundle(
        "Vision",
        globals(),
        bundle_path="/System/Library/Frameworks/Vision.framework",
    )
    return (
        objc.lookUpClass("VNRecognizeTextRequest"),
        objc.lookUpClass("VNImageRequestHandler"),
    )


def native_recognized_lines(
    image,
    roi: NormalizedRect,
) -> Iterable[RecognizedLine]:
    """Public generic Vision bridge used by post-send bubble capture."""
    return VisionTextRecognizer()(image, roi)
