#!/usr/bin/env python3
from typing import ClassVar, Literal
from utils import *


class SimpleMacro:

    arguments: tuple[str, ...]
    arg_count: ClassVar[int]

    def __init__(self, arguments):
        self.arguments = arguments

    def run(self, line: str, p: int, o: int) -> str:
        raise NotImplementedError

class BlockMacro:

    arguments: tuple[str, ...]
    open_p: int  # p from when the block was opened
    open_o: int  # o from when the block was opened
    arg_count: ClassVar[int]
    
    def __init__(self, arguments, open_p, open_o) -> None:
        self.arguments = arguments
        self.open_p = open_p
        self.open_o = open_o
    
    def open(self, line: str, p: int, o: int) -> str:
        raise NotImplementedError
    
    def close(self, line: str, p: int, o: int) -> str:
        raise NotImplementedError

class LD(SimpleMacro):
    arg_count = 2
    def run(self, line: str, p: int, o: int) -> str:
        _SRC = self.arguments[1]
        try:
            DST = Destination(self.arguments[0])
            SRC = Argument(_SRC)
        except BadDestination:
            raise ParserError(
                'MCR',
                "[LD] Destinacija mora biti jedan ili više registara,"
                "ili adresa.",
                o
            )
        except BadArgument:
            raise ParserError(
                'MCR',
                "[OR] Argument mora biti registar, konstanta, ili adresa.",
                o
            )
        except OutOfBoundsConstantError:
            raise ParserError(
                'MCR', "[OR] Konstanta mora biti u [-32768, 32767].", o
            )

        # $LD(AD, M) -> AD=M, $LD(M, 1) -> M=1
        if DST.is_register() and SRC.is_oneop():
            return clean(f"{DST.registers}={SRC.oneop}")
        
        # $LD(@54, D), $LD(**@54, D)
        # ovo *NE* prezervira stanje A registra
        # ako želim prezervirati A, to zahtijeva da prvo spremim
        # lokaciju A negdje drugdje, što zahtijeva da je stavim u D
        # prije A instrukcije, što pogazi bilo koju vrijednost koja
        # je bila u D, mogu ili prezervirati stanje A xili stanje D,
        # ne oboje, u ovom slučaju moram koristiti stanje D, tako da
        # njega prezerviram umjesto A
        if DST.is_address() and SRC.is_register() and SRC.register == 'D':
            return clean(f"@{DST.location}\n{DST.dereferences}\nM=D")

        # sve ostalo prezervira originalno stanje A registra, osim ako
        # ga sama instrukcija ne mijenja
        # (e.g. $LD(A, 5) *NE* prezervira stanje A registra)
        
        save_address = "D=A\n@__aux\nAM=D"
        
        if SRC.is_oneop():
            load_value = f"D={SRC.oneop}"
        elif SRC.is_constant():
            load_value = (f"@{SRC.constant}\nD=A" if
                          SRC.constant >= 0 else
                          f"@{~SRC.constant}\nD=!A")
        else:
            load_value = f"@{SRC.location}\n{SRC.dereferences}\nD=M"
        
        restore_address = "@__aux\nA=M"

        if DST.is_register():
            set_destination = f"{DST.registers}=D"
            return clean(f"{save_address}\n"
                         f"{load_value}\n"
                         f"{restore_address}\n"
                         f"{set_destination}")
        else:
            set_destination = f"@{DST.location}\n{DST.dereferences}\nM=D"
            return clean(f"{save_address}\n"
                         f"{load_value}\n"
                         f"{set_destination}\n"
                         f"{restore_address}")


class ADD(SimpleMacro):
    arg_count = 3

    SIMPLE_OPS: dict[tuple[str, str], str] = {
        ('0', '0'): '?=0',
        ('0', '1'): '?=1',
        ('0', '-1'): '?=-1',
        ('-1', '1'): '?=0',
        ('1', '1'): 'D=1\n?=D+1',
        ('-1', '-1'): 'D=-1\n?=D-1',

        ('D', '-1'): '?=D-1',
        ('A', '-1'): '?=A-1',
        ('M', '-1'): '?=M-1',
        ('D',  '0'): '?=D',
        ('A',  '0'): '?=A',
        ('M',  '0'): '?=M',
        ('D',  '1'): '?=D+1',
        ('A',  '1'): '?=A+1',
        ('M',  '1'): '?=M+1',

        ('A', 'D'): '?=A+D',
        ('M', 'D'): '?=M+D',
        
        ('A', 'A'): 'D=A\n?=A+D',
        ('M', 'M'): 'D=M\n?=D+M',
        ('A', 'M'): 'D=A\n?=D+M',
        
        ('D', 'D'): ''  # special case
    }
    
    DD_special_case: dict[str, str] = {
        'A':   "A=D\nA=A+D",
        'D':   "A=D\nD=A+D",  # ne prezervira A registar
        'M':   "M=D\nM=M+D",
        'AD':  "A=D\nA=A+D\nD=A",
        'MD':  "M=D\nM=M+D\nD=M",
        'AM':  "M=D\nM=M+D\nA=M",
        'AMD': "M=D\nM=M+D\nAD=M",
    }

    def run(self, line: str, p: int, o: int) -> str:

        _ARG1 = self.arguments[1]
        _ARG2 = self.arguments[2]
        try:
            DST = Destination(self.arguments[0])
            ARG1 = Argument(_ARG1)
            ARG2 = Argument(_ARG2)
        except BadDestination:
            raise ParserError(
                'MCR',
                "[OR] Destinacija mora biti jedan ili više registara,"
                "ili adresa.",
                o
            )
        except BadArgument:
            raise ParserError(
                'MCR',
                "[OR] Argument mora biti registar, konstanta, ili adresa.",
                o
            )
        except OutOfBoundsConstantError:
            raise ParserError(
                'MCR', "[OR] Konstanta mora biti u [-32768, 32767].", o
            )

        simple_op = (
            (_ARG1, _ARG2) if (_ARG1, _ARG2) in self.SIMPLE_OPS else
            (_ARG2, _ARG1) if (_ARG2, _ARG1) in self.SIMPLE_OPS else
            None
        )

        # oneop (registar ili -1, 0, 1) + oneop

        if simple_op == ('D', 'D') and DST.is_register():
            return self.DD_special_case[DST.registers]
        # ne prezervira A registar
        elif simple_op == ('D', 'D') and DST.is_address():
            return f"@{DST.location}\n{DST.dereferences}\nM=D\nM=M+D"

        if DST.is_register() and simple_op:
            set_destination = self.SIMPLE_OPS[simple_op]
            set_destination = set_destination.replace('?', DST.registers)
            return clean(set_destination)
        elif DST.is_address() and simple_op and 'D' not in simple_op:
            save_address = "D=A\n@__aux\nAM=D"
            load_value = self.SIMPLE_OPS[simple_op].replace('?', 'D')
            set_destination = f"@{DST.location}\n{DST.dereferences}\nM=D"
            restore_address = "@__aux\nA=M"
            return clean(f"{save_address}\n"
                         f"{load_value}\n"
                         f"{set_destination}\n"
                         f"{restore_address}")
        # ne prezervira A registar
        elif DST.is_address() and simple_op and 'D' in simple_op:
            load_value = self.SIMPLE_OPS[simple_op].replace('?', 'D')
            set_destination = f"@{DST.location}\n{DST.dereferences}\nM=D"
            return clean(f"{load_value}\n{set_destination}")
        
        if (
            (ARG2.is_oneop() and ARG1.is_constant()) or
            (ARG2.is_oneop() and ARG1.is_address()) or
            (ARG2.is_constant() and ARG1.is_address())
        ):
            ARG1, ARG2 = ARG2, ARG1

        preserve_A = True
        preserve_A_with_M = False

        if (
            ARG1.is_register() and ARG1.register == 'D' and
            DST.is_register() and 'M' in DST.registers
        ):
            preserve_A_with_M = True
        elif (ARG1.is_register() and ARG1.register == 'D'):
            preserve_A = False

        if DST.is_register():
            set_destination = f"{DST.registers}=D"
        else:
            set_destination = f"@{DST.location}\n{DST.dereferences}\nM=D"

        
        if ARG1.is_oneop() and ARG2.is_constant():
            compute_value = (
                f"D={ARG1.oneop}\n@{ARG2.constant}\nD=D+A"
                if ARG2.constant > 0 else
                f"D={ARG1.oneop}\n@{~ARG2.constant}\nA=!A\nD=D+A"
            )

        elif ARG1.is_oneop() and ARG2.is_address():
            compute_value = (
                f"D={ARG1.oneop}\n@{ARG2.location}\n{ARG2.dereferences}\nD=D+M"
            )

        elif ARG1.is_constant() and ARG2.is_address():
            load_value1 = (f"@{ARG1.constant}\nD=A"
                           if ARG1.constant >= 0 else
                           f"@{~ARG1.constant}\nA=!A\nD=A")
            load_value2 = f"@{ARG2.location}\n{ARG2.dereferences}D=D+M"
            compute_value = "{load_value1}\n{load_value2}"

        elif ARG1.is_constant() and ARG2.is_constant():
            result = ((ARG1.constant + ARG2.constant + 32768) & 0xffff) - 32768
            compute_value = (f"@{result}\nD=A"
                             if result >= 0 else
                             f"@{~result}\nA=!A\nD=A")

        elif ARG1.is_address() and ARG2.is_address():
            load_value1 = f"@{ARG1.location}\n{ARG1.dereferences}D=M"
            load_value2 = f"@{ARG2.location}\n{ARG2.dereferences}D=D+M"
            compute_value = f"{load_value1}\n{load_value2}"
        else:
            assert False

        restore_address = "@__aux\nA=M"
        if preserve_A_with_M:
            save_address = "M=D\nD=A\n@__aux\nAM=D\nD=M"
            return clean(f"{save_address}\n"
                         f"{compute_value}\n"
                         f"{restore_address}\n"
                         f"{set_destination}")
        elif preserve_A:
            save_address = "D=A\n@__aux\nM=D"
            if DST.is_register():
                return clean(f"{save_address}\n"
                             f"{compute_value}\n"
                             f"{restore_address}\n"
                             f"{set_destination}")
            return clean(f"{save_address}\n"
                         f"{compute_value}\n"
                         f"{set_destination}\n"
                         f"{restore_address}")
        else:
            return clean(f"{compute_value}\n{set_destination}")

class SUB(SimpleMacro):
    arg_count = 3
    SIMPLE_OPS: dict[tuple[str, str], str] = {

        ('0', '0'): '?=0',
        ('1', '1'): '?=0',
        ('-1', '-1'): '?=0',

        ('0', '1'): '?=-1',
        ('1', '0'): '?=1',

        ('0', '-1'): '?=1',
        ('-1', '0'): '?=-1',
        
        ('1', '-1'): 'D=1\n?=D+1',
        ('-1', '1'): 'D=-1\n?=D-1',

        ('D', '-1'): '?=D+1',
        ('-1', 'D'): 'D=-D\n?=D-1',

        ('A', '-1'): '?=A+1',
        ('-1', 'A'): 'D=-A\n?=D-1',

        ('M', '-1'): '?=M+1',
        ('-1', 'M'): 'D=-M\n?=D-1',

        ('D',  '0'): '?=D',
        ('0',  'D'): '?=-D',

        ('A',  '0'): '?=A',
        ('0',  'A'): '?=-A',

        ('M',  '0'): '?=M',
        ('0',  'M'): '?=-M',

        ('D',  '1'): '?=D-1',
        ('1',  'D'): 'D=-D\n?=D+1',

        ('A',  '1'): '?=A-1',
        ('1',  'A'): 'D=-A\n?=D+1',

        ('M',  '1'): '?=M-1',
        ('1',  'M'): 'D=-M\n?=D+1',

        ('A', 'D'): '?=A-D',
        ('D', 'A'): '?=D-A',

        ('M', 'D'): '?=M-D',
        ('D', 'M'): '?=D-M',
        
        ('A', 'A'): '?=0',
        ('M', 'M'): '?=0',
        ('D', 'D'): '?=0',

        ('A', 'M'): 'D=A\n?=D-M',
        ('M', 'A'): 'D=M\n?=D-A'
        
    }

    def run(self, line: str, p: int, o: int) -> str:
        _ARG1 = self.arguments[1]
        _ARG2 = self.arguments[2]
        try:
            DST = Destination(self.arguments[0])
            ARG1 = Argument(_ARG1)
            ARG2 = Argument(_ARG2)
        except BadDestination:
            raise ParserError(
                'MCR',
                "[OR] Destinacija mora biti jedan ili više registara,"
                "ili adresa.",
                o
            )
        except BadArgument:
            raise ParserError(
                'MCR',
                "[OR] Argument mora biti registar, konstanta, ili adresa.",
                o
            )
        except OutOfBoundsConstantError:
            raise ParserError(
                'MCR', "[OR] Konstanta mora biti u [-32768, 32767].", o
            )

        simple_op = (
            (_ARG1, _ARG2) if (_ARG1, _ARG2) in self.SIMPLE_OPS else None
        )

        # registar - registar early return
        if DST.is_register() and simple_op:
            return clean(
                self.SIMPLE_OPS[simple_op].replace('?', DST.registers)
            )
        # možemo očuvati stanje A registra
        elif DST.is_address() and simple_op and 'D' not in simple_op:
            save_address = "D=A\n@__aux\nM=D\nA=D"
            compute_value = self.SIMPLE_OPS[simple_op].replace('?', 'D')
            set_destination = f"@{DST.location}\n{DST.dereferences}\nM=D"
            restore_address = "@__aux\nA=M"
            return clean(f"{save_address}\n"
                         f"{compute_value}\n"
                         f"{set_destination}\n"
                         f"{restore_address}")
        # ne možemo očuvati stanje A registra
        elif DST.is_address() and simple_op and 'D' in simple_op:
            compute_value = self.SIMPLE_OPS[simple_op].replace('?', 'D')
            set_destination = f"@{DST.location}\n{DST.dereferences}\nM=D"
            return clean(f"{compute_value}\n{set_destination}")

        swap = False
        if (
            (ARG2.is_oneop() and ARG1.is_constant()) or
            (ARG2.is_oneop() and ARG1.is_address()) or
            (ARG2.is_constant() and ARG1.is_address())
        ):
            ARG1, ARG2 = ARG2, ARG1
            swap = True

        preserve_A = True
        preserve_A_with_M = False

        if (
            ARG1.is_register() and ARG1.register == 'D' and
            DST.is_register() and 'M' in DST.registers
        ):
            preserve_A_with_M = True
        elif (ARG1.is_register() and ARG1.register == 'D'):
            preserve_A = False

        if DST.is_register():
            set_destination = f"{DST.registers}=D"
        elif DST.is_address():
            set_destination = f"@{DST.location}\n{DST.dereferences}\nM=D"
        else:
            assert False

        if ARG1.is_oneop() and ARG2.is_constant():
            final_set = 'A-D' if swap else 'D-A'
            compute_value = (f"D={ARG1.oneop}\n@{ARG2.constant}\nD={final_set}"
                             if ARG2.constant >= 0 else
                             f"D={ARG1.oneop}\n@{~ARG2.constant}\n"
                             f"A=!A\nD={final_set}")

        elif ARG1.is_oneop() and ARG2.is_address():
            final_set = 'M-D' if swap else 'D-M'
            compute_value = (f"D={ARG1.oneop}\n@{ARG2.location}\n"
                             f"{ARG2.dereferences}D={final_set}")
        
        elif ARG1.is_constant() and ARG2.is_address():
            final_set = 'M-D' if swap else 'D-M'
            load_value1 = (f"@{ARG1.constant}\nD=A"
                           if ARG1.constant >= 0 else
                           f"@{~ARG1.constant}\nA=!A\nD=A")
            load_value2 = f"@{ARG2.location}\n{ARG2.dereferences}D={final_set}"
            compute_value = "{load_value1}\n{load_value2}"

        elif ARG1.is_constant() and ARG2.is_constant():
            result = ((ARG1.constant - ARG2.constant + 32768) & 0xffff) - 32768
            compute_value = (f"@{result}\nD=A"
                             if result >= 0 else
                             f"@{~result}\nA=!A\nD=A")

        elif ARG1.is_address() and ARG2.is_address():
            load_value1 = f"@{ARG1.location}\n{ARG1.dereferences}\nD=M"
            load_value2 = f"@{ARG2.location}\n{ARG2.dereferences}\nD=D-M"
            compute_value = f"{load_value1}\n{load_value2}"
        else:
            assert False

        restore_address = "@__aux\nA=M"
        if preserve_A_with_M:
            save_address = "M=D\nD=A\n@__aux\nAM=D\nD=M"
            return clean(f"{save_address}\n"
                         f"{compute_value}\n"
                         f"{restore_address}\n"
                         f"{set_destination}")
        elif preserve_A:
            save_address = "D=A\n@__aux\nM=D"
            if DST.is_register():
                return clean(f"{save_address}\n"
                             f"{compute_value}\n"
                             f"{restore_address}\n"
                             f"{set_destination}")
            return clean(f"{save_address}\n"
                         f"{compute_value}\n"
                         f"{set_destination}\n"
                         f"{restore_address}")
        else:
            return clean(f"{compute_value}\n{set_destination}")


