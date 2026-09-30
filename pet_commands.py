"""Application commands shared by IPC and local controls, independent of widgets."""
from contracts import validate_action


class PetCommands:
    def __init__(self, notifications, animation):
        self.notifications = notifications
        self.animation = animation

    def status(self):
        return dict(running=not self.notifications.closed, pet=self.animation.pet.name,
                    queued=len(self.notifications.queue),
                    current_id=self.notifications.current.id if self.notifications.current else None,
                    current_action=self.animation.track_name, paused=self.animation.paused)

    def __call__(self, request):
        command = request.get("command")
        options = {k: v for k, v in request.items() if k != "command"}
        if command == "bell":
            return self.notifications.notify(**options)
        if command == "status":
            return self.status()
        if command == "list_actions":
            return self.animation.list_actions()
        if command == "play_action":
            return self.animation.play_action(**validate_action(**options))
        raise ValueError("未知桌宠命令")
