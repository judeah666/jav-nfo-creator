# JAV NFO Creator

Current version:
- `1.0.0`

`JAV NFO Creator` is a Windows desktop app for creating and organizing movie metadata files.

It combines two tools in one app:
- `NFO Editor`: edit a single movie `.nfo` / `.xml`
- `Batch Editor`: scan a library and batch-update actor data

## Main Features

- create and edit movie `.nfo` / `.xml` files
- manage actors with thumbnails
- save poster and backdrop images from remote links
- create a movie folder with consistent naming
- create a full movie package in one step:
  - folder
  - `.nfo`
  - poster / backdrops
  - optional renamed movie file
- batch-edit actor metadata across many files

## App Layout

The packaged app opens as one combined window with:
- `NFO Editor` tab
- `Batch Editor` tab

Inside `NFO Editor`, the movie editor includes:
- `Movie Settings`
- `Poster`

## Run From Source

From the repo root:

```powershell
python -m app.main
```

You can also run the tools directly:

```powershell
python -m app.combined_app
python -m app.batch_main
```

## Tests

```powershell
python -B -m unittest discover -s tests -v
```

## Versioning

This project uses `MAJOR.MINOR.PATCH`.

Current release:
- `v1.0.0`

Examples:
- `1.0.0`: first stable release
- `1.1.0`: new features or workflow improvements
- `1.1.1`: bug fixes and small polish

## Build Release

The release format is a PyInstaller `--onedir` build.

```powershell
powershell -ExecutionPolicy Bypass -File .\build_release.ps1
```

Release folder:
- `dist\JAVNFOCreator-v1.0.0`

Launcher:
- `dist\JAVNFOCreator-v1.0.0\JAVNFOCreator-v1.0.0.exe`

## 32-bit Build

```powershell
powershell -ExecutionPolicy Bypass -File .\build_release_x86.ps1
```

Release folder:
- `dist\JAVNFOCreator-v1.0.0-32bit`

Launcher:
- `dist\JAVNFOCreator-v1.0.0-32bit\JAVNFOCreator-v1.0.0-32bit.exe`

## Repo Layout

- `app/`: application source
- `tests/`: automated tests
- `assets/`: icons and shared assets
- `build_release.ps1`: main release build
- `build_release_x86.ps1`: 32-bit release build
- `app/version.py`: app version constants used for release bookkeeping

## Notes

- keep the whole release folder together
- do not move only the `.exe` out of the release folder
- generated `build/`, `dist/`, and PyInstaller `.spec` files should not be committed as normal source files
- recommended GitHub release tag:
  - `v1.0.0`
