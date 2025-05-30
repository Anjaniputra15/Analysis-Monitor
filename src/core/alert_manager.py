import httpx
import logging
from typing import Dict, Optional
from datetime import datetime
import os
from abc import ABC, abstractmethod

class AlertChannel(ABC):
    @abstractmethod
    async def send_alert(self, service: Dict, alert_type: str, details: Dict) -> bool:
        pass

class DiscordNotifier(AlertChannel):
    def __init__(self, webhook_url: Optional[str] = None):
        self.webhook_url = webhook_url or os.getenv('DISCORD_WEBHOOK_URL')
        self.logger = logging.getLogger(__name__)

    async def send_alert(self, service: Dict, alert_type: str, details: Dict) -> bool:
        if not self.webhook_url:
            self.logger.warning("Discord webhook URL not configured")
            return False

        try:
            content = self._format_message(service, alert_type, details)
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.webhook_url,
                    json={"content": content},
                    timeout=10
                )
                return response.status_code in (200, 204)
        except Exception as e:
            self.logger.error(f"Error sending Discord alert: {str(e)}")
            return False

    def _format_message(self, service: Dict, alert_type: str, details: Dict) -> str:
        status_emoji = "✅" if alert_type == "UP" else "⚠️"
        return (
            f"{status_emoji} Service **{service['name']}** is {alert_type}!\n"
            f"URL: {service['url']}{service['path']}\n"
            f"Time: {details.get('timestamp', datetime.now().isoformat())}\n"
            f"Latency: {details.get('latency', 'N/A')} ms"
        )

class EmailNotifier(AlertChannel):
    def __init__(self, smtp_config: Dict):
        self.smtp_config = smtp_config
        self.logger = logging.getLogger(__name__)

    async def send_alert(self, service: Dict, alert_type: str, details: Dict) -> bool:
        # Implement email sending logic
        self.logger.info("Email notifications not implemented yet")
        return False

class SlackNotifier(AlertChannel):
    def __init__(self, webhook_url: Optional[str] = None):
        self.webhook_url = webhook_url or os.getenv('SLACK_WEBHOOK_URL')
        self.logger = logging.getLogger(__name__)

    async def send_alert(self, service: Dict, alert_type: str, details: Dict) -> bool:
        if not self.webhook_url:
            self.logger.warning("Slack webhook URL not configured")
            return False

        try:
            blocks = self._format_blocks(service, alert_type, details)
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.webhook_url,
                    json={"blocks": blocks},
                    timeout=10
                )
                return response.status_code == 200
        except Exception as e:
            self.logger.error(f"Error sending Slack alert: {str(e)}")
            return False

    def _format_blocks(self, service: Dict, alert_type: str, details: Dict) -> list:
        return [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"Service Alert: {service['name']} is {alert_type}"
                }
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*URL:*\n{service['url']}{service['path']}"},
                    {"type": "mrkdwn", "text": f"*Status:*\n{alert_type}"},
                    {"type": "mrkdwn", "text": f"*Latency:*\n{details.get('latency', 'N/A')} ms"},
                    {"type": "mrkdwn", "text": f"*Time:*\n{details.get('timestamp', datetime.now().isoformat())}"}
                ]
            }
        ]

class AlertManager:
    def __init__(self):
        self.channels: Dict[str, AlertChannel] = {}
        self.logger = logging.getLogger(__name__)

    def add_channel(self, name: str, channel: AlertChannel) -> None:
        """Add a notification channel."""
        self.channels[name] = channel

    async def send_alert(self, service: Dict, alert_type: str, details: Dict) -> None:
        """Send alerts through all configured channels."""
        if not self.channels:
            self.logger.warning("No alert channels configured")
            return

        for channel_name, channel in self.channels.items():
            try:
                success = await channel.send_alert(service, alert_type, details)
                if success:
                    self.logger.info(f"Alert sent successfully through {channel_name}")
                else:
                    self.logger.warning(f"Failed to send alert through {channel_name}")
            except Exception as e:
                self.logger.error(f"Error sending alert through {channel_name}: {str(e)}")

    def configure_default_channels(self) -> None:
        """Configure default notification channels."""
        # Add Discord if webhook URL is available
        discord_url = os.getenv('DISCORD_WEBHOOK_URL')
        if discord_url:
            self.add_channel('discord', DiscordNotifier(discord_url))

        # Add Slack if webhook URL is available
        slack_url = os.getenv('SLACK_WEBHOOK_URL')
        if slack_url:
            self.add_channel('slack', SlackNotifier(slack_url))

        # Add email if SMTP config is available
        smtp_config = {
            'host': os.getenv('SMTP_HOST'),
            'port': os.getenv('SMTP_PORT'),
            'username': os.getenv('SMTP_USERNAME'),
            'password': os.getenv('SMTP_PASSWORD'),
            'from_email': os.getenv('SMTP_FROM_EMAIL'),
            'to_email': os.getenv('SMTP_TO_EMAIL')
        }
        if all(smtp_config.values()):
            self.add_channel('email', EmailNotifier(smtp_config)) 