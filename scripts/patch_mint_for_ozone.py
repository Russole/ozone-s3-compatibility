#!/usr/bin/env python3

import argparse
from pathlib import Path
import sys


CONTENT = """#!/bin/bash -e
#
#  Mint (C) 2017 Minio, Inc.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#

# Ozone compatibility patch: avoid raw.githubusercontent.com transient HTML
# responses by cloning the tagged minio-go source directly.
MINIO_GO_VERSION=$(git ls-remote --refs --tags https://github.com/minio/minio-go.git 'v*' | awk '{print $2}' | sed 's#refs/tags/##' | sort -V | tail -n 1)
if [ -z "$MINIO_GO_VERSION" ]; then
\techo "unable to get minio-go version from git tags"
\texit 1
fi

test_run_dir="$MINT_RUN_CORE_DIR/minio-go"
tmp_dir=$(mktemp -d)
cleanup() {
\trm -rf "$tmp_dir"
}
trap cleanup EXIT

git clone --depth 1 --branch "$MINIO_GO_VERSION" https://github.com/minio/minio-go.git "$tmp_dir/minio-go"
cp "$tmp_dir/minio-go/functional_tests.go" "${test_run_dir}/main.go"

if ! grep -Eq '^(package main|//go:build)' "${test_run_dir}/main.go"; then
\techo "downloaded functional_tests.go does not look like Go source"
\tsed -n '1,20p' "${test_run_dir}/main.go"
\texit 1
fi

# Extract only the function from versioning_test.go (skip package, imports, comments)
# Start from line 34 where the function definition begins
tail -n +34 "${test_run_dir}/versioning_test.go" >>"${test_run_dir}/main.go"

# Patch functional_tests.go to call our versioning test
# Add testBucketVersioningExcludedPrefixes() call after testStatObjectWithVersioning()
sed -i.bak '/testStatObjectWithVersioning()/a\\
\t\ttestBucketVersioningExcludedPrefixes()
' "${test_run_dir}/main.go"

# Build the combined file
(cd "$test_run_dir" && go mod tidy -compat=1.21 && CGO_ENABLED=0 go build --ldflags "-s -w" -o minio-go main.go)
"""


MC_DOWNLOAD = '''$WGET --output-document="${test_run_dir}/mc" "https://dl.minio.io/client/mc/release/linux-amd64/mc.${MC_VERSION}"
chmod a+x "${test_run_dir}/mc"

git clone --quiet https://github.com/minio/mc.git "$test_run_dir/mc.git"
(
	cd "$test_run_dir/mc.git"
	git checkout --quiet "tags/${MC_VERSION}"
)'''

MC_BUILD = '''# MinIO retired its binary downloads; build the same tag as the functional tests.
git clone --quiet --depth 1 --branch "$MC_VERSION" https://github.com/minio/mc.git "$test_run_dir/mc.git"
(
	cd "$test_run_dir/mc.git"
	CGO_ENABLED=0 go build -trimpath -tags kqueue -ldflags "-s -w" -o "${test_run_dir}/mc" .
)'''


def patch_repo(repo: Path) -> None:
    target = repo / "build" / "minio-go" / "install.sh"
    if not target.exists():
        raise FileNotFoundError(f"missing target file: {target}")

    if target.read_text() != CONTENT:
        target.write_text(CONTENT)
        target.chmod(0o755)

    target = repo / "build" / "mc" / "install.sh"
    source = target.read_text()
    if MC_BUILD in source:
        return
    if MC_DOWNLOAD not in source:
        raise ValueError(f"unrecognized mc installer: {target}")
    target.write_text(source.replace(MC_DOWNLOAD, MC_BUILD))
    target.chmod(0o755)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, help="Path to the checked-out mint repository")
    args = parser.parse_args()

    patch_repo(Path(args.repo))
    return 0


if __name__ == "__main__":
    sys.exit(main())
