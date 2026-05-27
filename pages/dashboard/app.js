const bridge = window.AstrBotPluginPage;
const tokenInput = document.getElementById("token");
const saveTokenButton = document.getElementById("save-token");
const refreshButton = document.getElementById("refresh");
const statusBox = document.getElementById("status");
const booksBox = document.getElementById("books");

await bridge.ready();

const savedToken = localStorage.getItem("esjzone_dashboard_token") || "";
tokenInput.value = savedToken;

function setStatus(message) {
  statusBox.textContent = message;
}

function tokenParams() {
  const token = tokenInput.value.trim();
  return token ? { token } : {};
}

saveTokenButton.addEventListener("click", () => {
  localStorage.setItem("esjzone_dashboard_token", tokenInput.value.trim());
  setStatus("Token 已保存到当前浏览器。");
});

refreshButton.addEventListener("click", () => {
  loadBooks();
});

async function loadBooks() {
  booksBox.innerHTML = "";
  setStatus("正在加载...");
  try {
    const data = await bridge.apiGet("books", tokenParams());
    const books = data.books || [];
    if (!books.length) {
      booksBox.innerHTML = "<p>暂无本地书籍。</p>";
    } else {
      for (const book of books) {
        const card = document.createElement("article");
        card.className = "book-card";

        const title = document.createElement("h3");
        title.textContent = book.title || book.book_id || "未命名书籍";
        card.appendChild(title);

        card.appendChild(makeLine("编号", book.book_id || ""));
        card.appendChild(makeLine("作者", book.author || "未知"));
        card.appendChild(makeLine("章节数", book.chapter_count || 0));
        card.appendChild(makeLine("最新章节", book.latest_chapter_title || ""));
        card.appendChild(makeLine("格式", (book.downloaded_formats || []).join(", ")));
        card.appendChild(makeLine("包路径", book.package_path || ""));

        booksBox.appendChild(card);
      }
    }
    setStatus("加载完成。");
  } catch (error) {
    setStatus(`加载失败：${error.message || error}`);
  }
}

function makeLine(label, value) {
  const p = document.createElement("p");
  p.textContent = `${label}：${value}`;
  return p;
}

loadBooks();
