import uno
from com.sun.star.beans import PropertyValue
from datetime import datetime

def fix_spreadsheet():
    localContext = uno.getComponentContext()
    resolver = localContext.ServiceManager.createInstanceWithContext(
        "com.sun.star.bridge.UnoUrlResolver", localContext)
    
    ctx = resolver.resolve("uno:socket,host=localhost,port=2002;urp;StarOffice.ComponentContext")
    smgr = ctx.ServiceManager
    desktop = smgr.createInstanceWithContext("com.sun.star.frame.Desktop", ctx)
    
    url = "file:///home/acer/Documents/DEEPAK/eva_april2026/mainbranch/eva_april2026/week10/data/tasklist.ods"
    
    # Open document
    doc = desktop.loadComponentFromURL(url, "_blank", 0, ())
    
    sheets = doc.getSheets()
    sheet = sheets.getByIndex(0)
    
    # Check if 'Overdue' exists
    if sheets.hasByName("Overdue"):
        sheets.removeByName("Overdue")
    
    sheets.insertNewByName("Overdue", 1)
    overdue_sheet = sheets.getByName("Overdue")
    
    # Simple manual copy
    cursor = sheet.createCursor()
    cursor.gotoEndOfUsedArea(False)
    max_row = cursor.RangeAddress.EndRow
    max_col = cursor.RangeAddress.EndColumn
    
    dest_row = 0
    today = datetime.now().date()
    
    for row in range(max_row + 1):
        copy_row = False
        if row == 0:
            copy_row = True # Header
        else:
            status = sheet.getCellByPosition(1, row).getString() # Assuming Status is col 1
            date_val = sheet.getCellByPosition(2, row).getString() # Assuming Due Date is col 2
            
            # You would need the correct column indices! 
            # I will just write a simpler approach: get data array.

fix_spreadsheet()
