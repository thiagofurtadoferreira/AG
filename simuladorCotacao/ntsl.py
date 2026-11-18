"""Compilador de um subconjunto NTSL para simulação em barras."""
from collections import deque
from dataclasses import dataclass
import math
import re


TOKEN = re.compile(
    r'(?P<skip>\s+|\{[^}]*\}|\(\*.*?\*\)|//[^\n]*)'
    r'|(?P<string>"(?:[^"\n]|"")*")'
    r'|(?P<number>(?:\d+\.(?!\.)\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?)'
    r'|(?P<id>[A-Za-z_]\w*)|(?P<op>:=|<=|>=|<>|\.\.|[;.,():\[\]+*/=<>-])',
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
    "positionqty", "buypositionqty", "sellpositionqty",
}
FUNCTIONS = {
    "truerange": (0, 0), "truehigh": (0, 0), "truelow": (0, 0),
    "truerangecustom": (3, 3), "typicalprice": (0, 0), "medianprice": (0, 0),
    "avgprice": (0, 0), "avgtruerange": (2, 2),
    "mod": (2, 2), "intportion": (1, 1), "fracportion": (1, 1), "square": (1, 1),
    "sign": (1, 1), "log": (1, 1), "exp": (1, 1),
    "sendorder": (5, 5), "reverseposition": (0, 0),
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
PURE_FUNCTIONS = {"abs", "min", "max", "sqrt", "round", "floor", "ceiling", "power",
                  "mod", "intportion", "fracportion", "square", "sign", "log", "exp",
                  "truerange", "truehigh", "truelow", "truerangecustom", "typicalprice", "medianprice",
                  "avgprice", "avgtruerange"}
ROLLING = {"media", "mediaexp", "highest", "lowest", "summation"}
OPERATORS = {"or": 1, "and": 2, "=": 3, "<>": 3, "<": 3, ">": 3, "<=": 3,
             ">=": 3, "+": 4, "-": 4, "*": 5, "/": 5, "mod": 5}
COLORS = {"clgreen": 32768, "cllime": 65280, "clred": 255, "clblue": 16711680,
          "clwhite": 16777215, "clblack": 0, "clyellow": 65535, "clgray": 8421504}


ORDER_CONSTANTS = {"osbuy": 1001, "ossell": 1002, "otmarket": 1011, "otlimit": 1012, "otstoplimit": 1013}
SCALARS = {"integer", "float", "boolean", "real"}


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
        self.locals = {}
        self.routines = {}
        self.used_inputs = set()
        self.routine_lines = []
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
        if self.peek().startswith('"') and sign == 1:
            token = self.peek()
            self.pos += 1
            return token[1:-1].replace('""', '"')
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
            while self.peek() not in {"input", "var", "const", "begin", "function", "procedure", "<fim>"}:
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
                    bounds = self.array_type() if kind == "array" else None
                    if kind not in SCALARS and bounds is None:
                        self.fail(f"tipo ainda indisponível: {kind}.")
                    for item in names:
                        self.declare(item, kind, bounds if bounds else 0.0)
                self.expect(";")
        while self.peek() in {"function", "procedure"}:
            self.routine()
        self.expect("begin")
        self.block(1)
        self.take(";")
        self.take(".")
        self.expect("<fim>")
        namespace = {"__builtins__": {}}
        exec(compile("\n".join(self.routine_lines + self.lines), "<NTSL compilado>", "exec"), namespace)
        return Program(namespace["strategy"], self.symbols, self.defaults, self.inputs, self.used, self.used_inputs)

    def array_type(self):
        self.expect("[")
        lower = self.literal()
        if self.take(".."):
            upper = self.literal()
        else:
            lower, upper = 1, lower
        self.expect("]")
        self.expect("of")
        kind = self.identifier()
        if (kind not in SCALARS or type(lower) is not float or type(upper) is not float
                or not lower.is_integer() or not upper.is_integer() or not 0 <= upper-lower < 100_000):
            self.fail("intervalo ou tipo de array inválido (limite de 100.000 elementos).")
        return int(lower), int(upper), kind

    def routine(self):
        procedure = self.take("procedure")
        if not procedure:
            self.expect("function")
        name = self.identifier()
        if name in self.routines or name in self.symbols:
            self.fail(f"rotina duplicada: {name}.")
        args = []
        if self.take("("):
            while self.peek() != ")":
                args.extend(self.local_declarations())
                if not self.take(";"):
                    break
            self.expect(")")
        result = None
        if not procedure:
            self.expect(":")
            result = self.identifier()
            if result not in SCALARS:
                self.fail("tipo de retorno não suportado.")
        self.expect(";")
        locals_decl = []
        if self.take("var"):
            while self.peek() != "begin":
                locals_decl.extend(self.local_declarations())
                self.expect(";")
        declarations = args + locals_decl + ([("result", result)] if result else [])
        self.locals = {n: (i, t) for i, (n, t) in enumerate(declarations)}
        if len(self.locals) != len(declarations):
            self.fail(f"nome local duplicado em {name}.")
        identifier = f"routine_{len(self.routines)}"
        self.routines[name] = (identifier, len(args))
        outer = self.lines
        self.lines = [f"def {identifier}(ctx,*args):", "    v = ctx.values",
                      f"    local = [*args] + {[0.0]*(len(declarations)-len(args))}"]
        for index, (_, kind) in enumerate(args):
            self.emit(1, f"local[{index}] = ctx.cast({kind!r},local[{index}])")
        self.expect("begin")
        self.block(1)
        self.expect(";")
        if result:
            self.emit(1, f"return local[{self.locals['result'][0]}]")
        self.routine_lines.extend(self.lines)
        self.lines = outer
        self.locals = {}

    def local_declarations(self):
        names = [self.identifier()]
        while self.take(","):
            names.append(self.identifier())
        self.expect(":")
        kind = self.identifier()
        if kind not in SCALARS:
            self.fail(f"tipo local não suportado: {kind}.")
        return [(name, kind) for name in names]

    def variable(self, name):
        if name in self.locals:
            index, kind = self.locals[name]
            return f"local[{index}]", kind
        symbol = self.symbols.get(name)
        if symbol:
            return f"v[{symbol.slot}]", symbol.kind
        return None, None

    def index(self):
        if not self.take("["):
            return None
        expression = self.expression()
        self.expect("]")
        return expression

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
        if self.take("for"):
            name = self.identifier()
            destination, kind = self.variable(name)
            if kind != "integer":
                self.fail("o contador do for deve ser uma variável Integer.")
            self.expect(":=")
            start = self.expression()
            step = -1 if self.take("downto") else 1
            if step == 1:
                self.expect("to")
            end = self.expression()
            self.expect("do")
            self.emit(depth, f"for {destination} in ctx.iterate({start},{end},{step}):")
            self.statement(depth+1)
            return
        if self.take("while"):
            condition = self.expression()
            self.expect("do")
            self.emit(depth, f"while {condition}:")
            self.emit(depth+1, "ctx.loop_step()")
            self.statement(depth+1)
            return
        if self.take("repeat"):
            self.emit(depth, "while True:")
            self.emit(depth+1, "ctx.loop_step()")
            while self.peek() != "until":
                self.statement(depth+1)
                if self.peek() != "until":
                    self.expect(";")
            self.expect("until")
            self.emit(depth+1, f"if {self.expression()}: break")
            return
        name = self.identifier()
        offset = self.index()
        if self.take(":="):
            destination, kind = self.variable(name)
            expression = self.expression()
            if kind == "array" and offset is not None:
                slot = self.symbols[name].slot
                self.emit(depth, f"ctx.write_array({slot},{offset},{expression})")
                return
            if kind not in SCALARS or offset is not None:
                self.fail(f"atribuição inválida a {name}.")
            self.emit(depth, f"{destination} = ctx.cast({kind!r},{expression})")
        else:
            if offset is not None or (name not in FUNCTIONS and name not in self.routines):
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
        if name in self.locals:
            if self.peek() == "[":
                self.fail(f"histórico de variável local ainda não suportado: {name}.")
            return self.variable(name)[0]
        if name in self.routines or name in FUNCTIONS or name in ROLLING:
            call = self.call(name)
            offset = self.index()
            if offset is None:
                return call
            if name not in PURE_FUNCTIONS | ROLLING:
                self.fail(f"histórico não suportado para {name}.")
            return f"ctx.shift_call({offset},lambda:{call})"
        if name in SERIES or name in STATE:
            if self.take("("):
                self.expect(")")
        offset = self.index()
        if name in self.symbols:
            symbol = self.symbols[name]
            if symbol.kind == "input":
                self.used_inputs.add(name)
            if symbol.kind == "array":
                if offset is None:
                    self.fail(f"array requer índice: {name}.")
                return f"ctx.read_array({symbol.slot},{offset})"
            return f"ctx.read({symbol.slot})" if offset is None else f"ctx.lag({symbol.slot},{offset})"
        if name in SERIES:
            self.used.add(name)
            return f"ctx.series({name!r},{offset or 0})"
        if name in STATE and offset is None:
            return f"ctx.state({name!r})"
        if offset is None and name in (COLORS.keys() | ORDER_CONSTANTS.keys()):
            return repr((COLORS | ORDER_CONSTANTS)[name])
        self.fail(f"recurso ou identificador não suportado: {name}.")

    def call(self, name):
        args = []
        if self.take("("):
            if self.peek() != ")":
                args.append(self.expression())
                while self.take(","):
                    args.append(self.expression())
            self.expect(")")
        if name in self.routines:
            identifier, count = self.routines[name]
            if len(args) != count:
                self.fail(f"{name} exige {count} argumentos.")
            return f"{identifier}(ctx{',' if args else ''}{','.join(args)})"
        self.used.add(name)
        if name == "avgtruerange":
            if len(args) != 2:
                self.fail("avgtruerange exige 2 argumentos.")
            self.rolling += 1
            return f"ctx.atr({self.rolling},{args[0]},{args[1]})"
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
    used_inputs: set


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
        if kind == "wilder":
            self.value = value if len(self.window) == 1 else self.value + (value-self.value)/self.window.maxlen
        elif kind == "weighted":
            weights = range(1,len(self.window)+1)
            self.value = sum(w*v for w,v in zip(weights,self.window))/sum(weights)
        elif kind == "media":
            self.value = self.sum / len(self.window)
        elif kind == "mediaexp":
            self.value = self.ema
        elif kind == "summation":
            self.value = self.sum
        else:
            self.value = (max if kind == "highest" else min)(self.window)
        return self.value
