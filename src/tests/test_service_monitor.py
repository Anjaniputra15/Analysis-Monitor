import pytest
import asyncio
from datetime import datetime
from src.core.service_monitor import ServiceMonitor

@pytest.fixture
def mock_service():
    return {
        'id': 'test-1',
        'name': 'Test Service',
        'url': 'http://example.com',
        'path': '/test'
    }

@pytest.mark.asyncio
async def test_check_service_success(mock_service):
    async with ServiceMonitor() as monitor:
        result = await monitor.check_service_with_retry(mock_service)
        assert result['service_id'] == mock_service['id']
        assert result['name'] == mock_service['name']
        assert 'status' in result
        assert 'latency' in result
        assert 'timestamp' in result

@pytest.mark.asyncio
async def test_check_service_timeout(mock_service):
    monitor = ServiceMonitor(timeout=0.001)  # Very short timeout
    result = await monitor.check_service_with_retry(mock_service)
    assert result['status'] == 'DOWN'
    assert result['error'] == 'TIMEOUT'

@pytest.mark.asyncio
async def test_check_services_parallel():
    services = [
        {
            'id': f'test-{i}',
            'name': f'Test Service {i}',
            'url': 'http://example.com',
            'path': f'/test{i}'
        }
        for i in range(3)
    ]
    
    async with ServiceMonitor() as monitor:
        results = await monitor.check_services_parallel(services)
        assert len(results) == len(services)
        for result in results:
            assert 'status' in result
            assert 'latency' in result
            assert 'timestamp' in result

def test_create_error_response(mock_service):
    monitor = ServiceMonitor()
    error = "Test error"
    result = monitor._create_error_response(mock_service, error)
    assert result['service_id'] == mock_service['id']
    assert result['name'] == mock_service['name']
    assert result['status'] == 'DOWN'
    assert result['error'] == error
    assert 'timestamp' in result 