import asyncio
import httpx
from datetime import datetime
from typing import Dict, List, Optional
import logging

class ServiceMonitor:
    def __init__(self, max_retries: int = 3, timeout: float = 5.0):
        self.max_retries = max_retries
        self.timeout = timeout
        self.logger = logging.getLogger(__name__)
        self._client = None

    async def __aenter__(self):
        self._client = httpx.AsyncClient(timeout=self.timeout)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._client:
            await self._client.aclose()

    async def check_service_with_retry(self, service: Dict) -> Dict:
        """Check a single service with retry mechanism and exponential backoff."""
        for attempt in range(self.max_retries):
            try:
                return await self._check_service(service)
            except httpx.TimeoutException:
                if attempt == self.max_retries - 1:
                    self.logger.error(f"Service {service['name']} timed out after {self.max_retries} attempts")
                    return self._create_error_response(service, "TIMEOUT")
                await asyncio.sleep(2 ** attempt)
            except Exception as e:
                self.logger.error(f"Error checking service {service['name']}: {str(e)}")
                return self._create_error_response(service, str(e))

    async def _check_service(self, service: Dict) -> Dict:
        """Check a single service and return its status."""
        url = f"{service['url']}{service['path']}"
        start_time = datetime.now()
        
        try:
            response = await self._client.get(url)
            latency = (datetime.now() - start_time).total_seconds()
            
            return {
                'service_id': service.get('id'),
                'name': service['name'],
                'status': 'UP' if response.status_code == 200 else 'DOWN',
                'latency': latency,
                'timestamp': datetime.now().isoformat(),
                'status_code': response.status_code
            }
        except Exception as e:
            return self._create_error_response(service, str(e))

    def _create_error_response(self, service: Dict, error: str) -> Dict:
        """Create an error response for failed service checks."""
        return {
            'service_id': service.get('id'),
            'name': service['name'],
            'status': 'DOWN',
            'latency': None,
            'timestamp': datetime.now().isoformat(),
            'error': error
        }

    async def check_services_parallel(self, services: List[Dict]) -> List[Dict]:
        """Check multiple services in parallel."""
        if not services:
            return []

        async with self:
            tasks = [self.check_service_with_retry(service) for service in services]
            results = await asyncio.gather(*tasks)
            return results 