#!/usr/bin/env python3
"""Build the pinned picoquic/PicoTLS peer natively on Darwin arm64 and record its identity.

A missing tool is a failing prerequisite. CMake and OpenSSL come from explicit,
caller-owned prefixes; nothing is installed or changed on the host.
"""

import argparse
import json
import os
from pathlib import Path
import platform
import shlex
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import run  # noqa: E402  (the runner owns the pins and reads this record back)

PEER_SOURCE = Path(__file__).resolve().with_name("peer.c")
SELF_TEST_IPS = ("127.0.0.1", "127.0.0.1", "127.0.0.1")


def check_tools(cmake, pkg_config, openssl_root, which=shutil.which):
    """Require every named build input before any fetch or configure step."""
    missing = [str(tool) for tool in (cmake, pkg_config) if not tool.is_file() or not os.access(tool, os.X_OK)]
    for relative in ("include/openssl/ssl.h", "lib/libcrypto.a", "lib/libssl.a", "bin/openssl"):
        if not (openssl_root / relative).is_file():
            missing.append(str(openssl_root / relative))
    for executable in ("git", "xcrun", "otool"):
        if which(executable) is None:
            missing.append(executable)
    if missing:
        raise ValueError(f"missing native build prerequisites: {missing}")


def check_arch(lipo_output):
    """Each peer binary must be a native arm64 build, not an Intel build run under Rosetta."""
    if lipo_output.split() != ["arm64"]:
        raise ValueError(f"peer binary architectures are {lipo_output.split()}, not exactly arm64")


def check_static(otool_output):
    """The peer binaries must not load a caller-prefix OpenSSL dylib at run time."""
    if "libssl" in otool_output or "libcrypto" in otool_output:
        raise ValueError(f"peer binary links OpenSSL dynamically:\n{otool_output}")


def check_sysroot(compile_commands, sdk_path):
    """Every compile command must use the SDK the record names, whatever toolchain file or environment is ambient."""
    sysroots = set()
    for entry in compile_commands:
        arguments = entry["arguments"] if "arguments" in entry else shlex.split(entry["command"])
        flagged = [arguments[i + 1] for i, argument in enumerate(arguments[:-1]) if argument == "-isysroot"]
        sysroots.add(tuple(flagged))
    if sysroots != {(sdk_path,)}:
        raise ValueError(f"peer compile sysroots {sorted(sysroots)} differ from the recorded SDK {sdk_path}")


def check_self_test(output):
    lines = output.splitlines()
    if lines.count("self-test pass") != 1 or not any("truncated 1" in line for line in lines):
        raise ValueError(f"peer self-test did not report tuple binding and truncation:\n{output}")


