from fastapi.testclient import TestClient
from zhaoxi.web.app import create_app
from zhaoxi.config.settings import Settings
from test_web import FakeAgent


def test_prod_browser_denied_desktop_cookie_allowed():
    with TestClient(create_app(agent=FakeAgent(),api_token='secret')) as client:
        for url in ['/', '/static/index.html', '/static//index.html', '/static/INDEX.HTML', '/static/index.html.']:
            assert client.get(url).status_code == 403
        assert client.get('/desktop-entry?token=wrong').status_code == 403
        response = client.get('/desktop-entry?token=secret')
        assert response.status_code == 200
        assert 'id="messages"' in response.text
        assert 'secret' not in response.text
        assert client.get('/api/session').status_code == 200


def test_dev_browser_explicit_opt_in():
    with TestClient(create_app(agent=FakeAgent(),settings=Settings(dev_browser_ui=True))) as client:
        assert client.get('/').status_code == 200
    with TestClient(create_app(agent=FakeAgent(),settings=Settings(dev_browser_ui=False))) as client:
        assert client.get('/').status_code == 403
