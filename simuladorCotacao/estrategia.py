"""Replay local de estratégias NTSL por candle."""
import argparse
import csv
from dataclasses import dataclass
import hashlib
import html
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from diagnostico import chart
from ntsl import ORDER_CONSTANTS, NTSLError, Rolling, SERIES, compile_ntsl
from simulador import OHLC, read_export, read_ticks, validate_ohlc


def source_text(path):
    data = Path(path).read_bytes()
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252")


FORMATS = {
    "profit": ("Indicador exportado do Profit", {"data_minuto_origem", "v_barra_id", *OHLC}),
    "ohlc": ("Candles OHLC com timestamp", {"timestamp", *OHLC}),
    "negocios": ("Negócios com timestamp", {"timestamp", "preco"}),
}


def csv_format(path, requested="auto"):
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        columns = set(next(csv.reader(stream, delimiter=";"), []))
    detected = next((key for key, (_, required) in FORMATS.items() if required <= columns), None)
    if requested == "auto":
        if detected:
            return detected
        raise ValueError("Formato do CSV não reconhecido. Confira os nomes das colunas e o separador ponto e vírgula.")
    if requested not in FORMATS:
        raise ValueError(f"Formato desconhecido: {requested}.")
    label, required = FORMATS[requested]
    if required <= columns:
        return requested
    if detected:
        raise ValueError(f'O CSV corresponde a “{FORMATS[detected][0]}”. Selecione esse formato ou “Detectar automaticamente”.')
    missing = ", ".join(sorted(required - columns))
    raise ValueError(f'Colunas ausentes no formato “{label}”: {missing}. Confira o separador ponto e vírgula.')


def load_bars(path, seconds, format_name):
    if format_name == "profit":
        frame = read_export(path, seconds)
        stamp = frame["minuto"]
    elif format_name == "negocios":
        frame = read_ticks(path, seconds)
        stamp = frame["inicio"]
        frame["v_trades_atual"] = frame["negocios"]
    elif format_name == "ohlc":
        frame = pd.read_csv(path, sep=";", decimal=",", encoding="utf-8-sig")
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], format="ISO8601")
        if frame["timestamp"].isna().any() or frame["timestamp"].duplicated().any():
            raise ValueError("Cada candle OHLC precisa ter um timestamp válido e único.")
        frame = frame.sort_values("timestamp").reset_index(drop=True)
        stamp = frame["timestamp"]
    else:
        raise ValueError(f"Formato desconhecido: {format_name}.")
    if seconds < 1:
        raise ValueError("O intervalo precisa ser positivo.")
    validate_ohlc(frame)
    for column in OHLC:
        frame[column] = pd.to_numeric(frame[column])
    frame["pregao"] = stamp.dt.strftime("%Y-%m-%d")
    frame["data_ntsl"] = (stamp.dt.year-1900)*10000 + stamp.dt.month*100 + stamp.dt.day
    frame["hora_ntsl"] = stamp.dt.hour*100 + stamp.dt.minute
    frame["barra_ntsl"] = np.arange(1,len(frame)+1)
    return frame


@dataclass
class Order:
    function: str
    action: str
    kind: str
    quantity: int
    price: float = 0
    limit: float | None = None
    triggered: bool = False


