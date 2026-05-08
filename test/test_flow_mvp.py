from app.dialogue.command_parser import CommandParser
from app.dialogue.command_processor import CommandProcessor
from app.dialogue.commands import StartFlowCommand, SetSlotCommand


def test_parse_start_flow():
    parser = CommandParser()
    text = '{"commands":[{"type":"start_flow","flow":"apply_postsale"}]}'

    cmds = parser.parse(text)

    assert len(cmds) == 1
    assert isinstance(cmds[0], StartFlowCommand)
    assert cmds[0].flow == "apply_postsale"


def test_parse_set_slot():
    parser = CommandParser()
    text = '{"commands":[{"type":"set_slot","name":"order_id","value":"A12345678"}]}'

    cmds = parser.parse(text)

    assert len(cmds) == 1
    assert isinstance(cmds[0], SetSlotCommand)
    assert cmds[0].name == "order_id"
    assert cmds[0].value == "A12345678"


def test_parse_with_extra_text_should_still_work():
    parser = CommandParser()
    text = '好的，给你结果：{"commands":[{"type":"start_flow","flow":"query_logistics"}]}谢谢'

    cmds = parser.parse(text)

    assert len(cmds) == 1
    assert isinstance(cmds[0], StartFlowCommand)
    assert cmds[0].flow == "query_logistics"


def test_processor_applies_commands_to_tracker():
    tracker = {
        "active_flow": None,
        "flow_step_index": 999,
        "slot_to_collect": "order_id",
        "slots": {},
    }

    processor = CommandProcessor()
    commands = [
        StartFlowCommand(flow="apply_postsale"),
        SetSlotCommand(name="order_id", value="A12345678"),
    ]

    processor.process(commands, tracker)

    assert tracker["active_flow"] == "apply_postsale"
    assert tracker["flow_step_index"] == 0
    assert tracker["slot_to_collect"] is None
    assert tracker["slots"]["order_id"] == "A12345678"