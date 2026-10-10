"""Include console resources in distributions without duplicating source assets."""

from pathlib import Path
from shutil import copytree

from setuptools import setup
from setuptools.command.build_py import build_py


class BuildWithResources(build_py):
    def run(self):
        super().run()
        root = Path(__file__).parent
        target = Path(self.build_lib) / "xtract" / "resources"
        for source, name in (
            ("apps/operator-portal", "operator-portal"),
            ("assets/branding", "branding"),
        ):
            copytree(root / source, target / name, dirs_exist_ok=True)


setup(cmdclass={"build_py": BuildWithResources})
