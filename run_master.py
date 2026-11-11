"""Build one offline dashboard from scan HTML, rebound watchlist and backtest JSON."""
import argparse
import html
import json
from pathlib import Path
from screener.config import load_config

CSS = '''body{margin:0;background:#0b1220;color:#e8eef8;font:15px system-ui,Arial}header{padding:25px 4%;background:#111c30;border-bottom:1px solid #30415b}h1{margin:0;font-size:27px}header p,.muted{color:#9db0c9}nav{display:flex;gap:8px;padding:14px 4%;flex-wrap:wrap}button{background:#1c2a40;border:1px solid #3b506d;color:#e8eef8;padding:12px 17px;border-radius:9px;cursor:pointer}button.active{background:#2563eb;border-color:#60a5fa}.panel{display:none;padding:0 4% 35px}.panel.active{display:block}iframe{width:100%;height:82vh;border:1px solid #34445f;background:white;border-radius:10px}table{border-collapse:collapse;width:100%;margin:14px 0 26px}td,th{border-bottom:1px solid #30415b;text-align:right;padding:11px 9px}td:first-child,th:first-child{text-align:left}th{color:#a9bfdc}.cards{display:flex;gap:12px;flex-wrap:wrap}.card{background:#16243a;border:1px solid #33435d;padding:15px;border-radius:12px;min-width:145px}.card b{display:block;font-size:24px;margin-top:6px}.pos{color:#4ade80}.neg{color:#fb7185}pre{white-space:pre-wrap;background:#142238;padding:20px;border-radius:10px;line-height:1.6} .scroll{overflow-x:auto}.note{background:#1c2b42;border-left:3px solid #fbbf24;padding:13px;margin:15px 0}'''

