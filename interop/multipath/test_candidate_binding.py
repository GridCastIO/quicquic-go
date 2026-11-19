"""MP-MAC #1528: a consumed Go binary is bound to the candidate only by a byte-identical
rebuild from the clean recorded tree. These tests use real git repositories and real Go
builds of a tiny module; other driver tests import this module for the same fixture."""

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.dont_write_bytecode = True
import candidate_binding as binding

MODULE = "example.com/bindingfixture"
# A darwin/arm64 build without cgo, so the fixture is the drivers' domain on any host.
TARGET = {"GOOS": "darwin", "GOARCH": "arm64", "CGO_ENABLED": "0"}
GIT = ("git", "-c", "user.name=fixture", "-c", "user.email=fixture@example.com",
       "-c", "commit.gpgsign=false", "-c", "init.defaultBranch=main")


GO_VERSION = subprocess.run(["go", "env", "GOVERSION"], check=True, capture_output=True, text=True).stdout.strip()


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class FixtureRepo:
    """A git checkout of a tiny Go module: a library package with a test and a command."""

    def __init__(self, root):
        self.root = Path(root) / "source"
        self.bin = Path(root) / "bin"
        self.bin.mkdir()
        self.root.mkdir()
        self.git("init", "-q")
        self.write("go.mod", f"module {MODULE}\n\ngo 1.26\n")
        self.write(".gitignore", "*_ignored.go\n")
        self.write("fixture.go", 'package bindingfixture\n\nconst Version = "one"\n')
        self.write("fixture_test.go", 'package bindingfixture\n\nimport "testing"\n\n'
                   'func TestVersion(t *testing.T) {\n\tif Version == "" {\n\t\tt.Fatal("empty")\n\t}\n}\n')
        self.write("cmd/tool/main.go", f'package main\n\nimport (\n\t"fmt"\n\n\tfixture "{MODULE}"\n)\n\n'
                   'func main() { fmt.Println(fixture.Version) }\n')
        self.commit("first")
        self.commits = 1

    def git(self, *args):
        return subprocess.run([*GIT, *args], cwd=self.root, check=True, capture_output=True, text=True).stdout.strip()

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def commit(self, message):
        self.git("add", "--all")
        self.git("commit", "-q", "-m", message)
        return self.head()

    def head(self):
        return self.git("rev-parse", "HEAD")

    def tree(self):
        return self.git("rev-parse", "HEAD^{tree}")

    def build(self, name, test=True, tags=None, package=".", env=None):
        """The binary a protocol step would build, written outside the checkout."""
        output = self.bin / name
        flags = [f"-tags={tags}"] if tags else []
        command = ["go", "test", "-c", *flags, "-o", str(output), package] if test else \
            ["go", "build", *flags, "-o", str(output), package]
        subprocess.run(command, cwd=self.root, check=True, capture_output=True, text=True,
                       env=os.environ | TARGET | (env or {}))
        return output

    def stale(self, name, **build):
        """A binary built from an earlier commit with identical settings, then the checkout
        advances to a new clean commit."""
        binary = self.build(name, **build)
        self.commits += 1
        self.write("fixture.go", f'package bindingfixture\n\nconst Version = "{self.commits}"\n')
        self.commit(f"commit {self.commits}")
        return binary


class BindTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.repo = FixtureRepo(directory.name)

    def test_binary_from_the_clean_candidate_is_bound(self):
        test_binary = self.repo.build("fixture.test", tags="picoquic")
        tool = self.repo.build("tool", test=False, package="./cmd/tool")
        result = binding.bind(self.repo.root, self.repo.head(), {"test": test_binary, "tool": tool},
                              tree=self.repo.tree())
        self.assertEqual(result["source"], {"commit": self.repo.head(), "tree": self.repo.tree(),
                                            "head_tree": self.repo.tree(), "clean": True})
        test, built = result["bindings"]["test"], result["bindings"]["tool"]
        self.assertEqual((test["package"], test["form"], test["sha256"]), (MODULE, "test", sha256(test_binary)))
        self.assertEqual(test["settings"]["-tags"], "picoquic")
        self.assertEqual((built["package"], built["form"], built["sha256"]), (f"{MODULE}/cmd/tool", "build", sha256(tool)))
        # go build stamps the checkout's revision; the rebuild reproduces it.
        self.assertEqual(built["settings"]["vcs.revision"], self.repo.head())
        for record in (test, built):
            self.assertEqual(record["method"], binding.METHOD)
            self.assertEqual(record["rebuild"], "byte-identical")
            self.assertEqual(record["toolchain"], GO_VERSION)

    def refused(self, pattern, binaries, candidate=None, tree=None):
        with self.assertRaisesRegex(ValueError, pattern):
            binding.bind(self.repo.root, candidate or self.repo.head(), binaries, tree=tree)

    def test_binary_from_another_commit_with_identical_settings_is_refused(self):
        test_binary = self.repo.stale("fixture.test", tags="picoquic")
        self.refused("is not the candidate's build", {"test": test_binary})
        tool = self.repo.stale("tool", test=False, package="./cmd/tool")
        self.refused("is not the candidate's build", {"tool": tool})

    def test_dirty_checkout_is_refused(self):
        test_binary = self.repo.build("fixture.test")
        self.repo.write("fixture.go", 'package bindingfixture\n\nconst Version = "edited"\n')
        self.refused("not clean", {"test": test_binary})

    def test_build_reading_an_untracked_file_is_refused(self):
        self.repo.write("extra.go", "package bindingfixture\n\nconst Extra = 1\n")
        test_binary = self.repo.build("fixture.test")
        self.refused("not clean", {"test": test_binary})

    def test_build_reading_an_ignored_file_is_refused(self):
        self.repo.write("extra_ignored.go", "package bindingfixture\n\nconst Extra = 1\n")
        self.assertEqual(self.repo.git("status", "--porcelain"), "")
        test_binary = self.repo.build("fixture.test")
        self.refused("recorded tree omits.*extra_ignored.go", {"test": test_binary})

    def test_candidate_or_tree_mismatch_is_refused(self):
        first = self.repo.head()
        test_binary = self.repo.stale("fixture.test")
        self.refused("not the candidate", {"test": test_binary}, candidate=first)
        self.refused("not the recorded tree", {"test": test_binary}, tree="0" * 40)

    def test_unreproducible_builds_are_refused(self):
        for name, build, pattern in (
                ("gcflags.test", {"env": {"GOFLAGS": "-gcflags=-N"}}, "cannot be reproduced"),
                ("buildmode.test", {"env": {"GOFLAGS": "-buildvcs=true"}}, "-buildvcs was given"),
                ("tool", {"test": False, "package": "./cmd/tool", "env": {"GOFLAGS": "-buildvcs=false"}}, "-buildvcs was given")):
            with self.subTest(name=name):
                self.refused(pattern, {name: self.repo.build(name, **build)})

    def test_package_outside_the_main_module_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            other = FixtureRepo(directory)
            other.write("go.mod", "module example.com/other\n\ngo 1.26\n")
            other.write("cmd/tool/main.go", 'package main\n\nfunc main() {}\n')
            other.commit("other module")
            tool = other.build("tool", test=False, package="./cmd/tool")
            self.refused("not in the source's main module", {"tool": tool})

    def test_failed_rebuild_is_refused(self):
        tool = self.repo.build("tool", test=False, package="./cmd/tool")
        # Listed like any package, but it no longer type-checks.
        self.repo.write("cmd/tool/main.go", "package main\n\nfunc main() { undefined() }\n")
        self.repo.commit("break the command")
        self.refused("go build .* failed", {"tool": tool})

    def test_checkout_changed_during_the_binding_is_refused(self):
        test_binary = self.repo.build("fixture.test")
        real = binding.source_identity
        calls = []

        def changing(source):
            calls.append(source)
            identity = real(source)
            return identity if len(calls) == 1 else identity | {"tree": "f" * 40}

        with mock.patch.object(binding, "source_identity", side_effect=changing):
            self.refused("changed while", {"test": test_binary})
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
