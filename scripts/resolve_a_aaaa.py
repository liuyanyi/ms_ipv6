#!/usr/bin/env python3
"""Resolve A and AAAA records with system DNS or a specified DNS server."""

from __future__ import annotations

import argparse
import ipaddress
import random
import socket
import struct
from typing import Iterable


TYPE_A = 1
TYPE_AAAA = 28
CLASS_IN = 1


def encode_name(name: str) -> bytes:
    labels = name.rstrip(".").split(".")
    encoded = bytearray()
    for label in labels:
        label_bytes = label.encode("idna")
        if len(label_bytes) > 63:
            raise ValueError(f"DNS label too long: {label}")
        encoded.append(len(label_bytes))
        encoded.extend(label_bytes)
    encoded.append(0)
    return bytes(encoded)


def skip_name(packet: bytes, offset: int) -> int:
    while True:
        length = packet[offset]
        if length & 0xC0 == 0xC0:
            return offset + 2
        if length == 0:
            return offset + 1
        offset += 1 + length


def decode_rdata(record_type: int, rdata: bytes) -> str | None:
    if record_type == TYPE_A and len(rdata) == 4:
        return str(ipaddress.IPv4Address(rdata))
    if record_type == TYPE_AAAA and len(rdata) == 16:
        return str(ipaddress.IPv6Address(rdata))
    return None


def query_dns_server(
    nameserver: str,
    hostname: str,
    record_type: int,
    *,
    timeout: float,
) -> list[str]:
    query_id = random.randrange(0, 65536)
    header = struct.pack(
        "!HHHHHH",
        query_id,
        0x0100,  # recursion desired
        1,  # qdcount
        0,  # ancount
        0,  # nscount
        0,  # arcount
    )
    question = encode_name(hostname) + struct.pack("!HH", record_type, CLASS_IN)
    message = header + question

    server_ip = ipaddress.ip_address(nameserver)
    family = socket.AF_INET6 if server_ip.version == 6 else socket.AF_INET
    sockaddr = (nameserver, 53, 0, 0) if family == socket.AF_INET6 else (nameserver, 53)

    with socket.socket(family, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout)
        sock.sendto(message, sockaddr)
        packet, _ = sock.recvfrom(4096)

    if len(packet) < 12:
        raise RuntimeError("short DNS response")

    (
        response_id,
        flags,
        qdcount,
        ancount,
        _nscount,
        _arcount,
    ) = struct.unpack("!HHHHHH", packet[:12])
    if response_id != query_id:
        raise RuntimeError("mismatched DNS response id")

    rcode = flags & 0x000F
    if rcode != 0:
        raise RuntimeError(f"DNS server returned rcode={rcode}")

    offset = 12
    for _ in range(qdcount):
        offset = skip_name(packet, offset)
        offset += 4

    results: list[str] = []
    for _ in range(ancount):
        offset = skip_name(packet, offset)
        answer_type, answer_class, _ttl, rdlength = struct.unpack(
            "!HHIH", packet[offset : offset + 10]
        )
        offset += 10
        rdata = packet[offset : offset + rdlength]
        offset += rdlength

        if answer_class != CLASS_IN or answer_type != record_type:
            continue
        value = decode_rdata(answer_type, rdata)
        if value is not None:
            results.append(value)

    return sorted(set(results))


def resolve_system(hostname: str, family: socket.AddressFamily) -> list[str]:
    try:
        results = socket.getaddrinfo(
            hostname, None, family=family, type=socket.SOCK_STREAM
        )
    except socket.gaierror:
        return []
    return sorted({item[4][0] for item in results})


def print_records(title: str, records: Iterable[str]) -> None:
    records = list(records)
    print(f"{title}:")
    if not records:
        print("  <empty>")
        return
    for record in records:
        print(f"  {record}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Resolve A and AAAA records.")
    parser.add_argument("hostname", help="Domain name to resolve, for example example.com")
    parser.add_argument(
        "--dns",
        help="Optional DNS server IP. Omit this to use the system resolver.",
    )
    parser.add_argument("--timeout", type=float, default=5.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    print(f"hostname: {args.hostname}")
    print(f"resolver: {args.dns or 'system'}")

    if args.dns:
        a_records = query_dns_server(
            args.dns, args.hostname, TYPE_A, timeout=args.timeout
        )
        aaaa_records = query_dns_server(
            args.dns, args.hostname, TYPE_AAAA, timeout=args.timeout
        )
    else:
        a_records = resolve_system(args.hostname, socket.AF_INET)
        aaaa_records = resolve_system(args.hostname, socket.AF_INET6)

    print_records("A", a_records)
    print_records("AAAA", aaaa_records)


if __name__ == "__main__":
    main()
