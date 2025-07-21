import argparse
import os
import sys
import logging
import datetime
import pytz
from PIL import Image, ExifTags
import chardet

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def setup_argparse():
    """
    Sets up the argument parser for the command-line interface.

    Returns:
        argparse.ArgumentParser: The argument parser object.
    """
    parser = argparse.ArgumentParser(description="Normalize timestamps in file metadata to UTC.")
    parser.add_argument("file_path", help="Path to the file to process.")
    parser.add_argument("--timezone", default="UTC", help="Timezone to normalize to (default: UTC).")
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
    try:
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
        utc_dt = localized_dt.astimezone(target_tz)

        # Format the output timestamp string
        return utc_dt.strftime("%Y:%m:%d %H:%M:%S")

    except pytz.exceptions.UnknownTimeZoneError as e:
        logging.error(f"Invalid timezone: {e}")
        return None
    except Exception as e:
        logging.error(f"Error normalizing timestamp: {e}")
        return None

def process_image_file(file_path, target_timezone, dry_run, verbose):
    """
    Processes an image file to normalize timestamps in its EXIF data.

    Args:
        file_path (str): The path to the image file.
        target_timezone (str): The timezone to convert to.
        dry_run (bool): Whether to perform a dry run without modifying the file.
        verbose (bool): Whether to enable verbose logging.
    """
    try:
        img = Image.open(file_path)
        exif_data = img._getexif()

        if exif_data is None:
            logging.warning(f"No EXIF data found in {file_path}")
            return

        updated_exif = {}
        for tag_id, value in exif_data.items():
            tag = ExifTags.TAGS.get(tag_id, tag_id)
            if verbose:
                logging.info(f"Processing tag: {tag} with value: {value}")

            # Normalize DateTime, DateTimeOriginal, DateTimeDigitized
            if tag in ("DateTime", "DateTimeOriginal", "DateTimeDigitized"):
                normalized_timestamp = normalize_timestamp(value, "UTC", target_timezone) #Assume UTC as source in EXIF if not specified
                if normalized_timestamp:
                    updated_exif[tag_id] = normalized_timestamp
                    logging.info(f"Normalized {tag} from {value} to {normalized_timestamp} ({target_timezone})")
                else:
                    logging.warning(f"Failed to normalize {tag} with value: {value}")

        if updated_exif:
            if not dry_run:
                # Update EXIF data
                for tag_id, new_value in updated_exif.items():
                    exif_data[tag_id] = new_value

                # Construct the new EXIF data
                new_exif = Image.ExifTags.ExifTag.string_to_bytes(Image.ExifTags.ExifTag.dict_to_bytes(exif_data))
                img.save(file_path, exif=new_exif)
                logging.info(f"Successfully updated EXIF data in {file_path}")
            else:
                logging.info(f"Dry run: EXIF data would be updated in {file_path} with the following changes: {updated_exif}")
        else:
            logging.info(f"No DateTime related EXIF data found or updated in {file_path}")


    except FileNotFoundError:
        logging.error(f"File not found: {file_path}")
    except (IOError, OSError) as e:
        logging.error(f"Error opening or processing file {file_path}: {e}")
    except Exception as e:
        logging.error(f"An unexpected error occurred while processing {file_path}: {e}")

def process_text_file(file_path, target_timezone, dry_run, verbose):
    """
    Processes a text file, attempting to normalize timestamps found within its content.
    This is a basic example and may require significant customization based on the
    specific format of timestamps within the target text files.

    Args:
        file_path (str): Path to the text file.
        target_timezone (str): Timezone to normalize to.
        dry_run (bool): Whether to perform a dry run.
        verbose (bool): Enable verbose logging.
    """
    try:
        # Detect file encoding
        with open(file_path, 'rb') as f:
            result = chardet.detect(f.read())
        encoding = result['encoding']

        with open(file_path, 'r', encoding=encoding) as f:
            content = f.read()

        #  Simple placeholder for timestamp detection.  Needs adaptation for real-world usage.
        #  Ideally, regular expressions or format-specific parsing should be used.
        #  This example just searches for strings that *look* like timestamps.
        potential_timestamps = []
        for line in content.splitlines():
            words = line.split()
            for word in words:
                try:
                    datetime.datetime.strptime(word, '%Y-%m-%d') # Check if it looks like a date
                    potential_timestamps.append(word)
                except ValueError:
                    pass

        normalized_content = content  # Start with the original content
        replacements = {}

        for timestamp in potential_timestamps:
             normalized_timestamp = normalize_timestamp(timestamp, "UTC", target_timezone) #Assume UTC - MUST BE ADAPTED
             if normalized_timestamp:
                 replacements[timestamp] = normalized_timestamp
                 normalized_content = normalized_content.replace(timestamp, normalized_timestamp)
                 logging.info(f"Normalized timestamp {timestamp} to {normalized_timestamp} ({target_timezone})")

        if replacements:
            if not dry_run:
                with open(file_path, 'w', encoding=encoding) as f:
                    f.write(normalized_content)
                logging.info(f"Successfully normalized timestamps in {file_path}")
            else:
                logging.info(f"Dry run: timestamps would be normalized in {file_path} with the following changes: {replacements}")
        else:
            logging.info(f"No recognizable timestamps found or updated in {file_path}")


    except FileNotFoundError:
        logging.error(f"File not found: {file_path}")
    except UnicodeDecodeError as e:
        logging.error(f"UnicodeDecodeError: {e}.  Consider specifying the correct file encoding.")
    except Exception as e:
        logging.error(f"Error processing text file: {e}")

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
    dry_run = args.dry_run

    if not os.path.exists(file_path):
        logging.error(f"File not found: {file_path}")
        sys.exit(1)

    try:
        # Determine file type (crude check, extend for more file types)
        file_extension = os.path.splitext(file_path)[1].lower()
        if file_extension in (".jpg", ".jpeg", ".png", ".tiff", ".tif"):
            process_image_file(file_path, target_timezone, dry_run, args.verbose)
        elif file_extension in (".txt", ".log", ".csv", ".json", ".xml"):
            process_text_file(file_path, target_timezone, dry_run, args.verbose)
        else:
            logging.warning(f"Unsupported file type: {file_extension}. Only image and text files are currently supported.")

    except Exception as e:
        logging.error(f"An unexpected error occurred: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()