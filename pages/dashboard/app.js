/**
 * ESJZone 下载器 Dashboard 前端入口。
 * 运行在 AstrBot Plugin Page 的 iframe 中，使用原生 JavaScript 与 AstrBotPluginPage bridge 通信。
 */

const bridge = window.AstrBotPluginPage;

/* ===== 页面状态 ===== */
let cache = null;
let currentBookId = null;
let pluginName = 'astrbot_plugin_esjzone_downloader';

/* ===== 常用 DOM 引用 ===== */
const $ = (sel) => document.querySelector(sel);
const libraryView = $('#libraryView');
const detailView = $('#detailView');
const summaryGrid = $('#summaryGrid');
const bookGrid = $('#bookGrid');
const searchInput = $('#searchInput');
const syncMeta = $('#syncMeta');
const detailContent = $('#detailContent');
const toastEl = $('#toast');
const confirmDialog = $('#confirmDialog');

/* ===== 初始化与事件绑定 ===== */
async function init() {
  await bridge.ready();
  const ctx = bridge.getContext();
  if (ctx && ctx.pluginName) pluginName = ctx.pluginName;
  bindEvents();
  await loadData();
}

function bindEvents() {
  $('#refreshBtn').addEventListener('click', handleRefresh);
  $('#clearAllFilesBtn').addEventListener('click', () => confirmAction(
    '清除所有书籍文件？',
    '这将删除所有本地小说导出的 TXT 和 EPUB 文件及其 manifest。\n章节缓存、封面、插图和书籍状态不会被删除。',
    () => apiAction('dashboard/books/clear-all-files', '已清除所有书籍文件')
  ));
  $('#deleteAllBooksBtn').addEventListener('click', () => confirmAction(
    '删除所有书籍数据？',
    '这将删除整个本地书库缓存，包括封面、章节、插图、状态、导出文件和打包文件。\n此操作不可恢复。',
    () => apiAction('dashboard/books/delete-all', '已删除所有书籍数据')
  ));
  $('#backBtn').addEventListener('click', showLibrary);
  searchInput.addEventListener('input', renderBooks);
  $('#cancelConfirmBtn').addEventListener('click', hideConfirm);
}

/* ===== 数据加载与后端操作 ===== */
async function loadData() {
  try {
    // dashboard/cache 返回后端扫描本地书库后生成的快照。
    cache = await bridge.apiGet('dashboard/cache');
    renderAll();
  } catch (e) {
    toast('加载数据失败：' + (e.message || e));
  }
}

async function handleRefresh() {
  const btn = $('#refreshBtn');
  // 防止用户连续点击刷新导致重复扫描本地数据目录。
  btn.disabled = true;
  try {
    cache = await bridge.apiPost('dashboard/refresh', {});
    renderAll();
    toast('同步完成');
  } catch (e) {
    toast('刷新失败：' + (e.message || e));
  } finally {
    btn.disabled = false;
  }
}

async function apiAction(endpoint, successMsg) {
  try {
    await bridge.apiPost(endpoint, {});
    cache = await bridge.apiGet('dashboard/cache');
    renderAll();
    if (currentBookId && !cache.books.find(b => b.book_id === currentBookId)) {
      showLibrary();
    }
    toast(successMsg);
  } catch (e) {
    toast('操作失败：' + (e.message || e));
  }
}

/* ===== 图片加载 ===== */
function buildImageUrl(endpoint) {
  // 仅用于可直接访问的静态图片（如插件 Logo）。书籍封面在 iframe 中走 bridge 鉴权读取。
  return `/api/plug/${pluginName}/${endpoint}`;
}

async function loadImage(imgEl, endpoint) {
  const url = buildImageUrl(endpoint);
  imgEl.onload = () => { imgEl.style.display = ''; };
  imgEl.onerror = () => { imgEl.style.display = 'none'; };
  imgEl.src = url;
}

/* ===== 页面渲染 ===== */
function renderAll() {
  if (!cache) return;
  renderPluginMeta();
  renderSummary();
  renderBooks();
  renderSyncTime();
  if (currentBookId) {
    const book = cache.books.find(b => b.book_id === currentBookId);
    if (book) renderDetail(book);
    else showLibrary();
  }
}

