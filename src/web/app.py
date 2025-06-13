from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi import Request
import asyncio
from ..core.config_manager import ConfigManager
from ..core.service_monitor import ServiceMonitor

config_manager = ConfigManager('analysis_config.json')
service_monitor = ServiceMonitor()

app = FastAPI(title="Analysis Monitor API")

templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    services = config_manager.get_services()
    return templates.TemplateResponse("index.html", {"request": request, "services": services})

@app.get("/services")
async def list_services():
    return config_manager.get_services()

@app.post("/services")
async def add_service(service: dict):
    config_manager.add_service(service)
    return {"status": "added"}

@app.delete("/services/{service_id}")
async def remove_service(service_id: str):
    config_manager.remove_service(service_id)
    return {"status": "removed"}

@app.get("/services/{service_id}/status")
async def service_status(service_id: str):
    services = [s for s in config_manager.get_services() if s.get('id') == service_id]
    if not services:
        raise HTTPException(status_code=404, detail="Service not found")
    result = await service_monitor.check_service_with_retry(services[0])
    return result
