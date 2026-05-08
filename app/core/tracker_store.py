class InMemoryTrackerStore:
    def __init__(self):
        self._data = {}

    def get_or_create(self, sender_id: str):
        if sender_id not in self._data:
            self._data[sender_id] = {
                "sender_id": sender_id,
                "latest_message": None,
                "slots": {},
                "events": [],
                "latest_action_name": None,
                "active_flow": None,
                "flow_step_index": 0,
                "slot_to_collect": None
                
            }
        return self._data[sender_id]

    def save(self, tracker: dict):
        self._data[tracker["sender_id"]] = tracker

    def retrieve(self, sender_id: str):
        return self._data.get(sender_id)

    def delete(self, sender_id: str) -> bool:
        if sender_id not in self._data:
            return False

        del self._data[sender_id]
        return True
