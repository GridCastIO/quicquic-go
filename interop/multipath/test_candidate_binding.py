"""MP-MAC #1528: a consumed Go binary is bound to the candidate only by a byte-identical
rebuild from the clean recorded tree. These tests use real git repositories and real Go
builds of a tiny module; other driver tests import this module for the same fixture."""

import hashlib
import json
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


def source_record(commit, tree="8" * 40):
    """A clean snapshot as bind() records it."""
    return {"commit": commit, "tree": tree, "head_tree": tree, "clean": True}


def binding_record(digest, package=MODULE, form="test"):
    """A binding record shaped as bind() produces it, for driver fixtures."""
    settings = {"-tags": "picoquic", "GOOS": "darwin", "GOARCH": "arm64", "CGO_ENABLED": "0"}
    return {"method": binding.METHOD, "package": package, "form": form, "toolchain": GO_VERSION,
            "settings": settings, "sha256": digest, "rebuild": "byte-identical"}


def refusals():
    """(label, edit(source, record)) pairs, each making a bind() snapshot and record one
    that every #1528 binding reader refuses: the digest-only binding, the wrong method,
    rebuild or cleanliness, and every schema field missing or mistyped."""
    cases = [("digest-only binding", lambda source, record: [record.pop(key) for key in list(record) if key != "sha256"]),
             ("unclean source", lambda source, record: source.update(clean=False)),
             ("wrong method", lambda source, record: record.update(method="rebuild-from-candidate/v0")),
             ("wrong rebuild", lambda source, record: record.update(rebuild="assumed")),
             ("wrong form", lambda source, record: record.update(form="exe"))]
    for part, fields in (("source", source_record("a" * 40)), ("binding", binding_record("9" * 64))):
        for field in fields:
            def missing(source, record, part=part, field=field):
                (source if part == "source" else record).pop(field)

            def mistyped(source, record, part=part, field=field):
                (source if part == "source" else record)[field] = 0

            cases += [(f"missing {part} {field}", missing), (f"mistyped {part} {field}", mistyped)]
    return cases


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

    def ignore(self, *patterns):
        """Ignore paths through the fixture's own exclude file, which no tree records."""
        with (self.root / ".git" / "info" / "exclude").open("a") as exclude:
            exclude.write("".join(pattern + "\n" for pattern in patterns))

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

    def test_go_build_binary_ignores_test_only_sources(self):
        # #1577: go build never compiles a _test.go or a package only tests import.
        self.repo.ignore("cmd/tool/scratch_test.go", "scratchdep/")
        self.repo.write("scratchdep/dep.go", "package scratchdep\n\nconst Dep = 1\n")
        self.repo.write("cmd/tool/scratch_test.go", f'package main\n\nimport (\n\t"testing"\n\n\t"{MODULE}/scratchdep"\n)\n\n'
                        'func TestScratch(t *testing.T) { _ = scratchdep.Dep }\n')
        self.assertEqual(self.repo.git("status", "--porcelain"), "")
        tool = self.repo.build("tool", test=False, package="./cmd/tool")
        bound = binding.bind(self.repo.root, self.repo.head(), {"tool": tool}, tree=self.repo.tree())
        self.assertEqual((bound["bindings"]["tool"]["form"], bound["bindings"]["tool"]["sha256"]), ("build", sha256(tool)))

    def test_go_build_binary_reading_an_ignored_file_is_refused(self):
        self.repo.write("cmd/tool/extra_ignored.go", "package main\n\nconst Extra = 1\n")
        self.assertEqual(self.repo.git("status", "--porcelain"), "")
        tool = self.repo.build("tool", test=False, package="./cmd/tool")
        self.refused("recorded tree omits.*cmd/tool/extra_ignored.go", {"tool": tool})

    def test_go_test_binary_reading_an_ignored_test_file_is_refused(self):
        self.repo.ignore("scratch_test.go")
        self.repo.write("scratch_test.go", 'package bindingfixture\n\nimport "testing"\n\nfunc TestScratch(t *testing.T) {}\n')
        self.assertEqual(self.repo.git("status", "--porcelain"), "")
        self.refused("recorded tree omits.*scratch_test.go", {"test": self.repo.build("fixture.test")})

    def test_staged_change_is_refused_even_when_the_working_file_matches_head(self):
        test_binary = self.repo.build("fixture.test")
        original = (self.repo.root / "fixture.go").read_text()
        self.repo.write("fixture.go", 'package bindingfixture\n\nconst Version = "staged"\n')
        self.repo.git("add", "fixture.go")
        self.repo.write("fixture.go", original)
        self.assertNotEqual(self.repo.git("status", "--porcelain"), "")
        self.refused("not clean", {"test": test_binary})

    def test_tracked_link_to_an_ignored_source_is_refused(self):
        # Git records the link, not the bytes the build reads through it.
        # The target sits in a directory no build imports, so only the link compiles it.
        self.repo.write("targets/target_ignored.go", "package bindingfixture\n\nconst Extra = 1\n")
        os.symlink("targets/target_ignored.go", self.repo.root / "linked.go")
        self.repo.commit("track a link to an ignored file")
        self.assertEqual(self.repo.git("status", "--porcelain"), "")
        self.refused("not a regular file in the recorded tree.*target_ignored.go",
                     {"test": self.repo.build("linked.test")})

    def test_tracked_link_to_a_tracked_source_is_bound(self):
        self.repo.write("targets/target.go", "package bindingfixture\n\nconst Extra = 1\n")
        os.symlink("targets/target.go", self.repo.root / "linked.go")
        self.repo.commit("track a link to a tracked file")
        test_binary = self.repo.build("linked.test")
        binding.bind(self.repo.root, self.repo.head(), {"test": test_binary})

    def test_go_environment_file_cannot_substitute_sources(self):
        # A persisted GOFLAGS (go env -w) applies whenever GOFLAGS is unset or empty.
        overlay_dir = self.repo.bin.parent / "overlay"
        overlay_dir.mkdir()
        alternate = overlay_dir / "fixture.go"
        alternate.write_text('package bindingfixture\n\nconst Version = "alternate"\n')
        overlay = overlay_dir / "overlay.json"
        overlay.write_text(json.dumps({"Replace": {str((self.repo.root / "fixture.go").resolve()): str(alternate)}}))
        goenv = overlay_dir / "env"
        goenv.write_text(f"GOFLAGS=-overlay={overlay}\n")
        genuine = self.repo.build("genuine.test")
        substituted = self.repo.build("substituted.test", env={"GOENV": str(goenv)})
        self.assertNotEqual(sha256(genuine), sha256(substituted))
        with mock.patch.dict(os.environ, {"GOENV": str(goenv)}):
            self.refused("is not the candidate's build", {"test": substituted})
            binding.bind(self.repo.root, self.repo.head(), {"test": genuine})

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


