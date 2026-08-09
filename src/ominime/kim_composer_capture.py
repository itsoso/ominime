"""Local pre-submit text recovery for the legacy Kim desktop client."""

import re
import threading
import time
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from typing import Callable, Iterable


DOUBAO_BUNDLE_ID = "com.bytedance.inputmethod.doubaoime"
LEGACY_KIM_BUNDLE_ID = "Kem"
MAX_OCR_TEXT_CHARS = 4000
KIM_CHROME_LABELS = frozenset(
    {
        "↩︎ 发送 / ⌘↩︎ 换行",
        "↩ 发送 / ⌘↩ 换行",
        "B I S",
        "B I 8",
    }
)
MIN_KIM_WINDOW_WIDTH = 300
MIN_KIM_WINDOW_HEIGHT = 200
WINDOW_CACHE_TTL_SECONDS = 5.0
MIN_WATERMARK_SLANT_RATIO = 0.5


@dataclass(frozen=True)
class NormalizedRect:
    x: float
    y: float
    width: float
    height: float


KIM_COMPOSER_ROI = NormalizedRect(
    x=0.29,
    y=0.05,
    width=0.55,
    height=0.135,
)


@dataclass(frozen=True)
class WindowInfo:
    window_id: int
    pid: int
    layer: int
    width: float
    height: float


@dataclass(frozen=True)
class CapturedFrame:
    image: object
    target_pid: int
    width: float
    height: float
    captured_at: float
    input_source_bundle_id: str


@dataclass(frozen=True)
class RecognizedLine:
    text: str
    x: float
    y: float
    width: float
    height: float
    slant_ratio: float = 0.0


def assemble_recognized_text(lines) -> str:
    """Order Vision observations into bounded plain text."""
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
            line.slant_ratio >= MIN_WATERMARK_SLANT_RATIO
            for line in repeated_lines
        )
        and max(line.x for line in repeated_lines)
        - min(line.x for line in repeated_lines)
        > max(line.width for line in repeated_lines) * 1.5
        and max(line.y for line in repeated_lines)
        - min(line.y for line in repeated_lines)
        > max(line.height for line in repeated_lines) * 1.5
    }

    def is_tiled_watermark_variant(line: RecognizedLine) -> bool:
        if line.slant_ratio < MIN_WATERMARK_SLANT_RATIO:
            return False
        candidate = line.text.strip().casefold()
        return any(
            candidate == watermark
            or (
                min(len(candidate), len(watermark)) >= 4
                and abs(len(candidate) - len(watermark)) <= 2
                and (
                    candidate.startswith(watermark)
                    or watermark.startswith(candidate)
                )
            )
            for watermark in tiled_watermarks
        )

    usable = [
        line
        for line in usable
        if not is_tiled_watermark_variant(line)
    ]
    usable.sort(key=lambda line: (-(line.y + line.height / 2), line.x))

    rows: list[list[RecognizedLine]] = []
    for line in usable:
        if not rows:
            rows.append([line])
            continue
        previous = rows[-1]
        previous_center = sum(
            item.y + item.height / 2 for item in previous
        ) / len(previous)
        line_center = line.y + line.height / 2
        row_height = max(item.height for item in previous)
        if abs(previous_center - line_center) <= max(row_height, line.height) * 0.6:
            previous.append(line)
        else:
            rows.append([line])

    text = "\n".join(
        " ".join(item.text.strip() for item in sorted(row, key=lambda item: item.x))
        for row in rows
    )
    return text[:MAX_OCR_TEXT_CHARS]


def ocr_text_is_trusted(text: str, input_source_bundle_id: str) -> bool:
    """Reject raw Doubao pre-edit text while accepting committed CJK."""
    if not isinstance(text, str) or not text.strip():
        return False
    if input_source_bundle_id != DOUBAO_BUNDLE_ID:
        return True
    if re.search(r"[a-z]+(?:'[a-z]+)*\s*$", text):
        return False
    return any(
        "\u3400" <= character <= "\u4dbf"
        or "\u4e00" <= character <= "\u9fff"
        or "\uf900" <= character <= "\ufaff"
        for character in text
    )


def ocr_text_matches_physical_count(text: str, physical_key_count: int) -> bool:
    """Reject OCR that is implausibly small or large for observed input."""
    visible_chars = sum(1 for character in text if not character.isspace())
    if visible_chars <= 0 or physical_key_count <= 0:
        return False
    return (
        visible_chars <= physical_key_count * 4
        and physical_key_count <= visible_chars * 8 + 8
    )


