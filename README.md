# astrbot_plugin_esjzone_downloader
# ESJ Zone 小说下载插件

一个用于 AstrBot 的 ESJZone 小说下载插件。
本插件用于在 AstrBot 中通过聊天命令下载 ESJZone 小说，支持用户独立登录、自动 Cookie 校验、EPUB / TXT 导出、本地书库缓存和 ZIP 打包发送。、

！！！目前插件仍处于初步开发中，有功能出现问题欢迎反馈！！！
Tips：插件仅在aiocqhttp经过测试，其它平台建议自测。

## 插件已实现的功能

- 登录后可保存并使用cookie保持登录状态
- 自动连接ESJ国内站，避免无法访问的问题
- 获取书籍详情、更新状态
- 下载全本小说（epub/txt）
- 打包小说为zip格式并使用密码加密发送给用户
- 小说自选章节下载
- epub格式支持自选嵌入封面插图
- 插件输出状态的简详输出
- 生成EPUB下载封面和插图时，自动识别/修正内嵌图片格式，降低因扩展名或响应头异常导致的阅读器兼容问题
- 提供 AstrBot Dashboard / Plugin Page 可视化管理界面，可查看本地书库、封面、占用空间和调试文件状态

## 插件状况

- ~~[Bug] 当自选章节下载，且存在全本小说时，会直接输出全本小说~~（v1.1.0 已修复）
- ~~[ToDo] Dashboard (AstrBot Pages) 待开发~~（v2.0.0 已初步开发完成）
- [ToDo] 增加 个人收藏列表查看功能
- [ToDo] 增加 小说搜索功能
- [ToDo] 增加返回的消息合并转发功能（aiocqhttp）
- [ToDo] 增加 Dashboard ZIP 下载按钮。
- [ToDo] 增加 Dashboard 日志查看。
- [ToDo] 增加 Dashboard 亮色/深色主题切换。

## 功能

- `/esj help` 查看帮助
- `/esj l <邮箱> <密码>` 私聊登录并加密保存 Cookie
- `/esj i <编号或URL>` 查看书籍信息
- `/esj c <编号或URL>` 查看最近更新
- `/esj d <编号或URL> [epub|txt] [起始章节] [结束章节]` 下载并打包
- `/esj logout` 清除当前用户登录态
- `/esj clear ...` 清理缓存/输出/书籍/Cookie

## Dashboard 可视化管理界面

插件提供基于 AstrBot Plugin Page 的 Dashboard 页面，用于在 WebUI 中查看和管理本地缓存的 ESJZone 书库数据。页面为纯前端实现，无需额外构建步骤；数据由插件后端扫描本地数据目录后生成。

### Dashboard 主要能力

- 查看插件名称、版本、作者和仓库链接。
- 查看统计概览：
  - 已保存登录态用户数量
  - 本地小说数量
  - 插件数据目录占用空间
  - 调试文件数量
- 浏览本地书库卡片：
  - 展示书名、作者、下载状态、已导出格式
  - 展示本地缓存封面
  - 支持按书名、作者或书籍 ID 搜索
- 查看单本书详情：
  - 封面、简介、来源链接、信息块
  - 章节总数、已缓存章节、最新章节、最近下载时间
  - EPUB / TXT 输出文件列表、输出大小、本书总占用
  - 失败章节数、失败图片数等异常状态
- 清理数据：
  - 清理调试文件
  - 清除所有书籍导出文件（TXT / EPUB 与 manifest）
  - 删除所有本地书籍数据
  - 清除单本书导出文件
  - 删除单本书本地数据

### Dashboard 使用说明

安装并启用插件后，可在 AstrBot WebUI 的插件页面中打开本插件的 Dashboard / Plugin Page。进入页面后：

1. 点击“刷新”可重新扫描本地书库和调试目录。
2. 在“本地书库”中点击书籍卡片可进入详情页。
3. 使用搜索框可快速按书名、作者或 ID 过滤书籍。
4. 对删除、清理类操作，Dashboard 会弹出二次确认窗口，确认后才会执行。

### Dashboard 数据与安全说明

