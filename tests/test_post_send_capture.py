from datetime import datetime
import gc
import threading
import time
import weakref

import pytest

from ominime.post_send_capture import (
    MAX_TRUSTED_SUBMISSION_CHARS,
    CaptureOutcome,
    MessageSourceChain,
    PostSendCaptureCoordinator,
    SendIntent,
    SourceResult,
)


class FakeSource:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def read(self, intent):
        self.calls.append(intent)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.fixture
def intent():
    return SendIntent(
        intent_id="send-1",
        submitted_at=10.0,
        timestamp=datetime(2026, 8, 15, 12, 0),
        app_name="Kim",
        bundle_id="Kem",
        target_pid=123,
        modifiers={},
        physical_key_count=4,
        validation_text="测试",
        baseline=None,
    )


def test_send_intent_is_immutable(intent):
    with pytest.raises(AttributeError):
        intent.target_pid = 456


def test_send_intent_defensively_freezes_modifiers():
    modifiers = {"shift": False}
    immutable = SendIntent(
        intent_id="send-frozen",
        submitted_at=10.0,
        timestamp=datetime(2026, 8, 15, 12, 0),
        app_name="Kim",
        bundle_id="Kem",
        target_pid=123,
        modifiers=modifiers,
        physical_key_count=1,
        validation_text="x",
        baseline=None,
    )

    modifiers["shift"] = True

    assert immutable.modifiers["shift"] is False
    with pytest.raises(TypeError):
        immutable.modifiers["shift"] = True


def test_source_chain_returns_first_trusted_result(intent):
    unavailable = FakeSource(SourceResult.unavailable("ax_unavailable"))
    trusted = FakeSource(
        SourceResult.success(
            "  测试\n完成  ",
            "kim_postsend_ocr",
            "bubble-1",
            target_pid=123,
            observed_at=10.2,
        )
    )
    unused = FakeSource(
        SourceResult.success(
            "wrong",
            "unused",
            "bubble-2",
            target_pid=123,
            observed_at=10.3,
        )
    )

    result = MessageSourceChain([unavailable, trusted, unused]).read(intent)

    assert result.content == "测试\n完成"
    assert len(unavailable.calls) == 1
    assert len(trusted.calls) == 1
    assert unused.calls == []


@pytest.mark.parametrize(
    ("result", "reason"),
    [
        (
            SourceResult.success(
                "   ",
                "kim_postsend_ocr",
                "bubble-empty",
                target_pid=123,
                observed_at=10.2,
            ),
            "empty_content",
        ),
        (
            SourceResult.success(
                "x" * (MAX_TRUSTED_SUBMISSION_CHARS + 1),
                "kim_postsend_ocr",
                "bubble-long",
                target_pid=123,
                observed_at=10.2,
            ),
            "content_too_long",
        ),
        (
            SourceResult.success(
                "测试",
                "kim_postsend_ocr",
                "bubble-pid",
                target_pid=456,
                observed_at=10.2,
            ),
            "target_pid_mismatch",
        ),
        (
            SourceResult.success(
                "测试",
                "kim_postsend_ocr",
                "bubble-stale",
                target_pid=123,
                observed_at=9.9,
            ),
            "stale_observation",
        ),
    ],
)
def test_source_chain_rejects_untrusted_result(intent, result, reason):
    fallback = FakeSource(SourceResult.unavailable("fallback_unavailable"))

    outcome = MessageSourceChain([FakeSource(result), fallback]).read(intent)

    assert outcome.failure_reason == "fallback_unavailable"
    assert reason in outcome.diagnostics
    assert len(fallback.calls) == 1


def test_source_exception_is_named_and_next_source_runs(intent):
    fallback = FakeSource(
        SourceResult.success(
            "测试",
            "kim_postsend_ocr",
            "bubble-ok",
            target_pid=123,
            observed_at=10.2,
        )
    )

    result = MessageSourceChain(
        [FakeSource(RuntimeError("private candidate text")), fallback]
    ).read(intent)

    assert result.content == "测试"
    assert result.diagnostics == ("source_exception:FakeSource",)
    assert "private candidate text" not in repr(result)


