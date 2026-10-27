"""Include the existing runtime assets in wheels without moving source files."""

from pathlib import Path
import shutil

from setuptools.command.build_py import build_py


class BuildPy(build_py):
    def run(self):
        root = Path(__file__).resolve().parents[2]
        library = Path(self.build_lib).resolve()
        source = root/'src'
        if library in (root, source) or source in library.parents:
            raise RuntimeError('build output must not be the source checkout')
        super().run()
        destination = Path(self.build_lib) / 'terraproof' / 'data'
        # Excluded packages can survive from an older build_lib. Remove only
        # these private build outputs, after checking their resolved boundaries.
        for private in (library/'terraproof/evals', library/'terraproof/data/evals'):
            if library not in private.resolve().parents:
                raise RuntimeError('private build output escapes build_lib')
            if private.exists():
                shutil.rmtree(private)
        for relative in ('skills', 'routing', 'instructions', 'sources', 'third_party'):
            self.copy_tree(str(root / relative), str(destination / relative))
