# ESJZone 小说下载器

！！！！
目前未解决登录问题，插件仍在开发
！！！！

一个用于 AstrBot 的 ESJZone 小说下载插件。

本插件用于在 AstrBot 中通过聊天命令下载 ESJZone 小说，支持用户独立登录、自动 Cookie 校验、EPUB / TXT 导出、本地书库缓存、ZIP 打包发送和可选 Dashboard 管理页面。

> 参考项目：  
> - https://github.com/mikoto710/esj-novel-downloader  
>
> 代码生成：  
> - 本插件代码由 ChatGPT 5.5 辅助完成。

---

## 功能与特点

### 核心功能

- 通过聊天命令输入 ESJZone 小说编号或 URL。
- 支持解析小说详情页和论坛目录页。
- 支持查看小说信息。
- 支持查看最近更新章节。
- 支持全本下载。
- 支持指定章节范围下载。
- 支持导出 EPUB。
- 支持导出 TXT。
- 默认导出 EPUB。
- 默认打包为 ZIP 后发送。
- ZIP 默认密码为 `esj<book_id>`。

### 登录与安全

- 支持 ESJZone 自动登录。
- 每个 AstrBot 用户独立保存登录态。
- 群聊下载也使用发起用户自己的 Cookie。
- 不使用全局共享 Cookie。
- 登录命令仅允许私聊使用。
- 邮箱、密码、Cookie 使用 Fernet 加密保存。
- Cookie 失效后会尝试自动刷新。
- 网络校验失败时不会立即删除 Cookie。

### 本地书库与缓存

- 书籍数据统一保存到 AstrBot 数据目录下：

```text
data/plugin_data/astrbot_plugin_esjzone_downloader/books/<book_id>/
```

- 支持本地状态记录。
- 远端章节状态未变化时复用本地文件。
- 远端章节状态变化时全量重下。
- 同一小说全局互斥下载，避免重复任务。
- 同一会话限制并发任务。

### Dashboard / WebUI

- 提供 Dashboard 页面骨架。
- Dashboard 默认关闭，减少资源占用。
- 管理员可通过命令开启或关闭。
- Dashboard API 支持 Token 验证。
- 可查看本地书库状态。

---

## 安装与环境

### 环境要求

- AstrBot：`>=4.16,<5`
- Python：建议 `>=3.10`
- 操作系统：Windows / Linux / macOS 均可
- 网络：需要能够访问 ESJZone

### 依赖

插件依赖写在 `requirements.txt`：

```text
httpx>=0.27.0
beautifulsoup4>=4.12.0
lxml>=5.0.0
ebooklib>=0.18
Pillow>=10.0.0
aiofiles>=23.0.0
pyzipper>=0.3.6
cryptography>=42.0.0
```

如需 SOCKS 代理，可额外安装：

```text
httpx[socks]>=0.27.0
```

### 安装方式

将插件目录放入 AstrBot 插件目录：

```text
AstrBot/data/plugins/astrbot_plugin_esjzone_downloader/
```

插件目录结构应类似：

```text
astrbot_plugin_esjzone_downloader/
├─ main.py
├─ metadata.yaml
├─ requirements.txt
├─ _conf_schema.json
├─ README.md
├─ services/
└─ pages/
```

然后在 AstrBot WebUI 中：

1. 打开插件管理。
2. 重载插件。
3. 确认插件无报错。
4. 根据需要调整插件配置。

---

## 使用命令

主命令组：

```text
/esj
```

### `/esj help`

显示帮助信息。

```text
/esj help
```

---

### `/esj l <邮箱> <密码>`

登录 ESJZone。

```text
/esj l your@email.com your_password
```

说明：

- 仅允许私聊使用。
- 群聊中使用会被拒绝。
- 登录成功后会加密保存邮箱、密码和 Cookie。
- 后续查询和下载会使用该用户自己的 Cookie。

---

### `/esj logout`

清除当前用户登录态。

```text
/esj logout
```

说明：

- 仅允许私聊使用。
- 删除当前 AstrBot 用户保存的 ESJZone 登录信息。
- 不影响其他用户。

---

### `/esj i <编号或URL>`

查看小说信息。

```text
/esj i 114514
/esj i https://www.esjzone.one/detail/114514.html
/esj i https://www.esjzone.cc/forum/114514
```

输出内容包括：

- 小说编号
- 小说标题
- 作者
- 章节数
- 最新章节
- 来源 URL
- 简介
- 推荐下载命令

---

### `/esj c <编号或URL>`

查看最近更新章节。

```text
/esj c 114514
```

默认显示最近 8 章，可通过配置项调整。

---

### `/esj d <编号或URL> [epub|txt] [起始章节] [结束章节]`

下载小说并发送 ZIP。

```text
/esj d 114514
/esj d 114514 epub
/esj d 114514 txt
/esj d 114514 epub 1 50
/esj d 114514 txt 10 10
```

规则：

