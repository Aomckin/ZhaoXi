"""Extension point for presence activities."""
from .models import ActivitySpec

class ActivityRegistry:
    def __init__(self):
        self._specs: dict[str, ActivitySpec] = {}

    def register(self, spec: ActivitySpec):
        if spec.name in self._specs:
            raise ValueError(f"duplicate activity: {spec.name}")
        self._specs[spec.name] = spec

    def get(self, name):
        return self._specs[name]

    def __iter__(self):
        return iter(self._specs.values())

    def __contains__(self, name):
        return name in self._specs
