#!/usr/bin/env python3
"""make_release_sources.py - the corresponding source of one letitedit release, in one new folder, ready to attach.

    python -I release/source/make_release_sources.py --version 1.0.0-beta --out <new folder> \
        --editor-repo <editor checkout> --editor-ref <the commit the installer's editor was built from> \
        --tools-repo <tools checkout> --tools-ref <the commit the installer was built from> \
        [--mlt-repo <an MLT clone holding 63218a28>]

What it writes (nothing is uploaded, pushed or published):
  letitedit-editor-<version>/       the editor's source (tools/release/make_source_snapshot.py --kind editor) as a git
                                    repo with one commit by letitedit <teamletitedit@gmail.com> and no remote
  letitedit-tools-<version>/        the tool server, skills, Looks and installer scripts the same way (--kind tools)
  letitedit-editor-<version>-src.tar.gz, letitedit-tools-<version>-src.tar.gz
                                    each repo's one commit as an archive (git archive: no other metadata)
  mlt-63218a28-src.tar.gz, mlt-patches/
                                    upstream MLT at 63218a28 (the bundled 7.41.0) and letitedit's six patches, the
                                    source of app/libmlt-7.dll and the three patched modules
  msys2-sources.tsv, app-binaries-manifest.tsv
                                    the MSYS2 source archives of the bundled MSYS2 DLLs; every program file's origin
  WRITTEN-OFFER.txt, SOURCES.txt, SHA256SUMS.txt
Each snapshot's report (what was kept, what was left out and why) is written beside the folder, not in it.
Exit code 0 when both snapshots are clean or only review items remain (read them in the reports).
"""
import argparse
import hashlib
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SNAPSHOT = os.path.join(ROOT, "tools", "release", "make_source_snapshot.py")
MLT_COMMIT = "63218a28d21f1e64b5b9e6671b4ff9146023282c"
AUTHOR = {"GIT_AUTHOR_NAME": "letitedit", "GIT_AUTHOR_EMAIL": "teamletitedit@gmail.com",
          "GIT_COMMITTER_NAME": "letitedit", "GIT_COMMITTER_EMAIL": "teamletitedit@gmail.com"}


def run(cmd, **kw):
    print("+", " ".join(cmd), flush=True)
    return subprocess.run(cmd, check=True, **kw)


def snapshot(kind, repo, ref, version, out, work):
    dest = os.path.join(out, "letitedit-%s-%s" % (kind, version))
    rc = subprocess.run([sys.executable, "-I", SNAPSHOT, "--repo", repo, "--ref", ref, "--kind", kind,
                         "--version", version, "--out", dest, "--git", "--accept-review"]).returncode
    if rc != 0:
        raise SystemExit("the %s snapshot was refused (exit %d): read %s.report.txt" % (kind, rc, dest))
    for ext in (".report.txt", ".report.json"):   # the reports stay beside the release folder, not in it
        shutil.move(dest + ext, os.path.join(work, os.path.basename(dest) + ext))
    head = subprocess.run(["git", "-C", dest, "rev-parse", "HEAD"], check=True, capture_output=True,
                          text=True).stdout.strip()
    who = subprocess.run(["git", "-C", dest, "log", "-1", "--format=%an <%ae> / %cn <%ce>"], check=True,
                         capture_output=True, text=True).stdout.strip()
    if who != "letitedit <teamletitedit@gmail.com> / letitedit <teamletitedit@gmail.com>":
        raise SystemExit("the %s snapshot's commit is by %r" % (kind, who))
    archive = dest + "-src.tar.gz"
    run(["git", "-C", dest, "archive", "--format=tar.gz", "--prefix=%s/" % os.path.basename(dest), "-o", archive,
         "HEAD"])
    return dest, head


