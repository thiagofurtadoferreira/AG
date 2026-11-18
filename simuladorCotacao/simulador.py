"""Reconstrução OHLC e otimização cronológica do classificador NTSL."""
import argparse
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from decimal import Decimal
import html
from itertools import product
import json
import math
import os
from pathlib import Path
import random
import re
import time

import numpy as np
import pandas as pd

from diagnostico import BLOCKED, charts, dependencies, labels as make_labels, tree_features

OHLC = ['abertura', 'maxima', 'minima', 'fechamento']
NUM = r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?'
GENES = {
    'p_PeriodoMedia', 'p_PeriodoVolatilidade', 'p_PeriodoATR', 'p_PeriodoEficiencia',
    'p_PeriodoMediaTrades', 'p_BarrasAquecimento', 'p_CorteScoreModelo', 'p_SegundosPorBarra',
}
CHEAP = {'p_BarrasAquecimento', 'p_CorteScoreModelo'}


def read_export(path, seconds):
    if seconds < 1 or 60 % seconds:
        raise ValueError('Para CSV por minuto, segundos deve ser divisor positivo de 60.')
    frame = pd.read_csv(path, sep=';', decimal=',', low_memory=False, dtype={'classe': 'string'})
    frame = frame.dropna(how='all').copy()
    frame['minuto'] = pd.to_datetime(frame['data_minuto_origem'], format='%d/%m/%Y %H:%M')
    if frame[['minuto', 'v_barra_id']].isna().any().any():
        raise ValueError('CSV com minuto ou identificador ausente.')
    keys = ['minuto', 'v_barra_id']
    frame = frame.drop_duplicates()
    if frame.duplicated(keys).any():
        raise ValueError('Barras conflitantes com o mesmo minuto e identificador.')
    frame = frame.sort_values(keys).reset_index(drop=True)
    minute = frame['minuto']
    grouped = frame.groupby('minuto', sort=False)
    frame['ordem_no_minuto'] = grouped.cumcount() + 1
    size = grouped['v_barra_id'].transform('size')
    capacity = 60 // seconds
    if (size > capacity).any():
        raise ValueError(f'As barras por minuto excedem a capacidade para {seconds}s.')
    new_minute = minute.ne(minute.shift())
    adjacent = minute.diff().eq(pd.Timedelta(minutes=1))
    sequential = frame['v_barra_id'].diff().eq(1)
    same_day = minute.dt.normalize().eq(minute.shift().dt.normalize())
    complete_boundary = adjacent & same_day & size.eq(capacity) & size.shift().eq(capacity)
    boundary = np.where(new_minute, ~complete_boundary, ~sequential)
    frame['segmento'] = np.cumsum(boundary)
    frame['pregao'] = minute.dt.strftime('%Y-%m-%d')
    return frame


def read_ticks(path, seconds):
    if seconds < 1:
        raise ValueError('Intervalo deve ser positivo.')
    frame = pd.read_csv(path, sep=';', decimal=',')
    frame['timestamp'] = pd.to_datetime(frame['timestamp'], format='ISO8601')
    frame['preco'] = pd.to_numeric(frame['preco'])
    if frame['timestamp'].isna().any() or not np.isfinite(frame['preco']).all():
        raise ValueError('Hora ou preço inválido em negócios.')
    columns = ['timestamp'] + (['sequencia'] if 'sequencia' in frame else [])
    frame = frame.sort_values(columns, kind='stable')
    frame['inicio'] = frame['timestamp'].dt.floor(f'{seconds}s')
    if 'quantidade' in frame:
        frame['quantidade'] = pd.to_numeric(frame['quantidade'])
        if not np.isfinite(frame['quantidade']).all() or (frame['quantidade'] < 0).any():
            raise ValueError('Quantidade inválida em negócios.')
    specs = dict(abertura=('preco', 'first'), maxima=('preco', 'max'),
                 minima=('preco', 'min'), fechamento=('preco', 'last'),
                 negocios=('preco', 'size'))
    if 'quantidade' in frame:
        specs['volume_contratos'] = ('quantidade', 'sum')
    return frame.groupby('inicio', sort=True).agg(**specs).reset_index()


