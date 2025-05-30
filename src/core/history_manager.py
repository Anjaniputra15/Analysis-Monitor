import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import logging
from pathlib import Path

class HistoryManager:
    def __init__(self, history_file: str, max_entries: int = 1000, retention_days: int = 30):
        self.history_file = Path(history_file)
        self.max_entries = max_entries
        self.retention_days = retention_days
        self._cache: Dict[str, List[Dict]] = {}
        self._pending_updates: List[Dict] = []
        self.logger = logging.getLogger(__name__)
        self.load_history()

    def load_history(self) -> None:
        """Load history data from file with validation."""
        try:
            if self.history_file.exists():
                with open(self.history_file, 'r') as f:
                    data = json.load(f)
                    if self._validate_history_data(data):
                        self._cache = data
                    else:
                        self.logger.warning("Invalid history data detected, initializing empty history")
                        self._cache = {}
            else:
                self._cache = {}
        except Exception as e:
            self.logger.error(f"Error loading history: {str(e)}")
            self._cache = {}

    def _validate_history_data(self, data: Dict) -> bool:
        """Validate the structure of history data."""
        if not isinstance(data, dict):
            return False
        
        for service_id, entries in data.items():
            if not isinstance(entries, list):
                return False
            for entry in entries:
                if not all(key in entry for key in ['timestamp', 'status', 'latency']):
                    return False
        return True

    def add_entry(self, service_id: str, entry: Dict) -> None:
        """Add a new history entry with caching."""
        if service_id not in self._cache:
            self._cache[service_id] = []
        
        self._cache[service_id].append(entry)
        self._pending_updates.append((service_id, entry))
        
        # Prune old entries
        self._prune_old_entries(service_id)
        
        # Save if we have enough pending updates
        if len(self._pending_updates) >= 10:
            self.save_history()

    def _prune_old_entries(self, service_id: str) -> None:
        """Remove old entries based on retention policy."""
        cutoff_date = datetime.now() - timedelta(days=self.retention_days)
        cutoff_iso = cutoff_date.isoformat()
        
        # Keep only recent entries and limit to max_entries
        self._cache[service_id] = [
            entry for entry in self._cache[service_id]
            if entry.get('timestamp', '') >= cutoff_iso
        ][-self.max_entries:]

    def get_service_history(self, service_id: str, page: int = 1, page_size: int = 100) -> List[Dict]:
        """Get paginated history for a service."""
        if service_id not in self._cache:
            return []
        
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        return self._cache[service_id][start_idx:end_idx]

    def get_latency_data(self, service_id: str, max_points: int = 100) -> List[float]:
        """Get sampled latency data for graphing."""
        if service_id not in self._cache:
            return []
        
        data = [entry['latency'] for entry in self._cache[service_id] if entry.get('latency') is not None]
        
        if len(data) <= max_points:
            return data
        
        # Sample data points
        step = len(data) // max_points
        return data[::step]

    def save_history(self) -> None:
        """Save history data to file."""
        try:
            # Create backup of existing file
            if self.history_file.exists():
                backup_file = self.history_file.with_suffix('.json.bak')
                self.history_file.rename(backup_file)
            
            # Save new data
            with open(self.history_file, 'w') as f:
                json.dump(self._cache, f, indent=4)
            
            # Clear pending updates
            self._pending_updates = []
            
            # Remove backup if save was successful
            if backup_file.exists():
                backup_file.unlink()
                
        except Exception as e:
            self.logger.error(f"Error saving history: {str(e)}")
            # Restore backup if save failed
            if backup_file.exists():
                backup_file.rename(self.history_file)

    def calculate_uptime_stats(self, service_id: str) -> Dict:
        """Calculate uptime statistics for a service."""
        if service_id not in self._cache:
            return self._empty_stats()
        
        entries = self._cache[service_id]
        if not entries:
            return self._empty_stats()
        
        total_checks = len(entries)
        total_up = sum(1 for entry in entries if entry.get('status') == 'UP')
        total_down = total_checks - total_up
        
        # Calculate uptime percentage
        uptime_percentage = (total_up / total_checks) * 100 if total_checks > 0 else 0
        
        # Calculate consecutive status
        consecutive_up = 0
        consecutive_down = 0
        current_consecutive_up = 0
        current_consecutive_down = 0
        
        for entry in reversed(entries):
            if entry.get('status') == 'UP':
                current_consecutive_up += 1
                current_consecutive_down = 0
            else:
                current_consecutive_down += 1
                current_consecutive_up = 0
            
            consecutive_up = max(consecutive_up, current_consecutive_up)
            consecutive_down = max(consecutive_down, current_consecutive_down)
        
        # Calculate average latency
        latencies = [entry.get('latency', 0) for entry in entries if entry.get('status') == 'UP' and entry.get('latency') is not None]
        average_latency = sum(latencies) / len(latencies) if latencies else 0
        
        return {
            'uptime_percentage': uptime_percentage,
            'consecutive_up': consecutive_up,
            'consecutive_down': consecutive_down,
            'total_checks': total_checks,
            'total_up': total_up,
            'total_down': total_down,
            'average_latency': average_latency
        }

    def _empty_stats(self) -> Dict:
        """Return empty statistics structure."""
        return {
            'uptime_percentage': 0,
            'consecutive_up': 0,
            'consecutive_down': 0,
            'total_checks': 0,
            'total_up': 0,
            'total_down': 0,
            'average_latency': 0
        } 