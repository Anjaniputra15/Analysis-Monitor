# Analysis-Monitor - Service Monitoring Dashboard

<img width="1147" alt="Screenshot 1947-03-09 at 5 38 58 PM" src="https://github.com/user-attachments/assets/8715a539-bff9-49ae-82b1-bcba8e80b793" />

Analysis-Monitor is a powerful, terminal-based service monitoring dashboard built with Python and Textual. It provides real-time monitoring of web services, with features for uptime tracking, latency measurement, and alert notifications.




## Features

- **Real-time Service Monitoring**: Track the status of multiple web services simultaneously
- **Interactive TUI Dashboard**: Beautiful terminal-based user interface with color-coded status indicators
- **Latency Tracking**: Monitor and graph response times for your services
- **Uptime Statistics**: View detailed uptime percentages and history
- **Alert Notifications**: Get notified when services go down or recover
- **Discord Integration**: Send alerts to Discord channels when service status changes
- **Persistent Configuration**: Automatically saves your service configurations
- **History Logging**: Maintains historical data for trend analysis

## Installation

### Prerequisites

- Python 3.7+
- pip (Python package manager)

### Dependencies

Analysis-Monitor requires the following Python packages:

```bash
pip install textual httpx plyer textual-plotext
```

For timezone support (optional):
```bash
pip install pytz
```

## Usage

### Starting Analysis-Monitor

Run Analysis-Monitor from the command line:

```bash
python main.py
```

### Adding Services

1. Press `a` to add a new service
2. Enter the service details:
   - Service Name: A descriptive name for the service
   - Host: The hostname or IP address (default: localhost)
   - Port: The port number
   - Path: The URL path (default: /)
   - Check Interval: How often to check the service in seconds (default: 10)

### Managing Services

- Press `d` to delete the selected service
- Press `r` to refresh all services
- Press `q` to quit the application

### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| a | Add a new service |
| d | Delete selected service |
| r | Refresh all services |
| q | Quit the application |
| Ctrl+X | Emergency recovery (if UI becomes unresponsive) |

## Configuration

Analysis-Monitor stores its configuration in two files:

- `analysis_config.json`: Contains service definitions and settings
- `analysis_history.json`: Contains historical monitoring data

These files are automatically created in the same directory as the application.

## Discord Notifications

Analysis-Monitor can send notifications to Discord when a service changes status. To use this feature:

1. Create a webhook URL in your Discord server
2. Set the `DISCORD_WEBHOOK_URL` constant in the code

## Use Cases

### DevOps Monitoring

Monitor critical infrastructure services to ensure they're running properly. Get immediate notifications when services go down.

### Microservice Health Checks

Keep track of multiple microservices in a distributed architecture, with visual indicators of system health.

### API Endpoint Monitoring

Monitor external API endpoints your application depends on, with latency tracking to identify performance issues.

### Personal Website Uptime Tracking

Ensure your personal website or blog stays online with automatic monitoring and alerts.

## Customization

You can customize Analysis-Monitor by modifying the following constants in the code:

- `DEFAULT_HOST`: Default hostname for new services
- `DEFAULT_INTERVAL`: Default check interval in seconds
- `DOWN_ALERT_THRESHOLD`: Number of consecutive failed checks before alerting
- `MAX_HISTORY_ENTRIES`: Maximum number of history entries to keep per service
- `HISTORY_RETENTION_DAYS`: How many days of history to retain

## Troubleshooting

- If the UI becomes unresponsive, press `Ctrl+X` for emergency recovery
- Check the console output for debug messages if you encounter issues
- Ensure all services have valid URLs in the format `http://hostname:port`

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Acknowledgements

- Built with [Textual](https://github.com/Textualize/textual), a TUI framework for Python
- Uses [Plotext](https://github.com/piccolomo/plotext) for terminal-based plotting
