"""ARM64 output profiles, independent of the build machine's CPU."""
import os
from pathlib import Path
import platform
import shutil
import struct

LIBCS = ("bionic", "glibc", "musl")


def target_name(libc):
    if libc not in LIBCS:
        raise ValueError("libc must be bionic, glibc or musl")
    return ("android" if libc == "bionic" else "linux") + "-arm64-" + libc


class Arm64Toolchain:
    def __init__(self, libc, directory, environment):
        self.libc = libc
        self.target = target_name(libc)
        self.env = dict(environment)
        self.android_api = int(self.env.get("ANDROID_API", "28"))
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        if libc == "bionic":
            value = self.env.get("ANDROID_NDK_HOME") or self.env.get("ANDROID_NDK_ROOT")
            if not value:
                raise ValueError("Set ANDROID_NDK_HOME to an Android NDK; Actions provisions the pinned NDK")
            ndk = Path(value).resolve()
            candidates = sorted((ndk / "toolchains/llvm/prebuilt").glob("*"))
            preferred = "linux-aarch64" if platform.machine() in {"aarch64", "arm64"} else "linux-x86_64"
            candidates.sort(key=lambda x: x.name != preferred)
            tools = next((p / "bin" for p in candidates if (p / "bin" / f"aarch64-linux-android{self.android_api}-clang").exists()), None)
            if tools is None:
                raise ValueError("The supplied NDK lacks an ARM64 Android compiler")
            self.cc = str(tools / f"aarch64-linux-android{self.android_api}-clang")
            self.cxx = self.cc + "++"
            self.ar = str(tools / "llvm-ar")
            self.ranlib = str(tools / "llvm-ranlib")
            self.strip = str(tools / "llvm-strip")
            self.cmake = ["-DCMAKE_TOOLCHAIN_FILE=" + str(ndk / "build/cmake/android.toolchain.cmake"),
                          "-DANDROID_ABI=arm64-v8a", "-DANDROID_PLATFORM=android-" + str(self.android_api),
                          "-DANDROID_STL=c++_static"]
            self.details = {"ndk": str(ndk), "api": self.android_api,
                            "source_properties": (ndk / "source.properties").read_text()}
        elif libc == "glibc":
            prefix = self.env.get("ARM64_GNU_PREFIX", "aarch64-linux-gnu-")
            self.cc = self.find(prefix + "gcc")
            self.cxx = self.find(prefix + "g++")
            self.ar = self.find(prefix + "ar")
            self.ranlib = self.find(prefix + "ranlib")
            self.strip = self.find(prefix + "strip")
            self.cmake = self.linux_cmake()
            self.details = {"compiler_prefix": prefix}
        else:
            prefix = self.env.get("ARM64_MUSL_PREFIX")
            if prefix:
                self.cc, self.cxx = self.find(prefix + "gcc"), self.find(prefix + "g++")
                self.ar, self.ranlib, self.strip = self.find(prefix + "ar"), self.find(prefix + "ranlib"), self.find(prefix + "strip")
            else:
                zig = self.find(self.env.get("ZIG", "zig"))
                for name, command in (("cc", "cc"), ("cxx", "c++"), ("ar", "ar"), ("ranlib", "ranlib")):
                    wrapper = self.directory / name
                    import shlex
                    extra = " -target aarch64-linux-musl" if command in {"cc", "c++"} else ""
                    wrapper.write_text("#!/bin/sh\nexec " + shlex.quote(zig) + " " + command + extra + ' "$@"\n')
                    wrapper.chmod(0o755)
                self.cc, self.cxx, self.ar, self.ranlib = (str(self.directory / x) for x in ("cc", "cxx", "ar", "ranlib"))
                self.strip = shutil.which("llvm-strip") or shutil.which("strip") or "strip"
            self.cmake = self.linux_cmake()
            self.details = {"compiler_prefix": prefix, "zig": self.env.get("ZIG")}
        self.env.update(CC=self.cc, CXX=self.cxx, AR=self.ar, RANLIB=self.ranlib, STRIP=self.strip)

    def find(self, name):
        found = shutil.which(name, path=self.env.get("PATH"))
        if found is None:
            raise ValueError("Missing ARM64 cross tool: " + name)
        return found

    def linux_cmake(self):
        return ["-DCMAKE_SYSTEM_NAME=Linux", "-DCMAKE_SYSTEM_PROCESSOR=aarch64",
                "-DCMAKE_C_COMPILER=" + self.cc, "-DCMAKE_CXX_COMPILER=" + self.cxx,
                "-DCMAKE_AR=" + self.ar, "-DCMAKE_RANLIB=" + self.ranlib,
                "-DCMAKE_TRY_COMPILE_TARGET_TYPE=STATIC_LIBRARY"]


