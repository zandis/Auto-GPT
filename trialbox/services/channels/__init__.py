"""Channel abstraction (spec v4 §3.4, §9.2; S1-10): channel-relay, the native engine and the channel transports.

``channels.engine: hermes | native`` selects the conversation engine behind the relay; the native engine is the
default and the fallback (OPS-02). v1 ``services/mail_gateway`` is wrapped by ``channels.native.email`` (its move into
this package is an ENG-02 follow-up).
"""