- Dashboard 展示的数据来自插件本地数据目录，不会主动访问 ESJZone。
- “刷新”仅重新扫描本地文件并更新 `dashboard_cache.json`。
- 书籍封面通过插件后端接口读取本地封面文件，并在 Plugin Page 中以 data URL 方式展示，以兼容 AstrBot WebUI 的鉴权环境。
- “清除所有书籍文件”只删除已导出的 TXT / EPUB 文件及其 manifest，不删除章节缓存、封面、插图和书籍状态。
- “删除所有书籍数据”和“删除本书”会删除对应书籍目录中的封面、章节、插图、导出文件、状态等全部本地数据，请谨慎操作。
- “清理调试文件”会清空 `debug/auth` 和 `debug/pages` 下的文件。调试文件可能包含页面样本、请求诊断或登录态相关信息，排查完成后建议及时清理。

## 插件配置项

配置文件由 AstrBot 根据 `_conf_schema.json` 自动生成，可在 AstrBot WebUI 中可视化编辑。

### 下载配置 `download`

| 配置项 | 类型 | 默认值 | 说明 |
|---|---|---:|---|
| `default_format` | string | `epub` | 默认导出格式，可选 `epub` / `txt` |
| `concurrency` | int | `5` | 章节下载并发数，建议 1-10 |
| `enable_image_download` | bool | `true` | 生成 EPUB 时下载封面和正文插图 |
| `allow_external_images` | bool | `true` | 允许下载外站图床图片 |
| `request_timeout` | int | `15` | 页面请求超时时间，单位秒 |
| `image_timeout` | int | `8` | 图片请求超时时间，单位秒 |
| `max_retries` | int | `3` | 章节 / 图片最大重试次数 |
| `recent_chapter_count` | int | `8` | `/esj c` 显示最近章节数量 |
| `user_agent` | string | 浏览器 UA | 请求 User-Agent |

---

### ZIP 配置 `zip`

| 配置项 | 类型 | 默认值 | 说明 |
|---|---|---:|---|
| `password_mode` | string | `book_id` | ZIP 密码模式 |
| `fixed_password` | string | `esjzone` | 固定密码模式下使用 |
| `random_password_length` | int | `8` | 随机密码长度 |

`password_mode` 可选：

| 值 | 说明 |
|---|---|
| `book_id` | 密码为 `esj<book_id>` |
| `random` | 随机生成密码 |
| `fixed` | 使用固定密码 |

---

### 消息配置 `message`

| 配置项 | 类型 | 默认值 | 说明 |
|---|---|---:|---|
| `private_verbose_status` | bool | `true` | 私聊输出详细下载状态 |
| `group_mention_user` | bool | `true` | 群聊简短提示时是否 @ 发起用户 |
| `group_verbose_status` | bool | `false` | 群聊是否输出详细下载状态 |

---

### 调试配置 `debug`

| 配置项 | 类型 | 默认值 | 说明 |
|---|---|---:|---|
| `enabled` | bool | `false` | 启用 ESJZone 插件调试日志 |
| `save_pages` | bool | `true` | 调试模式下保存详情页和诊断 JSON |
| `save_auth_pages` | bool | `true` | 调试模式下保存登录与个人资料页调试文件 |
| `save_chapter_pages` | bool | `false` | 调试模式下保存章节页 HTML |

说明：

- 调试模式默认关闭。
- 开启后，插件会在认证流程中保存登录页、token 响应、密码登录响应、跳转页、profile 校验页、抓取的HTML文件等样本。
- 调试文件保存到：

```text
data/plugin_data/astrbot_plugin_esjzone_downloader/debug/
```

- 调试文件可能包含敏感登录态信息，仅建议开发排查时开启。
- 排查完成后建议关闭调试模式，并按需删除 `debug` 目录。

---

### 代理配置 `proxy`

| 配置项 | 类型 | 默认值 | 说明 |
|---|---|---:|---|
| `enabled` | bool | `false` | 是否启用代理。关闭时所有请求直连 |
| `url` | string | 空 | 代理地址，例如 `http://localhost:7899` 或 `socks5://127.0.0.1:7890` |

说明：

- 代理用于 ESJZone 页面请求、章节请求，以及启用图片下载时的封面 / 插图请求。
- `enabled` 为 `true` 时必须正确填写 `url`，否则请求仍可能无法通过代理发出。
- 仅需要代理访问 ESJZone 或外部图床时开启；不需要代理时建议保持关闭。
- 代理地址应填写 AstrBot 运行环境可访问的地址：
  - AstrBot 与代理运行在同一台机器时，可使用 `http://127.0.0.1:7899` 或 `http://localhost:7899`。
  - AstrBot 运行在 Docker / 服务器 / NAS 中时，`localhost` 指容器或服务器自身，不一定是你电脑上的代理，需要改为实际可访问的代理主机地址。
