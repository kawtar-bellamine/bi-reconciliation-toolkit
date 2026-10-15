# Escalation notes

Data: source extract 2010-12-01 to 2011-12-09, 541,909 lines, file SHA-256 d686c7ec387f

| Issue | Severity | Title | Owner |
|---|---|---|---|
| [DQ-01](DQ-01.md) | high | Lines without a customer ID | source system owner |
| [DQ-03](DQ-03.md) | high | Orders cancelled the same day they were placed | BI team |
| [DQ-11](DQ-11.md) | high | Last month is incomplete | BI team |
| [DQ-02](DQ-02.md) | medium | Probable duplicate lines (identical in every column) | source system owner |
| [DQ-04](DQ-04.md) | medium | Cancellations with no earlier sale of that product to that customer in the data | BI team |
| [DQ-05](DQ-05.md) | medium | Product codes with more than one description | master data owner |
| [DQ-08](DQ-08.md) | medium | Zero-price stock movements in the sales table | BI team |
| [DQ-12](DQ-12.md) | medium | Sale prices over 20 times the product's median price (and over 10 GBP) | sales operations |
| [DQ-06](DQ-06.md) | low | Customers recorded in more than one country | master data owner |
| [DQ-07](DQ-07.md) | low | Invoices with lines at different timestamps | BI team |
| [DQ-09](DQ-09.md) | low | Country values that are not countries | source system owner |
| [DQ-10](DQ-10.md) | low | Expected trading days with no sales (Saturdays and bank holidays excluded) | BI team |
| [DQ-13](DQ-13.md) | low | Product codes that never have a description | master data owner |
