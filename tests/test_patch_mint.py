import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from patch_mint_for_ozone import patch_repo


# Download/build section from the pinned Mint mc installer.
MC_INSTALLER = '''#!/bin/bash -e
test_run_dir="$MINT_RUN_CORE_DIR/mc"
MC_VERSION=release-for-test
$WGET --output-document="${test_run_dir}/mc" "https://dl.minio.io/client/mc/release/linux-amd64/mc.${MC_VERSION}"
chmod a+x "${test_run_dir}/mc"

git clone --quiet https://github.com/minio/mc.git "$test_run_dir/mc.git"
(
	cd "$test_run_dir/mc.git"
	git checkout --quiet "tags/${MC_VERSION}"
)
cp -a "${test_run_dir}/mc.git/functional-tests.sh" "$test_run_dir/"
rm -fr "$test_run_dir/mc.git"
'''


class MintPatchTests(unittest.TestCase):
    def test_mc_installer_builds_matching_source_and_propagates_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            for name, source in (("minio-go", "#!/bin/bash\n"), ("mc", MC_INSTALLER)):
                installer = repo / "build" / name / "install.sh"
                installer.parent.mkdir(parents=True)
                installer.write_text(source)
            patch_repo(repo)
            patched = installer.read_text()
            patch_repo(repo)
            self.assertEqual(patched, installer.read_text())

            commands = repo / "bin"
            commands.mkdir()
            # Fake only the network and compiler; execute the actual patched installer.
            (commands / "git").write_text('''#!/bin/bash -e
[[ "$*" == "clone --quiet --depth 1 --branch release-for-test https://github.com/minio/mc.git "* ]]
mkdir -p "${@: -1}"
echo release-for-test > "${@: -1}/functional-tests.sh"
''')
            (commands / "go").write_text('''#!/bin/bash -e
[[ "$CGO_ENABLED" == 0 && "$*" == "build "* ]]
[[ -f functional-tests.sh ]]
if [[ "${FAIL_BUILD:-0}" == 1 ]]; then exit 42; fi
while [[ "$1" != -o ]]; do shift; done
echo compiled > "$2"
''')
            for command in commands.iterdir():
                command.chmod(0o755)
            run_dir = repo / "run" / "core"
            (run_dir / "mc").mkdir(parents=True)
            env = dict(os.environ, PATH=f"{commands}:{os.environ['PATH']}", MINT_RUN_CORE_DIR=str(run_dir), WGET="false")
            subprocess.run([str(installer)], env=env, check=True)
            self.assertEqual("compiled\n", (run_dir / "mc" / "mc").read_text())
            self.assertEqual("release-for-test\n", (run_dir / "mc" / "functional-tests.sh").read_text())
            result = subprocess.run([str(installer)], env=dict(env, FAIL_BUILD="1"))
            self.assertEqual(42, result.returncode)


if __name__ == "__main__":
    unittest.main()
