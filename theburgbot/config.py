import configparser

from typing import Any, Dict

def parse_config_file(file_path: str) -> Dict[str, Dict[str, Any]]:
    config = configparser.ConfigParser()
    if config.read(file_path) != [file_path]:
        raise BaseException(f"Failed to parse {file_path}")
    return {section_name: dict(config.items(section_name)) for section_name in config.sections()}

