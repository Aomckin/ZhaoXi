"""Isolated dashboard fixture with no real model, plugins or user stores."""
from types import SimpleNamespace
from zhaoxi.config.settings import Settings
from zhaoxi.current_cognition.store import CurrentCognitionStore
from zhaoxi.current_cognition.service import CurrentCognitionService
from zhaoxi.internal_activity.runtime import InternalActivityRuntime
from zhaoxi.proactive.interaction import Interaction
from web_fixture import FakeAgent

def dashboard_core(path):
    settings=Settings(_env_file=None,dev_browser_ui=True,perception_enabled=False,
        current_cognition_consolidation_enabled=False,memory_maintenance_enabled=False,
        agenda_maintenance_enabled=False,proactive_activity_enabled=False,external_cognition_ambient_enabled=False,
        interface_settings_path=str(path/"interface.json"),internal_activity_db_path=str(path/"activity.db"))
    core=FakeAgent()
    core.provider=object()
    core.current_cognition=CurrentCognitionService(CurrentCognitionStore(path/"cognition.db"))
    core.proactive_state=SimpleNamespace(interaction=Interaction(),interacting=False,enabled=False,quiet_until=None,last_interaction_at=None)
    core.internal_activity=InternalActivityRuntime(core,settings,path/"activity.db")
    return core,settings
