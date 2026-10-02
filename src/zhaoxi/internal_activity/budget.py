"""Conservative reservations; debug cannot bypass resource caps."""
from collections import Counter
from .models import CostClass

class TickBudget:
    def __init__(self, settings):
        get = lambda key, default: getattr(settings, key, default)
        self.limits = {
            "llm": get("internal_activity_max_llm_per_tick", 1),
            "llm_light": get("internal_activity_max_llm_light_per_tick", 1),
            "llm_heavy": get("internal_activity_max_llm_heavy_per_tick", 0),
            "local": get("internal_activity_max_local_per_tick", 3),
            "external_read": get("internal_activity_max_external_read_per_tick", 1),
            "external_write": get("internal_activity_max_external_write_per_tick", 1),
        }
        self.used = Counter()

    @staticmethod
    def resources(spec, kind):
        cost = CostClass.LLM_LIGHT if kind == "llm" else spec.cost_class
        if kind == "local":
            cost = CostClass.LOCAL_LIGHT
        needs = Counter()
        if cost in {CostClass.LOCAL_LIGHT, CostClass.LOCAL_HEAVY}:
            needs["local"] = 1
        if cost in {CostClass.LLM_LIGHT, CostClass.LLM_HEAVY} or spec.requires_llm:
            needs["llm"] = 1
            needs["llm_heavy" if cost == CostClass.LLM_HEAVY else "llm_light"] = 1
        if cost == CostClass.EXTERNAL_READ or spec.requires_external_io:
            needs["external_read"] = 1
        if cost == CostClass.EXTERNAL_WRITE or spec.can_message_external:
            needs["external_write"] = 1
        return needs

    def reserve(self, spec, kind):
        needs = self.resources(spec, kind)
        if any(self.used[key] + value > self.limits[key] for key, value in needs.items()):
            return False
        self.used.update(needs)
        return True

    def diagnostics(self):
        return {key: {"used": self.used[key], "limit": limit} for key, limit in self.limits.items()}
