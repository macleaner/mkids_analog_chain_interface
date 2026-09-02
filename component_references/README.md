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
| `VHF-5050+.pdf` | Mini-Circuits VHF-5050+ high pass | `FilterHP_VHF5050p` | REV. B | 2026-08-28 |
| `VLF-6700+.pdf` | Mini-Circuits VLF-6700+ low pass | `FilterLP_VLF6700p` | (unmarked) | 2026-08-28 |
| `ZX60-83LN-S+.pdf` | Mini-Circuits ZX60-83LN-S+ LNA | `ZX60_83LN_Splus` | REV. C, ECO-015740 | 2026-09-02 |

All three from `https://www.minicircuits.com/pdfs/<part>.pdf`, which is why the
files keep the vendor's own names: the filename is the URL is the part number,
including the `+` that marks RoHS compliance.

The revision matters more than the date. Mini-Circuits reissues datasheets
without changing the URL, so re-fetching one of these can quietly hand you
different numbers under the same name. Check the revision in the footer against
the table above before concluding a model disagrees with its source.

```
81e25337f96fa20aec016a474bbad1884d726982479b126a04bb964229a6fd76  VHF-5050+.pdf
e9e5a9a8f9e5d6e240a02ee54feaf3b2abc02d3ceacbeec0bacc613b170b5e90  VLF-6700+.pdf
0d09ff885bd31620bec944d399915ed29d0e5f9a4dcd791c2d1541fff5ef5273  ZX60-83LN-S+.pdf
```

## What is missing

Recorded because a gap that is written down can be closed, and one that is not
gets mistaken for completeness. The cryogenic LNAs were added from transcribed
figures, and none of their sources are here:

* **`CMT_CITCRYO1_12D`** - gain is a measurement, `SN216D` at 13 K, Vd = 1.2 V,
  taken from an s2p file that is not in this repo and whose path was not
  recorded. That s2p is the primary record; the curve in `hardware_models.py`
  is derived from it. Its noise is a single 5 K figure said to come from a 12 K
  datasheet plot, and the digitised curve behind that figure never arrived -
  which is why the model holds noise flat across the whole band and says so.
* **`LNF_LNC1_5_6B`**, **`LNF_LNC0_3_14B`** - Low Noise Factory datasheet
  figures at 5 K, transcribed without the datasheets. The 0.3 GHz noise point
  on the LNC0.3_14B is extrapolated rather than read, and cannot be checked
  against anything until its datasheet is here.

The older parts - `CryoElec_LNA`, `ASU_3GHz_LNA`, `ZX60_3018Gplus`, the cables,
the AD9082 - predate this directory and have no stored source either. Their
docstrings name what the numbers are; nothing lets you confirm it.