class Engine:
    def __init__(self, program, frame, tick, overrides, seconds, point_value):
        self.program, self.frame, self.tick = program, frame, float(tick)
        if not math.isfinite(self.tick) or self.tick <= 0:
            raise ValueError("O tick precisa ser positivo.")
        self.point_value = float(point_value)
        if not math.isfinite(self.point_value) or self.point_value <= 0:
            raise ValueError("O valor por ponto precisa ser positivo.")
        self.values = program.defaults.copy()
        self.arrays = {symbol.slot: [0.0]*(program.defaults[symbol.slot][1]-program.defaults[symbol.slot][0]+1)
                       for symbol in program.symbols.values() if symbol.kind == "array"}
        self.loop_budget = 0
        self.series_data = {}
        required = {name: SERIES[name] for name in program.used & SERIES.keys()}
        for name, column in (("totalbuyqtd","v_qtd_compra_book"),
                             ("totalsellqtd","v_qtd_venda_book")):
            if name in program.used:
                required[name] = column
        required.update({key: SERIES[key] for key in ("open","high","low","close")})
        for name, column in required.items():
            if column not in frame:
                raise ValueError(f"{name} precisa da coluna {column} no CSV.")
            values = pd.to_numeric(frame[column], errors="raise").to_numpy(dtype=float)
            if not np.isfinite(values).all():
                raise ValueError(f"A coluna {column} contém dados ausentes ou inválidos.")
            self.series_data[name] = values
        for name, value in overrides.items():
            name = name.lower()
            if name not in program.inputs:
                raise ValueError(f"Input NTSL desconhecido: {name}.")
            if not isinstance(value,(int,float,bool,str)) or (not isinstance(value,str) and not math.isfinite(value)):
                raise ValueError(f"O input {name} requer texto, número finito ou booleano.")
            self.values[program.symbols[name].slot] = value
        self.ignored_asset = any(symbol.kind == "asset" for symbol in program.symbols.values())
        self.seconds = seconds
        self.history = np.empty((len(frame),len(self.values)), dtype=float)
        self.variable_slots = [s.slot for s in program.symbols.values()
                               if s.kind in {"float","real","boolean","integer"}]
        self.row = self.cursor = self.session_start = 0
        self.position = 0
        self.basis = self.daily = self.realized = 0.0
        self.orders = {}
        self.fills = []
        self.logs = []
        self.plots = {}
        self.trace = []
        self.rolling = {}
        self.ambiguities = 0
        self.entry_intentions = set()

    def series(self, name, offset=0):
        index = self.cursor - self.integer(offset,0)
        return float(self.series_data[name][index]) if index >= self.session_start else 0.0

    def read(self, slot):
        if self.cursor == self.row or isinstance(self.values[slot], (tuple,str)):
            return self.values[slot]
        return self.history[self.cursor,slot]

    def lag(self, slot, offset):
        index = self.cursor - self.integer(offset,0)
        if index < self.session_start:
            return self.program.defaults[slot]
        return self.read(slot) if index == self.cursor else float(self.history[index,slot])

    @staticmethod
    def integer(value, lower):
        if not isinstance(value,(int,float,np.number)) or not np.isfinite(value) or int(value) != value or value < lower:
            raise NTSLError(f"esperado inteiro >= {lower}, recebido {value}.")
        return int(value)

    @staticmethod
    def cast(kind, value):
        if kind == "boolean":
            return bool(value)
        return int(value) if kind == "integer" else float(value)

    def loop_step(self):
        self.loop_budget -= 1
        if self.loop_budget < 0:
            raise NTSLError("limite de 100.000 iterações por candle atingido.")

    def iterate(self, start, end, step):
        start, end = self.integer(start, -10**12), self.integer(end, -10**12)
        for value in range(start, end+step, step):
            self.loop_step()
            yield value

    def array_index(self, slot, index):
        lower, upper, _ = self.program.defaults[slot]
        index = self.integer(index, lower)
        if index > upper:
            raise NTSLError(f"índice {index} fora do array [{lower}..{upper}].")
        return index-lower

    def read_array(self, slot, index):
        return self.arrays[slot][self.array_index(slot,index)]

    def write_array(self, slot, index, value):
        self.arrays[slot][self.array_index(slot,index)] = self.cast(self.program.defaults[slot][2], value)

    @staticmethod
    def add(a,b):
        return str(a)+str(b) if isinstance(a,str) or isinstance(b,str) else a+b

    @staticmethod
    def divide(a,b):
        if not b:
            raise NTSLError("divisão por zero.")
        return a/b

    def average(self, key, kind, count, value):
        period = self.integer(count,1)
        if period > 100_000:
            raise NTSLError("janela máxima de 100.000 barras.")
        saved_row = self.cursor
        state = self.rolling.get(key)
        if state is None or state.window.maxlen != period or state.row > saved_row:
            state = self.rolling[key] = Rolling(period)
        if saved_row == state.row:
            return state.value
        first = max(self.session_start,state.row+1)
        if kind != "mediaexp":
            first = max(first,saved_row-period+1)
        try:
            for index in range(first,saved_row+1):
                self.cursor = index
                state.update(index,float(value()),kind)
        finally:
            self.cursor = saved_row
        return state.value

    def shift_call(self, offset, callback):
        index = self.cursor-self.integer(offset,0)
        if index < self.session_start:
            return 0.0
        original = self.cursor
        self.cursor = index
        try:
            return callback()
        finally:
            self.cursor = original

    def atr(self, key, period, kind):
        kind = self.integer(kind,0)
        kinds = ("media", "mediaexp", "wilder", "weighted")
        if kind >= len(kinds):
            raise NTSLError("AvgTrueRange aceita tipo de média entre 0 e 3.")
        return self.average(key,kinds[kind],period,lambda: self.call("truerange"))

    def state(self, name):
        return {
            "isbought": self.position>0, "issold": self.position<0,
            "hasposition": self.position!=0, "haspendingorders": bool(self.orders),
            "buyprice": self.basis if self.position>0 else 0,
            "sellprice": self.basis if self.position<0 else 0,
            "price": self.basis, "position": self.position,
            "buyposition": max(0,self.position), "sellposition": max(0,-self.position),
            "minpriceincrement": self.tick, "positionqty": self.position,
            "buypositionqty": max(0,self.position), "sellpositionqty": max(0,-self.position),
        }[name]

    def call(self, name, *args):
        math_calls = {"abs": abs, "max": max, "min": min, "sqrt": math.sqrt, "round": round,
                      "floor": math.floor, "ceiling": math.ceil, "power": pow,
                      "mod": lambda x,y: int(math.fmod(int(x),int(y))),
                      "intportion": math.trunc, "fracportion": lambda x: math.modf(x)[0],
                      "square": lambda x: x*x, "sign": lambda x: int(x>0)-int(x<0),
                      "log": math.log, "exp": math.exp}
        if name in math_calls:
            return math_calls[name](*args)
        if name == "truerangecustom":
            high, low, previous = args
            return max(high,previous)-min(low,previous)
        if name in {"truerange", "truehigh", "truelow", "typicalprice", "medianprice", "avgprice"}:
            high, low = self.series("high"), self.series("low")
            if name == "medianprice":
                return (high+low)/2
            if name == "typicalprice":
                return (high+low+self.series("close"))/3
            if name == "avgprice":
                return (high+low+self.series("open")+self.series("close"))/4
            prev = self.series("close",1) if self.cursor>self.session_start else self.series("open")
            upper, lower = max(high,prev), min(low,prev)
            return upper if name=="truehigh" else lower if name=="truelow" else upper-lower
        if name == "dailyresult":
            unrealized = (self.series("close")-self.basis)*self.position if args and args[0] else 0
            return (self.daily + unrealized) * self.point_value
        if name in {"totalbuyqtd","totalsellqtd"}:
            return self.series(name)
        if name == "sendorder":
            side, kind, qty, limit, stop = args
            side_map = {ORDER_CONSTANTS["osbuy"]: "net_long", ORDER_CONSTANTS["ossell"]: "net_short"}
            type_map = {ORDER_CONSTANTS["otmarket"]: "market", ORDER_CONSTANTS["otlimit"]: "limit",
                        ORDER_CONSTANTS["otstoplimit"]: "stop"}
            if side not in side_map or kind not in type_map:
                raise NTSLError("SendOrder exige osBuy/osSell e otMarket/otLimit/otStopLimit.")
            kind = type_map[kind]
            price = float(stop if kind == "stop" else limit)
            limit = float(limit) if kind == "stop" else None
            if kind != "market" and (not math.isfinite(price) or price <= 0):
                raise NTSLError("preço inválido em SendOrder.")
            if kind == "stop" and (not math.isfinite(limit) or limit <= 0 or
                                  (limit < price if side_map[side] == "net_long" else limit > price)):
                raise NTSLError("limite inválido em SendOrder stop-limit.")
            quantity = self.integer(qty,1)
            key = f"sendorder_{side}_{kind}"
            self.orders[key] = Order(name, side_map[side], kind, quantity, price, limit)
            if side_map[side] == "net_long" and quantity > -self.position:
                self.entry_intentions.add("long")
            if side_map[side] == "net_short" and quantity > self.position:
                self.entry_intentions.add("short")
        elif name == "reverseposition":
            if self.position:
                self.orders.clear()
                action = "net_short" if self.position>0 else "net_long"
                self.orders[name] = Order(name,action,"market",2*abs(self.position))
                self.entry_intentions.add("short" if self.position>0 else "long")
        elif name == "cancelpendingorders":
            self.orders.clear()
        elif name == "consolelog":
            if len(self.logs) < 10_000:
                self.logs.append((self.row+1,str(args[0])))
        elif name.startswith("plot") or name == "paintbar":
            self.plots[name] = float(args[0])
        else:
            self.queue(name,args)
        return 0

    def queue(self,name,args):
        if name == "closeposition":
            if not self.position:
                return
            action = "exit_long" if self.position>0 else "exit_short"
            self.orders.clear()
            self.orders[name] = Order(name,action,"market",abs(self.position))
            return
        prefix = next(prefix for prefix in ("selltocover","buytocover","sellshort","buyat")
                      if name.startswith(prefix))
        action = {"selltocover":"exit_long","buytocover":"exit_short",
                  "sellshort":"short","buyat":"long"}[prefix]
        kind = next(kind for kind in ("market","limit","stop") if name.endswith(kind))
        exit_order = action.startswith("exit")
        if (action == "exit_long" and self.position<=0) or (action == "exit_short" and self.position>=0):
            return
        # Entradas do lado oposto exigem zerar antes, como nas funções *ToCover.
        if (action == "long" and self.position<0) or (action == "short" and self.position>0):
            return
        quantity = abs(self.position) if exit_order else 1
        price,limit = 0,None
        if kind == "market":
            if args:
                quantity = self.integer(args[0],1)
        else:
            price = float(args[0])
            if kind == "stop":
                limit = float(args[1]) if len(args)>1 else None
                if limit == 0:
                    limit = None
                if len(args)>2:
                    quantity = self.integer(args[2],1)
                buying = action in {"long","exit_short"}
                if limit is not None and ((buying and limit<price) or (not buying and limit>price)):
                    raise NTSLError("preço limite do stop no lado incorreto do gatilho.")
            elif len(args)>1:
                quantity = self.integer(args[1],1)
            if not math.isfinite(price) or price <= 0 or (limit is not None and
                                                         (not math.isfinite(limit) or limit<=0)):
                raise NTSLError("preço inválido na ordem.")
        order = Order(name,action,kind,quantity,price,limit)
        old = self.orders.get(name)
        if old and old.triggered and (old.price,old.limit,old.quantity)==(price,limit,quantity):
            order.triggered = True
        self.orders[name] = order
        if not exit_order:
            self.entry_intentions.add(action)

    @staticmethod
    def match(order,o,h,l):
        buying = order.action in {"long","exit_short","net_long"}
        price = order.price
        if order.kind == "market":
            return o
        if order.kind == "stop" and not order.triggered:
            touched = h>=price if buying else l<=price
            if not touched:
                return None
            order.triggered = True
            fill = max(o,price) if buying else min(o,price)
            limit = order.limit
            if limit is None or (fill<=limit if buying else fill>=limit):
                return fill
            # A volta até o limite na mesma barra é indeterminada após gap.
            return None
        limit = order.limit if order.kind == "stop" else price
        if limit is None:
            return o
        if buying and l<=limit:
            return min(o,limit)
        if not buying and h>=limit:
            return max(o,limit)
        return None

    def execute(self, order, price):
        action, quantity = order.action, order.quantity
        old = self.position
        if action in {"net_long", "net_short"}:
            direction = 1 if action == "net_long" else -1
            if old*direction < 0:
                closed = min(quantity,abs(old))
                self.execute(Order(order.function,"exit_short" if direction>0 else "exit_long",
                                   order.kind,closed),price)
                quantity -= closed
            if quantity:
                self.execute(Order(order.function,"long" if direction>0 else "short",order.kind,quantity),price)
            return
        pnl = 0.0
        if action in {"long","short"}:
            direction = 1 if action=="long" else -1
            if old*direction<0:
                return
            self.basis = (self.basis*abs(old)+price*quantity)/(abs(old)+quantity)
            self.position += direction*quantity
        else:
            direction = 1 if action=="exit_long" else -1
            if old*direction<=0:
                return
            quantity = min(quantity,abs(old))
            pnl = (price-self.basis)*quantity*direction
            self.position -= direction*quantity
            self.daily += pnl
            self.realized += pnl
            self.orders = {key:item for key,item in self.orders.items()
                           if not item.action.startswith("exit")}
            if not self.position:
                self.basis = 0.0
        self.fills.append(dict(barra=self.row+1,pregao=self.frame["pregao"].iat[self.row],
                               ordem=order.function,acao=action,preco=price,quantidade=quantity,
                               pontos_contrato=pnl,posicao=self.position, tipo=order.kind))

    def process_orders(self):
        o,h,l = (self.series(name) for name in ("open","high","low"))
        matched = []
        for key,order in self.orders.items():
            fill = self.match(order,o,h,l)
            if fill is not None:
                matched.append((key,order,fill))
        exits = [item for item in matched if item[1].action.startswith("exit")]
        if exits:
            if len(exits)>1:
                self.ambiguities += 1
            chosen = min(exits,key=lambda item: (item[1].kind!="market",
                                                item[2] if self.position>0 else -item[2]))
            self.orders.pop(chosen[0],None)
            self.execute(chosen[1],chosen[2])
        else:
            # Quando duas entradas opostas são tocadas, a primeira ordem enviada prevalece.
            if len({item[1].action for item in matched})>1:
                self.ambiguities += 1
            for key,order,fill in matched:
                self.orders.pop(key,None)
                self.execute(order,fill)

    def run(self, record_trace=True):
        days = self.frame["pregao"].to_numpy()
        var_slots = self.variable_slots
        var_set = set(var_slots)
        constants = [(idx,val) for idx,val in enumerate(self.values) if idx not in var_set]
        numeric_constants = [(idx,0.0 if isinstance(val,(tuple,str)) else val) for idx,val in constants]
        for row in range(len(self.frame)):
            self.row = self.cursor = row
            if row==0 or days[row]!=days[row-1]:
                self.session_start = row
                self.daily = 0.0
                self.rolling.clear()
            self.process_orders()
            self.plots = {}
            self.entry_intentions = set()
            self.loop_budget = 100_000
            try:
                self.program.strategy(self)
            except (ValueError,TypeError,OverflowError,ZeroDivisionError,RecursionError) as error:
                raise NTSLError(f"Barra {row+1}, pregão {days[row]}: {error}") from error
            for slot in var_slots:
                self.history[row,slot] = self.values[slot]
            for slot,val in numeric_constants:
                self.history[row,slot] = val
            if row+1==len(days) or days[row+1]!=days[row]:
                self.orders.clear()
                if self.position:
                    action = "exit_long" if self.position>0 else "exit_short"
                    self.execute(Order("fim_pregao",action,"market",abs(self.position)),self.series("close"))
            if record_trace:
                self.trace.append({"sinal_compra": "long" in self.entry_intentions,
                               "sinal_venda": "short" in self.entry_intentions,
                               "posicao":self.position,"pontos_contrato_acumulados":self.realized,**self.plots})


