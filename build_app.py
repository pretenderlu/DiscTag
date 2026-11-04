import subprocess
import sys
from pathlib import Path


if __name__ == "__main__":
    project = Path(__file__).resolve().parent
    subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", str(project / "DiscTag.spec")],
        cwd=project,
        check=True,
    )
    if sys.platform == "darwin":
        print(f"Application: {project / 'dist' / 'DiscTag.app'}")
    else:
        print(f"Application: {project / 'dist' / 'DiscTag' / 'DiscTag.exe'}")
