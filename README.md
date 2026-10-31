![Banner](banner.png)

# dso-metadata-time-zone-normalizer
Command-line tool to normalize timestamps to a target timezone. For images it rewrites the three EXIF datetime tags (DateTime, DateTimeOriginal, DateTimeDigitized). For text files it rewrites full timestamp strings (date and time together) found in the content. Files are modified in place; use --dry-run to preview the changes first. Focused on tools for sanitizing and obfuscating sensitive data within text files and structured data formats.

What this tool does not do:
- It does not read or change filesystem creation or modification dates.
- It does not remove or change GPS tags or any other non datetime EXIF tags. Only the three datetime tags listed above are rewritten, so location data stored in GPS tags stays in the file.

## Install
`git clone https://github.com/ShadowGuard-AI/dso-metadata-time-zone-normalizer`

## Usage
`python3 main.py [params] file_path`

Example: `python3 main.py photo.jpg --source-timezone America/New_York --timezone UTC`

## Parameters
- `-h`: Show help message and exit
- `--timezone`: Timezone to normalize to (default: UTC).
- `--source-timezone`: Timezone the existing timestamps are in (default: UTC). Set this when the recorded times are local wall clock times rather than UTC.
- `--dry-run`: Perform a dry run without modifying the file. Reports what would change.
- `--verbose`: Enable verbose logging.

## Supported files
- Images: .jpg, .jpeg, .png, .tiff, .tif (EXIF datetime tags only)
- Text: .txt, .log, .csv, .json, .xml (full timestamp strings in the formats YYYY:MM:DD HH:MM:SS, YYYY-MM-DD HH:MM:SS, YYYY/MM/DD HH:MM:SS, MM/DD/YYYY HH:MM:SS, DD/MM/YYYY HH:MM:SS; converted values keep the format they were found in)

## Exit codes
- 0: At least one timestamp was updated. A dry run that finds timestamps to update also exits 0, because the check was performed.
- 1: The file does not exist, a timezone is invalid, the file type is unsupported, a timestamp could not be parsed, saving or writing failed, or no timestamp was updated. Runs that update nothing print a plain "No changes made" line.

## License
Copyright (c) ShadowGuardAI
