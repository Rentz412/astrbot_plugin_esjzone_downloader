const state = {
  token: localStorage.getItem("esjzone_dashboard_token") || "",
};

function el(id) {
  return document.getElementById(id);
}

function renderStatus(text, error = false) {
  const node = el("status");
  node.textContent = text;
  node.className = error ? "status error" : "status";
}

function renderBooks(books) {
  const root = el("books");
  if (!books.length) {
    root.innerHTML = "<p>暂无本地书籍。</p>";
    return;
  }
  root.innerHTML = books.map((book) => `
    <article class="book-card">
      <h2>${book.title || book.book_id}</h2>
      <p>作者：${book.author || "未知"}</p>
      <p>ID：${book.book_id}</p>
      <p>章节数：${book.chapter_count || 0}</p>
      <p>最新章节：${book.latest_chapter_title || ""}</p>
      <p>格式：${(book.downloaded_formats || []).join(", ")}</p>
      <p>ZIP：${book.package_path || ""}</p>
    </article>
  `).join("");
}

async function loadBooks() {
  try {
    const bridge = window.AstrBotPluginPage;
    await bridge.ready();
    const result = await bridge.apiGet("books", {
      headers: { "X-ESJ-Token": state.token },
    });
    if (!result.ok) {
      renderStatus(result.error || "加载失败", true);
      renderBooks([]);
      return;
    }
    renderStatus("加载完成");
    renderBooks(result.books || []);
  } catch (err) {
    renderStatus(`加载失败：${err.message}`, true);
  }
}

window.addEventListener("DOMContentLoaded", () => {
  el("token").value = state.token;
  el("saveToken").addEventListener("click", () => {
    state.token = el("token").value.trim();
    localStorage.setItem("esjzone_dashboard_token", state.token);
    renderStatus("Token 已保存");
  });
  el("refresh").addEventListener("click", loadBooks);
  loadBooks();
});
