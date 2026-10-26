"""Include the existing runtime assets in wheels without moving source files."""

from pathlib import Path

from setuptools.command.build_py import build_py


class BuildPy(build_py):
    def run(self):
        super().run()
        root = Path(__file__).resolve().parents[2]
        destination = Path(self.build_lib) / 'terraproof' / 'data'
        for relative in ('skills', 'routing', 'instructions', 'sources', 'third_party'):
            self.copy_tree(str(root / relative), str(destination / relative))