class KimPreSubmitCapture:
    """Freeze and locally recognize the visible legacy Kim composer."""

    composer_roi = KIM_COMPOSER_ROI
    failure_prefix = "kim_ocr"

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        window_provider: Callable[[], Iterable[WindowInfo]] | None = None,
        image_provider: Callable[[int], object] | None = None,
        ocr_provider: Callable[
            [object, NormalizedRect], Iterable[RecognizedLine]
        ]
        | None = None,
        input_source_provider: Callable[[], str] | None = None,
    ):
        self._clock = clock
        self._window_provider = window_provider or self._native_windows
        self._image_provider = image_provider or self._native_window_image
        self._ocr_provider = ocr_provider or self._native_recognized_lines
        self._input_source_provider = (
            input_source_provider or self._current_input_source_bundle_id
        )
        self._prepared_windows: dict[int, tuple[WindowInfo, float]] = {}
        self._window_lock = threading.Lock()

    def prepare(self, target_pid: int) -> bool:
        """Resolve the target window off the EventTap callback thread."""
        if target_pid <= 0:
            return False
        now = self._clock()
        with self._window_lock:
            prepared = self._prepared_windows.get(target_pid)
            if prepared is not None:
                _, prepared_at = prepared
                if now - prepared_at <= WINDOW_CACHE_TTL_SECONDS:
                    return True
                self._prepared_windows.pop(target_pid, None)
        try:
            windows = tuple(
                window
                for window in self._window_provider()
                if window.pid == target_pid
                and window.layer == 0
                and window.width >= MIN_KIM_WINDOW_WIDTH
                and window.height >= MIN_KIM_WINDOW_HEIGHT
            )
            if not windows:
                with self._window_lock:
                    self._prepared_windows.pop(target_pid, None)
                return False
            window = windows[0]
            with self._window_lock:
                self._prepared_windows = {
                    target_pid: (window, self._clock())
                }
            return True
        except Exception:
            return False

    def freeze(self, target_pid: int) -> CapturedFrame | None:
        """Copy a prepared target window without enumerating applications."""
        if target_pid <= 0:
            return None
        try:
            with self._window_lock:
                prepared = self._prepared_windows.get(target_pid)
                if prepared is None:
                    return None
                window, _ = prepared
            if window is None:
                return None
            image = self._image_provider(window.window_id)
            if image is None:
                self._invalidate_window(target_pid, window.window_id)
                return None
            return CapturedFrame(
                image=image,
                target_pid=target_pid,
                width=window.width,
                height=window.height,
                captured_at=self._clock(),
                input_source_bundle_id=self._input_source_provider(),
            )
        except Exception:
            self._invalidate_window(target_pid)
            return None

    def _invalidate_window(
        self,
        target_pid: int,
        expected_window_id: int | None = None,
    ) -> None:
        with self._window_lock:
            prepared = self._prepared_windows.get(target_pid)
            if prepared is None:
                return
            window, _ = prepared
            if (
                expected_window_id is None
                or window.window_id == expected_window_id
            ):
                self._prepared_windows.pop(target_pid, None)

    def recognize(self, frame: CapturedFrame | None) -> tuple[str, str | None]:
        """Return trusted local OCR text or a non-content failure code."""
        if frame is None:
            return "", self._failure_code("frame_unavailable")
        try:
            roi = self.composer_roi_for_frame(frame)
            lines = tuple(self._ocr_provider(frame.image, roi))
            bottom_edge = (
                roi.y + roi.height * 0.02
            )
            top_edge = (
                roi.y + roi.height * 0.98
            )
            if any(
                line.y <= bottom_edge
                or line.y + line.height >= top_edge
                or line.x <= roi.x + roi.width * 0.02
                or line.x + line.width >= roi.x + roi.width * 0.98
                for line in lines
                if line.text.strip()
            ):
                return "", self._failure_code("edge_clipped")
            text = assemble_recognized_text(lines)
            if not text:
                return "", self._failure_code("empty")
            if "\n" in text:
                return "", self._failure_code("multiline_untrusted")
            if not ocr_text_is_trusted(
                text,
                frame.input_source_bundle_id,
            ):
                return "", self._failure_code("uncommitted_text")
            return text, None
        except Exception:
            return "", self._failure_code("native_error")

    def _failure_code(self, suffix: str) -> str:
        return f"{self.failure_prefix}_{suffix}"

    def composer_roi_for_frame(self, frame: CapturedFrame) -> NormalizedRect:
        return self.composer_roi

    @staticmethod
    def _current_input_source_bundle_id() -> str:
        from .ime_candidate_capture import current_input_source_bundle_id

        return current_input_source_bundle_id()

    @staticmethod
    def _native_windows() -> Iterable[WindowInfo]:
        import Quartz

        options = (
            Quartz.kCGWindowListOptionOnScreenOnly
            | Quartz.kCGWindowListExcludeDesktopElements
        )
        items = Quartz.CGWindowListCopyWindowInfo(options, Quartz.kCGNullWindowID)
        windows = []
        for item in items or ():
            bounds = item.get(Quartz.kCGWindowBounds) or {}
            try:
                windows.append(
                    WindowInfo(
                        window_id=int(item.get(Quartz.kCGWindowNumber, 0) or 0),
                        pid=int(item.get(Quartz.kCGWindowOwnerPID, 0) or 0),
                        layer=int(item.get(Quartz.kCGWindowLayer, 0) or 0),
                        width=float(bounds.get("Width", 0) or 0),
                        height=float(bounds.get("Height", 0) or 0),
                    )
                )
            except (TypeError, ValueError):
                continue
        return tuple(windows)

    @staticmethod
    def _native_window_image(window_id: int):
        import Quartz

        return Quartz.CGWindowListCreateImageFromArray(
            Quartz.CGRectNull,
            [window_id],
            Quartz.kCGWindowImageBoundsIgnoreFraming,
        )

    @staticmethod
    def _native_recognized_lines(
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
        if not handler.performRequests_error_([request], None):
            raise RuntimeError("Vision text recognition failed")

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
