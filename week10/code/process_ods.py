import ezodf
from datetime import datetime
import sys

if len(sys.argv) > 1:
    file_path = sys.argv[1]
else:
    file_path = "/home/acer/Documents/DEEPAK/eva_april2026/mainbranch/eva_april2026/week10/data/tasklist.ods"

doc = ezodf.opendoc(file_path)

if "Overdue" in [s.name for s in doc.sheets]:
    print("Overdue sheet already exists, removing...")
    doc.sheets.remove(doc.sheets["Overdue"])

sheet = doc.sheets[0]

header_row = [cell.value for cell in sheet.row(0)]

try:
    status_idx = header_row.index('Status')
    due_date_idx = header_row.index('Due Date')
except ValueError:
    print("Could not find Status or Due Date in header")
    exit(1)

today = datetime.now().date()
overdue_rows = []

for i in range(1, sheet.nrows()):
    row_cells = sheet.row(i)
    if not any(c.value for c in row_cells):
        continue
    status = row_cells[status_idx].value
    due_date_str = row_cells[due_date_idx].value
    if status == "Pending" and due_date_str:
        due_date = None
        try:
            # Handle ISO string like 2024-05-10 or 2024-05-10T00:00:00
            due_date = datetime.strptime(str(due_date_str).split('T')[0], "%Y-%m-%d").date()
        except ValueError:
            try:
                due_date = datetime.strptime(str(due_date_str), "%m/%d/%Y").date()
            except ValueError:
                pass
        
        if due_date and due_date < today:
            overdue_rows.append((due_date, [c.value for c in row_cells]))

# Sort by Due Date
overdue_rows.sort(key=lambda x: x[0])

# Create new sheet
new_sheet = ezodf.Sheet("Overdue", size=(len(overdue_rows) + 1, sheet.ncols()))
doc.sheets.append(new_sheet)

# Write header
for col, val in enumerate(header_row):
    new_sheet[0, col].set_value(val)

# Write data
for row_idx, (date_obj, row_data) in enumerate(overdue_rows, start=1):
    for col, val in enumerate(row_data):
        new_sheet[row_idx, col].set_value(val)

doc.save()
print("Successfully created 'Overdue' sheet.")
