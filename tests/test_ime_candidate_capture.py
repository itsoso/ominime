from ominime.ime_candidate_capture import (
    CandidateSnapshot,
    DoubaoCompositionState,
    Rect,
    candidate_is_in_composer,
)


def test_candidate_inside_lower_target_region_is_trusted():
    target = Rect(x=2000, y=100, width=1200, height=800)
    candidate = Rect(x=2500, y=760, width=400, height=64)

    assert candidate_is_in_composer(candidate, target)


def test_candidate_near_top_search_field_is_rejected():
    target = Rect(x=2000, y=100, width=1200, height=800)
    candidate = Rect(x=2500, y=180, width=400, height=64)

    assert not candidate_is_in_composer(candidate, target)


def test_candidate_outside_target_horizontally_is_rejected():
    target = Rect(x=2000, y=100, width=1200, height=800)
    candidate = Rect(x=3150, y=760, width=400, height=64)

    assert not candidate_is_in_composer(candidate, target)


def test_candidate_below_target_is_rejected():
    target = Rect(x=2000, y=100, width=1200, height=800)
    candidate = Rect(x=2500, y=900, width=400, height=64)

    assert not candidate_is_in_composer(candidate, target)


class FakeClock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def candidate_snapshot(clock, candidates=("测试", "策士", "侧室"), target_pid=123):
    return CandidateSnapshot(candidates, target_pid, clock())


def test_composition_space_commits_default_candidate_without_pinyin():
    clock = FakeClock()
    state = DoubaoCompositionState(timeout_seconds=30, clock=clock)
    for character in "ceshi":
        state.record_printable(character, target_pid=123)
    state.update_candidates(candidate_snapshot(clock), target_pid=123)

    result = state.handle_key(keycode=49, text=" ", target_pid=123)

    assert result.candidate_committed
    assert result.committed_text == "测试"
    assert state.pop_submission(target_pid=123) == "测试"


def test_composition_number_key_commits_matching_candidate():
    clock = FakeClock()
    state = DoubaoCompositionState(timeout_seconds=30, clock=clock)
    state.record_printable("c", target_pid=123)
    state.update_candidates(candidate_snapshot(clock), target_pid=123)

    result = state.handle_key(keycode=19, text="2", target_pid=123)

    assert result.candidate_committed
    assert result.committed_text == "策士"


def test_composition_arrow_keys_move_and_clamp_selection():
    clock = FakeClock()
    state = DoubaoCompositionState(timeout_seconds=30, clock=clock)
    state.update_candidates(candidate_snapshot(clock), target_pid=123)

    state.handle_key(keycode=123, text="", target_pid=123)
    assert state.selected_index == 0
    state.handle_key(keycode=124, text="", target_pid=123)
    state.handle_key(keycode=124, text="", target_pid=123)
    state.handle_key(keycode=124, text="", target_pid=123)

    assert state.selected_index == 2


def test_composition_enter_commits_candidate_before_next_enter_submits():
    clock = FakeClock()
    state = DoubaoCompositionState(timeout_seconds=30, clock=clock)
    state.record_printable("c", target_pid=123)
    state.update_candidates(candidate_snapshot(clock), target_pid=123)

    result = state.handle_key(keycode=36, text="", target_pid=123)

    assert result.candidate_committed
    assert state.has_active_candidate is False
    assert state.pop_submission(target_pid=123) == "测试"
    assert state.pop_submission(target_pid=123) == ""


def test_composition_backspace_edits_preedit_then_confirmed_text():
    clock = FakeClock()
    state = DoubaoCompositionState(timeout_seconds=30, clock=clock)
    state.record_printable("c", target_pid=123)
    state.record_printable("e", target_pid=123)

    state.handle_key(keycode=51, text="", target_pid=123)
    assert state.pending_preedit == "c"
    state.update_candidates(candidate_snapshot(clock), target_pid=123)
    state.handle_key(keycode=49, text=" ", target_pid=123)
    state.handle_key(keycode=51, text="", target_pid=123)

    assert state.confirmed_text == "测"


def test_composition_never_submits_unconfirmed_raw_pinyin():
    clock = FakeClock()
    state = DoubaoCompositionState(timeout_seconds=30, clock=clock)
    for character in "ceshi":
        state.record_printable(character, target_pid=123)

    assert state.pop_submission(target_pid=123) == ""


def test_composition_accepts_latin_only_after_trusted_candidate_session():
    clock = FakeClock()
    state = DoubaoCompositionState(timeout_seconds=30, clock=clock)
    state.record_printable("c", target_pid=123)
    state.update_candidates(candidate_snapshot(clock), target_pid=123)
    state.handle_key(keycode=49, text=" ", target_pid=123)
    state.record_printable("A", target_pid=123)

    state.update_candidates(None, target_pid=123)

    assert state.pop_submission(target_pid=123) == "测试A"


def test_composition_pid_change_discards_previous_content():
    clock = FakeClock()
    state = DoubaoCompositionState(timeout_seconds=30, clock=clock)
    state.update_candidates(candidate_snapshot(clock), target_pid=123)
    state.handle_key(keycode=49, text=" ", target_pid=123)

    state.record_printable("x", target_pid=456)

    assert state.pop_submission(target_pid=456) == ""


def test_composition_timeout_discards_sensitive_content():
    clock = FakeClock()
    state = DoubaoCompositionState(timeout_seconds=30, clock=clock)
    state.update_candidates(candidate_snapshot(clock), target_pid=123)
    state.handle_key(keycode=49, text=" ", target_pid=123)
    clock.now += 31

    assert state.pop_submission(target_pid=123) == ""
