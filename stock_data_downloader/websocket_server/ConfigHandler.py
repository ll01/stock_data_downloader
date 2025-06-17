import json
import logging
import os
import yaml
from typing import Dict, Any, Union, cast
import sys
try:
    import tomllib  # Python 3.11+
except ImportError:
    try:
        import tomli as tomllib  # Fallback for older Python versions
    except ImportError:
        tomllib = None
import re

logger = logging.getLogger(__name__)

class ConfigHandler:
    """Handler for loading and parsing configuration files"""
   
    @staticmethod
    def load_config(config_path: str, resolve_env_vars: bool = True) -> Dict[str, Any]:
        """
        Load configuration from a file. Supports JSON, YAML, and TOML formats.
       
        Args:
            config_path: Path to the configuration file
            resolve_env_vars: Whether to resolve environment variables in the config
           
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
                    config = json.load(f)
               
            elif file_extension in ['.yaml', '.yml']:
                logger.info(f"Loading YAML configuration from {config_path}")
                with open(config_path, 'r') as f:
                    config = yaml.safe_load(f)
                    
            elif file_extension == '.toml':
                if tomllib is None:
                    raise ValueError("TOML support not available. Install 'tomli' package for Python < 3.11")
                logger.info(f"Loading TOML configuration from {config_path}")
                with open(config_path, 'rb') as f:
                    config = tomllib.load(f)
               
            else:
                supported_formats = ['.json', '.yaml', '.yml', '.toml']
                raise ValueError(f"Unsupported file format: {file_extension}. Supported formats: {', '.join(supported_formats)}")
       
            # Resolve environment variables if requested
            if resolve_env_vars:
                resolved_config = ConfigHandler._resolve_env_vars(config)
                # Ensure we return a Dict[str, Any] - config files should always be dictionaries at root level
                if not isinstance(resolved_config, dict):
                    raise ValueError(f"Configuration file must contain a dictionary at root level, got {type(resolved_config)}")
                config = cast(Dict[str, Any], resolved_config)
                
            return config
       
        except (json.JSONDecodeError, yaml.YAMLError) as e:
            logger.error(f"Error parsing configuration file {config_path}: {str(e)}")
            raise ValueError(f"Error parsing configuration file: {str(e)}")
        except Exception as e:
            if 'tomllib' in str(type(e).__module__) or 'TOML' in str(e):
                logger.error(f"Error parsing TOML configuration file {config_path}: {str(e)}")
                raise ValueError(f"Error parsing TOML configuration file: {str(e)}")
            else:
                raise
   
    @staticmethod
    def _resolve_env_vars(obj: Any) -> Any:
        """
        Recursively resolve environment variables in configuration objects.
        Supports ${VAR_NAME} and ${VAR_NAME:-default_value} syntax.
        """
        if isinstance(obj, dict):
            return {key: ConfigHandler._resolve_env_vars(value) for key, value in obj.items()}
        elif isinstance(obj, list):
            return [ConfigHandler._resolve_env_vars(item) for item in obj]
        elif isinstance(obj, str):
            return ConfigHandler._substitute_env_vars(obj)
        else:
            return obj
    
    @staticmethod
    def _substitute_env_vars(text: str) -> str:
        """
        Substitute environment variables in a string.
        Supports ${VAR_NAME} and ${VAR_NAME:-default_value} syntax.
        """
        def replace_var(match):
            var_expr = match.group(1)
            if ':-' in var_expr:
                var_name, default_value = var_expr.split(':-', 1)
                return os.getenv(var_name.strip(), default_value.strip())
            else:
                var_name = var_expr.strip()
                env_value = os.getenv(var_name)
                if env_value is None:
                    logger.warning(f"Environment variable '{var_name}' not found, keeping original placeholder")
                    return match.group(0)  # Return original ${VAR_NAME} if not found
                return env_value
        
        # Pattern to match ${VAR_NAME} or ${VAR_NAME:-default}
        pattern = r'\$\{([^}]+)\}'
        return re.sub(pattern, replace_var, text)
   
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