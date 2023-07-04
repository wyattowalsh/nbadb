"""logger.py - logging utilities
"""
# == Imports ===============================================================
import inspect
import logging
import time
from datetime import datetime
from functools import wraps
from logging.config import fileConfig
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Type

import numpy as np
import pandas as pd


# == Functions =============================================================
def init_logger(logger_type: str = "both") -> logging.Logger:
    """initializes the logger

    multiple types of loggers can be initialized:

    - file
    - console
    - both

    Args:
        logger_type (str, optional): The type of logger to be initialized. Defaults to "both".

    Raises:
        ValueError: Raised if logger_type is not one of: file, console, both

    Returns:
        logging.Logger: The initialized logger
    """
    # check if logger_type is str
    if not isinstance(logger_type, str):
        raise TypeError("logger_type must be a string")
    if logger_type == "file":
        config_file_path = "./utils/logging/logging-file.conf"
    elif logger_type == "console":
        config_file_path = "./utils/logging/logging-console.conf"
    elif logger_type == "both":
        config_file_path = "./utils/logging/logging-console-and-file.conf"
    else:
        raise ValueError("logger_type must be one of: file, console, both")
    fileConfig(config_file_path)
    logger = logging.getLogger("nba_db_logger")
    logger.info("Starting bot_logger logging...")
    return logger


def log(
    logger: logging.Logger,
    critical_exceptions: Sequence[Type[Exception]] = (),
    max_result_length: int = 1000,
    log_level_start: int = logging.INFO,
    log_level_end: int = logging.INFO,
    log_level_error: int = logging.ERROR,
    rethrow_exceptions: bool = True,
    preview_count: int = 3,  # Number of items from start and end of a formatted element
) -> Callable:
    """
    Decorator for logging function calls, exceptions, and results.
    Args:
        critical_exceptions (Sequence[Type[Exception]], optional): Exceptions to treat as critical. Defaults to ().
        max_result_length (int, optional): The maximum length of the result to log. Defaults to 1000.
        log_level_start (int, optional): The logging level for the start of the function. Defaults to logging.INFO.
        log_level_end (int, optional): The logging level for the end of the function. Defaults to logging.INFO.
        log_level_error (int, optional): The logging level for exceptions. Defaults to logging.ERROR.
        rethrow_exceptions (bool, optional): Whether to rethrow exceptions or swallow them. Defaults to True.
        preview_count (int, optional): Number of items from start and end of a formatted element. Defaults to 3.
    Returns:
        Callable[..., Any]: The wrapped function.
    """

    def decorator(func: Callable) -> Callable:
        # Get the function's signature for later use in binding arguments
        sig = inspect.signature(func)

        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Bind the passed arguments to their names in the function signature
            bound_args = sig.bind(*args, **kwargs)
            bound_args.apply_defaults()

            # Log the start of the function with the given log level
            logger.log(
                log_level_start,
                format_log(
                    func.__module__,
                    func.__qualname__,
                    "start",
                    bound_args.arguments,
                    max_result_length=max_result_length,
                    preview_count=preview_count,
                ),
            )

            # Record the start time of the function for calculating execution time later
            start_time = time.perf_counter()

            result = None

            try:
                result = func(*args, **kwargs)
            except Exception as exc:
                # Determine the log level based on the exception type
                log_level = get_log_level(exc, critical_exceptions, log_level_error)
                # Handle the exception by logging an error message and traceback
                handle_exception(
                    exc,
                    func.__module__,
                    func.__qualname__,
                    log_level,
                    bound_args.arguments,
                    max_result_length=max_result_length,
                    preview_count=preview_count,
                )
                # If rethrow_exceptions is True, rethrow the exception
                if rethrow_exceptions:
                    raise
            finally:
                # Record the end time of the function and calculate the execution time
                end_time = time.perf_counter()
                execution_time = end_time - start_time

                # Log the end of the function with the given log level
                logger.log(
                    log_level_end,
                    format_log(
                        func.__module__,
                        func.__qualname__,
                        "end",
                        bound_args.arguments,
                        result,
                        execution_time,
                        max_result_length=max_result_length,
                        preview_count=preview_count,
                    ),
                )

            return result

        return wrapper

    return decorator


