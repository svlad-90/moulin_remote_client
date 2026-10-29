from board_tools.serial_console_bridge import filter_input


def test_regular_console_input_passes_through() -> None:
    assert filter_input(b"help\r", False) == (b"help\r", False, False)


def test_picocom_exit_sequence_can_span_reads() -> None:
    assert filter_input(b"command\x01", False) == (b"command", True, False)
    assert filter_input(b"\x18ignored", True) == (b"", False, True)


def test_repeated_escape_sends_one_ctrl_a_to_board() -> None:
    assert filter_input(b"\x01\x01", False) == (b"\x01", False, False)


def test_unknown_escape_sequence_is_forwarded() -> None:
    assert filter_input(b"\x01Z", False) == (b"\x01Z", False, False)
