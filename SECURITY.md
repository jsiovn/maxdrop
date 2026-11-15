# Security

## Supported versions

Only the latest released version of MaxDrop gets fixes. Blender updates it from the extension repository.

## Reporting a vulnerability

Please do not open a public issue for a security problem. Use **Report a vulnerability** on the
[Security tab](https://github.com/jsiovn/maxdrop/security/advisories/new) of the repository (GitHub's private
vulnerability reporting). Say which version of MaxDrop and of Blender you used and how to reproduce the problem;
a `.max` file that triggers it helps most, attached to the private report rather than posted anywhere public.

You should get an answer within a week. Once a fix is released, the advisory is published and credits you
unless you prefer otherwise.

## What MaxDrop does with a file

- It **reads** the `.max` file you choose and the image files beside it. It never runs anything from a file: no
  MAXScript, no embedded code.
- It sends nothing anywhere. The only network request of the add-on is the **Check for Updates** button, which
  reads `https://jsiovn.github.io/maxdrop/index.json`.
- Texture paths stored in a scene are reduced to their file name before the lookup, which starts in the scene's
  own folder: the importer does not follow a path stored in the file to another place on your disk or on the
  network.
- Importing a `.max` writes nothing. Importing a scene pack writes the unpacked scene, as below.

### Scene packs (`.zip`, `.rar`, `.7z`)

- **What is written, and where.** Only the `.max` you import and the pack's image and `.ies` files, into one new
  folder named after the archive: next to the archive, or inside the folder set under *Unpack Scene Packs Into* in
  the preferences. The folder is flat: a path stored in the archive never decides where a file goes, only its file
  name is used, and names that Windows cannot store, reserved device names and over-long names are refused. Files
  are written into a temporary folder beside the destination and renamed when complete; on any error that folder
  is removed. A folder without MaxDrop's marker file (`.maxdrop-pack.json`) is never written into, and MaxDrop
  removes only folders it created itself.
- **What is never unpacked or run.** Everything else in a pack: scripts, programs, documents, other files. Links
  and other special files are refused. Nothing from a pack is executed or loaded as code. Limits on the number of
  files, the bytes really written, the time and the free disk space stop an archive that unpacks to far more than
  it claims.
- **Which programs may be started.** A `.zip` is read by Python's own `zipfile` module. For a `.rar` or `.7z`
  MaxDrop starts a program that is already installed, never one it brings: UnRAR (in the WinRAR folder), 7-Zip or
  bsdtar (`tar.exe` in the Windows system folder; `bsdtar` or `tar` in fixed folders such as `/usr/bin` or
  `/opt/homebrew/bin` on macOS and Linux). It is taken only from those fixed absolute paths or from the install
  folder the WinRAR and 7-Zip installers record, never from the current folder, `PATH` or the archive's folder, and
  only a native program, never a script. Versions before the vendor's fix of known path or link problems on
  extraction are refused (UnRAR 7.23, 7-Zip 25.01, libarchive 3.7.4); a bsdtar of the operating system on macOS and
  Linux is accepted whatever version it prints, because distributions backport fixes without changing it. The
  program runs without a shell, with its own folder as working directory, a reduced environment, no input, a time
  limit and capped output. It unpacks into a private folder, and its result is checked file by file (plain files
  only, exactly the names asked for) before anything is moved into place.

## Known limits of this version

A `.max` file is a complex binary format. In version 0.0.3 MaxDrop's own reader reads the nodes, meshes and
transforms with bounded reads, depth and entry limits and a size cap on compressed streams. The materials still
go through the parser inherited from io_scene_max as it is, which reads the whole file a second time and has not
been hardened against malformed or hostile files: such a file can make Blender use a lot of memory, take very
long or stop with a Python error. Memory safety is Python's, so the realistic risk is a hang or a crash of that
Blender session, not code execution, but treat files from unknown sources with the usual care and save your work
before importing. The inherited parser goes away as the material conversion moves to MaxDrop's reader.
