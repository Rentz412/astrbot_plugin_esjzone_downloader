# astrbot_plugin_esjzone_downloader

ESJZone 小说下载 AstrBot 插件。

## 功能

- `/esj help` 查看帮助
- `/esj l <邮箱> <密码>` 私聊登录并加密保存 Cookie
- `/esj i <编号或URL>` 查看书籍信息
- `/esj c <编号或URL>` 查看最近更新
- `/esj d <编号或URL> [epub|txt] [起始章节] [结束章节]` 下载并打包
- `/esj logout` 清除当前用户登录态
- `/esj db on|off|status` 管理 Dashboard
- `/esj clear ...` 清理缓存/输出/书籍/Cookie
- 生成 EPUB 时会下载封面和正文插图，并自动识别 / 修正内嵌图片格式，降低因扩展名或响应头异常导致的阅读器兼容问题。

## WebUI

默认端口为 `8989`，访问提示必须包含端口，例如：

```text
http://127.0.0.1:8989/
```

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

### Dashboard 配置 `dashboard`

| 配置项 | 类型 | 默认值 | 说明 |
|---|---|---:|---|
| `enabled` | bool | `false` | 是否启用 Dashboard / WebUI。默认关闭以减少资源占用 |
| `host` | string | `127.0.0.1` | WebUI 监听地址。仅本机访问保持默认值；需要局域网访问可设为 `0.0.0.0` |
| `port` | int | `8989` | WebUI 访问端口，访问地址必须包含端口 |
| `public_base_url` | string | 空 | WebUI 对外访问基础地址。反向代理或公网部署时填写，例如 `https://example.com:8443` |
| `auth_enabled` | bool | `true` | 是否启用 Dashboard Token 验证 |
| `token` | string | 空 | Dashboard 访问 Token。为空时插件首次启动会自动生成 |

说明：

- Dashboard 默认关闭，可通过 AstrBot 配置项启用，也可通过管理员命令 `/esj db on` 开启。
- 可通过 `/esj db off` 关闭 Dashboard，通过 `/esj db status` 查看当前状态、访问地址和 Token 配置状态。
- `host` 为 `127.0.0.1` 时通常只能本机访问；如果部署在服务器上并需要从其他设备访问，可设置为 `0.0.0.0`，同时务必启用 Token 验证。
- `port` 默认 `8989`，访问时必须使用带端口地址，例如 `http://127.0.0.1:8989/`。
- `public_base_url` 可选。为空时插件会按 `host` 和 `port` 生成访问提示；使用反向代理、HTTPS、公网域名或端口映射时，建议填写最终对外访问地址。
- `auth_enabled` 默认开启。公网、局域网共享或反向代理环境强烈建议保持开启。
- `token` 为空时插件首次启动会自动生成；公网环境请手动设置足够长、不可猜测的强随机 Token。

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

本插件代码由 ChatGPT 5.5 辅助完成，并依据 AstrBot 插件开发文档和本项目规格书进行整理与实现。

---

## To Do List

- [√] 在真实 AstrBot 环境中完成插件加载测试。
- [√] 实测 `/esj l` 自动登录流程。
- [√] 实测 Cookie 校验和失效自动刷新。
- [√] 实测 `/esj i` 小说信息解析。
- [√] 实测 `/esj c` 最近章节解析。
- [√] 实测 `/esj d` 全本 EPUB 下载。
- [ ] 实测 `/esj d` TXT 下载。
- [ ] 根据真实 ESJZone 页面结构微调解析器。
- [√] 完善正文插图下载与 EPUB 图片资源写入。
- [ ] 优化 EPUB XHTML 清理逻辑。
- [ ] 增强失败章节补抓策略。
- [ ] 增加任务取消命令。
- [ ] 增加更详细的任务进度提示。
- [ ] 完善 Dashboard 详情页。
- [ ] 增加 Dashboard ZIP 下载按钮。
- [ ] 增加 Dashboard 删除书籍二次确认。
- [ ] 增加 Dashboard 日志查看。
- [ ] 增加 WebUI 远程检查更新功能。
- [ ] 增强多平台文件发送兼容性。
