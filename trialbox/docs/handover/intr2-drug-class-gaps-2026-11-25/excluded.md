# INT-R2: the drug branches kept out of each class

**Reader:** the box owner, and the people who build TrialBox

A drug in a branch named here reads False for the class ("not on it"). Every other drug that is not a listed member
reads unknown and goes to the investigator. These are clinical judgements made by the builder, not yet confirmed by a
pharmacist; they do not block the card. Codes are ATC branches. The same table is `EXCLUDED` in
`tests/unit/test_drug_class_gaps_intr2.py`, and a test holds the product to it.

| Class | Kept out | Reason |
| --- | --- | --- |
| urate-lowering therapy | A B C D G H J L M01 M02 M03 M04AC01 M05 M09 N P R S V01 V04 V06 V07 V08 V09 V10 V20 | other main groups and other M groups treat other diseases; M04AC01 does not lower urate |
| glp-1 receptor agonist | A01 A02 A03 A04 A05 A06 A07 A09 A10AB0 A10AC0 A10AE0 A10BA0 A10BB0 A10BC0 A10BF0 A10BG0 A10BH0 A10BK0 A11 A12 A13 A14 A15 B C D G H J L M N P R S V | other main groups; A groups for other uses; single insulins and single oral drugs of another mechanism |
| colchicine | A B C D G H J L M01 M02 M03 M04AA0 M04AB0 M05 M09 N P R S V | other main groups; the single substances of M04AA and M04AB are other drugs |
| methotrexate | A B C D G H J L01A L01BA03 L01BA04 L01BA05 L01C L01D L01E L01F L02 L03 L04AA L04AB L04AC L04AD L04AE L04AF L04AG L04AH L04AJ L04AK L04AL L04AX01 L04AX02 L04AX04 L04AX05 L04AX06 L04AX07 L04AX08 L04AX09 L04AX10 L04AX11 M01A M01B M02 M03 M04 M05 M09 N P R S V | other main groups; antineoplastic and immunosuppressant groups whose single substances are other drugs |
| conventional synthetic dmard other than methotrexate | A01 A02 A03 A04 A05 A06 A07A A07B A07C A07D A07EA A07EC02 A07F A07X A08 A09 A10 A11 A12 A13 A14 A15 A16 B C D01 D02 D03 D04 D06 D07 D08 D09 D10 D11 G H J01B J01C J01D J01E J01F J01G J01M J01R J01X J02 J04 J05 J06 J07 L01BA01 L01E L01F L02 L04AB L04AC L04AF L04AG L04AJ L04AL L04AX03 M01A M01B M02 M03 M04 M05 M09 N P02 P03 R S V | methotrexate itself; biologics and JAK inhibitors; groups for other uses (cancer kinase inhibitors, pain drugs, vaccines) |
| tb preventive therapy | A B C D G H J01A J01B J01C J01D J01E J01F J01G J01R J01X J02 J05 J06 J07 L M N P R S V | other main groups; antibacterial groups other than quinolones; antifungals, antivirals, serums, vaccines |
| hbv antiviral prophylaxis | A B C D G H J01 J02 J04 J05AA J05AB J05AC J05AD J05AE J05AG J05AH J05AJ J07 L01 L02 L04 M N P R S V | other main groups; antivirals for other viruses; vaccines; cancer and immunosuppressant drugs |
| ra biologic | A B C01 C02 C03 C04 C05 C07 C08 C09 C10AA C10AB C10AC C10AD C10B D01 D02 D03 D04 D05 D06 D07 D08 D09 D10 G H J01 J02 J04 J05 J07 L01A L01B L01C L01D L01E L02 L04AA13 L04AD L04AE L04AF L04AH L04AK L04AX01 L04AX02 L04AX03 L04AX04 L04AX05 L04AX06 L04AX07 L04AX09 L04AX10 L04AX11 M01 M02 M03 M04 M09 N01 N03 N04 N05 N07 P R01 R02 R05 R06 R07 S02 S03 V | main groups with no antibody for RA; small molecules: cytotoxics, kinase and JAK inhibitors, calcineurin, S1P, mTOR and DHODH inhibitors, statins |
| biologic dmard or jak inhibitor | A B C01 C02 C03 C04 C05 C07 C08 C09 C10AA C10AB C10AC C10AD C10B D01 D02 D03 D04 D05 D06 D07 D08 D09 D10 G H J01 J02 J04 J05 J07 L01A L01B L01C L01D L01EA L01EB L01EC L01ED L01EE L01EF L01EG L01EH L01EK L01EL L01EM L01EN L01EP L02 L04AA13 L04AD L04AE L04AH L04AK L04AX01 L04AX02 L04AX03 L04AX04 L04AX05 L04AX06 L04AX07 L04AX09 L04AX10 L04AX11 M01 M02 M03 M04 M09 N01 N03 N04 N05 N07 P R01 R02 R05 R06 R07 S02 S03 V | as ra biologic, but JAK inhibitors are members; kinase inhibitors of another named target |
| egfr tyrosine kinase inhibitor | A B C D G H J L01A L01B L01C L01D L02 L03 L04 M N P R S V | other main groups; cytotoxics, hormones, immunostimulants, immunosuppressants |
| anticoagulant | A B01AC0 B01AC1 B01AC2 B02 B03 B06 C01 C02 C03 C04 C06 C07 C08 C09 C10 D G H J L M N P R S V | other main groups; antiplatelet single drugs; blood groups for other uses; heart and vessel groups but C05 |