class SWAP(SimpleMacro):

    arg_count = 2

    def run(self, line: str, p: int, o: int) -> str:
        _DST1 = self.arguments[1]
        _DST2 = self.arguments[2]
        try:
            DST1 = Destination(_DST1)
            DST2 = Destination(_DST2)
        except BadDestination:
            raise ParserError(
                'MCR',
                "[SWAP] Destinacija mora biti jedan ili više registara,"
                "ili adresa.",
                o
            )
        if (
            (DST1.is_register() and len(DST1.registers) > 1) or
            (DST2.is_register() and len(DST2.registers) > 1)
        ):
            raise ParserError(
                'MCR',
                "[SWAP] Swap ne može zamijeniti vište registara odjednom",
                o
            )
        if _DST1 == _DST2: return ''
        
        if DST2.is_register() and DST1.is_address():
            DST1, DST2 = DST2, DST1
        
        perform_swap = "D=D+M\nM=D-M\nD=D-M"
        if DST1.is_register() and DST2.is_register():
            # ne možemo direktno zamijeniti A i M
            if 'D' not in (DST1.registers, DST2.registers):
                perform_swap = ""
                return f"D=A\n{perform_swap}\nA=D"
            return clean(
                f"{DST1.registers}={DST1.registers}+{DST2.registers}\n"
                f"{DST2.registers}={DST1.registers}-{DST2.registers}\n"
                f"{DST1.registers}={DST1.registers}-{DST2.registers}"
            )
        elif (
            DST1.is_register() and DST1.registers == 'D' and
            DST2.is_address()
        ):
            # ne možemo očuvati stanje A registra
            return clean(f"@{DST2.location}\n"
                         f"{DST2.dereferences}\n"
                         f"{perform_swap}")
        elif (
            DST1.is_register() and DST1.registers == 'A' and
            DST2.is_address()
        ):
            return clean( "D=A\n"
                         f"@{DST2.location}\n"
                         f"{DST2.dereferences}\n"
                         f"{perform_swap}\n"
                          "A=D")
        elif (
            DST1.is_register() and DST1.registers == 'M' and
            DST2.is_address()
        ):
            save_address = "D=A\n@__aux\nAM=D"
            restore_address = "@__aux\nA=M"
            return clean(f"{save_address}\n"
                          "D=M\n"
                         f"@{DST2.location}\n"
                         f"{DST2.dereferences}\n"
                         f"{perform_swap}\n"
                         f"{restore_address}\n"
                          "M=D")
        else:
            save_address = "D=A\n@__aux\nAM=D"
            restore_address = "@__aux\nA=M"
            return clean(f"{save_address}\n"
                         f"@{DST1.location}\n{DST1.dereferences}\nD=M\n"
                         f"@{DST2.location}\n{DST2.dereferences}\n"
                         f"{perform_swap}\n"
                         f"@{DST1.location}\n{DST1.dereferences}M=D\n"
                         f"{restore_address}")

class AND(SimpleMacro):
    arg_count = 3

    SIMPLE_OPS: dict[tuple[str, str], str] = {

        ('0', '0'): '0',
        ('1', '1'): '1',
        ('-1', '-1'): '1',

        ('0', '1'): '0',
        ('0', '-1'): '0',
        ('1', '-1'): '1',

        ('D',  '0'): '0',
        ('A',  '0'): '0',
        ('M',  '0'): '0',
        
    }

    COMPLEX_OPS: dict[tuple[str, str], str] = {
        ('D', 'D'): 'D=D',
        ('A', 'A'): 'D=A',
        ('M', 'M'): 'D=M',
        
        ('D', '-1'): 'D=D',
        ('A', '-1'): 'D=A',
        ('M', '-1'): 'D=M',
        
        ('D',  '1'): 'D=D',
        ('A',  '1'): 'D=A',
        ('M',  '1'): 'D=M',

    }

    def run(self, line: str, p: int, o: int) -> str:
        _ARG1 = self.arguments[1]
        _ARG2 = self.arguments[2]
        try:
            DST = Destination(self.arguments[0])
            ARG1 = Argument(_ARG1)
            ARG2 = Argument(_ARG2)
        except BadDestination:
            raise ParserError(
                'MCR',
                "[OR] Destinacija mora biti jedan ili više registara,"
                "ili adresa.",
                o
            )
        except BadArgument:
            raise ParserError(
                'MCR',
                "[OR] Argument mora biti registar, konstanta, ili adresa.",
                o
            )
        except OutOfBoundsConstantError:
            raise ParserError(
                'MCR', "[OR] Konstanta mora biti u [-32768, 32767].", o
            )

        simple_op = (
            (_ARG1, _ARG2) if (_ARG1, _ARG2) in self.SIMPLE_OPS else
            (_ARG2, _ARG1) if (_ARG2, _ARG1) in self.SIMPLE_OPS else
            None
        )

        complex_op = (
            (_ARG1, _ARG2) if (_ARG1, _ARG2) in self.COMPLEX_OPS else
            (_ARG2, _ARG1) if (_ARG2, _ARG1) in self.COMPLEX_OPS else
            None
        )
        
        if DST.is_register() and simple_op:
            return f"{DST.registers}={self.SIMPLE_OPS[simple_op]}"
        elif DST.is_address() and simple_op:
            save_address = "D=A\n@__aux\nM=D"
            set_destination = (f"@{DST.location}\n"
                               f"{DST.dereferences}\n"
                               f"M={self.SIMPLE_OPS[simple_op]}")
            restore_address = "@__aux\nA=M"
            return clean(f"{save_address}\n"
                         f"{set_destination}\n"
                         f"{restore_address}")
        elif DST.is_register() and complex_op and 'D' in complex_op:
            # ne prezervira A registar
            if 'M' not in DST.registers:
                get_value = self.COMPLEX_OPS[complex_op]
                check_value = f"__andcheckfailed_{p}\nD;JEQ"
                end_operation = f"D=1\n@__endandoperation_{p}\n0;JMP"
                check_labels = (f"(__andcheckfailed_{p})\n"
                                 "D=0\n"
                                f"(__endandoperation_{p})")
                set_destination = f"{DST.registers}=D"
                return clean(f"{get_value}\n"
                             f"{check_value}\n"
                             f"{check_labels}\n"
                             f"{set_destination}")
            # ako je M jedna od lokacija u koju pišemo, slobodno ga
            # možemo koristiti kao pomoćni registar u koji možemo
            # spremiti operand. ovo nam pomaže da očuvamo A registar
            save_address = "M=D\nD=A\n@__aux\nAM=D\nD=M"
            get_value = self.COMPLEX_OPS[complex_op]
            check_value = f"@__andcheckfailed_{p}\nD;JEQ"
            end_operation = f"D=1\n@__endandoperation_{p}\n0;JMP"
            check_labels = (f"(__andcheckfailed_{p})\n"
                             "D=0\n"
                            f"(__endandoperation_{p})")
            restore_address = "@__aux\nA=M"
            set_destination = f"{DST.registers}=D"
            return clean(f"{save_address}\n"
                         f"{get_value}\n"
                         f"{check_value}\n"
                         f"{end_operation}\n"
                         f"{check_labels}\n"
                         f"{restore_address}\n"
                         f"{set_destination}")
        # ne prezervira A registar
        elif DST.is_address() and complex_op and 'D' in complex_op:
            get_value = self.COMPLEX_OPS[complex_op]
            check_value = f"@__andcheckfailed_{p}\nD;JEQ"
            end_operation = f"D=1\n@__endandoperation_{p}\n0;JMP"
            check_labels = (f"(__andcheckfailed_{p})\n"
                             "D=0\n"
                            f"(__endandoperation_{p})")
            set_destination = f"@{DST.location}\n{DST.dereferences}\nM=D"
            return clean(f"{get_value}\n"
                         f"{check_value}\n"
                         f"{end_operation}\n"
                         f"{check_labels}\n"
                         f"{set_destination}")
        elif DST.is_register() and complex_op and 'D' not in complex_op:
            save_address = "D=A\n@__aux\nAM=D"
            get_value = self.COMPLEX_OPS[complex_op]
            check_value = f"@__andcheckfailed_{p}\nD;JEQ"
            end_operation = f"D=1\n@__endandoperation_{p}\n0;JMP"
            check_labels = (f"(__andcheckfailed_{p})\n"
                             "D=0\n"
                            f"(__endandoperation_{p})")
            restore_address = "@__aux\nA=M"
            set_destination = "{DST.registers}=D"
            return clean(f"{save_address}\n"
                         f"{get_value}\n"
                         f"{check_value}\n"
                         f"{end_operation}\n"
                         f"{check_labels}\n"
                         f"{restore_address}\n"
                         f"{set_destination}")
        elif DST.is_address() and complex_op and 'D' not in complex_op:
            save_address = "D=A\n@__aux\nAM=D"
            get_value = self.COMPLEX_OPS[complex_op]
            check_value = f"@__andcheckfailed_{p}\nD;JEQ"
            end_operation = f"D=1\n@__endandoperation_{p}\n0;JMP"
            check_labels = (f"(__andcheckfailed_{p})\n"
                             "D=0\n"
                            f"(__endandoperation_{p})")
            set_destination = f"@{DST.location}\n{DST.dereferences}\nM=D"
            restore_address = "@__aux\nA=M"
            return clean(f"{save_address}\n"
                         f"{get_value}\n"
                         f"{check_value}\n"
                         f"{end_operation}\n"
                         f"{check_labels}\n"
                         f"{set_destination}\n"
                         f"{restore_address}")
        
        # ako uspoređujem M i D, kako bih usporedio D s nulom, moram se
        # prebaciti na adresu labela na koji ću skočiti, što pogazi
        # trenutni A, koji nisam nigdje spremio, a pošto nemam taj A
        # više ne mogu ni pročitati memoriju na njemu, tako da sam
        # izgubio i M
        # kako bih se kasnije mogao vratiti na trenutni A, morao bih ga
        # spremiti u D, što pogazi trenutni D
        # u ovom slučaju ne mogu napraviti 'trik' kao kod A && D, što je
        # pogaziti memoriju, jer je memorija jedan od operanada, tako da
        # *mislim* ja je usporedba M i D nemoguća osim ako ne napravim
        # nešto kao uvećanje A za 1, spremanje vrijednosti tu, vraćanja
        # natrag, etc, etc.
        # osim što pogazi trenutnu memoriju, ovaj pristup pogazi i neku
        # potpuno odvojenu memoriju, tako da to pogotovo ne želim
        # napraviti
        if (
            ARG1.is_register() and ARG2.is_register() and
            (ARG1.register, ARG2.register) in (('M', 'D'), ('D', 'M'))
        ):
            raise ParserError('MCR', "[AND] Nemoguća operacija.", o)
        
        if (
            ARG1.is_register() and ARG2.is_register()
            and ((ARG1.register, ARG2.register) in (('A', 'D'), ('D', 'A')))
        ):
            # ako uspoređujem A i D, kako bih usporedio D s nulom, moram
            # se prebaciti na adresu labela na koji ću skočiti, što
            # pogazi trenutni A, koji nisam nigdje spremio
            # kako bih se kasnije mogao vratiti na trenutni A, morao bih
            # ga spremiti u D, što pogazi trenutni D
            # A && D mogu napraviti ako na početku spremim trenutni D u
            # M, što uništava memoriju koja je bila na lokaciji A, ali
            # to ne želim napraviti osim ako svejedno ne overwriteam M u
            # konačnici
            if (
                (DST.is_register() and 'M' not in DST.registers)
                or DST.is_address()
            ):
                raise ParserError('MCR', "[AND] Nemoguća operacija.", o)

            save_address = "M=D\nD=A\n@__aux\nM=D"  # D = A now, check A first
            check_value = f"@__andcheckfailed_{p}\nD;JEQ"
            get_D = "A=D\nD=M"
            end_operation = f"D=1\n@__endandoperation_{p}\n0;JMP"
            check_labels = (f"(__andcheckfailed_{p})\n"
                             "D=0\n"
                            f"(__endandoperation_{p})")
            restore_address = "@__aux\nA=M"
            set_destination = f"{DST.registers}=D"
            return clean(f"{save_address}\n"
                         f"{check_value}\n"
                         f"{get_D}\n"
                         f"{check_value}\n"
                         f"{end_operation}\n"
                         f"{check_labels}\n"
                         f"{restore_address}\n"
                         f"{set_destination}")
        
        if (
            ARG1.is_register() and ARG2.is_register() and
            (ARG1.register, ARG2.register) in (('A', 'M'), ('M', 'A'))
        ):
            save_address = "D=A\n@__aux\nAM=D"
            check_value = f"@__andcheckfailed_{p}\nD;JEQ"
            get_M = f"A=D\nD=M"
            end_operation = f"D=1\n@__endandoperation_{p}\n0;JMP"
            check_labels = (f"(__andcheckfailed_{p})\n"
                             "D=0\n"
                            f"(__endandoperation_{p})")
            restore_address = "@__aux\nA=M"
            if DST.is_register():
                set_destination = f"{DST.registers}=D"
                return clean(f"{save_address}\n"
                             f"{check_value}\n"
                             f"{get_M}\n"
                             f"{check_value}\n"
                             f"{end_operation}\n"
                             f"{check_labels}\n"
                             f"{restore_address}\n"
                             f"{set_destination}")
            else:
                set_destination = "@{DST.location}\n{DST.dereferences}\nM=D"
                return clean(f"{save_address}\n"
                             f"{check_value}\n"
                             f"{get_M}\n"
                             f"{check_value}\n"
                             f"{end_operation}\n"
                             f"{check_labels}\n"
                             f"{set_destination}\n"
                             f"{restore_address}")
        
        if ARG2.is_register() and ARG1.is_constant():
            ARG1, ARG2 = ARG2, ARG1

        if ARG1.is_register() and ARG2.is_constant():
            if not ARG2.constant:
                if DST.is_address():
                    save_address = "D=A\n@__aux\nM=D"
                    set_destination = (f"@{DST.location}\n"
                                       f"{DST.dereferences}\n"
                                        "M=0")
                    restore_address = "@__aux\nA=M"
                    return clean(
                        f"{save_address}\n{set_destination}\n{restore_address}"
                    )
                else:
                    return f"{DST.registers}=0"
            else:
                if DST.is_address() and ARG1.register != 'D':
                    save_address = "D=A\n@__aux\nAM=D"
                    compute_value = f"D={ARG1.register}"
                    check_value = f"@__andcheckfailed_{p}\nD;JEQ"
                    end_operation = f"D=1\n@__endandoperation_{p}\n0;JMP"
                    check_labels = (f"(__andcheckfailed_{p})\n"
                                     "D=0\n"
                                    f"(__endandoperation_{p})")
                    set_destination = (f"@{DST.location}\n"
                                       f"{DST.dereferences}\n"
                                        "M=D")
                    restore_address = "@__aux\nA=M"
                    return clean(f"{save_address}\n"
                                 f"{compute_value}\n"
                                 f"{check_value}\n"
                                 f"{end_operation}\n"
                                 f"{check_labels}\n"
                                 f"{set_destination}\n"
                                 f"{restore_address}")
                # ne prezervira A registar
                elif DST.is_address() and ARG1.register == 'D':
                    check_value = f"@__andcheckfailed_{p}\nD;JEQ"
                    end_operation = f"D=1\n@__endandoperation_{p}\n0;JMP"
                    check_labels = (f"(__andcheckfailed_{p})\n"
                                     "D=0\n"
                                    f"(__endandoperation_{p})")
                    set_destination = (f"@{DST.location}\n"
                                       f"{DST.dereferences}\n"
                                        "M=D")
                    return clean(f"{check_value}\n"
                                 f"{end_operation}\n"
                                 f"{check_labels}\n"
                                 f"{set_destination}")
                elif DST.is_register() and ARG1.register != 'D':
                    save_address = "D=A\n@__aux\nAM=D"
                    compute_value = f"D={ARG1.register}"
                    check_value = f"@__andcheckfailed_{p}\nD;JEQ"
                    end_operation = f"D=1\n@__endandoperation_{p}\n0;JMP"
                    check_labels = (f"(__andcheckfailed_{p})\n"
                                     "D=0\n"
                                    f"(__endandoperation_{p})")
                    restore_address = "@__aux\nA=M"
                    set_destination = f"{DST.registers}=D"
                    return clean(f"{save_address}\n"
                                 f"{compute_value}\n"
                                 f"{check_value}\n"
                                 f"{end_operation}\n"
                                 f"{check_labels}\n"
                                 f"{restore_address}\n"
                                 f"{set_destination}")
                elif DST.is_register() and ARG1 == 'D':
                    # ne prezervira A registar
                    check_value = f"@__andcheckfailed_{p}\nD;JEQ"
                    end_operation = f"D=1\n@__endandoperation_{p}\n0;JMP"
                    check_labels = (f"(__andcheckfailed_{p})\n"
                                     "D=0\n"
                                    f"(__endandoperation_{p})")
                    set_destination = "{DST.registers}=D"
                    if 'M' not in DST.registers:
                        return (f"{check_value}\n"
                                f"{end_operation}\n"
                                f"{check_labels}\n"
                                f"{set_destination}")
                    save_address = "M=D\nD=A\n@__aux\nAM=D\nD=M"
                    restore_address = "@__aux\nA=M"
                    return clean(f"{save_address}\n"
                                 f"{check_value}\n"
                                 f"{check_labels}\n"
                                 f"{restore_address}\n"
                                 f"{set_destination}")

        if ARG1.is_constant() and ARG2.is_constant():
            if DST.is_register():
                return (
                    f"{DST.registers}={int(ARG1.constant and ARG2.constant)}"
                )
            else:
                save_address = "D=A\n@__aux\nM=D"
                set_destination = (f"@{DST.location}\n"
                                   f"{DST.dereferences}\n"
                                   f"M={int(ARG1.constant and ARG2.constant)}")
                restore_address = "@__aux\nA=M"
                return clean(f"{save_address}\n"
                             f"{set_destination}\n"
                             f"{restore_address}")

        if ARG2.is_constant() and ARG1.is_address():
            ARG1, ARG2 = ARG2, ARG1

        if ARG1.is_constant() and ARG2.is_address():
            if not ARG1.constant:
                if DST.is_address():
                    save_address = "D=A\n@__aux\nM=D"
                    set_destination = (f"@{DST.location}\n"
                                       f"{DST.dereferences}\n"
                                        "M=0")
                    restore_address = "@__aux\nA=M"
                    return clean(
                        f"{save_address}\n{set_destination}\n{restore_address}"
                    )
                else:
                    return f"{DST.registers}=0"
            else:
                save_address = "D=A\n@__aux\nM=D"
                compute_value = f"@{ARG2.location}\n{ARG2.dereferences}\nD=M"
                check_value = f"@__andcheckfailed_{p}\nD;JEQ"
                end_operation = f"D=1\n@__endandoperation_{p}\n0;JMP"
                check_labels = (f"(__andcheckfailed_{p})\n"
                                 "D=0\n"
                                f"(__endandoperation_{p})")
                restore_address = "@__aux\nA=M"
                if DST.is_address():
                    set_destination = (f"@{DST.location}\n"
                                       f"{DST.dereferences}\n"
                                        "M=D")
                    return clean(f"{save_address}\n"
                                 f"{compute_value}\n"
                                 f"{check_value}\n"
                                 f"{end_operation}\n"
                                 f"{check_labels}\n"
                                 f"{set_destination}\n"
                                 f"{restore_address}")
                else:
                    set_destination = f"{DST.registers}=D"
                    return clean(f"{save_address}\n"
                                 f"{compute_value}\n"
                                 f"{check_value}\n"
                                 f"{end_operation}\n"
                                 f"{check_labels}\n"
                                 f"{restore_address}\n"
                                 f"{set_destination}")

        if ARG1.is_address() and ARG2.is_address():
            save_address = "D=A\n@__aux\nM=D"
            get_value1 = f"@{ARG1.location}\n{ARG1.dereferences}\nD=M"
            get_value2 = f"@{ARG2.location}\n{ARG2.dereferences}\nD=M"
            check_value = f"@__andcheckfailed_{p}\nD;JEQ"
            end_operation = f"D=1\n@__endandoperation_{p}\n0;JMP"
            check_labels = (f"(__andcheckfailed_{p})\n"
                             "D=0\n"
                            f"(__endandoperation_{p})")
            restore_address = "@__aux\nA=M"

            if DST.is_address():
                set_destination = f"@{DST.location}\n{DST.dereferences}\nM=D"
                return clean(f"{save_address}\n"
                             f"{get_value1}\n"
                             f"{check_value}\n"
                             f"{get_value2}\n"
                             f"{check_value}\n"
                             f"{end_operation}\n"
                             f"{check_labels}\n"
                             f"{set_destination}\n"
                             f"{restore_address}")
            else:
                set_destination = f"{DST.registers}=D"
                return clean(f"{save_address}\n"
                             f"{get_value1}\n"
                             f"{check_value}\n"
                             f"{get_value2}\n"
                             f"{check_value}\n"
                             f"{end_operation}\n"
                             f"{check_labels}\n"
                             f"{restore_address}\n"
                             f"{set_destination}")

        if ARG2.is_register() and ARG1.is_address():
            ARG1, ARG2 = ARG2, ARG1
        
        if ARG1.is_register() and ARG1.register != 'D' and ARG2.is_address():

            save_address = "D=A\n@__aux\nAM=D"
            get_value1 = f"D={ARG1.register}"
            get_value2 = f"@{ARG2.location}\n{ARG2.dereferences}\nD=M"
            check_value = f"@__andcheckfailed_{p}\nD;JEQ"
            end_operation = f"D=1\n@__endandoperation_{p}\n0;JMP"
            check_labels = (f"(__andcheckfailed{p})\n"
                             "D=0\n"
                            f"(__endandoperation_{p})")
            restore_address = "@__aux\nA=M"

            if DST.is_address():
                set_destination = f"@{DST.location}\n{DST.dereferences}\nM=D"
                return clean(f"{save_address}\n"
                             f"{get_value1}\n"
                             f"{check_value}\n"
                             f"{get_value2}\n"
                             f"{check_value}\n"
                             f"{end_operation}\n"
                             f"{check_labels}\n"
                             f"{set_destination}\n"
                             f"{restore_address}")
            else:
                set_destination = f"{DST.registers}=D"
                return clean(f"{save_address}\n"
                             f"{get_value1}\n"
                             f"{check_value}\n"
                             f"{get_value2}\n"
                             f"{check_value}\n"
                             f"{end_operation}\n"
                             f"{check_labels}\n"
                             f"{restore_address}\n"
                             f"{set_destination}")

        if ARG1.is_register() and ARG1.register == 'D' and ARG2.is_address():
            
            if (
                (DST.is_register() and 'M' not in DST.registers) or
                DST.is_address()
            ):
                get_value2 = f"@{ARG2.location}\n{ARG2.dereferences}\nD=M"
                check_value = f"@__andcheckfailed_{p}\nD;JEQ"
                end_operation = f"D=1\n@__endandoperation_{p}\n0;JMP"
                check_labels = (f"(__andcheckfailed_{p})\n"
                                 "D=0\n"
                                f"(__endandoperation_{p})")
                set_destination = (f"{DST.registers}=D" if
                                   DST.is_register() else
                                   f"@{DST.location}\n{DST.dereferences}\nM=D")
                return clean(f"{check_value}\n"
                             f"{get_value2}\n"
                             f"{check_value}\n"
                             f"{end_operation}\n"
                             f"{check_labels}\n"
                             f"{set_destination}")

            elif DST.is_register() and 'M' in DST.registers:
                save_address = "M=D\nD=A\n@__aux\nAM=D\nD=M"
                get_value2 = f"@{ARG2.location}\n{ARG2.dereferences}\nD=M"
                check_value = f"@__andcheckfailed_{p}\nD;JEQ"
                end_operation = f"D=1\n@__endandoperation_{p}\n0;JMP"
                check_labels = (f"(__andcheckfailed_{p})\n"
                                 "D=0\n"
                                f"(__endandoperation_{p})")
                restore_address = "@__aux\nA=M"
                set_destination = f"{DST.registers}=D"
                return clean(f"{save_address}\n"
                             f"{check_value}\n"
                             f"{get_value2}\n"
                             f"{check_value}\n"
                             f"{end_operation}\n"
                             f"{check_labels}\n"
                             f"{restore_address}\n"
                             f"{set_destination}\n")

        raise ParserError('MCR', "[OR] Nevalidan argument.", o)