- 未指定格式时默认 `epub`。
- 支持格式：
  - `epub`
  - `txt`
- 不支持 HTML。
- 未指定章节范围时下载全本。
- 只指定起始章节时下载到最后。
- 指定起止章节时下载闭区间。
- 用户输入章节号从 1 开始。
- 下载完成后默认发送 ZIP。
- ZIP 默认密码为：

```text
esj<book_id>
```

---

### `/esj db on`

开启 Dashboard / WebUI。

```text
/esj db on
```

说明：

- 仅管理员可用。
- 开启后可在 AstrBot 插件 Pages 中访问 Dashboard。
- 如果启用了 Token 验证，需要输入 Dashboard Token。

---

### `/esj db off`

关闭 Dashboard / WebUI。

```text
/esj db off
```

说明：

- 仅管理员可用。
- 关闭后 Dashboard 高风险 API 会拒绝访问。
- 不影响聊天命令下载。
- 不删除本地书库。

---

### `/esj db status`

查看 Dashboard 状态。

```text
/esj db status
```

显示：

- Dashboard 是否启用。
- Token 验证是否启用。
- Token 是否已设置。

---

### `/esj clear cache`

清理章节缓存。

```text
/esj clear cache
```

说明：

- 仅管理员可用。
- 清理 `books/*/chapters/`。
- 不删除登录态。
- 不删除输出文件和 ZIP。

---

### `/esj clear outputs`

清理输出文件和 ZIP 包。

```text
/esj clear outputs
```

说明：

- 仅管理员可用。
- 清理 `books/*/outputs/` 和 `books/*/packages/`。

---

### `/esj clear book <编号>`

删除指定本地书籍。

```text
/esj clear book 114514
```

说明：

- 仅管理员可用。
- 删除：

```text
books/<book_id>/
```

---

## 插件配置项

配置文件由 AstrBot 根据 `_conf_schema.json` 自动生成，可在 AstrBot WebUI 中可视化编辑。

### 下载配置 `download`

| 配置项 | 类型 | 默认值 | 说明 |
|---|---|---:|---|
| `default_format` | string | `epub` | 默认导出格式，可选 `epub` / `txt` |
| `concurrency` | int | `5` | 章节下载并发数，建议 1-10 |
| `enable_image_download` | bool | `true` | 生成 EPUB 时下载封面和正文插图 |
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

### Dashboard 配置 `dashboard`

| 配置项 | 类型 | 默认值 | 说明 |
|---|---|---:|---|
| `enabled` | bool | `false` | 是否启用 Dashboard / WebUI |
| `auth_enabled` | bool | `true` | 是否启用 Dashboard Token 验证 |
| `token` | string | 空 | Dashboard 访问 Token |

说明：

- Dashboard 默认关闭。
- 可通过 `/esj db on` 开启。
- 可通过 `/esj db off` 关闭。
- `token` 为空时插件会尝试自动生成。
- 公网环境强烈建议启用 Token 验证并设置强随机 Token。

---

### 代理配置 `proxy`

| 配置项 | 类型 | 默认值 | 说明 |
|---|---|---:|---|
| `enabled` | bool | `false` | 是否启用 HTTP 代理 |
| `url` | string | 空 | 代理地址 |

示例：

```text
http://localhost:7899
socks5://127.0.0.1:7890
```

如果使用 SOCKS 代理，请安装：

```text
httpx[socks]>=0.27.0
```

---

## 数据目录

插件运行数据保存在 AstrBot 数据目录下：

```text
data/plugin_data/astrbot_plugin_esjzone_downloader/
```

主要结构：

```text
data/plugin_data/astrbot_plugin_esjzone_downloader/
├─ auth/
│  ├─ secret.key
│  └─ users/
└─ books/
   └─ <book_id>/
      ├─ status.json
      ├─ metadata.json
      ├─ cover.jpg
      ├─ chapters/
      ├─ illustrations/
      ├─ outputs/
      ├─ packages/
      └─ logs/
```

说明：

- `auth/secret.key` 是本地加密密钥，请勿泄露。
- `auth/users/` 保存加密后的用户登录态。
- `books/<book_id>/` 保存本地书籍数据。
- 删除 `auth/secret.key` 会导致旧登录数据无法解密。

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

- [ ] 在真实 AstrBot 环境中完成插件加载测试。
- [ ] 实测 `/esj l` 自动登录流程。
- [ ] 实测 Cookie 校验和失效自动刷新。
- [ ] 实测 `/esj i` 小说信息解析。
- [ ] 实测 `/esj c` 最近章节解析。
- [ ] 实测 `/esj d` 全本 EPUB 下载。
- [ ] 实测 `/esj d` TXT 下载。
- [ ] 根据真实 ESJZone 页面结构微调解析器。
- [ ] 完善正文插图下载与 EPUB 图片资源写入。
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
- [ ] 增加单元测试。
- [ ] 增加发布前检查脚本。