def handle_exception(
    exc: Exception,
    func_module: str,
    func_name: str,
    log_level: int,
    args: Optional[Dict[str, Any]] = None,
    max_result_length: int = 1000,
    preview_count: int = 3,
) -> None:
    """
    Handle exceptions by logging an error message and traceback.
    Args:
        exc (Exception): The Exception instance.
        func_module (str): The module of the function where the exception occurred.
        func_name (str): The name of the function where the exception occurred.
        log_level (int): The logging level for the error.
        args (Optional[Dict[str, Any]], optional): Arguments passed to the function. Defaults to None.
        max_result_length (int, optional): Maximum length of result to log. Defaults to 1000.
        preview_count (int, optional): Number of items from start and end of a formatted element. Defaults to 3.
    Returns:
        None
    """
    logger = logging.getLogger(func_module)
    error_msg = format_log(
        func_module,
        func_name,
        "error",
        args,
        exc,
        max_result_length,
        preview_count,
    )
    logger.log(log_level, error_msg, exc_info=True)


def get_log_level(
    exc: Exception,
    critical_exceptions: Sequence[Type[Exception]],
    default_log_level: int = logging.ERROR,
) -> int:
    """
    Determine the log level based on the exception type.
    Args:
        exc (Exception): The Exception instance.
        critical_exceptions (Sequence[Type[Exception]]): Exceptions to treat as critical.
        default_log_level (int, optional): The default logging level if no match is found. Defaults to logging.ERROR.
    Returns:
        int: The logging level for the exception.
    """
    if type(exc) in critical_exceptions:
        return logging.CRITICAL
    return default_log_level


def format_log(
    func_module: str,
    func_name: str,
    status: str,
    args: Optional[Dict[str, Any]] = None,
    result: Optional[Any] = None,
    exec_time: Optional[float] = None,
    max_result_length: int = 1000,
    preview_count: int = 3,
) -> str:
    """
    Format the log message based on the status of the function call.
    Args:
        func_module (str): The module of the function.
        func_name (str): The name of the function.
        status (str): The status of the function call ('start', 'end', or 'error').
        args (Optional[Dict[str, Any]], optional): Dictionary mapping argument names to their values. Defaults to None.
        result (Optional[Any], optional): Result of the function call. Defaults to None.
        exec_time (Optional[float], optional): Execution time of the function call. Defaults to None.
        max_result_length (int, optional): Maximum length of result to log. Defaults to 1000.
        preview_count (int, optional): Number of items from start and end of a formatted element. Defaults to 3.
    Returns:
        str: Formatted log message.
    """
    log_formats = {
        "start": f"Starting {func_module}.{func_name} with parameters:\n{format_args(args, preview_count=preview_count)}",
        "end": (
            f"Finished {func_module}.{func_name}:\n"
            f"  Execution time: {exec_time:.2f} seconds\n"
            f"  Result:\n{format_result(result, max_result_length=max_result_length, preview_count=preview_count)}"
            if exec_time is not None
            else f"Finished {func_module}.{func_name}:\n"
            f"  Result:\n{format_result(result, max_result_length=max_result_length, preview_count=preview_count)}"
        ),
        "error": (
            f"Failed {func_module}.{func_name}:\n"
            f"  Parameters:\n{format_args(args, preview_count=preview_count)}"
            f"\n  Error: {format_value(result, preview_count=preview_count)}"
        ),
    }

    return log_formats.get(status, f"Invalid log status: {status}")


def format_result(
    result: Any, max_result_length: int = 1000, preview_count: int = 3
) -> str:
    """
    Format the result for logging.
    Args:
        result (Any): The result of the function call.
        max_result_length (int, optional): The maximum length of the result to log. Defaults to 1000.
        preview_count (int, optional): Number of items from start and end of a formatted element. Defaults to 3.
    Returns:
        str: Formatted result.
    """
    if result is None:
        return "None"
    elif isinstance(result, pd.DataFrame):
        return format_dataframe(
            result, max_result_length=max_result_length, preview_count=preview_count
        )
    elif isinstance(result, pd.Series):
        return format_series(result, preview_count=preview_count)
    elif isinstance(result, list):
        return format_list(result, preview_count=preview_count)
    elif isinstance(result, dict):
        return format_dict(result, preview_count=preview_count)
    elif isinstance(result, tuple):
        return format_tuple(
            result, max_result_length=max_result_length, preview_count=preview_count
        )
    elif isinstance(result, np.ndarray):
        return format_array(
            result, max_result_length=max_result_length, preview_count=preview_count
        )
    elif isinstance(result, datetime):
        return format_datetime(result)
    else:
        result_repr = repr(result)
        if len(result_repr) > max_result_length:
            result_repr = result_repr[:max_result_length] + "..."
        return result_repr


