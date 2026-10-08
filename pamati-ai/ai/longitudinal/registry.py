from ai.longitudinal.algorithms import DescriptiveTracking


class TrackingRegistry:
    def __init__(self):
        self.factories = {"descriptive-personal-trends": DescriptiveTracking}

    def register(self, name, factory):
        if not name or name in self.factories:
            raise ValueError("Empty or duplicate tracking algorithm")
        self.factories[name] = factory

    def resolve(self, name):
        if name not in self.factories:
            raise ValueError("Unknown tracking algorithm")
        algorithm = self.factories[name]()
        if not algorithm.identifier or not algorithm.version:
            raise ValueError("Tracking algorithm identifier and version are required")
        return algorithm


registry = TrackingRegistry()
