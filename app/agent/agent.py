from app.core.tracker_store import InMemoryTrackerStore
from app.dialogue.flow_executor import FlowExecutor
from datetime import datetime, timezone

from typing import Any

from app.dialogue.prompt_builder import PromptBuilder
from app.dialogue.llm_generator import LLMCommandGenerator
from app.dialogue.command_parser import CommandParser
from app.dialogue.command_processor import CommandProcessor

def now_iso():
    return datetime.now(timezone.utc).isoformat()


class Agent:
    def __init__(self, tracker_store: InMemoryTrackerStore, flows: dict[str, any] | None = None):
        self.tracker_store = tracker_store
        self.flows = flows or {}
        self.flow_executor = FlowExecutor()

        self.prompt_builder = PromptBuilder()
        self.llm_generator = LLMCommandGenerator()
        self.command_parser = CommandParser()
        self.command_processor = CommandProcessor()

    def handle_message(self, message: str, sender_id: str):
        tracker = self.tracker_store.get_or_create(sender_id)
        text = message.strip()

        tracker["latest_message"] = text
        tracker["events"].append({"event": "user", "text": text, "timestamp": now_iso()})


        llm_ok = self._try_llm_commands(tracker, text)
        #understand:识别并启动 apply_postsale
        if not llm_ok and tracker.get("active_flow") is None:
        
            if ("退货" in text or "售后" in text):
                tracker["active_flow"] = "apply_postsale"
                tracker["flow_step_index"] = 0
                tracker["slot_to_collect"] = None
                tracker.setdefault("slots", {})
            elif ("物流" in text or "快递" in text):
                tracker["active_flow"] = "query_logistics"
                tracker["flow_step_index"] = 0
                tracker["slot_to_collect"] = None
                tracker.setdefault("slots", {})

        #collect: 如果slot_to_collect不为空，则收集slot
        if tracker.get("slot_to_collect") is not None and tracker.get("active_flow") is not None:
            tracker["slots"][tracker["slot_to_collect"]] = text
            tracker["slot_to_collect"] = None

        
        #policy: 如果有activate_flow, 走flow_executor 决策
        next_action = "action_echo"
        flow_def = None

        active_flow = tracker.get("active_flow")
        if active_flow:
            flow_def = self.flows.get(active_flow)
            if flow_def is None:
                next_action = "action_default_fallback"
            else:
                decision = self.flow_executor.decide_next_action(tracker, flow_def)
                next_action = decision.get("next_action") or "action_default_fallback"

                # 没有end step时，当推进到flow末尾就认为结束
                if tracker.get("flow_step_index", 0) >= len(flow_def.get("steps", []) or []):
                    tracker["active_flow"] = None
                    tracker["slot_to_collect"] = None
                    tracker["flow_step_index"] = 0
        
        ## action：根据 next_action 生成文本（本阶段只覆盖你需要的三种）
        if next_action == "action_ask_order_id":
            tracker["latest_action_name"] = "action_ask_order_id"
            tracker["slot_to_collect"] = "order_id"  # 关键：保证下一轮能 collect 到 order_id
            bot_text = "请提供订单号。"
        elif next_action == "action_listen":
            tracker["latest_action_name"] = "action_listen"
            bot_text = "我在等你提供订单号。"
        elif next_action == "action_confirm_postsale":
            tracker["latest_action_name"] = "action_confirm_postsale"
            order_id = tracker.get("slots", {}).get("order_id", "")
            bot_text = f"已收到订单号 {order_id}，正在为你提交售后申请。"
        elif next_action == "action_show_logistics":
            tracker["latest_action_name"] = "action_show_logistics"
            order_id = tracker.get("slots", {}).get("order_id", "")
            bot_text = f"订单{order_id} 当前状态：运输中，预计明日送达。"
        else:
            tracker["latest_action_name"] = next_action
            bot_text = f"已收到：{text}"

        tracker["events"].append({"event": "bot", "text": bot_text, "timestamp": now_iso()})
        self.tracker_store.save(tracker)
        return [{"recipient_id": sender_id, "text": bot_text, "timestamp": now_iso()}]


    def _try_llm_commands(self, tracker: dict[str, Any], text: str) -> bool:  # pyright: ignore[reportUnreachable]
            #只在“该没进入流程”或“正在收集订单号”时尝试LLM（避免每轮都花钱）
            if not self.llm_generator.enabled:
                return False

                
            # 只在“尚未进入任何 flow”时调用 LLM（省钱 + 稳定）
            if tracker.get("active_flow") is not None:
                return False
            
            flow_ids = sorted(self.flows.keys())
            prompt = self.prompt_builder.build(message=text, tracker=tracker, flow_ids=flow_ids)

            
            try:
                raw = self.llm_generator.generate(prompt)
            except Exception as e:
                tracker["events"].append({
                    "event": "llm_error",
                    "text": str(e),
                    "timestamp": now_iso(),
                })
                return False

            tracker["events"].append({
                "event": "llm_raw",
                "text": raw or "",
                "timestamp": now_iso(),
            })

            if not raw:
                tracker["events"].append({
                    "event": "llm_empty",
                    "text": "",
                    "timestamp": now_iso(),
                })
                return False
            
            try:
                cmds = self.command_parser.parse(raw)
            except Exception as e:
                tracker["events"].append({
                    "event": "llm_parse_error",
                    "text": str(e),
                    "timestamp": now_iso(),
                })
                return False
            
            tracker["events"].append({
                "event": "llm_commands",
                "text": str([cmd.__class__.__name__ for cmd in cmds]),
                "timestamp": now_iso(),
            })

            if not cmds:
                tracker["events"].append({
                    "event": "llm_parse_failed",
                    "text": raw[:200],
                    "timestamp": now_iso(),
                })
                return False
            
            self.command_processor.process(cmds, tracker)
            return True