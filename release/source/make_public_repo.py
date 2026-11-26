#!/usr/bin/env python3
"""make_public_repo.py - the public release repository's next state for one letitedit release, made on this PC.
Nothing is pushed, uploaded or published.

    python -I release/source/make_public_repo.py --sources <make_release_sources.py's folder> \
        --tag v1.0.0-beta-20261124.12 --installer <letitedit-Setup-....exe> [--out <new folder>]

What it writes, in <out> (default: <sources>.public):
  letitedit.git/  a bare git repo: branch main with one commit and the annotated tag <tag>, both by
                  letitedit <teamletitedit@gmail.com> in UTC, unsigned, with no remote. Its tree is the tools snapshot
                  at the top and the editor snapshot in src/ (the two snapshot repos' exact trees), plus
                  .github/workflows/release.yml (release/public-repo/release.yml), .github/release/notes.md (the
                  Release's text, from release/public-repo/notes.md) and .github/release/assets.txt (the Release's
                  files, one name per line).
  staging.tsv     each of the Release's files and where it is on this PC: the installer, MLT's source, and the MSYS2
                  source archives that go into one tar. It holds this PC's paths and stays here.
It refuses (exit 1) when a snapshot repo's or the new repo's git metadata is not clean
(tools/release/make_source_snapshot.py, check_git), when the new files hold a private term, or when a Release file
is missing. How the repo is pushed and the Release published: release/public-repo/README.md.
"""
import argparse
import glob
import hashlib
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
TEMPLATES = os.path.join(ROOT, "release", "public-repo")
sys.path.insert(0, os.path.join(ROOT, "tools", "release"))
import make_source_snapshot as snap  # noqa: E402


def holder():
    import re
    text = open(os.path.join(ROOT, "release", "installer", "letitedit.iss"), encoding="utf-8-sig").read()
    return re.search(r'^#define Holder "([^"]+)"', text, re.M).group(1)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def git(gitdir, *args, env=None, data=None):
    return subprocess.run(["git", "--git-dir", gitdir] + list(args), check=True, capture_output=True, env=env,
                          input=data).stdout.decode("utf-8", "replace").strip()


def one(pattern, what):
    found = [p for p in glob.glob(pattern) if os.path.isdir(p)]
    if len(found) != 1:
        raise SystemExit("want one %s (%s), found %d" % (what, pattern, len(found)))
    return found[0]


