"""Empaqueta `<proyecto>/.an-kla` en un tar determinista (sin mtime, uid ni nombres de usuario)."""
import sys, tarfile
from pathlib import Path

proyecto, destino = Path(sys.argv[1]), Path(sys.argv[2])
raiz = proyecto / ".an-kla"
miembros = [raiz, *sorted(raiz.rglob("*"), key=lambda p: p.as_posix())]
with tarfile.open(destino, "w", format=tarfile.USTAR_FORMAT) as tar:
    for ruta in miembros:
        info = tar.gettarinfo(str(ruta), arcname=ruta.relative_to(proyecto).as_posix())
        info.mtime, info.uid, info.gid, info.uname, info.gname = 0, 0, 0, "", ""
        info.mode = 0o700 if info.isdir() else (0o600 if info.mode & 0o077 == 0 else 0o644)
        if info.isfile():
            with ruta.open("rb") as fh:
                tar.addfile(info, fh)
        else:
            tar.addfile(info)
