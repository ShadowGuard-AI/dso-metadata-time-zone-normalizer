import argparse
import os
import re
import sys
import logging
import datetime
import pytz
from PIL import Image, ExifTags
import chardet

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


class ProcessingError(Exception):
    """Raised when a file cannot be processed; main turns this into exit 1."""


# Full timestamp patterns for text files: date and time captured together.
TEXT_TIMESTAMP_FORMATS = [
    "%Y:%m:%d %H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y/%m/%d %H:%M:%S",
    "%m/%d/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M:%S",
]
TEXT_TIMESTAMP_RE = re.compile(
    r"\d{4}:\d{2}:\d{2} \d{2}:\d{2}:\d{2}"
    r"|\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}"
    r"|\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}"
    r"|\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2}"
)

EXIF_DATETIME_TAGS = ("DateTime", "DateTimeOriginal", "DateTimeDigitized")
# Tags that live in the Exif IFD rather than IFD0.
EXIF_IFD_TAGS = (36867, 36868)


def setup_argparse():
    """
    Sets up the argument parser for the command-line interface.

    Returns:
        argparse.ArgumentParser: The argument parser object.
    """
    parser = argparse.ArgumentParser(description="Normalize timestamps in file metadata to a target timezone.")
    parser.add_argument("file_path", help="Path to the file to process.")
    parser.add_argument("--timezone", default="UTC", help="Timezone to normalize to (default: UTC).")
    parser.add_argument("--source-timezone", default="UTC",
                        help="Timezone the existing timestamps are in (default: UTC).")
    parser.add_argument("--dry-run", action="store_true", help="Perform a dry run without modifying the file.")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging.")
    return parser


def convert_timestamp(timestamp, source_timezone, target_timezone, output_format="%Y:%m:%d %H:%M:%S"):
    """
    Converts a timestamp string from a source timezone to a target timezone.

    Returns the converted string in output_format, or None if the timestamp
    cannot be parsed with any known format.
    """
    dt_object = None
    for fmt in TEXT_TIMESTAMP_FORMATS:
        try:
            dt_object = datetime.datetime.strptime(timestamp, fmt)
            break
        except ValueError:
            continue
    if dt_object is None:
        logging.error(f"Could not parse timestamp: {timestamp} with any known format. Please check your input format")
        return None

    source_tz = pytz.timezone(source_timezone)
    localized_dt = source_tz.localize(dt_object)
    target_tz = pytz.timezone(target_timezone)
    converted_dt = localized_dt.astimezone(target_tz)
    return converted_dt.strftime(output_format)


def normalize_timestamp(timestamp, source_timezone, target_timezone="UTC"):
    """Backward compatible wrapper returning EXIF formatted output."""
    try:
        return convert_timestamp(timestamp, source_timezone, target_timezone)
    except pytz.exceptions.UnknownTimeZoneError as e:
        logging.error(f"Invalid timezone: {e}")
        return None
    except Exception as e:
        logging.error(f"Error normalizing timestamp: {e}")
        return None


def process_image_file(file_path, target_timezone, source_timezone, dry_run, verbose):
    """
    Processes an image file to normalize timestamps in its EXIF data.

    Returns True if at least one timestamp was updated (or would be updated
    on a dry run). Raises ProcessingError on any failure.
    """
    try:
        img = Image.open(file_path)
        exif_data = img._getexif()
    except FileNotFoundError:
        raise ProcessingError(f"File not found: {file_path}")
    except (IOError, OSError) as e:
        raise ProcessingError(f"Error opening or processing file {file_path}: {e}")

    if exif_data is None:
        logging.warning(f"No EXIF data found in {file_path}")
        return False

    updated_exif = {}
    failed_tags = []
    for tag_id, value in exif_data.items():
        tag = ExifTags.TAGS.get(tag_id, tag_id)
        if verbose:
            logging.info(f"Processing tag: {tag} with value: {value}")

        if tag in EXIF_DATETIME_TAGS:
            normalized_timestamp = normalize_timestamp(value, source_timezone, target_timezone)
            if normalized_timestamp:
                updated_exif[tag_id] = normalized_timestamp
                logging.info(f"Normalized {tag} from {value} to {normalized_timestamp} ({target_timezone})")
            else:
                failed_tags.append(tag)
                logging.warning(f"Failed to normalize {tag} with value: {value}")

    if failed_tags:
        raise ProcessingError(f"Could not normalize EXIF timestamp tag(s) {failed_tags} in {file_path}")

    if not updated_exif:
        logging.info(f"No DateTime related EXIF data found or updated in {file_path}")
        return False

    if dry_run:
        logging.info(f"Dry run: EXIF data would be updated in {file_path} with the following changes: {updated_exif}")
        return True

    # Write the updated values back with the Pillow API that exists in
    # Pillow 10.x: set each tag on the Exif object itself and pass it to
    # save as bytes. Tags 36867 and 36868 also get set through the Exif
    # IFD mapping when the file carries one. The IFD mapping alone is
    # not enough: on Pillow 10.2 get_ifd returns a plain dict whose
    # changes never reach the saved file, so a run that only wrote
    # there reported success while those two tags kept their old
    # values on disk.
    try:
        exif = img.getexif()
        for tag_id, new_value in updated_exif.items():
            exif[tag_id] = new_value
            if tag_id in EXIF_IFD_TAGS:
                try:
                    exif.get_ifd(0x8769)[tag_id] = new_value
                except Exception:
                    pass
        img.save(file_path, exif=exif.tobytes())
    except Exception as e:
        raise ProcessingError(f"Failed to save updated EXIF data in {file_path}: {e}")

    # A save only counts when the new values read back from disk. If a
    # tag did not persist, the run fails instead of reporting success.
    try:
        saved_exif = Image.open(file_path)._getexif() or {}
    except Exception as e:
        raise ProcessingError(f"Failed to read back EXIF data in {file_path} after saving: {e}")
    for tag_id, new_value in updated_exif.items():
        if saved_exif.get(tag_id) != new_value:
            raise ProcessingError(
                f"Save did not persist tag {ExifTags.TAGS.get(tag_id, tag_id)} in {file_path}"
            )
    logging.info(f"Successfully updated EXIF data in {file_path}")
    return True


