"""Генерация HTML-дашборда аналитики."""
import os
import sys
import json
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import config
from database import Database


def generate_dashboard(db: Database, output_path: str = "dashboard/index.html"):
    daily = db.get_daily_stats(30)
    top = db.get_top_products(10)
    mp_stats = db.get_marketplace_stats()
    total = db.get_product_count()

    click_labels = json.dumps([d["date"] for d in daily])
    click_data = json.dumps([d["clicks"] for d in daily])
    post_data = json.dumps([d["posts"] for d in daily])

    mp_labels = json.dumps([s["marketplace"].upper() for s in mp_stats])
    mp_products = json.dumps([s["total_products"] for s in mp_stats])
    mp_posted = json.dumps([s["posted"] for s in mp_stats])

    top_rows = ""
    for i, p in enumerate(top, 1):
        top_rows += f"""
        <tr>
            <td>{i}</td>
            <td>{p['name'][:60]}</td>
            <td>{p['marketplace'].upper()}</td>
            <td>{p['total_clicks']}</td>
            <td>{p['discount_percent']}%</td>
        </tr>"""

    mp_rows = ""
    for s in mp_stats:
        mp_rows += f"""
        <tr>
            <td>{s['marketplace'].upper()}</td>
            <td>{s['total_products']}</td>
            <td>{s['posted']}</td>
            <td>{s['unposted']}</td>
            <td>{s['avg_discount']:.0f}%</td>
        </tr>"""

    total_clicks = sum(d["clicks"] for d in daily)
    total_posts = sum(d["posts"] for d in daily)

    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Marketplace Ref Bot — Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
        background: #0f172a; color: #e2e8f0; padding: 20px; }}
.header {{ text-align: center; margin-bottom: 30px; }}
.header h1 {{ font-size: 2em; color: #38bdf8; }}
.header .date {{ color: #94a3b8; margin-top: 5px; }}
.cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
           gap: 15px; margin-bottom: 30px; }}
.card {{ background: #1e293b; border-radius: 12px; padding: 20px;
          border: 1px solid #334155; }}
.card .label {{ color: #94a3b8; font-size: 0.85em; text-transform: uppercase; }}
.card .value {{ font-size: 2em; font-weight: bold; color: #38bdf8; margin-top: 5px; }}
.charts {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 30px; }}
.chart-box {{ background: #1e293b; border-radius: 12px; padding: 20px;
               border: 1px solid #334155; }}
.chart-box h3 {{ color: #f8fafc; margin-bottom: 15px; }}
canvas {{ max-height: 300px; }}
table {{ width: 100%; border-collapse: collapse; margin-bottom: 30px; }}
th, td {{ padding: 10px; text-align: left; border-bottom: 1px solid #334155; }}
th {{ color: #94a3b8; font-weight: 600; text-transform: uppercase; font-size: 0.8em; }}
td {{ color: #e2e8f0; }}
.section {{ background: #1e293b; border-radius: 12px; padding: 20px;
             border: 1px solid #334155; margin-bottom: 20px; }}
.section h3 {{ color: #f8fafc; margin-bottom: 15px; }}
</style>
</head>
<body>
<div class="header">
    <h1>\U0001F4CA Marketplace Ref Bot</h1>
    <div class="date">{datetime.now().strftime('%d.%m.%Y %H:%M')}</div>
</div>

<div class="cards">
    <div class="card">
        <div class="label">Всего товаров</div>
        <div class="value">{total}</div>
    </div>
    <div class="card">
        <div class="label">Кликов за 30д</div>
        <div class="value">{total_clicks}</div>
    </div>
    <div class="card">
        <div class="label">Постов за 30д</div>
        <div class="value">{total_posts}</div>
    </div>
    <div class="card">
        <div class="label">Маркетплейсов</div>
        <div class="value">{len(mp_stats)}</div>
    </div>
</div>

<div class="charts">
    <div class="chart-box">
        <h3>\U0001F4C8 Клики и посты (30 дней)</h3>
        <canvas id="lineChart"></canvas>
    </div>
    <div class="chart-box">
        <h3>\U0001F4E6 Товары по маркетплейсам</h3>
        <canvas id="barChart"></canvas>
    </div>
</div>

<div class="section">
    <h3>\U0001F3C6 Топ товаров по кликам</h3>
    <table>
        <thead><tr><th>#</th><th>Товар</th><th>MP</th><th>Клики</th><th>Скидка</th></tr></thead>
        <tbody>{top_rows}</tbody>
    </table>
</div>

<div class="section">
    <h3>\U0001F4CA Статистика по маркетплейсам</h3>
    <table>
        <thead><tr><th>MP</th><th>Всего</th><th>Опубл.</th><th>Ожидают</th><th>Ср. скидка</th></tr></thead>
        <tbody>{mp_rows}</tbody>
    </table>
</div>

<script>
const lineCtx = document.getElementById('lineChart').getContext('2d');
new Chart(lineCtx, {{
    type: 'line',
    data: {{
        labels: {click_labels},
        datasets: [
            {{ label: 'Клики', data: {click_data}, borderColor: '#38bdf8',
               backgroundColor: 'rgba(56,189,248,0.1)', fill: true, tension: 0.4 }},
            {{ label: 'Посты', data: {post_data}, borderColor: '#a78bfa',
               backgroundColor: 'rgba(167,139,250,0.1)', fill: true, tension: 0.4 }}
        ]
    }},
    options: {{
        responsive: true,
        plugins: {{ legend: {{ labels: {{ color: '#e2e8f0' }} }} }},
        scales: {{
            x: {{ ticks: {{ color: '#94a3b8' }}, grid: {{ color: '#1e293b' }} }},
            y: {{ ticks: {{ color: '#94a3b8' }}, grid: {{ color: '#1e293b' }} }}
        }}
    }}
}});

const barCtx = document.getElementById('barChart').getContext('2d');
new Chart(barCtx, {{
    type: 'bar',
    data: {{
        labels: {mp_labels},
        datasets: [
            {{ label: 'Всего', data: {mp_products}, backgroundColor: '#38bdf8' }},
            {{ label: 'Опубл.', data: {mp_posted}, backgroundColor: '#a78bfa' }}
        ]
    }},
    options: {{
        responsive: true,
        plugins: {{ legend: {{ labels: {{ color: '#e2e8f0' }} }} }},
        scales: {{
            x: {{ ticks: {{ color: '#94a3b8' }}, grid: {{ color: '#1e293b' }} }},
            y: {{ ticks: {{ color: '#94a3b8' }}, grid: {{ color: '#1e293b' }} }}
        }}
    }}
}});
</script>
</body>
</html>"""

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Dashboard generated: {output_path}")


if __name__ == "__main__":
    db = Database(config.DB_PATH)
    generate_dashboard(db)
