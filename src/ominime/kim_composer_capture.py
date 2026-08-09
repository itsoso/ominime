"""Local pre-submit text recovery for the legacy Kim desktop client."""

import time
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
    }
)
MIN_KIM_WINDOW_WIDTH = 300
MIN_KIM_WINDOW_HEIGHT = 200


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
    height=0.16,
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


@dataclass(frozen=True)
class RecognizedLine:
    text: str
    x: float
    y: float
    width: float
    height: float


def assemble_recognized_text(lines) -> str:
    """Order Vision observations into bounded plain text."""
    usable = [
        line
        for line in lines
        if line.text.strip()
        and line.text.strip() not in KIM_CHROME_LABELS
        and any(character.isalnum() for character in line.text)
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
    return any(
        "\u3400" <= character <= "\u4dbf"
        or "\u4e00" <= character <= "\u9fff"
        or "\uf900" <= character <= "\ufaff"
        for character in text
    )


class KimPreSubmitCapture:
    """Freeze and locally recognize the visible legacy Kim composer."""

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

    def freeze(self, target_pid: int) -> CapturedFrame | None:
        """Copy the largest normal window for the exact target PID."""
        if target_pid <= 0:
            return None
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
                return None
            window = max(windows, key=lambda item: item.width * item.height)
            image = self._image_provider(window.window_id)
            if image is None:
                return None
            return CapturedFrame(
                image=image,
                target_pid=target_pid,
                width=window.width,
                height=window.height,
                captured_at=self._clock(),
            )
        except Exception:
            return None

    def recognize(self, frame: CapturedFrame | None) -> tuple[str, str | None]:
        """Return trusted local OCR text or a non-content failure code."""
        if frame is None:
            return "", "kim_ocr_frame_unavailable"
        try:
            text = assemble_recognized_text(
                self._ocr_provider(frame.image, KIM_COMPOSER_ROI)
            )
            if not text:
                return "", "kim_ocr_empty"
            if not ocr_text_is_trusted(text, self._input_source_provider()):
                return "", "kim_ocr_uncommitted_text"
            return text, None
        except Exception:
            return "", "kim_ocr_native_error"

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
            lines.append(
                RecognizedLine(
                    text=str(candidate.string()),
                    x=float(bounds.origin.x),
                    y=float(bounds.origin.y),
                    width=float(bounds.size.width),
                    height=float(bounds.size.height),
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
