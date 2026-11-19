#!/usr/bin/env python3
"""MP-MAC #1528 (protocol D4 A): bind each prebuilt Go binary a Darwin driver consumes to
the recorded candidate tree.

A binary is bound only when a fresh rebuild from the clean candidate checkout, with the
settings the binary records about its own build, is byte-identical to it. The checkout
is snapshotted with E1's method before and after the rebuilds, and a build that reads
main-module files the recorded tree omits is refused. Byte identity is the acceptance
criterion, so a drifted build environment can only refuse a binary, never accept a stale
one. The drivers call bind before they create output or launch anything.
"""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

from native_darwin import (GO_LIST_FILE_FIELDS, Profile, build_env, check_build_sources, selected_sources, source_identity,
                           tree_paths)

METHOD = "rebuild-from-candidate/v1"
# The go command's output depends on which flags were given, not only on the settings it
# records: an explicit default such as -buildmode=exe, -compiler=gc or -buildvcs=false
# changes the binary. So the rebuild passes only the flags a default build records as
# given (-tags and -trimpath), requires the others to be the defaults, and passes the
# recorded environment. Anything else recorded refuses the binary.
FLAGS = ("-tags", "-trimpath")
DEFAULTS = {"-buildmode": "exe", "-compiler": "gc"}
ENVIRONMENT = ("CGO_ENABLED", "CGO_CFLAGS", "CGO_CPPFLAGS", "CGO_CXXFLAGS", "CGO_LDFLAGS", "GOOS", "GOARCH", "GOARM64")
# Derived by the go command from go.mod, and from the checkout when it stamps VCS
# information, which by default it does for go build and not for go test.
DERIVED = ("DefaultGODEBUG",)
VCS = ("vcs", "vcs.revision", "vcs.time", "vcs.modified")
# Never passed to the rebuild: the recorded flags replace GOFLAGS, and a GOEXPERIMENT the
# binary does not record was not set.
UNRECORDED = ("GOFLAGS", "GOEXPERIMENT")
# Every go command here ignores the persisted environment file (go env -w): it applies a
# GOFLAGS, such as an -overlay the binary does not record, whenever GOFLAGS is unset or empty.
ISOLATED = {"GOENV": "off", "GOWORK": "off"}
# Git modes of regular files: the tree holds their bytes, not a link to bytes it omits.
REGULAR_MODES = ("100644", "100755")
FORMS = ("test", "build")
REBUILD = "byte-identical"


def hex_text(length):
    return lambda value: isinstance(value, str) and len(value) == length and all(c in "0123456789abcdef" for c in value)


def text(value):
    return isinstance(value, str) and value != ""


def exactly(expected):
    return lambda value: value == expected and type(value) is type(expected)


# The binding record (#1528, #1576): the snapshot bind() takes and one binary's binding.
# Every reader validates it here; run.py composes these into its receipt schema.
SOURCE_SCHEMA = {"commit": hex_text(40), "tree": hex_text(40), "head_tree": hex_text(40), "clean": exactly(True)}
BINDING_SCHEMA = {
    "method": exactly(METHOD), "package": text, "form": lambda value: value in FORMS, "toolchain": text,
    "sha256": hex_text(64), "rebuild": exactly(REBUILD),
    "settings": lambda value: isinstance(value, dict) and all(isinstance(item, str) for pair in value.items() for item in pair),
}


def check_schema(value, schema, where, label):
    if not isinstance(value, dict):
        raise ValueError(f"{where}: malformed #1528 binding: {label} is {value!r}, not a record")
    missing, unexpected = sorted(set(schema) - set(value)), sorted(set(value) - set(schema))
    if missing or unexpected:
        raise ValueError(f"{where}: malformed #1528 binding: {label} lacks {missing} or has unexpected {unexpected}")
    for key, check in schema.items():
        if not check(value[key]):
            raise ValueError(f"{where}: malformed #1528 binding: {label}.{key} is {value[key]!r}")


def check_binding(source, binding, digest, candidate, where, name, tree=None):
    """Refuse, naming where, a snapshot and binding that are not bind()'s record of the
    named binary, whose sha256 is digest, at the clean candidate (and tree, if given)."""
    check_schema(source, SOURCE_SCHEMA, where, "source")
    check_schema(binding, BINDING_SCHEMA, where, f"{name} binding")
    if source["commit"] != candidate:
        raise ValueError(f"{where}: source commit {source['commit']} is not the candidate {candidate}")
    if tree is not None and source["tree"] != tree:
        raise ValueError(f"{where}: source tree {source['tree']} is not the recorded tree {tree}")
    if binding["sha256"] != digest:
        raise ValueError(f"{where}: the binding names {binding['sha256']}, not the {name} {digest}")


