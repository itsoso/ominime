from pathlib import Path


TEMPLATE = Path("src/ominime/web/templates/index.html")


def test_dashboard_initializes_today_from_status_endpoint():
    html = TEMPLATE.read_text(encoding="utf-8")

    assert "initializeDashboard" in html
    assert "fetch('/api/status')" in html
    assert "serverTodayDate = status.today_date" in html


def test_dashboard_auto_refreshes_when_viewing_today():
    html = TEMPLATE.read_text(encoding="utf-8")

    assert "setInterval(refreshTodayView" in html
    assert "datePicker.value === today" in html
    assert "datePicker.value === previousTodayDate" in html


def test_dashboard_overview_uses_lightweight_stats_endpoints():
    html = TEMPLATE.read_text(encoding="utf-8")

    assert "buildOverviewFromAppStats" in html
    assert "fetch(`/api/stats/apps?target_date=${dateStr}`)" in html


def test_dashboard_escapes_dynamic_app_and_work_path_labels():
    html = TEMPLATE.read_text(encoding="utf-8")

    assert "${escapeHtml(app.display_name)}" in html
    assert "${escapeHtml(workPath.work_pattern)}" in html
    assert "${escapeHtml(p.app)}" in html


def test_dashboard_does_not_contact_google_fonts():
    html = TEMPLATE.read_text(encoding="utf-8")

    assert "fonts.googleapis.com" not in html
    assert "fonts.gstatic.com" not in html


def test_dashboard_has_no_qwen_multimodal_panel():
    html = TEMPLATE.read_text(encoding="utf-8")

    assert "Qwen 多模态识别" not in html
    assert "qwen_analysis" not in html
    assert "qwen_model" not in html


def test_dashboard_explains_remote_ai_data_transfer():
    html = TEMPLATE.read_text(encoding="utf-8")

    assert "显式启用远程 AI" in html
    assert "分析内容会发送" in html


def test_dashboard_does_not_present_an_efficiency_score():
    html = TEMPLATE.read_text(encoding="utf-8")

    assert "效率分数" not in html
    assert "workPath.efficiency_score" not in html
