# Test packs

Self-made, tiny, dummy content only; read by `tests/test_intake_external.py`. Every file holds the same tree
(`TREE` in that test), all dates 2020-01-01:

```
pack/scene/scene.max      pack/scene/maps/wood.jpg   pack/other/wood.jpg
pack/sub dir/my map.png   pack/scene/light.IES       pack/readme.txt
```

| File | Made with |
|---|---|
| `normal.rar` | RAR 7.23 `a -r -ma5 -m3` |
| `solid.rar` | RAR 7.23 `a -r -ma5 -m3 -s` |
| `pwdata.rar` | RAR 7.23 `a -r -ma5 -pmaxdrop` (password on the data) |
| `pwhead.rar` | RAR 7.23 `a -r -ma5 -hpmaxdrop` (password on the data and the names) |
| `plain.7z` | bsdtar 3.8.9 `-a -cf` |

Before they were committed, their bytes were scanned (ASCII and UTF-16LE, case-insensitive) for the user name,
the computer name and user path prefixes: no hit.