def run(command, cwd=None, env=None):
    try:
        return subprocess.run(command, cwd=cwd, env=env, check=True, capture_output=True, text=True).stdout
    except (OSError, subprocess.CalledProcessError) as error:
        detail = getattr(error, "stderr", "") or ""
        raise ValueError(f"{' '.join(map(str, command))} failed: {error}\n{detail[-2000:]}") from error


def snapshot(source):
    """E1's tree snapshot, with the checkout's own status: a staged change whose working
    file was restored is clean to the snapshot but not to candidate rule 1."""
    try:
        identity = source_identity(source)
        status = run(["git", "status", "--porcelain"], cwd=source)
    except (OSError, subprocess.CalledProcessError) as error:
        raise ValueError(f"cannot snapshot the source checkout {source}: {error}") from error
    if status.strip():
        identity = dict(identity, clean=False)
    return identity


def regular_files(source, tree):
    """The resolved paths at which the recorded tree holds a regular file's bytes."""
    top = Path(run(["git", "rev-parse", "--show-toplevel"], cwd=source).strip()).resolve()
    try:
        listed = subprocess.run(["git", "ls-tree", "-r", "-z", "--full-tree", tree], cwd=top, check=True,
                                capture_output=True).stdout
    except (OSError, subprocess.CalledProcessError) as error:
        raise ValueError(f"cannot list the recorded tree {tree}: {error}") from error
    files = set()
    for entry in filter(None, os.fsdecode(listed).split("\0")):
        # "<mode> <type> <object>\t<path>"
        header, _, name = entry.partition("\t")
        if header.split(" ")[0] in REGULAR_MODES:
            files.add(top / name)
    return files


def check_regular_sources(binary, selected, regular):
    """Every main-module file the build reads, followed through any link, must be a regular
    file at its own path in the recorded tree; E1's membership check resolves links in the
    live checkout, so a tracked link to an ignored file would pass it."""
    outside = sorted(str(path.resolve()) for path in selected if path.resolve() not in regular)
    if outside:
        raise ValueError(f"{binary}: the build reads files that are not a regular file in the recorded tree: {outside}")


def build_info(binary):
    """The toolchain, package path, main module and build settings `go version -m` reads
    from the binary. A quoted key or value is not reproduced, so it is refused."""
    lines = run(["go", "version", "-m", str(binary)]).splitlines()
    if not lines or ": " not in lines[0]:
        raise ValueError(f"{binary} carries no Go build information")
    info = {"toolchain": lines[0].rpartition(": ")[2].strip(), "path": None, "module": None, "settings": {}}
    for line in lines[1:]:
        fields = line.strip("\n").split("\t")
        if len(fields) < 3 or fields[0] != "":
            continue
        kind, value = fields[1], fields[2]
        if kind == "path":
            info["path"] = value
        elif kind == "mod":
            info["module"] = value
        elif kind == "build":
            key, separator, setting = value.partition("=")
            if not separator or key.startswith('"') or setting.startswith('"'):
                raise ValueError(f"{binary}: build setting {value!r} cannot be reproduced")
            info["settings"][key] = setting
    if not info["path"] or not info["module"]:
        raise ValueError(f"{binary} does not name its package and main module")
    return info


def rebuild_plan(binary, info, module):
    """The package, form, flags and environment that reproduce the binary's recorded build."""
    path = info["path"]
    form = "test" if path.endswith(".test") else "build"
    package = path[:-len(".test")] if form == "test" else path
    if info["module"] != module or (package != module and not package.startswith(module + "/")):
        raise ValueError(f"{binary}: package {package} is not in the source's main module {module}")
    settings = info["settings"]
    unknown = sorted(set(settings) - set(FLAGS) - set(DEFAULTS) - set(ENVIRONMENT) - set(DERIVED) - set(VCS))
    if unknown:
        raise ValueError(f"{binary}: recorded build settings {unknown} cannot be reproduced")
    for key, default in DEFAULTS.items():
        if settings.get(key, default) != default:
            raise ValueError(f"{binary}: {key}={settings[key]} is not the default build and cannot be reproduced")
    if ("vcs" in settings) != (form == "build"):
        raise ValueError(f"{binary}: VCS stamping differs from go {form}'s default, so -buildvcs was given; "
                         "the build cannot be reproduced")
    if settings.get("-trimpath", "true") != "true":
        raise ValueError(f"{binary}: -trimpath={settings['-trimpath']} cannot be reproduced")
    flags = [f"-tags={settings['-tags']}"] if "-tags" in settings else []
    flags += ["-trimpath"] if "-trimpath" in settings else []
    environment = {key: settings[key] for key in ENVIRONMENT if key in settings}
    return package, form, flags, environment