- SOCKS 代理需要运行环境安装 `httpx[socks]` 支持。

示例：

```text
http://localhost:7899
http://127.0.0.1:7899
socks5://127.0.0.1:7890
```

如果使用 SOCKS 代理，请确保依赖中包含：

```text
httpx[socks]>=0.27.0
```

---

## 数据目录

插件运行数据保存在 AstrBot 数据目录下：

```text
data/plugin_data/astrbot_plugin_esjzone_downloader/
```

实际根路径由 AstrBot 的 `get_astrbot_data_path()` 决定。常见情况下可在 AstrBot 数据目录的 `plugin_data/astrbot_plugin_esjzone_downloader/` 下找到。

主要结构：

```text
data/plugin_data/astrbot_plugin_esjzone_downloader/
├─ dashboard_cache.json
├─ auth/
│  ├─ secret.key
│  └─ users/
├─ debug/
│  ├─ auth/
│  └─ pages/
└─ books/
   └─ <book_id>/
      ├─ status.json
      ├─ metadata.json
      ├─ cover.<ext>
      ├─ chapters/
      │  └─ 0001_<chapter_id>.json
      ├─ illustrations/
      │  └─ <hash>.<ext>
      ├─ outputs/
      │  ├─ <书名>.epub
      │  └─ <书名>.txt
      ├─ packages/
      │  └─ <书名>.zip
      └─ logs/
```

说明：

- `dashboard_cache.json` 是 Dashboard 生成的本地书库快照，会在打开页面或点击刷新时自动创建 / 更新。
- `auth/secret.key` 是本地加密密钥，请勿泄露，也不要随意删除。
- `auth/users/` 保存加密后的用户登录态 / Cookie。执行 `/esj logout` 或 `/esj clear cookies` 会清理对应登录态。
- `debug/auth/` 保存登录、Cookie 校验等认证流程调试文件。
- `debug/pages/` 保存详情页、章节页、下载诊断 JSON、图片处理诊断等调试文件。
- `debug/*` 仅在调试配置开启时写入，可能包含敏感登录态、页面内容或请求诊断信息，排查完成后建议关闭调试并按需删除。
- `books/<book_id>/metadata.json` 保存书籍元数据，`status.json` 保存最近一次下载 / 打包状态。
- `books/<book_id>/chapters/` 保存章节正文缓存。执行 `/esj clear cache` 会清理各书籍的章节缓存目录。
- `books/<book_id>/illustrations/` 保存 EPUB 正文插图。插件会根据图片真实内容和响应头自动识别 / 修正扩展名与媒体类型，必要时转换为 PNG，以提升 EPUB 内嵌图片兼容性。
- `books/<book_id>/cover.<ext>` 保存封面图片，扩展名可能为 `.jpg`、`.png`、`.webp` 等实际识别出的图片格式。
- `books/<book_id>/outputs/` 保存导出的 EPUB / TXT 文件。
- `books/<book_id>/packages/` 保存最终发送用 ZIP 压缩包。执行 `/esj clear outputs` 会清理 `outputs/` 和 `packages/`。
- `books/<book_id>/logs/` 预留用于书籍相关日志。
- 删除 `auth/secret.key` 会导致旧登录数据无法解密；如需彻底重置登录态，请同时清理 `auth/users/` 后重新登录。
- 如需删除单本书籍本地数据，可使用 `/esj clear book <编号>`。

---

## 开发与贡献

欢迎提交 Issue、建议和 Pull Request。

开发建议：

1. Fork 本仓库。
2. 创建开发分支。
3. 在 AstrBot 插件目录中进行测试。
4. 修改代码后在 AstrBot WebUI 中重载插件。
5. 提交前运行语法检查：

```bash
python -m compileall astrbot_plugin_esjzone_downloader
```

6. 如使用格式化工具，建议使用 `ruff`。

### 项目参考

本插件参考了以下项目的功能设计与使用场景：

- https://github.com/mikoto710/esj-novel-downloader

### 代码生成说明

本插件代码由 ChatGPT 5.5 与 Claude-opus-4.7 辅助完成，并依据 AstrBot 插件开发文档和本项目规格书进行整理与实现。
