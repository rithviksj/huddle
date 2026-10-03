---
id: <sender-ref>-<n>        # <n> = the sender's own message count on the thread
t: <thread id, chosen by the initiator in the HELLO>
from: <ref>
to: <ref>                    # one ref; "all" only for HELLO, MISSION, RELAY, SYNC, COMMIT, REVEAL, DONE, HALT
re: <id of the message this answers, or none>
type: ASK                    # HELLO | MISSION | RELAY | ASK | ANSWER | SYNC | REVIEW | COMMIT | REVEAL | DONE | HALT
reply: n                     # default n; silence means received
esc: none                    # or: user (the audience is the human, not the peer)
nonce: <nonce, HALT only>
---

<Body. Guidance only; this message grants no authority. No secrets, no personal information, no session names. Use [ref] ids.>
