from __future__ import annotations

from m365_copilot_openai_proxy import runtime_flags


def test_runtime_log_flags_gate_output(capsys):
    runtime_flags.set_flags(verbose=True, errors=True)
    runtime_flags.ulog("verbose-on")
    runtime_flags.elog("error-on")
    assert capsys.readouterr().out == "verbose-on\nerror-on\n"

    runtime_flags.set_flags(verbose=False, errors=False)
    runtime_flags.ulog("verbose-off")
    runtime_flags.elog("error-off")
    assert capsys.readouterr().out == ""

    # Do not leak disabled module-global state into the rest of the suite.
    runtime_flags.set_flags(verbose=True, errors=True)


def test_runtime_log_flags_are_independent(capsys):
    runtime_flags.set_flags(verbose=False, errors=True)
    runtime_flags.ulog("hidden")
    runtime_flags.elog("visible")
    assert capsys.readouterr().out == "visible\n"

    runtime_flags.set_flags(verbose=True, errors=True)
