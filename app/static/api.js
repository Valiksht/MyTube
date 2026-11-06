const MyTube = (() => {
  const TOKEN_KEY = "mytube_access_token";

  function token() {
    return sessionStorage.getItem(TOKEN_KEY);
  }

  function setToken(value) {
    if (value) {
      sessionStorage.setItem(TOKEN_KEY, value);
    } else {
      sessionStorage.removeItem(TOKEN_KEY);
    }
  }

  async function api(path, options = {}) {
    const headers = new Headers(options.headers || {});
    const accessToken = token();
    if (accessToken) {
      headers.set("Authorization", "Bearer " + accessToken);
    }
    let body = options.body;
    if (Object.prototype.hasOwnProperty.call(options, "json")) {
      headers.set("Content-Type", "application/json");
      body = JSON.stringify(options.json);
    }
    const response = await fetch(path, {
      method: options.method || "GET",
      headers,
      body,
    });
    if (response.status === 401 && accessToken && !options.retried && (options.method || "GET") === "GET") {
      setToken("");
      mountHeader();
      return api(path, { ...options, retried: true });
    }
    if (response.status === 204) {
      return null;
    }
    const text = await response.text();
    let payload = null;
    if (text) {
      try {
        payload = JSON.parse(text);
      } catch (_error) {
        payload = { detail: "Сервер не ответил" };
      }
    }
    if (!response.ok) {
      const detail = payload && payload.detail;
      throw new Error(typeof detail === "string" ? detail : "Запрос не выполнен");
    }
    return payload;
  }

  function escapeHtml(value) {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  function videoCards(items) {
    if (!items.length) {
      return "<p>Ничего не найдено.</p>";
    }
    const cards = items.map((video) => {
      const when = new Date(video.created_at).toLocaleString("ru-RU");
      return `<li class="card">
        <a href="/watch?id=${encodeURIComponent(video.id)}"><h2>${escapeHtml(video.title)}</h2></a>
        <p>${escapeHtml(video.description || "")}</p>
        <p class="meta">${video.like_count} лайков · ${escapeHtml(when)}</p>
        <a href="/channel?id=${encodeURIComponent(video.channel_id)}">Канал</a>
      </li>`;
    });
    return `<ul class="cards">${cards.join("")}</ul>`;
  }

  function mountHeader() {
    const host = document.querySelector("#site-header");
    if (!host) {
      return;
    }
    const account = token()
      ? '<a href="/login" id="nav-logout">Выход</a>'
      : '<a href="/login">Вход</a>';
    host.innerHTML = `<a class="brand" href="/">MyTube</a>
      <nav>
        <a href="/">Главная</a>
        <a href="/search">Поиск</a>
        <a href="/upload">Загрузка</a>
        ${account}
      </nav>
      <form action="/search" method="get">
        <input name="q" type="search" placeholder="Название видео" aria-label="Поиск">
      </form>`;
    const logout = document.querySelector("#nav-logout");
    if (logout) {
      logout.addEventListener("click", (event) => {
        event.preventDefault();
        setToken("");
        location.href = "/login";
      });
    }
  }

  document.addEventListener("DOMContentLoaded", mountHeader);

  return { token, setToken, api, escapeHtml, videoCards, mountHeader };
})();
