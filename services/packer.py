from __future__ import annotations

import secrets
import string
from pathlib import Path
from typing import Mapping

import pyzipper


class ZipPacker:
    def __init__(self, config: Mapping):
        self.config = config

    def build_password(self, book_id: str) -> str:
        zip_conf = self.config.get("zip", {})
        mode = zip_conf.get("password_mode", "book_id")
        if mode == "fixed":
            return zip_conf.get("fixed_password") or "esjzone"
        if mode == "random":
            length = int(zip_conf.get("random_password_length") or 8)
            alphabet = string.ascii_letters + string.digits
            return "".join(secrets.choice(alphabet) for _ in range(length))
        return f"esj{book_id}"

    def pack(self, book_dir: Path, output_file: Path, book_id: str, safe_title: str) -> tuple[Path, str]:
        package_path = book_dir / "packages" / f"{safe_title}.zip"
        password = self.build_password(book_id)
        with pyzipper.AESZipFile(package_path, "w", compression=pyzipper.ZIP_DEFLATED, encryption=pyzipper.WZ_AES) as zf:
            zf.setpassword(password.encode("utf-8"))
            zf.write(output_file, arcname=output_file.name)
        return package_path, password