def msys2_archives(sources, archive_dir):
    """The MSYS2 source archives msys2-sources.tsv names, deduplicated (several packages share one source), each
    checked against its listed SHA-256."""
    out, seen = [], set()
    with open(os.path.join(sources, "msys2-sources.tsv"), encoding="utf-8") as f:
        head = f.readline().rstrip("\n").split("\t")
        for line in f:
            row = dict(zip(head, line.rstrip("\n").split("\t")))
            name = row["source_url"].rsplit("/", 1)[-1]
            if name in seen:
                continue
            seen.add(name)
            path = os.path.join(archive_dir, name)
            if not os.path.isfile(path):
                raise SystemExit("an MSYS2 source archive is missing: %s" % path)
            if sha256(path) != row["sha256"]:
                raise SystemExit("an MSYS2 source archive differs from msys2-sources.tsv: %s" % path)
            out.append(path)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--sources", required=True, help="the folder make_release_sources.py wrote")
    ap.add_argument("--tag", required=True, help="the release's tag, v<version>")
    ap.add_argument("--installer", required=True, help="the installer this release ships")
    ap.add_argument("--msys2-dir", help="where the MSYS2 source archives are (default: beside --sources)")
    ap.add_argument("--out", help="a folder that does not exist yet (default: <sources>.public)")
    ap.add_argument("--private-terms", default=snap.DEFAULT_TERMS)
    a = ap.parse_args(argv)
    sources = os.path.abspath(a.sources)
    out = os.path.abspath(a.out or sources.rstrip(os.sep) + ".public")
    if not a.tag.startswith("v") or not all(c.isalnum() or c in ".+-" for c in a.tag[1:]):
        raise SystemExit("the tag must be v<version>, letters, digits and . + - only: %r" % a.tag)
    if os.path.exists(out):
        raise SystemExit("%s exists; choose a new folder" % out)
    version = a.tag[1:]
    block, review = snap.load_terms(a.private_terms)
    if not block:
        raise SystemExit("no blocking private terms loaded from %s; nothing is checked without them" % a.private_terms)
    terms = block + review        # the private terms name the account too

    tools = one(os.path.join(sources, "letitedit-tools-*"), "tools snapshot repo")
    editor = one(os.path.join(sources, "letitedit-editor-*"), "editor snapshot repo")
    for repo in (tools, editor):
        problems = snap.check_git(repo, terms)
        if problems:
            raise SystemExit("REFUSED: %s's git metadata:\n  %s" % (repo, "\n  ".join(problems)))

    installer = os.path.abspath(a.installer)
    mlt = glob.glob(os.path.join(sources, "mlt-*-src.tar.gz"))
    if not os.path.isfile(installer) or len(mlt) != 1:
        raise SystemExit("the installer (%s) or MLT's source archive in %s is missing" % (installer, sources))
    msys2 = msys2_archives(sources, a.msys2_dir or os.path.dirname(sources))
    msys2_tar = "letitedit-%s-msys2-sources.tar" % version
    assets = sorted([os.path.basename(installer), msys2_tar, os.path.basename(mlt[0])])

    with open(os.path.join(TEMPLATES, "notes.md"), encoding="utf-8") as f:
        notes = f.read().format(version=version, installer=os.path.basename(installer), msys2=msys2_tar,
                                mlt=os.path.basename(mlt[0]), holder=holder())
    with open(os.path.join(TEMPLATES, "release.yml"), encoding="utf-8") as f:
        workflow = f.read()
    extra = {
        ".github/workflows/release.yml": workflow,
        ".github/release/notes.md": notes,
        ".github/release/assets.txt": "# The Release's files: the draft release staging-<tag> must hold exactly these.\n"
                                      + "".join(n + "\n" for n in assets),
    }
    for path, text in extra.items():
        hits = [t for t in terms if t.lower() in text.lower()]
        if hits:
            raise SystemExit("REFUSED: %s holds a private term (%s)" % (path, ", ".join(hits)))

    os.makedirs(out)
    gitdir = os.path.join(out, "letitedit.git")
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", gitdir], check=True)
    git(gitdir, "fetch", "-q", "--no-tags", tools, "HEAD:refs/snapshot/tools")
    git(gitdir, "fetch", "-q", "--no-tags", editor, "HEAD:refs/snapshot/editor")
    os.remove(os.path.join(gitdir, "FETCH_HEAD"))   # it names this PC's folders
    epoch = max(int(git(gitdir, "show", "-s", "--format=%ct", r)) for r in ("refs/snapshot/tools",
                                                                          "refs/snapshot/editor"))
    title = git(gitdir, "show", "-s", "--format=%s", "refs/snapshot/tools")
    env = snap.git_env(epoch)

    def mktree(entries):
        """A tree object from (mode, type, id, name) entries; git puts them in its order."""
        data = b"".join(("%s %s %s\t%s" % e).encode("utf-8") + b"\0" for e in entries)
        return git(gitdir, "mktree", "-z", data=data)

    def blob(text):
        return git(gitdir, "hash-object", "-w", "--no-filters", "--stdin", data=text.encode("utf-8"))

    # the tools snapshot's tree as it is, with the editor snapshot's tree as src/ and the release files in .github/
    top = [tuple(line.split(" ", 2)[:2]) + tuple(line.split(" ", 2)[2].split("\t", 1))
           for line in git(gitdir, "ls-tree", "-z", "refs/snapshot/tools^{tree}").split("\0") if line]
    if {e[3] for e in top} & {"src", ".github"}:
        raise SystemExit("the tools snapshot has its own src/ or .github/: they would collide")
    workflows = mktree([("100644", "blob", blob(extra[".github/workflows/release.yml"]), "release.yml")])
    release = mktree([("100644", "blob", blob(extra[".github/release/notes.md"]), "notes.md"),
                      ("100644", "blob", blob(extra[".github/release/assets.txt"]), "assets.txt")])
    github = mktree([("040000", "tree", workflows, "workflows"), ("040000", "tree", release, "release")])
    tree = mktree(top + [("040000", "tree", git(gitdir, "rev-parse", "refs/snapshot/editor^{tree}"), "src"),
                         ("040000", "tree", github, ".github")])
    commit = git(gitdir, "commit-tree", tree, "-m", title, env=env)
    git(gitdir, "update-ref", "refs/heads/main", commit, env=env)
    git(gitdir, "tag", "-a", a.tag, "-m", "letitedit %s" % version, commit, env=env)
    for ref in ("refs/snapshot/tools", "refs/snapshot/editor"):
        git(gitdir, "update-ref", "-d", ref)
    git(gitdir, "reflog", "expire", "--expire=now", "--all")
    git(gitdir, "gc", "-q", "--prune=now")

    problems = snap.check_git(gitdir, terms)
    if problems:
        shutil.move(out, out + ".refused")
        raise SystemExit("REFUSED: the new repo's git metadata:\n  %s" % "\n  ".join(problems))

    with open(os.path.join(out, "staging.tsv"), "w", encoding="utf-8", newline="\n") as f:
        f.write("asset\tbytes\tsha256\tfrom\n")
        for path in (installer, mlt[0]):
            f.write("%s\t%d\t%s\t%s\n" % (os.path.basename(path), os.path.getsize(path), sha256(path), path))
        f.write("%s\t\t\ta tar of these %d archives, each under its own name: %s\n" % (
            msys2_tar, len(msys2), ";".join(msys2)))
    print("tag %s -> commit %s (tree %s)\nrepo %s\nRelease files: %s\nnothing pushed" % (
        a.tag, commit[:10], tree[:10], gitdir, ", ".join(assets)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
