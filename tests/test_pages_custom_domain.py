from __future__ import annotations

import unittest
import tomllib
import os
import subprocess
import tempfile
import textwrap
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CUSTOM_DOMAIN = "ozone.s3.peterxcli.dev"


class PagesCustomDomainTests(unittest.TestCase):
    def test_ui_refresh_preserves_report_data_and_rejects_missing_catalog(self) -> None:
        workflow = (ROOT / ".github/workflows/refresh-pages-ui.yml").read_text()
        refresh = textwrap.dedent(workflow.split("      - name: Refresh published UI assets\n        run: |\n")[1].split("\n      - name:")[0])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runs = root / ".pages-repo/data/runs"
            # Enough output to exceed a pipe buffer and expose find | grep -q under pipefail.
            for index in range(2000):
                run = runs / f"2026-09-21T00-00-00Z-{index:04d}"
                run.mkdir(parents=True)
                (run / "metadata.parquet").touch()
            (root / "site/dist").mkdir(parents=True)
            commands = root / "bin"
            commands.mkdir()
            uv = commands / "uv"
            uv.write_text("#!/bin/bash -e\nmkdir -p out/pages-ui-refresh/data/catalog\nprintf catalog > out/pages-ui-refresh/data/catalog/runs.parquet\n")
            uv.chmod(0o755)
            env = dict(os.environ, PATH=f"{commands}:{os.environ['PATH']}")
            subprocess.run(["bash", "-c", refresh], cwd=root, env=env, check=True)
            catalog = root / ".pages-repo/data/catalog/runs.parquet"
            self.assertEqual("catalog", catalog.read_text())
            # With no recoverable runs, an asset-only refresh must stop before rsync.
            result = subprocess.run(["bash", "-c", refresh], cwd=root, env=env)
            self.assertNotEqual(0, result.returncode)
            self.assertEqual("catalog", catalog.read_text())

    def test_vite_public_assets_include_pages_cname(self) -> None:
        cname_path = ROOT / "site" / "public" / "CNAME"

        self.assertTrue(cname_path.exists(), "site/public/CNAME must be published with the built Pages assets")
        self.assertEqual(CUSTOM_DOMAIN, cname_path.read_text(encoding="utf-8").strip())

    def test_refresh_pages_ui_syncs_full_generated_site(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "refresh-pages-ui.yml").read_text(encoding="utf-8")

        self.assertIn('rsync -a --delete --exclude \'.git/\' "${source_dir}/" .pages-repo/', workflow)
        self.assertIn("git -C .pages-repo add -A", workflow)
        self.assertNotIn('cp "${source_dir}/app.js" .pages-repo/app.js', workflow)
        self.assertNotIn('cp "${source_dir}/CNAME" .pages-repo/CNAME', workflow)

    def test_refresh_pages_ui_stages_generated_parquet_data_deletions(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "refresh-pages-ui.yml").read_text(encoding="utf-8")

        self.assertIn('rsync -a --delete --exclude \'.git/\' "${source_dir}/" .pages-repo/', workflow)
        self.assertIn("git -C .pages-repo add -A", workflow)
        self.assertNotIn('cp "${source_dir}/data/search-index.json"', workflow)
        self.assertNotIn("git -C .pages-repo add data/search-index.json", workflow)
        self.assertNotIn("git -C .pages-repo add data/catalog", workflow)
        self.assertNotIn("git -C .pages-repo add data/runs", workflow)

    def test_pages_workflows_publish_parquet_data_by_default(self) -> None:
        nightly = (ROOT / ".github" / "workflows" / "nightly.yml").read_text(encoding="utf-8")
        refresh = (ROOT / ".github" / "workflows" / "refresh-pages-ui.yml").read_text(encoding="utf-8")

        self.assertIn("VITE_REPORT_DATA_FORMAT=parquet npm --prefix site run build", nightly)
        self.assertIn("--data-format parquet", nightly)
        self.assertIn("VITE_REPORT_DATA_FORMAT=parquet npm --prefix site run build", refresh)
        self.assertIn("--data-format parquet", refresh)

    def test_generated_run_directory_is_ignored(self) -> None:
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")

        self.assertIn("run/", gitignore)

    def test_workflows_install_pyarrow_for_parquet_output(self) -> None:
        workflow_paths = [
            ROOT / ".github" / "workflows" / "nightly.yml",
            ROOT / ".github" / "workflows" / "refresh-pages-ui.yml",
            ROOT / ".github" / "workflows" / "ozone-pr-s3-compatibility.yml",
        ]

        for path in workflow_paths:
            with self.subTest(path=path.name):
                workflow = path.read_text(encoding="utf-8")
                self.assertIn("uses: astral-sh/setup-uv@", workflow)
                self.assertIn("uv sync --locked", workflow)
                self.assertNotIn("python3 -m pip install pyarrow", workflow)

    def test_pyarrow_is_managed_by_uv_project_metadata(self) -> None:
        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

        self.assertEqual(">=3.11", pyproject["project"]["requires-python"])
        self.assertIn("pyarrow>=24.0.0", pyproject["project"]["dependencies"])
        self.assertFalse(pyproject["tool"]["uv"]["package"])


if __name__ == "__main__":
    unittest.main()
