# maxdrop-voo: workflow actions off Node.js 20

## Finding

The bead's change is already on `main`. Dependabot (`.github/dependabot.yml`, one weekly group for all
actions) opened #6, merged as `5155162` on 2026-11-15:

| Action | From | To | `runs.using` at the new tag | Latest release (2026-11-17) |
|---|---|---|---|---|
| actions/checkout | v4 | v7 | node24 | v7.0.1 |
| actions/setup-python | v5 | v7 | node24 | v7.1.0 |
| actions/cache | v4 | v6 | node24 | v6.1.0 |
| actions/upload-pages-artifact | v3 | v5 | composite, uses upload-artifact v7.0.0 | v5.0.0 |
| actions/upload-artifact | v4 | v7 | node24 | v7.0.2 |
| actions/deploy-pages | v4 | v5 | node24 | v5.0.1 |
| actions/download-artifact | v4 | v8 | node24 | v8.0.2 |

Every action is on its current major; the pairs match (upload-pages-artifact v5 is built on upload-artifact v7,
which deploy-pages v5 reads; download-artifact v8 reads what upload-artifact v7 wrote).

Release notes checked for breaking changes that touch these workflows: none. download-artifact v5 changed the
path of downloads by ID and v8 (ESM, a hash mismatch now fails, no unzip of non-zip files) changed downloads of
non-zipped uploads; the release job downloads by `name:` an artifact upload-artifact v7 zipped by default, and
v7's direct (unzipped) upload is opt-in and not used. With a multi-path upload `dist/` is kept, so the release
step still finds `dist/$EXTENSION_ID-$VERSION.zip` and `release_notes.md`.

The Parallel section of the bead foresaw this: "If that bead adds Dependabot for GitHub Actions first, this one
may shrink to merging its pull requests." So no edit to `test.yml` or `publish.yml`.

## Verification

1. Static, on the files as they stand: both parse as YAML; `bash -n` on every bash `run` block (with `${{ }}`
   replaced); every `steps.<id>.outputs` reference has a step with that id in its job.
2. `python -I -m unittest discover tests` (the files are unchanged; the plain suite stays green).
3. Run evidence through `gh api` (annotations of each job's check run):
   - Run 43570703863 (v0.0.1, before #6): one Node.js annotation per job.
   - Run 44011103182 (push of `20fe776`, which contains `5155162`; released v0.0.4): build, deploy and release
     ran and succeeded with the new actions; no Node.js annotation on any job (only the ubuntu-latest notice).
   - Test run 44055372644 (PR #10, epic branch head `69372b8`): green, no Node.js annotation.
