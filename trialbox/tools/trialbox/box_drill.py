"""Run the installed box's drill with the same clients that made its backup.

The host orchestrates and holds the private work directory. Only the unpack step sees the key.
The database container's bootstrap role creates and drops databases. The workflow owner restores
and checks the data in them. No connection string or password goes into a process argument.
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Mapping
from functools import cached_property
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from tools.trialbox import restore_drill as rd
from tools.trialbox.backup_schedule import ComposeOps
from tools.trialbox.update import UpdateFailed

DATABASES = ("trialbox_wf", "hapi")
MODULE = "tools.trialbox.box_drill"


class BoxDrill(ComposeOps):
    def __init__(self, deploy: Path) -> None:
        super().__init__(deploy)
        self.image = self.env.get("TB_IMAGE") or "trialbox-py:1.0.0"
        self.url = self.env.get("TB_DB_URL", "")
        site = urlsplit(self.url)
        self.owner = unquote(site.username or "")
        self.live_names = {unquote(site.path.lstrip("/")), *DATABASES}
        self.created: set[str] = set()
        if not self.owner:
            raise rd.DrillError(
                "check TB_DB_URL in deploy/.env / 請檢查 deploy/.env 的 TB_DB_URL / "
                "deploy/.env の TB_DB_URL を確認してください"
            )

    @cached_property
    def database_id(self) -> str:
        ident = self.box.run(self.box._c("ps", "-q", "db")).strip()
        if not ident:
            raise rd.DrillError("database is stopped / 資料庫已停止 / データベースが停止しています")
        return ident

    def data_dir(self) -> Path:
        mounts = json.loads(self.box.run([*self.box.docker, "inspect", "-f", "{{json .Mounts}}", self.database_id]))
        for mount in mounts:
            if mount["Destination"] == "/var/lib/postgresql/data":
                return Path(mount["Source"])
        raise rd.DrillError(
            "set --db-dir to the database volume / 請用 --db-dir 指定資料庫資料卷 / "
            "--db-dir でデータベースボリュームを指定してください"
        )

    def unpack(self, file: Path, key: Path, into: Path) -> dict[str, Any]:
        # Keep the original file name for verification of its SHA-256 sidecar.
        if not key.is_file():
            raise rd.DrillError("key file missing / 找不到金鑰檔 / 鍵ファイルがありません")
        backup = Path("/backup") / file.name
        mounts = ["-v", f"{file.resolve()}:{backup}:ro"]
        checksum = file.with_name(file.name + ".sha256")
        if checksum.is_file():
            mounts += ["-v", f"{checksum.resolve()}:{backup}.sha256:ro"]
        args = [*self.box.docker, "run", "--rm", "--pull=never", "--network", "none", "--user", "0:0",
                "-v", f"{into.resolve()}:/work", *mounts,
                "-v", f"{key.resolve()}:/key:ro", self.image, "python", "-m", MODULE,
                "unpack", str(backup), "/key"]  # fmt: skip
        try:
            result: dict[str, Any] = json.loads(self.box.run(args))
        except UpdateFailed:
            # A mount error may contain the host key path. Keep it out of the persistent drill record.
            raise rd.DrillError(
                "cannot open or verify backup / 無法開啟或驗證備份 / バックアップを開くか検証できません"
            ) from None
        return result

    def create(self, db: str, name: str) -> None:
        if db not in DATABASES or name in self.live_names or not re.fullmatch(rf"tb_drill_[0-9a-f]{{8}}_{db}", name):
            raise rd.DrillError("invalid scratch database / 暫存資料庫名稱無效 / 一時データベース名が無効です")
        self.created.add(name)  # before the server answers: a lost acknowledgement is still dropped (IF EXISTS)
        self.box.run(
            self.box._c(
                "exec",
                "-T",
                "db",
                "sh",
                "-ec",
                'exec createdb --username "$POSTGRES_USER" --maintenance-db "$POSTGRES_DB" --owner "$1" -- "$2"',
                "sh",
                self.owner,
                name,
            )
        )

    def restore_compare(self, db: str, name: str, into: Path, want: Mapping[str, Any]) -> list[str]:
        try:
            self.box.run(
                self.box._c(
                    "exec",
                    "-T",
                    "db",
                    "pg_restore",
                    "--username",
                    self.owner,
                    "--dbname",
                    name,
                    "--no-owner",
                    "--no-privileges",
                    "--single-transaction",
                    "--exit-on-error",
                ),
                stdin_file=into / "db" / f"{db}.dump",
            )
            # Join the database container's network namespace. The client can resolve the installed URL without
            # publishing a port, loading a service's other secrets or mounting any live application volumes.
            args = [*self.box.docker, "run", "--rm", "--pull=never", "--network", f"container:{self.database_id}",
                    "--user", "0:0", "-v", f"{into.resolve()}:/work:ro", "-e", "TB_DB_URL",
                    self.image, "python", "-m", MODULE, "compare", db, name]  # fmt: skip
            diff: list[str] = json.loads(self.box.run(args, env={"TB_DB_URL": self.url}))
        except UpdateFailed:
            raise rd.DrillError(
                f"{db}: scratch restore or comparison failed / 暫存資料庫還原或比對失敗 / "
                "一時 DB の復元または照合に失敗"
            ) from None
        return diff

    def drop(self, name: str) -> None:
        if name not in self.created:
            raise rd.DrillError("invalid scratch database / 暫存資料庫名稱無效 / 一時データベース名が無効です")
        self.box.run(
            self.box._c(
                "exec",
                "-T",
                "db",
                "sh",
                "-ec",
                'exec dropdb --username "$POSTGRES_USER" --maintenance-db "$POSTGRES_DB" --if-exists --force -- "$1"',
                "sh",
                name,
            )
        )
        self.created.remove(name)


def image_step(args: list[str], work: Path) -> Any:
    from tools.trialbox import backup as bk

    if args[0] == "unpack":
        manifest = bk.unpack(Path(args[1]), Path(args[2]), work, lake_from_restic=False)
        # Only the fields the host needs cross stdout. The full manifest stays in the private work directory.
        return {k: manifest[k] for k in ("created_at", "databases", "_sha256", "files")} | {
            "site": manifest.get("site", "")
        }
    _, db, name = args
    workflow = bk.db_sources({"TB_DB_URL": os.environ["TB_DB_URL"]})[0]
    src = workflow if db == workflow.name else bk.DbSource(db, workflow.dsn, ())
    scratch = rd.scratch_source(src, workflow.dsn, name)
    want = json.loads((work / "manifest.json").read_text())["databases"][db]
    return rd.finish_database(scratch, work, want)


if __name__ == "__main__":
    print(json.dumps(image_step(sys.argv[1:], Path("/work"))))