class NTSLModel:
    """Lê a gramática restrita dos blocos de árvores exportados no modelo."""
    def __init__(self, path):
        self.source = Path(path).read_text(encoding='utf-8-sig')
        inputs = re.search(r'\binput\s+(.*?)\bvar\s+', self.source, re.S | re.I)[1]
        inputs = re.sub(r'\{.*?\}', '', inputs, flags=re.S)
        self.defaults = {name: float(value) for name, value in re.findall(
            rf'(p_\w+)\s*\(\s*({NUM})\s*\)\s*;', inputs)}
        self.bias = float(re.search(rf'v_ScoreModelo\s*:=\s*({NUM})\s*;', self.source)[1])
        body = self.source.split('v_ScoreModelo :=', 1)[1]
        blocks = re.split(r'\{\s*Arvore\s+\d+\s+de\s+(\d+)\.\s*\}', body)
        if len(blocks) < 3 or len(blocks[2::2]) != int(blocks[1]):
            raise ValueError('Formato de árvores NTSL não reconhecido.')
        tree_blocks = blocks[2::2]
        tree_blocks[-1] = re.split(r'\bv_SinalCompraModelo\s*:=', tree_blocks[-1], maxsplit=1)[0]
        self.features = set()
        self.trees = []
        for index, block in enumerate(tree_blocks):
            parser = TreeParser(block, self.features)
            tree = parser.node()
            remainder = parser.text[parser.pos:].strip()
            if remainder not in ('', ';') and not (index == len(tree_blocks)-1 and remainder == 'end;'):
                raise ValueError(f'Trecho NTSL não reconhecido após árvore {index + 1}: {remainder[:80]}')
            self.trees.append(tree)

    def patched(self, params):
        start = re.search(r'\binput\s+', self.source, re.I).end()
        end = re.search(r'\bvar\s+', self.source[start:], re.I).start() + start
        pattern = re.compile(rf'(p_\w+)(\s*\(\s*)({NUM})(\s*\)\s*;)')
        def replace(match):
            name, opening, value, closing = match.groups()
            return name + opening + (str(params[name]) if name in params else value) + closing
        return self.source[:start] + pattern.sub(replace, self.source[start:end]) + self.source[end:]


class TreeParser:
    def __init__(self, text, features):
        self.text, self.features, self.pos = text, features, 0

    def take(self, pattern):
        match = re.compile(r'\s*' + pattern).match(self.text, self.pos)
        if match:
            self.pos = match.end()
        return match

    def require(self, pattern):
        match = self.take(pattern)
        if match is None:
            raise ValueError(f'Bloco de árvore incompatível: {self.text[self.pos:self.pos + 100]}')
        return match

    def node(self):
        leaf = self.take(rf'v_ScoreModelo\s*:=\s*v_ScoreModelo\s*\+\s*\(({NUM})\)\s*;')
        if leaf:
            return float(leaf[1])
        split = self.require(rf'if\s+(v_\w+)(?:\[(\d+)\])?\s*(<=|=)\s*({NUM})\s+then\s+begin\b')
        key = split[1], int(split[2] or 0)
        if key[1] == 0 and key[0] != 'v_GapAbertura':
            raise ValueError(f'Variável da barra atual indisponível na abertura: {key[0]}')
        self.features.add(key)
        left = self.node()
        self.require(r'end\s+else\b')
        wrapped = self.take(r'begin\b')
        right = self.node()
        if wrapped:
            self.require(r'end\b;?')
        return key, split[3], float(split[4]), left, right


def divide(top, bottom, default=0):
    result = top.div(bottom.where(bottom != 0))
    return result.mask(bottom == 0, default)