class OR(SimpleMacro):
    arg_count = 3
    SIMPLE_OPS: dict[tuple[str, str], str] = {
        ('0', '0'): '0',
        ('1', '1'): '1',
        ('-1', '-1'): '1',

        ('0', '1'): '1',
        ('0', '-1'): '1',
        ('1', '-1'): '1',
        
        ('D',  '1'): '1',
        ('A',  '1'): '1',
        ('M',  '1'): '1',
        
        ('D', '-1'): '1',
        ('A', '-1'): '1',
        ('M', '-1'): '1',
    }

    COMPLEX_OPS: dict[tuple[str, str], str] = {
        ('D', 'D'): '',
        ('A', 'A'): 'D=A',
        ('M', 'M'): 'D=M',
        
        ('D',  '0'): '',
        ('A',  '0'): 'D=A',
        ('M',  '0'): 'D=M',
        
        ('A', 'M'): 'D=A\nD=D|M',
        ('D', 'M'): 'D=D|M',
        ('A', 'D'): 'D=D|A',
    }

    def run(self, line: str, p: int, o: int) -> str:
        _ARG1 = self.arguments[1]
        _ARG2 = self.arguments[2]
        try:
            DST = Destination(self.arguments[0])
            ARG1 = Argument(_ARG1)
            ARG2 = Argument(_ARG2)
        except BadDestination:
            raise ParserError(
                'MCR',
                "[OR] Destinacija mora biti jedan ili više registara,"
                "ili adresa.",
                o
            )
        except BadArgument:
            raise ParserError(
                'MCR',
                "[OR] Argument mora biti registar, konstanta, ili adresa.",
                o
            )
        except OutOfBoundsConstantError:
            raise ParserError(
                'MCR', "[OR] Konstanta mora biti u [-32768, 32767].", o
            )

        simple_op = (
            (_ARG1, _ARG2) if (_ARG1, _ARG2) in self.SIMPLE_OPS else
            (_ARG2, _ARG1) if (_ARG2, _ARG1) in self.SIMPLE_OPS else
            None
        )

        complex_op = (
            (_ARG1, _ARG2) if (_ARG1, _ARG2) in self.COMPLEX_OPS else
            (_ARG2, _ARG1) if (_ARG2, _ARG1) in self.COMPLEX_OPS else
            None
        )
        
        if DST.is_register() and simple_op:
            return f"{DST.registers}={self.SIMPLE_OPS[simple_op]}"
        elif DST.is_address() and simple_op:
            save_address = "D=A\n@__aux\nM=D"
            set_destination = (f"@{DST.location}\n"
                               f"{DST.dereferences}\n"
                               f"M={self.SIMPLE_OPS[simple_op]}")
            restore_address = "@__aux\nA=M"
            return clean(f"{save_address}\n"
                         f"{set_destination}\n"
                         f"{restore_address}")
        elif DST.is_register() and complex_op and 'D' in complex_op:
            # ne prezervira A registar
            if 'M' not in DST.registers:
                get_value = self.COMPLEX_OPS[complex_op]
                check_value = f"__orcheckfailed_{p}\nD;JEQ"
                end_operation = f"D=1\n@__endoroperation_{p}\n0;JMP"
                check_labels = (f"(__orcheckfailed_{p})\n"
                                 "D=0\n"
                                f"(__endoroperation_{p})")
                set_destination = f"{DST.registers}=D"
                return clean(f"{get_value}\n"
                             f"{check_value}\n"
                             f"{check_labels}\n"
                             f"{set_destination}")
            # ako je M jedna od lokacija u koju pišemo, slobodno ga
            # možemo koristiti kao pomoćni registar u koji možemo
            # spremiti operand. ovo nam pomaže da očuvamo A registar
            save_address = "M=D\nD=A\n@__aux\nAM=D\nD=M"
            get_value = self.COMPLEX_OPS[complex_op]
            check_value = f"@__orcheckfailed_{p}\nD;JEQ"
            end_operation = f"D=1\n@__endoroperation_{p}\n0;JMP"
            check_labels = (f"(__orcheckfailed_{p})\n"
                             "D=0\n"
                            f"(__endoroperation_{p})")
            restore_address = "@__aux\nA=M"
            set_destination = f"{DST.registers}=D"
            return clean(f"{save_address}\n"
                         f"{get_value}\n"
                         f"{check_value}\n"
                         f"{end_operation}\n"
                         f"{check_labels}\n"
                         f"{restore_address}\n"
                         f"{set_destination}")
        # ne prezervira A registar
        elif DST.is_address() and complex_op and 'D' in complex_op:
            get_value = self.COMPLEX_OPS[complex_op]
            check_value = f"@__orcheckfailed_{p}\nD;JEQ"
            end_operation = f"D=1\n@__endoroperation_{p}\n0;JMP"
            check_labels = (f"(__orcheckfailed_{p})\n"
                             "D=0\n"
                            f"(__endoroperation_{p})")
            set_destination = f"@{DST.location}\n{DST.dereferences}\nM=D"
            return clean(f"{get_value}\n"
                         f"{check_value}\n"
                         f"{end_operation}\n"
                         f"{check_labels}\n"
                         f"{set_destination}")
        elif DST.is_register() and complex_op and 'D' not in complex_op:
            save_address = "D=A\n@__aux\nAM=D"
            get_value = self.COMPLEX_OPS[complex_op]
            check_value = f"@__orcheckfailed_{p}\nD;JEQ"
            end_operation = f"D=1\n@__endoroperation_{p}\n0;JMP"
            check_labels = (f"(__orcheckfailed_{p})\n"
                             "D=0\n"
                            f"(__endoroperation_{p})")
            restore_address = "@__aux\nA=M"
            set_destination = "{DST.registers}=D"
            return clean(f"{save_address}\n"
                         f"{get_value}\n"
                         f"{check_value}\n"
                         f"{end_operation}\n"
                         f"{check_labels}\n"
                         f"{restore_address}\n"
                         f"{set_destination}")
        elif DST.is_address() and complex_op and 'D' not in complex_op:
            save_address = "D=A\n@__aux\nAM=D"
            get_value = self.COMPLEX_OPS[complex_op]
            check_value = f"@__orcheckfailed_{p}\nD;JEQ"
            end_operation = f"D=1\n@__endoroperation_{p}\n0;JMP"
            check_labels = (f"(__orcheckfailed_{p})\n"
                             "D=0\n"
                            f"(__endoroperation_{p})")
            set_destination = f"@{DST.location}\n{DST.dereferences}\nM=D"
            restore_address = "@__aux\nA=M"
            return clean(f"{save_address}\n"
                         f"{get_value}\n"
                         f"{check_value}\n"
                         f"{end_operation}\n"
                         f"{check_labels}\n"
                         f"{set_destination}\n"
                         f"{restore_address}")
        
        if ARG2.is_register() and ARG1.is_constant():
            ARG1, ARG2 = ARG2, ARG1

        if ARG1.is_register() and ARG2.is_constant():
            if ARG2.constant:
                if DST.is_address():
                    save_address = "D=A\n@__aux\nM=D"
                    set_destination = (f"@{DST.location}\n"
                                       f"{DST.dereferences}\n"
                                        "M=1")
                    restore_address = "@__aux\nA=M"
                    return clean(
                        f"{save_address}\n{set_destination}\n{restore_address}"
                    )
                else:
                    return f"{DST.registers}=1"
            else:
                if DST.is_address() and ARG1.register != 'D':
                    save_address = "D=A\n@__aux\nAM=D"
                    compute_value = f"D={ARG1.register}"
                    check_value = f"@__orcheckfailed_{p}\nD;JEQ"
                    end_operation = f"D=1\n@__endoroperation_{p}\n0;JMP"
                    check_labels = (f"(__orcheckfailed_{p})\n"
                                     "D=0\n"
                                    f"(__endoroperation_{p})")
                    set_destination = (f"@{DST.location}\n"
                                       f"{DST.dereferences}\n"
                                        "M=D")
                    restore_address = "@__aux\nA=M"
                    return clean(f"{save_address}\n"
                                 f"{compute_value}\n"
                                 f"{check_value}\n"
                                 f"{end_operation}\n"
                                 f"{check_labels}\n"
                                 f"{set_destination}\n"
                                 f"{restore_address}")
                # ne prezervira A registar
                elif DST.is_address() and ARG1.register == 'D':
                    check_value = f"@__orcheckfailed_{p}\nD;JEQ"
                    end_operation = f"D=1\n@__endoroperation_{p}\n0;JMP"
                    check_labels = (f"(__orcheckfailed_{p})\n"
                                     "D=0\n"
                                    f"(__endoroperation_{p})")
                    set_destination = (f"@{DST.location}\n"
                                       f"{DST.dereferences}\n"
                                        "M=D")
                    return clean(f"{check_value}\n"
                                 f"{end_operation}\n"
                                 f"{check_labels}\n"
                                 f"{set_destination}")
                elif DST.is_register() and ARG1.register != 'D':
                    save_address = "D=A\n@__aux\nAM=D"
                    compute_value = f"D={ARG1.register}"
                    check_value = f"@__orcheckfailed_{p}\nD;JEQ"
                    end_operation = f"D=1\n@__endoroperation_{p}\n0;JMP"
                    check_labels = (f"(__orcheckfailed_{p})\n"
                                     "D=0\n"
                                    f"(__endoroperation_{p})")
                    restore_address = "@__aux\nA=M"
                    set_destination = f"{DST.registers}=D"
                    return clean(f"{save_address}\n"
                                 f"{compute_value}\n"
                                 f"{check_value}\n"
                                 f"{end_operation}\n"
                                 f"{check_labels}\n"
                                 f"{restore_address}\n"
                                 f"{set_destination}")
                elif DST.is_register() and ARG1 == 'D':
                    # ne prezervira A registar
                    check_value = f"@__orcheckfailed_{p}\nD;JEQ"
                    end_operation = f"D=1\n@__endoroperation_{p}\n0;JMP"
                    check_labels = (f"(__orcheckfailed_{p})\n"
                                     "D=0\n"
                                    f"(__endoroperation_{p})")
                    set_destination = "{DST.registers}=D"
                    if 'M' not in DST.registers:
                        return (f"{check_value}\n"
                                f"{end_operation}\n"
                                f"{check_labels}\n"
                                f"{set_destination}")
                    save_address = "M=D\nD=A\n@__aux\nAM=D\nD=M"
                    restore_address = "@__aux\nA=M"
                    return clean(f"{save_address}\n"
                                 f"{check_value}\n"
                                 f"{check_labels}\n"
                                 f"{restore_address}\n"
                                 f"{set_destination}")

        if ARG1.is_constant() and ARG2.is_constant():
            if DST.is_register():
                return f"{DST.registers}={int(ARG1.constant or ARG2.constant)}"
            else:
                save_address = "D=A\n@__aux\nM=D"
                set_destination = (f"@{DST.location}\n"
                                   f"{DST.dereferences}\n"
                                   f"M={int(ARG1.constant or ARG2.constant)}")
                restore_address = "@__aux\nA=M"
                return clean(f"{save_address}\n"
                             f"{set_destination}\n"
                             f"{restore_address}")

        if ARG2.is_constant() and ARG1.is_address():
            ARG1, ARG2 = ARG2, ARG1

        if ARG1.is_constant() and ARG2.is_address():
            if ARG1.constant:
                if DST.is_address():
                    save_address = "D=A\n@__aux\nM=D"
                    set_destination = (f"@{DST.location}\n"
                                       f"{DST.dereferences}\n"
                                        "M=1")
                    restore_address = "@__aux\nA=M"
                    return clean(
                        f"{save_address}\n{set_destination}\n{restore_address}"
                    )
                else:
                    return f"{DST.registers}=1"
            else:
                save_address = "D=A\n@__aux\nM=D"
                compute_value = f"@{ARG2.location}\n{ARG2.dereferences}\nD=M"
                check_value = f"@__orcheckfailed_{p}\nD;JEQ"
                end_operation = f"D=1\n@__endoroperation_{p}\n0;JMP"
                check_labels = (f"(__orcheckfailed_{p})\n"
                                 "D=0\n"
                                f"(__endoroperation_{p})")
                restore_address = "@__aux\nA=M"
                if DST.is_address():
                    set_destination = (f"@{DST.location}\n"
                                       f"{DST.dereferences}\n"
                                        "M=D")
                    return clean(f"{save_address}\n"
                                 f"{compute_value}\n"
                                 f"{check_value}\n"
                                 f"{end_operation}\n"
                                 f"{check_labels}\n"
                                 f"{set_destination}\n"
                                 f"{restore_address}")
                else:
                    set_destination = f"{DST.registers}=D"
                    return clean(f"{save_address}\n"
                                 f"{compute_value}\n"
                                 f"{check_value}\n"
                                 f"{end_operation}\n"
                                 f"{check_labels}\n"
                                 f"{restore_address}\n"
                                 f"{set_destination}")

        if ARG1.is_address() and ARG2.is_address():
            save_address = "D=A\n@__aux\nM=D"
            compute_value = (f"@{ARG1.location}\n{ARG1.dereferences}\nD=M\n"
                             f"@{ARG2.location}\n{ARG2.dereferences}\nD=D|M")
            check_value = f"@__orcheckfailed_{p}\nD;JEQ"
            end_operation = f"D=1\n@__endoroperation_{p}\n0;JMP"
            check_labels = (f"(__orcheckfailed_{p})\n"
                             "D=0\n"
                            f"(__endoroperation_{p})")
            restore_address = "@__aux\nA=M"

            if DST.is_address():
                set_destination = f"@{DST.location}\n{DST.dereferences}\nM=D"
                return clean(f"{save_address}\n"
                             f"{compute_value}\n"
                             f"{check_value}\n"
                             f"{end_operation}\n"
                             f"{check_labels}\n"
                             f"{set_destination}\n"
                             f"{restore_address}")
            else:
                set_destination = f"{DST.registers}=D"
                return clean(f"{save_address}\n"
                             f"{compute_value}\n"
                             f"{check_value}\n"
                             f"{end_operation}\n"
                             f"{check_labels}\n"
                             f"{restore_address}\n"
                             f"{set_destination}")

        if ARG2.is_register() and ARG1.is_address():
            ARG1, ARG2 = ARG2, ARG1
        
        if ARG1.is_register() and ARG1.register != 'D' and ARG2.is_address():

            save_address = "D=A\n@__aux\nAM=D"
            compute_value = (f"D={ARG1}\n"
                             f"@{ARG2.location}\n{ARG2.dereferences}\nD=M|D")
            check_value = f"@__orcheckfailed_{p}\nD;JEQ"
            end_operation = f"D=1\n@__endoroperation_{p}\n0;JMP"
            check_labels = (f"(__orcheckfailed{p})\n"
                             "D=0\n"
                            f"(__endoroperation_{p})")
            restore_address = "@__aux\nA=M"

            if DST.is_address():
                set_destination = f"@{DST.location}\n{DST.dereferences}\nM=D"
                return clean(f"{save_address}\n"
                             f"{compute_value}\n"
                             f"{check_value}\n"
                             f"{end_operation}\n"
                             f"{check_labels}\n"
                             f"{set_destination}\n"
                             f"{restore_address}")
            else:
                set_destination = f"{DST.registers}=D"
                return clean(f"{save_address}\n"
                             f"{compute_value}\n"
                             f"{check_value}\n"
                             f"{end_operation}\n"
                             f"{check_labels}\n"
                             f"{restore_address}\n"
                             f"{set_destination}")

        if ARG1.is_register() and ARG1.register == 'D' and ARG2.is_address():
            
            if (
                (DST.is_register() and 'M' not in DST.registers) or
                DST.is_address()
            ):
                compute_value = f"@{ARG2.location}\n{ARG2.dereferences}\nD=D|M"
                check_value = f"@__orcheckfailed_{p}\nD;JEQ"
                end_operation = f"D=1\n@__endoroperation_{p}\n0;JMP"
                check_labels = (f"(__orcheckfailed_{p})\n"
                                 "D=0\n"
                                f"(__endoroperation_{p})")
                set_destination = (f"{DST.registers}=D" if
                                   DST.is_register() else
                                   f"@{DST.location}\n{DST.dereferences}\nM=D")
                return clean(f"{compute_value}\n"
                             f"{check_value}\n"
                             f"{end_operation}\n"
                             f"{check_labels}\n"
                             f"{set_destination}")
            elif DST.is_register() and 'M' in DST.registers:
                save_address = "M=D\nD=A\n@__aux\nAM=D\nD=M"
                compute_value = f"@{ARG2.location}\n{ARG2.dereferences}\nD=D|M"
                check_value = f"@__orcheckfailed_{p}\nD;JEQ"
                end_operation = f"D=1\n@__endoroperation_{p}\n0;JMP"
                check_labels = (f"(__orcheckfailed_{p})\n"
                                 "D=0\n"
                                f"(__endoroperation_{p})")
                restore_address = "@__aux\nA=M"
                set_destination = f"{DST.registers}=D"
                return clean(f"{save_address}\n"
                             f"{compute_value}\n"
                             f"{check_value}\n"
                             f"{end_operation}\n"
                             f"{check_labels}\n"
                             f"{restore_address}\n"
                             f"{set_destination}\n")

        raise ParserError('MCR', "[OR] Nevalidan argument.", o)

