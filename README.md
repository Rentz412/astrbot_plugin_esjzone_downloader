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

## URL 规范

- 纯数字默认识别为 `book_id`
- 主站：`https://www.esjzone.one`
- 备用站：`https://www.esjzone.cc`
- 详情页：`/detail/<book_id>` 或 `/detail/<book_id>.html`
- 章节页：`/forum/<book_id>/<chapter_id>` 或 `/forum/<book_id>/<chapter_id>.html`
- `chapter_id` 必须从详情页章节列表解析，不能按序号推导

## WebUI

默认端口为 `8989`，访问提示必须包含端口，例如：

```text
http://127.0.0.1:8989/
```

## 安全

账号密码、Cookie、Dashboard token 不得明文输出到日志。