class Replay:
    def __init__(self, frame, model, seconds, target, specification=None, excluded=()):
        self.frame, self.model, self.seconds = frame, model, seconds
        self.segment = frame['segmento']
        self.age = frame.groupby('segmento', sort=False).cumcount().to_numpy() + 1
        self.specification = specification or {}
        self.excluded = set(excluded) | BLOCKED
        self.label, self.valid_label = make_labels(frame, target, self.specification)
        impact = {field for field in model.features if dependencies(field[0][2:]) & self.excluded}
        self.trees = [tree for tree in model.trees if not (tree_features(tree) & impact)]
        if not self.trees:
            raise ValueError('Os campos excluídos afetam todas as árvores. Revise a seleção.')
        self.features = set().union(*(tree_features(tree) for tree in self.trees))
        self.day = frame['pregao'].to_numpy()
        self.hhmm = (frame['minuto'].dt.hour * 100 + frame['minuto'].dt.minute).to_numpy()

    def lag(self, s, k=1):
        return s.groupby(self.segment, sort=False).shift(k)

    def sma(self, s, n):
        return (s.groupby(self.segment, sort=False).rolling(int(n)).mean()
                .reset_index(level=0, drop=True).reindex(s.index))

    def score(self, params):
        f, lag, sma = self.frame, self.lag, self.sma
        o, h, l, c = (f[k] for k in OHLC)
        trades, buy, sell = (f[k] for k in ('v_trades_atual', 'v_agressao_compra', 'v_agressao_venda'))
        prev = lag(c)
        ret = c - prev
        amplitude = h - l
        delta, total = buy - sell, buy + sell
        media = sma(c, params['p_PeriodoMedia'])
        distancia = c - media
        range_ma = sma(amplitude, params['p_PeriodoVolatilidade'])
        period = int(params['p_PeriodoEficiencia'])
        true_range = np.maximum(amplitude, np.maximum((h - prev).abs(), (l - prev).abs()))
        ratio = divide(buy, sell).mask(sell.eq(0), buy).where(
            buy.ge(sell), -divide(sell, buy).mask(buy.eq(0), sell))
        values = dict(
            ATRRange=sma(true_range, params['p_PeriodoATR']), RangeAtual=amplitude,
            GapAbertura=o-prev, Retorno3=c-lag(c, 3), Retorno5=c-lag(c, 5),
            RetornoFechado=lag(ret), RangeBarraFechada=lag(amplitude),
            PosicaoFechamentoRange=divide(c-l, amplitude, .5),
            InclinacaoMedia=media-lag(media), DistanciaMediaAssinada=distancia,
            DistanciaMediaFechada=lag(distancia.abs()), MediaRangeFechada=lag(range_ma),
            EficienciaDirecional=divide((c-lag(c, period)).abs(), sma(ret.abs(), period)*period),
            Aceleracao=(ret-lag(ret)) / float(params['p_SegundosPorBarra'])**2,
            TradesAtual=trades, TradesFechadaSerie=lag(trades),
            TradesRelativosMedia=divide(trades, sma(trades, params['p_PeriodoMediaTrades'])),
            AgressaoCompra=buy, AgressaoVenda=sell, AgressaoCompraFechada=lag(buy),
            AgressaoVendaFechada=lag(sell), AgressaoTotal=total, DeltaAgressao=delta,
            AgressaoLiquidaPorTrade=divide(delta, trades), AgressaoTotalPorTrade=divide(total, trades),
            ImpactoPrecoPor100Agressao=divide(ret.abs()*100, total), RazaoAgressaoAssinada=ratio,
        )
        raw = {
            'QtdAsk': 'v_qtd_ask', 'QtdBid': 'v_qtd_bid', 'SpreadTicks': 'v_spread_ticks',
            'ImbalanceTopo': 'v_imbalance_topo', 'ReacaoFavoravel': 'v_reacao_favoravel',
            'RecuoAtual': 'v_recuo_atual', 'FlagPressaoSaidaShort': 'v_flag_pressao_saida_short',
        }
        values.update({key: f[col] for key, col in raw.items()})
        aliases = {
            'BidVsMedia': (f['v_bid']-media, True), 'AskVsMedia': (f['v_ask']-media, True),
            'MicroVsBid': (f['v_micropreco']-f['v_bid'], True),
            'RefSetupVsMedia': (f['v_preco_referencia_setup']-media, f['v_preco_referencia_setup'].ne(0)),
        }
        for key, (value, present) in aliases.items():
            valid = value.abs().le(500) & present
            values[key] = value.where(valid, 0)
            values['Flag'+key+'Valido'] = valid.astype(float)
        series = dict(Trades=trades, AbsDelta=delta.abs(), Delta=delta, AbsRet=ret.abs(), Ret=ret,
                      Alta=ret.gt(0).astype(float), Faixa=amplitude.ge(30).astype(float),
                      Classe1C=(amplitude.ge(30) & c.gt(o)).astype(float))
        for name, k in self.features:
            key = name[2:]
            if key not in values:
                base, window = key.split('M', 1) if re.fullmatch(r'\w+M\d+', key) else ('', '')
                if base not in series:
                    raise ValueError(f'Feature NTSL sem implementação: {name}')
                values[key] = sma(series[base], int(window))
        features = {(name, k): (lag(values[name[2:]], k) if k else values[name[2:]]).to_numpy()
                    for name, k in self.features}
        valid = np.logical_and.reduce([np.isfinite(v) for v in features.values()]) if features else np.ones(len(f), dtype=bool)
        result = np.full(len(f), self.model.bias)
        rows = np.flatnonzero(valid)
        for tree in self.trees:
            add_tree(tree, rows, features, result)
        result[~valid] = np.nan
        return result

    def eligible(self, warmup):
        return ((self.age >= warmup) & self.valid_label
                & (self.hhmm >= self.model.defaults['p_HorarioInicio'])
                & (self.hhmm < self.model.defaults['p_HorarioFimEntradas'])
                & (self.hhmm < self.model.defaults['p_HorarioZeragem']))