class XOR(SimpleMacro):
    arg_count = 3

    SIMPLE_OPS: dict[tuple[str, str], str] = {
        ('0', '0'): '0',
        ('1', '1'): '0',
        ('-1', '-1'): '0',

        ('0', '1'): '1',
        ('0', '-1'): '1',
        ('1', '-1'): '0',
        
        
        ('D', 'D'): '0',
        ('A', 'A'): '0',
        ('M', 'M'): '0',
    }

    COMPLEX_OPS: dict[tuple[str, str], str] = {

        ('D',  '1'): 'D=D',
        ('A',  '1'): 'D=A',
        ('M',  '1'): 'D=M',
        
        ('D', '-1'): 'D=D',
        ('A', '-1'): 'D=A',
        ('M', '-1'): 'D=M',
        
        ('D',  '0'): 'D=D',
        ('A',  '0'): 'D=A',
        ('M',  '0'): 'D=M',

    }

    def run(self, line: str, p: int, o: int) -> str:
        _ARG1 = self.arguments[1]
        _ARG2 = self.arguments[2]
        try:
            DST = Destination(self.arguments[0])
            ARG1 = Argument(_ARG1)
            ARG2 = Argument(_ARG2)
        except BadDestination:
            raise ParserError(
                'MCR',
                "[XOR] Destinacija mora biti jedan ili više registara,"
                "ili adresa.",
                o
            )
        except BadArgument:
            raise ParserError(
                'MCR',
                "[XOR] Argument mora biti registar, konstanta, ili adresa.",
                o
            )
        except OutOfBoundsConstantError:
            raise ParserError(
                'MCR', "[XOR] Konstanta mora biti u [-32768, 32767].", o
            )

        simple_op = (
            (_ARG1, _ARG2) if (_ARG1, _ARG2) in self.SIMPLE_OPS else
            (_ARG2, _ARG1) if (_ARG2, _ARG1) in self.SIMPLE_OPS else
            None
        )

        complex_op = (
            (_ARG1, _ARG2) if (_ARG1, _ARG2) in self.COMPLEX_OPS else
            (_ARG2, _ARG1) if (_ARG2, _ARG1) in self.COMPLEX_OPS else
            None
        )
        
        if DST.is_register() and simple_op:
            return f"{DST.registers}={self.SIMPLE_OPS[simple_op]}"
        elif DST.is_address() and simple_op:
            save_address = "D=A\n@__aux\nM=D"
            set_destination = (f"@{DST.location}\n"
                               f"{DST.dereferences}\n"
                               f"M={self.SIMPLE_OPS[simple_op]}")
            restore_address = "@__aux\nA=M"
            return clean(f"{save_address}\n"
                         f"{set_destination}\n"
                         f"{restore_address}")
        elif DST.is_register() and complex_op and 'D' in complex_op:
            jump_type = 'JEQ' if '0' in complex_op else 'JNE'
            # ne prezervira A registar
            if 'M' not in DST.registers:
                get_value = self.COMPLEX_OPS[complex_op]
                check_value = f"__xorcheckfailed_{p}\nD;{jump_type}"
                end_operation = f"D=1\n@__endxoroperation_{p}\n0;JMP"
                check_labels = (f"(__xorcheckfailed_{p})\n"
                                 "D=0\n"
                                f"(__endxoroperation_{p})")
                set_destination = f"{DST.registers}=D"
                return clean(f"{get_value}\n"
                             f"{check_value}\n"
                             f"{check_labels}\n"
                             f"{set_destination}")
            # ako je M jedna od lokacija u koju pišemo, slobodno ga
            # možemo koristiti kao pomoćni registar u koji možemo
            # spremiti operand. ovo nam pomaže da očuvamo A registar
            save_address = "M=D\nD=A\n@__aux\nAM=D\nD=M"
            get_value = self.COMPLEX_OPS[complex_op]
            check_value = f"@__xorcheckfailed_{p}\nD;{jump_type}"
            end_operation = f"D=1\n@__endxoroperation_{p}\n0;JMP"
            check_labels = (f"(__xorcheckfailed_{p})\n"
                             "D=0\n"
                            f"(__endxoroperation_{p})")
            restore_address = "@__aux\nA=M"
            set_destination = f"{DST.registers}=D"
            return clean(f"{save_address}\n"
                         f"{get_value}\n"
                         f"{check_value}\n"
                         f"{end_operation}\n"
                         f"{check_labels}\n"
                         f"{restore_address}\n"
                         f"{set_destination}")
        # ne prezervira A registar
        elif DST.is_address() and complex_op and 'D' in complex_op:
            jump_type = 'JEQ' if '0' in complex_op else 'JNE'
            get_value = self.COMPLEX_OPS[complex_op]
            check_value = f"@__xorcheckfailed_{p}\nD;{jump_type}"
            end_operation = f"D=1\n@__endxoroperation_{p}\n0;JMP"
            check_labels = (f"(__xorcheckfailed_{p})\n"
                             "D=0\n"
                            f"(__endxoroperation_{p})")
            set_destination = f"@{DST.location}\n{DST.dereferences}\nM=D"
            return clean(f"{get_value}\n"
                         f"{check_value}\n"
                         f"{end_operation}\n"
                         f"{check_labels}\n"
                         f"{set_destination}")
        elif DST.is_register() and complex_op and 'D' not in complex_op:
            jump_type = 'JEQ' if '0' in complex_op else 'JNE'
            save_address = "D=A\n@__aux\nAM=D"
            get_value = self.COMPLEX_OPS[complex_op]
            check_value = f"@__xorcheckfailed_{p}\nD;{jump_type}"
            end_operation = f"D=1\n@__endxoroperation_{p}\n0;JMP"
            check_labels = (f"(__xorcheckfailed_{p})\n"
                             "D=0\n"
                            f"(__endxoroperation_{p})")
            restore_address = "@__aux\nA=M"
            set_destination = "{DST.registers}=D"
            return clean(f"{save_address}\n"
                         f"{get_value}\n"
                         f"{check_value}\n"
                         f"{end_operation}\n"
                         f"{check_labels}\n"
                         f"{restore_address}\n"
                         f"{set_destination}")
        elif DST.is_address() and complex_op and 'D' not in complex_op:
            jump_type = 'JEQ' if '0' in complex_op else 'JNE'
            save_address = "D=A\n@__aux\nAM=D"
            get_value = self.COMPLEX_OPS[complex_op]
            check_value = f"@__xorcheckfailed_{p}\nD;{jump_type}"
            end_operation = f"D=1\n@__endxoroperation_{p}\n0;JMP"
            check_labels = (f"(__xorcheckfailed_{p})\n"
                             "D=0\n"
                            f"(__endxoroperation_{p})")
            set_destination = f"@{DST.location}\n{DST.dereferences}\nM=D"
            restore_address = "@__aux\nA=M"
            return clean(f"{save_address}\n"
                         f"{get_value}\n"
                         f"{check_value}\n"
                         f"{end_operation}\n"
                         f"{check_labels}\n"
                         f"{set_destination}\n"
                         f"{restore_address}")
        
        if (
            ARG1.is_register() and ARG2.is_register() and
            (ARG1.register, ARG2.register) in (('M', 'D'), ('D', 'M'))
        ):
            raise ParserError('MCR', "[XOR] Nemoguća operacija.", o)

        if (
            ARG1.is_register() and ARG2.is_register() and
            (ARG1.register, ARG2.register) in (('A', 'D'), ('D', 'A'))
        ):
            if (
                (DST.is_register() and 'M' not in DST.registers)
                or DST.is_address()
            ):
                raise ParserError('MCR', "[XOR] Nemoguća operacija.", o)

            save_address = "M=D\nD=A\n@__aux\nM=D"  # D = A now, check A first
            check_first = f"@__xorfirstfalse_{p}\nD;JEQ"
            get_D = "A=D\nD=M"
            check_value_false = f"@__xorcheckfailed_{p}\nD;JEQ"
            check_value_true = f"@__xorcheckfailed_{p}\nD;JNE"
            end_operation = f"D=1\n@__endxoroperation_{p}\n0;JMP"
            check_labels = (f"(__xorcheckfailed_{p})\n"
                             "D=0\n"
                            f"(__endxoroperation_{p})")
            restore_address = "@__aux\nA=M"
            set_destination = f"{DST.registers}=D"
            return clean(f"{save_address}\n"
                         f"{check_first}\n"
                         f"{get_D}\n"
                         f"{check_value_true}\n"
                         f"{end_operation}\n"
                         f"(__xorfirstfalse_{p})\n"
                         f"{get_D}\n"
                         f"{check_value_false}\n"
                         f"{end_operation}\n"
                         f"{check_labels}\n"
                         f"{restore_address}\n"
                         f"{set_destination}")
        
        if (
            ARG1.is_register() and ARG2.is_register() and
            (ARG1.register, ARG2.register) in (('A', 'M'), ('M', 'A'))
        ):

            save_address = "D=A\n@__aux\nAM=D"
            check_first = f"@__xorfirstfalse_{p}\nD;JEQ"
            get_M = "A=D\nD=M"
            check_value_false = f"@__xorcheckfailed_{p}\nD;JEQ"
            check_value_true = f"@__xorcheckfailed_{p}\nD;JNE"
            end_operation = f"D=1\n@__endxoroperation_{p}\n0;JMP"
            check_labels = (f"(__xorcheckfailed_{p})\n"
                             "D=0\n"
                            f"(__endxoroperation_{p})")
            restore_address = "@__aux\nA=M"

            if DST.is_register():
                set_destination = f"{DST.registers}=D"
                return clean(f"{save_address}\n"
                             f"{check_first}\n"
                             f"{get_M}\n"
                             f"{check_value_true}\n"
                             f"{end_operation}\n"
                             f"(__xorfirstfalse_{p})\n"
                             f"{get_M}\n"
                             f"{check_value_false}\n"
                             f"{end_operation}\n"
                             f"{check_labels}\n"
                             f"{restore_address}\n"
                             f"{set_destination}")
            else:
                set_destination = "@{DST.location}\n{DST.dereferences}\nM=D"
                return clean(f"{save_address}\n"
                             f"{check_first}\n"
                             f"{get_M}\n"
                             f"{check_value_true}\n"
                             f"{end_operation}\n"
                             f"(__xorfirstfalse_{p})\n"
                             f"{get_M}\n"
                             f"{check_value_false}\n"
                             f"{end_operation}\n"
                             f"{check_labels}\n"
                             f"{set_destination}\n"
                             f"{restore_address}")
        
        if ARG2.is_register() and ARG1.is_constant():
            ARG1, ARG2 = ARG2, ARG1

        if ARG1.is_register() and ARG2.is_constant():
            jump_type = 'JNE' if ARG2.constant else 'JEQ'
            if DST.is_address() and ARG1.register != 'D':
                save_address = "D=A\n@__aux\nAM=D"
                compute_value = f"D={ARG1.register}"
                check_value = f"@__xorcheckfailed_{p}\nD;{jump_type}"
                end_operation = f"D=1\n@__endxoroperation_{p}\n0;JMP"
                check_labels = (f"(__xorcheckfailed_{p})\n"
                                 "D=0\n"
                                f"(__endxoroperation_{p})")
                set_destination = (f"@{DST.location}\n"
                                   f"{DST.dereferences}\n"
                                    "M=D")
                restore_address = "@__aux\nA=M"
                return clean(f"{save_address}\n"
                             f"{compute_value}\n"
                             f"{check_value}\n"
                             f"{end_operation}\n"
                             f"{check_labels}\n"
                             f"{set_destination}\n"
                             f"{restore_address}")
            # ne prezervira A registar
            elif DST.is_address() and ARG1.register == 'D':
                check_value = f"@__xorcheckfailed_{p}\nD;{jump_type}"
                end_operation = f"D=1\n@__endxoroperation_{p}\n0;JMP"
                check_labels = (f"(__xorcheckfailed_{p})\n"
                                 "D=0\n"
                                f"(__endxoroperation_{p})")
                set_destination = (f"@{DST.location}\n"
                                   f"{DST.dereferences}\n"
                                    "M=D")
                return clean(f"{check_value}\n"
                             f"{end_operation}\n"
                             f"{check_labels}\n"
                             f"{set_destination}")
            elif DST.is_register() and ARG1.register != 'D':
                save_address = "D=A\n@__aux\nAM=D"
                compute_value = f"D={ARG1.register}"
                check_value = f"@__xorcheckfailed_{p}\nD;{jump_type}"
                end_operation = f"D=1\n@__endxoroperation_{p}\n0;JMP"
                check_labels = (f"(__xorcheckfailed_{p})\n"
                                 "D=0\n"
                                f"(__endxoroperation_{p})")
                restore_address = "@__aux\nA=M"
                set_destination = f"{DST.registers}=D"
                return clean(f"{save_address}\n"
                             f"{compute_value}\n"
                             f"{check_value}\n"
                             f"{end_operation}\n"
                             f"{check_labels}\n"
                             f"{restore_address}\n"
                             f"{set_destination}")
            elif DST.is_register() and ARG1.register == 'D':
                check_value = f"@__xorcheckfailed_{p}\nD;{jump_type}"
                end_operation = f"D=1\n@__endxoroperation_{p}\n0;JMP"
                check_labels = (f"(__xorcheckfailed_{p})\n"
                                 "D=0\n"
                                f"(__endxoroperation_{p})")
                set_destination = "{DST.registers}=D"
                # ne prezervira A registar
                if 'M' not in DST.registers:
                    return (f"{check_value}\n"
                            f"{end_operation}\n"
                            f"{check_labels}\n"
                            f"{set_destination}")
                save_address = "M=D\nD=A\n@__aux\nAM=D\nD=M"
                restore_address = "@__aux\nA=M"
                return clean(f"{save_address}\n"
                             f"{check_value}\n"
                             f"{check_labels}\n"
                             f"{restore_address}\n"
                             f"{set_destination}")

        if ARG1.is_constant() and ARG2.is_constant():
            if DST.is_register():
                return (
                    f"{DST.registers}="
                    f"{int(bool(ARG1.constant) != bool(ARG2.constant))}"
                )
            else:
                save_address = "D=A\n@__aux\nM=D"
                set_destination = (
                    f"@{DST.location}\n"
                    f"{DST.dereferences}\n"
                    f"M={int(bool(ARG1.constant) != bool(ARG2.constant))}"
                )
                restore_address = "@__aux\nA=M"
                return clean(f"{save_address}\n"
                             f"{set_destination}\n"
                             f"{restore_address}")

        if ARG2.is_constant() and ARG1.is_address():
            ARG1, ARG2 = ARG2, ARG1

        if ARG1.is_constant() and ARG2.is_address():
            jump_type = 'JNE' if ARG2.constant else 'JEQ'
            save_address = "D=A\n@__aux\nM=D"
            compute_value = f"@{ARG2.location}\n{ARG2.dereferences}\nD=M"
            check_value = f"@__xorcheckfailed_{p}\nD;{jump_type}"
            end_operation = f"D=1\n@__endxoroperation_{p}\n0;JMP"
            check_labels = (f"(__xorcheckfailed_{p})\n"
                             "D=0\n"
                            f"(__endxoroperation_{p})")
            restore_address = "@__aux\nA=M"
            if DST.is_address():
                set_destination = (f"@{DST.location}\n"
                                   f"{DST.dereferences}\n"
                                    "M=D")
                return clean(f"{save_address}\n"
                             f"{compute_value}\n"
                             f"{check_value}\n"
                             f"{end_operation}\n"
                             f"{check_labels}\n"
                             f"{set_destination}\n"
                             f"{restore_address}")
            else:
                set_destination = f"{DST.registers}=D"
                return clean(f"{save_address}\n"
                             f"{compute_value}\n"
                             f"{check_value}\n"
                             f"{end_operation}\n"
                             f"{check_labels}\n"
                             f"{restore_address}\n"
                             f"{set_destination}")

        if ARG1.is_address() and ARG2.is_address():
            save_address = "D=A\n@__aux\nM=D"
            get_value1 = f"@{ARG1.location}\n{ARG1.dereferences}\nD=M"
            check_first = f"@__xorfirstfalse_{p}\nD;JEQ"
            get_value2 = f"@{ARG2.location}\n{ARG2.dereferences}\nD=M"
            check_value_true = f"@__xorcheckfailed_{p}\nD;JNE"
            end_operation = f"D=1\n@__endxoroperation_{p}\n0;JMP"
            check_value_false = f"@__xorcheckfailed_{p}\nD;JEQ"
            check_labels = (f"(__xorcheckfailed_{p})\n"
                             "D=0\n"
                            f"(__endxoroperation_{p})")
            restore_address = "@__aux\nA=M"

            if DST.is_address():
                set_destination = f"@{DST.location}\n{DST.dereferences}\nM=D"
                return clean(f"{save_address}\n"
                             f"{get_value1}\n"
                             f"{check_first}\n"
                             f"{get_value2}\n"
                             f"{check_value_true}\n"
                             f"{end_operation}\n"
                             f"(__xorfirstfalse_{p})\n"
                             f"{get_value2}\n"
                             f"{check_value_false}\n"
                             f"{end_operation}\n"
                             f"{check_labels}\n"
                             f"{set_destination}\n"
                             f"{restore_address}")
            else:
                set_destination = f"{DST.registers}=D"
                return clean(f"{save_address}\n"
                             f"{get_value1}\n"
                             f"{check_first}\n"
                             f"{get_value2}\n"
                             f"{check_value_true}\n"
                             f"{end_operation}\n"
                             f"(__xorfirstfalse_{p})\n"
                             f"{get_value2}\n"
                             f"{check_value_false}\n"
                             f"{end_operation}\n"
                             f"{check_labels}\n"
                             f"{restore_address}\n"
                             f"{set_destination}")

        if ARG2.is_register() and ARG1.is_address():
            ARG1, ARG2 = ARG2, ARG1
        
        if ARG1.is_register() and ARG1.register != 'D' and ARG2.is_address():
            
            save_address = "D=A\n@__aux\nM=D"
            get_value1 = f"D={ARG1.register}"
            check_first = f"@__xorfirstfalse_{p}\nD;JEQ"
            get_value2 = f"@{ARG2.location}\n{ARG2.dereferences}\nD=M"
            check_value_true = f"@__xorcheckfailed_{p}\nD;JNE"
            end_operation = f"D=1\n@__endxoroperation_{p}\n0;JMP"
            check_value_false = f"@__xorcheckfailed_{p}\nD;JEQ"
            check_labels = (f"(__xorcheckfailed_{p})\n"
                             "D=0\n"
                            f"(__endxoroperation_{p})")
            restore_address = "@__aux\nA=M"

            if DST.is_address():
                set_destination = f"@{DST.location}\n{DST.dereferences}\nM=D"
                return clean(f"{save_address}\n"
                             f"{get_value1}\n"
                             f"{check_first}\n"
                             f"{get_value2}\n"
                             f"{check_value_true}\n"
                             f"{end_operation}\n"
                             f"(__xorfirstfalse_{p})\n"
                             f"{get_value2}\n"
                             f"{check_value_false}\n"
                             f"{end_operation}\n"
                             f"{check_labels}\n"
                             f"{set_destination}\n"
                             f"{restore_address}")
            else:
                set_destination = f"{DST.registers}=D"
                return clean(f"{save_address}\n"
                             f"{get_value1}\n"
                             f"{check_first}\n"
                             f"{get_value2}\n"
                             f"{check_value_true}\n"
                             f"{end_operation}\n"
                             f"(__xorfirstfalse_{p})\n"
                             f"{get_value2}\n"
                             f"{check_value_false}\n"
                             f"{end_operation}\n"
                             f"{check_labels}\n"
                             f"{restore_address}\n"
                             f"{set_destination}")

        if ARG1.is_register() and ARG1.register == 'D' and ARG2.is_address():

            if (
                (DST.is_register() and 'M' not in DST.registers) or
                DST.is_address()
            ):
                check_first = f"@__xorfirstfalse_{p}\nD;JEQ"
                get_value2 = f"@{ARG2.location}\n{ARG2.dereferences}\nD=M"
                check_value_true = f"@__xorcheckfailed_{p}\nD;JNE"
                end_operation = f"D=1\n@__endxoroperation_{p}\n0;JMP"
                check_value_false = f"@__xorcheckfailed_{p}\nD;JEQ"
                check_labels = (f"(__xorcheckfailed_{p})\n"
                                 "D=0\n"
                                f"(__endxoroperation_{p})")
                set_destination = (f"{DST.registers}=D" if
                                   DST.is_register() else
                                   f"@{DST.location}\n{DST.dereferences}\nM=D")
                return clean(f"{check_first}\n"
                             f"{get_value2}\n"
                             f"{check_value_true}\n"
                             f"{end_operation}\n"
                             f"(__xorfirstfalse_{p})\n"
                             f"{get_value2}\n"
                             f"{check_value_false}\n"
                             f"{end_operation}\n"
                             f"{check_labels}\n"
                             f"{set_destination}")

            elif DST.is_register() and 'M' in DST.registers:
                save_address = "M=D\nD=A\n@__aux\nAM=D\nD=M"
                check_first = f"@__xorfirstfalse_{p}\nD;JEQ"
                get_value2 = f"@{ARG2.location}\n{ARG2.dereferences}\nD=M"
                check_value_true = f"@__xorcheckfailed_{p}\nD;JNE"
                end_operation = f"D=1\n@__endxoroperation_{p}\n0;JMP"
                check_value_false = f"@__xorcheckfailed_{p}\nD;JEQ"
                check_labels = (f"(__xorcheckfailed_{p})\n"
                                 "D=0\n"
                                f"(__endxoroperation_{p})")
                restore_address = "@__aux\nA=M"
                set_destination = (f"{DST.registers}=D" if
                                   DST.is_register() else
                                   f"@{DST.location}\n{DST.dereferences}\nM=D")
                return clean(f"{save_address}\n"
                             f"{check_first}\n"
                             f"{get_value2}\n"
                             f"{check_value_true}\n"
                             f"{end_operation}\n"
                             f"(__xorfirstfalse_{p})\n"
                             f"{get_value2}\n"
                             f"{check_value_false}\n"
                             f"{end_operation}\n"
                             f"{check_labels}\n"
                             f"{restore_address}\n"
                             f"{set_destination}")

        raise ParserError('MCR', "[OR] Nevalidan argument.", o)

