#!/usr/bin/env python3
# ensamblador_two_pass.py
# Ensamblador x86 (dos pasadas) basado en el ensamblador original del usuario.
# Mantiene soporte SIB, ModR/M, MOV reg/imm (r8/r32), MOV mem/reg, MOV mem, imm32,
# saltos rel8/rel32, CALL rel32, DD, MOVZX, LEA, XCHG, PUSH/POP, etc.

import re
import sys
from enum import Enum, auto
from dataclasses import dataclass, field
from typing import List, Dict

# -------------------- Tokens --------------------
class Token(Enum):
    MOV = auto(); ADD = auto(); SUB = auto(); INC = auto(); DEC = auto()
    MUL = auto(); IMUL = auto(); DIV = auto(); IDIV = auto(); JMP = auto()
    CMP = auto(); JE = auto(); JNE = auto(); JL = auto(); JG = auto()
    JLE = auto(); JGE = auto(); CALL = auto(); RET = auto(); PUSH = auto()
    POP = auto(); NOP = auto(); XOR = auto(); AND = auto(); OR = auto()
    TEST = auto(); MOVZX = auto(); LEA = auto(); XCHG = auto(); LOOP = auto()
    DD = auto()
    EAX = auto(); EBX = auto(); ECX = auto(); EDX = auto(); ESI = auto(); EDI = auto(); EBP = auto(); ESP = auto()
    AL = auto(); AH = auto(); CL = auto(); CH = auto(); DL = auto(); DH = auto(); BL = auto(); BH = auto()
    NUMBER = auto(); COMA = auto(); LCOR = auto(); RCOR = auto(); UNKNOWN = auto()

# -------------------- Estructuras --------------------
@dataclass
class MemOperand:
    is_memory: bool = False
    usa_sib: bool = False
    original_str: str = ""
    mod: int = 0
    rm: int = 0
    sib: int = 0
    disp_size: int = 0
    displacement: int = 0
    label: str = ""
    base_reg: str = ""
    index_reg: str = ""
    escala: int = 1
    tiene_disp: bool = False
    es_word: bool = False

@dataclass
class OperandInfo:
    type: Token = Token.UNKNOWN
    es_registro: bool = False
    registro: str = ""
    es_inmediato: bool = False
    inmediato: int = 0
    es_memoria: bool = False
    mem: MemOperand = field(default_factory=MemOperand)
    original_str: str = ""

