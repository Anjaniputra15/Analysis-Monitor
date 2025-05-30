import httpx
import json
import os
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from textual import on, work
from textual.app import App, ComposeResult
from textual.reactive import reactive
from textual.widgets import Header, Footer, DataTable, Static, Input, Button, Label, LoadingIndicator
from textual.containers import Vertical, Horizontal, ScrollableContainer
from textual.screen import ModalScreen
from textual.notifications import Notification
from textual.message import Message
from textual.message_pump import MessagePump
from textual.timer import Timer
from textual_plotext import PlotextPlot
from typing import List, Dict, Any, Optional
from plyer import notification as system_notification


# Constants
DEFAULT_HOST = "localhost"
DEFAULT_INTERVAL = 10  # seconds
CONFIG_FILE = "analysis_config.json"
DOWN_ALERT_THRESHOLD = 3  # Number of consecutive failed checks before alerting
HISTORY_LOG_FILE = "analysis_history.json"  # New history log file 
MAX_HISTORY_ENTRIES = 1000  # Maximum number of entries per service
HISTORY_RETENTION_DAYS = 30  # How many days of history to keep
DISCORD_WEBHOOK_URL = os.getenv('DISCORD_WEBHOOK_URL')


class AnalysisMonitorJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


class UpdateServiceMessage(Message):
    """Message to update a service from a worker thread"""
    def __init__(self, service):
        self.service = service
        super().__init__()


class ServiceStatusChangeMessage(Message):
    """Message to notify about service status change"""
    def __init__(self, service_name: str, new_status: str, old_status: str):
        self.service_name = service_name
        self.new_status = new_status
        self.old_status = old_status
        super().__init__()


# Modal for adding a new service
class AddServiceModal(ModalScreen):
    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("Add New Service"),
            Input(placeholder="Service Name", id="name-input"),
            Input(value=DEFAULT_HOST, placeholder="Host", id="host-input"),
            Input(placeholder="Port", id="port-input"),
            Input(placeholder="Path (optional)", id="path-input"),
            Input(value=str(DEFAULT_INTERVAL), placeholder="Check Interval (seconds)", id="interval-input"),
            Horizontal(
                Button("Cancel", variant="error", id="cancel"),
                Button("Add", variant="success", id="add"),
            ),
            id="add-service-modal",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        try:
            if event.button.id == "add":
                name = self.query_one("#name-input", Input).value.strip()
                host = self.query_one("#host-input", Input).value.strip()
                port = self.query_one("#port-input", Input).value.strip()
                path = self.query_one("#path-input", Input).value.strip() or "/"
                interval_str = self.query_one("#interval-input", Input).value.strip() or str(DEFAULT_INTERVAL)
                
                try:
                    interval = int(interval_str)
                except ValueError:
                    self.app.notify("Interval must be a number", severity="error")
                    return
                
                if name and host and port:
                    self.dismiss({
                        "id": str(uuid.uuid4()),
                        "name": name,
                        "url": f"http://{host}:{port}",
                        "path": path,
                        "check_interval": interval,
                        "last_check": {},
                        "status": "PENDING",
                        "consecutive_down": 0,
                        "alerted": False
                    })
                else:
                    self.app.notify("All fields are required", severity="error")
            elif event.button.id == "cancel":
                # Just dismiss with None to indicate cancellation
                self.dismiss(None)
        except Exception as e:
            # Handle errors in the modal
            print(f"[DEBUG] Error in modal button press: {e}")
            import traceback
            traceback.print_exc()
            self.app.notify(f"Error processing input: {str(e)}", severity="error")
            # Ensure we dismiss the modal even on error
            self.dismiss(None)

