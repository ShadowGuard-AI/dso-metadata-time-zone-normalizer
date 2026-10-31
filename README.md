![Banner](banner.png)

# dso-metadata-time-zone-normalizer
Command-line tool to normalize timestamps to a target timezone. For images (.jpg, .jpeg, .png, .tiff, .tif) it rewrites the three EXIF datetime tags (DateTime, DateTimeOriginal, DateTimeDigitized) in place. For text files (.txt, .log, .csv, .json, .xml) it rewrites full timestamp strings (date and time together) in place. Files are modified in place by design; use --dry-run to preview the changes first. - Focused on Tools for sanitizing and obfuscating sensitive data within text files and structured data formats

## What it does not do
- It does not read or change filesystem creation or modification dates. Only the EXIF datetime tags in images and full timestamp strings in text files are handled.
- It does not remove GPS tags or any other non datetime tags. Only the three EXIF datetime tags listed above are rewritten; every other tag is left exactly as it was.

## Install
`git clone https://github.com/ShadowGuard-AI/dso-metadata-time-zone-normalizer`

## Usage
`python3 main.py [params] file_path`

## Parameters
- `-h`: Show help message and exit
- `--timezone`: Target timezone to normalize to (default: UTC).
- `--source-timezone`: Timezone the existing timestamps are in (default: UTC). The stored values are read as wall clock times in this zone and converted to the target zone.
- `--dry-run`: Perform a dry run without modifying the file. Reports what would change.
- `--verbose`: Enable verbose logging.

## Exit behavior
- Exit 0: at least one timestamp was updated, or, with --dry-run, at least one timestamp was found that would be updated. A dry run writes nothing.
- Exit 1: the file is missing, the target or source timezone is invalid, the file extension is not supported, a timestamp or the file could not be parsed, the save failed, or no timestamp was updated. A run that updates nothing prints a plain "No changes made" line and exits 1. A dry run that finds no timestamps also exits 1.

## License
Copyright (c) ShadowGuard-AI
