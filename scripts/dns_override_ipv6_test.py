#!/usr/bin/env python3
"""Test process-local DNS overriding for IPv6 HTTP requests."""

from __future__ import annotations

import argparse
import socket
from contextlib import contextmanager
from typing import Iterator
from urllib.parse import urlparse

import httpx


@contextmanager
def override_ipv6_dns(hostname: str, ipv6_address: str) -> Iterator[None]:
    """Temporarily force socket.getaddrinfo(hostname) to return ipv6_address."""
    original_getaddrinfo = socket.getaddrinfo
    normalized_hostname = hostname.rstrip(".").lower()

    def patched_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        host_text = host.decode("ascii") if isinstance(host, bytes) else str(host)
        if host_text.rstrip(".").lower() != normalized_hostname:
            return original_getaddrinfo(host, port, family, type, proto, flags)

        if family not in (socket.AF_UNSPEC, socket.AF_INET6):
            return []

        socktype = type or socket.SOCK_STREAM
        protocol = proto or socket.IPPROTO_TCP
        return [
            (
                socket.AF_INET6,
                socktype,
                protocol,
                "",
                (ipv6_address, port, 0, 0),
            )
        ]

    socket.getaddrinfo = patched_getaddrinfo
    try:
        yield
    finally:
        socket.getaddrinfo = original_getaddrinfo


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Temporarily override one hostname to one IPv6 address."
    )
    parser.add_argument("--host", required=True, help="Hostname to override.")
    parser.add_argument("--ipv6", required=True, help="IPv6 address to return.")
    parser.add_argument(
        "--url",
        help="URL to request. Defaults to https://<host>/ when omitted.",
    )
    parser.add_argument("--timeout", type=float, default=10.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    url = args.url or f"https://{args.host}/"
    parsed = urlparse(url)
    if parsed.hostname and parsed.hostname.rstrip(".").lower() != args.host.lower():
        raise SystemExit("--url host must match --host so TLS SNI stays consistent")

    print(f"host: {args.host}")
    print(f"forced_ipv6: {args.ipv6}")
    print(f"url: {url}")

    try:
        original = socket.getaddrinfo(
            args.host,
            parsed.port or (443 if parsed.scheme == "https" else 80),
            family=socket.AF_INET6,
            type=socket.SOCK_STREAM,
        )
        print(f"original_aaaa_count: {len(original)}")
    except socket.gaierror as exc:
        print(f"original_aaaa_error: {exc}")

    with override_ipv6_dns(args.host, args.ipv6):
        overridden = socket.getaddrinfo(
            args.host,
            parsed.port or (443 if parsed.scheme == "https" else 80),
            family=socket.AF_INET6,
            type=socket.SOCK_STREAM,
        )
        print(f"overridden_getaddrinfo: {overridden[0]}")

        transport = httpx.HTTPTransport(local_address="::")
        with httpx.Client(transport=transport, follow_redirects=True) as client:
            response = client.get(url, timeout=args.timeout)
            print(f"status_code: {response.status_code}")
            print(f"final_url: {response.url}")
            print(f"server: {response.headers.get('server', '')}")


if __name__ == "__main__":
    main()