def run_strategy(csv, source, output, seconds, format_name, tick, overrides=None, point_value=1):
    program = compile_ntsl(source)
    format_name = csv_format(csv, format_name)
    frame = load_bars(csv,seconds,format_name)
    engine = Engine(program,frame,tick,overrides or {},seconds,point_value)
    engine.run()
    output = Path(output)
    output.mkdir(parents=True,exist_ok=False)
    fills = pd.DataFrame(engine.fills,columns=[
        "barra","pregao","ordem","acao","preco","quantidade","pontos_contrato","posicao"])
    fills.to_csv(output/"execucoes.csv",index=False)
    columns = [key for key in ("timestamp","inicio","minuto","ordem_no_minuto","v_barra_id",
                               "pregao",*OHLC,"classe") if key in frame]
    trace = pd.concat([frame[columns],pd.DataFrame(engine.trace)],axis=1)
    trace.to_csv(output/"candles.csv",index_label="indice")
    pd.DataFrame(engine.logs,columns=["barra","mensagem"]).to_csv(output/"console.csv",index=False)
    exits = fills[fills.acao.str.startswith("exit")] if len(fills) else fills
    pnl = exits["pontos_contrato"].to_numpy(dtype=float)
    equity = np.r_[0,pnl.cumsum()]
    summary = dict(versao=Path(__file__).with_name("VERSION").read_text().strip(),
                   estrategia_sha256=hashlib.sha256(source.encode()).hexdigest(),
                   barras=len(frame),pregoes=int(frame["pregao"].nunique()),
                   sinais_compra=int(trace.sinal_compra.sum()),sinais_venda=int(trace.sinal_venda.sum()),
                   preenchimentos=len(fills),saidas=len(exits),saidas_positivas=int((pnl>0).sum()),
                   saidas_negativas=int((pnl<0).sum()),pontos_contrato=engine.realized,
                   drawdown_pontos_contrato=float((np.maximum.accumulate(equity)-equity).max()),
                   barras_ambiguas=engine.ambiguities,formato_csv=FORMATS[format_name][0],
                   intervalo_segundos=seconds,tick=tick,
                   valor_por_ponto=point_value,resultado_bruto_convertido=engine.realized*point_value,
                   inputs=program.inputs|{k.lower():v for k,v in (overrides or {}).items()},
                   usa_asset_snapshot=engine.ignored_asset)
    (output/"metricas.json").write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding="utf-8")
    (output/"estrategia.ntsl").write_text(source,encoding="utf-8")
    table = "".join(f"<tr><th>{html.escape(k.replace('_',' '))}</th><td>{html.escape(str(v))}</td></tr>"
                    for k,v in summary.items() if k!="inputs")
    sample = sorted(set(np.linspace(0, len(equity)-1, min(len(equity), 350), dtype=int)))
    payoff = [{"geracao": int(i), "resultado": float(equity[i])} for i in sample]
    performance = chart(payoff, [("resultado", "Pontos × contratos")], "Resultado realizado", axis="Saída")
    items = '<a href="execucoes.csv">Execuções</a> · <a href="candles.csv">Candles e sinais</a> · <a href="console.csv">Console</a> · <a href="metricas.json">Métricas e inputs</a>'
    (output/"relatorio.html").write_text(f"""<!doctype html><html lang="pt-BR"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Replay NTSL</title>
<style>
body{{font:16px system-ui;max-width:850px;margin:3rem auto;padding:0 1.1rem;background:#f2f7f6;color:#172e2b}}
h1{{font-size:2.3rem}}table{{border-collapse:collapse;width:100%;background:white}}
th,td{{text-align:left;padding:.6rem 1rem;border-bottom:1px solid #d9e4e1}}a{{color:#146253}}
figure{{margin:1rem 0;background:white;padding:1rem}} svg{{width:100%;max-height:245px;font-size:11px}}
</style><h1>Replay NTSL</h1><p>{items}</p>
<p>O código roda no fechamento de cada candle. Ordens novas só são elegíveis na barra seguinte.
O resultado é bruto em pontos × contratos. Barras ambíguas podem alterar os preenchimentos.</p>
{performance}<table>{table}</table></html>""",encoding="utf-8")
    return summary


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--csv",required=True)
    p.add_argument("--ntsl",required=True)
    p.add_argument("--saida",required=True)
    p.add_argument("--segundos",type=int,required=True)
    p.add_argument("--formato",choices=["auto", "profit", "negocios", "ohlc"],default="auto")
    p.add_argument("--tick",type=float,default=5)
    p.add_argument("--valor-ponto",type=float,default=1,help="Multiplicador de DailyResult e do resultado bruto")
    p.add_argument("--inputs",help="Arquivo JSON com valores de inputs a substituir")
    args=p.parse_args()
    try:
        overrides=json.loads(Path(args.inputs).read_text(encoding="utf-8-sig")) if args.inputs else {}
        print(json.dumps(run_strategy(args.csv,source_text(args.ntsl),args.saida,args.segundos,
                                      args.formato,args.tick,overrides,args.valor_ponto),ensure_ascii=False,indent=2))
    except (ValueError,OSError,KeyError) as error:
        p.exit(2,f"Erro: {error}\n")


