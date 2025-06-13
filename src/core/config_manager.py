import json
import os
import logging
from pathlib import Path
from typing import Dict, Any, Optional
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class ConfigFileHandler(FileSystemEventHandler):
    def __init__(self, callback):
        self.callback = callback

    def on_modified(self, event):
        if not event.is_directory and event.src_path.endswith('.json'):
            self.callback()

class ConfigManager:
    def __init__(self, config_file: str):
        self.config_file = Path(config_file)
        self.config: Dict[str, Any] = {}
        self.logger = logging.getLogger(__name__)
        self._observer = None
        self.load_config()

    def load_config(self) -> None:
        """Load configuration from file with validation."""
        try:
            if self.config_file.exists():
                with open(self.config_file, 'r') as f:
                    data = json.load(f)
                    if self._validate_config(data):
                        self.config = data
                    else:
                        self.logger.warning("Invalid config data detected, using defaults")
                        self.config = self._get_default_config()
            else:
                self.config = self._get_default_config()
                self.save_config()
        except Exception as e:
            self.logger.error(f"Error loading config: {str(e)}")
            self.config = self._get_default_config()

    def _validate_config(self, data: Dict) -> bool:
        """Validate the structure of configuration data."""
        required_keys = ['services', 'settings']
        if not all(key in data for key in required_keys):
            return False
        
        # Validate services
        if not isinstance(data['services'], list):
            return False
        
        for service in data['services']:
            if not all(key in service for key in ['name', 'url', 'path']):
                return False
        
        # Validate settings
        if not isinstance(data['settings'], dict):
            return False
        
        return True

    def _get_default_config(self) -> Dict:
        """Get default configuration."""
        return {
            'services': [],
            'settings': {
                'check_interval': 10,
                'timeout': 5.0,
                'max_retries': 3,
                'alert_threshold': 3,
                'history_retention_days': 30,
                'max_history_entries': 1000
            }
        }

    def save_config(self) -> None:
        """Save configuration to file."""
        try:
            backup_file = self.config_file.with_suffix('.json.bak')

            # Create backup of existing file
            if self.config_file.exists():
                self.config_file.rename(backup_file)

            # Save new data
            with open(self.config_file, 'w') as f:
                json.dump(self.config, f, indent=4)

            # Remove backup if save was successful
            if backup_file.exists():
                backup_file.unlink()

        except Exception as e:
            self.logger.error(f"Error saving config: {str(e)}")
            # Restore backup if save failed
            if backup_file.exists():
                backup_file.rename(self.config_file)

    def get_setting(self, key: str, default: Any = None) -> Any:
        """Get a setting value."""
        return self.config.get('settings', {}).get(key, default)

    def update_setting(self, key: str, value: Any) -> None:
        """Update a setting value."""
        if 'settings' not in self.config:
            self.config['settings'] = {}
        self.config['settings'][key] = value
        self.save_config()

    def get_services(self) -> list:
        """Get all services."""
        return self.config.get('services', [])

    def add_service(self, service: Dict) -> None:
        """Add a new service."""
        if 'services' not in self.config:
            self.config['services'] = []
        self.config['services'].append(service)
        self.save_config()

    def remove_service(self, service_id: str) -> None:
        """Remove a service by ID."""
        self.config['services'] = [
            service for service in self.config['services']
            if service.get('id') != service_id
        ]
        self.save_config()

    def update_service(self, service_id: str, updates: Dict) -> None:
        """Update a service's configuration."""
        for service in self.config['services']:
            if service.get('id') == service_id:
                service.update(updates)
                break
        self.save_config()

    def start_watching(self, callback) -> None:
        """Start watching for config file changes."""
        if self._observer is None:
            self._observer = Observer()
            self._observer.schedule(
                ConfigFileHandler(callback),
                str(self.config_file.parent),
                recursive=False
            )
            self._observer.start()

    def stop_watching(self) -> None:
        """Stop watching for config file changes."""
        if self._observer is not None:
            self._observer.stop()
            self._observer.join()
            self._observer = None

    def get_env_config(self) -> Dict:
        """Get configuration from environment variables."""
        return {
            'check_interval': int(os.getenv('ANALYSIS_MONITOR_CHECK_INTERVAL', '10')),
            'timeout': float(os.getenv('ANALYSIS_MONITOR_TIMEOUT', '5.0')),
            'max_retries': int(os.getenv('ANALYSIS_MONITOR_MAX_RETRIES', '3')),
            'alert_threshold': int(os.getenv('ANALYSIS_MONITOR_ALERT_THRESHOLD', '3')),
            'history_retention_days': int(os.getenv('ANALYSIS_MONITOR_HISTORY_RETENTION_DAYS', '30')),
            'max_history_entries': int(os.getenv('ANALYSIS_MONITOR_MAX_HISTORY_ENTRIES', '1000'))
        } 