def holder():
    """The copyright holder, from the installer's one #define (release/HOLDER.md lists every place it appears)."""
    import re
    text = open(os.path.join(ROOT, 'release', 'installer', 'letitedit.iss'), encoding='utf-8-sig').read()
    return re.search(r'^#define Holder "([^"]+)"', text, re.M).group(1)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--version", required=True)
    ap.add_argument("--out", required=True, help="a folder that does not exist yet")
    ap.add_argument("--editor-repo", required=True)
    ap.add_argument("--editor-ref", required=True)
    ap.add_argument("--tools-repo", required=True)
    ap.add_argument("--tools-ref", required=True)
    ap.add_argument("--mlt-repo", default=os.path.join(ROOT, "engine-patches", "mlt-build", "mlt"))
    a = ap.parse_args(argv)
    out = os.path.abspath(a.out)
    if os.path.exists(out):
        raise SystemExit("%s exists; choose a new folder" % out)
    work = out + ".reports"
    os.makedirs(out)
    os.makedirs(work, exist_ok=True)
    os.environ.update(AUTHOR)

    editor_dir, editor_head = snapshot("editor", a.editor_repo, a.editor_ref, a.version, out, work)
    tools_dir, tools_head = snapshot("tools", a.tools_repo, a.tools_ref, a.version, out, work)
    editor_commit = subprocess.run(["git", "-C", a.editor_repo, "rev-parse", a.editor_ref], check=True,
                                   capture_output=True, text=True).stdout.strip()
    tools_commit = subprocess.run(["git", "-C", a.tools_repo, "rev-parse", a.tools_ref], check=True,
                                  capture_output=True, text=True).stdout.strip()

    run(["git", "-C", a.mlt_repo, "archive", "--format=tar.gz", "--prefix=mlt-63218a28/", "-o",
         os.path.join(out, "mlt-63218a28-src.tar.gz"), MLT_COMMIT])
    shutil.copytree(os.path.join(HERE, "mlt-patches"), os.path.join(out, "mlt-patches"))
    for name in ("msys2-sources.tsv", "app-binaries-manifest.tsv", "WRITTEN-OFFER.txt"):
        shutil.copyfile(os.path.join(HERE, name), os.path.join(out, name))

    with open(os.path.join(out, "SOURCES.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write("""letitedit {v}: the corresponding source

letitedit is Copyright (C) 2026 {holder}, free software under the GNU GPL version 3 or later. Every bundled part
keeps its own copyright and licence (THIRD-PARTY-NOTICES.md in the tools source, COPYING in the editor source).

letitedit-editor-{v}-src.tar.gz  the editor (a custom build of Shotcut 26.9.27), one tree with no history
                                  (letitedit-editor-{v}/ is the same tree as a git repo with one commit)
letitedit-tools-{v}-src.tar.gz   the tool server, skills, Looks, motion and VFX code and the installer's scripts
                                  (letitedit-tools-{v}/ the same as a git repo); release/installer/build.ps1 and
                                  letitedit.iss build the installer, build.ps1 the editor
mlt-63218a28-src.tar.gz           MLT at commit {mlt} (the bundled MLT 7.41.0)
mlt-patches/                      letitedit's six MLT patches: 0001-0003 build lib/mlt/libmltqt6.dll and
                                  libmltplus.dll, 0004-0005 libmlt-7.dll, 0006 lib/mlt/libmltresample.dll
                                  (the build scripts: engine-patches/ in the tools source)
msys2-sources.tsv                 the MSYS2 source archives of the MSYS2-built DLLs the app bundles (Qt, x264,
                                  x265, ...): name, version, licence, address, size, SHA-256
app-binaries-manifest.tsv         where each program file in app/ comes from
WRITTEN-OFFER.txt                 the written offer for the source of these components

Everything else in app/ is the official Shotcut 26.9.27 Windows build, unchanged; its own dependency source
(FFmpeg, frei0r, movit, OpenCV, rubberband, whisper.cpp ...) is Shotcut's shotcut-src-26.9.27.txz.
""".format(v=a.version, mlt=MLT_COMMIT, holder=holder()))

    sums = []
    for base, dirs, files in os.walk(out):
        dirs[:] = [d for d in dirs if not d.startswith("letitedit-") and d != ".git"]
        for name in sorted(files):
            p = os.path.join(base, name)
            if name != "SHA256SUMS.txt":
                sums.append("%s *%s" % (sha256(p), os.path.relpath(p, out).replace(os.sep, "/")))
    with open(os.path.join(out, "SHA256SUMS.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(sorted(sums, key=lambda s: s.split("*", 1)[1])) + "\n")

    print("editor %s -> %s\ntools %s -> %s\nwrote %s (reports: %s)" % (
        editor_commit[:10], editor_head[:10], tools_commit[:10], tools_head[:10], out, work))
    return 0


if __name__ == "__main__":
    sys.exit(main())
