"""Alvos, auditoria de campos e gráficos do otimizador."""
from html import escape
import math
import re

import numpy as np
import pandas as pd

BLOCKED = {'classe', 'tipo_ordem', 'pts_maior_30'}


def labels(frame, target, specification):
    mode = specification.get('modo', 'classe')
    if mode == 'classe':
        if 'classe' not in frame:
            raise ValueError('O alvo de classe requer a coluna classe.')
        actual = frame['classe']
        return actual.eq(target).fillna(False).to_numpy(dtype=bool), actual.notna().to_numpy()
    n = specification.get('barras', 1)
    direction = specification.get('lado', 'compra')
    if mode not in {'barras', 'pontos'} or type(n) is not int or not 1 <= n <= 100_000 or direction not in {'compra', 'venda'}:
        raise ValueError('Configure o alvo com 1 a 100.000 barras e lado compra ou venda.')
    groups = frame['segmento']
    valid = groups.eq(groups.shift(1-n)).to_numpy()
    if mode == 'barras':
        end = frame['fechamento'].shift(1-n)
        change = end - frame['abertura']
        result = change.gt(0) if direction == 'compra' else change.lt(0)
    else:
        points = float(specification.get('pontos', 0))
        if not math.isfinite(points) or points <= 0:
            raise ValueError('O alvo em pontos precisa ser positivo.')
        extreme = frame['maxima' if direction == 'compra' else 'minima']
        reverse = extreme.iloc[::-1].rolling(n)
        future = (reverse.max() if direction == 'compra' else reverse.min()).iloc[::-1]
        result = (future-frame['abertura']).ge(points) if direction == 'compra' else (frame['abertura']-future).ge(points)
    return result.fillna(False).to_numpy(dtype=bool), valid


def tree_features(tree):
    if isinstance(tree, float):
        return set()
    field, _, _, left, right = tree
    return {field} | tree_features(left) | tree_features(right)


PRICE = {'abertura', 'maxima', 'minima', 'fechamento'}
FLOW = {'v_agressao_compra', 'v_agressao_venda', 'v_trades_atual'}
BOOK = {'v_bid', 'v_ask', 'v_qtd_bid', 'v_qtd_ask', 'v_qtd_compra_book', 'v_qtd_venda_book'}
DIRECT = {
    'QtdAsk': {'v_qtd_ask'}, 'QtdBid': {'v_qtd_bid'},
    'SpreadTicks': {'v_spread_ticks', 'v_bid', 'v_ask'},
    'ImbalanceTopo': {'v_imbalance_topo', 'v_qtd_bid', 'v_qtd_ask'},
    'GapAbertura': {'v_gap_abertura', 'abertura', 'fechamento'},
    'BidVsMedia': {'v_bid', 'fechamento', 'v_media_preco'},
    'AskVsMedia': {'v_ask', 'fechamento', 'v_media_preco'},
    'MicroVsBid': {'v_micropreco', *BOOK},
    'RefSetupVsMedia': {'v_preco_referencia_setup', *PRICE, *FLOW, *BOOK},
    'ReacaoFavoravel': {'v_reacao_favoravel', *PRICE, *FLOW, *BOOK},
    'RecuoAtual': {'v_recuo_atual', *PRICE, *FLOW, *BOOK},
    'FlagPressaoSaidaShort': {'v_flag_pressao_saida_short', *PRICE, *FLOW, *BOOK},
    'PosicaoFechamentoRange': {'v_posicao_fechamento_range', *PRICE, 'v_range_atual'},
    'Aceleracao': {'v_aceleracao_preco', 'v_velocidade_preco', 'v_retorno_1', 'fechamento'},
    'ATRRange': {'v_atr_range', 'v_true_range_atual', *PRICE, 'v_range_atual'},
    'RangeBarraFechada': {'v_range_fechada', 'v_range_atual', 'maxima', 'minima'},
    'TradesFechadaSerie': {'v_trades_fechada', 'v_trades_atual'},
}


def dependencies(key):
    if key.startswith('Flag') and key.endswith('Valido'):
        key = key[4:-6]
    if key.startswith(('DeltaM', 'AbsDeltaM')):
        return FLOW | {'v_delta_agressao'}
    if key.startswith(('FaixaM', 'RangeAtual')):
        return {'v_range_atual', 'maxima', 'minima'}
    if key in DIRECT:
        return DIRECT[key]
    snake = re.sub(r'(?<!^)(?=[A-Z])', '_', key).lower()
    aliases = {
        'retorno3': 'retorno_3', 'retorno5': 'retorno_5',
        'distancia_media_fechada': 'distancia_media_fechada',
    }
    named = {'v_'+aliases.get(snake, snake)}
    if key.startswith('Classe1C'):
        return named | PRICE | {'v_range_atual', 'v_corpo_atual'}
    if key.startswith(('Agressao', 'Delta', 'AbsDelta', 'RazaoAgressao', 'Trades', 'Impacto')):
        return named | FLOW | ({'fechamento', 'v_retorno_1'} if key.startswith('Impacto') else set())
    return named | PRICE | {'v_media_preco', 'v_retorno_1', 'v_media_range', 'v_range_atual'}


def chart(history, series, title, percent=False, axis='Geração'):
    if not history or not series:
        return ''
    values = [float(row[key]) for row in history for key, _ in series]
    low, high = (0, 1) if percent else (min(values), max(values))
    span = high-low or 1
    x = lambda i: 82 + i*606/max(1,len(history)-1)
    y = lambda v: 176 - (float(v)-low)*139/span
    result = [f'<figure><figcaption>{escape(title)}</figcaption><svg role="img" aria-label="{escape(title)}" viewBox="0 0 720 213">']
    for fraction in (0, .25, .5, .75, 1):
        value = low+fraction*(high-low)
        pos = 176-fraction*139
        label = f'{value:.0%}' if percent else f'{value:.4g}'
        result.append(f'<path d="M82,{pos} H688" stroke="#cbdad6"/><text x="75" y="{pos+4}" text-anchor="end">{label}</text>')
    result.append(f'<text x="82" y="201">{escape(axis)} {history[0]["geracao"]}</text><text x="688" y="201" text-anchor="end">{history[-1]["geracao"]}</text>')
    colors = ('#126355','#8a421f','#244da3','#733f92','#415f27')
    legend = []
    for (key,label),color in zip(series,colors):
        points = ' '.join(f'{x(i):.1f},{y(row[key]):.1f}' for i,row in enumerate(history))
        result.append(f'<polyline fill="none" stroke="{color}" stroke-width="2.5" points="{points}"/>')
        for i,row in enumerate(history):
            value = row[key]
            formatted = f'{value:.2%}' if percent else str(value)
            result.append(f'<circle cx="{x(i):.1f}" cy="{y(value):.1f}" r="3" fill="{color}"><title>{escape(axis)} {row["geracao"]} · {escape(label)} {formatted}</title></circle>')
        legend.append(f'<span style="color:{color}">● {escape(label)}</span>')
    return ''.join(result)+'</svg><div class="legenda">'+' · '.join(legend)+'</div></figure>'


def charts(history, parameters):
    result = chart(history, [('accuracy','Acurácia'),('precision','Precisão dos sinais'),
                             ('recall','Recall'),('f1','F1'),('balanced_accuracy','Acurácia balanceada')],
                   'Métricas do melhor candidato na busca', True)
    return result + ''.join(chart(history, [(name,name)], name) for name in parameters)
