# JAV NFO Creator

Current version:
- `1.0.0.1`

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
  - optional multipart movie support
- batch-edit actor metadata across many files

## Create Movie

`Create Movie` can work with zero, one, or multiple video files.

- no video selected: create the folder, `.nfo`, and images only
- one video selected: create the folder, save the `.nfo` and images, then rename and move the video into the folder
- multiple videos selected: create one movie folder and rename each video as `-Part-1`, `-Part-2`, and so on
- for multipart movies, only `Part 1` gets the `.nfo` and images

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

This project uses `MAJOR.MINOR.PATCH.REVISION`.

Current release:
- `v1.0.0.1`

Examples:
- `1.0.0.1`: packaging or safety revision on top of an existing release
- `1.0.1.0`: bug fixes and small polish
- `1.1.0.0`: new features or workflow improvements

## Build Release

The release format is a PyInstaller `--onedir` build.

The main build script now auto-detects a 64-bit Python interpreter, stops if only 32-bit Python is available, and builds with `--noupx`.

```powershell
powershell -ExecutionPolicy Bypass -File .\build_release.ps1
```

Release folder:
- `dist\JAVNFOCreator-v1.0.0.1`

Launcher:
- `dist\JAVNFOCreator-v1.0.0.1\JAVNFOCreator-v1.0.0.1.exe`

## 32-bit Build

```powershell
powershell -ExecutionPolicy Bypass -File .\build_release_x86.ps1
```

Release folder:
- `dist\JAVNFOCreator-v1.0.0.1-32bit`

Launcher:
- `dist\JAVNFOCreator-v1.0.0.1-32bit\JAVNFOCreator-v1.0.0.1-32bit.exe`

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
- generated PyInstaller spec files are written under `build\spec`
- recommended GitHub release tag:
  - `v1.0.0.1`
