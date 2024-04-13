#!/usr/bin/env python3
import itertools
import re
from sys import argv, stderr
from typing import Mapping, NamedTuple, Optional, Callable, Generator


class ParserLine(NamedTuple):
    line: str
    lineno_parsed: int
    lineno_original: int

class SimpleMacro(NamedTuple):

    arguments: tuple[str, ...]
    
    def run(self, line: str, p: int, o: int) -> str:
        raise NotImplementedError

class BlockMacro(NamedTuple):

    arguments: tuple[str, ...]
    open_p: int  # p from when the block was opened
    open_o: int  # o from when the block was opened
    
    def open(self, line: str, p: int, o: int) -> str:
        raise NotImplementedError
    
    def close(self, line: str, p: int, o: int) -> str:
        raise NotImplementedError

class MVMacro(SimpleMacro):

    def run(self, line: str, p: int, o: int) -> str:
        A = self.arguments[0]
        B = self.arguments[1]
        return f'@{A}\nD=M\n@{B}\nM=D'

class SETMacro(SimpleMacro):

    def run(self, line: str, p: int, o: int) -> str:
        A = self.arguments[0]
        B = self.arguments[1]

        try:
            B = int(B)
        except ValueError:
            raise ParserError(
                'MCR',
                'Nevalidan SET Macro. Drugi argument mora biti broj. '
                'Mozda ste htjeli MV?',
                o,
            )

        if B in (-1, 0, 1):
            return f'@{A}\nM={B}'

        return (f'@{B}\nD=A\n@{A}\nM=D'
                if B >= 0 else
                f'@{~B}\nD=A\nD=!D\n@{A}\nM=D')

class HALTMacro(SimpleMacro):

    def run(self, line: str, p: int, o: int) -> str:
        return f'(__halt_{o})\n@__halt_{o}\n0;JMP'

class SWPMacro(SimpleMacro):

    def run(self, line: str, p: int, o: int) -> str:
        A = self.arguments[0]
        B = self.arguments[1]
        A_ptr_count = len([*itertools.takewhile(lambda c: c == '*', A)])
        B_ptr_count = len([*itertools.takewhile(lambda c: c == '*', B)])
        A_real = A[A_ptr_count:]
        B_real = B[B_ptr_count:]
        if not A_real or not B_real:
            raise ParsingError('MCR', "Nevalidan SWP macro.", o)
        A_str = 'A=M\n'*A_ptr_count
        B_str = 'A=M\n'*B_ptr_count
        return (f'@{A_real}\n{A_str}D=M\n@__aux\nM=D\n@{B_real}\n{B_str}D=M\n'
                f'@{A_real}\n{A_str}M=D\n@__aux\nD=M\n@{B_real}\n{B_str}M=D')

class SUMMacro(SimpleMacro):

    def run(self, line: str, p: int, o: int) -> str:
        A = self.arguments[0]
        B = self.arguments[1]
        D = self.arguments[2]
        return f'@{A}\nD=M\n@{B}\nD=D+M\n@{D}\nM=D'

class SUBMacro(SimpleMacro):

    def run(self, line: str, p: int, o: int) -> str:
        A = self.arguments[0]
        B = self.arguments[1]
        D = self.arguments[2]
        return f'@{A}\nD=M\n@{B}\nD=D-M\n@{D}\nM=D'

class DOWHILEMacro(BlockMacro):
    
    def open(self, line: str, p: int, o: int) -> str:
        A = self.arguments[0]
        return f'(__while_{A}_{o})'

    def close(self, line: str, p: int, o: int) -> str:
        A = self.arguments[0]
        var = f'__while_{A}_{self.open_o}'
        return f'@{A}\nD=M\n@__while_{A}_{self.open_o}\nD;JNE'

class WHILEMacro(BlockMacro):
    
    def open(self, line: str, p: int, o: int) -> str:
        A = self.arguments[0]
        var = f'__while_{A}_{o}'
        var_after = f'__while_{A}_{o}_after'
        return f"@{A}\nD=M\n@{var_after}\nD;JEQ\n({var})"

    def close(self, line: str, p: int, o: int) -> str:
        A = self.arguments[0]
        var = f'__while_{A}_{self.open_o}'
        var_after = f'__while_{A}_{self.open_o}_after'
        return f'@{A}\nD=M\n@{var}\nD;JNE\n({var_after})'


class ParsingError(Exception):
    def __init__(self, src: str, msg: str, lineno: int):
        self.src = src
        self.msg = msg
        self.lineno = lineno