def add_tree(node, rows, features, score):
    if not rows.size:
        return
    if isinstance(node, float):
        score[rows] += node
        return
    key, op, threshold, left, right = node
    values = features[key][rows]
    go_left = values <= threshold if op == "<=" else values == threshold
    add_tree(left, rows[go_left], features, score)
    add_tree(right, rows[~go_left], features, score)


def metrics(y, prediction):
    tp = int(np.count_nonzero(y & prediction))
    fp = int(np.count_nonzero(~y & prediction))
    fn = int(np.count_nonzero(y & ~prediction))
    tn = len(y) - tp - fp - fn
    def rate(numerator, denominator):
        return numerator / denominator if denominator else 0.0
    return dict(barras=len(y), sinais=tp+fp, positivos=tp+fn, tp=tp, fp=fp, fn=fn, tn=tn,
                precision=rate(tp, tp+fp), recall=rate(tp, tp+fn),
                f1=rate(2*tp, 2*tp+fp+fn),
                balanced_accuracy=(rate(tp, tp+fn)+rate(tn, tn+fp))/2,
                accuracy=rate(tp+tn, len(y)), cobertura=rate(tp+fp, len(y)))


def grid(spec, name):
    lo, hi, step = (Decimal(str(spec[key])) for key in ('min', 'max', 'passo'))
    if not all(x.is_finite() for x in (lo, hi, step)) or step <= 0 or lo > hi:
        raise ValueError(f'Faixa inválida para {name}.')
    integer = name != 'p_CorteScoreModelo'
    if integer and (lo < 1 or any(v != int(v) for v in (lo, hi, step))):
        raise ValueError(f'{name} requer faixa inteira positiva.')
    size = int((hi-lo)//step) + 1
    if size > 100_000:
        raise ValueError(f'Faixa excessiva para {name}.')
    convert = int if integer else float
    return tuple(convert(lo+step*i) for i in range(size))


def cpu_count():
    return len(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else os.cpu_count() or 1


def optimize(replay, config, out, on_progress=None):
    cfg = config['genetico']
    names = tuple(config['parametros'])
    if not names or set(names) - GENES or set(names) - replay.model.defaults.keys():
        raise ValueError('Selecione parâmetros compatíveis: ' + ', '.join(sorted(GENES)))
    defaults = replay.model.defaults
    pools = [grid(config['parametros'][name], name) for name in names]
    total = math.prod(map(len, pools))
    population = min(int(cfg['populacao']), total)
    generations, patience = (int(cfg[key]) for key in ('geracoes', 'paciencia'))
    minimum_signals = int(cfg.get('min_sinais', 1))
    stop_score = float(cfg.get('meta') or 0)
    seconds = float(cfg.get('limite_segundos') or 0)
    mutation = float(cfg.get('mutacao', .25))
    metric = cfg.get('metrica', 'f1')
    if (min(generations, population) < 1 or min(patience, minimum_signals, seconds) < 0
            or not 0 <= mutation <= 1 or not 0 <= stop_score <= 1
            or metric not in {'f1', 'balanced_accuracy', 'precision', 'recall', 'accuracy'}):
        raise ValueError('Configuração genética inválida.')
    days = np.unique(replay.day)
    n_test = int(config['pregoes_teste'])
    if not 1 <= n_test < len(days):
        raise ValueError('Reserve pelo menos um pregão de busca e um de teste.')
    base_mask = replay.eligible(1)
    search = base_mask & (replay.day < days[-n_test])
    test = base_mask & (replay.day >= days[-n_test])
    for mask in (search, test):
        classes = replay.label[mask]
        if not classes.any() or classes.all():
            raise ValueError('Busca e teste precisam conter exemplos positivos e negativos do alvo.')
    splits = {'busca': search, 'teste': test}
    search_rows = replay.day < days[-n_test]
    search_replay = Replay(replay.frame.loc[search_rows].reset_index(drop=True),
                           replay.model, replay.seconds, config.get('classe_alvo', '1C'), replay.specification, replay.excluded)
    local_mask = search[search_rows]
    labels = search_replay.label[local_mask]
    local_age = search_replay.age[local_mask]

    n = len(search_replay.frame)
    budget = int(config['cache_ram_mb']) * 1024**2
    requested = int(config['threads'])
    if budget < 0 or requested < 0:
        raise ValueError('threads e cache_ram_mb precisam ser não negativos.')
    # O orçamento limita o cache, e a RAM disponível limita também os workers.
    available = None
    try:
        import psutil
        available = psutil.virtual_memory().available
    except ImportError:
        pass
    worker_estimate = max(24*1024**2, n*2300)
    if available:
        budget = min(budget, available//4)
    workers = min(requested or cpu_count(), population)
    if available:
        workers = min(workers, max(1, (available//2)//worker_estimate))
    rng = random.Random(cfg['semente'])
    scores = OrderedDict()
    history, seen = [], {}
    clock = time.monotonic()

    def parameters(genome):
        return defaults | dict(zip(names, genome))

    def score_key(genome):
        return tuple(value for name, value in zip(names, genome) if name not in CHEAP)

    def predictions(p, score):
        return ((replay.age >= p['p_BarrasAquecimento'])
                & np.isfinite(score) & (score >= p['p_CorteScoreModelo']))

    def assess(score, genomes):
        local_score = score[local_mask]
        results = {}
        for genome in genomes:
            p = parameters(genome)
            pred = (local_score >= p['p_CorteScoreModelo']) & (local_age >= p['p_BarrasAquecimento'])
            stats = metrics(labels, pred)
            fitness = stats[metric] if stats['sinais'] >= minimum_signals else -1.0
            results[genome] = (fitness, stats)
        return results

    def run_group(genome, members, cache_hit):
        score = cache_hit if cache_hit is not None else search_replay.score(parameters(genome))
        return score, assess(score, members)

    def random_genome():
        return tuple(rng.choice(pool) for pool in pools)

    def populate(seed, parents=()):
        candidates = dict.fromkeys(seed)
        for _ in range(population*20):
            if len(candidates) == population:
                break
            if not parents or rng.random() < .2:
                genome = random_genome()
            else:
                first, second = rng.choices(parents, k=2)
                genome = tuple(rng.choice(pool) if rng.random() < mutation else rng.choice(pair)
                               for pool, pair in zip(pools, zip(first, second)))
            candidates[genome] = None
        if len(candidates) < population:
            for genome in product(*pools):
                candidates[genome] = None
                if len(candidates) == population:
                    break
        return list(candidates)

    original = tuple(min(pool, key=lambda x: abs(x-defaults[name])) for name, pool in zip(names, pools))
    candidates = populate([original])
    best, best_value, unchanged = None, -math.inf, 0
    reason = 'limite de gerações'
    with ThreadPoolExecutor(max_workers=workers) as executor:
        for generation in range(1, generations+1):
            groups = {}
            for genome in candidates:
                if genome not in seen:
                    groups.setdefault(score_key(genome), []).append(genome)
            entries = list(groups.items())
            deadline_hit = False
            for start in range(0, len(entries), workers):
                if seconds and seen and time.monotonic()-clock >= seconds:
                    deadline_hit = True
                    break
                futures = []
                for key, members in entries[start:start+workers]:
                    hit = scores.get(key)
                    if hit is not None:
                        scores.move_to_end(key)
                    futures.append((key, executor.submit(run_group, members[0], members, hit)))
                for key, future in futures:
                    score, results = future.result()
                    seen.update(results)
                    if score.nbytes <= budget:
                        scores[key] = score
                        scores.move_to_end(key)
                        while len(scores)*score.nbytes > budget:
                            scores.popitem(last=False)
            available_candidates = [g for g in candidates if g in seen]
            ranked = sorted(available_candidates, key=lambda g: seen[g][0], reverse=True)
            if not ranked:
                reason = 'limite de tempo'
                break
            winner = ranked[0]
            if seen[winner][0] > best_value:
                best, best_value, unchanged = winner, seen[winner][0], 0
            else:
                unchanged += 1
            elapsed = round(time.monotonic()-clock, 2)
            history.append(dict(geracao=generation, aptidao=best_value, avaliados=len(seen), segundos=elapsed)
                           | seen[best][1] | dict(zip(names, best)))
            if on_progress:
                on_progress(history, names)
            print(f'Geração {generation} | {metric}={best_value:.4f} | {len(seen)} candidatos | {elapsed}s', flush=True)
            if stop_score and best_value >= stop_score:
                reason = 'meta de desempenho'
                break
            if len(seen) == total:
                reason = 'espaço de busca avaliado'
                break
            if deadline_hit or (seconds and elapsed >= seconds):
                reason = 'limite de tempo'
                break
            if patience and unchanged >= patience:
                reason = 'gerações sem melhora'
                break
            parents = ranked[:max(2, population//3)]
            candidates = populate([best], parents)

    fitted = parameters(best)
    optimized = dict(zip(names, best))
    original_score = replay.score(defaults)
    scores.clear()
    best_score = replay.score(fitted)
    pred = predictions(fitted, best_score)
    baseline = predictions(defaults, original_score)
    summary = dict(
        classe_alvo=config.get('classe_alvo', '1C'), alvo=replay.specification, segundos_por_candle=replay.seconds,
        entradas_na_abertura=True, configuracao=config,
        arvores=len(replay.trees), arvores_removidas=len(replay.model.trees)-len(replay.trees),
        campos_excluidos=sorted(replay.excluded), threads=workers, cache_ram_mb=budget/1024**2,
        metrica=metric, parada=reason, candidatos_avaliados=len(seen), espaco_busca=total,
        segundos_busca=history[-1]['segundos'], atende_min_sinais=best_value >= 0,
        parametros_otimizados=optimized,
        parametros_originais={name: defaults[name] for name in names},
        resultados={name: dict(
            pregoes=np.unique(replay.day[mask]).tolist(),
            barras_com_score=int(np.count_nonzero(np.isfinite(best_score[mask]))),
            original=metrics(replay.label[mask], baseline[mask]),
            otimizado=metrics(replay.label[mask], pred[mask]),
        ) for name, mask in splits.items()},
    )
    (out/'metricas.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    pd.DataFrame(history).to_csv(out/'evolucao.csv', index=False)
    ranking = [dict(zip(names, g)) | {'aptidao': fitness} | stats for g, (fitness, stats) in seen.items()]
    pd.DataFrame(ranking).sort_values('aptidao', ascending=False).to_csv(out/'candidatos.csv', index=False)
    columns = ['minuto', 'ordem_no_minuto', 'v_barra_id', 'segmento', *OHLC]
    candles = replay.frame[columns]
    candles.to_csv(out/'candles.csv', index=False)
    predictions_csv = candles.assign(
        classe_real=replay.frame.get('classe'), alvo_real=replay.label, score_original=original_score, score_otimizado=best_score,
        sinal_original=baseline & base_mask, sinal_otimizado=pred & base_mask,
        amostra=np.select([search, test], ['busca', 'teste'], default='fora_do_horario'),
    )
    predictions_csv.loc[base_mask].to_csv(out/'predicoes.csv', index=False)
    warning = ''
    if (best_value >= 0 and config.get('classe_alvo', '1C') == '1C'
            and replay.specification.get('modo', 'classe') == 'classe' and len(replay.trees) == len(replay.model.trees)):
        (out/'modelo_parametrizado.ntsl').write_text(replay.model.patched(optimized), encoding='utf-8')
    elif best_value < 0:
        warning = 'Nenhum candidato cumpriu o mínimo de sinais na busca.'
    else:
        warning = 'A avaliação reaproveita o score do ensemble. A configuração não é exportada como NTSL quando muda o alvo ou remove árvores.'
    write_html(out, summary, warning, history, names)
    print(f'Relatório: {out/"relatorio.html"}')


def write_html(out, summary, warning, history, names):
    rows = []
    for split, result in summary['resultados'].items():
        for version in ('original', 'otimizado'):
            m = result[version]
            rows.append(f'<tr><td>{split}</td><td>{version}</td><td>{m["barras"]}</td>'
                        f'<td>{m["sinais"]}</td><td>{m["accuracy"]:.2%}</td><td>{m["precision"]:.2%}</td>'
                        f'<td>{m["recall"]:.2%}</td><td>{m["f1"]:.4f}</td>'
                        f'<td>{m["balanced_accuracy"]:.4f}</td>'
                        f'<td>{m["tp"]} / {m["fp"]} / {m["fn"]} / {m["tn"]}</td></tr>')
    detail = html.escape(json.dumps(summary, indent=2, ensure_ascii=False))
    specification = summary['alvo']
    mode = specification.get('modo', 'classe')
    if mode == 'classe':
        label = f"Classe {summary['classe_alvo']}"
    elif mode == 'barras':
        label = f"{specification['lado']} · fechamento de {specification['barras']} barras"
    else:
        label = f"{specification['lado']} · toque de {specification['pontos']} pontos em {specification['barras']} barras"
    target = html.escape(label)
    graphs = charts(history, names)
    note = html.escape(warning)
    content = f"""<!doctype html>
<html lang="pt-BR"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Simulador de Cotação</title>
<style>
body{{font:16px system-ui;max-width:1040px;margin:4rem auto;padding:0 1.2rem;color:#152c2b;background:#f5f8f7}}
h1{{font-size:2.6rem;letter-spacing:-.04em}} table{{border-collapse:collapse;background:white;width:100%}}
th,td{{padding:.75rem;text-align:left;border-bottom:1px solid #dce7e4;white-space:nowrap}}
th{{background:#153b36;color:white}} pre{{overflow:auto;background:white;padding:1rem}}
.table{{overflow:auto}} a{{color:#146253}} p{{max-width:75ch}}
figure{{margin:14px 0;padding:14px;background:white}} svg{{width:100%;max-height:245px;font-size:11px}} .legenda{{font-size:13px}}
</style>
<h1>Simulador de Cotação</h1>
<p><strong>{target}</strong> · candles de {summary['segundos_por_candle']} s · {summary['candidatos_avaliados']} candidatos</p>
<p>Parada por {html.escape(summary['parada'])}. {note}</p>
<p>O teste usa pregões posteriores aos da busca. A matriz está na ordem VP, FP, FN, VN.
Barras sem score ou em aquecimento contam como ausência de sinal.</p>
<div class="table"><table><thead><tr><th>Amostra</th><th>Versão</th><th>Barras</th><th>Sinais</th>
<th>Acurácia</th><th>Precisão</th><th>Recall</th><th>F1</th><th>Acurácia balanceada</th><th>VP / FP / FN / VN</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div>
<h2>Evolução por geração</h2>{graphs}
<p>Árvores ativas: {summary["arvores"]}. Árvores removidas pelo filtro: {summary["arvores_removidas"]}.</p>
<p><a href="candles.csv">Candles</a> · <a href="predicoes.csv">Predições</a> · <a href="candidatos.csv">Candidatos</a> ·
<a href="evolucao.csv">Evolução</a> · <a href="metricas.json">Métricas completas</a></p>
<details><summary>Configuração e resultados detalhados</summary><pre>{detail}</pre></details></html>"""
    (out/'relatorio.html').write_text(content, encoding='utf-8')


def validate_ohlc(frame):
    o, h, l, c = (pd.to_numeric(frame[k], errors='raise').to_numpy() for k in OHLC)
    if len(o) == 0 or not np.isfinite([o, h, l, c]).all():
        raise ValueError('A base deve conter OHLC numérico em todas as barras.')
    if (h < np.maximum(o, c)).any() or (l > np.minimum(o, c)).any():
        raise ValueError('Máxima/mínima incompatível com abertura/fechamento.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    rebuild = commands.add_parser('candles', help='Gera OHLC a partir de negócios ou de um CSV exportado.')
    rebuild.add_argument('csv', type=Path)
    rebuild.add_argument('--formato', choices=['negocios', 'profit'], required=True)
    rebuild.add_argument('--segundos', type=int, required=True)
    rebuild.add_argument('--saida', type=Path, required=True)
    tuner = commands.add_parser('otimizar', help='Calibra o classificador sobre candles rotulados.')
    tuner.add_argument('--config', type=Path, required=True)
    tuner.add_argument('--csv', type=Path, required=True)
    tuner.add_argument('--ntsl', type=Path, default=Path(__file__).with_name('modelo_profit.ntsl'))
    tuner.add_argument('--saida', type=Path, default=Path('resultados')/datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    args = parser.parse_args()
    try:
        if args.command == 'candles':
            read = read_ticks if args.formato == 'negocios' else read_export
            frame = read(args.csv, args.segundos)
            validate_ohlc(frame)
            if args.formato == 'profit':
                frame = frame[['minuto', 'ordem_no_minuto', 'v_barra_id', 'segmento', *OHLC]]
            args.saida.parent.mkdir(parents=True, exist_ok=True)
            frame.to_csv(args.saida, index=False)
            print(f'{len(frame)} candles em {args.saida}')
        else:
            config = json.loads(args.config.read_text(encoding='utf-8-sig'))
            model = NTSLModel(args.ntsl)
            seconds = int(config['segundos_por_candle'])
            frame = read_export(args.csv, seconds)
            validate_ohlc(frame)
            args.saida.mkdir(parents=True, exist_ok=False)
            optimize(Replay(frame, model, seconds, config.get('classe_alvo', '1C'), config.get('alvo'), config.get('campos_excluidos', ())), config, args.saida)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, ArithmeticError) as error:
        parser.exit(2, f'Erro: {error}\n')


if __name__ == '__main__':
    main()
