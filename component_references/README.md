# Component references

The documents the component models were built from.

`hardware_models.py` carries transcribed numbers - a gain curve, a noise
temperature, an insertion loss table - and a docstring saying where each came
from. That prose is not the source. A datasheet gets revised, a plot gets
re-digitised, a measurement gets repeated on a different unit at a different
bias, and a number in the code that no longer matches anything has no way of
saying so. This directory holds the actual documents, so a value in a model can
be checked against the thing it was read off rather than against a memory of it.

Keep it to what is small and stable: vendor datasheets, application notes,
measurement reports. Anything large or routinely regenerated - raw s-parameter
sweeps, cooldown logs - belongs wherever that data already lives, referenced by
path and date rather than copied here.

## What is here

| File | Part | Model class | Revision | Retrieved |
|---|---|---|---|---|
| `CITCRYO1-12D_Technical_DataSheet_04.13.26.pdf` | CMT CITCRYO1-12D cryogenic LNA | `CMT_CITCRYO1_12D` | Rev. 04/13/2026 | 2026-09-03 |
| `lnf-lnc0-3_14b.pdf` | Low Noise Factory LNC0.3_14B | `LNF_LNC0_3_14B` | dated 2023-02-24 | 2026-09-03 |
| `lnf-lnc1-5_6b.pdf` | Low Noise Factory LNC1.5_6B | `LNF_LNC1_5_6B` | dated 2023-02-23 | 2026-09-03 |
| `RG316-SMAcable-HUBERSUHNERRG316UDataSheet.pdf` | HUBER+SUHNER RG316/U coax | `SMA_RG316_cables` | DOC-0000177782, 2020-10-14 | 2026-09-03 |
| `VHF-5050+.pdf` | Mini-Circuits VHF-5050+ high pass | `FilterHP_VHF5050p` | REV. B | 2026-08-28 |
| `VLF-6700+.pdf` | Mini-Circuits VLF-6700+ low pass | `FilterLP_VLF6700p` | (unmarked) | 2026-08-28 |
| `ZN4PD-4R722+_dashboard.pdf` | Mini-Circuits ZN4PD-4R722+ 4-way splitter/combiner | *none yet* | REV. OR, ECO-011123 | 2026-09-03 |
| `ZX60-83LN-S+.pdf` | Mini-Circuits ZX60-83LN-S+ LNA | `ZX60_83LN_Splus` | REV. C, ECO-015740 | 2026-09-02 |

The Mini-Circuits parts come from `https://www.minicircuits.com/pdfs/<part>.pdf`,
which is why those files keep the vendor's own names: the filename is the URL is
the part number, including the `+` that marks RoHS compliance.

The revision matters more than the date. Vendors reissue datasheets without
changing the URL, so re-fetching one of these can quietly hand you different
numbers under the same name. Check the revision in the footer against the table
above before concluding a model disagrees with its source.

```
588648afebacaa4f1a9f43e256a8ae8c88d95b8e243083beaccc25426605a0a2  CITCRYO1-12D_Technical_DataSheet_04.13.26.pdf
357e96ba8f26b8e9cc8ba437f8ac871410bff5098e3f2c42ae59bac734c791b5  lnf-lnc0-3_14b.pdf
a00b61e2fb304f22fe46eb062c326222be191801a5146e678fe793e2cc2df2b4  lnf-lnc1-5_6b.pdf
2fb12f580e6b30683fb0717ba493faaf307a5901cfd579e144365ca46266c664  RG316-SMAcable-HUBERSUHNERRG316UDataSheet.pdf
81e25337f96fa20aec016a474bbad1884d726982479b126a04bb964229a6fd76  VHF-5050+.pdf
e9e5a9a8f9e5d6e240a02ee54feaf3b2abc02d3ceacbeec0bacc613b170b5e90  VLF-6700+.pdf
879208550a105029d08914f2b447fd78df7cedc56cbf911f3edce446c9de540d  ZN4PD-4R722+_dashboard.pdf
0d09ff885bd31620bec944d399915ed29d0e5f9a4dcd791c2d1541fff5ef5273  ZX60-83LN-S+.pdf
```

## Stored but not modelled

**`ZN4PD-4R722+`**, a 4-way 0° power splitter/combiner, 400-7200 MHz, 0.9 dB
typical insertion loss, 30 W. There is no splitter in the library and no obvious
place to put one: `SignalChain` is a linear cascade, so a four-port part has no
representation beyond the -6 dB split plus its insertion loss along one arm,
which throws away the amplitude and phase unbalance that are the reasons to
choose this part over another. Worth a deliberate decision rather than a
component that quietly models a splitter as an attenuator.

## What is still missing

Recorded because a gap that is written down can be closed, and one that is not
gets mistaken for completeness.

* **`CMT_CITCRYO1_12D`** - its datasheet is here now, but two things behind the
  model are not. The gain curve is a measurement, `SN216D` at 13 K, Vd = 1.2 V,
  from an s2p file whose path was never recorded; that s2p is the primary record
  and the repo holds only a curve derived from it. And the datasheet's noise
  data is a *plot*, not a table - its specification table says only
  "Noise Temperature < 5 K" - so the flat 5 K in the model is still the honest
  reading of it. Closing that needs the digitised curve, not the PDF.
* **The parts that predate this directory** - `CryoElec_LNA`, `ASU_3GHz_LNA`,
  `ZX60_3018Gplus`, the cryogenic and other room-temperature cables, the
  AD9082. Their docstrings name what the numbers are; nothing here lets you
  confirm it.
