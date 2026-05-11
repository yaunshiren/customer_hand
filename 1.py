from app.dialogue.flow_executor import FlowExecutor
from app.core.tracker import DialogueStateTracker
from app.actions.builtin import register_builtin_actions

register_builtin_actions()

executor = FlowExecutor()
tracker = DialogueStateTracker("u1")

action_name = executor.decide_next_action(tracker, "我要退货")
print(action_name, tracker.active_flow)

result = executor._handle_action_step(tracker, action_name)
print(result.to_dict())

action_name = executor.decide_next_action(tracker, "A12345678")
print(action_name, tracker.get_slot("order_id"))

result = executor._handle_action_step(tracker, action_name)
print(result.to_dict())