class StrategyReplay:
    """Executa o NTSL com cada conjunto de inputs do otimizador."""
    def __init__(self, frame, program, seconds, target, specification, excluded, tick, point_value):
        from diagnostico import BLOCKED, labels

        self.frame, self.program, self.seconds = frame, program, seconds
        self.target, self.specification = target, specification or {}
        self.excluded = set(excluded) | BLOCKED
        inputs = {SERIES[name] for name in program.used & SERIES.keys()}
        if program.used & {"truerange","truehigh","truelow","typicalprice","medianprice","avgprice","avgtruerange"}:
            inputs |= set(OHLC)
        if "dailyresult" in program.used:
            inputs.add("fechamento")
        inputs |= {column for name, column in (("totalbuyqtd", "v_qtd_compra_book"),
                                               ("totalsellqtd", "v_qtd_venda_book")) if name in program.used}
        conflicts = inputs & self.excluded
        if conflicts:
            raise ValueError("O NTSL lê campos excluídos: " + ", ".join(sorted(conflicts))
                             + ". Altere o código ou a seleção para executar a estratégia.")
        self.tick, self.point_value = tick, point_value
        self.day = frame["pregao"].to_numpy()
        self.defaults = program.inputs
        if self.specification.get("modo") == "resultado":
            self.label, self.valid_label = np.zeros(len(frame), bool), np.ones(len(frame), bool)
        else:
            self.label, self.valid_label = labels(frame, target, self.specification)

    def subset(self, mask):
        return StrategyReplay(self.frame.loc[mask].reset_index(drop=True), self.program, self.seconds,
                              self.target, self.specification, self.excluded, self.tick, self.point_value)

    def score(self, parameters):
        engine = Engine(self.program, self.frame, self.tick, parameters, self.seconds, self.point_value)
        engine.run(record_trace=False)
        scores = np.zeros((len(self.frame), 4))
        for fill in engine.fills:
            row = scores[fill["barra"]-1]
            action = fill["acao"]
            if action in {"long", "short"}:
                if self.specification.get("modo") == "resultado" or fill["tipo"] == "market":
                    row[0 if action == "long" else 1] = 1
            else:
                row[2] += fill["pontos_contrato"]
                row[3] += 1
        return scores


def strategy_replay(path, source, seconds, format_name, config, tick, point_value):
    format_name = csv_format(path, format_name)
    frame = load_bars(path, seconds, format_name)
    if "segmento" not in frame:
        stamp = frame["inicio" if format_name == "negocios" else "timestamp"]
        boundary = frame["pregao"].ne(frame["pregao"].shift()) | stamp.diff().ne(pd.Timedelta(seconds=seconds))
        frame["segmento"] = boundary.cumsum()
    specification = config.get("alvo", {})
    if config["genetico"].get("metrica") in {"resultado", "resultado_menos_drawdown"}:
        specification = specification | {"modo": "resultado"}
    return StrategyReplay(frame, compile_ntsl(source), seconds, config.get("classe_alvo", "1C"),
                          specification, config.get("campos_excluidos", ()), tick, point_value)


if __name__=="__main__":
    main()
