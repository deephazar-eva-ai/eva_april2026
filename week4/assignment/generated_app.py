from prefab_ui.app import PrefabApp
from prefab_ui.components import (
    Badge, Button, Card, CardContent, CardHeader, CardTitle,
    Checkbox, Column, H1, H2, H3, Muted, Progress, Ring, Row,
    Tab, Table, TableBody, TableCell, TableHead, TableHeader, TableRow, Tabs, Text,
)
from prefab_ui.components.charts import (
    BarChart, ChartSeries, LineChart, PieChart, Sparkline,
)

with PrefabApp(css_class="max-w-5xl mx-auto p-6") as app:
    with Card():
        with CardHeader():
            CardTitle('Reliance Financial Overview')
        with CardContent():
            with Tabs(value='performance'):
                with Tab('Performance', value='performance'):
                    with Column(gap=5):
                        with Column(gap=1):
                            Muted('2026 Revenue')
                            H1('5.24T')
                            Muted('INR')
                        with Column(gap=1):
                            Muted('2026 Net Profit')
                            H1('438.51B')
                            Muted('INR')
                        with Column(gap=1):
                            Muted('2026 EPS')
                            H1('32.4')
                            Muted('INR')
                        with Column(gap=2):
                            H3('Revenue Trend (5 Years)')
                            LineChart(data=[{'year': '2022', 'Revenue': 4.45}, {'year': '2023', 'Revenue': 5.43}, {'year': '2024', 'Revenue': 5.48}, {'year': '2025', 'Revenue': 5.33}, {'year': '2026', 'Revenue': 5.24}],
                                      series=[ChartSeries(data_key='Revenue', label='Revenue')],
                                      x_axis='year', show_legend=False)
                with Tab('Financials Table', value='financials_table'):
                    with Column(gap=5):
                        with Column(gap=2):
                            H3('Summary P&L (in Billions INR)')
                            with Table():
                                with TableHeader():
                                    with TableRow():
                                        TableHead('Year')
                                        TableHead('Revenue')
                                        TableHead('Profit')
                                        TableHead('EPS')
                                with TableBody():
                                    with TableRow():
                                        TableCell('2026')
                                        TableCell('5241.05')
                                        TableCell('438.51')
                                        TableCell('32.4')
                                    with TableRow():
                                        TableCell('2025')
                                        TableCell('5327.92')
                                        TableCell('352.62')
                                        TableCell('26.06')
                                    with TableRow():
                                        TableCell('2024')
                                        TableCell('5479.42')
                                        TableCell('420.42')
                                        TableCell('31.07')
                                    with TableRow():
                                        TableCell('2023')
                                        TableCell('5432.49')
                                        TableCell('442.05')
                                        TableCell('32.67')
                                    with TableRow():
                                        TableCell('2022')
                                        TableCell('4453.75')
                                        TableCell('390.84')
                                        TableCell('28.88')
                with Tab('Financial Ratios', value='financial_ratios'):
                    with Column(gap=5):
                        with Column(gap=1):
                            Muted('2026 ROE')
                            H1('7.74')
                            Muted('%')
                        with Column(gap=1):
                            Muted('2026 ROCE')
                            H1('7.29')
                            Muted('%')
                        with Column(gap=1):
                            Muted('2026 Net Margin')
                            H1('8.01')
                            Muted('%')
                        with Column(gap=2):
                            H3('Key Financial Ratios History')
                            with Table():
                                with TableHeader():
                                    with TableRow():
                                        TableHead('Year')
                                        TableHead('Net Margin')
                                        TableHead('ROE')
                                        TableHead('ROCE')
                                with TableBody():
                                    with TableRow():
                                        TableCell('2026')
                                        TableCell('8.01%')
                                        TableCell('7.74%')
                                        TableCell('7.29%')
                                    with TableRow():
                                        TableCell('2025')
                                        TableCell('6.42%')
                                        TableCell('6.49%')
                                        TableCell('7.35%')
                                    with TableRow():
                                        TableCell('2024')
                                        TableCell('7.51%')
                                        TableCell('8.16%')
                                        TableCell('9.55%')
                                    with TableRow():
                                        TableCell('2023')
                                        TableCell('7.97%')
                                        TableCell('8.80%')
                                        TableCell('10.08%')
                                    with TableRow():
                                        TableCell('2022')
                                        TableCell('8.51%')
                                        TableCell('8.29%')
                                        TableCell('8.25%')
                with Tab('Watchlist', value='watchlist'):
                    with Column(gap=5):
                        with Column(gap=2):
                            H3('Industry Competitors')
                            with Table():
                                with TableHeader():
                                    with TableRow():
                                        TableHead('Company')
                                        TableHead('Industry')
                                        TableHead('Market Cap (est)')
                                with TableBody():
                                    with TableRow():
                                        TableCell('TCS')
                                        TableCell('IT Services')
                                        TableCell('14.2T INR')
                                    with TableRow():
                                        TableCell('HDFC Bank')
                                        TableCell('Banking')
                                        TableCell('12.8T INR')
                                    with TableRow():
                                        TableCell('ICICI Bank')
                                        TableCell('Banking')
                                        TableCell('8.9T INR')
