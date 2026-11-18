"""Compilador de um subconjunto NTSL para simulação em barras."""
from collections import deque
from dataclasses import dataclass
import math
import re


TOKEN = re.compile(
    r'(?P<skip>\s+|\{[^}]*\}|\(\*.*?\*\)|//[^\n]*)'
    r'|(?P<string>"(?:[^"\n]|"")*")'
    r'|(?P<number>(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?)'
    r'|(?P<id>[A-Za-z_]\w*)|(?P<op>:=|<=|>=|<>|[;.,():\[\]+*/=<>-])',
    re.S,
)

SERIES = {
    "open": "abertura", "high": "maxima", "low": "minima", "close": "fechamento",
    "volume": "volume", "quantity": "volume_contratos", "trades": "v_trades_atual",
    "bidprice": "v_bid", "askprice": "v_ask", "bidsize": "v_qtd_bid", "asksize": "v_qtd_ask",
    "agressionvolbuy": "v_agressao_compra", "agressionvolsell": "v_agressao_venda",
    "date": "data_ntsl", "time": "hora_ntsl", "currentbar": "barra_ntsl",
}
STATE = {
    "isbought", "issold", "hasposition", "haspendingorders", "buyprice", "sellprice",
    "price", "position", "buyposition", "sellposition", "minpriceincrement",
}
FUNCTIONS = {
    "abs": (1, 1), "max": (2, 2), "min": (2, 2), "sqrt": (1, 1),
    "round": (1, 1), "floor": (1, 1), "ceiling": (1, 1), "power": (2, 2),
    "totalbuyqtd": (0, 2), "totalsellqtd": (0, 2), "dailyresult": (0, 1),
    "buyatmarket": (0, 1),
    "sellshortatmarket": (0, 1), "selltocoveratmarket": (0, 1), "buytocoveratmarket": (0, 1),
    "buyatlimit": (1, 2), "sellshortatlimit": (1, 2),
    "selltocoverlimit": (1, 2), "buytocoverlimit": (1, 2),
    "buyatstop": (1, 3), "sellshortatstop": (1, 3),
    "selltocoverstop": (1, 3), "buytocoverstop": (1, 3),
    "closeposition": (0, 0), "cancelpendingorders": (0, 0),
    "plot": (1, 1), "plot2": (1, 1), "plot3": (1, 1), "plot4": (1, 1),
    "paintbar": (1, 1), "consolelog": (1, 2),
}
ROLLING = {"media", "mediaexp", "highest", "lowest", "summation"}
OPERATORS = {"or": 1, "and": 2, "=": 3, "<>": 3, "<": 3, ">": 3, "<=": 3,
             ">=": 3, "+": 4, "-": 4, "*": 5, "/": 5, "mod": 5}
COLORS = {"clgreen": 32768, "cllime": 65280, "clred": 255, "clblue": 16711680,
          "clwhite": 16777215, "clblack": 0, "clyellow": 65535, "clgray": 8421504}


class NTSLError(ValueError):
    pass


@dataclass
class Symbol:
    name: str
    kind: str
    slot: int