def build_sources(directory, toolchain, profile):
    """The main-module files `go build` of the package in directory reads (#1577): E1's
    package build-input fields of every main-module package in its production dependency
    graph, and go.mod and go.sum. Unlike E1's test-build selector, it lists without -test
    and never reads a test-file field, which go list reports even then."""
    listed = run(["go", "list", "-deps", "-json", "."], cwd=directory, env=build_env(toolchain, profile))
    decoder, index, files = json.JSONDecoder(), 0, set()
    while True:
        while index < len(listed) and listed[index].isspace():
            index += 1
        if index == len(listed):
            return files
        package, index = decoder.raw_decode(listed, index)
        module = package.get("Module") or {}
        if package.get("Standard") or not module.get("Main"):
            continue
        root, package_directory = Path(module["GoMod"]).resolve().parent, Path(package["Dir"]).resolve()
        for field in GO_LIST_FILE_FIELDS:
            files.update(path for path in (package_directory / name for name in package.get(field) or ()) if path.is_relative_to(root))
        files.update(path for path in (root / "go.mod", root / "go.sum") if path.exists())


def bind_one(source, tree, regular, module, binary):
    info = build_info(binary)
    package, form, flags, environment = rebuild_plan(binary, info, module)
    toolchain = info["toolchain"]
    directory = source / package[len(module) + 1:] if package != module else source
    # The source check lists the package as the build reads it, with no workspace outside
    # the module; native_darwin passes build settings through the environment. A go test
    # binary reads its package's test files too, so it keeps E1's test-build selector.
    profile = Profile("candidate-binding", "", (), environment | {"GOFLAGS": " ".join(flags)} | ISOLATED)
    try:
        selected = selected_sources(directory, toolchain, profile) if form == "test" else \
            build_sources(directory, toolchain, profile)
    except (OSError, subprocess.CalledProcessError, ValueError) as error:
        raise ValueError(f"{binary}: cannot list the build sources of {package}: {error}") from error
    check_build_sources(selected, tree)
    check_regular_sources(binary, selected, regular)
    env = {key: value for key, value in os.environ.items() if key not in ENVIRONMENT and key not in UNRECORDED}
    env |= environment | ISOLATED | {"GOTOOLCHAIN": toolchain}
    digest = hashlib.sha256(Path(binary).read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory(prefix="candidate-binding-") as temporary:
        # The binary's own name: a Darwin code signature can carry the output name.
        output = Path(temporary) / Path(binary).name
        command = ["go", "test", "-c", *flags, "-o", str(output), package] if form == "test" else \
            ["go", "build", *flags, "-o", str(output), package]
        run(command, cwd=source, env=env)
        rebuilt = hashlib.sha256(output.read_bytes()).hexdigest()
    if rebuilt != digest:
        raise ValueError(f"{binary} (sha256 {digest}) is not the candidate's build of {package}: "
                         f"a rebuild from the recorded tree has sha256 {rebuilt}")
    return {"method": METHOD, "package": package, "form": form, "toolchain": toolchain,
            "settings": dict(info["settings"]), "sha256": digest, "rebuild": REBUILD}


def bind(source, candidate, binaries, tree=None):
    """Bind each named binary to the clean candidate checkout at source, or raise ValueError
    naming why not. candidate is the asserted commit; tree, when the caller asserts one,
    must be its tree. Returns the snapshot and one binding record per binary."""
    source = Path(source).resolve()
    before = snapshot(source)
    if not before["clean"]:
        if before["tree"] == before["head_tree"]:
            raise ValueError(f"the source checkout {source} is not clean: git status --porcelain reports changes "
                             "(for example a staged change) although its working tree matches HEAD's")
        raise ValueError(f"the source checkout {source} is not clean: its working tree {before['tree']} "
                         f"is not HEAD's tree {before['head_tree']}")
    if before["commit"] != candidate:
        raise ValueError(f"the source checkout is at {before['commit']}, not the candidate {candidate}")
    if tree is not None and before["tree"] != tree:
        raise ValueError(f"the source checkout's tree is {before['tree']}, not the recorded tree {tree}")
    listed = run(["go", "list", "-m", "-f", "{{.Path}}\t{{.Dir}}"], cwd=source,
                 env=os.environ | ISOLATED).strip().split("\t")
    if len(listed) != 2 or Path(listed[1]).resolve() != source:
        raise ValueError(f"the source checkout {source} is not the root of its main module")
    module, recorded, regular = listed[0], tree_paths(source, before["tree"]), regular_files(source, before["tree"])
    bindings = {name: bind_one(source, recorded, regular, module, binary) for name, binary in binaries.items()}
    if snapshot(source) != before:
        raise ValueError(f"the source checkout {source} changed while its binaries were bound")
    return {"source": before, "bindings": bindings}
