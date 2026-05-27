from __future__ import annotations

from pathlib import Path
from typing import Any

import astrbot.api.message_components as Comp
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

try:
    from quart import jsonify, request, send_file
except Exception:  # pragma: no cover
    jsonify = None
    request = None
    send_file = None

from .services.auth import EsjAuthService
from .services.client import EsjHttpClient
from .services.downloader import DownloadService
from .services.exporter_epub import EpubExporter
from .services.exporter_txt import TxtExporter
from .services.image import ImageService
from .services.models import DownloadOptions
from .services.packer import ZipPacker
from .services.parser import EsjParser
from .services.repository import BookRepository
from .services.task_manager import TaskManager
from .services.utils import PLUGIN_NAME, ensure_within_base


class EsjZoneDownloaderPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.data_dir = Path(get_astrbot_data_path()) / "plugin_data" / PLUGIN_NAME
        self.data_dir.mkdir(parents=True, exist_ok=True)

        download_cfg = self._cfg("download", {})
        proxy_cfg = self._cfg("proxy", {})
        proxy = proxy_cfg.get("url") if proxy_cfg.get("enabled") and proxy_cfg.get("url") else None

        self.client = EsjHttpClient(
            user_agent=download_cfg.get("user_agent", "Mozilla/5.0"),
            timeout=int(download_cfg.get("request_timeout", 15) or 15),
            image_timeout=int(download_cfg.get("image_timeout", 8) or 8),
            max_retries=int(download_cfg.get("max_retries", 3) or 3),
            proxy=proxy,
        )
        self.parser = EsjParser()
        self.repository = BookRepository(self.data_dir)
        self.auth_service = EsjAuthService(self.data_dir, self.client)
        self.task_manager = TaskManager()

        self.downloader = DownloadService(
            client=self.client,
            parser=self.parser,
            repository=self.repository,
            image_service=ImageService(self.client),
            txt_exporter=TxtExporter(),
            epub_exporter=EpubExporter(),
            packer=ZipPacker(),
            config_getter=self._cfg,
        )

        self._ensure_dashboard_token()
        self._register_web_apis(context)

    def _cfg(self, key: str, default: Any = None) -> Any:
        try:
            value = self.config.get(key, default)
        except AttributeError:
            value = default
        return value if value is not None else default

    def _set_nested_cfg(self, section: str, key: str, value: Any) -> None:
        section_data = self._cfg(section, {})
        if not isinstance(section_data, dict):
            section_data = {}
        section_data[key] = value
        try:
            self.config[section] = section_data
        except Exception:
            setattr(self.config, section, section_data)
        if hasattr(self.config, "save_config"):
            self.config.save_config()

    def _ensure_dashboard_token(self) -> None:
        import secrets

        dashboard_cfg = self._cfg("dashboard", {})
        if not isinstance(dashboard_cfg, dict):
            dashboard_cfg = {}
        if not dashboard_cfg.get("token"):
            dashboard_cfg["token"] = secrets.token_urlsafe(24)
            try:
                self.config["dashboard"] = dashboard_cfg
                self.config.save_config()
            except Exception:
                logger.warning("无法自动保存 Dashboard token，请在配置中手动设置。")

    def _register_web_apis(self, context: Context) -> None:
        if jsonify is None:
            logger.warning("quart 不可用，Dashboard API 将不会注册。")
            return
        context.register_web_api(f"/{PLUGIN_NAME}/books", self.api_books, ["GET"], "List ESJZone books")
        context.register_web_api(f"/{PLUGIN_NAME}/books/detail", self.api_book_detail, ["GET"], "ESJZone book detail")
        context.register_web_api(f"/{PLUGIN_NAME}/books/delete", self.api_book_delete, ["POST"], "Delete ESJZone book")
        context.register_web_api(f"/{PLUGIN_NAME}/files/download", self.api_file_download, ["GET"], "Download ESJZone file")
        context.register_web_api(f"/{PLUGIN_NAME}/auth/token/check", self.api_token_check, ["POST"], "Check dashboard token")

    @filter.command_group("esj")
    def esj():
        pass

    @esj.command("help")
    async def esj_help(self, event: AstrMessageEvent):
        """显示 ESJZone 下载器帮助。"""
        yield event.plain_result(
            "ESJZone 下载器命令：\n\n"
            "/esj i <URL或编号>      查看书籍简介、编号、章节数\n"
            "/esj c <URL或编号>      查看最近更新章节\n"
            "/esj d <URL或编号> [epub|txt] [起始章节] [结束章节]\n"
            "                       下载小说，未指定格式默认 EPUB\n"
            "/esj l <邮箱> <密码>    私聊登录并保存 Cookie\n"
            "/esj logout             私聊清除当前用户 Cookie\n"
            "/esj db on|off|status   管理员开启、关闭或查看 Dashboard\n"
            "/esj clear              管理员清理缓存\n\n"
            "示例：\n"
            "/esj i 114514\n"
            "/esj c 114514\n"
            "/esj d 114514\n"
            "/esj d 114514 txt\n"
            "/esj d 114514 epub 1 50"
        )

    @esj.command("i")
    async def esj_info(self, event: AstrMessageEvent, url: str):
        """查看 ESJZone 小说信息。"""
        auth = await self.auth_service.require_auth_or_reply(event)
        if not auth:
            return
        try:
            metadata, chapters = await self.downloader.get_info(url, auth)
            latest = chapters[-1] if chapters else None
            yield event.plain_result(
                f"《{metadata.title}》\n"
                f"编号：{metadata.book_id}\n"
                f"作者：{metadata.author}\n"
                f"章节数：{len(chapters)}\n"
                f"最新章节：{latest.title if latest else '无'}\n"
                f"来源：{metadata.detail_url}\n\n"
                f"简介：\n{metadata.intro_text or '无'}\n\n"
                f"下载：/esj d {metadata.book_id}"
            )
        except Exception as exc:
            logger.exception("esj info failed")
            yield event.plain_result(f"查询失败：{exc}")

    @esj.command("c")
    async def esj_check(self, event: AstrMessageEvent, url: str):
        """查看 ESJZone 小说最近更新章节。"""
        auth = await self.auth_service.require_auth_or_reply(event)
        if not auth:
            return
        try:
            metadata, chapters = await self.downloader.get_info(url, auth)
            count = int(self._cfg("download", {}).get("recent_chapter_count", 8) or 8)
            recent = chapters[-count:]
            lines = [f"《{metadata.title}》最近更新：", f"总章节数：{len(chapters)}", ""]
            for chapter in recent:
                lines.append(f"{chapter.index + 1}. {chapter.title}")
            if recent:
                lines.extend(["", f"下载最近章节：/esj d {metadata.book_id} epub {recent[0].index + 1} {recent[-1].index + 1}"])
            yield event.plain_result("\n".join(lines))
        except Exception as exc:
            logger.exception("esj check failed")
            yield event.plain_result(f"检查失败：{exc}")

    @esj.command("d")
    async def esj_download(
        self,
        event: AstrMessageEvent,
        url: str,
        fmt: str = "",
        start: int = 0,
        end: int = 0,
    ):
        """下载 ESJZone 小说并发送 ZIP。"""
        auth = await self.auth_service.require_auth_or_reply(event)
        if not auth:
            return

        fmt = (fmt or self._cfg("download", {}).get("default_format", "epub")).lower()
        if fmt not in {"epub", "txt"}:
            yield event.plain_result("当前版本仅支持 epub 和 txt。")
            return

        session_key = event.unified_msg_origin
        if self.task_manager.is_session_busy(session_key):
            yield event.plain_result("当前会话已有下载任务正在运行，请等待完成后再试。")
            return

        try:
            book_id, _, _ = self.parser.normalize_input(url)
        except Exception:
            book_id = url

        async with self.task_manager.session_guard(session_key):
            async with self.task_manager.book_lock(book_id):
                try:
                    yield event.plain_result("任务已开始，正在获取书籍信息并检查本地状态。")

                    async def progress(done: int, total: int, title: str) -> None:
                        if done == total or done % 10 == 0:
                            logger.info(f"ESJZone download progress {done}/{total}: {title}")

                    result = await self.downloader.download(
                        url,
                        auth,
                        DownloadOptions(fmt=fmt, start=start, end=end),
                        progress_cb=progress,
                    )
                    yield event.plain_result(
                        f"下载完成：{result.title}\n"
                        f"格式：{result.format}\n"
                        f"ZIP 密码：{result.zip_password}\n"
                        f"{'已复用本地文件。' if result.reused else '已生成新文件。'}"
                    )
                    yield event.chain_result([Comp.File(file=str(result.package_path), name=result.package_path.name)])
                except Exception as exc:
                    logger.exception("esj download failed")
                    yield event.plain_result(f"下载失败：{exc}")

    @esj.command("l")
    async def esj_login(self, event: AstrMessageEvent, email: str, password: str):
        """私聊登录 ESJZone。"""
        if event.get_group_id():
            yield event.plain_result("登录涉及账号密码，请私聊机器人执行 /esj l <邮箱> <密码>")
            return
        try:
            result = await self.auth_service.login(email, password)
            if not result.success:
                yield event.plain_result(result.message)
                return
            await self.auth_service.save_login(event, email, password, result)
            yield event.plain_result(f"登录成功。用户：{result.username or '已登录'}")
        except Exception as exc:
            logger.exception("esj login failed")
            yield event.plain_result(f"登录失败：{exc}")

    @esj.command("logout")
    async def esj_logout(self, event: AstrMessageEvent, scope: str = ""):
        """清除 ESJZone 登录态。"""
        if scope == "all":
            yield event.plain_result("清除全部登录态需要管理员权限，请使用管理员账号执行。")
            return
        if event.get_group_id():
            yield event.plain_result("退出登录请私聊机器人执行 /esj logout")
            return
        removed = await self.auth_service.logout_user(event)
        yield event.plain_result("已清除当前用户登录态。" if removed else "当前用户没有保存登录态。")

    @esj.command("db")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def esj_dashboard(self, event: AstrMessageEvent, action: str = "status"):
        """管理员开启、关闭或查看 Dashboard 状态。"""
        action = (action or "status").lower()
        dashboard_cfg = self._cfg("dashboard", {})
        if action == "on":
            self._set_nested_cfg("dashboard", "enabled", True)
            auth_enabled = self._cfg("dashboard", {}).get("auth_enabled", True)
            yield event.plain_result(
                "Dashboard 已开启。\n"
                "访问插件 Pages 中的 dashboard 页面即可查看本地书库。\n"
                f"当前 Token 验证：{'已启用' if auth_enabled else '未启用'}。"
            )
        elif action == "off":
            self._set_nested_cfg("dashboard", "enabled", False)
            yield event.plain_result("Dashboard 已关闭。\nWebUI 只显示未启用提示，高风险 API 将拒绝访问。")
        else:
            token_set = bool(dashboard_cfg.get("token"))
            yield event.plain_result(
                "Dashboard 状态：\n"
                f"启用：{'是' if dashboard_cfg.get('enabled') else '否'}\n"
                f"Token 验证：{'是' if dashboard_cfg.get('auth_enabled', True) else '否'}\n"
                f"Token：{'已设置' if token_set else '未设置'}"
            )

    @esj.command("clear")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def esj_clear(self, event: AstrMessageEvent, target: str = "", book_id: str = ""):
        """管理员清理 ESJZone 下载缓存。"""
        target = (target or "").lower()
        try:
            if target == "cache":
                count = self.repository.clear_cache()
                yield event.plain_result(f"已清理章节缓存：{count} 项。")
            elif target == "outputs":
                count = self.repository.clear_outputs()
                yield event.plain_result(f"已清理输出和压缩包：{count} 项。")
            elif target == "book" and book_id:
                ok = self.repository.clear_book(book_id)
                yield event.plain_result(f"已删除书籍 {book_id}。" if ok else f"未找到书籍 {book_id}。")
            else:
                yield event.plain_result(
                    "清理命令：\n"
                    "/esj clear cache\n"
                    "/esj clear outputs\n"
                    "/esj clear book <编号>\n"
                    "cookies/books/all 属于高风险操作，当前版本暂未开放。"
                )
        except Exception as exc:
            logger.exception("esj clear failed")
            yield event.plain_result(f"清理失败：{exc}")

    async def api_books(self):
        disabled = self._dashboard_disabled_response()
        if disabled:
            return disabled
        auth = self._check_dashboard_token()
        if auth:
            return auth
        return jsonify({"books": self.repository.list_books()})

    async def api_book_detail(self):
        disabled = self._dashboard_disabled_response()
        if disabled:
            return disabled
        auth = self._check_dashboard_token()
        if auth:
            return auth
        book_id = request.args.get("book_id", "")
        status = self.repository.load_status(book_id)
        return jsonify({"book": status})

    async def api_book_delete(self):
        disabled = self._dashboard_disabled_response()
        if disabled:
            return disabled
        auth = self._check_dashboard_token()
        if auth:
            return auth
        data = await request.get_json()
        book_id = (data or {}).get("book_id", "")
        ok = self.repository.clear_book(book_id) if book_id else False
        return jsonify({"ok": ok})

    async def api_file_download(self):
        disabled = self._dashboard_disabled_response()
        if disabled:
            return disabled
        auth = self._check_dashboard_token()
        if auth:
            return auth
        relative = request.args.get("path", "")
        target = ensure_within_base(self.data_dir, self.data_dir / relative)
        if not target.exists() or not target.is_file():
            return jsonify({"error": "file not found"}), 404
        return await send_file(target, as_attachment=True)

    async def api_token_check(self):
        disabled = self._dashboard_disabled_response()
        if disabled:
            return disabled
        auth = self._check_dashboard_token()
        if auth:
            return auth
        return jsonify({"ok": True})

    def _dashboard_disabled_response(self):
        dashboard_cfg = self._cfg("dashboard", {})
        if not dashboard_cfg.get("enabled", False):
            return jsonify({"error": "dashboard disabled"}), 403
        return None

    def _check_dashboard_token(self):
        import secrets

        dashboard_cfg = self._cfg("dashboard", {})
        if not dashboard_cfg.get("auth_enabled", True):
            return None
        token = request.headers.get("X-ESJ-Token") or request.args.get("token") or ""
        expected = dashboard_cfg.get("token", "")
        if not token or not expected or not secrets.compare_digest(token, expected):
            return jsonify({"error": "invalid token"}), 403
        return None

    async def terminate(self):
        await self.client.close()
