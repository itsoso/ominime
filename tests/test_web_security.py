from datetime import date
from types import SimpleNamespace

from fastapi.testclient import TestClient

from ominime.analyzer import DailyReport, WorkPathAnalysis
from ominime.web import api as web_api


def test_rejects_cross_site_origin():
    response = TestClient(web_api.app).get(
        "/api/health",
        headers={"Origin": "https://evil.example"},
    )

    assert response.status_code == 403


def test_rejects_non_local_host():
    response = TestClient(web_api.app).get(
        "/api/health",
        headers={"Host": "evil.example"},
    )

    assert response.status_code == 403


def test_allows_same_origin_test_client_request(monkeypatch):
    monkeypatch.setattr(
        web_api,
        "_build_health_payload",
        lambda: {"status": "running"},
    )

    response = TestClient(web_api.app).get(
        "/api/health",
        headers={"Origin": "http://testserver"},
    )

    assert response.status_code == 200


def test_today_full_report_is_not_captured_by_date_route(monkeypatch):
    empty_report = DailyReport(
        date=date(2026, 8, 11),
        total_chars=0,
        total_apps=0,
        total_sessions=0,
        total_time_minutes=0,
        app_stats=[],
        main_activities=[],
        summary="",
        suggestions=[],
        work_path=WorkPathAnalysis(
            segments=[],
            total_segments=1,
            app_switches=0,
            peak_hours=[],
            focus_periods=[],
            work_pattern="混合型",
        ),
    )
    monkeypatch.setattr(
        web_api,
        "get_analyzer",
        lambda: SimpleNamespace(generate_full_report=lambda _date: empty_report),
    )
    monkeypatch.setattr(web_api, "business_today", lambda: date(2026, 8, 11))

    response = TestClient(web_api.app).get("/api/report/full")

    assert response.status_code == 200
    assert response.json()["overview"]["date"] == "2026-08-11"
    assert "efficiency_score" not in response.json()["work_path"]
