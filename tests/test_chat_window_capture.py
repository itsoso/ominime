import gc
import threading
import time
import weakref

from ominime.chat_window_capture import (
    ChatWindowBaselineSampler,
    WindowFrame,
    WindowInfo,
)


def _wait_until(predicate, timeout=1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("condition was not reached")


class MutableClock:
    def __init__(self, value=0.0):
        self.value = value

    def __call__(self):
        return self.value


def test_sampler_selects_frontmost_eligible_layer_zero_window():
    selected = []
    sampler = ChatWindowBaselineSampler(
        window_provider=lambda: (
            WindowInfo(1, 123, 1, 900, 700),
            WindowInfo(2, 999, 0, 900, 700),
            WindowInfo(3, 123, 0, 100, 100),
            WindowInfo(4, 123, 0, 900, 700),
            WindowInfo(5, 123, 0, 1200, 900),
        ),
        image_provider=lambda window_id: selected.append(window_id) or "image",
        clock=lambda: 12.5,
    )

    try:
        assert sampler.schedule(123)
        _wait_until(lambda: sampler.has_baseline)
        frame = sampler.take_baseline(123)
    finally:
        sampler.stop()

    assert frame == WindowFrame("image", 4, 123, 900, 700, 12.5)
    assert selected == [4]


def test_sampler_throttles_typing_to_one_capture_per_250ms():
    clock = MutableClock()
    captures = []
    sampler = ChatWindowBaselineSampler(
        window_provider=lambda: (WindowInfo(4, 123, 0, 900, 700),),
        image_provider=lambda window_id: captures.append(window_id) or object(),
        clock=clock,
    )

    try:
        assert sampler.schedule(123)
        _wait_until(lambda: len(captures) == 1)
        clock.value = 0.1
        assert not sampler.schedule(123)
        clock.value = 0.25
        assert sampler.schedule(123)
        _wait_until(lambda: len(captures) == 2)
    finally:
        sampler.stop()

    assert captures == [4, 4]


def test_sampler_captures_on_worker_not_calling_thread():
    caller_thread = threading.get_ident()
    provider_threads = []
    sampler = ChatWindowBaselineSampler(
        window_provider=lambda: provider_threads.append(threading.get_ident())
        or (WindowInfo(4, 123, 0, 900, 700),),
        image_provider=lambda window_id: object(),
    )

    try:
        assert sampler.schedule(123)
        _wait_until(lambda: sampler.has_baseline)
    finally:
        sampler.stop()

    assert provider_threads
    assert provider_threads[0] != caller_thread


def test_sampler_keeps_only_newest_frame_and_take_transfers_it():
    clock = MutableClock()
    image_number = [0]

    def image_provider(window_id):
        image_number[0] += 1
        return f"image-{image_number[0]}"

    sampler = ChatWindowBaselineSampler(
        window_provider=lambda: (WindowInfo(4, 123, 0, 900, 700),),
        image_provider=image_provider,
        clock=clock,
    )

    try:
        assert sampler.schedule(123)
        _wait_until(lambda: image_number[0] == 1)
        clock.value = 0.3
        assert sampler.schedule(123)
        _wait_until(lambda: image_number[0] == 2)
        frame = sampler.take_baseline(123)
        assert frame.image == "image-2"
        assert sampler.take_baseline(123) is None
        assert not sampler.has_baseline
    finally:
        sampler.stop()


def test_sampler_pid_and_window_changes_invalidate_previous_baseline():
    clock = MutableClock()
    active_pid = [123]
    window_id = [4]
    captured = []
    sampler = ChatWindowBaselineSampler(
        window_provider=lambda: (
            WindowInfo(window_id[0], active_pid[0], 0, 900, 700),
        ),
        image_provider=lambda selected: captured.append(selected)
        or f"image-{selected}",
        clock=clock,
    )

    try:
        assert sampler.schedule(123)
        _wait_until(lambda: sampler.has_baseline)
        active_pid[0] = 456
        window_id[0] = 8
        assert sampler.schedule(456)
        _wait_until(lambda: captured == [4, 8])
        assert sampler.take_baseline(123) is None
        assert sampler.take_baseline(456).window_id == 8
    finally:
        sampler.stop()


def test_sampler_failure_is_named_without_image_and_worker_survives():
    diagnostics = []
    fail = [True]

    def image_provider(window_id):
        if fail[0]:
            fail[0] = False
            raise RuntimeError("secret pixels")
        return "memory-image"

    clock = MutableClock()
    sampler = ChatWindowBaselineSampler(
        window_provider=lambda: (WindowInfo(4, 123, 0, 900, 700),),
        image_provider=image_provider,
        on_diagnostic=diagnostics.append,
        clock=clock,
    )

    try:
        assert sampler.schedule(123)
        _wait_until(lambda: diagnostics == ["baseline_unavailable"])
        assert sampler.worker_alive
        clock.value = 0.3
        assert sampler.schedule(123)
        _wait_until(lambda: sampler.has_baseline)
    finally:
        sampler.stop()

    assert diagnostics == ["baseline_unavailable"]
    assert "secret pixels" not in repr(diagnostics)


def test_sampler_drops_worker_reference_after_baseline_transfer():
    class MemoryImage:
        pass

    image = MemoryImage()
    image_ref = weakref.ref(image)
    sampler = ChatWindowBaselineSampler(
        window_provider=lambda: (WindowInfo(4, 123, 0, 900, 700),),
        image_provider=lambda window_id: image,
    )

    try:
        assert sampler.schedule(123)
        _wait_until(lambda: sampler.has_baseline)
        frame = sampler.take_baseline(123)
        del frame
        del image
        gc.collect()
        assert image_ref() is None
    finally:
        sampler.stop()


def test_sampler_timeout_stop_eventually_clears_current_frame():
    entered = threading.Event()
    release_capture = threading.Event()

    class MemoryImage:
        pass

    image = MemoryImage()
    image_ref = weakref.ref(image)

    def image_provider(window_id):
        entered.set()
        release_capture.wait(1)
        return image

    sampler = ChatWindowBaselineSampler(
        window_provider=lambda: (WindowInfo(4, 123, 0, 900, 700),),
        image_provider=image_provider,
    )

    assert sampler.schedule(123)
    assert entered.wait(1)
    sampler.stop(timeout=0.02)
    del image
    release_capture.set()
    _wait_until(lambda: not sampler.worker_alive)
    gc.collect()

    assert image_ref() is None
