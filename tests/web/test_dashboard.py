from fastapi.testclient import TestClient
from zhaoxi.web.app import create_app
from dashboard_fixture import dashboard_core

def test_browser_dashboard_bootstraps_local_session_without_desktop(tmp_path):
    core,s=dashboard_core(tmp_path);s.dev_browser_ui=False
    opened=[]
    with TestClient(create_app(agent=core,settings=s,api_token="secret",desktop_open_callback=lambda:opened.append(True)),
                    base_url="http://127.0.0.1",client=("127.0.0.1",50000)) as client:
        assert client.get("/api/dashboard/overview").status_code==401
        assert client.get("/static/engineering.html").status_code==403
        response=client.get("/")
        assert response.status_code==200 and response.url.path=="/dashboard"
        assert 'id="messages"' not in response.text
        assert 'dashboard-desktop.js' not in response.text
        assert "secret" not in response.text
        assert "HttpOnly" in response.headers["set-cookie"]
        assert "zhaoxi_session" not in client.cookies
        overview=client.get("/api/dashboard/overview").json()
        assert overview["presence"]["current_presence"] and overview["core"]["healthy"]
        assert client.get("/static/engineering.html").status_code==200
        assert client.get("/static/index.html").status_code==403
        assert client.put("/api/settings/presence",json={"heartbeat_interval_seconds":30}).status_code==200
        assert client.post("/api/dashboard/open-desktop").json()=={"opened":True}
        assert opened==[True]
        for headers in ({"origin":"https://external.test"},{"origin":"http://127.0.0.1:9999"},{"sec-fetch-site":"cross-site"}):
            assert client.put("/api/settings/presence",json={"heartbeat_interval_seconds":20},headers=headers).status_code==401
            assert client.get("/dashboard",headers=headers).status_code==403
        assert client.get("/api/settings/presence").json()["values"]["heartbeat_interval_seconds"]==30
        assert client.get("/api/dashboard/overview",headers={"host":"external.test"}).status_code==401
        assert client.get("/dashboard",headers={"host":"external.test"}).status_code==403
        client.get("/desktop-entry?token=secret")
        assert 'id="messages"' in client.get("/").text


def test_dashboard_rejects_remote_peer(tmp_path):
    core,s=dashboard_core(tmp_path)
    with TestClient(create_app(agent=core,settings=s,api_token="secret"),base_url="http://127.0.0.1",client=("203.0.113.5",50000)) as client:
        assert client.get("/dashboard").status_code==403
        assert "zhaoxi_dashboard_session" not in client.cookies


def test_api_controls_receipts_and_manual_editor(tmp_path):
    core,s=dashboard_core(tmp_path)
    with TestClient(create_app(agent=core,settings=s)) as client:
        assert client.put("/api/settings/presence",json={"active_hold_seconds":10,"semi_active_hold_seconds":20,"heartbeat_interval_seconds":5}).status_code==200
        assert client.get("/api/settings/presence").json()["values"]["heartbeat_interval_seconds"]==5
        for invalid in ({"heartbeat_interval_seconds":0},{"unknown":10}):assert client.put("/api/settings/presence",json=invalid).status_code==422
        assert client.post("/api/debug/presence/override",json={"enabled":True}).json()["debug_override"]
        assert client.post("/api/debug/presence/override",json={"enabled":False}).json()["debug_override"] is None
        # Restore IDLE so registry policies permit the local gardening action.
        client.post("/api/debug/presence",json={"state":"IDLE"})
        receipt=client.post("/api/internal-activity/cognition_gardening/run",json={}).json()["receipt"]
        assert receipt["status"]=="NO_CHANGE" and receipt["summary"]
        assert client.get("/api/internal-activity/history?limit=1").json()["items"][0]["action_id"]==receipt["action_id"]
        assert client.get("/api/internal-activity/history?limit=9999").status_code==422
        assert client.post("/api/internal-activity/unknown/run",json={}).status_code==404
        added=client.post("/api/current-cognition/thread",json={"key":"test","title":"日语学习","summary":"学日语","manual_state":"LOCKED"}).json()
        assert added["state"]["threads"][0]["source"]=="OWNER_MANUAL"
        revision=client.get("/api/current-cognition/revisions").json()["items"][0]
        assert revision["actor"]=="owner"
        assert client.post('/api/current-cognition/revisions/'+str(revision["revision_id"])+"/undo",json={}).json()["threads"]==[]
        assert client.post('/api/current-cognition/revisions/'+str(revision["revision_id"])+"/undo",json={}).status_code==409
        assert client.get("/api/current-cognition/revisions?offset=-1").status_code==422
        before=client.get("/api/dashboard/overview").json()["today"]["activities"]
        core.internal_activity.record_daily("social_write")
        assert client.get("/api/dashboard/overview").json()["today"]["activities"]==before