class DeleteConfirmationModal(ModalScreen):
    """Modal for confirming service deletion"""
    
    def __init__(self, service_name, service_id):
        self.service_name = service_name
        self.service_id = service_id
        super().__init__()
    
    def compose(self) -> ComposeResult:
        yield Vertical(
            Label(f"Delete Service: {self.service_name}"),
            Label("Are you sure you want to delete this service?"),
            Horizontal(
                Button("Cancel", variant="primary", id="cancel"),
                Button("Delete", variant="error", id="confirm"),
            ),
            id="delete-confirmation-modal",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm":
            self.dismiss(True)  # Confirm deletion
        else:
            self.dismiss(False)  # Cancel deletion
            
# Main Analysis-Monitor application
class AnalysisMonitorDashboard(App):
    CSS = '''
    DataTable {
        width: 100%;
        height: 60%;
        border: solid #4CAF50;
        background: #1a1a1a;
        color: #ffffff;
    }
    DataTable > .header {
        background: #2d2d2d;
        color: #4CAF50;
    }
    DataTable > .row {
        background: #1a1a1a;
    }
    DataTable > .row.alternate {
        background: #2d2d2d;
    }
    DataTable > .row:hover {
        background: #4CAF50;
    }
    DataTable > .row.selected {
        background: #1a1a1a;
    }
    DataTable {
        padding: 1 2;
    }

    #main-container {
        width: 100%;
        height: 100%;
    }

    #services-container {
        width: 65%;
        height: 100%;
    }

    #info-panel {
        width: 35%;
        height: 100%;
        background: #2d2d2d;
        color: #ffffff;
        border-left: solid #4CAF50;
        padding: 1;
        overflow: auto;
    }

    #config-display, #service-details {
        margin: 0 1;
        padding: 1;
        background: #1a1a1a;
        border: solid #2d2d2d;
        height: auto;
    }

    #service-section {
        margin: 1 0;
        padding: 1;
    }

    .info-title {
        background: #4CAF50;
        color: #fff;
        padding: 1 2;
        text-align: center;
        margin-bottom: 1;
    }

    #status-bar {
        background: #2d2d2d;
        color: #4CAF50;
        padding: 1 2;
        border-top: solid #2d2d2d;
    }

    #add-service-modal {
        background: #2d2d2d;
        color: #ffffff;
        border: solid #4CAF50;
        padding: 2 4;
    }

    Button {
        background: #4CAF50;
        color: #fff;
        border: solid #4CAF50;
        padding: 1 3;
        margin: 1 1;
    }
    Button.-error {
        background: #f44336;
    }
    Button.-success {
        background: #4CAF50;
    }

    .service-property {
        margin: 1 0;
        color: #4CAF50;
    }
    
    .property-value {
        color: #ffffff;
    }
    
    .service-up {
        color: #4CAF50;
    }
    
    .service-down {
        color: #f44336;
    }
    
    .service-pending {
        color: #9e9e9e;
    }
    
    #delete-confirmation-modal {
        background: #2d2d2d;
        color: #ffffff;
        border: solid #f44336;
        padding: 2 4;
        align: center middle;
        width: 60;
        height: 20;
    }

    #delete-confirmation-modal Label {
        text-align: center;
        margin-bottom: 1;
    }

    #delete-confirmation-modal Button {
        min-width: 16;
    }
    '''
    
    BINDINGS = [
        ("a", "add_service", "Add Service"),
        ("d", "delete_service", "Delete Service"),
        ("r", "refresh", "Refresh"),
        ("q", "quit", "Quit")
    ]

    # Reactive state for monitored applications
    services = reactive([])
    current_service = reactive(None)
    status = reactive("Ready")
    
    row_keys = {}  # Maps service ID to row key
    name_to_id = {}  # Maps service name to service ID
    column_keys = {}
    
    # Queue for pending updates when modal is active
    pending_updates = []
    is_modal_active = False
    
    # Settings
    down_alert_threshold = DOWN_ALERT_THRESHOLD

    def compose(self) -> ComposeResult:
        yield Header()
        # Create a horizontal layout with table on left and info panel on right
        yield Horizontal(
            Vertical(
                DataTable(id="services-table"),
                PlotextPlot(),
                id="services-container"
            ),
            Vertical(
                Vertical(
                    Label("Application Configuration", classes="info-title"),
                    ScrollableContainer(Static(id="config-display", markup=False), id="config-display-scroll", can_maximize=None),
                    id="config-section"
                ),
                Vertical(
                    Label("Service Details", classes="info-title"),
                    ScrollableContainer(Static(id="service-details"), id="service-details-scroll", can_maximize=None),
                    id="service-section"
                ),
                id="info-panel"
            ),
            id="main-container"
        )
        yield Footer()

    def on_mount(self) -> None:

        # Initialize the graph
        self.graph = self.query_one(PlotextPlot).plt
        self.graph.title("Service Latency Over Time")
        # Set default empty graph
        self.graph.clear_data()
        self.graph.xlabel("Time")
        self.graph.ylabel("Latency (ms)")
        
        # Initialize the table
        table = self.query_one("#services-table", DataTable)
        column_keys = table.add_columns("Status", "Name", "URL", "Path", "Current Status", "Ping", "Last Check")
        self.column_keys = {
            "Status": column_keys[0],
            "Name": column_keys[1],
            "URL": column_keys[2],
            "Path": column_keys[3],
            "Current Status": column_keys[4],
            "Ping": column_keys[5],
            "Last Check": column_keys[6],
        }

        # Initialize services and pending updates lists
        self.services = []
        self.pending_updates = []
        self.row_keys = {}
        self.name_to_id = {}
        self.is_modal_active = False
        self.current_service = None
        self.down_alert_threshold = DOWN_ALERT_THRESHOLD

        # Load services from config file if it exists
        self.load_services_from_config()

        # Check if we have services and show appropriate message
        if not self.services:
            self.update_status("No services available. Press 'a' to add a new service.")
            self.show_notification("No services being monitored. Add a service to begin monitoring.", severity="information")
        else:
            # Initialize the dashboard
            self.update_status(f"Monitoring {len(self.services)} services")

        self.set_interval(DEFAULT_INTERVAL, self.check_services)

        # Trigger an initial check of services if we have any
        if self.services:
            self.call_later(self.check_services)

        # Add periodic refresh timer
        self.set_interval(30, self.refresh_services_table)  # Refresh every 30 seconds

        # Update the info panel with initial config
        self.update_config_display()

    def check_health(self):
        """Periodic check to ensure the application is still responsive"""
        try:
            # Basic health check - just update the status to show we're alive
            self.update_status(self.status)
        except Exception as e:
            print(f"[DEBUG] Health check failed: {e}")
            # Application might be in a bad state, try to recover
            self.refresh_services_table()

    def load_services_from_config(self):
        """Load services from analysis_config.json if it exists."""
        config_file = Path(CONFIG_FILE)
        if config_file.exists():
            try:
                with open(config_file, "r") as f:
                    services_data = json.load(f)
                    
                    # Process the loaded services to restore datetime objects
                    self.services = []  # Clear existing services
                    for service in services_data:
                        # Ensure each service has an ID (for backward compatibility)
                        if "id" not in service:
                            service["id"] = str(uuid.uuid4())
                            
                        # Only keep last_check, status, consecutive_down, alerted, etc.
                        service.setdefault("last_check", {})
                        service.setdefault("status", "PENDING")
                        service.setdefault("consecutive_down", 0)
                        service.setdefault("alerted", False)
                        self.services.append(service)
                        try:
                            table = self.query_one("#services-table", DataTable)
                            last_check = service.get("last_check", {})
                            last_status = last_check.get("status", service.get("status", "PENDING"))
                            last_ping = last_check.get("latency", "N/A")
                            last_time = last_check.get("timestamp", "N/A")
                            row_key = table.add_row(
                                self.get_status_circle(last_status),
                                service["name"],
                                service["url"],
                                service["path"],
                                last_status,
                                f"{int(last_ping*1000)} ms" if last_ping not in (None, "N/A") else "N/A",
                                last_time
                            )
                            self.row_keys[service["id"]] = row_key
                            self.name_to_id[service["name"]] = service["id"]
                            
                        except Exception:
                            self.pending_updates.append({"action": "add_row", "service": service})
                    # Select the first service by default
                    if self.services and not self.current_service:
                        self.current_service = self.services[0]
                        self.update_service_details(self.current_service)
                    self.update_status(f"Loaded {len(self.services)} services from config")
            except Exception as e:
                self.update_status(f"Failed to load config: {str(e)}")
        else:
            # Create an empty config file if it doesn't exist
            self.save_services_to_config()

    def save_services_to_config(self):
        """Save services to analysis_config.json."""
        try:
            # Create a deep copy to avoid modifying the original data
            services_to_save = []
            for service in self.services:
                # Create a copy of the service to avoid modifying the original
                service_copy = service.copy()
                services_to_save.append(service_copy)
            
            # Always write to config, even if services list is empty
            # This ensures the config reflects when all services are deleted
            with open(CONFIG_FILE, "w") as f:
                json.dump(services_to_save, f, indent=4, cls=AnalysisMonitorJSONEncoder)
                
            if services_to_save:
                self.update_status(f"Configuration saved with {len(services_to_save)} services")
            else:
                self.update_status("Configuration saved - no services")
                
            print(f"[DEBUG] Saved {len(services_to_save)} services to config")
            
            # Update the config display
            self.update_config_display()
            
        except Exception as e:
            self.update_status(f"Failed to save config: {str(e)}")
            print(f"[DEBUG] Failed to save config: {e}")

    def load_history_from_file(self):
        """Load service history from the history log file."""
        history_file = Path(HISTORY_LOG_FILE)
        if history_file.exists():
            try:
                with open(history_file, "r") as f:
                    history_data = json.load(f)
                    print(f"[DEBUG] Loaded history data for {len(history_data)} services")
                    return history_data
            except Exception as e:
                print(f"[DEBUG] Error loading history file: {e}")
        return {}  # Return empty dict if file doesn't exist or is invalid

    def save_history_to_file(self, history_data):
        """Save service history to the history log file."""
        try:
            with open(HISTORY_LOG_FILE, "w") as f:
                json.dump(history_data, f, indent=4, cls=AnalysisMonitorJSONEncoder)
            print(f"[DEBUG] Saved history data for {len(history_data)} services")
        except Exception as e:
            print(f"[DEBUG] Error saving history file: {e}")

    def prune_history(self, history_data):
        """Remove old history entries to keep file size manageable."""
        pruned_data = {}
        cutoff_date = datetime.now() - timedelta(days=HISTORY_RETENTION_DAYS)
        cutoff_iso = cutoff_date.isoformat()

        for service_id, entries in history_data.items():
            # Keep entries newer than the cutoff date and limit to MAX_HISTORY_ENTRIES
            recent_entries = [entry for entry in entries if entry.get("timestamp", "") >= cutoff_iso]
            pruned_data[service_id] = recent_entries[-MAX_HISTORY_ENTRIES:] if len(recent_entries) > MAX_HISTORY_ENTRIES else recent_entries

        return pruned_data
    
    def calculate_uptime_stats(self, service_id, history_entries):
        """Calculate uptime statistics for a service."""
        if not history_entries:
            return {
                "uptime_percentage": 0,
                "consecutive_up": 0,
                "consecutive_down": 0,
                "total_checks": 0,
                "total_up": 0,
                "total_down": 0,
                "average_latency": 0,
                "last_24h_uptime": 0,
                "last_24h_checks": 0
            }

        # Initialize counters
        total_checks = len(history_entries)
        total_up = sum(1 for entry in history_entries if entry.get("status") == "UP")
        total_down = total_checks - total_up

        # Calculate uptime percentage
        uptime_percentage = (total_up / total_checks) * 100 if total_checks > 0 else 0

        # Calculate consecutive status
        consecutive_up = 0
        consecutive_down = 0
        current_consecutive_up = 0
        current_consecutive_down = 0

        # Reverse to get most recent first
        for entry in reversed(history_entries):
            if entry.get("status") == "UP":
                current_consecutive_up += 1
                current_consecutive_down = 0
            else:
                current_consecutive_down += 1
                current_consecutive_up = 0

            # Track max consecutive statuses
            consecutive_up = max(consecutive_up, current_consecutive_up)
            consecutive_down = max(consecutive_down, current_consecutive_down)

        # Calculate average latency for UP entries
        latencies = [entry.get("latency", 0) for entry in history_entries if entry.get("status") == "UP" and entry.get("latency") is not None]
        average_latency = sum(latencies) / len(latencies) if latencies else 0

        # Calculate last 24h stats
        cutoff_time = datetime.now() - timedelta(hours=24)
        cutoff_iso = cutoff_time.isoformat()

        last_24h_entries = [entry for entry in history_entries if entry.get("timestamp", "") >= cutoff_iso]
        last_24h_checks = len(last_24h_entries)
        last_24h_up = sum(1 for entry in last_24h_entries if entry.get("status") == "UP")
        last_24h_uptime = (last_24h_up / last_24h_checks) * 100 if last_24h_checks > 0 else 0

        return {
            "uptime_percentage": uptime_percentage,
            "consecutive_up": consecutive_up,
            "consecutive_down": consecutive_down,
            "total_checks": total_checks,
            "total_up": total_up,
            "total_down": total_down,
            "average_latency": average_latency,
            "last_24h_uptime": last_24h_uptime,
            "last_24h_checks": last_24h_checks
        }

    def get_uptime_summary(self, service_id, history_entries):
        """Get a human-readable summary of service uptime."""
        if not history_entries:
            return "No history data available yet."

        stats = self.calculate_uptime_stats(service_id, history_entries)

        # For consecutive status reporting
        if stats["consecutive_up"] > 0:
            consecutive_status = f"UP for {stats['consecutive_up']} consecutive checks"
            status_class = "history-up"
        else:
            consecutive_status = f"DOWN for {stats['consecutive_down']} consecutive checks"
            status_class = "history-down"

        # For uptime percentage classification
        if stats["uptime_percentage"] >= 99:
            uptime_class = "uptime-good"
        elif stats["uptime_percentage"] >= 95:
            uptime_class = "uptime-warning"
        else:
            uptime_class = "uptime-bad"

        # Create summary message
        summary = f"Service is [{status_class}]{consecutive_status}[/] with "
        summary += f"[{uptime_class}]{stats['uptime_percentage']:.2f}% uptime[/] over {stats['total_checks']} checks."

        # Add 24h stats if available
        if stats["last_24h_checks"] > 0:
            if stats["last_24h_uptime"] >= 99:
                h24_class = "uptime-good"
            elif stats["last_24h_uptime"] >= 95:
                h24_class = "uptime-warning"
            else:
                h24_class = "uptime-bad"

            summary += f"\nLast 24h: [{h24_class}]{stats['last_24h_uptime']:.2f}% uptime[/] over {stats['last_24h_checks']} checks."

        if stats["average_latency"] > 0:
            summary += f"\nAverage response time: {int(stats['average_latency']*1000)} ms"

        return summary

    def update_service_history(self, service):
        """Add a new history entry for a service."""
        # Load existing history
        history_data = self.load_history_from_file()

        # Initialize service history if not exists
        service_id = service.get("id", str(uuid.uuid4()))
        if service_id not in history_data:
            history_data[service_id] = []

        # Create new history entry
        last_check = service.get("last_check", {})
        new_entry = {
            "timestamp": last_check.get("timestamp", datetime.now().isoformat()),
            "status": service.get("status", "PENDING"),
            "latency": last_check.get("latency"),
            "url": f"{service.get('url')}{service.get('path')}",
            "name": service.get("name")  # Store name for reference
        }

        # Add to history
        history_data[service_id].append(new_entry)

        # Prune old entries
        history_data = self.prune_history(history_data)

        # Save updated history
        self.save_history_to_file(history_data)

        return history_data

    def get_service_history(self, service_id):
        """Get all history entries for a service."""
        history_data = self.load_history_from_file()
        return history_data.get(service_id, [])

    def get_status_circle(self, status: str) -> str:
        # Unicode colored circle for status
        print(f"[DEBUG] get_status_circle called with status={status}")
        if status == "UP":
            return "[bold green]●[/]"
        elif status == "DOWN":
            return "[bold red]●[/]"
        else:
            return "[grey]●[/]"

    def update_service_row(self, service):
        try:
            print(f"[DEBUG] update_service_row called for {service['name']}")
            
            # Ensure service has an ID (for backward compatibility)
            if "id" not in service:
                service["id"] = str(uuid.uuid4())
                print(f"[DEBUG] Added missing ID to service {service['name']}")
                
            table = self.query_one("#services-table", DataTable)
            row_key = self.row_keys.get(service["id"])

            print(f"[DEBUG] Row key for {service['name']} is {row_key} while updating")
            print(f"[DEBUG] Current services: {self.services}")
            print(f"[DEBUG] Row keys: {self.row_keys}")
            print(f"[DEBUG] Column keys: {self.column_keys}")

            # If service doesn't exist in the row_keys, it might have been deleted
            if service["id"] not in self.row_keys:
                print(f"[DEBUG] Service {service['name']} no longer exists, skipping update")
                return

            # Get the current status directly from the service
            current_status = service.get("status", "PENDING")
            print(f"[DEBUG] Current status for {service['name']} is {current_status}")

            # Get last check details
            last_check = service.get("last_check", {})
            last_ping = last_check.get("latency", "N/A")
            last_time = last_check.get("timestamp", "N/A")

            # Format ping
            formatted_ping = f"{int(last_ping*1000)} ms" if last_ping not in (None, "N/A") else "N/A"

            # Get status circle
            status_circle = self.get_status_circle(current_status)

            if row_key is not None:
                # Update each cell individually
                try:
                    table.update_cell(row_key, self.column_keys["Status"], status_circle)
                    table.update_cell(row_key, self.column_keys["Current Status"], current_status)
                    table.update_cell(row_key, self.column_keys["Ping"], formatted_ping)
                    table.update_cell(row_key, self.column_keys["Last Check"], last_time)
                    print(f"[DEBUG] Successfully updated cells for {service['name']}")
                except Exception as e:
                    print(f"[DEBUG] Error updating cells: {e}")
            else:
                # Row doesn't exist, queue as add
                print(f"[DEBUG] Row key not found for {service['name']}, queueing as add")
                self.pending_updates.append({"action": "add_row", "service": service})

            # Update service details if this is the currently selected service
            if self.current_service and service["name"] == self.current_service["name"]:
                self.update_service_details(service)

        except Exception as e:
            # Table not available, queue update
            print(f"[DEBUG] Error updating row for {service['name']}: {e}")
            self.pending_updates.append({"action": "update_row", "service": service})

    def update_config_display(self):
        """Updates the configuration display panel with current config details"""
        try:
            config_display = self.query_one("#config-display", Static)

            # Read the config file and display its contents prettified
            config_file = Path(CONFIG_FILE)
            if config_file.exists():
                try:
                    with open(config_file, "r") as f:
                        config_data = json.load(f)
                        # print(f"[DEBUG] Loaded config data: {config_data}")

                    # Make a nice display of the config data
                    display_text = f"Analysis-Monitor Configuration\n\n"
                    display_text += f"Services Count: {len(config_data)}\n"
                    display_text += f"Config File: {config_file.absolute()}\n"
                    display_text += f"Check Interval: {DEFAULT_INTERVAL}s\n"
                    display_text += f"Alert Threshold: {self.down_alert_threshold} consecutive failures\n\n"

                    # Don't use rich markdown formatting for the JSON
                    display_text += "Raw Configuration: \n```\n"
                    display_text += json.dumps(config_data, indent=4, cls=AnalysisMonitorJSONEncoder)
                    display_text += "\n```"

                    # print(f"[DEBUG] Loaded config display text: {display_text}")

                    # Update the config display
                    config_display.update(display_text)               
                
                except Exception as e:
                    config_display.update(f"Error loading configuration: {str(e)}")
            else:
                config_display.update("No configuration file found.\nA new one will be created when services are added.")

        except Exception as e:
            print(f"[DEBUG] Error updating config display: {e}")

    def update_service_details(self, service):
        """Updates the service details panel with information about the selected service"""
        try:
            if not service:
                # Clear the details if no service is selected
                service_details = self.query_one("#service-details", Static)
                service_details.update("No service selected")
                # Update the graph to show all services or clear it if no services
                self.update_latency_graph()
                return
                
            service_details = self.query_one("#service-details", Static)
            
            # Get the current status and format accordingly
            status = service.get("status", "PENDING")
            if status == "UP":
                status_display = f"[bold green]{status}[/bold green]"
            elif status == "DOWN":
                status_display = f"[bold red]{status}[/bold red]"
            else:
                status_display = f"[grey]{status}[/grey]"
                
            # Get last check details
            last_check = service.get("last_check", {})
            last_ping = last_check.get("latency", "N/A")
            formatted_ping = f"{int(last_ping*1000)} ms" if last_ping not in (None, "N/A") else "N/A"
            last_time = last_check.get("timestamp", "N/A")
            
            # Format the details display
            details_text = f"[bold]{service['name']}[/bold]\n\n"
            details_text += f"[bold]Status:[/bold] {status_display}\n"
            details_text += f"[bold]URL:[/bold] {service['url']}{service['path']}\n"
            details_text += f"[bold]Check Interval:[/bold] {service.get('check_interval', DEFAULT_INTERVAL)}s\n"
            details_text += f"[bold]Last Ping:[/bold] {formatted_ping}\n"
            details_text += f"[bold]Last Check:[/bold] {last_time}\n"
            details_text += f"[bold]Consecutive Down:[/bold] {service.get('consecutive_down', 0)}\n"
            
            if 'alerted' in service:
                details_text += f"[bold]Alert Sent:[/bold] {'Yes' if service['alerted'] else 'No'}\n"
                
            # Get service history
            try:
                service_id = service.get("id", str(uuid.uuid4()))
                print(f"[DEBUG] Getting history for service ID: {service_id}")
                service_history = self.get_service_history(service_id)
                print(f"[DEBUG] Got history with {len(service_history)} entries")
                
                # Update the graph with all services' latency data
                self.update_latency_graph(selected_service_id=service_id)
                    
                # Generate and add history summary
                if service_history:
                    details_text += "\n[bold]Service History:[/bold]\n"
                    try:
                        details_text += self.get_uptime_summary(service_id, service_history)
                    except Exception as e:
                        print(f"[DEBUG] Error getting uptime summary: {e}")
                        details_text += "Error generating uptime summary."
                else:
                    details_text += "\n[bold]Service History:[/bold]\n"
                    details_text += "No history data available yet. History will be collected as the service is monitored."
            except Exception as e:
                print(f"[DEBUG] Error in service history section: {e}")
                import traceback
                traceback.print_exc()
                details_text += "\n[bold]Service History:[/bold]\n"
                details_text += "Error loading service history."
            
            service_details.update(details_text)
                
        except Exception as e:
            print(f"[DEBUG] Error updating service details: {e}")
            import traceback
            traceback.print_exc()

    def update_latency_graph(self, selected_service_id=None):
        """
        Updates the graph to display latency data for all services.
        If selected_service_id is provided, that service will be highlighted.
        If no services are present, clears the graph.
        """
        try:
            print(f"[DEBUG] Updating latency graph with {len(self.services)} services")
            self.graph.clear_data()
            self.graph.clear_figure()
            self.graph.xlabel("Time")
            self.graph.ylabel("Latency (ms)")
            
            # If no services, just set a default empty graph
            if not self.services:
                self.graph.title("Service Latency Over Time")
                service_details = self.query_one("#service-details", Static)
                service_details.update("No services being monitored. Add a service to begin monitoring.")
                return
                
            # Set graph title
            if selected_service_id:
                # Get the name of the selected service
                selected_name = next((s['name'] for s in self.services if s.get('id') == selected_service_id), None)
                if selected_name:
                    self.graph.title(f"Service Latency Comparison (Selected: {selected_name})")
                else:
                    self.graph.title("Service Latency Comparison")
            else:
                self.graph.title("Service Latency Comparison")
                
            # Plot data for all services
            colors = ["red", "blue", "green", "yellow", "purple", "orange", "cyan", "magenta"]
            for idx, service in enumerate(self.services):
                service_id = service.get("id", str(uuid.uuid4()))
                service_history = self.get_service_history(service_id)
                
                # Extract latency values and ensure they are valid numbers
                latency_data = []
                for entry in service_history:
                    latency = entry.get("latency")
                    if latency is not None and isinstance(latency, (int, float)):
                        latency_data.append(float(latency) * 1000)  # Convert to ms
                
                # Only plot if we have data
                if latency_data and len(latency_data) > 0:
                    # Ensure we have at least two data points for plotting
                    if len(latency_data) == 1:
                        # If only one point, duplicate it to have at least two points
                        latency_data = latency_data + latency_data
                    
                    # Use a different color for each service (cycle through colors list)
                    color = colors[idx % len(colors)]
                    
                    # Highlight the selected service with a thicker line
                    if service_id == selected_service_id:
                        # Plot selected service with a different marker and thicker line
                        self.graph.plot(latency_data, label=service['name'], marker="dot", color=color)
                    else:
                        self.graph.plot(latency_data, label=service['name'], marker="braille", color=color)
            
            # Only refresh the plot if we have services to display
            if self.services:
                service_plot = self.query_one(PlotextPlot)
                service_plot.refresh()
                
        except Exception as e:
            print(f"[DEBUG] Error updating latency graph: {e}")
            import traceback
            traceback.print_exc()

    def process_pending_updates(self):
        """Process and apply all pending service/table updates that were deferred while modal/dialog was active or table was unavailable."""
        if not self.pending_updates:
            return

        try:
            # Only process a limited number of updates at once to avoid UI freezes
            max_updates_per_cycle = 5
            updates_to_process = self.pending_updates[:max_updates_per_cycle]
            self.pending_updates = self.pending_updates[max_updates_per_cycle:]

            table = self.query_one("#services-table", DataTable)
            updates_to_retry = []

            for update in updates_to_process:
                try:
                    if update["action"] == "update_row":
                        service = update["service"]
                        # Skip if service doesn't exist anymore
                        if not any(s.get("id") == service.get("id") for s in self.services):
                            continue
                        self.update_service_row(service)
                    elif update["action"] == "add_row":
                        service = update["service"]
                        # Skip if service already has a row or doesn't exist anymore
                        if service.get("id") in self.row_keys or not any(s.get("id") == service.get("id") for s in self.services):
                            continue
                        last_check = service.get("last_check", {})
                        last_status = last_check.get("status", service.get("status", "PENDING"))
                        last_ping = last_check.get("latency", "N/A")
                        last_time = last_check.get("timestamp", "N/A")
                        row_key = table.add_row(
                            self.get_status_circle(last_status),
                            service["name"],
                            service["url"],
                            service["path"],
                            last_status,
                            f"{int(last_ping*1000)} ms" if last_ping not in (None, "N/A") else "N/A",
                            last_time
                        )
                        self.row_keys[service.get("id", str(uuid.uuid4()))] = row_key
                        self.name_to_id[service["name"]] = service.get("id", str(uuid.uuid4()))
                    elif update["action"] == "remove_row":
                        service_id = update["service_id"]
                        # Only remove if service no longer exists in our list
                        if not any(s.get("id") == service_id for s in self.services):
                            row_key = self.row_keys.pop(service_id, None)
                            if row_key is not None:
                                table.remove_row(row_key)
                except Exception as e:
                    print(f"[DEBUG] Error processing update {update['action']}: {e}")
                    updates_to_retry.append(update)

            # Add back any updates that failed
            self.pending_updates = updates_to_retry + self.pending_updates

            # If there are still updates to process, schedule another call
            if self.pending_updates:
                self.call_later(self.process_pending_updates)

        except Exception as e:
            print(f"[DEBUG] Error in process_pending_updates: {e}")
            # Schedule another attempt later
            self.call_later(self.process_pending_updates)

    @work
    async def check_services(self) -> None:
        """Check the uptime of all monitored services."""
        print("[DEBUG] Running check_services...")

        # First check if there are any services to monitor
        if not self.services:
            print("[DEBUG] No services to check")
            self.update_status("No services being monitored. Press 'a' to add a new service.")
            return

        # Create a copy of services to avoid modification issues during iteration
        services_to_check = list(self.services)

        for service in services_to_check:
            # Ensure service has an ID (for backward compatibility)
            if "id" not in service:
                service["id"] = str(uuid.uuid4())
                print(f"[DEBUG] Added missing ID to service {service['name']}")
            
            # Skip if service has been removed from the main list
            if not any(s.get("id") == service.get("id") for s in self.services):
                print(f"[DEBUG] Skipping check for removed service {service['name']}")
                continue

            url = f"{service['url']}{service['path']}"
            old_status = service.get("status", "PENDING")
            print(f"[DEBUG] Checking {service['name']} at {url} (old_status={old_status})")
            try:
                async with httpx.AsyncClient() as client:
                    start = datetime.now()
                    response = await client.get(url, timeout=5)
                    latency = (datetime.now() - start).total_seconds()
                    status = "UP" if response.status_code == 200 else "DOWN"
                    print(f"[DEBUG] {service['name']} responded with {response.status_code}, latency={latency}")
            except Exception as e:
                status = "DOWN"
                latency = 0
                print(f"[DEBUG] {service['name']} check failed: {e}")

            # Find the service in the current list (it may have been removed)
            service_index = None
            for i, s in enumerate(self.services):
                if s.get("id") == service.get("id"):
                    service_index = i
                    break

            if service_index is None:
                # Service was removed, skip updating
                print(f"[DEBUG] Service {service['name']} was removed during check, skipping update")
                continue

            # Get the current service instance
            current_service = self.services[service_index]

            # Update status
            old_service_status = current_service.get("status")
            current_service["status"] = status
            print(f"[DEBUG] Updated service status from {old_service_status} to {status}")

            # Store latest health ping
            current_service["last_check"] = {
                "timestamp": datetime.now().isoformat(),
                "status": status,
                "latency": latency if status == "UP" else None
            }

            # Update history log
            self.update_service_history(current_service)

            # Handle status changes
            if status == "DOWN":
                current_service["consecutive_down"] = current_service.get("consecutive_down", 0) + 1
                if old_status != "DOWN":
                    current_service["alerted"] = True
                    print(f"[DEBUG] Posting DOWN message for {current_service['name']}")
                    MessagePump.post_message(
                        self, 
                        ServiceStatusChangeMessage(current_service["name"], "DOWN", old_status or "UNKNOWN")
                    )
            else:
                if old_status == "DOWN":
                    print(f"[DEBUG] Posting UP message for {current_service['name']}")
                    MessagePump.post_message(
                        self, 
                        ServiceStatusChangeMessage(current_service["name"], "UP", "DOWN")
                    )
                current_service["consecutive_down"] = 0
                current_service["alerted"] = False

            # Always post update message to refresh UI
            print(f"[DEBUG] Posting UpdateServiceMessage for {current_service['name']} with status={current_service['status']}")
            MessagePump.post_message(self, UpdateServiceMessage(current_service))

        # If no services left, update the status
        if not self.services:
            self.update_status("No services available. Press 'a' to add a new service.")

        print("[DEBUG] check_services complete. Current services:")
        for s in self.services:
            print(f"  - {s['name']}: {s['status']}")

    def on_key(self, event) -> None:
        """Handle key press events."""
        # Provide an emergency escape from any state - Ctrl+X
        if event.key == "ctrl+x":
            self.show_notification("Emergency exit triggered", severity="warning")
            self.is_modal_active = False
            self.pending_updates = []
            self.update_status("Emergency recovery completed")
            # Force refresh the table
            self.call_later(self.refresh_services_table)

    def update_status(self, message: str):
        """Update the status bar with a message."""
        try:
            self.status = message
            print(f"[DEBUG] Status updated: {message}")
        except Exception as e:
            print(f"[DEBUG] Error updating status: {e}")

    def safe_update_status(self, message: str):
        """Safely update status bar, handling case when modal is active."""
        if self.is_modal_active:
            self.status = message
        else:
            self.update_status(message)

    def show_notification(self, message: str, severity: str = "information"):
        """Display a toast notification."""
        # Apply custom styling based on severity
        self.notify(message, title="Analysis Monitor", severity=severity, timeout=5)
        
        # Also show system notification for errors and warnings
        if severity in ["error", "warning"]:
            try:
                system_notification.notify(
                    title="Analysis Monitor Alert",
                    message=message,
                    app_name="Analysis",
                    timeout=10
                )
            except Exception as e:
                # If system notification fails, just log the error but continue
                print(f"System notification error: {e}")

    @on(DataTable.RowSelected)
    def show_service_details(self, event: DataTable.RowSelected):
        """Handle row selection to show service details."""
        table = self.query_one("#services-table", DataTable)
        if event.row_index is not None and event.row_key in table.rows:
            # Get the service name from the row
            row_values = table.get_row(event.row_key)
            service_name = row_values[1]  # Service name is in the second column
            
            # Find the service with this row key
            for service_id, row_key in self.row_keys.items():
                if row_key == event.row_key:
                    # Find the service with this ID
                    for service in self.services:
                        if service.get("id") == service_id:
                            self.current_service = service
                            self.update_status(f"Selected: {service['name']}")
                            self.update_service_details(service)
                            return
                    break

    @on(UpdateServiceMessage)
    def handle_service_update(self, message: UpdateServiceMessage):
        print(f"[DEBUG] handle_service_update called for {message.service['name']} with status={message.service.get('status', 'UNKNOWN')}")
        # Update the UI
        self.update_service_row(message.service)
        # Save to config
        self.save_services_to_config()

    @on(ServiceStatusChangeMessage)
    def handle_service_status_change(self, message: ServiceStatusChangeMessage):
        print(f"[DEBUG] handle_service_status_change: {message.service_name} {message.old_status} -> {message.new_status}")
        if message.new_status == "DOWN" and message.old_status != "DOWN":
            # Service went down - show error notification
            self.show_notification(
                f"⚠️ Service {message.service_name} is DOWN!",
                severity="error"
            )
            # Send Discord SOS notification
            self.send_discord_sos(message.service_name, status="DOWN")
        elif message.new_status == "UP" and message.old_status == "DOWN":
            # Service recovered - show success notification
            self.show_notification(
                f"✅ Service {message.service_name} is back UP!",
                severity="success"
            )
            # Find service details for notification
            service = next((s for s in self.services if s["name"] == message.service_name), None)
            if service:
                latency = service["last_check"].get("latency")
                timestamp = service["last_check"].get("timestamp")
                url = service.get("url")
                print(f"[DEBUG] Sending Discord UP notification for {service['name']}")
                self.send_discord_sos(message.service_name, status="UP", url=url, latency=latency, timestamp=timestamp)
            # Force table update for service status
            self.update_service_row(service)

    def send_discord_sos(self, service_name: str, status: str = "DOWN", url: str = None, latency: float = None, timestamp: datetime = None):
        print(f"[DEBUG] send_discord_sos called for {service_name} status={status}")
        if not DISCORD_WEBHOOK_URL:
            print("Discord webhook URL not set. Cannot send SOS.")
            return
        try:
            # Convert string timestamp to datetime if needed
            if isinstance(timestamp, str):
                try:
                    timestamp = datetime.fromisoformat(timestamp)
                except (ValueError, TypeError):
                    timestamp = None
            
            now = timestamp or datetime.now()
            
            # Make sure we have pytz installed
            try:
                import pytz
                ist = pytz.timezone("Asia/Kolkata")
                now_ist = now.astimezone(ist)
                formatted_time = now_ist.strftime("%Y-%m-%d %H:%M:%S")
                formatted_date = now_ist.strftime("%d/%m/%Y, %H:%M")
            except Exception as e:
                print(f"[DEBUG] Error with timezone conversion: {e}")
                formatted_time = now.strftime("%Y-%m-%d %H:%M:%S")
                formatted_date = now.strftime("%d/%m/%Y, %H:%M")
            
            # Format ping value safely
            try:
                ping_ms = f"{int(float(latency) * 1000)} ms" if latency is not None else "N/A"
            except (ValueError, TypeError):
                ping_ms = "N/A"
                print(f"[DEBUG] Error converting latency to int: {latency}")
            
            # Create message content
            if status == "UP":
                content = f"✅ Your service **{service_name}** is up! ✅\nService Name: **{service_name}**\nService URL: {url}\nTime (Asia/Kolkata): {formatted_time}\nPing: {ping_ms}\n{formatted_date}"
            else:
                content = f"@everyone :rotating_light: **SOS! Service '{service_name}' is DOWN!** :rotating_light: \nService Name: **{service_name}**\nService URL: {url}\nTime (Asia/Kolkata): {formatted_time}\nPing: {ping_ms}\n{formatted_date}"
            
            data = {"content": content}
            print(f"[DEBUG] Sending Discord webhook: {data}")
            
            # Use httpx instead of requests for consistency
            import httpx
            response = httpx.post(DISCORD_WEBHOOK_URL, json=data, timeout=10)
            print(f"[DEBUG] Discord webhook response: {response.status_code} {response.text}")
            
            if response.status_code != 204 and response.status_code != 200:
                print(f"Failed to send Discord SOS notification: {response.status_code} {response.text}")
        except Exception as e:
            print(f"Error sending Discord SOS: {e}")
            import traceback
            traceback.print_exc()
    
    def action_refresh(self):
        """Force a complete refresh of the services table and status."""
        self.refresh_services_table()
        self.update_status(f"Refreshed {len(self.services)} services")
        self.check_services()  # Trigger a fresh check of all services

        # Also refresh the current service details if one is selected
        if self.current_service:
            self.update_service_details(self.current_service)

    def action_add_service(self):
        """Open the modal to add a new service."""
        self.is_modal_active = True

        def add_service_callback(result):
            try:
                self.is_modal_active = False

                # First clear any pending updates to prevent conflicts
                self.pending_updates = []

                # Update status bar with the stored message
                if self.status:
                    self.update_status(self.status)

                # Handle cancellation - just return without doing anything else
                if result is None:
                    self.show_notification("Service addition cancelled", severity="warning")
                    self.update_status("Service addition cancelled")
                    return

                # Check for duplicate service names
                existing_names = [s["name"] for s in self.services]
                if result["name"] in existing_names:
                    self.show_notification(f"A service with name '{result['name']}' already exists", severity="error")
                    return

                # Create a new list with the new service (better for reactive state)
                new_services = list(self.services)
                new_services.append(result)

                # Update the services list
                self.services = new_services

                # Update the table
                self.call_later(self._add_service_to_table, result)

                 # Set current service to the newly added service
                self.current_service = result
                self.update_service_details(result)  # Immediately update the details panel

                # Save configuration
                self.call_later(self.save_services_to_config)

                # Update status and selection
                self.update_status(f"Added new service: {result['name']}")
                if len(self.services) == 1:
                    self.current_service = result

            except Exception as e:
                # Handle any errors during callback
                print(f"[DEBUG] Error in add_service_callback: {e}")
                import traceback
                traceback.print_exc()
                self.show_notification(f"Error adding service: {str(e)}", severity="error")
                self.update_status("Error adding service")

        # Use call_later to defer the screen push to avoid blocking UI
        self.call_later(lambda: self.push_screen(AddServiceModal(), callback=add_service_callback))

    def _add_service_to_table(self, service):
        """Helper method to add a service to the table safely"""
        try:
            table = self.query_one("#services-table", DataTable)
            row_key = table.add_row(
                self.get_status_circle("PENDING"),
                service["name"],
                service["url"],
                service["path"],
                "PENDING",
                "N/A",
                "N/A"
            )
            self.row_keys[service.get("id", str(uuid.uuid4()))] = row_key
            self.name_to_id[service["name"]] = service.get("id", str(uuid.uuid4()))
        except Exception as e:
            print(f"[DEBUG] Error adding row: {e}")
            # Queue for later processing
            self.pending_updates.append({"action": "add_row", "service": service})

    def action_delete_service(self):
        """Delete the currently selected service with confirmation."""
        if not self.current_service:
            self.show_notification("No service selected to delete", severity="warning")
            return

        service_id = self.current_service.get("id", str(uuid.uuid4()))
        service_name = self.current_service["name"]
        self.is_modal_active = True  # Set flag that modal is active

        def delete_service_callback(confirmed):
            self.is_modal_active = False  # Reset flag when done

            # Process any pending updates that occurred while modal was open
            self.call_later(self.process_pending_updates)

            if not confirmed:
                self.show_notification("Service deletion cancelled", severity="information")
                return

            # Create a new list without the service to delete
            new_services = [s for s in self.services if s.get("id") != service_id]

            # Only proceed if we actually found something to remove
            if len(new_services) < len(self.services):
                # Save the current service before updating the list
                removed_service = self.current_service

                # Update the services list with a new list reference to trigger reactive updates
                self.services = new_services

                try:
                    table = self.query_one("#services-table", DataTable)
                    row_key = self.row_keys.pop(removed_service.get("id", str(uuid.uuid4())), None)
                    if row_key is not None:
                        table.remove_row(row_key)
                    # Also remove from name_to_id mapping
                    if removed_service["name"] in self.name_to_id:
                        del self.name_to_id[removed_service["name"]]
                except Exception as e:
                    print(f"[DEBUG] Error removing row: {e}")
                    self.pending_updates.append({"action": "remove_row", "service_id": service_id})

                if self.services:
                    self.current_service = self.services[0]
                    try:
                        table = self.query_one("#services-table", DataTable)
                        if table.row_count > 0:
                            table.cursor_coordinate = (0, 0)
                    except Exception as e:
                        print(f"[DEBUG] Error setting cursor: {e}")
                else:
                    # If no services left, clear current_service
                    self.current_service = None
                    # Clear the table completely to ensure no phantom services
                    try:
                        table = self.query_one("#services-table", DataTable)
                        table.clear(rows=True)  # Only clear rows, not columns
                        self.row_keys.clear()  # Clear all row keys
                        self.name_to_id.clear()  # Clear name to ID mapping
                    except Exception as e:
                        print(f"[DEBUG] Error clearing table: {e}")

                self.save_services_to_config()
                
                # Update the graph to reflect removed service
                self.update_latency_graph()
                
                # Update the service details panel
                self.update_service_details(self.current_service)

                self.show_notification(f"Service '{service_name}' deleted", severity="information")

                # Show specific message when no services are left
                if len(self.services) == 0:
                    self.update_status("No services available. Press 'a' to add a new service.")
                    self.show_notification("No services being monitored. Add a service to begin monitoring.", severity="information")
                else:
                    self.update_status(f"Service '{service_name}' removed. {len(self.services)} services remaining.")
            else:
                self.show_notification(f"Could not find service with ID '{service_id}'", severity="error")

        # Show the confirmation modal
        self.push_screen(DeleteConfirmationModal(service_name, service_id), callback=delete_service_callback)
            
    def action_quit(self):
        """Quit the application."""
        self.exit()
        
    def key_a(self):
        """Handle 'a' key press to add a service."""
        self.action_add_service()

    def key_d(self):
        """Handle 'd' key press to delete a service."""
        self.action_delete_service()
    
    def key_r(self):
        """Handle 'r' key press to refresh all services."""
        self.action_refresh()

    def key_q(self):
        """Handle 'q' key press to quit the application."""
        self.action_quit()

    def on_resume(self):
        self.process_pending_updates()

    def refresh_services_table(self):
        """Clear and reload all services into the table."""
        try:
            table = self.query_one("#services-table", DataTable)
            table.clear(rows=True)  # ONLY clear the rows, not the entire table structure

            self.row_keys.clear()

            for service in self.services:
                last_check = service.get("last_check", {})
                last_status = last_check.get("status", service.get("status", "PENDING"))
                last_ping = last_check.get("latency", "N/A")
                last_time = last_check.get("timestamp", "N/A")
                row_key = table.add_row(
                    self.get_status_circle(last_status),
                    service["name"],
                    service["url"],
                    service["path"],
                    last_status,
                    f"{int(last_ping*1000)} ms" if last_ping not in (None, "N/A") else "N/A",
                    last_time
                )
                self.row_keys[service.get("id", str(uuid.uuid4()))] = row_key
        except Exception as e:
            print(f"[DEBUG] Error refreshing services table: {e}")

# Run the application
if __name__ == "__main__":
    try:
        app = AnalysisMonitorDashboard()
        app.run()
    except Exception as e:
        import traceback
        print(f"Error: {e}")
        traceback.print_exc()