def run_step(command, log, cwd, timeout=1200):
    """Run one build step in its own process group, appending its command line and output to the open build log.

    `run.run_group` kills and joins the whole group (CMake plus its make and compiler workers)
    on timeout, interrupt or SIGTERM, and a nonzero exit fails like `check=True`.
    """
    log.write(f"$ {' '.join(map(str, command))}\n")
    log.flush()
    status = run.run_group(command, log, timeout, cwd=cwd)
    if status != 0:
        raise subprocess.CalledProcessError(status, command)
    return status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cmake", required=True, type=Path, help="cmake executable from an isolated user-owned prefix")
    parser.add_argument("--pkg-config", required=True, type=Path,
                        help="pkg-config from an isolated user-owned prefix; PicoTLS requires it to probe Brotli, which picoquic disables")
    parser.add_argument("--openssl-root", required=True, type=Path, help="OpenSSL prefix with static libraries")
    parser.add_argument("--work", required=True, type=Path, help="new build directory")
    parser.add_argument("--jobs", type=int, default=4)
    args = parser.parse_args()
    run.check_prerequisites(None, platform.system(), platform.machine(), run.NATIVE_PROFILE)
    # Resolve caller-relative inputs before any step changes the working directory.
    args.cmake, args.pkg_config, args.openssl_root = args.cmake.resolve(), args.pkg_config.resolve(), args.openssl_root.resolve()
    check_tools(args.cmake, args.pkg_config, args.openssl_root)
    args.work.mkdir(parents=True, exist_ok=False)
    work = args.work.resolve()
    log = (work / "build.log").open("w")

    def call(command, cwd=work, timeout=1200):
        return run_step(command, log, cwd, timeout)

    def output(command, cwd=work):
        return subprocess.check_output(command, cwd=cwd, text=True, timeout=60).strip()

    source = work / "picoquic"
    source.mkdir()
    peer = work / "r17-peer.c"
    shutil.copyfile(PEER_SOURCE, peer)
    call(["git", "init", "-q"], source)
    call(["git", "remote", "add", "origin", "https://github.com/private-octopus/picoquic.git"], source)
    call(["git", "fetch", "-q", "--depth", "1", "origin", run.PICOQUIC_PIN], source)
    call(["git", "checkout", "-q", "FETCH_HEAD"], source)
    if output(["git", "rev-parse", "HEAD"], source) != run.PICOQUIC_PIN:
        raise ValueError("picoquic checkout differs from its pin")
    with (source / "CMakeLists.txt").open("a") as cmakelists:
        # Relative to the picoquic source directory, so a work path with spaces stays one source argument.
        cmakelists.write("add_executable(qgf-r17-peer ../r17-peer.c)\n"
                         "target_include_directories(qgf-r17-peer PRIVATE ${PTLS_INCLUDE_DIRS})\n"
                         "target_link_libraries(qgf-r17-peer PRIVATE picoquic-core)\n")
    build = source / "build"
    sdk_path = output(["xcrun", "--show-sdk-path"])
    sdk_version = output(["xcrun", "--sdk", sdk_path, "--show-sdk-version"])
    call([args.cmake, "-S", ".", "-B", "build", "-DCMAKE_BUILD_TYPE=Release", "-DPICOQUIC_FETCH_PTLS=ON",
          f"-DPICOQUIC_FETCH_PTLS_TAG={run.PICOTLS_PIN}", "-DBUILD_TESTING=OFF",
          f"-DPKG_CONFIG_EXECUTABLE={args.pkg_config}", "-DCMAKE_OSX_ARCHITECTURES=arm64",
          f"-DCMAKE_OSX_SYSROOT={sdk_path}", "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON",
          f"-DOPENSSL_ROOT_DIR={args.openssl_root}", "-DOPENSSL_USE_STATIC_LIBS=TRUE"], source)
    check_sysroot(json.loads((build / "compile_commands.json").read_text()), sdk_path)
    if output(["git", "-C", str(build / "_deps" / "picotls-src"), "rev-parse", "HEAD"]) != run.PICOTLS_PIN:
        raise ValueError("PicoTLS checkout differs from its pin")
    call([args.cmake, "--build", "build", "--target", *run.PEER_BINARIES, "-j", str(args.jobs)], source)
    binaries = {}
    for name in run.PEER_BINARIES:
        binary = build / name
        linked = output(["otool", "-L", str(binary)])
        log.write(linked + "\n")
        check_static(linked)
        check_arch(output(["xcrun", "lipo", "-archs", str(binary)]))
        binaries[name] = {"sha256": run.digest(binary)}
    self_test = subprocess.run([build / "qgf-r17-peer", "self-test", *SELF_TEST_IPS], capture_output=True, text=True, timeout=20)
    log.write(self_test.stdout + self_test.stderr)
    if self_test.returncode != 0:
        raise ValueError(f"peer self-test exited {self_test.returncode}; see {work / 'build.log'}")
    check_self_test(self_test.stdout)
    compiler = next(line.split("=", 1)[1] for line in (build / "CMakeCache.txt").read_text().splitlines()
                    if line.startswith("CMAKE_C_COMPILER:"))
    record = {
        "version": 1, "profile": run.NATIVE_PROFILE,
        "platform": {"system": platform.system(), "machine": platform.machine(), "release": platform.release(),
                     "macos": platform.mac_ver()[0]},
        "picoquic": run.PICOQUIC_PIN, "picotls": run.PICOTLS_PIN,
        "toolchain": {
            "cc": f"{compiler}: {output([compiler, '--version']).splitlines()[0]}",
            "sdk_version": sdk_version, "sdk_path": sdk_path,
            "cmake": output([args.cmake, "--version"]).splitlines()[0], "cmake_sha256": run.digest(args.cmake),
            "pkg_config": output([args.pkg_config, "--version"]), "pkg_config_sha256": run.digest(args.pkg_config),
            "openssl": output([args.openssl_root / "bin" / "openssl", "version"]),
            "openssl_root": str(args.openssl_root),
            "openssl_static_sha256": {name: run.digest(args.openssl_root / "lib" / name) for name in ("libcrypto.a", "libssl.a")},
        },
        "peer_driver_sha256": run.digest(peer), "binaries": binaries, "self_test": "pass",
    }
    identity = work / "build-identity.json"
    identity.write_text(json.dumps(record, indent=2) + "\n")
    for name in run.PEER_BINARIES:
        run.load_build_identity(identity, platform.system(), platform.machine(), build / name)
    log.close()
    print(json.dumps({"build_identity": str(identity), "binaries": {name: str(build / name) for name in run.PEER_BINARIES}}))


if __name__ == "__main__":
    main()