function renderPluginMeta() {
  const p = cache.plugin || {};
  $('#pluginName').textContent = p.display_name || 'ESJZone 小说下载器';
  $('#pluginVersion').textContent = p.version || '';
  $('#pluginAuthor').textContent = '作者：' + (p.author || '');
  const repoLink = $('#repoLink');
  const repoUrl = p.repo || '';
  repoLink.href = repoUrl || '#';
  repoLink.dataset.repo = repoUrl;
  // 插件 Logo 可以直接作为图片资源加载。
  const logo = $('#pluginLogo');
  loadImage(logo, p.logo_url || 'dashboard/logo');
}

function renderSummary() {
  const s = cache.summary || {};
  const cards = [
    { icon: 'icon-users', bg: '#dbeafe', value: s.logged_in_users ?? 0, label: '已登录用户' },
    { icon: 'icon-book-open', bg: '#d1fae5', value: s.local_books ?? 0, label: '本地小说' },
    { icon: 'icon-hard-drive', bg: '#e2e8f0', value: formatSize(s.data_dir_size || 0), label: '本地占用空间' },
    { icon: 'icon-bug', bg: '#fef3c7', value: s.debug_file_count ?? 0, label: '调试文件', action: true },
  ];
  summaryGrid.innerHTML = cards.map((c) => `
    <div class="stat-card">
      <div class="stat-icon" style="background:${c.bg}">
        <span class="icon ${c.icon}"></span>
      </div>
      <div class="stat-body">
        <div class="stat-value">${c.value}</div>
        <div class="stat-label">${c.label}</div>
        ${c.action ? `<button class="btn btn-success-soft stat-action" data-action="clear-debug"><span class="icon icon-trash-2"></span> 清理</button>` : ''}
      </div>
    </div>
  `).join('');

  const clearDebugBtn = summaryGrid.querySelector('[data-action="clear-debug"]');
  if (clearDebugBtn) {
    clearDebugBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      confirmAction(
        '清理调试文件？',
        '这将清空 debug/auth 和 debug/pages 目录中的所有文件。',
        () => apiAction('dashboard/debug/clear', '已清理调试文件')
      );
    });
  }
}

function renderBooks() {
  const books = cache.books || [];
  const query = (searchInput.value || '').trim().toLowerCase();
  const filtered = query
    ? books.filter(b =>
        b.title.toLowerCase().includes(query) ||
        b.author.toLowerCase().includes(query) ||
        b.book_id.toLowerCase().includes(query)
      )
    : books;

  if (filtered.length === 0) {
    bookGrid.innerHTML = `
      <div class="empty-state" style="grid-column:1/-1">
        <span class="icon icon-book-open"></span>
        <p>${query ? '没有匹配的书籍' : '暂无本地小说'}</p>
      </div>`;
    return;
  }

  bookGrid.innerHTML = filtered.map(b => {
    const badges = [];
    if (b.downloaded_formats.includes('epub')) badges.push('<span class="badge badge-epub">EPUB</span>');
    if (b.downloaded_formats.includes('txt')) badges.push('<span class="badge badge-txt">TXT</span>');
    if (b.status === 'warning') badges.push('<span class="badge badge-warning">异常</span>');
    else if (b.status === 'ready') badges.push('<span class="badge badge-ready"><span class="icon icon-circle-check-big"></span> 就绪</span>');
    else if (b.status === 'cached') badges.push('<span class="badge badge-cached">缓存</span>');

    return `
      <div class="book-card" data-book-id="${b.book_id}">
        <img class="book-card-cover" data-endpoint="${esc(b.cover_url)}" alt="" style="display:none" />
        <div class="book-card-cover-placeholder">
          <span class="icon icon-book-image"></span>
        </div>
        <div class="book-card-body">
          <div class="book-card-title">${esc(b.title)}</div>
          <div class="book-card-author">${esc(b.author)}</div>
          <div class="book-card-badges">${badges.join('')}</div>
        </div>
      </div>`;
  }).join('');

  // 渲染完成后再逐张加载封面，失败时保留占位图。
  bookGrid.querySelectorAll('.book-card-cover[data-endpoint]').forEach(img => {
    const endpoint = img.dataset.endpoint;
    if (endpoint) {
      loadImageWithPlaceholder(img);
    }
  });

  bookGrid.querySelectorAll('.book-card').forEach(card => {
    card.addEventListener('click', () => {
      const id = card.dataset.bookId;
      const book = cache.books.find(b => b.book_id === id);
      if (book) showDetail(book);
    });
  });
}