def format_args(args: Dict[str, Any], preview_count: int = 3) -> str:
    """
    Format the arguments for logging.
    Args:
        args (Dict[str, Any]): Dictionary mapping argument names to their values.
        preview_count (int, optional): Number of items from start and end of a formatted element. Defaults to 3.
    Returns:
        str: Formatted arguments.
    """
    if args is None:
        return ""

    formatted_args = []
    for key, value in args.items():
        formatted_value = format_value(value, preview_count=preview_count)
        formatted_args.append(f"    {key} = {formatted_value}")

    return "\n".join(formatted_args)


def format_value(value: Any, preview_count: int = 3) -> str:
    """
    Format a value for logging.
    Args:
        value (Any): The value to format.
        preview_count (int, optional): Number of items from start and end of a formatted element. Defaults to 3.
    Returns:
        str: Formatted value.
    """
    if isinstance(value, (pd.DataFrame, pd.Series, list, dict, tuple, np.ndarray)):
        return format_result(value, preview_count=preview_count)
    elif isinstance(value, datetime):
        return format_datetime(value)
    elif isinstance(value, Exception):
        return format_exception(value)
    else:
        return repr(value)


def format_dataframe(
    dataframe: pd.DataFrame, max_result_length: int = 1000, preview_count: int = 3
) -> str:
    """
    Format a pandas DataFrame for logging.
    Args:
        dataframe (pd.DataFrame): The DataFrame to format.
        max_result_length (int, optional): Maximum length of result to log. Defaults to 1000.
        preview_count (int, optional): Number of items from start and end of a formatted element. Defaults to 3.
    Returns:
        str: Formatted DataFrame.
    """
    n_rows, n_cols = dataframe.shape
    if n_rows <= 2 * preview_count:
        return dataframe.to_string(index=False)
    else:
        preview_start = dataframe.head(preview_count).to_string(index=False)
        preview_end = dataframe.tail(preview_count).to_string(index=False)
        return f"{preview_start}\n...\n{preview_end}"


def format_series(series: pd.Series, preview_count: int = 3) -> str:
    """
    Format a pandas Series for logging.
    Args:
        series (pd.Series): The Series to format.
        preview_count (int, optional): Number of items from start and end of a formatted element. Defaults to 3.
    Returns:
        str: Formatted Series.
    """
    values = series.tolist()
    if len(values) <= 2 * preview_count:
        formatted_values = [repr(value) for value in values]
    else:
        preview_values = values[:preview_count] + values[-preview_count:]
        formatted_values = [repr(value) for value in preview_values]
        formatted_values.insert(preview_count, "...")
    return f"Series with shape {series.shape} and values:\n    {', '.join(formatted_values)}"


def format_nested(
    data: Any, max_result_length: int = 1000, preview_count: int = 3, indent: int = 0
) -> str:
    """
    Format a nested data structure for logging.
    Args:
        data (Any): The nested data structure to format.
        max_result_length (int, optional): Maximum length of result to log. Defaults to 1000.
        preview_count (int, optional): Number of items from start and end of a formatted element. Defaults to 3.
        indent (int, optional): Indentation level. Defaults to 0.
    Returns:
        str: Formatted data.
    """
    if isinstance(data, list):
        if len(data) <= 2 * preview_count:
            return format_list(data, preview_count=preview_count, indent=indent)
        else:
            preview_data = data[:preview_count] + ["..."] + data[-preview_count:]
            return format_list(preview_data, preview_count=preview_count, indent=indent)
    elif isinstance(data, dict):
        if len(data) <= 2 * preview_count:
            return format_dict(data, preview_count=preview_count, indent=indent)
        else:
            preview_keys = (
                list(data.keys())[:preview_count]
                + ["..."]
                + list(data.keys())[-preview_count:]
            )
            preview_data = {
                key: data[key] if key in data.keys() else "..."
                for key in preview_keys
                for key in preview_keys
            }
            return format_dict(preview_data, preview_count=preview_count, indent=indent)
    else:
        return repr(data)