def elf_details(data, libc, label):
    if not data.startswith(b"\x7fELF"):
        return False
    if len(data) < 64 or data[4] != 2 or data[5] != 1 or struct.unpack_from("<H", data, 18)[0] != 183:
        raise ValueError("Non-ARM64 ELF in release output: " + label)
    phoff = struct.unpack_from("<Q", data, 32)[0]
    phsize, count = struct.unpack_from("<HH", data, 54)
    loads, dynamic, interpreter = [], None, None
    for index in range(count):
        offset = phoff + index * phsize
        if phsize < 56 or offset + 56 > len(data):
            raise ValueError("Invalid ELF program table: " + label)
        kind, flags, file_offset, address, _, size, _, _ = struct.unpack_from("<IIQQQQQQ", data, offset)
        if kind == 1:
            loads.append((address, address + size, file_offset))
        elif kind == 2:
            dynamic = (file_offset, size)
        elif kind == 3:
            interpreter = data[file_offset:file_offset + size].rstrip(b"\0").decode()
    if interpreter:
        allowed = {"bionic": "/system/bin/linker64", "glibc": "/lib/ld-linux-aarch64.so.1", "musl": "/lib/ld-musl-aarch64.so.1"}
        if interpreter != allowed[libc]:
            raise ValueError(f"Wrong libc interpreter in {label}: {interpreter}; expected {allowed[libc]}")
    if dynamic:
        table_address, needed = None, []
        for offset in range(dynamic[0], dynamic[0] + dynamic[1], 16):
            if offset + 16 > len(data):
                raise ValueError("Invalid ELF dynamic table: " + label)
            kind, value = struct.unpack_from("<qQ", data, offset)
            if kind == 0:
                break
            if kind == 5:
                table_address = value
            if kind == 1:
                needed.append(value)
        if needed and table_address is not None:
            table = next((start + table_address - lo for lo, hi, start in loads if lo <= table_address < hi), None)
            if table is None:
                raise ValueError("Invalid ELF string table: " + label)
            names = [data[table + n:].split(b"\0", 1)[0].decode() for n in needed]
            if libc == "bionic" and any(x in {"libc.so.6", "libm.so.6", "libpthread.so.0", "libdl.so.2"} or "musl" in x for x in names):
                raise ValueError("Desktop libc dependency in Android output: " + label)
            if libc == "glibc" and any("musl" in x or x == "libc.so" for x in names):
                raise ValueError("Wrong libc dependency in glibc output: " + label)
            if libc == "musl" and any(x in {"libc.so.6", "libm.so.6", "libpthread.so.0"} for x in names):
                raise ValueError("glibc dependency in musl output: " + label)
    return True


def inspect_binary(data, libc, label):
    counts = {"elf_files": 0, "static_members": 0}
    if data.startswith(b"\x7fELF"):
        elf_details(data, libc, label)
        counts["elf_files"] += 1
    elif data.startswith(b"!<thin>\n"):
        raise ValueError("Thin archives cannot be independently verified or shipped: " + label)
    elif data.startswith(b"!<arch>\n"):
        offset = 8
        while offset < len(data):
            if offset + 60 > len(data):
                raise ValueError("Invalid static archive: " + label)
            header = data[offset:offset + 60]
            length = int(header[48:58].strip())
            name = header[:16].decode().strip()
            contents = data[offset + 60:offset + 60 + length]
            if name.startswith("#1/"):
                contents = contents[int(name[3:]):]
            if contents.startswith(b"\x7fELF"):
                elf_details(contents, libc, label + ":" + name)
                counts["static_members"] += 1
            offset += 60 + length + length % 2
    return counts


def inspect_payload(data, libc, label):
    counts = inspect_binary(data, libc, label)
    if data.startswith(b"PK\x03\x04"):
        import io, zipfile
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for item in archive.infolist():
                if not item.is_dir() and item.filename.endswith((".so", ".a")):
                    child = inspect_binary(archive.read(item), libc, label + ":" + item.filename)
                    for key, value in child.items():
                        counts[key] += value
    return counts


def validate_tree(root, libc):
    counts = {"elf_files": 0, "static_members": 0}
    for directory, folders, files in os.walk(root):
        folders[:] = [x for x in folders if x != ".git"]
        for name in files:
            path = Path(directory) / name
            if path.is_symlink():
                continue
            with path.open("rb") as stream:
                magic = stream.read(8)
                if magic[:4] != b"\x7fELF" and magic != b"!<arch>\n" and magic != b"!<thin>\n" and not (magic.startswith(b"PK") and path.suffix in {".jar", ".zip"}):
                    continue
                stream.seek(0)
                observed = inspect_payload(stream.read(), libc, str(path.relative_to(root)))
                for key, value in observed.items():
                    counts[key] += value
    return {"architecture": "arm64", "libc": libc, **counts}


def validate_archive(path, libc):
    import tarfile
    counts = {"elf_files": 0, "static_members": 0}
    with tarfile.open(path, "r:gz") as archive:
        for item in archive:
            if not item.isfile() or "/.git/" in item.name:
                continue
            stream = archive.extractfile(item)
            magic = stream.read(8)
            if magic[:4] != b"\x7fELF" and magic not in (b"!<arch>\n", b"!<thin>\n") and not (magic.startswith(b"PK") and item.name.endswith((".jar", ".zip"))):
                continue
            observed = inspect_payload(magic + stream.read(), libc, item.name)
            for key, value in observed.items():
                counts[key] += value
    return {"architecture": "arm64", "libc": libc, **counts}