def process_text_file(file_path, target_timezone, source_timezone, dry_run, verbose):
    """
    Processes a text file, normalizing full timestamp strings (date and
    time together) found within its content, in place.

    Returns True if at least one timestamp was updated (or would be updated
    on a dry run). Raises ProcessingError on any failure.
    """
    try:
        with open(file_path, 'rb') as f:
            result = chardet.detect(f.read())
        encoding = result['encoding'] or 'utf-8'

        with open(file_path, 'r', encoding=encoding) as f:
            content = f.read()
    except FileNotFoundError:
        raise ProcessingError(f"File not found: {file_path}")
    except UnicodeDecodeError as e:
        raise ProcessingError(f"UnicodeDecodeError: {e}. Consider specifying the correct file encoding.")

    replacements = {}
    failures = []

    def replace_match(match):
        original = match.group(0)
        if original in replacements:
            return replacements[original]
        if original in failures:
            return original
        output_format = None
        for fmt in TEXT_TIMESTAMP_FORMATS:
            try:
                datetime.datetime.strptime(original, fmt)
                output_format = fmt
                break
            except ValueError:
                continue
        converted = None
        if output_format is not None:
            converted = convert_timestamp(original, source_timezone, target_timezone, output_format)
        if converted is None:
            failures.append(original)
            return original
        replacements[original] = converted
        logging.info(f"Normalized timestamp {original} to {converted} ({target_timezone})")
        return converted

    normalized_content = TEXT_TIMESTAMP_RE.sub(replace_match, content)

    if failures:
        raise ProcessingError(f"Could not parse timestamp(s) {failures} in {file_path}")

    if not replacements:
        logging.info(f"No recognizable timestamps found or updated in {file_path}")
        return False

    if dry_run:
        logging.info(f"Dry run: timestamps would be normalized in {file_path} with the following changes: {replacements}")
        return True

    try:
        with open(file_path, 'w', encoding=encoding) as f:
            f.write(normalized_content)
    except (IOError, OSError) as e:
        raise ProcessingError(f"Failed to write normalized content to {file_path}: {e}")
    logging.info(f"Successfully normalized timestamps in {file_path}")
    return True


def main():
    """
    Main function to execute the timestamp normalization process.

    Exit codes: 0 when at least one timestamp was updated, or on a dry run
    that found timestamps to update. 1 when the file is missing, the
    timezone is invalid, the file type is unsupported, processing or
    saving fails, or no timestamp was updated.
    """
    parser = setup_argparse()
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    file_path = args.file_path
    target_timezone = args.timezone
    source_timezone = args.source_timezone
    dry_run = args.dry_run

    if not os.path.exists(file_path):
        logging.error(f"File not found: {file_path}")
        sys.exit(1)

    for tz_name in (source_timezone, target_timezone):
        try:
            pytz.timezone(tz_name)
        except pytz.exceptions.UnknownTimeZoneError:
            logging.error(f"Invalid timezone: {tz_name}")
            sys.exit(1)

    file_extension = os.path.splitext(file_path)[1].lower()
    try:
        if file_extension in (".jpg", ".jpeg", ".png", ".tiff", ".tif"):
            updated = process_image_file(file_path, target_timezone, source_timezone, dry_run, args.verbose)
        elif file_extension in (".txt", ".log", ".csv", ".json", ".xml"):
            updated = process_text_file(file_path, target_timezone, source_timezone, dry_run, args.verbose)
        else:
            logging.error(f"Unsupported file type: {file_extension}. Only image and text files are currently supported.")
            sys.exit(1)
    except ProcessingError as e:
        logging.error(str(e))
        sys.exit(1)
    except Exception as e:
        logging.error(f"An unexpected error occurred: {e}")
        sys.exit(1)

    if not updated:
        print(f"No changes made: no timestamps were updated in {file_path}.")
        sys.exit(1)


if __name__ == "__main__":
    main()
