import json
import logging
import os
import yaml
from typing import Dict, Any
import sys
import tomllib

logger = logging.getLogger(__name__)

class ConfigHandler:
    """Handler for loading and parsing configuration files"""
    
    @staticmethod
    def load_config(config_path: str) -> Dict[str, Any]:
        """
        Load configuration from a file. Supports JSON, YAML, and TOML formats.
        
        Args:
            config_path: Path to the configuration file
            
        Returns:
            Dictionary with configuration
            
        Raises:
            FileNotFoundError: If the file does not exist
            ValueError: If the file format is not supported
        """
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"Configuration file not found: {config_path}")
        
        file_extension = os.path.splitext(config_path)[1].lower()
        
        try:
            if file_extension == '.json':
                logger.info(f"Loading JSON configuration from {config_path}")
                with open(config_path, 'r') as f:
                    return json.load(f)
                
            elif file_extension in ['.yaml', '.yml']:
                logger.info(f"Loading YAML configuration from {config_path}")
                with open(config_path, 'r') as f:
                    return yaml.safe_load(f)

            elif file_extension == '.toml':
                logger.info(f"Loading TOML configuration from {config_path}")
                with open(config_path, 'rb' if sys.version_info >= (3, 11) else 'r') as f:
                    return tomllib.load(f) if sys.version_info >= (3, 11) else tomllib.load(f)
                
            else:
                supported_formats = ['.json', '.yaml', '.yml', '.toml']
                raise ValueError(f"Unsupported file format: {file_extension}. Supported formats: {', '.join(supported_formats)}")
        
        except (json.JSONDecodeError, yaml.YAMLError, tomllib.TOMLDecodeError) as e:
            logger.error(f"Error parsing configuration file {config_path}: {str(e)}")
            raise ValueError(f"Error parsing configuration file: {str(e)}")
    
    @staticmethod
    def get_exchange_config(config: Dict[str, Any]) -> Dict[str, Any]:
        return config.get("exchange", {})
    
    @staticmethod
    def get_data_source_config(config: Dict[str, Any]) -> Dict[str, Any]:
        return config.get("data_source", {})
    
    @staticmethod
    def get_server_config(config: Dict[str, Any]) -> Dict[str, Any]:
        return config.get("server", {})
    
    @staticmethod
    def get_simulation_config(config: Dict[str, Any]) -> Dict[str, Any]:
        return config.get("simulation", {})
