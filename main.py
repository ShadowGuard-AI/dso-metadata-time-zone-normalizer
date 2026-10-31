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

# Matches a full timestamp (date and time together) inside text content.
TEXT_TIMESTAMP_PATTERN = re.compile(
    r"\d{4}[:\-/]\d{2}[:\-/]\d{2}[ T]\d{2}:\d{2}:\d{2}"
    r"|\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2}"
)

DATETIME_TAG_NAMES = ("DateTime", "DateTimeOriginal", "DateTimeDigitized")


class ProcessingError(Exception):
    """Raised when a file cannot be processed or saved."""


def setup_argparse():
    """
    Sets up the argument parser for the command-line interface.

    Returns:
        argparse.ArgumentParser: The argument parser object.
    """
    parser = argparse.ArgumentParser(description="Normalize timestamps in file metadata and text files from a source timezone to a target timezone.")
    parser.add_argument("file_path", help="Path to the file to process.")
    parser.add_argument("--timezone", default="UTC", help="Target timezone to normalize to (default: UTC).")
    parser.add_argument("--source-timezone", default="UTC", help="Timezone the existing timestamps are in (default: UTC).")
    parser.add_argument("--dry-run", action="store_true", help="Perform a dry run without modifying the file.")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging.")
    return parser

def normalize_timestamp(timestamp, source_timezone, target_timezone="UTC"):
    """
    Normalizes a timestamp string from a source timezone to a target timezone.

    Args:
        timestamp (str): The timestamp string to normalize.
        source_timezone (str): The timezone of the input timestamp.
        target_timezone (str): The timezone to convert to (default: UTC).

    Returns:
        str: The normalized timestamp string, or None if an error occurred.
    """
    # Attempt to parse the timestamp using a flexible format
    dt_object = None
    formats_to_try = ["%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%m/%d/%Y %H:%M:%S", "%d/%m/%Y %H:%M:%S"]
    for fmt in formats_to_try:
        try:
            dt_object = datetime.datetime.strptime(timestamp, fmt)
            break  # If parsing succeeds, exit the loop
        except ValueError:
            continue # Try the next format
    if dt_object is None:
        logging.error(f"Could not parse timestamp: {timestamp} with any known format. Please check your input format")
        return None

    # Localize the datetime object to the source timezone
    source_tz = pytz.timezone(source_timezone)
    localized_dt = source_tz.localize(dt_object)

    # Convert to the target timezone
    target_tz = pytz.timezone(target_timezone)
    converted_dt = localized_dt.astimezone(target_tz)

    # Format the output timestamp string
    return converted_dt.strftime("%Y:%m:%d %H:%M:%S")

def process_image_file(file_path, source_timezone, target_timezone, dry_run, verbose):
    """
    Processes an image file to normalize timestamps in its EXIF data.

    Args:
        file_path (str): The path to the image file.
        source_timezone (str): The timezone the existing EXIF timestamps are in.
        target_timezone (str): The timezone to convert to.
        dry_run (bool): Whether to perform a dry run without modifying the file.
        verbose (bool): Whether to enable verbose logging.

    Returns:
        int: The number of EXIF datetime tags updated (or that would be updated on a dry run).

    Raises:
        ProcessingError: If the file cannot be read, a datetime tag cannot be parsed, or the save fails.
    """
    try:
        img = Image.open(file_path)
        exif_data = img._getexif()
    except (IOError, OSError) as e:
        raise ProcessingError(f"Error opening or processing file {file_path}: {e}")
    except Exception as e:
        raise ProcessingError(f"An unexpected error occurred while processing {file_path}: {e}")

    if exif_data is None:
        logging.warning(f"No EXIF data found in {file_path}")
        return 0

    updated_exif = {}
    for tag_id, value in exif_data.items():
        tag = ExifTags.TAGS.get(tag_id, tag_id)
        if verbose:
            logging.info(f"Processing tag: {tag} with value: {value}")

        # Normalize DateTime, DateTimeOriginal, DateTimeDigitized
        if tag in DATETIME_TAG_NAMES:
            normalized_timestamp = normalize_timestamp(value, source_timezone, target_timezone)
            if normalized_timestamp is None:
                raise ProcessingError(f"Failed to parse {tag} with value: {value}")
            updated_exif[tag_id] = normalized_timestamp
            logging.info(f"Normalized {tag} from {value} to {normalized_timestamp} ({target_timezone})")

    if not updated_exif:
        logging.info(f"No DateTime related EXIF data found or updated in {file_path}")
        return 0

    if dry_run:
        logging.info(f"Dry run: EXIF data would be updated in {file_path} with the following changes: {updated_exif}")
        return len(updated_exif)

    try:
        # Update the EXIF data through the mapping Pillow exposes and save it back.
        new_exif = img.getexif()
        for tag_id, new_value in updated_exif.items():
            new_exif[tag_id] = new_value
        img.save(file_path, exif=new_exif)
    except Exception as e:
        raise ProcessingError(f"Failed to save updated EXIF data in {file_path}: {e}")
    logging.info(f"Successfully updated EXIF data in {file_path}")
    return len(updated_exif)

