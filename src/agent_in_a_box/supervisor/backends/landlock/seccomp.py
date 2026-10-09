"""A small seccomp filter: which socket families the workload may create.

The network namespace is the primary network boundary: inside it there is
only a loopback interface. This filter is defense in depth for what a
network namespace does not cover. VSOCK sockets reach the hypervisor, and
netlink, packet, and other families expose kernel interfaces. So socket()
and socketpair() are allowed only for AF_UNIX, AF_INET, and AF_INET6, and
io_uring, which could create sockets without calling socket(), is refused.

The program is classic BPF, built by hand: a dozen instructions, checked by
tests instruction by instruction. bubblewrap loads it (--seccomp FD) right
before it starts the workload.
"""

from __future__ import annotations

import platform
import struct
from dataclasses import dataclass

# Classic BPF opcodes used here.
LOAD_WORD = 0x20     # BPF_LD | BPF_W | BPF_ABS: load a 32-bit word of seccomp_data
JUMP_EQUAL = 0x15    # BPF_JMP | BPF_JEQ | BPF_K
JUMP_AT_LEAST = 0x35  # BPF_JMP | BPF_JGE | BPF_K
RETURN = 0x06        # BPF_RET | BPF_K

ALLOW = 0x7FFF0000
KILL_PROCESS = 0x80000000
ERRNO = 0x00050000   # SECCOMP_RET_ERRNO, with the errno in the low 16 bits
ENOSYS = 38
EAFNOSUPPORT = 97

# Offsets into struct seccomp_data.
NR = 0
ARCH = 4
FIRST_ARGUMENT = 16  # low 32 bits of args[0] on a little-endian machine

ALLOWED_FAMILIES = {"AF_UNIX": 1, "AF_INET": 2, "AF_INET6": 10}
IO_URING_SETUP = 425  # the same number on every architecture


@dataclass(frozen=True)
class Architecture:
    audit_arch: int
    socket: int
    socketpair: int
    x32_bit: int | None  # x86-64's x32 syscalls set this bit; refuse them all


ARCHITECTURES = {
    "x86_64": Architecture(0xC000003E, socket=41, socketpair=53, x32_bit=0x40000000),
    "aarch64": Architecture(0xC00000B7, socket=198, socketpair=199, x32_bit=None),
}


def supported_machine() -> str | None:
    machine = platform.machine().lower()
    if machine == "amd64":
        machine = "x86_64"
    if machine == "arm64":
        machine = "aarch64"
    return machine if machine in ARCHITECTURES else None


def instruction(code: int, k: int, jump_true: int = 0, jump_false: int = 0) -> bytes:
    return struct.pack("<HBBI", code, jump_true, jump_false, k)


def program(machine: str) -> list[bytes]:
    """The filter for one architecture. Jumps count instructions to skip."""
    arch = ARCHITECTURES[machine]
    families = list(ALLOWED_FAMILIES.values())
    prog = [
        instruction(LOAD_WORD, ARCH),
        instruction(JUMP_EQUAL, arch.audit_arch, 1, 0),
        instruction(RETURN, KILL_PROCESS),            # a foreign architecture's syscall
        instruction(LOAD_WORD, NR),
    ]
    if arch.x32_bit is not None:
        prog += [instruction(JUMP_AT_LEAST, arch.x32_bit, 0, 1),
                 instruction(RETURN, ERRNO | ENOSYS)]
    prog += [
        instruction(JUMP_EQUAL, IO_URING_SETUP, 0, 1),
        instruction(RETURN, ERRNO | ENOSYS),
        instruction(JUMP_EQUAL, arch.socket, 2, 0),
        instruction(JUMP_EQUAL, arch.socketpair, 1, 0),
        instruction(RETURN, ALLOW),                    # every other syscall
        instruction(LOAD_WORD, FIRST_ARGUMENT),        # socket(family, ...)
    ]
    for position, family in enumerate(families):
        skip_to_allow = len(families) - position
        prog.append(instruction(JUMP_EQUAL, family, skip_to_allow, 0))
    prog += [instruction(RETURN, ERRNO | EAFNOSUPPORT), instruction(RETURN, ALLOW)]
    return prog


def compiled(machine: str) -> bytes:
    """The filter as bubblewrap reads it: an array of struct sock_filter."""
    return b"".join(program(machine))