# -------------------- Ensamblador dos pasadas --------------------
class EnsambladorTwoPass:
    def __init__(self):
        self.file = None
        self.linea = 0
        self.tabla_simbolos: Dict[str,int] = {}
        self.referencias_pendientes: Dict[str,List[int]] = {}
        self.codigo_hex: List[int] = []
        self.contador_posicion = 0
        self.dry_run = True  # True en pasada1, False en pasada2

        self.reg_token_map: Dict[Token,int] = {
            Token.EAX:0, Token.ECX:1, Token.EDX:2, Token.EBX:3,
            Token.ESP:4, Token.EBP:5, Token.ESI:6, Token.EDI:7,
            Token.AL:0, Token.CL:1, Token.DL:2, Token.BL:3,
            Token.AH:4, Token.CH:5, Token.DH:6, Token.BH:7
        }

    # ---------- I/O y errores ----------
    def openFile(self, fileName: str):
        try:
            self.file = open(fileName, "r", encoding="utf-8")
        except Exception:
            print(f'Error fatal: "{fileName}" no es un archivo ni un directorio.', file=sys.stderr)
            sys.exit(1)
        self.linea = 0

    def error(self, msg: str):
        print(f"Error de Ensamblado en linea {self.linea}: {msg}", file=sys.stderr)
        sys.exit(1)

    # ---------- Parse / control de pasadas ----------
    def parse(self, filename: str = "prueba.asm"):
        # Pasada 1: dry run para construir tabla de símbolos (y medir tamaños)
        self.dry_run = True
        self.tabla_simbolos = {}
        self.referencias_pendientes = {}
        self.codigo_hex = []
        self.contador_posicion = 0
        self._procesar_todo(filename)

        # Pasada 2: generar bytes reales
        self.dry_run = False
        self.codigo_hex = []
        self.contador_posicion = 0
        # NOTA: no reiniciamos tabla_simbolos; la usamos.
        self._procesar_todo(filename)

        # resolver referencias y generar salidas
        self.resolver_referencias_pendientes()
        self.generar_hex("programa.hex")
        self.generar_reportes()

    def _procesar_todo(self, filename: str):
        self.openFile(filename)
        for raw in self.file:
            self.linea += 1
            self.procesar_linea(raw.rstrip('\n'))
        self.file.close()

    # ---------- Token y utilidades ----------
    def generar_token(self, s: str) -> Token:
        if s is None:
            return Token.UNKNOWN
        upper_s = s.strip().upper()

        mapping = {
            "MOV":Token.MOV, "ADD":Token.ADD, "SUB":Token.SUB, "INC":Token.INC,
            "DEC":Token.DEC, "JMP":Token.JMP, "RET":Token.RET, "JE":Token.JE,
            "JNE":Token.JNE, "JL":Token.JL, "JG":Token.JG, "JLE":Token.JLE,
            "JGE":Token.JGE, "CALL":Token.CALL, "PUSH":Token.PUSH, "POP":Token.POP,
            "NOP":Token.NOP, "CMP":Token.CMP, "AND":Token.AND, "OR":Token.OR,
            "XOR":Token.XOR, "DD":Token.DD, "MUL":Token.MUL, "IMUL":Token.IMUL,
            "DIV":Token.DIV, "IDIV":Token.IDIV, "TEST":Token.TEST, "MOVZX":Token.MOVZX,
            "LEA":Token.LEA, "XCHG":Token.XCHG, "LOOP":Token.LOOP,
        }
        if upper_s in mapping:
            return mapping[upper_s]

        # common aliases for jumps
        if upper_s == "JZ": return Token.JE
        if upper_s == "JNZ": return Token.JNE

        regs = {
            "AL":Token.AL,"AH":Token.AH,"EAX":Token.EAX,"EBX":Token.EBX,
            "ECX":Token.ECX,"EDX":Token.EDX,"ESI":Token.ESI,"EDI":Token.EDI,
            "EBP":Token.EBP,"ESP":Token.ESP,"CL":Token.CL,"CH":Token.CH,
            "DL":Token.DL,"DH":Token.DH,"BL":Token.BL,"BH":Token.BH
        }
        if upper_s in regs:
            return regs[upper_s]

        if upper_s == ",":
            return Token.COMA
        if upper_s == "[":
            return Token.LCOR
        if upper_s == "]":
            return Token.RCOR

        if re.match(r"^[+-]?\d+$", s.strip()):
            return Token.NUMBER
        if re.match(r"^[0-9A-Fa-f]+[Hh]$", s.strip()):
            return Token.NUMBER
        if re.match(r"^0x[0-9A-Fa-f]+$", s.strip()):
            return Token.NUMBER

        return Token.UNKNOWN

    def parse_immediate(self, s: str) -> int:
        temp_s = s.strip()
        if temp_s == "":
            return 0
        if temp_s[-1] in ('h','H') and len(temp_s) > 1:
            number = temp_s[:-1]
            try:
                return int(number, 16)
            except Exception:
                self.error("Valor hexadecimal inválido: " + s)
        if temp_s.startswith("0x") or temp_s.startswith("0X"):
            try:
                return int(temp_s, 16)
            except Exception:
                self.error("Valor hexadecimal inválido: " + s)
        else:
            try:
                return int(temp_s, 10)
            except Exception:
                self.error("Valor decimal inválido: " + s)
        return 0

    def get_reg_code(self, reg_token_or_str, ctx: str = "") -> int:
        if isinstance(reg_token_or_str, Token):
            tok = reg_token_or_str
            original = ctx
        else:
            original = reg_token_or_str
            tok = self.generar_token(reg_token_or_str)

        if tok in self.reg_token_map:
            return self.reg_token_map[tok]

        extra = f" (contexto: {original})" if original else ""
        name = tok.name if isinstance(tok, Token) else str(tok)
        self.error(f"Token no es un registro válido para ModR/M: {name}{extra}")
        return 0

    # ---------- Strings helpers ----------
    @staticmethod
    def trim_copy(s: str) -> str:
        return s.strip()

    @staticmethod
    def split_operands(s: str) -> List[str]:
        out = []
        cur = []
        bracket = 0
        i = 0
        while i < len(s):
            c = s[i]
            if c == '[':
                bracket += 1
                cur.append(c)
            elif c == ']':
                bracket -= 1
                cur.append(c)
            elif c == ',' and bracket == 0:
                token = ''.join(cur).strip()
                if token != "":
                    out.append(token)
                cur = []
            else:
                cur.append(c)
            i += 1
        last = ''.join(cur).strip()
        if last != "":
            out.append(last)
        return out

    # ---------- Limpieza y etiquetas ----------
    def limpiar_linea(self, linea: str) -> str:
        pos = linea.find(';')
        if pos != -1:
            linea = linea[:pos]
        return linea.strip()

    def es_etiqueta(self, s: str) -> bool:
        return s != "" and s.endswith(':')

    def procesar_etiqueta(self, etiqueta: str):
        if etiqueta in self.tabla_simbolos and self.dry_run:
            self.error("Etiqueta duplicada: " + etiqueta)
        # registrar etiqueta a la posición actual (independientemente de dry_run)
        self.tabla_simbolos[etiqueta] = self.contador_posicion

    def procesar_linea(self, linea: str):
        linea = self.limpiar_linea(linea)
        if linea == "":
            return

        colon_pos = linea.find(':')
        if colon_pos != -1:
            etiqueta = self.trim_copy(linea[:colon_pos])
            resto = self.trim_copy(linea[colon_pos+1:])
            if etiqueta != "":
                self.procesar_etiqueta(etiqueta)
            if resto != "":
                self.procesar_instruccion(resto)
            return
        elif self.es_etiqueta(linea):
            etiqueta = self.trim_copy(linea[:-1])
            self.procesar_etiqueta(etiqueta)
            return

        self.procesar_instruccion(linea)

    # ---------- Emisión bytes / ModR/M / SIB (soporta dry_run) ----------
    def generar_modrm(self, mod: int, reg: int, rm: int) -> int:
        modrm = 0
        modrm |= (mod & 0b11) << 6
        modrm |= (reg & 0b111) << 3
        modrm |= (rm & 0b111)
        return modrm

    def emit_byte(self, byte: int):
        if self.dry_run:
            self.contador_posicion += 1
            return
        self.codigo_hex.append(byte & 0xFF)
        self.contador_posicion += 1

    def emit_dword(self, dword: int):
        for shift in (0,8,16,24):
            self.emit_byte((dword >> shift) & 0xFF)

    def _emit_modrm(self, mod: int, reg: int, rm: int):
        self.emit_byte(self.generar_modrm(mod, reg, rm))

    def _emit_modrm_reg_reg(self, reg_dest: str, reg_src: str):
        td = self.generar_token(reg_dest)
        ts = self.generar_token(reg_src)
        rd = self.get_reg_code(td, reg_dest)
        rs = self.get_reg_code(ts, reg_src)
        self.emit_byte(self.generar_modrm(0b11, rd, rs))

    def _emit_modrm_disp(self, reg_code: int, mem: MemOperand):
        mod = mem.mod
        rm = mem.rm

        if mem.label:
            mod = 0b00
            rm = 0b101

        if mem.usa_sib:
            rm = 0b100
            if mem.tiene_disp:
                if -128 <= mem.displacement <= 127:
                    mod = 0b01
                else:
                    mod = 0b10
            else:
                mod = 0b00

        self.emit_byte(self.generar_modrm(mod, reg_code, rm))

        if mem.usa_sib:
            ss = 0
            if mem.escala == 1: ss = 0
            elif mem.escala == 2: ss = 1
            elif mem.escala == 4: ss = 2
            elif mem.escala == 8: ss = 3

            index = 0b100
            base = 0b101

            if mem.index_reg:
                t = self.generar_token(mem.index_reg)
                index = self.get_reg_code(t, mem.index_reg)
            if mem.base_reg:
                t2 = self.generar_token(mem.base_reg)
                base = self.get_reg_code(t2, mem.base_reg)
            else:
                if mod == 0b00:
                    base = 0b101

            sib = (ss << 6) | ((index & 0b111) << 3) | (base & 0b111)
            self.emit_byte(sib)

        if mem.label:
            pos_parche = self.contador_posicion
            # en pasada1 reservamos 4 bytes si dry_run, en pasada2 escribimos dword y guardamos referencia
            self.emit_dword(0x00000000)
            # Guardamos referencia con bandera ABS32 (0x40000000)
            self.referencias_pendientes.setdefault(mem.label, []).append(pos_parche | 0x40000000)
        elif mem.tiene_disp:
            if -128 <= mem.displacement <= 127:
                self.emit_byte(mem.displacement & 0xFF)
            else:
                self.emit_dword(mem.displacement & 0xFFFFFFFF)
        elif (not mem.usa_sib) and mem.mod == 0b01 and mem.rm == 0b101:
            # edge case [EBP] with mod=01 -> disp8 zero
            self.emit_byte(0x00)

    # ---------- Análisis operandos / memoria ----------
    def analyze_operand(self, s: str) -> OperandInfo:
        op = OperandInfo()
        op.original_str = self.trim_copy(s)
        t = op.original_str
        if t == "":
            return op

        if t.startswith('[') and t.endswith(']'):
            op.es_memoria = True
            op.mem = self.analyze_memory_operand(t)
            return op

        tok = self.generar_token(t)
        if tok == Token.NUMBER:
            op.es_inmediato = True
            op.inmediato = self.parse_immediate(t)
            op.type = Token.NUMBER
            return op

        if tok != Token.UNKNOWN:
            op.es_registro = True
            op.registro = t
            op.type = tok
            return op

        op.type = Token.UNKNOWN
        op.original_str = t
        return op

    def analyze_memory_operand(self, s: str) -> MemOperand:
        mem = MemOperand()
        mem.is_memory = True
        mem.original_str = s
        inside = self.trim_copy(s[1:-1])

        # label case: [LABEL]
        if (re.search(r"[\+\-\*]", inside) is None and
            not self.es_etiqueta(inside) and
            self.generar_token(inside) == Token.UNKNOWN and
            not re.match(r"^[0-9]+$", inside)):
            mem.label = inside
            mem.mod = 0b00
            mem.rm = 0b101
            return mem

        texto = inside.replace(" ", "")

        pos_mul = texto.find('*')
        if pos_mul != -1:
            mem.usa_sib = True
            before_mul = texto[:pos_mul]
            after_mul = texto[pos_mul+1:]

            idx_sep_plus = before_mul.rfind('+')
            idx_sep_minus = before_mul.rfind('-')
            idx_sep = max(idx_sep_plus, idx_sep_minus)
            if idx_sep != -1:
                mem.index_reg = before_mul[idx_sep+1:]
                potential_base = before_mul[:idx_sep]
                if potential_base != "":
                    mem.base_reg = potential_base
            else:
                mem.index_reg = before_mul

            plus_pos = after_mul.find('+')
            minus_pos = after_mul.find('-')

            if plus_pos == -1 and minus_pos == -1:
                try:
                    mem.escala = int(after_mul)
                except Exception:
                    mem.escala = int(self.parse_immediate(after_mul))
                mem.tiene_disp = False
            else:
                if plus_pos != -1 and minus_pos != -1:
                    sep = min(plus_pos, minus_pos)
                else:
                    sep = plus_pos if plus_pos != -1 else minus_pos

                escala_str = after_mul[:sep]
                try:
                    mem.escala = int(escala_str)
                except Exception:
                    mem.escala = int(self.parse_immediate(escala_str))

                resto = after_mul[sep+1:]
                t = self.generar_token(resto)
                if t != Token.UNKNOWN and t != Token.NUMBER:
                    if mem.base_reg == "":
                        mem.base_reg = resto
                else:
                    mem.tiene_disp = True
                    try:
                        mem.displacement = int(resto, 10)
                    except Exception:
                        mem.displacement = self.parse_immediate(resto)

            mem.index_reg = mem.index_reg.strip() if mem.index_reg else ""
            mem.base_reg = mem.base_reg.strip() if mem.base_reg else ""

            if mem.base_reg:
                base_tok = self.generar_token(mem.base_reg)
                if base_tok != Token.UNKNOWN:
                    mem.rm = self.get_reg_code(base_tok, mem.base_reg)
                else:
                    pass
            else:
                pass

            return mem

        plus_pos = texto.find('+')
        minus_pos = texto.find('-', 1)

        if plus_pos == -1 and minus_pos == -1:
            t = self.generar_token(texto)
            if t != Token.UNKNOWN:
                mem.base_reg = texto
                mem.usa_sib = False
                mem.mod = 0b00
                mem.rm = self.get_reg_code(t, texto)
                if t == Token.ESP:
                    mem.usa_sib = True
                    mem.index_reg = ""
                    mem.base_reg = "ESP"
                    mem.escala = 1
                return mem

        base = ""
        disp = ""
        if plus_pos != -1:
            base = texto[:plus_pos]
            disp = texto[plus_pos+1:]
        else:
            base = texto[:minus_pos]
            disp = texto[minus_pos:]

        base_token = self.generar_token(base)
        if base_token != Token.UNKNOWN:
            mem.base_reg = base
            try:
                mem.displacement = int(disp, 10)
            except Exception:
                mem.displacement = self.parse_immediate(disp)
            mem.tiene_disp = True
            if -128 <= mem.displacement <= 127:
                mem.mod = 0b01
            else:
                mem.mod = 0b10
            mem.rm = self.get_reg_code(base_token, base)
            if base_token == Token.ESP:
                mem.usa_sib = True
                mem.index_reg = ""
                mem.escala = 1
            return mem

        self.error("No se pudo analizar operando de memoria: " + s)
        return mem

    # ---------- Procesar instrucciones (dispatcher) ----------
    def procesar_instruccion(self, linea: str):
        if linea.strip() == "":
            return
        parts = linea.split(None, 1)
        mnem = parts[0]
        operandos = parts[1] if len(parts) > 1 else ""
        up = mnem.upper()

        dispatch = {
            "MOV": self.procesar_mov, "ADD": self.procesar_add, "SUB": self.procesar_sub,
            "CMP": self.procesar_cmp, "AND": self.procesar_and, "OR": self.procesar_or,
            "XOR": self.procesar_xor, "INC": self.procesar_inc, "DEC": self.procesar_dec,
            "PUSH": self.procesar_push, "POP": self.procesar_pop, "RET": lambda x=None: self.procesar_ret(),
            "NOP": lambda x=None: self.procesar_nop(), "JMP": self.procesar_jmp, "CALL": self.procesar_call,
            "JE": self.procesar_je, "JNE": self.procesar_jne, "JL": self.procesar_jl, "JG": self.procesar_jg,
            "JLE": self.procesar_jle, "JGE": self.procesar_jge, "LOOP": self.procesar_loop,
            "MUL": self.procesar_mul, "IMUL": self.procesar_imul, "DIV": self.procesar_div, "IDIV": self.procesar_idiv,
            "TEST": self.procesar_test, "MOVZX": self.procesar_movzx, "LEA": self.procesar_lea, "XCHG": self.procesar_xchg,
            "DD": lambda ops: self.procesar_data_directive(mnem, ops),
            # aliases
            "JZ": self.procesar_je, "JNZ": self.procesar_jne
        }

        if up in dispatch:
            func = dispatch[up]
            try:
                func(operandos)
            except TypeError:
                func()
            return

        self.error("Mnemónico desconocido: " + mnem)

    # ---------- Instrucciones implementadas ----------
    def procesar_mov(self, operandos: str):
        ops = self.split_operands(operandos)
        if len(ops) != 2: self.error("MOV requiere 2 operandos: " + operandos)
        op1 = self.analyze_operand(ops[0])
        op2 = self.analyze_operand(ops[1])

        # MOV reg, imm (r8 or r32)
        if op1.es_registro and op2.es_inmediato:
            t = self.generar_token(op1.registro)
            reg = self.get_reg_code(t, op1.registro)
            if t in (Token.AL, Token.CL, Token.DL, Token.BL, Token.AH, Token.CH, Token.DH, Token.BH):
                if op2.inmediato < -128 or op2.inmediato > 255:
                    self.error("MOV: inmediato fuera de rango para registro 8-bit: " + operandos)
                self.emit_byte(0xB0 + reg)
                self.emit_byte(op2.inmediato & 0xFF)
                return
            # r32
            self.emit_byte(0xB8 + reg)
            self.emit_dword(op2.inmediato)
            return

        # MOV reg, reg
        if op1.es_registro and op2.es_registro:
            self.emit_byte(0x8B)
            self._emit_modrm_reg_reg(op1.registro, op2.registro)
            return

        # MOV reg, mem
        if op1.es_registro and op2.es_memoria:
            self.emit_byte(0x8B)
            t = self.generar_token(op1.registro)
            reg = self.get_reg_code(t, op1.registro)
            self._emit_modrm_disp(reg, op2.mem)
            return

        # MOV mem, reg
        if op1.es_memoria and op2.es_registro:
            self.emit_byte(0x89)
            t = self.generar_token(op2.registro)
            reg = self.get_reg_code(t, op2.registro)
            self._emit_modrm_disp(reg, op1.mem)
            return

        # MOV mem, imm32
        if op1.es_memoria and op2.es_inmediato:
            self.emit_byte(0xC7)
            self._emit_modrm_disp(0, op1.mem)
            self.emit_dword(op2.inmediato)
            return

        self.error("Forma no válida de MOV: " + operandos)

    def procesar_add(self, operandos: str):
        ops = self.split_operands(operandos)
        if len(ops) != 2: self.error("ADD requiere 2 operandos: " + operandos)
        op1 = self.analyze_operand(ops[0])
        op2 = self.analyze_operand(ops[1])

        if op1.es_registro and op2.es_inmediato:
            t = self.generar_token(op1.registro)
            reg = self.get_reg_code(t, op1.registro)
            self.emit_byte(0x81)
            self._emit_modrm(0b11, 0, reg)
            self.emit_dword(op2.inmediato)
            return

        if op1.es_registro and op2.es_registro:
            self.emit_byte(0x03)
            self._emit_modrm_reg_reg(op1.registro, op2.registro)
            return

        if op1.es_registro and op2.es_memoria:
            self.emit_byte(0x03)
            t = self.generar_token(op1.registro)
            reg = self.get_reg_code(t, op1.registro)
            self._emit_modrm_disp(reg, op2.mem)
            return

        if op1.es_memoria and op2.es_registro:
            self.emit_byte(0x01)
            t = self.generar_token(op2.registro)
            reg = self.get_reg_code(t, op2.registro)
            self._emit_modrm_disp(reg, op1.mem)
            return

        if op1.es_memoria and op2.es_inmediato:
            self.emit_byte(0x81)
            self._emit_modrm_disp(0, op1.mem)
            self.emit_dword(op2.inmediato)
            return

        self.error("Forma no válida de ADD: " + operandos)

    def procesar_sub(self, operandos: str):
        ops = self.split_operands(operandos)
        if len(ops) != 2: self.error("SUB requiere 2 operandos: " + operandos)
        op1 = self.analyze_operand(ops[0])
        op2 = self.analyze_operand(ops[1])

        if op1.es_registro and op2.es_inmediato:
            t = self.generar_token(op1.registro)
            reg = self.get_reg_code(t, op1.registro)
            self.emit_byte(0x81)
            self._emit_modrm(0b11, 5, reg)
            self.emit_dword(op2.inmediato)
            return

        if op1.es_registro and op2.es_registro:
            self.emit_byte(0x2B)
            self._emit_modrm_reg_reg(op1.registro, op2.registro)
            return

        if op1.es_registro and op2.es_memoria:
            self.emit_byte(0x2B)
            t = self.generar_token(op1.registro)
            reg = self.get_reg_code(t, op1.registro)
            self._emit_modrm_disp(reg, op2.mem)
            return

        if op1.es_memoria and op2.es_registro:
            self.emit_byte(0x29)
            t = self.generar_token(op2.registro)
            reg = self.get_reg_code(t, op2.registro)
            self._emit_modrm_disp(reg, op1.mem)
            return

        self.error("Forma no válida de SUB: " + operandos)

    def procesar_cmp(self, operandos: str):
        ops = self.split_operands(operandos)
        if len(ops) != 2: self.error("CMP requiere 2 operandos: " + operandos)
        op1 = self.analyze_operand(ops[0])
        op2 = self.analyze_operand(ops[1])

        if op1.es_registro and op2.es_registro:
            self.emit_byte(0x3B)
            self._emit_modrm_reg_reg(op1.registro, op2.registro)
            return

        if op1.es_registro and op2.es_inmediato:
            t = self.generar_token(op1.registro)
            reg = self.get_reg_code(t, op1.registro)
            self.emit_byte(0x81)
            self.emit_byte(self.generar_modrm(0b11, 7, reg))
            self.emit_dword(op2.inmediato)
            return

        if op1.es_registro and op2.es_memoria:
            t = self.generar_token(op1.registro)
            reg = self.get_reg_code(t, op1.registro)
            self.emit_byte(0x3B)
            self._emit_modrm_disp(reg, op2.mem)
            return

        if op1.es_memoria and op2.es_registro:
            t = self.generar_token(op2.registro)
            reg = self.get_reg_code(t, op2.registro)
            self.emit_byte(0x39)
            self._emit_modrm_disp(reg, op1.mem)
            return

        if op1.es_memoria and op2.es_inmediato:
            self.emit_byte(0x81)
            self._emit_modrm_disp(7, op1.mem)
            self.emit_dword(op2.inmediato)
            return

        self.error("Forma no válida de CMP: " + operandos)

    def procesar_and(self, operandos: str):
        ops = self.split_operands(operandos)
        if len(ops) != 2: self.error("AND requiere 2 operandos: " + operandos)
        op1 = self.analyze_operand(ops[0]); op2 = self.analyze_operand(ops[1])

        if op1.es_registro and op2.es_registro:
            self.emit_byte(0x23)
            self._emit_modrm_reg_reg(op1.registro, op2.registro); return

        if op1.es_registro and op2.es_memoria:
            t = self.generar_token(op1.registro); reg = self.get_reg_code(t, op1.registro)
            self.emit_byte(0x23); self._emit_modrm_disp(reg, op2.mem); return

        if op1.es_memoria and op2.es_registro:
            t = self.generar_token(op2.registro); reg = self.get_reg_code(t, op2.registro)
            self.emit_byte(0x21); self._emit_modrm_disp(reg, op1.mem); return

        if (op1.es_registro or op1.es_memoria) and op2.es_inmediato:
            if op1.es_registro:
                reg = self.get_reg_code(self.generar_token(op1.registro), op1.registro)
                self.emit_byte(0x81); self.emit_byte(self.generar_modrm(0b11, 4, reg))
                self.emit_dword(op2.inmediato); return
            else:
                self.emit_byte(0x81); self._emit_modrm_disp(4, op1.mem)
                self.emit_dword(op2.inmediato); return

        self.error("Forma no válida de AND: " + operandos)

    def procesar_or(self, operandos: str):
        ops = self.split_operands(operandos); 
        if len(ops) != 2: self.error("OR requiere 2 operandos: " + operandos)
        op1 = self.analyze_operand(ops[0]); op2 = self.analyze_operand(ops[1])

        if op1.es_registro and op2.es_registro:
            self.emit_byte(0x0B); self._emit_modrm_reg_reg(op1.registro, op2.registro); return
        if op1.es_registro and op2.es_memoria:
            reg = self.get_reg_code(self.generar_token(op1.registro), op1.registro)
            self.emit_byte(0x0B); self._emit_modrm_disp(reg, op2.mem); return
        if op1.es_memoria and op2.es_registro:
            reg = self.get_reg_code(self.generar_token(op2.registro), op2.registro)
            self.emit_byte(0x09); self._emit_modrm_disp(reg, op1.mem); return
        if (op1.es_registro or op1.es_memoria) and op2.es_inmediato:
            if op1.es_registro:
                reg = self.get_reg_code(self.generar_token(op1.registro), op1.registro)
                self.emit_byte(0x81); self.emit_byte(self.generar_modrm(0b11, 1, reg)); self.emit_dword(op2.inmediato); return
            else:
                self.emit_byte(0x81); self._emit_modrm_disp(1, op1.mem); self.emit_dword(op2.inmediato); return
        self.error("Forma no válida de OR: " + operandos)

    def procesar_xor(self, operandos: str):
        ops = self.split_operands(operandos); 
        if len(ops) != 2: self.error("XOR requiere 2 operandos: " + operandos)
        op1 = self.analyze_operand(ops[0]); op2 = self.analyze_operand(ops[1])

        if op1.es_registro and op2.es_registro:
            self.emit_byte(0x33); self._emit_modrm_reg_reg(op1.registro, op2.registro); return
        if op1.es_registro and op2.es_memoria:
            reg = self.get_reg_code(self.generar_token(op1.registro), op1.registro); self.emit_byte(0x33); self._emit_modrm_disp(reg, op2.mem); return
        if op1.es_memoria and op2.es_registro:
            reg = self.get_reg_code(self.generar_token(op2.registro), op2.registro); self.emit_byte(0x31); self._emit_modrm_disp(reg, op1.mem); return
        if (op1.es_registro or op1.es_memoria) and op2.es_inmediato:
            if op1.es_registro:
                reg = self.get_reg_code(self.generar_token(op1.registro), op1.registro); self.emit_byte(0x81); self.emit_byte(self.generar_modrm(0b11, 6, reg)); self.emit_dword(op2.inmediato); return
            else:
                self.emit_byte(0x81); self._emit_modrm_disp(6, op1.mem); self.emit_dword(op2.inmediato); return
        self.error("Forma no válida de XOR: " + operandos)

    def procesar_inc(self, operandos: str):
        r = self.trim_copy(operandos)
        t = self.generar_token(r)
        if t in self.reg_token_map:
            self.emit_byte(0x40 + self.get_reg_code(t, r)); return
        self.error("INC: operando inválido: " + operandos)

    def procesar_dec(self, operandos: str):
        r = self.trim_copy(operandos)
        t = self.generar_token(r)
        if t in self.reg_token_map:
            self.emit_byte(0x48 + self.get_reg_code(t, r)); return
        self.error("DEC: operando inválido: " + operandos)

    def procesar_push(self, operandos: str):
        o = self.trim_copy(operandos)
        op = self.analyze_operand(o)
        if op.es_registro:
            self.emit_byte(0x50 + self.get_reg_code(self.generar_token(op.registro), op.registro)); return
        self.error("PUSH: solo soportado PUSH reg32: " + operandos)

    def procesar_pop(self, operandos: str):
        o = self.trim_copy(operandos)
        op = self.analyze_operand(o)
        if op.es_registro:
            self.emit_byte(0x58 + self.get_reg_code(self.generar_token(op.registro), op.registro)); return
        self.error("POP: solo soportado POP reg32: " + operandos)

    def procesar_ret(self):
        self.emit_byte(0xC3)

    def procesar_nop(self):
        self.emit_byte(0x90)

    # Jumps/calls (en pasada1 reservan espacios como en pasada2)
    def procesar_jmp(self, operandos: str):
        label = self.trim_copy(operandos)
        self.emit_byte(0xE9)
        pos = self.contador_posicion
        self.emit_dword(0x00000000)
        # almacenamos referencia rel32 (pos)
        self.referencias_pendientes.setdefault(label, []).append(pos)

    def procesar_call(self, operandos: str):
        label = self.trim_copy(operandos)
        self.emit_byte(0xE8)
        pos = self.contador_posicion
        self.emit_dword(0x00000000)
        self.referencias_pendientes.setdefault(label, []).append(pos)

    def procesar_cond_jump(self, operandos: str, opcode: int):
        label = self.trim_copy(operandos)
        self.emit_byte(opcode)
        pos = self.contador_posicion
        self.emit_byte(0x00)
        # almacenamos referencia rel8 marcada con 0x80000000
        self.referencias_pendientes.setdefault(label, []).append(pos | 0x80000000)

    def procesar_je(self, operandos: str): self.procesar_cond_jump(operandos, 0x74)
    def procesar_jne(self, operandos: str): self.procesar_cond_jump(operandos, 0x75)
    def procesar_jl(self, operandos: str): self.procesar_cond_jump(operandos, 0x7C)
    def procesar_jg(self, operandos: str): self.procesar_cond_jump(operandos, 0x7F)
    def procesar_jle(self, operandos: str): self.procesar_cond_jump(operandos, 0x7E)
    def procesar_jge(self, operandos: str): self.procesar_cond_jump(operandos, 0x7D)

    def procesar_loop(self, etiqueta: str):
        label = self.trim_copy(etiqueta)
        self.emit_byte(0xE2)
        pos = self.contador_posicion
        self.emit_byte(0x00)
        self.referencias_pendientes.setdefault(label, []).append(pos | 0x80000000)

    def procesar_mul(self, operandos: str):
        o = self.trim_copy(operandos)
        if o.startswith('['):
            m = self.analyze_memory_operand(o)
            self.emit_byte(0xF7)
            self._emit_modrm_disp(4, m)
            return
        else:
            t = self.generar_token(o)
            if t in self.reg_token_map:
                self.emit_byte(0xF7)
                self.emit_byte(self.generar_modrm(0b11, 4, self.get_reg_code(t, o)))
                return
        self.error("MUL: operando inválido: " + operandos)

    def procesar_imul(self, operandos: str):
        ops = self.split_operands(operandos)
        if len(ops) == 1:
            o = self.trim_copy(ops[0])
            if o.startswith('['):
                m = self.analyze_memory_operand(o)
                self.emit_byte(0xF7)
                self._emit_modrm_disp(5, m)
                return
            else:
                t = self.generar_token(o)
                if t in self.reg_token_map:
                    self.emit_byte(0xF7)
                    self.emit_byte(self.generar_modrm(0b11, 5, self.get_reg_code(t, o)))
                    return
            self.error("IMUL: operando inválido: " + operandos)
        elif len(ops) == 2:
            dst = self.trim_copy(ops[0]); src = self.trim_copy(ops[1])
            td = self.generar_token(dst)
            if td not in self.reg_token_map:
                self.error("IMUL: destino inválido: " + dst)
            self.emit_byte(0x0F); self.emit_byte(0xAF)
            if src.startswith('['):
                m = self.analyze_memory_operand(src); self._emit_modrm_disp(self.get_reg_code(td, dst), m)
            else:
                ts = self.generar_token(src)
                if ts not in self.reg_token_map:
                    self.error("IMUL: fuente inválida: " + src)
                self.emit_byte(self.generar_modrm(0b11, self.get_reg_code(ts, src), self.get_reg_code(td, dst)))
        elif len(ops) == 3:
            dst = self.trim_copy(ops[0]); src = self.trim_copy(ops[1]); imm_s = self.trim_copy(ops[2])
            td = self.generar_token(dst)
            if td not in self.reg_token_map:
                self.error("IMUL: destino inválido: " + dst)
            imm = int(self.parse_immediate(imm_s))
            imm8 = (-128 <= imm <= 127)
            self.emit_byte(0x6B if imm8 else 0x69)
            if src.startswith('['):
                m = self.analyze_memory_operand(src); self._emit_modrm_disp(self.get_reg_code(td, dst), m)
            else:
                ts = self.generar_token(src)
                if ts not in self.reg_token_map:
                    self.error("IMUL: fuente inválida: " + src)
                self.emit_byte(self.generar_modrm(0b11, self.get_reg_code(ts, src), self.get_reg_code(td, dst)))
            if imm8:
                self.emit_byte(imm & 0xFF)
            else:
                self.emit_dword(imm & 0xFFFFFFFF)
        else:
            self.error("IMUL: sintaxis inválida: " + operandos)

    def procesar_div(self, operandos: str):
        o = self.trim_copy(operandos)
        self.emit_byte(0xF7)
        if o.startswith('['):
            m = self.analyze_memory_operand(o); self._emit_modrm_disp(6, m); return
        else:
            t = self.generar_token(o)
            if t in self.reg_token_map:
                self.emit_byte(self.generar_modrm(0b11, 6, self.get_reg_code(t, o))); return
        self.error("DIV: operando inválido: " + operandos)

    def procesar_idiv(self, operandos: str):
        o = self.trim_copy(operandos)
        self.emit_byte(0xF7)
        if o.startswith('['):
            m = self.analyze_memory_operand(o); self._emit_modrm_disp(7, m); return
        else:
            t = self.generar_token(o)
            if t in self.reg_token_map:
                self.emit_byte(self.generar_modrm(0b11, 7, self.get_reg_code(t, o))); return
        self.error("IDIV: operando inválido: " + operandos)

    def procesar_test(self, operandos: str):
        ops = self.split_operands(operandos)
        if len(ops) != 2: self.error("TEST requiere 2 operandos: " + operandos)
        a = self.analyze_operand(ops[0]); b = self.analyze_operand(ops[1])

        if a.es_registro and b.es_registro:
            self.emit_byte(0x85)
            self.emit_byte(self.generar_modrm(0b11, self.get_reg_code(self.generar_token(b.registro), b.registro), self.get_reg_code(self.generar_token(a.registro), a.registro)))
            return

        if a.es_memoria and b.es_registro:
            tr = self.generar_token(b.registro); self.emit_byte(0x85); self._emit_modrm_disp(self.get_reg_code(tr, b.registro), a.mem); return
        if a.es_registro and b.es_memoria:
            tr = self.generar_token(a.registro); self.emit_byte(0x85); self._emit_modrm_disp(self.get_reg_code(tr, a.registro), b.mem); return

        if a.es_memoria and b.es_inmediato:
            self.emit_byte(0xF7); self._emit_modrm_disp(0, a.mem); self.emit_dword(b.inmediato); return

        if a.es_registro and b.es_inmediato:
            self.emit_byte(0xF7); self.emit_byte(self.generar_modrm(0b11, 0, self.get_reg_code(self.generar_token(a.registro), a.registro))); self.emit_dword(b.inmediato); return

        self.error("TEST: forma no soportada: " + operandos)

    def procesar_movzx(self, operandos: str):
        ops = self.split_operands(operandos)
        if len(ops) != 2: self.error("MOVZX requiere 2 operandos: " + operandos)
        dst = self.trim_copy(ops[0]); src = self.trim_copy(ops[1])
        td = self.generar_token(dst)
        if td not in self.reg_token_map: self.error("MOVZX: destino inválido: " + dst)
        self.emit_byte(0x0F); self.emit_byte(0xB6)
        if src.startswith('['):
            m = self.analyze_memory_operand(src); self._emit_modrm_disp(self.get_reg_code(td, dst), m)
        else:
            ts = self.generar_token(src)
            if ts not in self.reg_token_map: self.error("MOVZX: fuente inválida: " + src)
            self.emit_byte(self.generar_modrm(0b11, self.get_reg_code(ts, src), self.get_reg_code(td, dst)))

    def procesar_lea(self, operandos: str):
        ops = self.split_operands(operandos)
        if len(ops) != 2: self.error("LEA requiere 2 operandos: " + operandos)
        dst = self.trim_copy(ops[0]); src = self.trim_copy(ops[1])
        td = self.generar_token(dst)
        if td not in self.reg_token_map: self.error("LEA: destino inválido: " + dst)
        if not (src.startswith('[') and src.endswith(']')): self.error("LEA: segundo operando debe ser memoria: " + src)
        self.emit_byte(0x8D)
        m = self.analyze_memory_operand(src)
        self._emit_modrm_disp(self.get_reg_code(td, dst), m)

    def procesar_xchg(self, operandos: str):
        ops = self.split_operands(operandos)
        if len(ops) != 2: self.error("XCHG requiere 2 operandos: " + operandos)
        a = self.trim_copy(ops[0]); b = self.trim_copy(ops[1])
        ta = self.generar_token(a); tb = self.generar_token(b)
        if ta == Token.EAX and tb in self.reg_token_map:
            self.emit_byte(0x90 + self.get_reg_code(tb, b)); return
        if ta in self.reg_token_map and tb in self.reg_token_map:
            self.emit_byte(0x87); self.emit_byte(self.generar_modrm(0b11, self.get_reg_code(tb, b), self.get_reg_code(ta, a))); return
        if a.startswith('[') and tb in self.reg_token_map:
            ma = self.analyze_memory_operand(a); self.emit_byte(0x87); self._emit_modrm_disp(self.get_reg_code(tb, b), ma); return
        if b.startswith('[') and ta in self.reg_token_map:
            mb = self.analyze_memory_operand(b); self.emit_byte(0x87); self._emit_modrm_disp(self.get_reg_code(ta, a), mb); return
        self.error("XCHG: forma no soportada: " + operandos)

    def procesar_data_directive(self, mnem: str, operandos: str):
        up = mnem.upper()
        if up == "DD":
            val = self.parse_immediate(operandos.strip())
            self.emit_dword(val)
            return
        self.error("Directiva no soportada: " + mnem)

    # ---------- Resolver referencias pendientes y salidas ----------
    def resolver_referencias_pendientes(self):
        for simbolo, pos_raw in list(self.referencias_pendientes.items()):
            if simbolo not in self.tabla_simbolos:
                self.error("Etiqueta o símbolo no definido: " + simbolo)
            destino = self.tabla_simbolos[simbolo]
            for pos_r in pos_raw:
                is_rel8 = (pos_r & 0x80000000) != 0
                is_abs32 = (pos_r & 0x40000000) != 0
                pos = pos_r & 0x3FFFFFFF

                if is_abs32:
                    dir = destino
                    self._write_bytes_at(pos, [
                        (dir & 0xFF),
                        ((dir >> 8) & 0xFF),
                        ((dir >> 16) & 0xFF),
                        ((dir >> 24) & 0xFF)
                    ])
                    continue

                bytes_disp = 1 if is_rel8 else 4
                next_instr = pos + bytes_disp
                disp = destino - next_instr
                if is_rel8:
                    if disp < -128 or disp > 127:
                        print(f"Aviso: salto corto fuera de rango a {simbolo}", file=sys.stderr)
                    self._write_bytes_at(pos, [disp & 0xFF])
                else:
                    self._write_bytes_at(pos, [
                        (disp & 0xFF),
                        ((disp >> 8) & 0xFF),
                        ((disp >> 16) & 0xFF),
                        ((disp >> 24) & 0xFF)
                    ])

    def _write_bytes_at(self, pos: int, bytes_list: List[int]):
        while len(self.codigo_hex) < pos + len(bytes_list):
            self.codigo_hex.append(0)
        for i, b in enumerate(bytes_list):
            self.codigo_hex[pos + i] = b & 0xFF

    def generar_hex(self, archivo_salida: str):
        try:
            with open(archivo_salida, "w", encoding="utf-8") as f:
                for b in self.codigo_hex:
                    f.write(f"{b:02X} ")
        except Exception:
            print("No se pudo crear " + archivo_salida, file=sys.stderr)
            return
        print("Generado: " + archivo_salida)

    def generar_reportes(self):
        try:
            with open("simbolos.txt", "w", encoding="utf-8") as simb:
                simb.write("Tabla de Símbolos:\n")
                for name, addr in self.tabla_simbolos.items():
                    simb.write(f"{name} \t @ 0x{addr:X}\n")
            with open("referencias.txt", "w", encoding="utf-8") as refs:
                refs.write("Referencias pendientes:\n")
                for name, arr in self.referencias_pendientes.items():
                    refs.write(f"{name} : ")
                    for x in arr:
                        refs.write(f"{x:X} ")
                    refs.write("\n")
            print("Reportes: simbolos.txt, referencias.txt")
        except Exception as e:
            print("Error generando reportes: " + str(e), file=sys.stderr)

    def trim_copy(self, s: str) -> str:
        return s.strip()

# -------------------- main --------------------
if __name__ == "__main__":
    filename = "prueba.asm"
    if len(sys.argv) > 1:
        filename = sys.argv[1]
    ens = EnsambladorTwoPass()
    ens.parse(filename)