class NOT(SimpleMacro):
    arg_count = 2

    SIMPLE_OPS: dict[str, str] = {
        '0': '1',
        '1': '0',
        '-1': '0',
    }

    COMPLEX_OPS: dict[str, str] = {
        'D': 'D=D',
        'A': 'D=A',
        'M': 'D=M',
    }

    def run(self, line: str, p: int, o: int) -> str:
        _ARG1 = self.arguments[1]
        try:
            DST = Destination(self.arguments[0])
            ARG1 = Argument(_ARG1)
        except BadDestination:
            raise ParserError(
                'MCR',
                "[NOT] Destinacija mora biti jedan ili više registara,"
                "ili adresa.",
                o
            )
        except BadArgument:
            raise ParserError(
                'MCR',
                "[NOT] Argument mora biti registar, konstanta, ili adresa.",
                o
            )
        except OutOfBoundsConstantError:
            raise ParserError(
                'MCR', "[NOT] Konstanta mora biti u [-32768, 32767].", o
            )

        simple_op = _ARG1 if _ARG1 in self.SIMPLE_OPS else None
        complex_op = _ARG1 if _ARG1 in self.COMPLEX_OPS else None

        if DST.is_register() and simple_op:
            return f"{DST.registers}={self.SIMPLE_OPS[simple_op]}"
        elif DST.is_address() and simple_op:
            save_address = "D=A\n@__aux\nM=D"
            set_destination = (f"@{DST.location}\n"
                               f"{DST.dereferences}\n"
                               f"M={self.SIMPLE_OPS[simple_op]}")
            restore_address = "@__aux\nA=M"
            return clean(f"{save_address}\n"
                         f"{set_destination}\n"
                         f"{restore_address}")
        elif DST.is_register() and complex_op and 'D' in complex_op:
            # ne prezervira A registar
            if 'M' not in DST.registers:
                get_value = self.COMPLEX_OPS[complex_op]
                check_value = f"__notfalse_{p}\nD;JEQ"
                end_operation = f"D=0\n@__endnotoperation_{p}\n0;JMP"
                check_labels = (f"(__notfalse_{p})\n"
                                 "D=1\n"
                                f"(__endnotoperation_{p})")
                set_destination = f"{DST.registers}=D"
                return clean(f"{get_value}\n"
                             f"{check_value}\n"
                             f"{check_labels}\n"
                             f"{set_destination}")
            # ako je M jedna od lokacija u koju pišemo, slobodno ga
            # možemo koristiti kao pomoćni registar u koji možemo
            # spremiti operand. ovo nam pomaže da očuvamo A registar
            save_address = "M=D\nD=A\n@__aux\nAM=D\nD=M"
            get_value = self.COMPLEX_OPS[complex_op]
            check_value = f"@__notfalse_{p}\nD;JEQ"
            end_operation = f"D=0\n@__endnotoperation_{p}\n0;JMP"
            check_labels = (f"(__notfalse_{p})\n"
                             "D=1\n"
                            f"(__endnotoperation_{p})")
            restore_address = "@__aux\nA=M"
            set_destination = f"{DST.registers}=D"
            return clean(f"{save_address}\n"
                         f"{get_value}\n"
                         f"{check_value}\n"
                         f"{end_operation}\n"
                         f"{check_labels}\n"
                         f"{restore_address}\n"
                         f"{set_destination}")
        # ne prezervira A registar
        elif DST.is_address() and complex_op and 'D' in complex_op:
            get_value = self.COMPLEX_OPS[complex_op]
            check_value = f"@__notfalse_{p}\nD;JEQ"
            end_operation = f"D=0\n@__endnotoperation_{p}\n0;JMP"
            check_labels = (f"(__notfalse_{p})\n"
                             "D=1\n"
                            f"(__endnotoperation_{p})")
            set_destination = f"@{DST.location}\n{DST.dereferences}\nM=D"
            return clean(f"{get_value}\n"
                         f"{check_value}\n"
                         f"{end_operation}\n"
                         f"{check_labels}\n"
                         f"{set_destination}")
        elif DST.is_register() and complex_op and 'D' not in complex_op:
            save_address = "D=A\n@__aux\nAM=D"
            get_value = self.COMPLEX_OPS[complex_op]
            check_value = f"@__notfalse_{p}\nD;JEQ"
            end_operation = f"D=0\n@__endnotoperation_{p}\n0;JMP"
            check_labels = (f"(__notfalse_{p})\n"
                             "D=1\n"
                            f"(__endnotoperation_{p})")
            restore_address = "@__aux\nA=M"
            set_destination = "{DST.registers}=D"
            return clean(f"{save_address}\n"
                         f"{get_value}\n"
                         f"{check_value}\n"
                         f"{end_operation}\n"
                         f"{check_labels}\n"
                         f"{restore_address}\n"
                         f"{set_destination}")
        elif DST.is_address() and complex_op and 'D' not in complex_op:
            save_address = "D=A\n@__aux\nAM=D"
            get_value = self.COMPLEX_OPS[complex_op]
            check_value = f"@__notfalse_{p}\nD;JEQ"
            end_operation = f"D=0\n@__endnotoperation_{p}\n0;JMP"
            check_labels = (f"(__notfalse_{p})\n"
                             "D=1\n"
                            f"(__endnotoperation_{p})")
            set_destination = f"@{DST.location}\n{DST.dereferences}\nM=D"
            restore_address = "@__aux\nA=M"
            return clean(f"{save_address}\n"
                         f"{get_value}\n"
                         f"{check_value}\n"
                         f"{end_operation}\n"
                         f"{check_labels}\n"
                         f"{set_destination}\n"
                         f"{restore_address}")
        
        if ARG1.is_constant():
            if DST.is_address():
                save_address = "D=A\n@__aux\nM=D"
                set_destination = (f"@{DST.location}\n"
                                   f"{DST.dereferences}\n"
                                   f"M={int(not ARG1.constant)}")
                restore_address = "@__aux\nA=M"
                return clean(
                    f"{save_address}\n{set_destination}\n{restore_address}"
                )
            else:
                return f"{DST.registers}={int(not ARG1.constant)}"

        save_address = "D=A\n@__aux\nM=D"
        get_value = f"@{ARG1.location}\n{ARG1.dereferences}\nD=M"
        check_value = f"@__notfalse_{p}\nD;JEQ"
        end_operation = f"D=0\n@__endnotoperation_{p}\n0;JMP"
        check_labels = f"(__notfalse_{p})\nD=1\n(__endnotoperation_{p})"
        set_destination = (f"@{ARG1.location}\n{ARG1.dereferences}\nM=D"
                           if DST.is_address() else
                           f"{DST.registers}=D")
        restore_address = "@__aux\nA=M"
        if DST.is_address():
            return clean(f"{save_address}\n"
                         f"{get_value}\n"
                         f"{check_value}\n"
                         f"{end_operation}\n"
                         f"{check_labels}\n"
                         f"{set_destination}\n"
                         f"{restore_address}")
        else:
            return clean(f"{save_address}\n"
                         f"{get_value}\n"
                         f"{check_value}\n"
                         f"{end_operation}\n"
                         f"{check_labels}\n"
                         f"{restore_address}\n"
                         f"{set_destination}")

