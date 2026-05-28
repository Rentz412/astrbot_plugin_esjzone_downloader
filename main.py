"""AstrBot 插件入口模块。

负责初始化 ESJZone 下载器的核心服务、注册聊天命令与 Dashboard API，并将用户请求路由到认证、下载、仓储等服务层。"""

from __future__ import annotations

import secrets
from pathlib import Path
from typing import Any

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
import astrbot.api.message_components as Comp
from astrbot.api.star import Context, Star, register
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

from .services.auth import EsjAuthService
from .services.downloader import EsjDownloader
from .services.repository import EsjRepository
from .services.task_manager import TaskManager

PLUGIN_NAME = "astrbot_plugin_esjzone_downloader"


@register(
    PLUGIN_NAME,
    "Rentz",
    "ESJZone 小说下载器，支持登录、EPUB/TXT 导出、ZIP 打包和 Dashboard 管理。",
    "1.0.0",
)
class EsjZoneDownloaderPlugin(Star):
    """AstrBot 插件主类，负责连接聊天命令、Web API 与底层下载服务。"""
    def __init__(self, context: Context, config: AstrBotConfig):
        """初始化对象依赖和运行时目录。"""
        super().__init__(context)
        self.context = context
        self.config = config
        self.data_dir = Path(get_astrbot_data_path()) / "plugin_data" / PLUGIN_NAME
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self._ensure_config_defaults()
        self.auth_service = EsjAuthService(self.data_dir, self.config, logger)
        self.downloader = EsjDownloader(self.data_dir, self.config, logger)
        self.repository = EsjRepository(self.data_dir)
        self.task_manager = TaskManager()

        self._register_web_apis()

    def _ensure_config_defaults(self) -> None:
        """补齐缺省配置，避免旧配置缺字段导致运行时报错。"""
        self.config.setdefault("dashboard", {})
        dash = self.config["dashboard"]
        dash.setdefault("enabled", False)
        dash.setdefault("host", "127.0.0.1")
        dash.setdefault("port", 8989)
        dash.setdefault("public_base_url", "")
        dash.setdefault("auth_enabled", True)

        self.config.setdefault("download", {})
        self.config["download"].setdefault("allow_external_images", True)

        self.config.setdefault("message", {})
        msg = self.config["message"]
        msg.setdefault("private_verbose_status", True)
        msg.setdefault("group_verbose_status", False)
        msg.setdefault("group_mention_user", True)

        self.config.setdefault("debug", {})
        dbg = self.config["debug"]
        dbg.setdefault("enabled", False)
        dbg.setdefault("save_pages", True)
        dbg.setdefault("save_auth_pages", True)
        dbg.setdefault("save_chapter_pages", False)

        if not dash.get("token"):
            dash["token"] = secrets.token_urlsafe(24)
            try:
                self.config.save_config()
            except Exception:
                logger.warning("Dashboard token 已生成，但配置保存失败。")

    def _webui_url(self) -> str:
        """根据 Dashboard 配置生成对用户展示的访问地址。"""
        dash = self.config.get("dashboard", {})
        public_base_url = (dash.get("public_base_url") or "").rstrip("/")
        if public_base_url:
            return public_base_url + "/"
        host = dash.get("host") or "127.0.0.1"
        port = int(dash.get("port") or 8989)
        display_host = "127.0.0.1" if host == "0.0.0.0" else host
        return f"http://{display_host}:{port}/"

    def _message_cfg(self) -> dict[str, Any]:
        """读取消息回复相关配置，并兼容非字典配置。"""
        cfg = self.config.get("message", {}) if hasattr(self.config, "get") else {}
        return cfg if isinstance(cfg, dict) else {}

    def _is_verbose_reply(self, event: AstrMessageEvent) -> bool:
        """判断当前场景是否应该返回详细进度信息。"""
        cfg = self._message_cfg()
        if self._is_group_event(event):
            return bool(cfg.get("group_verbose_status", False))
        return bool(cfg.get("private_verbose_status", True))

    def _should_mention(self, event: AstrMessageEvent) -> bool:
        """判断群聊回复是否需要 @ 触发用户。"""
        return self._is_group_event(event) and bool(self._message_cfg().get("group_mention_user", True))

    def _reply(self, event: AstrMessageEvent, text: str):
        """统一构造回复消息，兼容群聊 @ 和普通文本回复。"""
        if self._should_mention(event):
            try:
                return event.chain_result([
                    Comp.At(qq=event.get_sender_id()),
                    Comp.Plain(" "),
                    Comp.Plain(text),
                ])
            except Exception:
                return event.plain_result(text)
        return event.plain_result(text)

    def _download_start_text(self, event: AstrMessageEvent, fmt: str) -> str:
        """生成下载开始提示文案。"""
        if self._is_verbose_reply(event):
            return f"任务开始：正在下载并导出 {fmt.upper()}。"
        return "正在开始任务"

    def _download_done_text(self, event: AstrMessageEvent, result) -> str:
        """生成下载完成提示文案。"""
        if self._is_verbose_reply(event):
            return (
                f"下载完成：{result.title}\n"
                f"格式：{result.format}\n"
                f"章节数：{result.chapter_count}\n"
                f"ZIP 密码：{result.password}\n"
                "正在发送 ZIP 文件。"
            )
        return f"下载完成，正在发送文件。ZIP 密码：{result.password}"

    def _register_web_apis(self) -> None:
        """向 AstrBot 注册 Dashboard 所需的后端 API。"""
        try:
            self.context.register_web_api(f"/{PLUGIN_NAME}/books", self.api_books, ["GET"], "List local books")
            self.context.register_web_api(f"/{PLUGIN_NAME}/books/detail", self.api_book_detail, ["GET"], "Book detail")
            self.context.register_web_api(f"/{PLUGIN_NAME}/books/delete", self.api_book_delete, ["POST"], "Delete book")
            self.context.register_web_api(f"/{PLUGIN_NAME}/files/download", self.api_file_download, ["GET"], "Download file")
            self.context.register_web_api(f"/{PLUGIN_NAME}/auth/token/check", self.api_token_check, ["POST"], "Check token")
        except Exception as exc:
            logger.warning(f"注册 Web API 失败，可能当前 AstrBot 版本不支持 Pages API: {exc}")

    def _dashboard_enabled(self) -> bool:
        """判断 Dashboard 功能是否启用。"""
        return bool(self.config.get("dashboard", {}).get("enabled", False))

    def _check_token(self, request: Any) -> bool:
        """校验 Dashboard API 请求携带的访问 Token。"""
        dash = self.config.get("dashboard", {})
        if not dash.get("auth_enabled", True):
            return True
        configured = dash.get("token") or ""
        token = ""
        try:
            token = request.headers.get("X-ESJ-Token") or request.args.get("token") or ""
        except Exception:
            token = ""
        return bool(configured) and secrets.compare_digest(str(token), str(configured))

    async def api_books(self, request):
        """返回本地书库列表。"""
        if not self._dashboard_enabled():
            return {"ok": False, "error": "dashboard disabled"}
        if not self._check_token(request):
            return {"ok": False, "error": "unauthorized"}
        return {"ok": True, "books": self.repository.list_books()}

    async def api_book_detail(self, request):
        """返回指定书籍的本地状态详情。"""
        if not self._dashboard_enabled():
            return {"ok": False, "error": "dashboard disabled"}
        if not self._check_token(request):
            return {"ok": False, "error": "unauthorized"}
        book_id = request.args.get("book_id", "")
        status = self.repository.load_status(book_id)
        return {"ok": bool(status), "book": status}

    async def api_book_delete(self, request):
        """删除指定书籍的本地缓存和输出。"""
        if not self._dashboard_enabled():
            return {"ok": False, "error": "dashboard disabled"}
        if not self._check_token(request):
            return {"ok": False, "error": "unauthorized"}
        data = await request.json()
        book_id = str(data.get("book_id", ""))
        return {"ok": self.repository.clear_book(book_id)}

    async def api_file_download(self, request):
        """预留文件下载接口，等待适配 AstrBot 响应对象。"""
        return {"ok": False, "error": "文件下载 API 需按 AstrBot 当前版本的响应对象适配。"}

    async def api_token_check(self, request):
        """供前端检查当前 Token 是否有效。"""
        return {"ok": self._check_token(request)}

    @filter.command_group("esj")
    def esj(self):
        """ESJZone 下载器命令组。"""
        pass

    @esj.command("help")
    async def esj_help(self, event: AstrMessageEvent):
        """查看 ESJZone 下载器帮助。"""
        yield event.plain_result(
            "ESJZone 下载器命令：\n\n"
            "/esj i <编号或规范URL>  查看书籍简介、编号、章节数\n"
            "/esj c <编号或规范URL>  查看最近更新章节\n"
            "/esj d <编号或规范URL> [epub|txt] [起始章节] [结束章节]\n"
            "/esj l <邮箱> <密码>    私聊登录并保存 Cookie\n"
            "/esj logout             私聊清除当前用户 Cookie\n"
            "/esj db on|off|status   管理员开启、关闭或查看 Dashboard\n"
            "/esj clear cache|outputs|book <id>\n\n"
            "示例：\n"
            "/esj i 114514\n"
            "/esj i https://www.esjzone.one/detail/114514.html\n"
            "/esj d 114514 epub 1 50"
        )

    @esj.command("login", alias={"l"})
    async def esj_login(self, event: AstrMessageEvent, email: str, password: str):
        """私聊登录 ESJZone。"""
        if self._is_group_event(event):
            yield event.plain_result("登录涉及账号密码，请私聊机器人执行 /esj l <邮箱> <密码>")
            return

        yield event.plain_result("正在登录 ESJZone，请稍候。")
        result = await self.auth_service.login(email, password)
        if not result.success:
            yield event.plain_result(f"登录失败：{result.reason or '未知错误'}")
            return
        await self.auth_service.save_user_auth(event, email, password, result)
        yield event.plain_result(f"登录成功：{result.username or '已保存 Cookie'}。")

    @esj.command("logout")
    async def esj_logout(self, event: AstrMessageEvent, scope: str = ""):
        """清除登录态。"""
        if scope == "all":
            if not self._is_admin(event):
                yield event.plain_result("无权限执行 logout all。")
                return
            count = await self.auth_service.logout_all()
            yield event.plain_result(f"已清除全部用户登录态，共 {count} 个。")
            return

        if self._is_group_event(event):
            yield event.plain_result("退出登录请私聊机器人执行 /esj logout。")
            return

        ok = await self.auth_service.logout_user(event)
        yield event.plain_result("已清除当前用户登录态。" if ok else "当前用户没有保存登录态。")

    @esj.command("info", alias={"i"})
    async def esj_info(self, event: AstrMessageEvent, url: str):
        """查看书籍信息。"""
        auth = await self.auth_service.require_auth_or_reply(event)
        if not auth:
            yield event.plain_result(self._not_login_text(event))
            return

        try:
            metadata, chapters = await self.downloader.fetch_info(auth, url)
        except Exception as exc:
            logger.exception("获取书籍信息失败")
            yield event.plain_result(f"获取书籍信息失败：{exc}")
            return

        latest = chapters[-1].title if chapters else "无"
        if self._is_verbose_reply(event):
            text = (
                f"《{metadata.title}》\n"
                f"ID：{metadata.book_id}\n"
                f"作者：{metadata.author}\n"
                f"章节数：{len(chapters)}\n"
                f"最新章节：{latest}\n"
                f"详情页：{metadata.detail_url}\n\n"
                f"简介：{metadata.intro_text[:300] or '无'}\n\n"
                f"下载：/esj d {metadata.book_id} epub"
            )
        else:
            text = (
                f"《{metadata.title}》\n"
                f"章节数：{len(chapters)}\n"
                f"最新：{latest}\n"
                f"下载：/esj d {metadata.book_id} epub"
            )
        yield self._reply(event, text)

    @esj.command("check", alias={"c"})
    async def esj_check(self, event: AstrMessageEvent, url: str):
        """查看最近更新章节。"""
        auth = await self.auth_service.require_auth_or_reply(event)
        if not auth:
            yield event.plain_result(self._not_login_text(event))
            return

        try:
            metadata, chapters = await self.downloader.fetch_info(auth, url)
        except Exception as exc:
            logger.exception("检查更新失败")
            yield event.plain_result(f"检查更新失败：{exc}")
            return

        n = int(self.config.get("download", {}).get("recent_chapter_count", 8))
        recent = chapters[-n:]
        start_no = max(len(chapters) - len(recent) + 1, 1)
        if self._is_verbose_reply(event):
            lines = [f"《{metadata.title}》最近更新：", f"总章节数：{len(chapters)}", ""]
            for offset, chapter in enumerate(recent):
                lines.append(f"{start_no + offset}. {chapter.title}")
            if recent:
                lines += ["", "下载最新章节：", f"/esj d {metadata.book_id} epub {start_no} {len(chapters)}"]
            text = "\n".join(lines)
        else:
            latest = chapters[-1].title if chapters else "无"
            text = (
                f"《{metadata.title}》\n"
                f"总章节数：{len(chapters)}\n"
                f"最新：{latest}"
            )
            if recent:
                text += f"\n下载最新章节：/esj d {metadata.book_id} epub {start_no} {len(chapters)}"
        yield self._reply(event, text)

    @esj.command("download", alias={"d"})
    async def esj_download(self, event: AstrMessageEvent, url: str, fmt: str = "", start: int = 0, end: int = 0):
        """下载小说并导出 EPUB/TXT，默认 ZIP 打包。"""
        auth = await self.auth_service.require_auth_or_reply(event)
        if not auth:
            yield event.plain_result(self._not_login_text(event))
            return

        fmt = (fmt or self.config.get("download", {}).get("default_format", "epub")).lower()
        session_key = getattr(event, "unified_msg_origin", None) or "default"
        if not self.task_manager.enter_session(session_key):
            yield event.plain_result("当前会话已有下载任务正在运行，请稍后再试。")
            return

        try:
            yield self._reply(event, self._download_start_text(event, fmt))
            result = await self.downloader.download(auth, url, fmt, start, end)
            package_path = Path(result.package_path)
            yield self._reply(event, self._download_done_text(event, result))

            try:
                yield event.chain_result([
                    Comp.File(file=str(package_path), name=package_path.name)
                ])
            except Exception as send_exc:
                logger.exception("ZIP 文件发送失败")
                if self._is_verbose_reply(event):
                    text = (
                        f"ZIP 文件发送失败：{send_exc}\n"
                        f"ZIP：{result.package_path}\n"
                        f"ZIP 密码：{result.password}\n"
                        f"WebUI：{self._webui_url()}"
                    )
                else:
                    text = "文件发送失败，请私聊机器人或联系管理员查看。"
                yield self._reply(event, text)
        except Exception as exc:
            logger.exception("下载失败")
            yield event.plain_result(f"下载失败：{exc}")
        finally:
            self.task_manager.leave_session(session_key)

    @esj.command("db", alias={"dashboard"})
    async def esj_dashboard(self, event: AstrMessageEvent, action: str = "status"):
        """管理员开启、关闭或查看 Dashboard 状态。"""
        if not self._is_admin(event):
            yield event.plain_result("无权限操作 Dashboard。")
            return

        action = (action or "status").lower()
        dash = self.config.setdefault("dashboard", {})
        if action == "on":
            dash["enabled"] = True
            self.config.save_config()
            yield event.plain_result(
                "Dashboard 已开启。\n"
                f"WebUI 访问地址：{self._webui_url()}\n"
                "也可在 AstrBot 插件 Pages 中打开 dashboard 页面查看本地书库。\n"
                f"当前 Token 验证：{'已启用' if dash.get('auth_enabled', True) else '未启用'}。"
            )
            return
        if action == "off":
            dash["enabled"] = False
            self.config.save_config()
            yield event.plain_result("Dashboard 已关闭。\nWebUI 只显示未启用提示，高风险 API 将拒绝访问。")
            return

        yield event.plain_result(
            "Dashboard 状态：\n"
            f"启用：{'是' if dash.get('enabled') else '否'}\n"
            f"监听地址：{dash.get('host', '127.0.0.1')}\n"
            f"访问端口：{dash.get('port', 8989)}\n"
            f"WebUI 访问地址：{self._webui_url()}\n"
            f"Token 验证：{'是' if dash.get('auth_enabled', True) else '否'}\n"
            f"Token：{'已设置' if dash.get('token') else '未设置'}"
        )

    @esj.command("clear")
    async def esj_clear(self, event: AstrMessageEvent, target: str = "", book_id: str = ""):
        """管理员清理缓存、输出或书籍。"""
        if not self._is_admin(event):
            yield event.plain_result("无权限执行清理命令。")
            return

        if target == "cache":
            count = self.repository.clear_cache()
            yield event.plain_result(f"已清理章节缓存：{count} 项。")
            return
        if target == "outputs":
            count = self.repository.clear_outputs()
            yield event.plain_result(f"已清理输出和压缩包：{count} 项。")
            return
        if target == "book" and book_id:
            ok = self.repository.clear_book(book_id)
            yield event.plain_result(f"已删除书籍 {book_id}。" if ok else f"未找到书籍 {book_id}。")
            return
        if target == "cookies":
            count = await self.auth_service.logout_all()
            yield event.plain_result(f"已清理全部 Cookie：{count} 个用户。")
            return

        yield event.plain_result(
            "清理命令：\n"
            "/esj clear cache\n"
            "/esj clear outputs\n"
            "/esj clear book <编号>\n"
            "/esj clear cookies"
        )

    def _is_group_event(self, event: AstrMessageEvent) -> bool:
        """兼容不同平台事件对象，判断是否来自群聊。"""
        try:
            return bool(event.get_group_id())
        except Exception:
            return False

    def _is_admin(self, event: AstrMessageEvent) -> bool:
        """兼容不同平台事件对象，判断操作者是否管理员。"""
        try:
            return bool(event.is_admin())
        except Exception:
            return True

    def _not_login_text(self, event: AstrMessageEvent) -> str:
        """根据私聊/群聊场景生成未登录提示。"""
        if self._is_group_event(event):
            return "你尚未登录 ESJZone。请私聊机器人执行 /esj l <邮箱> <密码> 后再使用该命令。"
        return "你尚未登录 ESJZone，无法执行该命令。\n\n请发送：\n/esj l <邮箱> <密码>"

    async def terminate(self):
        """插件卸载或停用时执行的清理钩子。"""
        logger.info("astrbot_plugin_esjzone_downloader terminated.")
