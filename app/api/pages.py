from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(include_in_schema=False)
STATIC_DIR = Path(__file__).resolve().parents[1] / "static"

_PAGES = {
    "/": "index.html",
    "/watch": "watch.html",
    "/channel": "channel.html",
    "/search": "search.html",
    "/upload": "upload.html",
    "/login": "login.html",
}


def _page(name: str) -> HTMLResponse:
    return HTMLResponse((STATIC_DIR / name).read_text(encoding="utf-8"))


for _path, _filename in _PAGES.items():

    def _make_handler(filename: str):
        async def handler() -> HTMLResponse:
            return _page(filename)

        return handler

    router.add_api_route(_path, _make_handler(_filename), methods=["GET"], response_class=HTMLResponse)
