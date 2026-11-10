"""Docker's embedded DNS (127.0.0.11:53) for the rehearsal: nginx's ``resolver 127.0.0.11`` asks it for ``judge`` and
``verifier`` (the vLLM containers on the ``tb`` network); here they are the stand-ins on 127.0.0.2 and 127.0.0.3.
A minimal A-record responder, standard library only."""

from __future__ import annotations

import socket
import struct

NAMES = {"judge.": "127.0.0.2", "verifier.": "127.0.0.3", "host.docker.internal.": "172.17.0.1"}


def parse_qname(data: bytes, off: int) -> tuple[str, int]:
    labels = []
    while True:
        n = data[off]
        off += 1
        if n == 0:
            break
        labels.append(data[off : off + n].decode())
        off += n
    return ".".join(labels) + ".", off


def main() -> None:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.11", 53))
    print("dns stand-in on 127.0.0.11:53", flush=True)
    while True:
        data, addr = s.recvfrom(512)
        qname, off = parse_qname(data, 12)
        qtype = struct.unpack("!H", data[off : off + 2])[0]
        question = data[12 : off + 4]
        ip = NAMES.get(qname.lower())
        if ip and qtype in (1, 255):
            header = data[:2] + b"\x81\x80" + struct.pack("!HHHH", 1, 1, 0, 0)
            answer = b"\xc0\x0c" + struct.pack("!HHIH", 1, 1, 5, 4) + socket.inet_aton(ip)
            s.sendto(header + question + answer, addr)
        elif ip:  # AAAA and the rest: no record (nginx asks with ipv6=off anyway)
            s.sendto(data[:2] + b"\x81\x80" + struct.pack("!HHHH", 1, 0, 0, 0) + question, addr)
        else:  # NXDOMAIN
            s.sendto(data[:2] + b"\x81\x83" + struct.pack("!HHHH", 1, 0, 0, 0) + question, addr)


if __name__ == "__main__":
    main()
