#!/usr/bin/env python3
import re
from typing import Optional, NamedTuple, Generator, Literal, cast
from enum import Enum


type REGDST_t = Literal['M', 'D', 'MD', 'A', 'AM', 'AD', 'AMD']
type REG_t = Literal['M', 'D', 'A']
type ONEOP_t = REG_t | Literal['0', '1', '-1']

REGDSTS = ('M', 'D', 'MD', 'A', 'AM', 'AD', 'AMD')
REGARGS = ('M', 'D', 'A')

def sliding_substring(string: str, n: int = 2) -> Generator[str, None, None]:
    if len(string) <= n:
        yield string
        return
    for i in range(len(string) - n + 1):
        yield string[i:i+n]

class ParserLine(NamedTuple):
    line: str
    lineno_parsed: int
    lineno_original: int

class ParserError(Exception):
    def __init__(self, src: str, msg: str, lineno: int) -> None:
        self.src = src
        self.msg = msg
        self.lineno = lineno

class OutOfBoundsConstantError(Exception):
    pass

class BadDestination(Exception):
    pass

class BadArgument(Exception):
    pass

class WrongTypeError(Exception):
    def __init__(self, msg: str):
        self.msg = msg


def convert_constant(constant: str) -> Optional[int]:
    if not constant.isascii():
        return None
    if not constant.isdigit() and (constant[0] != '-' or not constant[1:].isdigit()):
        return None
    int_constant = int(constant)
    if int_constant > 32767 or int_constant < -32768:
        raise OutOfBoundsConstantError
    return int_constant

def convert_address(address: str) -> Optional[tuple[str, str]]:
    if not address.lstrip('*').startswith('@'):
        return None
    location = address.lstrip('*')[1:]
    if not location:
        return None
    dereferences = '\n'.join(['A=M'] * address.index('@'))
    return (location, dereferences)


class DestinationType(Enum):
    REGISTERS = 0
    ADDRESS = 1

class ArgumentType(Enum):
    REGISTER = 0
    ADDRESS = 1
    CONSTANT = 2


class Destination:
    _type: DestinationType
    _registers: Optional[REGDST_t]
    _location: Optional[str]
    _dereferences: Optional[str]

    def __init__(self, dst: str) -> None:
        if dst in REGDSTS:
            self._type = DestinationType.REGISTERS
            self._registers = dst
            self._location = None
            self._dereferences = None
        elif (_dst := convert_address(dst)) is not None:
            self._type = DestinationType.ADDRESS
            self._registers = None
            self._location, self._dereferences = _dst
        else:
            raise BadDestination

    def __repr__(self) -> str:
        if self.is_register():
            return self.registers
        elif self.is_address() and self.dereferences:
            return len(self.dereferences.split('\n'))*'*' + f'@{self.location}'
        else:
            return f'@{self.location}'

    def is_register(self) -> bool:
        return self._type == DestinationType.REGISTERS
    def is_address(self) -> bool:
        return self._type == DestinationType.ADDRESS

    @property
    def type(self) -> DestinationType: return self._type
    
    @property
    def registers(self) -> REGDST_t:
        if self.is_register():
            return cast(REGDST_t, self._registers)
        raise WrongTypeError('Expected a register type.')

    @property
    def location(self) -> str:
        if self.is_address():
            return cast(str, self._location)
        raise WrongTypeError('Expected an address type.')
    
    @property
    def dereferences(self) -> str:
        if self.is_address():
            return cast(str, self._dereferences)
        raise WrongTypeError('Expected an address type.')


class Argument:
    _type: ArgumentType
    _register: Optional[REG_t]
    _location: Optional[str]
    _dereferences: Optional[str]
    _constant: Optional[int]
    
    def is_register(self) -> bool: return self._type == ArgumentType.REGISTER
    def is_address(self) -> bool: return self._type == ArgumentType.ADDRESS
    def is_constant(self) -> bool: return self._type == ArgumentType.CONSTANT
    def is_oneop(self) -> bool:
        return (
            self._type == ArgumentType.REGISTER or (
                self._type == ArgumentType.CONSTANT and
                abs(cast(int, self._constant)) <= 1
            )
        )
    
    def __init__(self, arg: str) -> None:
        if arg in REGARGS:
            self._type = ArgumentType.REGISTER
            self._register = arg
            self._location, self._dereferences = None, None
            self._constant = None
        elif (_arg := convert_address(arg)) is not None:
            self._type = ArgumentType.ADDRESS
            self._register = None
            self._location, self._dereferences = _arg
            self._constant = None
        elif (_iarg := convert_constant(arg)) is not None:
            self._type = ArgumentType.CONSTANT
            self._register = None
            self._location, self._dereferences = None, None
            self._constant = _iarg
        else:
            raise BadArgument

    def __repr__(self) -> str:
        if self.is_register():
            return self.register
        elif self.is_address() and self.dereferences:
            return len(self.dereferences.split('\n'))*'*' + f'@{self.location}'
        elif self.is_address():
            return f'@{self.location}'
        else:
            return str(self.constant)

    @property
    def type(self) -> ArgumentType: return self._type
    
    @property
    def register(self) -> REG_t:
        if self.is_register():
            return cast(REG_t, self._register)
        raise WrongTypeError('Expected a register type.')
    
    @property
    def oneop(self) -> ONEOP_t:
        if self.is_oneop():
            return cast(
                ONEOP_t,
                self._register if self.is_register() else str(self._constant)
            )
        raise WrongTypeError('Expected a register type or -1, 0, 1 constant.')

    @property
    def location(self) -> str:
        if self.is_address():
            return cast(str, self._location)
        raise WrongTypeError('Expected an address type.')
    
    @property
    def dereferences(self) -> str:
        if self.is_address():
            return cast(str, self._dereferences)
        raise WrongTypeError('Expected an address type.')
    
    @property
    def constant(self) -> int:
        if self.is_constant():
            return cast(int, self._constant)
        raise WrongTypeError('Expected a constant type.')


def clean(code: str) -> str:
    code = re.sub(r'^((?:D=D)|(?:A=A)|(?:M=M))$', '', code, flags=re.MULTILINE)
    return re.sub(r'\n+', '\n', code).strip('\n')
