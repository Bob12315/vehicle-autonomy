"""Assertions shared by owned native-motion scenarios; never grant authority."""


def assert_handoff_blocked(runtime):
    def scope():
        a=runtime.authority
        return (runtime._action_id,a.lease,a.authorization_generation,
                a.send_generation,a.system_send,a.action_send)
    before=scope()
    try:
        runtime.authorize_action('forbidden-native-handoff',allow_send=True)
    except RuntimeError as exc:
        if 'stop barrier' not in str(exc):raise
    else:raise AssertionError('unresolved native motion allowed Action handoff')
    if scope()!=before:raise AssertionError('refused handoff mutated Action authorization')
    return dict(passed=True,rejected=True,authority_unchanged=True)
