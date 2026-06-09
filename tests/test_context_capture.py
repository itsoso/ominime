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

from ominime.context_capture import select_container_node, frame_from_dict


def test_selects_nearest_large_parent_as_container():
    hierarchy = [
        {"role": "AXTextArea", "frame": {"x": 100, "y": 700, "width": 700, "height": 60}},
        {"role": "AXGroup", "frame": {"x": 80, "y": 100, "width": 760, "height": 660}},
        {"role": "AXWindow", "frame": {"x": 0, "y": 0, "width": 900, "height": 800}},
    ]
    assert select_container_node(hierarchy)["role"] == "AXGroup"


def test_select_container_falls_back_to_window():
    hierarchy = [
        {"role": "AXTextArea", "frame": {"x": 100, "y": 700, "width": 700, "height": 60}},
        {"role": "AXWindow", "frame": {"x": 0, "y": 0, "width": 900, "height": 800}},
    ]
    assert select_container_node(hierarchy)["role"] == "AXWindow"


def test_frame_from_dict_rejects_incomplete_frames():
    assert frame_from_dict({"x": 1, "y": 2}) is None
