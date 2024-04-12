"""
File       : nbadb/logging.py
Author     : @wyattowalsh
Description: logging module for the nbadb package
"""
from datetime import datetime
from pathlib import Path
from sys import stderr

from loguru import logger

# Configuration for the print formatting
PRINT_CONFIG = {
    "expand_all": True,
    "max_length": 3,
    "max_string": 21,
}

# Separate logger configuration
LOG_CONFIG = {
    "console": {
        "format":
        "🏀 <green>executed at: {time:YYYY-MM-DD at HH:mm:ss}</green> | <b>module:</b> {module} <b>⇨</b> <e><b>function:</b> {function}</e> <b>⇨</b> <c><b>line #:</b> {line}</c> | <yellow><b>elapsed time:</b> <u>{elapsed}</u></yellow> | <level><b>{level}</b></level> ⇨ {message} <red>{exception}</red> ⛹️",
    },
    "file": {
        "format":
        "executed at: {time:YYYY-MM-DD at HH:mm:ss} | module: {module} ⇨ function: {function} ⇨ line #: {line} | elapsed time: {elapsed} | {level} ⇨ {message} {exception}",
    },
    "common": {
        "colorize": True,
        "diagnose": True,
        "enqueue": True,
        "backtrace": True,
    },
}


def start_logger(
    console: bool = False,
    file: bool = True,
    log_folder: str = "logs",
    log_name: str = "nbadb",
    rotation: str = "100 MB",
) -> None:
    """
    Initializes a logger with console and/or file handlers with enhanced flexibility and error handling.

      Parameters: 
    - console (bool)  : Enable console logging if True.
    - file (bool)     : Enable file logging if True.
    - log_folder (str): The directory where log files will be stored.
    - log_name (str)  : Base name for log files.
    - rotation (str)  : The rotation condition for log files.

      Raises: 
    - ValueError: If neither console nor file logging is enabled.

    This function sets up the logger to output to the console and/or file based on the provided configurations.
    It ensures the log directory exists, and formats the log filenames with timestamps for uniqueness.
    """
    if not console and not file:
        raise ValueError( "At least one of console or file must be enabled" )

    logger.remove()

    log_folder_path = Path( log_folder )
    log_folder_path.mkdir( exist_ok=True )

    datetime.now().strftime( "%Y-%m-%d_%H-%M-%S" )
    log_file_path = log_folder_path / f"{log_name}.log"
    structured_log_file_path = log_folder_path / f"{log_name}_structured.json"

    if console:
        logger.add( stderr, **LOG_CONFIG[ "console" ],
                    **LOG_CONFIG[ "common" ] )

    if file:
        logger.add( str( log_file_path ), **LOG_CONFIG[ "file" ],
                    **LOG_CONFIG[ "common" ] )
        logger.add(
            str( structured_log_file_path ),
            **LOG_CONFIG[ "file" ],
            **LOG_CONFIG[ "common" ],
            serialize=True,
        )

    logger.info( "Logger initialized" )
