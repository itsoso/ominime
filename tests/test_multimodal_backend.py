from ominime.multimodal_backend import (
    MultimodalAnalysisRequest,
    parse_json_response,
    build_qwen_vl_messages,
)


def test_build_qwen_vl_messages_includes_text_metadata_and_image():
    messages = build_qwen_vl_messages(
        submitted_text="帮我修改这里",
        screenshot_path="/tmp/dialog.png",
        metadata={"app_name": "Codex", "window_title": "OmniMe"},
    )
    user_content = messages[1]["content"]
    assert any(part.get("type") == "image" for part in user_content)
    assert any("帮我修改这里" in part.get("text", "") for part in user_content)
    assert any("Codex" in part.get("text", "") for part in user_content)


def test_build_qwen_vl_messages_supports_text_only():
    messages = build_qwen_vl_messages(
        submitted_text="没有截图",
        screenshot_path=None,
        metadata={"app_name": "Codex"},
    )
    user_content = messages[1]["content"]
    assert not any(part.get("type") == "image" for part in user_content)
    assert any("没有截图" in part.get("text", "") for part in user_content)


def test_parse_json_response_handles_fenced_json():
    parsed = parse_json_response('```json\n{"context_type":"chat","confidence":0.8}\n```')
    assert parsed["context_type"] == "chat"
    assert parsed["confidence"] == 0.8


def test_request_defaults_metadata_to_dict():
    req = MultimodalAnalysisRequest(submitted_text="x", screenshot_path=None)
    assert req.metadata == {}
