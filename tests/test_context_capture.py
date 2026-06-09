from ominime.context_capture import AXFrame, CapturedContext, choose_screenshot_scope


def test_choose_container_scope_before_window_scope():
    context = CapturedContext(
        focused_frame=AXFrame(10, 500, 600, 40),
        container_frame=AXFrame(0, 80, 900, 700),
        window_frame=AXFrame(0, 0, 1000, 800),
    )
    scope = choose_screenshot_scope(context)
    assert scope.scope == "container"
    assert scope.frame == AXFrame(0, 80, 900, 700)


def test_choose_window_scope_when_container_missing():
    context = CapturedContext(
        focused_frame=AXFrame(10, 500, 600, 40),
        window_frame=AXFrame(0, 0, 1000, 800),
    )
    scope = choose_screenshot_scope(context)
    assert scope.scope == "window"
    assert scope.frame == AXFrame(0, 0, 1000, 800)