class Compiler:
    def __init__(self, source):
        self.tokens = []
        source = source.lstrip('\ufeff')
        pos, line = 0, 1
        while pos < len(source):
            match = TOKEN.match(source, pos)
            if not match:
                raise NTSLError(f"Linha {line}: caractere ou comentário inválido {source[pos:pos+16]!r}.")
            if match.lastgroup != "skip":
                token = match.group()
                self.tokens.append((token if match.lastgroup == "string" else token.lower(), line))
            pos = match.end()
            line += match.group().count('\n')
        self.tokens.append(("<fim>", line))
        self.pos = 0
        self.symbols = {}
        self.defaults = []
        self.inputs = {}
        self.used = set()
        self.rolling = 0
        self.lines = ["def strategy(ctx):", "    v = ctx.values"]

    def peek(self):
        return self.tokens[self.pos][0]

    def fail(self, message):
        raise NTSLError(f"Linha {self.tokens[self.pos][1]}: {message}")

    def take(self, value):
        if self.peek() != value:
            return False
        self.pos += 1
        return True

    def expect(self, value):
        if not self.take(value):
            self.fail(f"esperado {value!r}, encontrado {self.peek()!r}.")

    def identifier(self):
        name = self.peek()
        if not re.fullmatch(r'[a-z_]\w*', name):
            self.fail(f"identificador esperado, encontrado {name!r}.")
        self.pos += 1
        return name

    def declare(self, name, kind, initial=0.0):
        if name in self.symbols or name in (SERIES.keys() | STATE | FUNCTIONS.keys() | ROLLING):
            self.fail(f"identificador já definido ou reservado: {name}.")
        symbol = Symbol(name, kind, len(self.defaults))
        self.symbols[name] = symbol
        self.defaults.append(initial)
        if kind == "input":
            self.inputs[name] = initial

    def literal(self):
        sign = -1 if self.take("-") else 1
        if self.take("true"):
            return True
        if self.take("false"):
            return False
        token = self.peek()
        if re.fullmatch(r'(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?', token):
            self.pos += 1
            value = sign * float(token)
            if not math.isfinite(value):
                self.fail("número fora do intervalo.")
            return value
        self.fail("esperado valor inicial numérico ou booleano.")

    def compile(self):
        while self.peek() in {"input", "var", "const"}:
            section = self.peek()
            self.pos += 1
            while self.peek() not in {"input", "var", "const", "begin", "<fim>"}:
                name = self.identifier()
                if section == "input":
                    self.expect("(")
                    self.declare(name, section, self.literal())
                    self.expect(")")
                elif section == "const":
                    self.expect("=")
                    if self.take("asset"):
                        self.expect("(")
                        self.expect("getasset")
                        self.expect(",")
                        interval = self.identifier()
                        if interval not in {"itsecond", "itminute"}:
                            self.fail("Asset suporta itSecond e itMinute com GetAsset.")
                        self.expect(",")
                        resolution = self.literal()
                        if resolution <= 0:
                            self.fail("resolução do Asset inválida.")
                        self.expect(")")
                        self.declare(name, "asset", ("asset", interval, resolution))
                    else:
                        self.declare(name, section, self.literal())
                else:
                    names = [name]
                    while self.take(","):
                        names.append(self.identifier())
                    self.expect(":")
                    kind = self.identifier()
                    if kind not in {"integer", "float", "boolean", "real"}:
                        self.fail(f"tipo ainda indisponível: {kind}.")
                    for item in names:
                        self.declare(item, kind)
                self.expect(";")
        self.expect("begin")
        self.block(1)
        self.take(";")
        self.take(".")
        self.expect("<fim>")
        namespace = {"__builtins__": {}}
        exec(compile("\n".join(self.lines), "<NTSL compilado>", "exec"), namespace)
        return Program(namespace["strategy"], self.symbols, self.defaults, self.inputs, self.used)

    def emit(self, depth, line):
        self.lines.append("    " * depth + line)

    def block(self, depth):
        start = len(self.lines)
        while self.peek() != "end":
            if self.take(";"):
                continue
            self.statement(depth)
            if self.peek() != "end":
                self.expect(";")
        self.expect("end")
        if len(self.lines) == start:
            self.emit(depth, "pass")

    def statement(self, depth):
        if self.take("begin"):
            self.block(depth)
            return
        if self.take("if"):
            check = self.expression()
            self.expect("then")
            self.emit(depth, f"if {check}:")
            self.statement(depth + 1)
            if self.peek() == ";" and self.tokens[self.pos+1][0] == "else":
                self.pos += 1
            if self.take("else"):
                self.emit(depth, "else:")
                self.statement(depth + 1)
            return
        name = self.identifier()
        if self.take(":="):
            symbol = self.symbols.get(name)
            if symbol is None or symbol.kind not in {"float", "real", "integer", "boolean"}:
                self.fail(f"atribuição inválida a {name}.")
            expression = self.expression()
            if symbol.kind in {"integer", "boolean"}:
                expression = f"ctx.cast({symbol.kind!r},{expression})"
            self.emit(depth, f"v[{symbol.slot}] = {expression}")
        else:
            if name not in FUNCTIONS:
                self.fail(f"instrução não suportada: {name}.")
            self.emit(depth, self.call(name))

    def expression(self, minimum=1):
        token = self.peek()
        if token in {"not", "-", "+"}:
            self.pos += 1
            result = f"({token} {self.expression(6)})"
        elif self.take("("):
            result = self.expression()
            self.expect(")")
        elif token.startswith('"'):
            self.pos += 1
            result = repr(token[1:-1].replace('""', '"'))
        elif token[:1].isdigit() or token.startswith(".") or token in {"true", "false"}:
            result = repr(self.literal())
        else:
            name = self.identifier()
            result = self.reference(name)
        while OPERATORS.get(self.peek(), 0) >= minimum:
            op = self.peek()
            self.pos += 1
            right = self.expression(OPERATORS[op] + 1)
            if op in {"+", "/"}:
                result = f"ctx.{('add' if op == '+' else 'divide')}({result},{right})"
            else:
                python_op = {"=": "==", "<>": "!=", "mod": "%"}.get(op, op)
                result = f"({result} {python_op} {right})"
        return result

    def reference(self, name):
        if name in FUNCTIONS or name in ROLLING:
            return self.call(name)
        offset = None
        if self.take("["):
            offset = self.expression()
            self.expect("]")
        if name in self.symbols:
            symbol = self.symbols[name]
            return f"ctx.read({symbol.slot})" if offset is None else f"ctx.lag({symbol.slot},{offset})"
        if name in SERIES:
            self.used.add(name)
            return f"ctx.series({name!r},{offset or 0})"
        if name in STATE and offset is None:
            return f"ctx.state({name!r})"
        if name in COLORS and offset is None:
            return repr(COLORS[name])
        self.fail(f"recurso ou identificador não suportado: {name}.")

    def call(self, name):
        args = []
        if self.take("("):
            if self.peek() != ")":
                args.append(self.expression())
                while self.take(","):
                    args.append(self.expression())
            self.expect(")")
        self.used.add(name)
        if name in ROLLING:
            if len(args) != 2:
                self.fail(f"{name} exige 2 argumentos.")
            count, value = args if name in {"media", "mediaexp"} else reversed(args)
            self.rolling += 1
            return f"ctx.average({self.rolling},{name!r},{count},lambda:{value})"
        low, high = FUNCTIONS[name]
        if not low <= len(args) <= high:
            self.fail(f"{name} exige entre {low} e {high} argumentos.")
        return f"ctx.call({name!r}{',' if args else ''}{','.join(args)})"


@dataclass
class Program:
    strategy: object
    symbols: dict
    defaults: list
    inputs: dict
    used: set


def compile_ntsl(source):
    try:
        return Compiler(source).compile()
    except RecursionError as error:
        raise NTSLError("Código com expressões ou blocos aninhados demais.") from error


class Rolling:
    def __init__(self, period):
        self.window = deque(maxlen=period)
        self.sum = self.ema = self.value = 0.0
        self.row = -2

    def update(self, row, value, kind):
        if row > self.row + 1:
            self.window.clear()
            self.sum = self.ema = 0.0
        alpha = 2 / (self.window.maxlen + 1)
        self.ema = (value if not self.window else self.ema + alpha * (value - self.ema))
        self.sum += value - (self.window[0] if len(self.window) == self.window.maxlen else 0)
        self.window.append(value)
        self.row = row
        if kind == "media":
            self.value = self.sum / len(self.window)
        elif kind == "mediaexp":
            self.value = self.ema
        elif kind == "summation":
            self.value = self.sum
        else:
            self.value = (max if kind == "highest" else min)(self.window)
        return self.value