async function loadImageWithPlaceholder(imgEl) {
  const endpoint = imgEl.dataset.endpoint;
  // 约定封面 img 后紧跟一个 placeholder 元素，用于失败或未加载时显示。
  const placeholder = imgEl.nextElementSibling;
  if (!endpoint) return;

  // 卡片封面初始是 display:none；原生 lazy loading 在 iframe 中可能因为元素不可见而不触发，
  // 导致 onload 不执行、占位符一直显示。这里统一改为 eager，封面数据仍由 bridge.apiGet 按需获取。
  imgEl.loading = 'eager';
  imgEl.removeAttribute('loading');

  imgEl.onload = () => {
    imgEl.style.display = '';
    if (placeholder) placeholder.style.display = 'none';
  };
  imgEl.onerror = () => {
    imgEl.style.display = 'none';
    if (placeholder) placeholder.style.display = '';
  };

  try {
    // Plugin Pages 的 iframe 不能直接复用 Dashboard 鉴权。
    // 通过 bridge.apiGet 获取 data URL，避免直接 <img src="/api/plug/..."> 被鉴权拦截。
    const dataEndpoint = endpoint.endsWith('/cover') ? `${endpoint}-data` : endpoint;
    const payload = await bridge.apiGet(dataEndpoint);
    if (!payload || !payload.data_url) throw new Error('empty image payload');
    imgEl.src = payload.data_url;
  } catch (e) {
    imgEl.style.display = 'none';
    if (placeholder) placeholder.style.display = '';
  }
}

function renderSyncTime() {
  const ts = cache.generated_at;
  syncMeta.textContent = ts ? `上次同步：${formatTime(ts)}` : '上次同步：-';
}

/* ===== 书籍详情页 ===== */
function showDetail(book) {
  currentBookId = book.book_id;
  renderDetail(book);
  libraryView.classList.remove('active');
  detailView.classList.add('active');
}

function showLibrary() {
  currentBookId = null;
  detailView.classList.remove('active');
  libraryView.classList.add('active');
}

