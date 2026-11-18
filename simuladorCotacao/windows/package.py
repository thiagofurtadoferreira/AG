"""Monta o ZIP portátil com o runtime e as wheels Windows já baixados."""
import argparse
import hashlib
from pathlib import Path
import shutil
import subprocess
import tempfile
from zipfile import ZipFile, ZIP_DEFLATED

VERSION = "0.2.0"
PROJECT = Path(__file__).resolve().parents[1]
FILES = ("app.py", "estrategia.py", "ntsl.py", "interface.html", "simulador.py",
         "modelo_profit.ntsl", "config_v6.json", "config_v7.json", "README.md",
         "CHANGELOG.md", "README-otimizador.md", "requirements.txt", "VERSION", "exemplo_cruzamento.ntsl")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python-win",required=True,type=Path)
    parser.add_argument("--wheels",required=True,type=Path)
    parser.add_argument("--gcc",default="x86_64-w64-mingw32-gcc")
    parser.add_argument("--windres",default="x86_64-w64-mingw32-windres")
    parser.add_argument("--saida",required=True,type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)/f"simuladorCotacao-v{VERSION}"
        root.mkdir()
        for filename in FILES:
            shutil.copy2(PROJECT/filename,root/filename)
        shutil.copytree(PROJECT/"windows",root/"windows",ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(PROJECT/"exemplos",root/"exemplos")
        runtime = root/"runtime"
        with ZipFile(args.python_win) as archive:
            archive.extractall(runtime)
        site = runtime/"Lib"/"site-packages"
        site.mkdir(parents=True)
        for wheel in sorted(args.wheels.glob("*.whl")):
            with ZipFile(wheel) as archive:
                archive.extractall(site)
        (runtime/"python312._pth").write_text("python312.zip\n.\nLib\\site-packages\n..\nimport site\n",encoding="ascii")
        version = Path(tmp)/"version.o"
        subprocess.run([args.windres,"--preprocessor",args.gcc,"--preprocessor-arg=-E","--preprocessor-arg=-xc-header",str(PROJECT/"windows/version.rc"),str(version)],check=True)
        common = [args.gcc,"-O2","-Wall","-Wextra","-municode","-static","-s",
                  str(PROJECT/"windows/launcher.c"),str(version)]
        subprocess.run([*common,"-mwindows","-o",str(root/"SimuladorCotacao.exe")],check=True)
        subprocess.run([*common,"-DCONSOLE","-mconsole","-o",str(root/"SimuladorCotacao-CLI.exe")],check=True)
        checked = []
        for file in sorted(root.rglob("*")):
            if file.is_file():
                with file.open("rb") as stream:
                    digest = hashlib.file_digest(stream,"sha256").hexdigest()
                checked.append(f"{digest}  {file.relative_to(root).as_posix()}")
        (root/"SHA256SUMS.txt").write_text("\n".join(checked)+"\n",encoding="utf-8")
        with ZipFile(args.saida,"w",ZIP_DEFLATED,compresslevel=6) as archive:
            for file in sorted(root.rglob("*")):
                if file.is_file():
                    archive.write(file,file.relative_to(root.parent))


if __name__=="__main__":
    main()
