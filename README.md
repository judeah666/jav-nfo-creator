# JAV NFO Creator

JAV NFO Creator is a Windows Tkinter desktop app for creating and editing **JAV `.nfo` / `.xml` metadata** files.

It is built for a JAV-focused metadata workflow, including helpers for movie-code naming, JAVDB links, tags, posters, backdrops, and actor editing.

## Features

- create and edit JAV `.nfo` / `.xml` metadata
- JAVDB link helper
- title, year, tag, and original-title naming helpers
- actor editing support
- poster and backdrop link fields
- genre parsing and metadata formatting helpers
- desktop UI for local metadata editing

## Running From Source

```powershell
python -m app.main
```

Or install in editable mode:

```powershell
pip install -e .
jav-nfo-creator
```

## Release Build

The packaged release uses a PyInstaller **one-folder** build.

Requires a **64-bit Python** with PyInstaller available in that interpreter.

```powershell
powershell -ExecutionPolicy Bypass -File .\build_release.ps1 -Python64 "C:\Path\To\Python64\python.exe"
```

Output:
- `dist\JAVNFOCreator\JAVNFOCreator.exe`

Keep the whole output folder together. Do not move only the `.exe`.

## Repository Layout

- `app/`: application source
- `assets/`: application icon assets
- `tests/`: automated tests
- `build_release.ps1`: release build script

## Notes

- `build/` and `dist/` are generated output and should not normally be committed
- generated PyInstaller `.spec` files are intentionally ignored
- packaged builds are better distributed through **GitHub Releases**
