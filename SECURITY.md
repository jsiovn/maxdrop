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
- It writes nothing next to your scene and sends nothing anywhere. The only network request of the add-on is the
  **Check for Updates** button, which reads `https://jsiovn.github.io/maxdrop/index.json`.
- Texture paths stored in a scene are reduced to their file name before the lookup, which starts in the scene's
  own folder: the importer does not follow a path stored in the file to another place on your disk or on the
  network.

## Known limits of this version

A `.max` file is a complex binary format and version 0.0.1 uses the parser inherited from io_scene_max as it is.
It has not been hardened against malformed or hostile files yet: such a file can make Blender use a lot of
memory, take very long or stop with a Python error. Memory safety is Python's, so the realistic risk is a hang
or a crash of that Blender session, not code execution, but treat files from unknown sources with the usual
care and save your work before importing. Bounded reads, depth and size limits are part of the reader rework.
