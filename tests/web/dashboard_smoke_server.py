"""Local fixture server for the dashboard browser acceptance test."""
from pathlib import Path
import uvicorn
import zhaoxi.core.agent
from zhaoxi.web.app import create_app
from dashboard_fixture import dashboard_core

if __name__=="__main__":
    path=Path(".zhaoxi/v145-browser-fixture");path.mkdir(parents=True,exist_ok=True)
    core,settings=dashboard_core(path)
    settings.dev_browser_ui=False
    core.internal_activity.control.update("presence",{"heartbeat_enabled":False})
    uvicorn.run(create_app(agent=core,settings=settings,api_token="dashboard-ui-test"),host="127.0.0.1",port=18765)
