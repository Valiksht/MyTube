from fastapi.testclient import TestClient

from app.main import create_app


def test_screens_are_served() -> None:
    client = TestClient(create_app())
    expected = {
        "/": "Главная",
        "/watch": "<video",
        "/channel": "Канал",
        "/search": "Поиск",
        "/upload": 'id="upload-progress"',
        "/login": "Войти",
    }
    for path, needle in expected.items():
        response = client.get(path)
        assert response.status_code == 200
        assert needle in response.text
        assert "/static/api.js" in response.text

    script = client.get("/static/api.js")
    assert script.status_code == 200
    assert "fetch(" in script.text

    upload = client.get("/upload")
    assert 'value="public"' in upload.text
    assert 'value="private"' in upload.text
    assert 'request.upload.addEventListener("progress"' in upload.text