class MULT(SimpleMacro):
    arg_count = 3

    def run(self, line: str, p: int, o: int) -> str:
        _ARG1 = self.arguments[1]
        _ARG2 = self.arguments[2]
        try:
            DST = Destination(self.arguments[0])
            ARG1 = Argument(_ARG1)
            ARG2 = Argument(_ARG2)
        except BadDestination:
            raise ParserError(
                'MCR',
                "[MULT] Destinacija mora biti jedan ili više registara,"
                "ili adresa.",
                o
            )
        except BadArgument:
            raise ParserError(
                'MCR',
                "[MULT] Argument mora biti registar, konstanta, ili adresa.",
                o
            )
        except OutOfBoundsConstantError:
            raise ParserError(
                'MCR', "[MULT] Konstanta mora biti u [-32768, 32767].", o
            )
        
        premult, postmult = None, None

        if (
            (ARG2.is_oneop() and ARG1.is_constant()) or
            (ARG2.is_oneop() and ARG1.is_address()) or
            (ARG2.is_constant() and ARG1.is_address())
        ):
            ARG1, ARG2 = ARG2, ARG1

        if ARG1.is_oneop() and ARG2.is_oneop():
            match (ARG1.oneop, ARG2.oneop):
                case ('0', _) | (_, '0'):
                    if DST.is_register():
                        return clean(f"{DST.registers}=0")
                    return clean( "D=A\n@__aux\nM=D\n"
                                 f"@{DST.location}\n{DST.dereferences}\nM=0\n"
                                  "@__aux\nA=M")
                case ('1', '1') | ('-1', '-1') | ('1', '-1') | ('-1', '1'):
                    result = '1' if ARG1.oneop == ARG2.oneop else '-1'
                    if DST.is_register():
                        return clean(f"{DST.registers}={result}")
                    return clean( "D=A\n@__aux\nM=D\n"
                                 f"@{DST.location}\n{DST.dereferences}\n"
                                 f"M={result}\n"
                                  "@__aux\nA=M")
                case (
                    ('1' as number_sign, reg) |
                    (reg, '1' as number_sign) |
                    ('-1' as number_sign, reg) |
                    (reg, '-1' as number_sign)
                ):
                    sign = number_sign.rstrip('1')
                    if DST.is_register():
                        return clean(f"{DST.registers}={sign}{reg}")
                    # ne prezervira A registar
                    if reg == 'D':
                        return (f"@{DST.location}\n"
                                f"{DST.dereferences}\n"
                                f"M={sign}{reg}")
                    return clean( "D=A\n@__aux\nAM=D\nD={sign}{reg}\n"
                                 f"@{DST.location}\n{DST.dereferences}\n"
                                 f"M=D\n"
                                  "@__aux\nA=M")
                case ('D', 'D'):
                    if DST.is_register() and 'M' in DST.registers:
                        premult = ("M=D\nD=A\n__aux\nAM=D\nD=M\n"
                                   "@__multresult\nM=0\n"
                                   "@__multarg1\nM=D\n"
                                   "@__multarg2\nM=D")
                        postmult = ( "@__multresult\nD=M\n"
                                    f"@__aux\nA=M\n{DST.registers}=D")
                    # ne prezervira A registar
                    else:
                        premult = ("@__multresult\nM=0\n"
                                   "@__multarg1\nM=D\n"
                                   "@__multarg2\nM=D")
                        if DST.is_register():
                            postmult = f"@__multresult\nD=M\n{DST.registers}=D"
                        else:
                            postmult = ( "@__multresult\nD=M\n"
                                        f"@{DST.location}\n"
                                        f"{DST.dereferences}\nM=D")

                case ('A', 'D') | ('D', 'A'):
                    if DST.is_register() and 'M' in DST.registers:
                        premult = ("M=D\nD=A\n__aux\nAM=D\n"
                                   "@__multresult\nM=0\n"
                                   "@__multarg1\nM=D\n"
                                   "A=D\nD=M\n"
                                   "@__multarg2\nM=D")
                        postmult = ( "@__multresult\nD=M\n"
                                    f"@__aux\nA=M\n{DST.registers}=D")
                    else:
                        raise ParserError(
                            'MCR', "[MULT] Nemoguća operacija", o
                        )
                case ('M', 'D') | ('D', 'M'):
                    raise ParserError('MCR', "[MULT] Nemoguća operacija", o)
                case ('M', 'M') | ('M', 'A') | ('A', 'M') | ('A', 'A'):
                    if ARG1.oneop == ARG2.oneop:
                        premult = (f"D=A\n__aux\nAM=D\nD={ARG1.oneop}\n"
                                    "@__multresult\nM=0\n"
                                    "@__multarg1\nM=D\n"
                                    "@__multarg2\nM=D")
                    else:
                        premult = ( "D=A\n__aux\nAM=D\n"
                                   f"D={ARG1.oneop}\n"
                                    "@__multresult\nM=0\n"
                                    "@__multarg1\nM=D\n"
                                   f"@__aux\nA=M\n"
                                   f"D={ARG2.oneop}\n"
                                    "@__multarg2\nM=D")
                    if DST.is_register():
                        postmult = ( "@__multresult\nD=M\n"
                                     "@__aux\nA=M\n"
                                    f"{DST.registers}=D")
                    else:
                        postmult = ( "@__multresult\nD=M\n"
                                    f"@{DST.location}\n"
                                    f"{DST.dereferences}\nM=D\n"
                                     "@__aux\nA=M")
    

        elif ARG1.is_oneop() and ARG2.is_constant():
            match (ARG1.oneop):
                case '0':
                    if DST.is_register():
                        return clean(f"{DST.registers}=0")
                    return clean( "D=A\n@__aux\nM=D\n"
                                 f"@{DST.location}\n{DST.dereferences}\nM=0\n"
                                  "@__aux\nA=M")
                case '1' | '-1':
                    constant = ARG2.constant * int(ARG1.oneop)
                    if constant == 32768:
                        constant = -32768

                    save_address = "D=A\n@__aux\nM=D"
                    compute_value = (
                        f"@{constant if constant >= 0 else ~constant}\n"
                        f"D={'A' if constant >= 0 else '!A'}"
                    )
                    restore_address = "@__aux\nA=M"
                    if DST.is_register():
                        set_destination = f"{DST.registers}=D"
                        return clean(f"{save_address}\n"
                                     f"{compute_value}\n"
                                     f"{restore_address}\n"
                                     f"{set_destination}")
                    set_destination = (f"@{DST.location}\n"
                                       f"{DST.dereferences}\n"
                                        "M=D")
                    return clean(f"{save_address}\n"
                                 f"{compute_value}\n"
                                 f"{set_destination}\n"
                                 f"{restore_address}")
                case 'M' | 'A':
                    premult = ( "D=A\n@__aux\nAM=D\n"
                               f"D={ARG1.oneop}\n"
                                "@__multresult\nM=0\n"
                                "@__multarg1\nM=D\n"
                               f"@{ARG2.constant
                                   if ARG2.constant >= 0 else
                                   ~ARG2.constant}\n"
                               f"D={'A' if ARG2.constant >= 0 else '!A'}\n"
                                "@__multarg2\nM=D")
                    if DST.is_register():
                        postmult = ( "@__multresult\nD=M\n"
                                    f"@__aux\nA=M\n{DST.registers}=D")
                    else:
                        postmult = ( "@__multresult\nD=M\n"
                                    f"@{DST.location}\n"
                                    f"{DST.dereferences}\nM=D\n"
                                     "@__aux\nA=M")
                case 'D':
                    if DST.is_register() and 'M' in DST.registers:
                        premult = ( "M=D\nD=A\n__aux\nAM=D\nD=M\n"
                                    "@__multresult\nM=0\n"
                                    "@__multarg1\nM=D\n"
                                   f"@{ARG2.constant
                                       if ARG2.constant >= 0 else
                                       ~ARG2.constant}\n"
                                   f"D={'A' if ARG2.constant >= 0 else '!A'}\n"
                                    "@__multarg2\nM=D")
                        postmult = ( "@__multresult\nD=M\n"
                                    f"@__aux\nA=M\n{DST.registers}=D")
                    # ne prezervira A registar
                    else:
                        premult = ("@__multresult\nM=0\n"
                                   "@__multarg1\nM=D\n"
                                   f"@{ARG2.constant
                                       if ARG2.constant >= 0 else
                                       ~ARG2.constant}\n"
                                   f"D={'A' if ARG2.constant >= 0 else '!A'}\n"
                                   "@__multarg2\nM=D")
                        if DST.is_register():
                            postmult = f"@__multresult\nD=M\n{DST.registers}=D"
                        else:
                            postmult = ( "@__multresult\nD=M\n"
                                        f"@{DST.location}\n"
                                        f"{DST.dereferences}\nM=D")

        elif ARG1.is_oneop() and ARG2.is_address():
            match (ARG1.oneop):
                case '0':
                    if DST.is_register():
                        return clean(f"{DST.registers}=0")
                    return clean( "D=A\n@__aux\nM=D\n"
                                 f"@{DST.location}\n{DST.dereferences}\nM=0\n"
                                  "@__aux\nA=M")
                case '1' | '-1':
                    sign = ARG1.oneop.rstrip('1')

                    save_address = "D=A\n@__aux\nM=D"
                    compute_value = (
                        f"@{ARG2.location}\n{ARG2.dereferences}\nD={sign}M"
                    )
                    restore_address = "@__aux\nA=M"
                    if DST.is_register():
                        set_destination = f"{DST.registers}=D"
                        return clean(f"{save_address}\n"
                                     f"{compute_value}\n"
                                     f"{restore_address}\n"
                                     f"{set_destination}")
                    set_destination = (f"@{DST.location}\n"
                                       f"{DST.dereferences}\n"
                                        "M=D")
                    return clean(f"{save_address}\n"
                                 f"{compute_value}\n"
                                 f"{set_destination}\n"
                                 f"{restore_address}")
                case 'M' | 'A':
                    premult = ( "D=A\n@__aux\nAM=D\n"
                               f"D={ARG1.oneop}\n"
                                "@__multresult\nM=0\n"
                                "@__multarg1\nM=D\n"
                               f"@{ARG2.location}\n{ARG2.dereferences}\nD=M\n"
                                "@__multarg2\nM=D")
                    if DST.is_register():
                        postmult = ( "@__multresult\nD=M\n"
                                    f"@__aux\nA=M\n{DST.registers}=D")
                    else:
                        postmult = ( "@__multresult\nD=M\n"
                                    f"@{DST.location}\n"
                                    f"{DST.dereferences}\nM=D\n"
                                     "@__aux\nA=M")
                case 'D':
                    if DST.is_register() and 'M' in DST.registers:
                        premult = ( "M=D\nD=A\n__aux\nAM=D\nD=M\n"
                                    "@__multresult\nM=0\n"
                                    "@__multarg1\nM=D\n"
                                   f"@{ARG2.location}\n"
                                   f"{ARG2.dereferences}\nD=M\n"
                                    "@__multarg2\nM=D")
                        postmult = ( "@__multresult\nD=M\n"
                                    f"@__aux\nA=M\n{DST.registers}=D")
                    # ne prezervira A registar
                    else:
                        premult = ("@__multresult\nM=0\n"
                                   "@__multarg1\nM=D\n"
                                   f"@{ARG2.location}\n"
                                   f"{ARG2.dereferences}\nD=M\n"
                                   "@__multarg2\nM=D")
                        if DST.is_register():
                            postmult = f"@__multresult\nD=M\n{DST.registers}=D"
                        else:
                            postmult = ( "@__multresult\nD=M\n"
                                        f"@{DST.location}\n"
                                        f"{DST.dereferences}\nM=D")
        elif ARG1.is_constant() and ARG2.is_constant():
            constant = ((ARG1.constant*ARG2.constant + 32768) & 0xffff) - 32768

            save_address = "D=A\n@__aux\nM=D"
            compute_value = (
                f"@{constant if constant >= 0 else ~constant}\n"
                f"D={'A' if constant >= 0 else '!A'}"
            )
            restore_address = "@__aux\nA=M"
            if DST.is_register():
                set_destination = f"{DST.registers}=D"
                return clean(f"{save_address}\n"
                             f"{compute_value}\n"
                             f"{restore_address}\n"
                             f"{set_destination}")

            set_destination = (f"@{DST.location}\n"
                               f"{DST.dereferences}\n"
                                "M=D")
            return clean(f"{save_address}\n"
                         f"{compute_value}\n"
                         f"{set_destination}\n"
                         f"{restore_address}")

        elif ARG1.is_constant() and ARG2.is_address():
            save_address = "D=A\n@__aux\nM=D"
            load_value1 = (
                f"@{ARG1.constant if ARG1.constant >= 0 else ~ARG1.constant}\n"
                f"D={'A' if ARG1.constant >= 0 else '!A'}"
            )
            load_value2 = (
                f"@{ARG2.location}\n{ARG2.dereferences}\nD=M"
            )
            restore_address = "@__aux\nA=M"
            premult = (f"{save_address}\n"
                       f"{load_value1}\n"
                        "@__multresult\nM=0\n"
                        "@__multarg1\nM=D\n"
                       f"{load_value2}\n"
                        "@__multarg2\nM=D")
            if DST.is_register():
                postmult = ( "@__multresult\nD=M\n"
                            f"{restore_address}\n"
                            f"{DST.registers}=D")
            else:
                postmult = ( "@__multresult\nD=M\n"
                            f"@{DST.location}\n{DST.dereferences}\nM=D\n"
                            f"{restore_address}")

        elif ARG1.is_address() and ARG2.is_address():
            save_address = "D=A\n@__aux\nM=D"
            load_value1 = (
                f"@{ARG1.location}\n{ARG1.dereferences}\nD=M"
            )
            load_value2 = (
                f"@{ARG2.location}\n{ARG2.dereferences}\nD=M"
            )
            restore_address = "@__aux\nA=M"
            premult = (f"{save_address}\n"
                       f"{load_value1}\n"
                        "@__multresult\nM=0\n"
                        "@__multarg1\nM=D\n"
                       f"{load_value2}\n"
                        "@__multarg2\nM=D")
            if DST.is_register():
                postmult = ( "@__multresult\nD=M\n"
                            f"{restore_address}\n"
                            f"{DST.registers}=D")
            else:
                postmult = ( "@__multresult\nD=M\n"
                            f"@{DST.location}\n{DST.dereferences}\nM=D\n"
                            f"{restore_address}")
        
        start_portion = (
             "@__multarg1\nD=M\n@32767\nA=!A\nD=D&A\n"
            f"@__mult_2p14_{p}\nD;JEQ\n"
             "@__multarg2\nD=-M\n"
             "@__multhelper\nM=D\n"
            f"{'\n'.join(['MD=M+D']*15)}\n"
             "@__multresult\nM=M+D"
        )
        middle_parts = '\n'.join([
            (
                f"(__mult_2p{power}_{p})\n"
                 "@__multarg1\nD=M\n"
                f"@{2**power}\nD=D&A\n"
                f"@__mult_2p{power-1}_{p}\nD;JEQ\n"
                 "@__multarg2\nD=M\n"
                 "@__multhelper\nM=D\n"
                f"{'\n'.join(['MD=M+D']*power)}\n"
                 "@__multresult\nM=M+D"
            ) for power in range(14, 0, -1)
        ])
        end_portion = (
            f"(__mult_2p0_{p})\n"
             "@__multarg1\nD=M\n"
             "@1\nD=D&A\n"
            f"@__multend_{p}\nD;JEQ\n"
            f"@__multarg2\nD=M\n"
            f"@__multresult\nM=M+D\n"
            f"(__multend_{p})"
        )

        mult_algorithm = f"{start_portion}\n{middle_parts}\n{end_portion}"

        return clean(f"{premult}\n{mult_algorithm}\n{postmult}")