class SequenceSource:
    def __init__(self, results):
        self.results = iter(results)
        self.calls = 0

    def read(self, intent):
        self.calls += 1
        return next(self.results, SourceResult.unavailable("capture_timeout"))


class FakeClock:
    def __init__(self, value=10.0):
        self.value = value
        self.waits = []

    def __call__(self):
        return self.value

    def wait(self, delay):
        self.waits.append(delay)
        self.value += delay
        return False


class ReleasableBaseline:
    def __init__(self):
        self.released = False

    def release(self):
        self.released = True


def _wait_until(predicate, timeout=1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("condition was not reached")


def _result(content, source, identity, observed_at, stability_key=None):
    return SourceResult.success(
        content,
        source,
        identity,
        target_pid=123,
        observed_at=observed_at,
        stability_key=stability_key,
    )


def test_coordinator_retries_at_relative_schedule_and_reports_timeout(intent):
    clock = FakeClock()
    diagnostics = []
    coordinator = PostSendCaptureCoordinator(
        MessageSourceChain([SequenceSource([])]),
        on_success=lambda outcome: None,
        on_diagnostic=diagnostics.append,
        clock=clock,
        wait=clock.wait,
    )

    try:
        assert coordinator.submit(intent)
        _wait_until(lambda: len(diagnostics) == 1)
    finally:
        coordinator.stop()

    assert clock.waits == pytest.approx([0.15, 0.2, 0.3, 0.35, 0.5, 0.5])
    assert diagnostics[0].failure_reason == "capture_timeout"


def test_coordinator_structured_result_completes_immediately(intent):
    clock = FakeClock()
    completed = []
    source = SequenceSource(
        [_result("最终文本", "kim_postsend_ax", "ax-message-1", 10.15)]
    )
    coordinator = PostSendCaptureCoordinator(
        MessageSourceChain([source]),
        on_success=completed.append,
        on_diagnostic=lambda outcome: None,
        clock=clock,
        wait=clock.wait,
    )

    try:
        assert coordinator.submit(intent)
        _wait_until(lambda: len(completed) == 1)
    finally:
        coordinator.stop()

    assert completed == [
        CaptureOutcome(
            intent_id="send-1",
            content="最终文本",
            source="kim_postsend_ax",
            message_identity="ax-message-1",
            failure_reason=None,
        )
    ]
    assert source.calls == 1
    assert clock.waits == pytest.approx([0.15])


def test_coordinator_requires_two_identical_ocr_results(intent):
    clock = FakeClock()
    completed = []
    source = SequenceSource(
        [
            _result("草稿", "kim_postsend_ocr", "bubble-1", 10.15),
            _result(
                "最终文本", "kim_postsend_ocr", "bubble-2", 10.35, "bounds-b"
            ),
            _result(
                "最终文本", "kim_postsend_ocr", "bubble-3", 10.65, "bounds-b"
            ),
        ]
    )
    coordinator = PostSendCaptureCoordinator(
        MessageSourceChain([source]),
        on_success=completed.append,
        on_diagnostic=lambda outcome: None,
        clock=clock,
        wait=clock.wait,
    )

    try:
        assert coordinator.submit(intent)
        _wait_until(lambda: len(completed) == 1)
    finally:
        coordinator.stop()

    assert completed[0].content == "最终文本"
    assert completed[0].message_identity == "bubble-3"
    assert source.calls == 3


def test_coordinator_ocr_requires_stable_geometry_as_well_as_text(intent):
    clock = FakeClock()
    completed = []
    source = SequenceSource(
        [
            _result("相同", "kim_postsend_ocr", "bubble-1", 10.15, "bounds-a"),
            _result("相同", "kim_postsend_ocr", "bubble-2", 10.35, "bounds-b"),
            _result("相同", "kim_postsend_ocr", "bubble-3", 10.65, "bounds-b"),
        ]
    )
    coordinator = PostSendCaptureCoordinator(
        MessageSourceChain([source]),
        on_success=completed.append,
        on_diagnostic=lambda outcome: None,
        clock=clock,
        wait=clock.wait,
    )

    try:
        assert coordinator.submit(intent)
        _wait_until(lambda: len(completed) == 1)
    finally:
        coordinator.stop()

    assert source.calls == 3
    assert completed[0].message_identity == "bubble-3"


def test_coordinator_rejects_expired_task_without_reading_source(intent):
    clock = FakeClock(20.0)
    diagnostics = []
    source = SequenceSource(
        [_result("wrong", "kim_postsend_ax", "message-late", 20.0)]
    )
    coordinator = PostSendCaptureCoordinator(
        MessageSourceChain([source]),
        on_success=lambda outcome: None,
        on_diagnostic=diagnostics.append,
        clock=clock,
        wait=clock.wait,
    )

    try:
        assert coordinator.submit(intent)
        _wait_until(lambda: len(diagnostics) == 1)
    finally:
        coordinator.stop()

    assert source.calls == 0
    assert diagnostics[0].failure_reason == "capture_expired"


def test_coordinator_rejects_result_that_finishes_after_deadline(intent):
    clock = FakeClock(11.9)
    diagnostics = []

    class SlowSource:
        def read(self, current):
            clock.value = 12.1
            return _result("wrong", "kim_postsend_ax", "message-late", 12.1)

    coordinator = PostSendCaptureCoordinator(
        MessageSourceChain([SlowSource()]),
        on_success=lambda outcome: None,
        on_diagnostic=diagnostics.append,
        clock=clock,
        wait=clock.wait,
    )

    try:
        assert coordinator.submit(intent)
        _wait_until(lambda: len(diagnostics) == 1)
    finally:
        coordinator.stop()

    assert diagnostics[0].failure_reason == "capture_expired"


def test_coordinator_preserves_submit_order_for_one_pid(intent):
    clock = FakeClock()
    completed = []

    class PerIntentSource:
        def read(self, current):
            return SourceResult.success(
                current.intent_id,
                "kim_postsend_ax",
                f"message:{current.intent_id}",
                target_pid=current.target_pid,
                observed_at=clock(),
            )

    second = SendIntent(**{**intent.__dict__, "intent_id": "send-2"})
    coordinator = PostSendCaptureCoordinator(
        MessageSourceChain([PerIntentSource()]),
        on_success=completed.append,
        on_diagnostic=lambda outcome: None,
        clock=clock,
        wait=clock.wait,
    )

    try:
        assert coordinator.submit(intent)
        assert coordinator.submit(second)
        _wait_until(lambda: len(completed) == 2)
    finally:
        coordinator.stop()

    assert [outcome.intent_id for outcome in completed] == ["send-1", "send-2"]


def test_coordinator_queue_full_is_non_blocking_and_named(intent):
    entered = threading.Event()
    release = threading.Event()
    diagnostics = []

    class BlockingSource:
        def read(self, current):
            entered.set()
            release.wait(1)
            return SourceResult.unavailable("blocked")

    coordinator = PostSendCaptureCoordinator(
        MessageSourceChain([BlockingSource()]),
        on_success=lambda outcome: None,
        on_diagnostic=diagnostics.append,
        max_queue_size=1,
        retry_delays=(0.0,),
    )
    submitted_at = time.monotonic()
    first = SendIntent(**{**intent.__dict__, "submitted_at": submitted_at})
    second = SendIntent(
        **{**intent.__dict__, "intent_id": "send-2", "submitted_at": submitted_at}
    )
    third = SendIntent(
        **{**intent.__dict__, "intent_id": "send-3", "submitted_at": submitted_at}
    )

    try:
        assert coordinator.submit(first)
        assert entered.wait(1)
        assert coordinator.submit(second)
        started = time.monotonic()
        assert not coordinator.submit(third)
        assert time.monotonic() - started < 0.05
        release.set()
        _wait_until(
            lambda: any(
                outcome.failure_reason == "post_send_queue_full"
                for outcome in diagnostics
            )
        )
    finally:
        release.set()
        coordinator.stop()


def test_coordinator_stop_rejects_new_tasks_and_releases_baselines(intent):
    baseline = ReleasableBaseline()
    with_baseline = SendIntent(**{**intent.__dict__, "baseline": baseline})
    coordinator = PostSendCaptureCoordinator(
        MessageSourceChain([SequenceSource([])]),
        on_success=lambda outcome: None,
        on_diagnostic=lambda outcome: None,
        retry_delays=(0.0,),
    )

    assert coordinator.submit(with_baseline)
    coordinator.stop()

    assert baseline.released
    assert not coordinator.submit(intent)


def test_coordinator_source_exception_does_not_kill_worker(intent):
    completed = []

    class SometimesBrokenSource:
        def read(self, current):
            if current.intent_id == "send-1":
                raise RuntimeError("boom")
            return SourceResult.success(
                "ok",
                "kim_postsend_ax",
                "message-ok",
                target_pid=current.target_pid,
                observed_at=time.monotonic(),
            )

    current_time = time.monotonic()
    first = SendIntent(**{**intent.__dict__, "submitted_at": current_time})
    second = SendIntent(
        **{**intent.__dict__, "intent_id": "send-2", "submitted_at": current_time}
    )
    coordinator = PostSendCaptureCoordinator(
        MessageSourceChain([SometimesBrokenSource()]),
        on_success=completed.append,
        on_diagnostic=lambda outcome: None,
        retry_delays=(0.0,),
    )

    try:
        assert coordinator.submit(first)
        assert coordinator.submit(second)
        _wait_until(lambda: len(completed) == 1)
    finally:
        coordinator.stop()

    assert completed[0].intent_id == "send-2"
    assert coordinator.worker_alive is False


def test_coordinator_queue_full_does_not_run_callback_on_submitter(intent):
    entered = threading.Event()
    release_source = threading.Event()
    release_diagnostic = threading.Event()

    class BlockingSource:
        def read(self, current):
            entered.set()
            release_source.wait(1)
            return SourceResult.unavailable("blocked")

    def slow_diagnostic(outcome):
        if outcome.failure_reason == "post_send_queue_full":
            release_diagnostic.wait(1)

    coordinator = PostSendCaptureCoordinator(
        MessageSourceChain([BlockingSource()]),
        on_success=lambda outcome: None,
        on_diagnostic=slow_diagnostic,
        max_queue_size=1,
        retry_delays=(0.0,),
    )
    submitted_at = time.monotonic()
    first = SendIntent(**{**intent.__dict__, "submitted_at": submitted_at})
    second = SendIntent(
        **{**intent.__dict__, "intent_id": "send-2", "submitted_at": submitted_at}
    )
    third = SendIntent(
        **{**intent.__dict__, "intent_id": "send-3", "submitted_at": submitted_at}
    )

    try:
        assert coordinator.submit(first)
        assert entered.wait(1)
        assert coordinator.submit(second)
        started = time.monotonic()
        assert not coordinator.submit(third)
        assert time.monotonic() - started < 0.05
    finally:
        release_source.set()
        release_diagnostic.set()
        coordinator.stop()


def test_coordinator_drops_worker_reference_to_finished_baseline(intent):
    class MemoryImage:
        pass

    baseline = MemoryImage()
    baseline_ref = weakref.ref(baseline)
    with_baseline = SendIntent(**{**intent.__dict__, "baseline": baseline})
    diagnostics = []
    coordinator = PostSendCaptureCoordinator(
        MessageSourceChain([SequenceSource([])]),
        on_success=lambda outcome: None,
        on_diagnostic=diagnostics.append,
        retry_delays=(0.0,),
    )

    try:
        assert coordinator.submit(with_baseline)
        _wait_until(lambda: len(diagnostics) == 1)
        del with_baseline
        del baseline
        gc.collect()
        assert baseline_ref() is None
    finally:
        coordinator.stop()


def test_coordinator_stop_releases_queued_baseline_and_eventually_current(intent):
    entered = threading.Event()
    release_source = threading.Event()

    class BlockingSource:
        def read(self, current):
            entered.set()
            release_source.wait(1)
            return SourceResult.unavailable("blocked")

    current_baseline = ReleasableBaseline()
    queued_baseline = ReleasableBaseline()
    submitted_at = time.monotonic()
    current = SendIntent(
        **{
            **intent.__dict__,
            "submitted_at": submitted_at,
            "baseline": current_baseline,
        }
    )
    queued = SendIntent(
        **{
            **intent.__dict__,
            "intent_id": "send-queued",
            "submitted_at": submitted_at,
            "baseline": queued_baseline,
        }
    )
    coordinator = PostSendCaptureCoordinator(
        MessageSourceChain([BlockingSource()]),
        on_success=lambda outcome: None,
        on_diagnostic=lambda outcome: None,
        retry_delays=(0.0,),
    )

    assert coordinator.submit(current)
    assert entered.wait(1)
    assert coordinator.submit(queued)
    coordinator.stop(timeout=0.02)
    assert queued_baseline.released

    release_source.set()
    _wait_until(lambda: not coordinator.worker_alive)
    assert current_baseline.released


def test_coordinator_coalesces_queue_full_diagnostics(intent):
    entered = threading.Event()
    release_source = threading.Event()
    diagnostics = []

    class BlockingSource:
        def read(self, current):
            entered.set()
            release_source.wait(1)
            return SourceResult.unavailable("blocked")

    submitted_at = time.monotonic()
    first = SendIntent(**{**intent.__dict__, "submitted_at": submitted_at})
    queued = SendIntent(
        **{**intent.__dict__, "intent_id": "queued", "submitted_at": submitted_at}
    )
    coordinator = PostSendCaptureCoordinator(
        MessageSourceChain([BlockingSource()]),
        on_success=lambda outcome: None,
        on_diagnostic=diagnostics.append,
        max_queue_size=1,
        retry_delays=(0.0,),
    )

    try:
        assert coordinator.submit(first)
        assert entered.wait(1)
        assert coordinator.submit(queued)
        for index in range(1000):
            rejected = SendIntent(
                **{
                    **intent.__dict__,
                    "intent_id": f"rejected-{index}",
                    "submitted_at": submitted_at,
                }
            )
            assert not coordinator.submit(rejected)
        release_source.set()
        _wait_until(
            lambda: any(
                outcome.failure_reason == "post_send_queue_full"
                for outcome in diagnostics
            )
        )
    finally:
        release_source.set()
        coordinator.stop()

    assert sum(
        outcome.failure_reason == "post_send_queue_full"
        for outcome in diagnostics
    ) == 1


def test_coordinator_times_out_hung_source_and_releases_baseline(intent):
    entered = threading.Event()
    never_release = threading.Event()
    diagnostics = []
    baseline = ReleasableBaseline()
    submitted_at = time.monotonic()
    current = SendIntent(
        **{
            **intent.__dict__,
            "submitted_at": submitted_at,
            "baseline": baseline,
        }
    )

    class HungSource:
        def read(self, current_intent):
            entered.set()
            never_release.wait()
            raise AssertionError("unreachable")

    coordinator = PostSendCaptureCoordinator(
        MessageSourceChain([HungSource()]),
        on_success=lambda outcome: None,
        on_diagnostic=diagnostics.append,
        retry_delays=(0.0,),
        source_timeout=0.02,
    )

    assert coordinator.submit(current)
    assert entered.wait(1)
    _wait_until(lambda: baseline.released)
    coordinator.stop(timeout=0.1)
    _wait_until(lambda: not coordinator.worker_alive)

    assert any(
        outcome.failure_reason == "source_read_timeout"
        for outcome in diagnostics
    )