def sliding_substring(string: str, n: int = 2) -> Generator[str, None, None]:
    if len(string) <= n:
        yield string
        return
    for i in range(len(string) - n + 1):
        yield string[i:i+n]

class Parser:
    _lines: list[ParserLine]
    _labels: dict[str, int]
    _variables: dict[str, int]
    _comment: bool
    _current_variable: int
    filename: str
    output_filename: str
    _block_stack: list[str]
    _block_macro_stack: list[BlockMacro]
    expand_macros_only: bool
    
    OPERATIONS = {"0": "0101010", "1": "0111111", "-1": "0111010",
                  "D": "0001100", "A": "0110000", "!D": "0001101",
                  "!A": "0110001", "-D": "0001111", "-A": "0110011",
                  "D+1": "0011111", "A+1": "0110111", "D-1": "0001110",
                  "A-1": "0110010", "D+A": "0000010", "A+D": "0000010",
                  "D-A": "0010011", "A-D": "0000111", "D&A": "0000000",
                  "A&D": "0000000", "D|A": "0010101", "A|D": "0010101",
                  "M": "1110000", "!M": "1110001", "-M": "1110011",
                  "M+1": "1110111", "M-1": "1110010", "D+M": "1000010",
                  "M+D": "1000010", "D-M": "1010011", "M-D": "1000111",
                  "D&M": "1000000", "M&D": "1000000", "D|M": "1010101",
                  "M|D": "1010101"}

    JUMPS = {"" : "000", "JGT": "001", "JEQ": "010", "JGE": "011", 
             "JLT": "100", "JNE": "101", "JLE": "110", "JMP": "111"}
    
    DESTINATIONS = {"" : "000", "M" : "001", "D" : "010", "MD" : "011",
                    "A" : "100", "AM" : "101", "AD" : "110", "AMD" : "111"}
    
    # korisnicke varijable ne smiju biti prefiksane ni s cim odavde
    RESTRICTIONS = ('__while', '__aux', '__halt')

    # ne smiju postojati konstante za zatvaranje blokova koje su ujedno
    # i makroi, to ce se provjeravati tijekom inicjalizacije
    # ovo je komplikacija koja dopusta da razlicite konstante zatvaraju
    # razlicite blokove, npr.
    # FOR(A, B, C) -> DONE umjesto samo hardcodeani FOR(A, B, C) -> END 
    BLOCK_OPENING_MACROS = {'WHILE': ('END',), 'DOWHILE': ('END',)}
    BLOCK_CLOSING_CONSTS: dict[str, tuple[str, ...]]  # __init__

    BLOCK_MACROS = {'WHILE': WHILEMacro, 'DOWHILE': DOWHILEMacro}
    SIMPLE_MACROS = {'MV': MVMacro, 'SWP': SWPMacro,
                     'SUM': SUMMacro, 'HALT': HALTMacro,
                     'SET': SETMacro, 'SUB': SUBMacro}
    MACRO_ARGCOUNTS = {'MV': 2, 'SWP': 2, 'SUM': 3, 'SUB': 3,
                       'WHILE': 1, 'DOWHILE': 1, 'HALT': 0, 'SET': 2}

    def __init__(
        self, filename: str, output_filename: Optional[str] = None,
        *, expand_macros_only = False,
    ):

        self.filename = filename
        self.expand_macros_only = expand_macros_only
        
        # Ako datoteka ima .asm ekstenziju, zamijeni je s .hack,
        # a ako ju nema, samo dodaj .hack
        if output_filename is None and not expand_macros_only:
            self.output_filename = re.sub(r'\.asm$', '', filename,
                                          flags=re.IGNORECASE) + '.hack'
        # ako datoteka im .asm ekstenziju, promijeni je u .expanded.asm,
        # a ako ju nema, samo dodaj .asm
        elif output_filename is None and expand_macros_only:
            self.output_filename = re.sub(r'\.asm$', '.expanded', filename,
                                          flags=re.IGNORECASE) + '.asm'
        else:
            self.output_filename = output_filename

        self._lines = []

        self._labels = {'SCREEN': 16384, 'KBD': 24576, 'SP': 0,
                        'LCL': 1, 'ARG': 2, 'THIS': 3, 'THAT': 4}
        for i in range(16):
            self._labels[f"R{i}"] = i

        self._variables = {}

        self._comment = False
        
        # varijable pocinju na 16
        self._current_variable = 16

        self._block_stack = []
        self._block_macro_stack = []
        self.BLOCK_CLOSING_CONSTS = {
            v: tuple(x
                     for x in self.BLOCK_OPENING_MACROS
                     if v in self.BLOCK_OPENING_MACROS[x])
            for k in self.BLOCK_OPENING_MACROS
            for v in self.BLOCK_OPENING_MACROS[k]
        }
        for x in self.BLOCK_OPENING_MACROS:
            if x in self.BLOCK_CLOSING_CONSTS:
                raise ValueError('Nevalidan parser. '
                                 'Blok konstante ne smiju biti makroi.')

    def _iter_lines(self, func: Callable[[str, int, int], str]) -> None:
        newlines = []
        i = 0
        for (line, _, o) in self._lines:
            newline = func(line, i, o)
            if not newline:
                continue
            for l in newline.split('\n'):
                if not newline.strip():
                    continue
                newlines.append(ParserLine(l, i, o))
                i += 1
            
        self._lines = newlines

    def _parse_lines(self) -> None:
        self._iter_lines(self._parse_line)
    
    def _parse_symbols(self) -> None:
        self._iter_lines(self._parse_label)
        self._iter_lines(self._parse_variable)
    
    def _parse_commands(self) -> None:
        self._iter_lines(self._parse_command)

    def _parse_line(self, line: str, p: int, o: int) -> str:
        real_line = ""
        skip_next = False
        # zadnji character nece biti parsan, zato je hack s razmakom
        # potreban u splitlinesu u parse metodi
        for window in sliding_substring(line):
            if skip_next:
                skip_next = False
                continue
            if (
                (not self._comment and window == '/*') or
                (self._comment and window == '*/')
            ):
                skip_next = True
                self._comment = not self._comment
            elif not self._comment and window == '*/':
                raise ParsingError('PL', "Unbalanced comment delimiter.", o)
            elif window == '//' and not self._comment:
                break
            elif not window[0].isspace() and not self._comment:
                real_line += window[0]
        return real_line

    def _parse_label(self, line: str, p: int, o: int) -> str:
        if line[0] != '(':
            return line
        split_label = line[1:].split(')')
        label = split_label[0]
        if len(split_label) != 2 or split_label[1] != '' or label == '':
            raise ParsingError('SYM', f'Invalid label: `{label}\'', o)
        self._labels[label] = p
        return ""

    def _parse_variable(self, line: str, p: int, o: int) -> str:
        if line[0] != "@":
            return line
        l = line[1:]
        if l.isdigit():
            return line
        if l in self._labels:
            return f"@{self._labels[l]}"
        if l not in self._variables:
            self._variables[l] = self._current_variable
            self._current_variable += 1
        return f"@{self._variables[l]}"

    def _parse_command(self, line: str, p: int, o: int) -> str:
        if line[0] == "@":
            num = int(line[1:])
            return "{0:016b}".format(num)
        try:
            dest_str, rest = line.split('=')
        except ValueError:
            dest_str, rest = '', line

        try:
            op_str, jmp_str = rest.split(';')
        except ValueError:
            op_str, jmp_str = rest, ''
        
        error_message = ''  # pyright se zali da je error_message unbound lol
        try:
            error_message = f"Invalid operation: {op_str}"
            op = self.OPERATIONS[op_str]
            error_message = f"Invalid destination: {dest_str}"
            dest = self.DESTINATIONS[dest_str]
            error_message = f"Invalid jump: {jmp_str}"
            jmp = self.JUMPS[jmp_str]
        except KeyError:
            raise ParsingError('COM', error_message, o)
        
        return f"111{op}{dest}{jmp}"

    def _check_restriction(self, line: str, p: int, o: int) -> str:
        if line[0] not in '(@':
            return line
        for r in self.RESTRICTIONS:
            if line[1:].startswith(r):
                raise ParsingError('MCR',
                                   f"Simbol ne smije pocinjati s {r}",
                                   o)
        return line

    def _check_macro_syntax(self, line: str, p: int, o: int) -> str:
        if line[0] != '$':
            return line

        if line[1:] in self.BLOCK_CLOSING_CONSTS:
            return line

        if self.MACRO_ARGCOUNTS.get(line[1:], None) is not None:
            raise ParsingError('MCR', f'Makro {line[1:]} treba zagrade.', o)

        if (
            line.count('(') != 1 or
            line.count(')') != 1 or
            not line.endswith(')')
        ):
            raise ParsingError('MCR', 'Nevalidna makro sintaksa.', o)

        macro, sarguments = line[1:-1].split('(')
        if macro not in self.MACRO_ARGCOUNTS:
            raise ParsingError('MCR', f'Nepoznat makro: {macro}', o)
        if line.endswith('()'):
            arguments = []
        else:
            arguments = [arg.strip() for arg in sarguments.split(',')]
        if self.MACRO_ARGCOUNTS[macro] != len(arguments):
            raise ParsingError(
                'MCR',
                f'Krivi broj argumenata za macro {macro}: got '
                f'{len(arguments)}, expected {self.MACRO_ARGCOUNTS[macro]}',
                o,
            )
        
        for arg in arguments:
            for r in self.RESTRICTIONS:
                if arg.startswith(r):
                    raise ParsingError('MCR',
                                       f'Simbol ne smije pocinjati s {r}',
                                       o)
        return line

    def _check_balanced_blocks(self, line: str, p: int, o: int) -> str:
        if not line.startswith('$'):
            return line
        macro = line[1:].split('(')[0]
        if macro in self.BLOCK_OPENING_MACROS:
            self._block_stack.append(macro)
        elif macro in self.BLOCK_CLOSING_CONSTS:
            if len(self._block_stack) == 0:
                raise ParsingError('MCR', 'Nebalansirani makro blokovi.', o)
            if macro not in self.BLOCK_OPENING_MACROS[self._block_stack[-1]]:
                raise ParsingError('MCR', 'Kriva makro closing konstanta.', o)
            self._block_stack.pop()
        return line

    def _parse_macro(self, line: str, p: int, o: int) -> str:
        if not line.startswith('$'):
            return line
        macro = ''
        arguments: tuple[str, ...] = ()
        if line[1:] not in self.BLOCK_CLOSING_CONSTS:
            macro, sarguments = line[1:-1].split('(')
            arguments = tuple(arg.strip() for arg in sarguments.split(','))

        simple_macro = self.SIMPLE_MACROS.get(macro, None)
        block_macro = self.BLOCK_MACROS.get(macro, None)

        if simple_macro:
            return simple_macro(arguments).run(line, p, o)
        elif block_macro:
            self._block_macro_stack.append(block_macro(arguments, p, o))
            return self._block_macro_stack[-1].open(line, p, o)
        else:
            fmacro = self._block_macro_stack.pop()
            return fmacro.close(line, p, o)


    def _parse_macros(self) -> None:
        self._iter_lines(self._check_restriction)
        self._iter_lines(self._check_macro_syntax)
        self._iter_lines(self._check_balanced_blocks)
        if self._block_stack:
            raise ParsingError('MCR', 'Nebalansirani makro blokovi.', -1)
        self._iter_lines(self._parse_macro)


    def _full_parse(self) -> None:
        try:
            self._parse_lines()
            self._parse_macros()
            if self.expand_macros_only:
                return
            self._parse_symbols()
            self._parse_commands()
        except ParsingError as error:
            if error.lineno != -1:
                print(f"[{error.src},{error.lineno}] {error.msg}", file=stderr)
            else:
                print(f"[{error.src}] {error.msg}", file=stderr)
            exit(1)

    def parse(self) -> None:
        try:
            with open(self.filename) as file:
                text = file.read()
        except OSError as error:
            print(f"[IO] Cannot open `{self.filename}' "
                  f"for reading: {error.strerror}",
                  file=stderr)
            return
        
        for i, line in enumerate([f'{l.strip()} ' for l in text.splitlines()]):
            self._lines.append(ParserLine(line, i, i))

        self._full_parse()
        
        try:
            with open(self.output_filename, 'w') as file:
                file.write('\n'.join(line for (line, _, __) in self._lines))
        except OSError as error:
            print(f"[IO] Cannot open `{self.output_filename}' "
                  f"for writing: {error.strerror}",
                  file=stderr)
            return

if __name__ == "__main__":
    if len(argv) < 2:
        print(f"{argv[0]} [--expand-macros-only] <filename> ...")
        exit(1)
    expandonly = False
    if argv[1] == '--expand-macros-only':
        expandonly = True
        del argv[1]
    if len(argv) < 2:
        print(f"{argv[0]} [--expand-macros-only] <filename> ...")
        exit(1)
    for filename in argv[1:]:
        Parser(filename, expand_macros_only=expandonly).parse()
