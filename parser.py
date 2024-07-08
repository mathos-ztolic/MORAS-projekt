#!/usr/bin/env python3
import itertools
import re
from sys import argv, stderr
from typing import Mapping, NamedTuple, Optional, Callable

from macros import *
from utils import *

class Parser:
    _lines: list[ParserLine]
    _labels: dict[str, int]
    _variables: dict[str, int]
    _comment: bool
    _current_variable: int
    filename: str
    output_filename: str
    _block_stack: list[tuple[str, bool]]
    _block_macro_stack: list[tuple[BlockMacro, bool]]
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
    
    # korisnicke varijable ne smiju matchati nijedan od ovih patterna
    RESTRICTIONS = (
        '__aux',

        r'__loop_.+_\d+_start',
        r'__loop_.+_\d+_after',

        r'__halt_\d+',

        r'__if_.+_\d+',
        r'__ifn_.+_\d+',

        r'__endandoperation_\d+',
        r'__endoroperation_\d+',
        r'__endxoroperation_\d+',
        r'__endnotoperation_\d+',
        r'__andcheckfailed_\d+',
        r'__orcheckfailed_\d+',
        r'__xorcheckfailed_\d+',
        r'__xorfirstfalse_\d+',
        r'__notfalse_\d+',

        '__multresult',
        '__multarg1',
        '__multarg2',
        '__multhelper',
        r'__mult_2p\d+_\d+',

        r'__registerisone_\d+',
        r'__registerisnegativeone_\d+',
        r'__enddiv_\d+',
        r'__trueenddiv_\d+',
        '__divresult',
        '__divarg1',
        '__divarg2',
        '__divsign',
        r'__div_2p\d+_\d+',
        r'__nonnegativearg1_\d+',

        '__powaux',
        '__powresult',
        '__powbase',
        '__powexponent',
        r'__exponentiseven',
        r'__powstart_\d+',
        r'__powend_\d+',
        r'__powbaseisnegativeone_\d+',
        r'__powcheckexponent_\d+',
    )

    BLOCK_MACROS = {'IF': IF, 'IFN': IFN, 'LOOP': LOOP}
    SIMPLE_MACROS = {
        'LD': LD, 'ADD': ADD, 'SUB': SUB, 'SWAP': SWAP,
        'AND': AND, 'OR': OR, 'XOR': XOR, 'NOT': NOT,
        'HALT': HALT, 'MULT': MULT, 'DIV': DIV, 'POW': POW
    }

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
            self.output_filename = str(output_filename)

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
                raise ParserError('PL', "Unbalanced comment delimiter.", o)
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
            raise ParserError('SYM', f'Invalid label: `{label}\'', o)
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
            raise ParserError('COM', error_message, o)
        
        return f"111{op}{dest}{jmp}"

    def _check_restriction(self, line: str, p: int, o: int) -> str:
        if line[0] not in '(@':
            return line
        for r in self.RESTRICTIONS:
            if re.match(r, line[1:-1]):
                raise ParserError('MCR',
                                   f"Zabranjeno ime simbola.",
                                   o)
        return line

    def _check_macro_syntax(self, line: str, p: int, o: int) -> str:
        if line[0] != '$':
            return line

        if (
            line[1:].split('(')[0] not in self.SIMPLE_MACROS
            and line[1:].split('(')[0] not in self.BLOCK_MACROS
        ):
            raise ParserError(
                'MCR',
                f"Nepoznat makro {line[1:].split('(')[0]}.",
                o
            )

        if (
            line.count('(') != 1 or
            line.count(')') != 1 or

            line.split(')')[1].count('{') > 1 or
            line.split(')')[1].count('}') > 1 or

            (line.split(')')[1].count('{') == 0 and
             line.split(')')[1].count('}') == 1) or

            (not line.endswith(')') and
             not line.endswith('){') and
             not line.endswith('){}'))
        ):
            raise ParserError(
                'MCR',
                'Nevalidna makro sintaksa.',
                o
            )

        if (
            line[1:].split(')')[1] and
            line[1:].split('(')[0] in self.SIMPLE_MACROS
        ):
            raise ParserError(
                'MCR',
                'Nevalidna makro sintaksa. Blok na simple makru.',
                o
            )


        macro, sarguments, _ = re.split('[()]', line[1:])
        if line.endswith('()'):
            arguments = []
        else:
            arguments = [arg.strip() for arg in sarguments.split(',')]
        if (
            (
                macro in self.SIMPLE_MACROS and
                (ec := self.SIMPLE_MACROS[macro].arg_count) != len(arguments)
            ) or (
                macro in self.BLOCK_MACROS and
                (ec := self.BLOCK_MACROS[macro].arg_count) != len(arguments)

            )
        ):
            raise ParserError(
                'MCR',
                f'Krivi broj argumenata za macro {macro}: got '
                f'{len(arguments)}, expected {ec}',
                o,
            )
        
        for arg in arguments:
            for r in self.RESTRICTIONS:
                if arg.startswith(r):
                    raise ParserError('MCR',
                                       f'Simbol ne smije pocinjati s {r}',
                                       o)
        return line

    def _check_balanced_blocks(self, line: str, p: int, o: int) -> str:
        if not line.startswith('$') and line not in ('{', '}', '{}'):
            # allow omitting {} for single lines
            if self._block_stack and not self._block_stack[-1][1]:
                self._block_stack.pop()
            return line
        if line in ('{', '}', '{}') and len(self._block_stack) == 0:
            raise ParserError('MCR', 'Nebalansirani makro blokovi.', o)
        if line in ('{', '{}') and self._block_stack[-1][1]:
            raise ParserError('MCR', 'Nebalansirani makro blokovi.', o)
        if line == '}' and not self._block_stack[-1][1]:
            raise ParserError('MCR', 'Nebalansirani makro blokovi.', o)

        if line == '{':
            self._block_stack.append((self._block_stack.pop()[0], True))
            return line
        if line == '}':
            self._block_stack.pop()
            return line
        # no need to add anything to the stack
        if line.endswith('{}'):
            return line

        macro = line[1:].split('(')[0]
        is_open = line.endswith('{')

        if macro in self.BLOCK_MACROS:
            self._block_stack.append((macro, is_open))
        elif macro in self.SIMPLE_MACROS:
            # allow omitting {} for single lines
            if self._block_stack and not self._block_stack[-1][1]:
                self._block_stack.pop()

        return line

    def _parse_macro(self, line: str, p: int, o: int) -> str:
        if not line.startswith('$') and line not in ('{', '}', '{}'):
            cl = ""
            if self._block_macro_stack and not self._block_macro_stack[-1][1]:
                cl = self._block_macro_stack[-1][0].close(line, p, o)
                self._block_macro_stack.pop()
            return f"{line}\n{cl}".rstrip('\n')

        if line == '{':
            self._block_stack.append((self._block_stack.pop()[0], True))
            return self._block_macro_stack[-1][0].open(line, p, o)
        if line == '}':
            popped_macro = self._block_macro_stack.pop()[0]
            return popped_macro.close(line, p, o)
        if line == '{}':
            op = self._block_macro_stack[-1][0].open(line, p, o)
            cl = self._block_macro_stack[-1][0].close(line, p, o)
            self._block_macro_stack.pop()
            return f"{op}\n{cl}".strip('\n')


        macro, sarguments, line_ending = re.split("[()]", line[1:])
        arguments = tuple(arg.strip() for arg in sarguments.split(','))

        simple_macro = self.SIMPLE_MACROS.get(macro, None)
        block_macro = self.BLOCK_MACROS.get(macro, None)

        if simple_macro:
            sm = simple_macro(arguments).run(line, p, o)
            cl = ""
            if self._block_macro_stack and not self._block_macro_stack[-1][1]:
                cl = self._block_macro_stack[-1][0].close(line, p, o)
                self._block_macro_stack.pop()
            return f"{sm}\n{cl}".rstrip('\n')
        elif block_macro:
            self._block_macro_stack.append(
                (block_macro(arguments, p, o), line_ending == '{')
            )
            if line_ending == '{':
                return self._block_macro_stack[-1][0].open(line, p, o)
            elif line_ending == '{}':
                op = self._block_macro_stack[-1][0].open(line, p, o)
                cl = self._block_macro_stack[-1][0].close(line, p, o)
                self._block_macro_stack.pop()
                return f"{op}\n{cl}".strip('\n')
            return ""
        assert False


    def _parse_macros(self) -> None:
        self._iter_lines(self._check_restriction)
        self._iter_lines(self._check_macro_syntax)
        self._iter_lines(self._check_balanced_blocks)
        if self._block_stack:
            raise ParserError('MCR', 'Nebalansirani makro blokovi.', -1)
        while True:
            self._iter_lines(self._parse_macro)
            if all(not line.line.startswith('$') for line in self._lines):
                break


    def _full_parse(self) -> None:
        try:
            self._parse_lines()
            self._parse_macros()
            if self.expand_macros_only:
                return
            self._parse_symbols()
            self._parse_commands()
        except ParserError as error:
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