def format_datetime(dt: datetime) -> str:
    """
    Format a datetime object for logging.
    Args:
        dt (datetime): The datetime object to format.
    Returns:
        str: Formatted datetime.
    """
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def format_exception(exc: Exception) -> str:
    """
    Format an exception object for logging.
    Args:
        exc (Exception): The exception object to format.
    Returns:
        str: Formatted exception.
    """
    return f"{type(exc).__name__}: {str(exc)}"


def format_list(data: List[Any], preview_count: int = 3, indent: int = 0) -> str:
    """
    Format a list for logging.
    Args:
        data (List[Any]): The list to format.
        preview_count (int, optional): Number of items from start and end of a formatted element. Defaults to 3.
        indent (int, optional): Indentation level. Defaults to 0.
    Returns:
        str: Formatted list.
    """
    indent_str = " " * 4 * indent
    if len(data) <= 2 * preview_count:
        formatted_items = [
            format_nested(item, preview_count=preview_count, indent=indent + 1)
            for item in data
        ]
    else:
        preview_items = data[:preview_count] + ["..."] + data[-preview_count:]
        formatted_items = [
            format_nested(item, preview_count=preview_count, indent=indent + 1)
            for item in preview_items
        ]
    return f"[{', '.join(formatted_items)}]"


def format_dict(data: Dict[Any, Any], preview_count: int = 3, indent: int = 0) -> str:
    """
    Format a dictionary for logging.
    Args:
        data (Dict[Any, Any]): The dictionary to format.
        preview_count (int, optional): Number of items from start and end of a formatted element. Defaults to 3.
        indent (int, optional): Indentation level. Defaults to 0.
    Returns:
        str: Formatted dictionary.
    """
    indent_str = " " * 4 * indent
    if len(data) <= 2 * preview_count:
        formatted_items = [
            f"{format_nested(key, preview_count=preview_count, indent=indent + 1)}: {format_nested(value, preview_count=preview_count, indent=indent + 1)}"
            for key, value in data.items()
        ]
    else:
        preview_keys = (
            list(data.keys())[:preview_count]
            + ["..."]
            + list(data.keys())[-preview_count:]
        )
        preview_items = {key: data[key] for key in preview_keys}
        formatted_items = [
            f"{format_nested(key, preview_count=preview_count, indent=indent + 1)}: {format_nested(value, preview_count=preview_count, indent=indent + 1)}"
            for key, value in preview_items.items()
        ]
    return f"{{{', '.join(formatted_items)}}}"


def format_tuple(
    tpl: Tuple[Any, ...], max_result_length: int = 1000, preview_count: int = 3
) -> str:
    """
    Format a tuple for logging.
    Args:
        tpl (Tuple[Any, ...]): The tuple to format.
        max_result_length (int, optional): Maximum length of result to log. Defaults to 1000.
        preview_count (int, optional): Number of items from start and end of a formatted element. Defaults to 3.
    Returns:
        str: Formatted tuple.
    """
    if len(tpl) <= 2 * preview_count:
        formatted_values = [
            format_nested(value, preview_count=preview_count) for value in tpl
        ]
    else:
        preview_values = tpl[:preview_count] + ("...",) + tpl[-preview_count:]
        formatted_values = [
            format_nested(value, preview_count=preview_count)
            for value in preview_values
        ]
    return f"Tuple with {len(tpl)} elements: ({', '.join(formatted_values)})"


def format_array(
    arr: np.ndarray, max_result_length: int = 1000, preview_count: int = 3
) -> str:
    """
    Format a NumPy array for logging.
    Args:
        arr (np.ndarray): The NumPy array to format.
        max_result_length (int, optional): Maximum length of result to log. Defaults to 1000.
        preview_count (int, optional): Number of items from start and end of a formatted element. Defaults to 3.
    Returns:
        str: Formatted array.
    """
    if arr.size <= 2 * preview_count:
        formatted_values = [
            format_nested(value, preview_count=preview_count) for value in arr.flatten()
        ]
    else:
        preview_values = np.concatenate(
            [arr[:preview_count], ["..."], arr[-preview_count:]]
        )
        formatted_values = [
            format_nested(value, preview_count=preview_count)
            for value in preview_values
        ]
    shape_str = " x ".join(str(dim) for dim in arr.shape)
    return f"NumPy array with shape {shape_str} and dtype {arr.dtype}: [{', '.join(formatted_values)}]"
