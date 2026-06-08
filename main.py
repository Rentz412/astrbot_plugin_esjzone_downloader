"""AstrBot 插件入口模块。

负责初始化 ESJZone 下载器的核心服务、注册聊天命令，并将用户请求路由到认证、下载、仓储等服务层。"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from quart import jsonify, send_file

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
import astrbot.api.message_components as Comp
from astrbot.api.star import Context, Star, register
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

from .services.auth import EsjAuthService
from .services.dashboard import DashboardService, guess_mime
from .services.downloader import EsjDownloader
from .services.favorite import FavoriteRefreshCooldown, FavoriteService
from .services.repository import EsjRepository
from .services.task_manager import TaskManager

PLUGIN_NAME = "astrbot_plugin_esjzone_downloader"


@register(
    PLUGIN_NAME,
    "Rentz",
    "ESJZone 小说下载器，支持登录、EPUB/TXT 导出和 ZIP 打包。",
    "2.3.0",
)
class EsjZoneDownloaderPlugin(Star):
    """AstrBot 插件主类，负责连接聊天命令与底层下载服务。"""
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
        self.favorite_service = FavoriteService(self.data_dir, self.config, logger)
        self.repository = EsjRepository(self.data_dir)
        self.dashboard_service = DashboardService(self.data_dir, Path(__file__).parent)
        self.task_manager = TaskManager()
        self._register_dashboard_apis()

    def _ensure_config_defaults(self) -> None:
        """补齐缺省配置，避免旧配置缺字段导致运行时报错。"""
        self.config.setdefault("download", {})
        self.config["download"].setdefault("allow_external_images", True)

        self.config.setdefault("message", {})
        msg = self.config["message"]
        msg.setdefault("private_verbose_status", True)
        msg.setdefault("group_verbose_status", False)
        msg.setdefault("group_mention_user", True)

        self.config.setdefault("favorite", {})
        fav = self.config["favorite"]
        fav.setdefault("passive_refresh_ttl_seconds", 600)
        fav.setdefault("manual_refresh_cd_seconds", 60)
        fav.setdefault("page_size", 20)
        fav.setdefault("max_pages", 50)
        fav.setdefault("send_forward", True)
        fav.setdefault("save_raw_html", False)

        self.config.setdefault("debug", {})
        dbg = self.config["debug"]
        dbg.setdefault("enabled", False)
        dbg.setdefault("save_pages", True)
        dbg.setdefault("save_auth_pages", False)
        dbg.setdefault("save_chapter_pages", False)

    def _register_dashboard_apis(self) -> None:
        """注册 AstrBot Plugin Page 使用的 Dashboard API。"""
        # register_web_api 会把路由挂到 /api/plug/<插件名>/... 下；
        # 前端 bridge.apiGet/bridge.apiPost 只需要传入去掉插件名前缀后的相对端点。
        routes = [
            ("dashboard/cache", self.dashboard_cache, ["GET"], "Read ESJZone dashboard cache"),
            ("dashboard/refresh", self.dashboard_refresh, ["POST"], "Refresh ESJZone dashboard cache"),
            ("dashboard/logo", self.dashboard_logo, ["GET"], "Read ESJZone dashboard logo"),
            ("dashboard/books/<book_id>/cover", self.dashboard_book_cover, ["GET"], "Read ESJZone book cover"),
            ("dashboard/books/<book_id>/cover-data", self.dashboard_book_cover_data, ["GET"], "Read ESJZone book cover as data URL"),
            ("dashboard/books/<book_id>", self.dashboard_book_detail, ["GET"], "Read ESJZone book detail"),
            ("dashboard/books/<book_id>/clear-files", self.dashboard_clear_book_files, ["POST"], "Clear one book output files"),
            ("dashboard/books/<book_id>/delete", self.dashboard_delete_book, ["POST"], "Delete one book"),
            ("dashboard/books/clear-all-files", self.dashboard_clear_all_book_files, ["POST"], "Clear all book output files"),
            ("dashboard/books/delete-all", self.dashboard_delete_all_books, ["POST"], "Delete all books"),
            ("dashboard/debug/clear", self.dashboard_clear_debug, ["POST"], "Clear debug files"),
        ]
        for route, handler, methods, desc in routes:
            self.context.register_web_api(f"/{PLUGIN_NAME}/{route}", handler, methods, desc)

    def _refresh_dashboard_cache_quietly(self) -> None:
        """刷新 Dashboard 缓存；失败时不影响聊天命令主流程。"""
        try:
            self.dashboard_service.refresh_cache()
        except Exception:
            logger.warning("Dashboard 缓存刷新失败", exc_info=True)

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

    def _favorite_cfg(self) -> dict[str, Any]:
        """读取收藏列表相关配置，并兼容非字典配置。"""
        cfg = self.config.get("favorite", {}) if hasattr(self.config, "get") else {}
        return cfg if isinstance(cfg, dict) else {}

    def _favorite_page_size(self) -> int:
        """返回收藏列表每页展示数量。"""
        try:
            return max(1, min(int(self._favorite_cfg().get("page_size", 20)), 50))
        except Exception:
            return 20

    def _favorite_parse_page(self, value: str, default: int = 1) -> int:
        """解析收藏列表展示页码。"""
        if not value:
            return default
        if not str(value).isdigit():
            return default
        return max(1, int(value))

    def _favorite_help_text(self) -> str:
        """生成收藏列表命令帮助。"""
        return (
            "ESJZone 收藏列表命令：\n\n"
            "/esj f                 查看个人收藏列表第 1 页\n"
            "/esj f <页码>          查看个人收藏列表指定页\n"
            "/esj f refresh         手动刷新收藏列表\n"
            "/esj f refresh <页码>  手动刷新后查看指定页\n"
            "/esj f clear           清除当前用户收藏缓存\n\n"
            "说明：普通查看会在缓存超过设定时间后自动刷新；手动刷新有冷却时间。"
        )

    @staticmethod
    def _favorite_book_text(book) -> str:
        """格式化单本收藏书籍。"""
        lines = [
            f"{book.index}. {book.title}",
            book.url,
        ]
        if book.latest:
            lines.append(f"最新：{book.latest}")
        if book.last_read:
            lines.append(f"最後觀看：{book.last_read}")
        if book.updated_at:
            lines.append(f"更新日期：{book.updated_at}")
        return "\n".join(lines)

    def _favorite_page_items(self, result, page: int) -> tuple[list, int, int]:
        """根据展示页码切片收藏条目。"""
        page_size = self._favorite_page_size()
        total = len(result.items)
        total_pages = max((total + page_size - 1) // page_size, 1)
        page = min(max(page, 1), total_pages)
        start = (page - 1) * page_size
        return result.items[start:start + page_size], page, total_pages

    def _favorite_summary_text(self, result, page: int, total_pages: int) -> str:
        """生成收藏列表摘要文本。"""
        page_size = self._favorite_page_size()
        source_host = result.source_host or "www.esjzone.one"
        status = result.status_message or ("使用缓存数据" if result.from_cache else "获取成功")
        lines = [
            "ESJZone 收藏列表",
            "",
            f"{result.username}的收藏列表上次更新于：{result.fetched_at_text or '未知'}",
            "如需手动刷新请发送：/esj f refresh",
            "",
            f"共 {len(result.items)} 本",
            f"第 {page}/{total_pages} 页，每页 {page_size} 本",
            f"来源：{source_host}",
            f"状态：{status}",
        ]
        if result.error_message:
            lines.append(f"失败原因：{result.error_message}")
        if page < total_pages:
            lines.append(f"下一页：/esj f {page + 1}")
        return "\n".join(lines)

    def _favorite_fallback_text(self, result, page: int) -> str:
        """生成普通文本 fallback。"""
        items, page, total_pages = self._favorite_page_items(result, page)
        blocks = [self._favorite_summary_text(result, page, total_pages)]
        blocks.extend(self._favorite_book_text(item) for item in items)
        return "\n\n".join(blocks)

    def _favorite_forward_chain(self, event: AstrMessageEvent, result, page: int) -> list:
        """生成单条合并转发消息链。

        注意：多个 Node 直接放进消息链时，部分 OneBot 适配器会拆成多条合并消息；
        因此这里优先用 Nodes 包装全部 Node，确保最终只发送一条合并转发。
        """
        items, page, total_pages = self._favorite_page_items(result, page)
        try:
            uin = int(event.get_sender_id())
        except Exception:
            uin = 10000
        try:
            name = event.get_sender_name() or "ESJZone"
        except Exception:
            name = "ESJZone"

        texts = [self._favorite_summary_text(result, page, total_pages)]
        texts.extend(self._favorite_book_text(item) for item in items)
        nodes = [
            Comp.Node(
                uin=uin,
                name=name,
                content=[Comp.Plain(text)],
            )
            for text in texts
        ]

        nodes_cls = getattr(Comp, "Nodes", None)
        if not nodes_cls:
            raise RuntimeError("当前 AstrBot 消息组件不支持 Nodes 合并转发容器")

        # 兼容不同 AstrBot 版本里 Nodes 构造参数命名差异。
        for kwargs in ({"nodes": nodes}, {"content": nodes}, {"node": nodes}):
            try:
                return [nodes_cls(**kwargs)]
            except TypeError:
                pass

        try:
            return [nodes_cls(nodes)]
        except TypeError:
            pass

        container = nodes_cls()
        for attr in ("nodes", "content", "node"):
            try:
                setattr(container, attr, nodes)
                return [container]
            except Exception:
                pass
        raise RuntimeError("无法构造 Nodes 合并转发容器")

    async def _send_favorite_result(self, event: AstrMessageEvent, result, page: int):
        """优先用单条合并转发发送收藏列表，失败则降级普通文本。"""
        cfg = self._favorite_cfg()
        fallback_text = self._favorite_fallback_text(result, page)
        if bool(cfg.get("send_forward", True)):
            try:
                await event.send(event.chain_result(self._favorite_forward_chain(event, result, page)))
                return
            except Exception:
                logger.warning("收藏列表合并转发发送失败，降级为普通文本", exc_info=True)
        yield self._reply(event, fallback_text)

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
            "/esj f [页码]           查看个人收藏列表\n"
            "/esj f refresh [页码]   手动刷新个人收藏列表\n"
            "/esj l <邮箱> <密码>    私聊登录并保存 Cookie\n"
            "/esj logout             私聊清除当前用户 Cookie\n"
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

    @esj.command("favor", alias={"f", "favorite"})
    async def esj_favor(self, event: AstrMessageEvent, arg1: str = "", arg2: str = ""):
        """查看个人 ESJZone 收藏列表。"""
        action = (arg1 or "").strip().lower()
        page_arg = arg2 if action in {"refresh", "clear", "help"} else arg1
        page = self._favorite_parse_page(page_arg)

        if action in {"help", "h", "?"}:
            yield event.plain_result(self._favorite_help_text())
            return

        auth = await self.auth_service.require_auth_or_reply(event)
        if not auth:
            yield event.plain_result(self._not_login_text(event))
            return

        if action == "clear":
            ok = self.favorite_service.clear_cache(auth)
            yield event.plain_result("已清除当前用户的收藏列表缓存。" if ok else "当前用户没有收藏列表缓存。")
            return

        force_refresh = action == "refresh"
        if action and not action.isdigit() and action != "refresh":
            yield event.plain_result(self._favorite_help_text())
            return

        try:
            result = await self.favorite_service.get_favorites(auth, force_refresh=force_refresh)
        except FavoriteRefreshCooldown as exc:
            yield event.plain_result(f"手动刷新过于频繁，请 {exc.remaining_seconds} 秒后再试。")
            return
        except Exception as exc:
            logger.exception("获取收藏列表失败")
            yield event.plain_result(f"获取收藏列表失败：{exc}")
            return

        if not result.items:
            yield self._reply(
                event,
                (
                    f"{result.username}的收藏列表为空。\n"
                    f"上次更新于：{result.fetched_at_text or '未知'}\n"
                    "如需手动刷新请发送：/esj f refresh"
                ),
            )
            return

        async for message in self._send_favorite_result(event, result, page):
            yield message

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

        # 兼容 /esj d <编号> <起始章节> [结束章节] 这种省略格式的写法。
        # AstrBot 会把第一个可选参数先绑定到 fmt，因此这里检测数字并把参数右移回章节范围。
        if str(fmt or "").isdigit():
            range_start = int(fmt)
            range_end = start
            fmt = ""
            start = range_start
            end = range_end

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
                        "请联系管理员在 AstrBot 数据目录中查看导出文件。"
                    )
                else:
                    text = "文件发送失败，请私聊机器人或联系管理员查看。"
                yield self._reply(event, text)
            finally:
                # packages/ 下的 ZIP 是临时发送产物；章节缓存、导出文件和 manifest 会继续保留复用。
                try:
                    if package_path.exists():
                        package_path.unlink()
                        logger.info(f"已清理临时 ZIP 文件：{package_path}")
                except Exception:
                    logger.warning(f"临时 ZIP 文件清理失败：{package_path}", exc_info=True)
                self._refresh_dashboard_cache_quietly()
        except Exception as exc:
            logger.exception("下载失败")
            yield event.plain_result(f"下载失败：{exc}")
        finally:
            self.task_manager.leave_session(session_key)

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

    async def dashboard_cache(self):
        """返回 Dashboard 缓存。"""
        return jsonify(self.dashboard_service.load_cache())

    async def dashboard_refresh(self):
        """强制刷新 Dashboard 缓存。"""
        return jsonify(self.dashboard_service.refresh_cache())

    async def dashboard_logo(self):
        """返回插件 Logo。"""
        path = self.dashboard_service.logo_path()
        if not path:
            return jsonify({"error": "logo not found"}), 404
        return await send_file(path, mimetype=guess_mime(path))

    async def dashboard_book_cover(self, book_id: str):
        """返回书籍封面。"""
        # 保留二进制封面接口，便于浏览器直接访问或调试。
        path = self.dashboard_service.cover_path(book_id)
        if not path:
            return jsonify({"error": "cover not found"}), 404
        return await send_file(path, mimetype=guess_mime(path))

    async def dashboard_book_cover_data(self, book_id: str):
        """返回书籍封面的 data URL，供 Plugin Page 通过 bridge.apiGet 鉴权读取。"""
        # Plugin Page 的 iframe 直接把 /api/plug/... 作为 img src 时可能拿不到 Dashboard 鉴权；
        # 因此前端通过 bridge.apiGet 请求本接口，再把 data_url 赋给 img.src。
        path = self.dashboard_service.cover_path(book_id)
        if not path:
            return jsonify({"error": "cover not found"}), 404
        mime = guess_mime(path)
        data = base64.b64encode(path.read_bytes()).decode("ascii")
        return jsonify({
            "book_id": book_id,
            "name": path.name,
            "mime": mime,
            "data_url": f"data:{mime};base64,{data}",
        })

    async def dashboard_book_detail(self, book_id: str):
        """返回单本书详情。"""
        book = self.dashboard_service.get_book(book_id)
        if not book:
            return jsonify({"error": "book not found"}), 404
        return jsonify(book)

    async def dashboard_clear_book_files(self, book_id: str):
        """清除单本书 TXT/EPUB 与对应 manifest。"""
        return jsonify(self.dashboard_service.clear_book_files(book_id))

    async def dashboard_delete_book(self, book_id: str):
        """删除单本书全部本地数据。"""
        return jsonify(self.dashboard_service.delete_book(book_id))

    async def dashboard_clear_all_book_files(self):
        """清除所有书籍 TXT/EPUB 与对应 manifest。"""
        return jsonify(self.dashboard_service.clear_all_book_files())

    async def dashboard_delete_all_books(self):
        """删除全部本地书籍数据。"""
        return jsonify(self.dashboard_service.delete_all_books())

    async def dashboard_clear_debug(self):
        """清理调试文件。"""
        return jsonify(self.dashboard_service.clear_debug())

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