class CheckBindingTests(unittest.TestCase):
    """MP-MAC #1576: one validator of the binding record, shared by every reader."""

    def check(self, source, record, digest="9" * 64, candidate="a" * 40, tree=None):
        binding.check_binding(source, record, digest, candidate, "round 1 attempt /x identity.json", "binary", tree=tree)

    def test_records_bind_produced_validate(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = FixtureRepo(directory)
            binaries = {"test": repo.build("fixture.test", tags="picoquic"),
                        "tool": repo.build("tool", test=False, package="./cmd/tool")}
            bound = binding.bind(repo.root, repo.head(), binaries, tree=repo.tree())
            for name, path in binaries.items():
                with self.subTest(name=name):
                    binding.check_binding(bound["source"], bound["bindings"][name], sha256(path), repo.head(),
                                          "fixture", name, tree=repo.tree())
        self.check(source_record("a" * 40), binding_record("9" * 64))

    def test_incomplete_or_wrong_records_are_refused(self):
        for label, edit in refusals():
            with self.subTest(label=label):
                source, record = source_record("a" * 40), binding_record("9" * 64)
                edit(source, record)
                with self.assertRaisesRegex(ValueError, r"^round 1 attempt /x identity\.json: malformed #1528 binding"):
                    self.check(source, record)
        for source, record in ((None, binding_record("9" * 64)), (source_record("a" * 40), None),
                               (source_record("a" * 40), [])):
            with self.subTest(source=source, record=record), self.assertRaisesRegex(ValueError, "malformed #1528 binding"):
                self.check(source, record)

    def test_a_record_of_another_commit_tree_or_binary_is_refused(self):
        where = "native ordinary-control receipt identity"
        for change, message in (
                ({"candidate": "d" * 40}, f"{where}: source commit {'a' * 40} is not the candidate {'d' * 40}"),
                ({"tree": "e" * 40}, f"{where}: source tree {'8' * 40} is not the recorded tree {'e' * 40}"),
                ({"digest": "e" * 64}, f"{where}: the binding names {'9' * 64}, not the test binary {'e' * 64}")):
            with self.subTest(change=change):
                arguments = {"digest": "9" * 64, "candidate": "a" * 40, "tree": "8" * 40} | change
                with self.assertRaises(ValueError) as caught:
                    binding.check_binding(source_record("a" * 40), binding_record("9" * 64), arguments["digest"],
                                          arguments["candidate"], where, "test binary", tree=arguments["tree"])
                self.assertEqual(str(caught.exception), message)


if __name__ == "__main__":
    unittest.main()