def process_text_file(file_path, source_timezone, target_timezone, dry_run, verbose):
    """
    Processes a text file, normalizing full timestamp strings found within its content.
    A timestamp is only handled when its date and time appear together as one string.

    Args:
        file_path (str): Path to the text file.
        source_timezone (str): Timezone the existing timestamps are in.
        target_timezone (str): Timezone to normalize to.
        dry_run (bool): Whether to perform a dry run.
        verbose (bool): Enable verbose logging.

    Returns:
        int: The number of timestamps updated (or that would be updated on a dry run).

    Raises:
        ProcessingError: If the file cannot be read, a matched timestamp cannot be parsed, or the save fails.
    """
    try:
        # Detect file encoding
        with open(file_path, 'rb') as f:
            result = chardet.detect(f.read())
        encoding = result['encoding'] or 'utf-8'

        with open(file_path, 'r', encoding=encoding) as f:
            content = f.read()
    except FileNotFoundError:
        raise ProcessingError(f"File not found: {file_path}")
    except UnicodeDecodeError as e:
        raise ProcessingError(f"UnicodeDecodeError: {e}. Consider specifying the correct file encoding.")
    except Exception as e:
        raise ProcessingError(f"Error processing text file: {e}")

    replacements = {}

    def replace_timestamp(match):
        original = match.group(0)
        if original not in replacements:
            normalized_timestamp = normalize_timestamp(original, source_timezone, target_timezone)
            if normalized_timestamp is None:
                raise ProcessingError(f"Failed to parse timestamp: {original}")
            replacements[original] = normalized_timestamp
            logging.info(f"Normalized timestamp {original} to {normalized_timestamp} ({target_timezone})")
        return replacements[original]

    normalized_content = TEXT_TIMESTAMP_PATTERN.sub(replace_timestamp, content)
    update_count = sum(1 for _ in TEXT_TIMESTAMP_PATTERN.finditer(content))

    if not replacements:
        logging.info(f"No recognizable timestamps found or updated in {file_path}")
        return 0

    if dry_run:
        logging.info(f"Dry run: timestamps would be normalized in {file_path} with the following changes: {replacements}")
        return update_count

    try:
        with open(file_path, 'w', encoding=encoding) as f:
            f.write(normalized_content)
    except Exception as e:
        raise ProcessingError(f"Failed to save normalized timestamps in {file_path}: {e}")
    logging.info(f"Successfully normalized timestamps in {file_path}")
    return update_count

def main():
    """
    Main function to execute the timestamp normalization process.
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

    # Validate both timezones before touching the file.
    for zone_name in (source_timezone, target_timezone):
        try:
            pytz.timezone(zone_name)
        except pytz.exceptions.UnknownTimeZoneError:
            logging.error(f"Invalid timezone: {zone_name}")
            sys.exit(1)

    file_extension = os.path.splitext(file_path)[1].lower()
    try:
        if file_extension in (".jpg", ".jpeg", ".png", ".tiff", ".tif"):
            updated = process_image_file(file_path, source_timezone, target_timezone, dry_run, args.verbose)
        elif file_extension in (".txt", ".log", ".csv", ".json", ".xml"):
            updated = process_text_file(file_path, source_timezone, target_timezone, dry_run, args.verbose)
        else:
            logging.error(f"Unsupported file type: {file_extension}. Only image and text files are currently supported.")
            sys.exit(1)
    except ProcessingError as e:
        logging.error(str(e))
        sys.exit(1)

    if updated == 0:
        print(f"No changes made: no timestamps were updated in {file_path}.")
        sys.exit(1)

if __name__ == "__main__":
    main()
