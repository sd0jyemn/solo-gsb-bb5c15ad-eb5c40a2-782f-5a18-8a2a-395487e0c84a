"""FastAPI 端到端测试（临时 SQLite，随 TestClient 启动自动建表）。"""

from datetime import date, timezone, datetime

from fastapi.testclient import TestClient

from app.main import app


def _today_serials(offset_nn: int) -> int:
    return int(date.today().strftime("%Y%m%d")) * 100 + offset_nn


def test_healthz():
    with TestClient(app) as client:
        resp = client.get("/healthz")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


def test_create_audit_and_fetch_by_id():
    with TestClient(app) as client:
        payload = {
            "zone": "Example.ORG.",
            "serials": [
                _today_serials(10),
                _today_serials(12),
                _today_serials(12),
            ],
        }
        resp = client.post("/audits", json=payload)
        assert resp.status_code == 201, resp.text
        body = resp.json()

        assert body["id"] > 0
        assert body["zone"] == "example.org"
        assert body["reference"] == "RFC 1982"

        states = [item["state"] for item in body["serials"]]
        assert states == [None, "forward", "equal"]
        assert body["summary"]["forward"] == 1
        assert body["summary"]["equal"] == 1
        assert body["summary"]["reject_risk_count"] == 0

        assert body["suggestion"]["valid_forward"] is True
        assert body["suggestion"]["next_serial"] == _today_serials(13)

        # created_at 为合法 ISO 时间戳
        datetime.fromisoformat(body["created_at"]).astimezone(timezone.utc)

        # 按 ID 回查
        fetched = client.get(f"/audits/{body['id']}")
        assert fetched.status_code == 200
        assert fetched.json()["id"] == body["id"]
        assert fetched.json()["serials"] == body["serials"]


def test_backward_and_incomparable_flagged():
    with TestClient(app) as client:
        half = 1 << 31
        payload = {
            "zone": "example.com",
            "serials": [
                _today_serials(5),
                _today_serials(3),  # 倒退
                (_today_serials(3) + half),  # 不可比较
            ],
        }
        resp = client.post("/audits", json=payload)
        assert resp.status_code == 201, resp.text
        body = resp.json()

        assert body["serials"][1]["state"] == "backward"
        assert body["serials"][1]["reject_risk"] is True
        assert body["serials"][2]["state"] == "incomparable"
        assert body["serials"][2]["reject_risk"] is True
        assert body["summary"]["reject_risk_count"] == 2


def test_409_daily_exhausted_still_persisted():
    with TestClient(app) as client:
        payload = {"zone": "exhausted.example", "serials": [_today_serials(99)]}
        resp = client.post("/audits", json=payload)
        assert resp.status_code == 409, resp.text
        body = resp.json()
        assert body["suggestion"]["valid_forward"] is False
        assert body["suggestion"]["error"]["code"] == "DAILY_SEQUENCE_EXHAUSTED"
        assert body["suggestion"]["next_serial"] is None

        # 409 的记录同样落库，可按 ID 查询
        fetched = client.get(f"/audits/{body['id']}")
        assert fetched.status_code == 200
        assert fetched.json()["suggestion"]["error"]["code"] == "DAILY_SEQUENCE_EXHAUSTED"


def test_get_unknown_audit_404():
    with TestClient(app) as client:
        resp = client.get("/audits/99999999")
        assert resp.status_code == 404


def test_invalid_zone_422():
    with TestClient(app) as client:
        resp = client.post(
            "/audits",
            json={"zone": "not_a_zone!!", "serials": [1]},
        )
        assert resp.status_code == 422


def test_serial_out_of_range_422():
    with TestClient(app) as client:
        resp = client.post(
            "/audits",
            json={"zone": "example.org", "serials": [0x1_0000_0000]},
        )
        assert resp.status_code == 422


def test_empty_serials_422():
    with TestClient(app) as client:
        resp = client.post("/audits", json={"zone": "example.org", "serials": []})
        assert resp.status_code == 422
