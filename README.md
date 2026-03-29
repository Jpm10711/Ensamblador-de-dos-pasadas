# Ensamblador-de-dos-pasadas
Ensamblador x86 de Dos Pasadas en Python
Descripción
Este proyecto implementa un ensamblador básico para arquitectura x86 utilizando la técnica de
dos pasadas.
Convierte código ensamblador en código máquina en formato hexadecimal.
Características- Construcción de tabla de símbolos- Generación de código máquina- Soporte de etiquetas y saltos- Manejo de direccionamiento (ModR/M y SIB)
Instrucciones Soportadas
MOV, ADD, SUB, CMP, AND, OR, XOR, INC, DEC
MUL, IMUL, DIV, IDIV
JMP, JE, JNE, JL, JG, JLE, JGE, LOOP
CALL, RET, PUSH, POP, NOP
MOVZX, LEA, XCHG, TEST, DD
Funcionamiento
Primera pasada: analiza etiquetas y posiciones
Segunda pasada: genera código máquina
Resolución: corrige direcciones de saltos y referencias
Uso
1. Crear archivo prueba.asm
2. Ejecutar el script en Python
3. Se generan archivos .hex, simbolos.txt y referencias.txt
Limitaciones
- No cubre todo x86- Validación limitada- Saltos cortos pueden fallar
Objetivo
Proyecto educativo para entender ensambladores y arquitectura de computadoras
