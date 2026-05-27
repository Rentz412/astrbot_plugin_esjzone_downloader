from __future__ import annotations

import secrets
import string
import zipfile
from pathlib import Path

import pyzipper


class ZipPacker:
    def make_password(
        self,
        book_id: str,
        mode: str = "book_id",
        fixed_password: str = "esjzone",
        random_length: int = 8,
    ) -> str:
        if mode == "fixed":
            return fixed_password or "esjzone"
        if mode == "random":
            alphabet = string.ascii_letters + string.digits
            return "".join(secrets.choice(alphabet) for _ in range(max(4, random_length)))
        return f"esj{book_id}"

    def pack(self, files: list[Path], package_path: Path, password: str) -> tuple[Path, bool]:
        package_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with pyzipper.AESZipFile(
                package_path,
                "w",
                compression=zipfile.ZIP_DEFLATED,
                encryption=pyzipper.WZ_AES,
            ) as zip_file:
                zip_file.setpassword(password.encode("utf-8"))
                for file in files:
                    if file.exists():
                        zip_file.write(file, arcname=file.name)
            return package_path, True
        except Exception:
            with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_DEFLATED) as zip_file:
                for file in files:
                    if file.exists():
                        zip_file.write(file, arcname=file.name)
            return package_path, False