def fmt(v, suffix='%'):
    return '—' if v is None else f'{v:+.2f}{suffix}'

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', default='output/master_dashboard.html')
    args = ap.parse_args()
    root = Path('output')
    threshold = load_config()['detection']['daily_drop_pct']
    scan_files = sorted(root.glob('report_*_close.html')) or sorted(root.glob('report_*_open.html'))
    scan = scan_files[-1] if scan_files else None
    rebound = scan.with_name(scan.stem + '_rebound_watchlist.txt') if scan else None
    datafile = root / 'rebound_backtest.json'
    data = json.loads(datafile.read_text(encoding='utf-8')) if datafile.exists() else None
    sections = []
    research_file = scan.with_name(scan.stem + '_research.json') if scan else None
    if research_file and research_file.exists():
        research = json.loads(research_file.read_text(encoding='utf-8'))
        candidates = research.get('candidates', [])
        rows = []
        for c in candidates:
            h = c.get('history') or {}
            five = h.get('horizons', {}).get('5') or h.get('horizons', {}).get(5) or {}
            n = h.get('n', 0)
            rate = five.get('win_rate')
            mean = five.get('mean_return')
            rows.append((c, n, rate, mean))
        # Rank first by reliability of the history, then observed five-day outcomes and existing research score.
        # This is a descriptive ranking, NOT a calibrated probability or a buy signal.
        rows.sort(key=lambda x: x[0]['score'], reverse=True)
        summary = f'<div class="note">Strictly greater than {threshold:g}% CLOSE-TO-CLOSE declines only. Historical win rates are NOT forecasts or calibrated probabilities. A small sample cannot justify a buy recommendation. Historical statistics are close-to-close hypothetical returns, with assumed costs. The ranking is descriptive research, not investment advice.</div>'
        summary += f'<div class="cards"><div class="card">Trading date<b>{html.escape(str(research.get("as_of", "?")))}</b></div><div class="card">Qualified candidates<b>{len(rows)}</b></div><div class="card">Universe scanned<b>{research.get("universe_size", 0)}</b></div></div>'
        if not rows:
            summary += '<p>No qualifying candidates in the current report.</p>'
        for rank, (c, n, rate, mean) in enumerate(rows, 1):
            status = 'Research candidate' if n >= 10 and rate is not None and rate >= .6 and mean is not None and mean > 0 else ('Limited evidence' if n < 10 else 'Review risks')
            summary += f'<h2>#{rank} {html.escape(c["ticker"])} — {html.escape(c["name"])} · {status}</h2><p>Daily drop: {c["daily_drop_pct"]:+.2f}% · Rebound research score: <b>{c["score"]}/100</b> · Historical drops: {h.get("total_events", n)} · Score coverage: {c.get("score_coverage_pct", "?")}%</p>'
            summary += '<div class="scroll"><table><tr><th>Holding period</th><th>Events</th><th>Average net return</th><th>Median net return</th><th>Historical positive rate</th><th>Beat SPY</th></tr>'
            for period in (1, 2, 3, 5, 10, 20):
                st = (c.get('history') or {}).get('horizons', {})
                rec = st.get(str(period)) or st.get(period) or {}
                def pc(v): return '—' if v is None else f'{v*100:+.1f}%'
                summary += f'<tr><td>{period}d</td><td>{n}</td><td>{pc(rec.get("mean_return"))}</td><td>{pc(rec.get("median_return"))}</td><td>{pc(rec.get("win_rate"))}</td><td>{pc(rec.get("win_rate_vs_spy"))}</td></tr>'
            summary += '</table></div>'
            summary += f'<details open><summary><b>Every historical decline greater than {threshold:g}% — 3, 5, 10 and 20 trading days</b></summary>'
            summary += '<p class="muted">Each event is shown, including back-to-back drops. Returns start at the decline-day close and subtract the configured 0.10% round-trip cost. Pending = insufficient future sessions.</p>'
            summary += '<div class="scroll"><table><tr><th>Selloff date</th><th>Daily decline</th><th>3d</th><th>5d</th><th>10d</th><th>20d</th></tr>'
            for ev in reversed(h.get('events', [])):
                def ep(k):
                    value = ev.get('r' + str(k))
                    if value is None: return '<td>Pending</td>'
                    return f'<td class={"pos" if value >= 0 else "neg"}>{value:+.2f}%</td>'
                summary += '<tr><td>' + html.escape(ev['date']) + '</td><td>' + f'{ev["drop_pct"]:+.2f}%' + '</td>' + ''.join(ep(k) for k in (3,5,10,20)) + '</tr>'
            summary += '</table></div></details>'
            summary += '<details><summary><b>100-point score breakdown</b></summary><table><tr><th>Category</th><th>Points earned</th><th>Possible points</th><th>Explanation</th></tr>'
            labels = {'historical_rebound':'Historical rebound performance','earnings_quality':'Reason for decline (earnings proxy)','fundamentals':'Financial strength','market_context':'Market conditions','technical_support':'Technical support','valuation':'Valuation','drop_severity':'Drop severity (0 weight)'}
            for comp in c.get('score_breakdown', []):
                if comp.get('weight',0) <= 0: continue
                pts = comp.get('points'); maximum = comp.get('max_points')
                summary += '<tr><td>' + labels.get(comp['component'],comp['component']) + '</td><td>' + ('N/A' if pts is None else f'{pts:.1f}') + '</td><td>' + ('N/A' if maximum is None else f'{maximum:.1f}') + '</td><td>' + html.escape(str(comp.get('note',''))) + '</td></tr>'
            summary += '</table><p class="muted">Earnings-based catalyst assessment is incomplete without full guidance, revenue expectations and verified news. Missing data can cause weight rescaling; the score is not a calibrated probability.</p></details>'
            risks = c.get('risks') or []
            if risks:
                summary += '<p><b>Risks and cautions:</b> ' + ' '.join(html.escape(str(x)) for x in risks) + '</p>'
            summary += '<p class="muted">Assessment is descriptive, not a predictive likelihood. Review the selloff catalyst and company filings before deciding.</p>'
        sections.append(('research', 'Ranked stock research', summary))
    if scan:
        sections.append(('scan','Today’s opportunities', '<iframe title="Original Overreaction Report" srcdoc="' + html.escape(scan.read_text(encoding='utf-8'), quote=True) + '"></iframe>'))
    if rebound and rebound.exists():
        sections.append(('rebound','Reversal watchlist','<pre>' + html.escape(rebound.read_text(encoding='utf-8')) + '</pre>'))
    if data:
        periods = data['periods']
        cards = '<div class="cards">' + ''.join(f'<div class="card">{html.escape(str(k))}<b>{html.escape(str(v))}</b></div>' for k,v in [('Historical setups',data['setups']),('Confirmed setups',data['confirmed']),('Drop threshold',f"{data['threshold']}%"),('Symbols',len(data['tickers']))]) + '</div>'
        rows = ''
        for p in periods:
            row = data['summary'][str(p)]
            def cells(k):
                s=row[k]
                return f'<td>{s["n"]}</td><td class="{"pos" if (s["mean_pct"] or 0)>=0 else "neg"}">{fmt(s["mean_pct"])}</td><td>{fmt(s["median_pct"])}</td><td>{fmt(s["win_rate_pct"])}</td>'
            rows += f'<tr><td>{p} days</td>{cells("immediate_all")}{cells("immediate_matched")}{cells("confirmed_matched")}</tr>'
        table = '<div class="scroll"><table><thead><tr><th rowspan="2">Hold</th><th colspan="4">Immediate · all setups</th><th colspan="4">Immediate · matched</th><th colspan="4">Confirmation · matched</th></tr><tr>' + '<th>Trades</th><th>Mean</th><th>Median</th><th>Win rate</th>'*3 + '</tr></thead><tbody>' + rows + '</tbody></table></div>'
        stocks = ''
        for ticker in sorted(data['by_stock']):
            rec=data['by_stock'][ticker]
            stocks += f'<tr><td>{html.escape(ticker)}</td><td>{rec["setups"]}</td><td>{rec["confirmed"]}</td>' + ''.join(f'<td>{fmt(rec["periods"][str(p)]["immediate_all"]["mean_pct"])}</td>' for p in periods) + '</tr>'
        stocks_table='<h2>Stock-by-stock · immediate entry mean</h2><div class="scroll"><table><thead><tr><th>Symbol</th><th>Setups</th><th>Confirmed</th>'+''.join(f'<th>{p}d</th>' for p in periods)+'</tr></thead><tbody>'+stocks+'</tbody></table></div>'
        backtest=cards+'<h2>Return by holding period</h2>'+table+stocks_table+'<div class="note">Historical research only. Close-to-close hypothetical fills; no slippage, delisted stocks, point-in-time market caps or out-of-sample validation. Confirmation does not trade every setup. Matched entries use different entry and exit dates. The backtest universe is the symbols shown above, not necessarily the full daily scan universe.</div>'
        sections.append(('backtest','Historical backtest',backtest))
    validation_file = root / 'walkforward_validation.json'
    if validation_file.exists():
        v=json.loads(validation_file.read_text(encoding='utf-8'))
        summary='<div class="note">PRICE-ONLY WALK-FORWARD REPLAY, not the original composite score. Historical constituent membership and fundamentals are not reconstructed. Scores are not probabilities.</div>'
        summary+=f'<div class="cards"><div class="card">Coverage<b>{v.get("universe_downloaded",0)}/{v.get("universe_requested",0)}</b></div><div class="card">Replay dates<b>{v["replay_dates"]}</b></div><div class="card">Selected events<b>{v["selected_events"]}</b></div></div>'
        summary+='<h2>Ranked picks vs all rankable setups</h2><div class="scroll"><table><tr><th>Horizon</th><th>Picks n</th><th>Picks mean</th><th>Picks vs SPY</th><th>All mean</th><th>All vs SPY</th></tr>'
        for h in (1,2,3,5,10,20):
            a=v['selected'][str(h)];b=v['all_rankable'][str(h)]
            summary+=f'<tr><td>{h}d</td><td>{a["n"]}</td><td>{fmt(a["mean_pct"])}</td><td>{fmt(a["mean_excess_spy_pct"])}</td><td>{fmt(b["mean_pct"])}</td><td>{fmt(b["mean_excess_spy_pct"])}</td></tr>'
        summary+='</table></div><h2>Historical replay — choose a trading date</h2>'
        summary+='<select id="replay-date" style="padding:10px;background:#1c2a40;color:white;border:1px solid #3b506d">'
        for r in reversed(v['replays']):summary+=f'<option value="{html.escape(r["date"])}">{html.escape(r["date"])} · {r["setups"]} selloffs</option>'
        summary+='</select><div id="replay-detail" class="scroll"></div>'
        payload=json.dumps(v['replays']).replace('<',chr(92)+'u003c').replace('>',chr(92)+'u003e').replace('&',chr(92)+'u0026')
        summary+=f'<script type="application/json" id="replay-data">{payload}</script>'
        summary+="""<script>(function(){const s=document.getElementById('replay-date'),t=document.getElementById('replay-detail'),rs=JSON.parse(document.getElementById('replay-data').textContent);function show(){const r=rs.find(x=>x.date===s.value);if(!r)return;let out='<p>Setups: '+r.setups+' · rankable: '+r.rankable+' · selected: '+r.picks.length+'</p><table><tr><th>Symbol</th><th>Drop</th><th>Score</th><th>Prior events</th><th>1d actual</th><th>5d actual</th><th>20d actual</th></tr>';for(const x of r.picks){out+='<tr><td>'+x.ticker+'</td><td>'+x.drop_pct.toFixed(1)+'%</td><td>'+x.score+'</td><td>'+x.prior_events+'</td><td>'+x.returns['1'].toFixed(2)+'%</td><td>'+x.returns['5'].toFixed(2)+'%</td><td>'+x.returns['20'].toFixed(2)+'%</td></tr>'}t.innerHTML=out+'</table><p>'+r.unranked.length+' setups lacked 5 matured prior events and were not scored.</p>'}s.addEventListener('change',show);show()})();</script>"""
        summary+='<div class="note">'+' '.join(html.escape(x) for x in v['limitations'])+'</div>'
        sections.append(('validation','Walk-forward & historical replay',summary))
    # Historical 30-day price-only archive: separate from the full live scan.
    archive_file = root / 'last_30_days.json'
    if archive_file.exists():
        archive = json.loads(archive_file.read_text(encoding='utf-8'))
        days = archive.get('days', [])
        threshold = archive.get('threshold_pct', 6.5)
        history_html = '<div class="note">Historical daily close-to-close drops strictly greater than ' + html.escape(str(threshold)) + '%. Price-only reconstruction from the current stock universe. Historical $10B market-cap eligibility, composite scores and catalysts are NOT verified; these are not equivalent to full historical live-screen results.</div>'
        history_html += '<label for="history-date"><b>Choose a trading date (last 30 calendar days)</b></label> '
        history_html += '<select id="history-date" style="padding:12px;background:#1c2a40;color:white;border:1px solid #3b506d;border-radius:8px">'
        for day in days:
            date = html.escape(day['date'], quote=True)
            history_html += f'<option value="{date}">{date} · {len(day["declines"])} declines</option>'
        history_html += '</select><div id="history-results" class="scroll" aria-live="polite"></div>'
        history_html += '<p class="muted">' + html.escape(archive.get('limitations','')) + '</p>'
        payload = json.dumps(days).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
        history_html += '<script type="application/json" id="history-json">' + payload + '</script>'
        history_html += """<script>(function(){const s=document.getElementById('history-date'),el=document.getElementById('history-results'),node=document.getElementById('history-json');if(!s||!el||!node)return;const days=JSON.parse(node.textContent);function draw(){const d=days.find(x=>x.date===s.value);if(!d){el.textContent='No historical price data available.';return;}let out='<p><b>'+d.declines.length+' declines</b> on '+d.date+' · '+d.symbols_with_prices+' symbols with price data</p>';if(!d.declines.length){el.innerHTML=out+'<p>No stocks crossed the threshold in the available price data.</p>';return;}out+='<table><thead><tr><th>Ticker</th><th>Daily decline</th><th>Composite score</th></tr></thead><tbody>';for(const x of d.declines){out+='<tr><td>'+x.ticker+'</td><td class="neg">'+x.drop_pct.toFixed(2)+'%</td><td>Not reconstructed</td></tr>';}el.innerHTML=out+'</tbody></table>';}s.addEventListener('change',draw);draw();})();</script>"""
        sections.insert(0, ('history30', 'Last 30 days', history_html))
    if not sections:
        raise SystemExit('No reports found. Run run_scan.py and/or run_backtest.py first.')
    buttons=''.join(f'<button data-tab="{key}" class="{"active" if i==0 else ""}">{label}</button>' for i,(key,label,_) in enumerate(sections))
    panels=''.join(f'<section id="{key}" class="panel {"active" if i==0 else ""}">{body}</section>' for i,(key,_,body) in enumerate(sections))
    document='<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Overreaction Screener · Master Dashboard</title><style>'+CSS+'</style></head><body><header><h1>Overreaction Screener</h1><p>Master Dashboard · Daily opportunities, reversal signals and historical research</p></header><nav>'+buttons+'</nav>'+panels+'''<script>document.querySelectorAll('button[data-tab]').forEach(b=>b.addEventListener('click',()=>{document.querySelectorAll('button[data-tab]').forEach(x=>x.classList.toggle('active',x===b));document.querySelectorAll('.panel').forEach(p=>p.classList.toggle('active',p.id===b.dataset.tab));}));</script></body></html>'''
    target=Path(args.output);target.parent.mkdir(parents=True,exist_ok=True);target.write_text(document,encoding='utf-8');print('Saved:',target)

if __name__=='__main__':main()
