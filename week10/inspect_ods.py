import ezodf
doc = ezodf.opendoc("/home/acer/Documents/DEEPAK/eva_april2026/mainbranch/eva_april2026/week10/data/tasklist.ods")
print("Sheets:", [s.name for s in doc.sheets])
