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

- It **reads** the `.max` file you choose and the texture files it names, found as below. It never runs anything
  from a file: no MAXScript, no embedded code.
- It sends nothing anywhere. The only network request of the add-on is the **Check for Updates** button, which
  reads `https://jsiovn.github.io/maxdrop/index.json`.
- Texture paths stored in a scene are untrusted. Only their file name is looked up: in the scene's folder, in
  `maps` or `textures` folders beside it, and in the texture search folders you set in the preferences. The stored
  path itself is opened only when it is a full path on a local drive and names a plain file; a network path
  (`\\server\share`), a device path, a relative path or one that climbs with `..` is never opened, and the search
  does not follow links or junctions.
- Importing a `.max` writes nothing. Importing a scene pack writes the unpacked scene, as below.

### Scene packs (`.zip`, `.rar`, `.7z`)

- **What is written, and where.** Only the `.max` you import and the pack's image and `.ies` files it names (all of
  them when its asset list cannot be read), into one new folder named after the archive: next to the archive, or
  inside the folder set under *Unpack Scene Packs Into* in the preferences. The folder is flat: a path stored in
  the archive never decides where a file goes, only its file name is used, and names that Windows cannot store,
  reserved device names and over-long names are refused. Files are written into a temporary folder beside the
  destination and renamed when complete; on any error that folder is removed. A folder without MaxDrop's marker
  file (`.maxdrop-pack.json`) is never written into, and MaxDrop removes only folders it created itself.
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
  extraction are refused (UnRAR 7.23, 7-Zip 26.02, libarchive 3.8.8); a bsdtar of the operating system on macOS and
  Linux is accepted whatever version it prints, because distributions backport fixes without changing it. The
  program runs without a shell, with its own folder as working directory, a reduced environment, no input, a time
  limit and capped output. It unpacks into a private folder, and its result is checked file by file (plain files
  only, exactly the names asked for) before anything is moved into place.

## Known limits of this version

A `.max` file is a complex binary format. From version 0.0.4 MaxDrop's own reader reads everything it imports,
nodes, meshes, transforms and materials (and from 0.1.0 lights and cameras; an IES file a light names is not
opened); the parser inherited from io_scene_max is gone. What it guards against:

- **Sizes, offsets and indices** taken from the file are checked against the stream or the array they point into
  before anything is read or allocated: every sector of the compound file, every chunk against its parent, every
  record count against the bytes that hold it, every vertex and object index against its list.
- **Loops and depth:** sector chains, the directory tree, parents, references, controllers and look-at targets are
  checked for cycles; chunks nest at most 64 levels, controllers 32, texture-map graphs and material wrappers 8,
  and the code that recurses stays within these limits.
- **Counts:** at most 65,536 directory entries, 4 million chunks per level, 1 million references per object,
  1 million objects per scene, 64 million vertices and 128 million face corners per mesh, and a cap on the
  generated geometry of primitives, extrusions and modifiers; a compressed stream inflates to at most 4 GiB.
- **One kind of error:** anything malformed raises MaxFileError, and the import ends in "Not imported" with its
  message; a memory or recursion failure that slips past these checks is reported the same way.

The reader is fuzzed: the plain test suite runs a fixed slice of mutated fixtures (and mutated scene packs) on
every change, and this version was run against 100,000 mutations of every fixture (bits flipped, files cut,
chunk sizes and counts set to extremes, directory entries, FAT entries and sectors bent), each required to read or
be refused within 5 seconds and 1 GB. Fuzzing finds defects; it does not prove there are none. A hostile file can
still make Blender use a lot of memory or take long within those caps, and a defect can still stop the import with
a Python error. Memory safety is Python's, so the realistic risk is a hang or a crash of that Blender session, not
code execution: treat files from unknown sources with the usual care and save your work before importing.

Scene packs are fuzzed the same way (central directory, local headers, names, sizes, flags, compression methods,
attributes, truncation): each must unpack into its own folder or be refused, never write outside it or leave a
staging folder behind, and the name rules are tested on random names.

A texture file found by its stored path is checked (a local drive, a plain file, no link or junction in the path)
when the scene is imported, and Blender opens it a moment later. Something that can already write into that
folder could swap the file for a link in between. This is an accepted risk: it needs a program already running on
your computer with access to that folder, and the window ends when the image is loaded.

MaxDrop's reader maps the `.max` file into memory read-only instead of copying it. If the file is truncated or
rewritten in place while an import reads it (another program writing it, a network share that drops), the
operating system can end the Blender process (SIGBUS on Linux and macOS, an in-page error on Windows) instead of
raising an error MaxDrop could report. This is an accepted risk: the mapping lives only while one import reads the
file and builds its objects. Copy a scene to a local disk before importing it if something else may change it
meanwhile.