function renderDetail(book) {
  const b = book;
  detailContent.innerHTML = `
    <div class="detail-left">
      <img class="detail-cover" data-endpoint="${esc(b.cover_url)}" alt="" style="display:none" />
      <div class="detail-cover-placeholder">
        <span class="icon icon-book-image"></span>
      </div>
      <div class="detail-actions">
        <button class="btn btn-danger-soft" id="detailClearFiles">
          <span class="icon icon-file-text"></span> 清除本书文件
        </button>
        <button class="btn btn-danger" id="detailDeleteBook">
          <span class="icon icon-trash-2"></span> 删除本书
        </button>
      </div>
    </div>
    <div class="detail-right">
      <div>
        <div class="detail-title">${esc(b.title)}</div>
        <div class="detail-author">${esc(b.author)}</div>
      </div>

      ${b.description ? `<div class="description-block">${esc(b.description)}</div>` : ''}

      <div class="info-group">
        <div class="info-group-title">基础信息</div>
        <div class="info-rows">
          ${infoRow('书籍 ID', b.book_id)}
          ${infoRow('来源', b.source_url ? `<a href="${esc(b.source_url)}" target="_blank" rel="noreferrer"><span class="icon icon-external-link"></span> ${esc(b.source_url)}</a>` : '-')}
          ${infoRow('信息块', b.info_block ? esc(b.info_block).replace(/\n/g, '<br>') : '-')}
          ${infoRow('创建时间', b.created_at ? formatTime(b.created_at) : '-')}
          ${infoRow('更新时间', b.updated_at ? formatTime(b.updated_at) : '-')}
        </div>
      </div>

      <div class="info-group">
        <div class="info-group-title">下载状态</div>
        <div class="info-rows">
          ${infoRow('章节总数', b.chapter_count)}
          ${infoRow('已缓存章节', b.cached_chapter_count)}
          ${infoRow('已导出格式', (b.downloaded_formats || []).join(', ') || '-')}
          ${infoRow('最新章节', b.latest_chapter_title || '-')}
          ${infoRow('远端检查', b.last_remote_check_at ? formatTime(b.last_remote_check_at) : '-')}
          ${infoRow('最近下载', b.last_download_at ? formatTime(b.last_download_at) : '-')}
          ${infoRow('失败章节', b.failed_chapters || 0)}
          ${infoRow('失败图片', b.failed_images || 0)}
        </div>
      </div>

      <div class="info-group">
        <div class="info-group-title">本地文件</div>
        <div class="info-rows">
          ${infoRow('插图数量', b.illustration_count)}
          ${infoRow('输出文件', b.outputs.length ? b.outputs.map(o => `<span class="icon icon-file-archive"></span> ${o.name} (${formatSize(o.size)})`).join('<br>') : '无')}
          ${infoRow('输出大小', formatSize(b.output_size || 0))}
          ${infoRow('本书占用', formatSize(b.book_size || 0))}
        </div>
      </div>
    </div>
  `;

  // 详情页封面复用卡片封面的 data URL 加载逻辑。
  const detailCoverImg = detailContent.querySelector('.detail-cover[data-endpoint]');
  if (detailCoverImg) {
    loadImageWithPlaceholder(detailCoverImg);
  }

  detailContent.querySelector('#detailClearFiles').addEventListener('click', () => {
    confirmAction(
      `清除《${b.title}》的导出文件？`,
      '将删除本书 TXT/EPUB 文件及其 manifest。\n章节缓存和封面不受影响。',
      () => apiAction(`dashboard/books/${b.book_id}/clear-files`, '已清除本书文件')
    );
  });

  detailContent.querySelector('#detailDeleteBook').addEventListener('click', () => {
    confirmAction(
      `删除《${b.title}》？`,
      '将删除本书全部本地数据，包括封面、章节缓存、插图、导出文件和状态。\n此操作不可恢复。',
      async () => {
        await apiAction(`dashboard/books/${b.book_id}/delete`, '已删除本书');
        showLibrary();
      }
    );
  });
}

/* ===== 危险操作确认弹窗 ===== */
let confirmCallback = null;

function confirmAction(title, message, callback) {
  $('#confirmTitle').textContent = title;
  $('#confirmMessage').textContent = message;
  confirmCallback = callback;
  confirmDialog.setAttribute('aria-hidden', 'false');
  $('#acceptConfirmBtn').onclick = async () => {
    hideConfirm();
    if (confirmCallback) await confirmCallback();
    confirmCallback = null;
  };
}

function hideConfirm() {
  confirmDialog.setAttribute('aria-hidden', 'true');
  confirmCallback = null;
}

/* ===== 轻提示 ===== */
let toastTimer = null;
function toast(msg) {
  toastEl.textContent = msg;
  toastEl.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toastEl.classList.remove('show'), 3000);
}

/* ===== 通用工具函数 ===== */
function formatSize(bytes) {
  if (!bytes || bytes <= 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  let i = 0;
  let size = bytes;
  while (size >= 1024 && i < units.length - 1) { size /= 1024; i++; }
  return `${size.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

function formatTime(ts) {
  if (!ts) return '-';
  const d = new Date(ts * 1000);
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function esc(str) {
  if (!str) return '';
  const el = document.createElement('span');
  el.textContent = String(str);
  return el.innerHTML;
}

function infoRow(label, value) {
  return `<div class="info-row"><span class="label">${esc(label)}</span><span class="value">${value}</span></div>`;
}

/* ===== 启动入口 ===== */
init();