class DIV(SimpleMacro):
    arg_count = 3

    def run(self, line: str, p: int, o: int) -> str:
        _ARG1 = self.arguments[1]
        _ARG2 = self.arguments[2]
        try:
            DST = Destination(self.arguments[0])
            ARG1 = Argument(_ARG1)
            ARG2 = Argument(_ARG2)
        except BadDestination:
            raise ParserError(
                'MCR',
                "[DIV] Destinacija mora biti jedan ili više registara,"
                "ili adresa.",
                o
            )
        except BadArgument:
            raise ParserError(
                'MCR',
                "[DIV] Argument mora biti registar, konstanta, ili adresa.",
                o
            )
        except OutOfBoundsConstantError:
            raise ParserError(
                'MCR', "[DIV] Konstanta mora biti u [-32768, 32767].", o
            )
        
        premult, postmult = None, None
        swap = False
        if (
            (ARG2.is_oneop() and ARG1.is_constant()) or
            (ARG2.is_oneop() and ARG1.is_address()) or
            (ARG2.is_constant() and ARG1.is_address())
        ):
            ARG1, ARG2 = ARG2, ARG1
            swap = True

        if ARG1.is_oneop() and ARG2.is_oneop():
            match (ARG1.oneop, ARG2.oneop):
                case (arg1, arg2) if arg1 == arg2:
                    if DST.is_register():
                        return clean(f"{DST.registers}=1")
                    return clean( "D=A\n@__aux\nM=D\n"
                                 f"@{DST.location}\n{DST.dereferences}\n"
                                 f"M=1\n"
                                  "@__aux\nA=M")
                case ('0', _) | (_, '0'):
                    if DST.is_register():
                        return clean(f"{DST.registers}=0")
                    return clean( "D=A\n@__aux\nM=D\n"
                                 f"@{DST.location}\n{DST.dereferences}\nM=0\n"
                                  "@__aux\nA=M")
                case ('1', '1') | ('-1', '-1') | ('1', '-1') | ('-1', '1'):
                    result = '1' if ARG1.oneop == ARG2.oneop else '-1'
                    if DST.is_register():
                        return clean(f"{DST.registers}={result}")
                    return clean( "D=A\n@__aux\nM=D\n"
                                 f"@{DST.location}\n{DST.dereferences}\n"
                                 f"M={result}\n"
                                  "@__aux\nA=M")
                case (reg, '1' as number_sign) | (reg, '-1' as number_sign):
                    sign = number_sign.rstrip('1')
                    if DST.is_register():
                        return clean(f"{DST.registers}={sign}{reg}")
                    # ne prezervira A registar
                    if reg == 'D':
                        return (f"@{DST.location}\n"
                                f"{DST.dereferences}\n"
                                f"M={sign}{reg}")
                    return clean( "D=A\n@__aux\nAM=D\nD={sign}{reg}\n"
                                 f"@{DST.location}\n{DST.dereferences}\n"
                                 f"M=D\n"
                                  "@__aux\nA=M")
                case ('1' as number_sign, 'D') | ('-1' as number_sign, 'D'):
                    opposite_number_sign = '-1' if number_sign == '1' else '1'
                    if DST.is_register() and 'M' in DST.registers:
                        save_address = "M=D\nD=A\n@__aux\nAM=D\nD=M"
                        reg_isone = f"@__registerisone_{p}\nD-1;JEQ"
                        reg_isnegone = f"@__registerisnegativeone_{p}\nD-1;JEQ"
                        lab_isone = f"(__registerisone_{p})\nD={number_sign}"
                        lab_isnegone = (f"(__registerisone_{p})\n"
                                        f"D={opposite_number_sign}")
                        end_division = f"@__enddiv_{p}\n0;JMP"
                        restore_address = f"@__aux\nA=M"

                        return (f"{save_address}\n"
                                f"{reg_isone}\n"
                                f"{reg_isnegone}\n"
                                f"D=0\n{end_division}\n"
                                f"{lab_isone}\n{end_division}\n"
                                f"{lab_isnegone}\n{end_division}\n"
                                f"(__enddiv_{p})\n"
                                f"{restore_address}\n"
                                f"{DST.registers}=D")
                    # ne prezervira A registar
                    else:
                        reg_isone = f"@__registerisone_{p}\nD-1;JEQ"
                        reg_isnegone = f"@__registerisnegativeone_{p}\nD-1;JEQ"
                        lab_isone = f"(__registerisone_{p})\nD={number_sign}"
                        lab_isnegone = (f"(__registerisone_{p})\n"
                                        f"D={opposite_number_sign}")
                        end_division = f"@__enddiv_{p}\n0;JMP"
                        if DST.is_register():
                            return (f"{reg_isone}\n"
                                    f"{reg_isnegone}\n"
                                    f"D=0\n{end_division}\n"
                                    f"{lab_isone}\n{end_division}\n"
                                    f"{lab_isnegone}\n{end_division}\n"
                                    f"(__enddiv_{p})\n"
                                    f"{DST.registers}=D")
                        else:
                            return (f"{reg_isone}\n"
                                    f"{reg_isnegone}\n"
                                    f"D=0\n{end_division}\n"
                                    f"{lab_isone}\n{end_division}\n"
                                    f"{lab_isnegone}\n{end_division}\n"
                                    f"(__enddiv_{p})\n"
                                    f"@{DST.location}\n"
                                    f"{DST.dereferences}\nM=D")
                case ('1' as number_sign, reg) | ('-1' as number_sign, reg):
                    opposite_number_sign = '-1' if number_sign == '1' else '1'
                    save_address = "D=A\n@__aux\nAM=D\nD={reg}"
                    reg_isone = f"@__registerisone_{p}\nD-1;JEQ"
                    reg_isnegone = f"@__registerisnegativeone_{p}\nD-1;JEQ"
                    lab_isone = f"(__registerisone_{p})\nD={number_sign}"
                    lab_isnegone = (f"(__registerisone_{p})\n"
                                    f"D={opposite_number_sign}")
                    end_division = f"@__enddiv_{p}\n0;JMP"
                    restore_address = f"@__aux\nA=M"
                    if DST.is_register():
                        return (f"{save_address}\n"
                                f"{reg_isone}\n"
                                f"{reg_isnegone}\n"
                                f"D=0\n{end_division}\n"
                                f"{lab_isone}\n{end_division}\n"
                                f"{lab_isnegone}\n{end_division}\n"
                                f"(__enddiv_{p})\n"
                                f"{restore_address}\n"
                                f"{DST.registers}=D")
                    else:
                        return (f"{save_address}\n"
                                f"{reg_isone}\n"
                                f"{reg_isnegone}\n"
                                f"D=0\n{end_division}\n"
                                f"{lab_isone}\n{end_division}\n"
                                f"{lab_isnegone}\n{end_division}\n"
                                f"(__enddiv_{p})\n"
                                f"@{DST.location}\n"
                                f"{DST.dereferences}\n"
                                 "M=D\n"
                                f"{restore_address}\n")
                case ('A', 'D') | ('D', 'A') as state:
                    arg1, arg2 = ('1', '2') if state[0] == 'A' else ('2', '1')
                    if DST.is_register() and 'M' in DST.registers:
                        prediv = ( "M=D\nD=A\n@__aux\nAM=D\n"
                                   "@__divresult\nM=0\n"
                                  f"@__divarg{arg1}\nM=D\n"
                                   "A=D\nD=M\n"
                                  f"@__divarg{arg2}\nM=D")
                        postdiv = ( "@__divresult\nD=M\n"
                                   f"@__aux\nA=M\n{DST.registers}=D")
                    else:
                        raise ParserError(
                            'MCR', "[MULT] Nemoguća operacija", o
                        )
                case ('M', 'D') | ('D', 'M'):
                    raise ParserError('MCR', "[MULT] Nemoguća operacija", o)
                case ('M', 'A') | ('A', 'M'):
                    prediv = ( "D=A\n__aux\nAM=D\n"
                              f"D={ARG1.oneop}\n"
                               "@__divresult\nM=0\n"
                               "@__divarg1\nM=D\n"
                              f"@__aux\nA=M\n"
                              f"D={ARG2.oneop}\n"
                               "@__divarg2\nM=D")
                    if DST.is_register():
                        postdiv = ( "@__divresult\nD=M\n"
                                    "@__aux\nA=M\n"
                                   f"{DST.registers}=D")
                    else:
                        postdiv = ( "@__divresult\nD=M\n"
                                   f"@{DST.location}\n"
                                   f"{DST.dereferences}\nM=D\n"
                                    "@__aux\nA=M")
                case _:
                    assert False
    

        elif ARG1.is_oneop() and ARG2.is_constant():
            match (ARG1.oneop):
                case '0':
                    if DST.is_register():
                        return clean(f"{DST.registers}=0")
                    return clean( "D=A\n@__aux\nM=D\n"
                                 f"@{DST.location}\n{DST.dereferences}\nM=0\n"
                                  "@__aux\nA=M")
                case '1' | '-1':
                    if not swap:
                        if DST.is_register():
                            return clean(f"{DST.registers}=0")
                        else:
                            return clean( "D=A\n@__aux\nM=D\n"
                                         f"@{DST.location}\n"
                                         f"{DST.dereferences}\nM=0\n"
                                          "@__aux\nA=M")


                    constant = ARG2.constant * int(ARG1.oneop)
                    if constant == 32768:
                        constant = -32768

                    save_address = "D=A\n@__aux\nM=D"
                    compute_value = (
                        f"@{constant if constant >= 0 else ~constant}\n"
                        f"D={'A' if constant >= 0 else '!A'}"
                    )
                    restore_address = "@__aux\nA=M"
                    if DST.is_register():
                        set_destination = f"{DST.registers}=D"
                        return clean(f"{save_address}\n"
                                     f"{compute_value}\n"
                                     f"{restore_address}\n"
                                     f"{set_destination}")
                    set_destination = (f"@{DST.location}\n"
                                       f"{DST.dereferences}\n"
                                        "M=D")
                    return clean(f"{save_address}\n"
                                 f"{compute_value}\n"
                                 f"{set_destination}\n"
                                 f"{restore_address}")
                case 'M' | 'A':
                    arg1, arg2 = ('2', '1') if swap else ('1', '2')

                    prediv = ( "D=A\n@__aux\nAM=D\n"
                              f"D={ARG1.oneop}\n"
                               "@__divresult\nM=0\n"
                              f"@__divarg{arg1}\nM=D\n"
                              f"@{ARG2.constant
                                  if ARG2.constant >= 0 else
                                  ~ARG2.constant}\n"
                              f"D={'A' if ARG2.constant >= 0 else '!A'}\n"
                              f"@__divarg{arg2}\nM=D")
                    if DST.is_register():
                        postdiv = ( "@__divresult\nD=M\n"
                                   f"@__aux\nA=M\n{DST.registers}=D")
                    else:
                        postdiv = ( "@__divresult\nD=M\n"
                                   f"@{DST.location}\n"
                                   f"{DST.dereferences}\nM=D\n"
                                    "@__aux\nA=M")
                case 'D':
                    arg1, arg2 = ('2', '1') if swap else ('1', '2')
                    if DST.is_register() and 'M' in DST.registers:
                        prediv = ( "M=D\nD=A\n__aux\nAM=D\nD=M\n"
                                   "@__divresult\nM=0\n"
                                  f"@__divarg{arg1}\nM=D\n"
                                  f"@{ARG2.constant
                                      if ARG2.constant >= 0 else
                                      ~ARG2.constant}\n"
                                  f"D={'A' if ARG2.constant >= 0 else '!A'}\n"
                                  f"@__divarg{arg2}\nM=D")
                        postdiv = ( "@__divresult\nD=M\n"
                                   f"@__aux\nA=M\n{DST.registers}=D")
                    # ne prezervira A registar
                    else:
                        prediv = ( "@__divresult\nM=0\n"
                                  f"@__divarg{arg1}\nM=D\n"
                                  f"@{ARG2.constant
                                      if ARG2.constant >= 0 else
                                      ~ARG2.constant}\n"
                                  f"D={'A' if ARG2.constant >= 0 else '!A'}\n"
                                  f"@__divarg{arg2}\nM=D")
                        if DST.is_register():
                            postdiv = f"@__divresult\nD=M\n{DST.registers}=D"
                        else:
                            postdiv = ( "@__divresult\nD=M\n"
                                       f"@{DST.location}\n"
                                       f"{DST.dereferences}\nM=D")
                case _:
                    assert False

        elif ARG1.is_oneop() and ARG2.is_address():
            match (ARG1.oneop):
                case '0':
                    if DST.is_register():
                        return clean(f"{DST.registers}=0")
                    return clean( "D=A\n@__aux\nM=D\n"
                                 f"@{DST.location}\n{DST.dereferences}\nM=0\n"
                                  "@__aux\nA=M")
                case '1' | '-1':
                    if not swap:
                        if DST.is_register():
                            return clean(f"{DST.registers}=0")
                        else:
                            return clean( "D=A\n@__aux\nM=D\n"
                                         f"@{DST.location}\n"
                                         f"{DST.dereferences}\nM=0\n"
                                          "@__aux\nA=M")

                    sign = ARG1.oneop.rstrip('1')

                    save_address = "D=A\n@__aux\nM=D"
                    compute_value = (
                        f"@{ARG2.location}\n{ARG2.dereferences}\nD={sign}M"
                    )
                    restore_address = "@__aux\nA=M"
                    if DST.is_register():
                        set_destination = f"{DST.registers}=D"
                        return clean(f"{save_address}\n"
                                     f"{compute_value}\n"
                                     f"{restore_address}\n"
                                     f"{set_destination}")
                    set_destination = (f"@{DST.location}\n"
                                       f"{DST.dereferences}\n"
                                        "M=D")
                    return clean(f"{save_address}\n"
                                 f"{compute_value}\n"
                                 f"{set_destination}\n"
                                 f"{restore_address}")
                case 'M' | 'A':
                    arg1, arg2 = ('2', '1') if swap else ('1', '2')
                    prediv = ( "D=A\n@__aux\nAM=D\n"
                              f"D={ARG1.oneop}\n"
                               "@__divresult\nM=0\n"
                              f"@__divarg{arg1}\nM=D\n"
                              f"@{ARG2.location}\n{ARG2.dereferences}\nD=M\n"
                              f"@__divarg{arg2}\nM=D")
                    if DST.is_register():
                        postdiv = ( "@__divresult\nD=M\n"
                                   f"@__aux\nA=M\n{DST.registers}=D")
                    else:
                        postdiv = ( "@__divresult\nD=M\n"
                                   f"@{DST.location}\n"
                                   f"{DST.dereferences}\nM=D\n"
                                    "@__aux\nA=M")
                case 'D':
                    arg1, arg2 = ('2', '1') if swap else ('1', '2')
                    if DST.is_register() and 'M' in DST.registers:
                        prediv = ( "M=D\nD=A\n__aux\nAM=D\nD=M\n"
                                   "@__divresult\nM=0\n"
                                  f"@__divarg{arg1}\nM=D\n"
                                  f"@{ARG2.location}\n"
                                  f"{ARG2.dereferences}\nD=M\n"
                                  f"@__divarg{arg2}\nM=D")
                        postdiv = ( "@__divresult\nD=M\n"
                                   f"@__aux\nA=M\n{DST.registers}=D")
                    # ne prezervira A registar
                    else:
                        prediv = ( "@__divresult\nM=0\n"
                                  f"@__divarg{arg1}\nM=D\n"
                                  f"@{ARG2.location}\n"
                                  f"{ARG2.dereferences}\nD=M\n"
                                  f"@__divarg{arg2}\nM=D")
                        if DST.is_register():
                            postdiv = f"@__divresult\nD=M\n{DST.registers}=D"
                        else:
                            postdiv = ( "@__divresult\nD=M\n"
                                       f"@{DST.location}\n"
                                       f"{DST.dereferences}\nM=D")
                case _:
                    assert False
        elif ARG1.is_constant() and ARG2.is_constant():
            sgn = 2*((ARG1.constant >= 0) == (ARG2.constant >= 0)) - 1
            constant = sgn * (abs(ARG1.constant) // abs(ARG2.constant))
            constant = ((constant + 32768) & 0xffff) - 32768

            save_address = "D=A\n@__aux\nM=D"
            compute_value = (
                f"@{constant if constant >= 0 else ~constant}\n"
                f"D={'A' if constant >= 0 else '!A'}"
            )
            restore_address = "@__aux\nA=M"
            if DST.is_register():
                set_destination = f"{DST.registers}=D"
                return clean(f"{save_address}\n"
                             f"{compute_value}\n"
                             f"{restore_address}\n"
                             f"{set_destination}")

            set_destination = (f"@{DST.location}\n"
                               f"{DST.dereferences}\n"
                                "M=D")
            return clean(f"{save_address}\n"
                         f"{compute_value}\n"
                         f"{set_destination}\n"
                         f"{restore_address}")

        elif ARG1.is_constant() and ARG2.is_address():
            arg1, arg2 = ('2', '1') if swap else ('1', '2')
            save_address = "D=A\n@__aux\nM=D"
            load_value1 = (
                f"@{ARG1.constant if ARG1.constant >= 0 else ~ARG1.constant}\n"
                f"D={'A' if ARG1.constant >= 0 else '!A'}"
            )
            load_value2 = (
                f"@{ARG2.location}\n{ARG2.dereferences}\nD=M"
            )
            restore_address = "@__aux\nA=M"
            prediv = (f"{save_address}\n"
                      f"{load_value1}\n"
                       "@__divresult\nM=0\n"
                      f"@__divarg{arg1}\nM=D\n"
                      f"{load_value2}\n"
                      f"@__divarg{arg2}\nM=D")
            if DST.is_register():
                postdiv = ( "@__divresult\nD=M\n"
                           f"{restore_address}\n"
                           f"{DST.registers}=D")
            else:
                postdiv = ( "@__divresult\nD=M\n"
                           f"@{DST.location}\n{DST.dereferences}\nM=D\n"
                           f"{restore_address}")

        elif ARG1.is_address() and ARG2.is_address():
            save_address = "D=A\n@__aux\nM=D"
            load_value1 = (
                f"@{ARG1.location}\n{ARG1.dereferences}\nD=M"
            )
            load_value2 = (
                f"@{ARG2.location}\n{ARG2.dereferences}\nD=M"
            )
            restore_address = "@__aux\nA=M"
            prediv = (f"{save_address}\n"
                      f"{load_value1}\n"
                       "@__divresult\nM=0\n"
                       "@__divarg1\nM=D\n"
                      f"{load_value2}\n"
                       "@__divarg2\nM=D")
            if DST.is_register():
                postdiv = ( "@__divresult\nD=M\n"
                           f"{restore_address}\n"
                           f"{DST.registers}=D")
            else:
                postdiv = ( "@__divresult\nD=M\n"
                           f"@{DST.location}\n{DST.dereferences}\nM=D\n"
                           f"{restore_address}")
        else:
            assert False


        start_portion = (f"@__divarg2\nD=M\n@__trueenddiv_{p}\nD;JEQ\n"
                         f"@__divsign\nM=1\n@__divarg1\nD=M\n"
                         f"@__nonnegativearg1_{p}\nD;JGE\n"
                         f"@__divsign\nM=-M\n@__divarg1\nM=-M\n"
                         f"(__nonnegativearg1_{p})\n@__divarg2\nD=M\n"
                         f"@__div_2p14_{p}\nD;JGE\n@__divsign\nM=-M\n"
                         f"@__divarg2\nM=-M")

        middle_parts = '\n'.join([
            (
                f"(__div_2p{power}_{p})\n@__divarg2\nD=M\n"
                f"@__divhelper\nM=D\n"
                f"{'\n'.join(
                    [f'MD=M+D\n@__div_2p{power-1}_{p}'
                      '\nD;JLT\n@__divhelper\n']*power
                   )}\n"
                f"@__div_2p{power-1}_{p}\nD;JLT\n"
                f"@__divarg1\nD=M-D\n@__div_2p{power-1}_{p}\nD;JLT\n"
                f"@__divhelper\nD=M\n@__divarg1\nM=M-D\n@{2**power}\nD=A\n"
                f"@__divresult\nM=M+D\n@__div_2p{power}_{p}\n0;JMP"
            ) for power in range(14, 0, -1)
        ])

        end_portion = (f"(__div_2p0_{p})\n@__divarg2\n"
                        "D=M\n@__divarg1\nMD=M-D\n"
                       f"@__enddiv_{p}\nD;JLT\n@__divarg2\nD=M\n@__divarg1\n"
                       f"M=M-D\n@__divresult\nM=M+1\n@__div_2p0_{p}\n0;JMP\n"
                       f"(__enddiv_{p})\n@__divsign\nD=M\n@__trueenddiv_{p}\n"
                       f"D;JGE\n@__divresult\nM=-M\n(__trueenddiv_{p})")

        div_algorithm = f"{start_portion}\n{middle_parts}\n{end_portion}"

        return clean(f"{prediv}\n{div_algorithm}\n{postdiv}")

