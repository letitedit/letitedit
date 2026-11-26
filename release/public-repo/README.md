# The public release repository

letitedit's releases go on a public repository of their own, under letitedit's GitHub organization: each
release is one commit of its source (the tools at the top, the editor in `src/`), a tag, and a GitHub Release with the
installer. The development repositories are separate.

| File here | In the release repository |
|---|---|
| `release.yml` | `.github/workflows/release.yml`: publishes the Release for a pushed tag (below) |
| `notes.md` | `.github/release/notes.md`, filled in: the Release's text |

`release/source/make_public_repo.py` makes the repository's next state on the build PC (a bare git repo with the new
commit and tag, by `letitedit <teamletitedit@gmail.com>` in UTC) and `staging.tsv`, the Release's files.

## Publishing a release

Everything is done as the organization's GitHub App (its pushes and API calls show as `<app>[bot]`), with an
installation token made from the App's private key. A person's GitHub account is never used for the release
repository, because GitHub shows who pushed, who ran a workflow and who made a repository public.

1. Push `main` from `letitedit.git` (no tag yet, so nothing runs). Use only the App's token, sent as a header, and no
   credential helper (a PC's helper would sign in as its owner):
   `git -c credential.helper= -c http.extraHeader="Authorization: Basic <base64 of x-access-token:TOKEN>" push ...`
2. Upload the Release's files (`staging.tsv`; the MSYS2 archives as one tar) to a **draft** release named
   `staging-<tag>`. Drafts are not public.
3. Push the tag the same way. The push starts `release.yml` on GitHub's own runner (`ubuntu-latest`): it checks the
   draft's files against `.github/release/assets.txt`, publishes the Release as `github-actions[bot]` with
   `SHA256SUMS.txt`, and deletes the draft.

The workflow runs only on GitHub's runners: a self-hosted runner is never attached to a public repository. It uses
no actions and no secret but its own `GITHUB_TOKEN`, and only a tag push starts it.