class POW(SimpleMacro):
    arg_count = 3

    def run(self, line: str, p: int, o: int) -> str:
        _ARG1 = self.arguments[1]
        _ARG2 = self.arguments[2]
        try:
            DST = Destination(self.arguments[0])
            ARG1 = Argument(_ARG1)
            ARG2 = Argument(_ARG2)
        except BadDestination:
            raise ParserError(
                'MCR',
                "[POW] Destinacija mora biti jedan ili više registara,"
                "ili adresa.",
                o
            )
        except BadArgument:
            raise ParserError(
                'MCR',
                "[POW] Argument mora biti registar, konstanta, ili adresa.",
                o
            )
        except OutOfBoundsConstantError:
            raise ParserError(
                'MCR', "[POW] Konstanta mora biti u [-32768, 32767].", o
            )
        
        premult, postmult = None, None
        swap = False
        if (
            (ARG2.is_oneop() and ARG1.is_constant()) or
            (ARG2.is_oneop() and ARG1.is_address()) or
            (ARG2.is_constant() and ARG1.is_address())
        ):
            ARG1, ARG2 = ARG2, ARG1
            swap = True

        if ARG1.is_oneop() and ARG2.is_oneop():
            match (ARG1.oneop, ARG2.oneop):
                case (_, '1'):
                    return ""
                case (_, '0'):
                    return f"$LD({DST}, 1)"
                case ('1', _):
                    return f"$LD({DST}, 1)"
                case ('0', _):
                    return f"$LD({DST}, 0)"
                case ('-1' | '0', '-1'):
                    return f"$LD({DST}, {ARG1})"
                case (_, '-1'):
                    return f"$DIV({DST}, 1, {ARG1})"
                case ('-1', 'D'):
                    create_value = "@1\nD=D&A\nD=-D\nA=D\nA=A+D\nD=A+1"
                    if DST.is_register() and 'M' in DST.registers:
                        save_address = "M=D\nD=A\n@__aux\nAM=D\nD=M"
                        restore_address = "@__aux\nA=M"
                        set_destination = "{DST.registers}=D"
                        return (f"{save_address}\n{create_value}\n"
                                f"{restore_address}\n{set_destination}")
                    # ne prezervira A registar
                    if DST.is_register():
                        set_destination = "{DST.registers}=D"
                    else:
                        set_destination = (f"@{DST.location}\n"
                                           f"{DST.dereferences}\n"
                                            "M=D")
                    return f"{create_value}\n{set_destination}"
                case ('-1', _):
                    save_address = "D=A\n@__aux\nAM=D"
                    create_value = (f"D={ARG2}\n@1\nD=D&A\nD=-D\n"
                                     "A=D\nA=A+D\nD=A+1")
                    restore_address = "@__aux\nA=M"
                    if DST.is_register():
                        set_destination = "{DST.registers}=D"
                        return (f"{save_address}\n{create_value}\n"
                                f"{restore_address}\n{set_destination}")
                    else:
                        set_destination = (f"@{DST.location}\n"
                                           f"{DST.dereferences}\n"
                                            "M=D")
                        return (f"{save_address}\n{create_value}\n"
                                f"{set_destination}\n{restore_address}")
                case ('A', 'D') | ('D', 'A') as state:
                    arg1, arg2 = (
                        ('base', 'exponent')
                        if state[0] == 'A' else
                        ('exponent', 'base')
                    )
                    if DST.is_register() and 'M' in DST.registers:
                        prepow = ( "M=D\nD=A\n@__powaux\nAM=D\n"
                                   "@__powresult\nM=1\n"
                                  f"@__pow{arg1}\nM=D\n"
                                   "A=D\nD=M\n"
                                  f"@__pow{arg2}\nM=D")
                        postpow = ( "@__powresult\nD=M\n"
                                   f"@__powaux\nA=M\n{DST.registers}=D")
                    else:
                        raise ParserError(
                            'MCR', "[MULT] Nemoguća operacija", o
                        )

                case ('M', 'D') | ('D', 'M'):
                    raise ParserError('MCR', "[MULT] Nemoguća operacija", o)
                case ('M', 'A') | ('A', 'M'):
                    prepow = ( "D=A\n__powaux\nAM=D\n"
                              f"D={ARG1.oneop}\n"
                               "@__powresult\nM=1\n"
                               "@__powbase\nM=D\n"
                              f"@__powaux\nA=M\n"
                              f"D={ARG2.oneop}\n"
                               "@__powexponent\nM=D")
                    if DST.is_register():
                        postpow = ( "@__powresult\nD=M\n"
                                    "@__powaux\nA=M\n"
                                   f"{DST.registers}=D")
                    else:
                        postpow = ( "@__powresult\nD=M\n"
                                   f"@{DST.location}\n"
                                   f"{DST.dereferences}\nM=D\n"
                                    "@__powaux\nA=M")
                case _:
                    assert False

        elif ARG1.is_oneop() and ARG2.is_constant():
            match (ARG1.oneop):
                case '0':
                    return f"$LD({DST}, {int(swap)})"
                case '1':
                    return f"$LD({DST}, 1)" if not swap else ""
                case '-1':
                    if not swap:
                        return f"$LD({DST}, {-2 * (ARG2.constant&1) + 1})"
                    else:
                        return f"$LD({DST}, 0)"

                case 'M' | 'A':
                    arg1, arg2 = (
                        ('exponent', 'base')
                        if swap else
                        ('base', 'exponent')
                    )

                    prepow = ( "D=A\n@__powaux\nAM=D\n"
                              f"D={ARG1.oneop}\n"
                               "@__powresult\nM=1\n"
                              f"@__pow{arg1}\nM=D\n"
                              f"@{ARG2.constant
                                  if ARG2.constant >= 0 else
                                  ~ARG2.constant}\n"
                              f"D={'A' if ARG2.constant >= 0 else '!A'}\n"
                              f"@__pow{arg2}\nM=D")
                    if DST.is_register():
                        postpow = ( "@__powresult\nD=M\n"
                                   f"@__powaux\nA=M\n{DST.registers}=D")
                    else:
                        postpow = ( "@__powresult\nD=M\n"
                                   f"@{DST.location}\n"
                                   f"{DST.dereferences}\nM=D\n"
                                    "@__powaux\nA=M")
                case 'D':
                    arg1, arg2 = (
                        ('exponent', 'base')
                        if swap else
                        ('base', 'exponent')
                    )
                    if DST.is_register() and 'M' in DST.registers:
                        prepow = ( "M=D\nD=A\n__powaux\nAM=D\nD=M\n"
                                   "@__powresult\nM=1\n"
                                  f"@__pow{arg1}\nM=D\n"
                                  f"@{ARG2.constant
                                      if ARG2.constant >= 0 else
                                      ~ARG2.constant}\n"
                                  f"D={'A' if ARG2.constant >= 0 else '!A'}\n"
                                  f"@__pow{arg2}\nM=D")
                        postpow = ( "@__powresult\nD=M\n"
                                   f"@__powaux\nA=M\n{DST.registers}=D")
                    # ne prezervira A registar
                    else:
                        prepow = ( "@__powresult\nM=1\n"
                                  f"@__pow{arg1}\nM=D\n"
                                  f"@{ARG2.constant
                                      if ARG2.constant >= 0 else
                                      ~ARG2.constant}\n"
                                  f"D={'A' if ARG2.constant >= 0 else '!A'}\n"
                                  f"@__pow{arg2}\nM=D")
                        if DST.is_register():
                            postpow = f"@__powresult\nD=M\n{DST.registers}=D"
                        else:
                            postpow = ( "@__powresult\nD=M\n"
                                       f"@{DST.location}\n"
                                       f"{DST.dereferences}\nM=D")
                case _:
                    assert False

        elif ARG1.is_oneop() and ARG2.is_address():
            match (ARG1.oneop):
                case '0':
                    return f"$LD({DST}, {int(swap)})"
                case '1':
                    return f"$LD({DST}, 1)" if not swap else ""
                case '-1':
                    if swap:
                        return f"$DIV({DST}, 1, {ARG2})"
                    save_address = "D=A\n@__aux\nAM=D"
                    create_value = (f"@{ARG2.location}\n"
                                    f"@{ARG2.dereferences}\n"
                                     "D=M\n@1\nD=D&A\nD=-D\n"
                                     "A=D\nA=A+D\nD=A+1")
                    restore_address = "@__aux\nA=M"
                    if DST.is_register():
                        set_destination = "{DST.registers}=D"
                        return (f"{save_address}\n{create_value}\n"
                                f"{restore_address}\n{set_destination}")
                    else:
                        set_destination = (f"@{DST.location}\n"
                                           f"{DST.dereferences}\n"
                                            "M=D")
                        return (f"{save_address}\n{create_value}\n"
                                f"{set_destination}\n{restore_address}")
                case 'M' | 'A':
                    arg1, arg2 = (
                        ('exponent', 'base')
                        if swap else
                        ('base', 'exponent')
                    )
                    prepow = ( "D=A\n@__powaux\nAM=D\n"
                              f"D={ARG1.oneop}\n"
                               "@__powresult\nM=1\n"
                              f"@__pow{arg1}\nM=D\n"
                              f"@{ARG2.location}\n{ARG2.dereferences}\nD=M\n"
                              f"@__pow{arg2}\nM=D")
                    if DST.is_register():
                        postpow = ( "@__powresult\nD=M\n"
                                   f"@__powaux\nA=M\n{DST.registers}=D")
                    else:
                        postpow = ( "@__powresult\nD=M\n"
                                   f"@{DST.location}\n"
                                   f"{DST.dereferences}\nM=D\n"
                                    "@__powaux\nA=M")
                case 'D':
                    arg1, arg2 = (
                        ('exponent', 'base')
                        if swap else
                        ('base', 'exponent')
                    )
                    if DST.is_register() and 'M' in DST.registers:
                        prepow = ( "M=D\nD=A\n__powaux\nAM=D\nD=M\n"
                                   "@__powresult\nM=1\n"
                                  f"@__pow{arg1}\nM=D\n"
                                  f"@{ARG2.location}\n"
                                  f"{ARG2.dereferences}\nD=M\n"
                                  f"@__pow{arg2}\nM=D")
                        postpow = ( "@__powresult\nD=M\n"
                                   f"@__powaux\nA=M\n{DST.registers}=D")
                    # ne prezervira A registar
                    else:
                        prepow = ( "@__powresult\nM=1\n"
                                  f"@__pow{arg1}\nM=D\n"
                                  f"@{ARG2.location}\n"
                                  f"{ARG2.dereferences}\nD=M\n"
                                  f"@__pow{arg2}\nM=D")
                        if DST.is_register():
                            postpow = f"@__powresult\nD=M\n{DST.registers}=D"
                        else:
                            postpow = ( "@__powresult\nD=M\n"
                                       f"@{DST.location}\n"
                                       f"{DST.dereferences}\nM=D")
                case _:
                    assert False
        elif ARG1.is_constant() and ARG2.is_constant():
            if ARG2.constant < 0:
                return f"$LD({DST}, 0)"
            constant = ARG1.constant ** ARG2.constant
            constant = ((constant + 32768) & 0xffff) - 32768

            save_address = "D=A\n@__aux\nM=D"
            compute_value = (
                f"@{constant if constant >= 0 else ~constant}\n"
                f"D={'A' if constant >= 0 else '!A'}"
            )
            restore_address = "@__aux\nA=M"
            if DST.is_register():
                set_destination = f"{DST.registers}=D"
                return clean(f"{save_address}\n"
                             f"{compute_value}\n"
                             f"{restore_address}\n"
                             f"{set_destination}")

            set_destination = (f"@{DST.location}\n"
                               f"{DST.dereferences}\n"
                                "M=D")
            return clean(f"{save_address}\n"
                         f"{compute_value}\n"
                         f"{set_destination}\n"
                         f"{restore_address}")

        elif ARG1.is_constant() and ARG2.is_address():
            arg1, arg2 = (
                ('exponent', 'base')
                if swap else
                ('base', 'exponent')
            )
            save_address = "D=A\n@__powaux\nM=D"
            load_value1 = (
                f"@{ARG1.constant if ARG1.constant >= 0 else ~ARG1.constant}\n"
                f"D={'A' if ARG1.constant >= 0 else '!A'}"
            )
            load_value2 = (
                f"@{ARG2.location}\n{ARG2.dereferences}\nD=M"
            )
            restore_address = "@__powaux\nA=M"
            prepow = (f"{save_address}\n"
                      f"{load_value1}\n"
                       "@__powresult\nM=1\n"
                      f"@__pow{arg1}\nM=D\n"
                      f"{load_value2}\n"
                      f"@__pow{arg2}\nM=D")
            if DST.is_register():
                postpow = ( "@__powresult\nD=M\n"
                           f"{restore_address}\n"
                           f"{DST.registers}=D")
            else:
                postpow = ( "@__powresult\nD=M\n"
                           f"@{DST.location}\n{DST.dereferences}\nM=D\n"
                           f"{restore_address}")

        elif ARG1.is_address() and ARG2.is_address():
            save_address = "D=A\n@__powaux\nM=D"
            load_value1 = (
                f"@{ARG1.location}\n{ARG1.dereferences}\nD=M"
            )
            load_value2 = (
                f"@{ARG2.location}\n{ARG2.dereferences}\nD=M"
            )
            restore_address = "@__powaux\nA=M"
            prepow = (f"{save_address}\n"
                      f"{load_value1}\n"
                       "@__powresult\nM=1\n"
                       "@__powbase\nM=D\n"
                      f"{load_value2}\n"
                       "@__powexponent\nM=D")
            if DST.is_register():
                postpow = ( "@__powresult\nD=M\n"
                           f"{restore_address}\n"
                           f"{DST.registers}=D")
            else:
                postpow = ( "@__powresult\nD=M\n"
                           f"@{DST.location}\n{DST.dereferences}\nM=D\n"
                           f"{restore_address}")
        else:
            assert False
        
        # 1^X = 1
        # (-1)^X = if X odd then -1 else 1
        # 0^X = if X = 0 then 1 else 0
        pow_check_base = ( "@__powbase\nD=M\n"
                          f"@__powend_{p}\nD-1;JEQ\n"
                          f"@__powbaseisnegativeone_{p}\nD+1;JEQ\n"
                          f"@__powcheckexponent_{p}\nD;JNE\n"
                          f"@__powexponent\nD=M\n"
                          f"@__powend_{p}\nD;JEQ\n"
                           "@__powresult\nM=0\n"
                          f"@__powend_{p}\n0;JMP\n"
                          f"(__powbaseisnegativeone_{p})\n"
                          f"@__powexponent\nD=M\n@1\nD=D&A\nA=-D\nA=A-D\n"
                           "D=A+1\n@__powresult\nM=D\n"
                          f"@__powend_{p}\n0;JMP")
        
        # if Y < 0, 0
        # base being 1 or -1, ((-1)^-5 != 0) handled in pow_check_base
        pow_check_exponent = (f"(__powcheckexponent_{p})\n"
                              f"@__powexponent\nD=M\n"
                              f"@__powstart_{p}\nD;JGE\n"
                               "@__powresult\nM=0\n"
                              f"@__powend_{p}\n0;JMP")


        pow_algorithm = (f"{pow_check_base}\n{pow_check_exponent}\n"
                         f"(__powstart_{p})\n$LOOP(@__powexponent){{\n"
                          "@__powexponent\nD=M\n@1\nD=D&A\n"
                          "$IF(D){\n"
                          "$MULT(@__powresult,@__powbase,@__powresult)\n"
                          "}\n"
                          "$DIV(@__powexponent,@__powexponent,2)\n"
                          "$MULT(@__powbase,@__powbase,@__powbase)\n"
                         f"}}\n(__powend_{p})")

        return clean(f"{prepow}\n{pow_algorithm}\n{postpow}")


class HALT(SimpleMacro):

    arg_count = 0

    def run(self, line: str, p: int, o: int) -> str:
        return f'(__halt_{p})\n@__halt_{p}\n0;JMP'

class IF(BlockMacro):

    arg_count = 1

    def open(self, line: str, p: int, o: int) -> str:
        try:
            ARG = Argument(self.arguments[0])
        except BadArgument:
            raise ParserError(
                'MCR',
                "[IF] Argument mora biti registar, konstanta, ili adresa.",
                o
            )
        except OutOfBoundsConstantError:
            raise ParserError(
                'MCR', "[IF] Konstanta mora biti u [-32768, 32767].", o
            )

        
        if ARG.is_register():
            return clean(f"D={ARG.register}\n@__if_{ARG}_{p}\nD;JEQ")
        elif ARG.is_constant():
            if not ARG.constant:
                return clean(f"@__if_{ARG}_{p}\n0;JMP")
            return ''
        else:
            return clean(f"@{ARG.location}\n"
                         f"{ARG.dereferences}\n"
                          "D=M\n"
                         f"@__if_{ARG}_{p}\n"
                          "D;JEQ")

    def close(self, line: str, p: int, o: int) -> str:
        ARG = Argument(self.arguments[0])
        if ARG.is_constant() and ARG.constant:
            return ''
        return f"(__if_{ARG}_{self.open_p})"

class IFN(BlockMacro):

    arg_count = 1

    def open(self, line: str, p: int, o: int) -> str:
        try:
            ARG = Argument(self.arguments[0])
        except BadArgument:
            raise ParserError(
                'MCR',
                "[IFN] Argument mora biti registar, konstanta, ili adresa.",
                o
            )
        except OutOfBoundsConstantError:
            raise ParserError(
                'MCR', "[IFN] Konstanta mora biti u [-32768, 32767].", o
            )

        
        if ARG.is_register():
            return clean(f"D={ARG.register}\n@__ifn_{ARG}_{p}\nD;JNE")
        elif ARG.is_constant():
            if ARG.constant:
                return clean(f"@__ifn_{ARG}_{p}\n0;JMP")
            return ''
        else:
            return clean(f"@{ARG.location}\n"
                         f"{ARG.dereferences}\n"
                          "D=M\n"
                         f"@__ifn_{ARG}_{p}\n"
                          "D;JNE")

    def close(self, line: str, p: int, o: int) -> str:
        ARG = Argument(self.arguments[0])
        if ARG.is_constant() and not ARG.constant:
            return ''
        return f"(__ifn_{ARG}_{self.open_p})"


class LOOP(BlockMacro):

    arg_count = 1
    
    def open(self, line: str, p: int, o: int) -> str:
        try:
            ARG = Argument(self.arguments[0])
        except BadArgument:
            raise ParserError(
                'MCR',
                "[LOOP] Argument mora biti registar, konstanta, ili adresa.",
                o
            )
        except OutOfBoundsConstantError:
            raise ParserError(
                'MCR', "[LOOP] Konstanta mora biti u [-32768, 32767].", o
            )
        var_start = f'__loop_{ARG}_{p}_start'
        var_after = f'__loop_{ARG}_{p}_after'

        if ARG.is_register():
            return clean(f"D={ARG.register}\n"
                         f"@{var_after}\n"
                          "D;JEQ\n"
                         f"({var_start})")
        elif ARG.is_address():
            return clean(f"@{ARG.location}\n"
                         f"{ARG.dereferences}\n"
                          "D=M\n"
                         f"@{var_after}\n"
                          "D;JEQ\n"
                         f"({var_start})")
        elif ARG.constant == 0:
            # never enters - no need for var_start
            return f"@{var_after}\n0;JMP"
        else:
            # never exits - no need for var_after
            return f"({var_start})"


    def close(self, line: str, p: int, o: int) -> str:
        ARG = Argument(self.arguments[0])
        var_start = f'__loop_{ARG}_{self.open_p}_start'
        var_after = f'__loop_{ARG}_{self.open_p}_after'

        if ARG.is_register():
            return clean(f"D={ARG.register}\n"
                         f"@{var_start}\n"
                          "D;JNE\n"
                         f"({var_after})")
        elif ARG.is_address():
            return clean(f"@{ARG.location}\n"
                         f"{ARG.dereferences}\n"
                          "D=M\n"
                         f"@{var_start}\n"
                          "D;JNE\n"
                         f"({var_after})")
        elif ARG.constant == 0:
            # never enters - no need for var_start
            return f"({var_after})"
        else:
            # never exits - no need for var_after
            return clean(f"@{var_start}\n0;JMP")
