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
| `lnf-xxxxc4_12a.pdf` | Low Noise Factory LNF-xxxxC4_12A cryogenic isolator/circulator | `LNF_C4_12A` | dated 2022-05-02 | 2026-09-10 |
| `rg223-data-sheet.pdf` | McGill Microwave RG223/U coax | `SMA_RG223_cables` | (unmarked, undated) | 2026-09-11 |
| `RG316-SMAcable-HUBERSUHNERRG316UDataSheet.pdf` | HUBER+SUHNER RG316/U coax | `SMA_RG316_cables` | DOC-0000177782, 2020-10-14 | 2026-09-03 |
| `VHF-5050+.pdf` | Mini-Circuits VHF-5050+ high pass | `FilterHP_VHF5050p` | REV. B | 2026-08-28 |
| `VLF-6700+.pdf` | Mini-Circuits VLF-6700+ low pass | `FilterLP_VLF6700p` | (unmarked) | 2026-08-28 |
| `VLFG-2000+_dashboard.pdf` | Mini-Circuits VLFG-2000+ low pass | `FilterLP_VLFG2000p` | REV. A ECO-013807 (spec), REV. OR 210812 (data) | 2026-09-04 |
| `ZC16PD-02183-S+.pdf` | Mini-Circuits ZC16PD-02183-S+ 16-way splitter/combiner | `ZC16PD_02183_Splus` | REV. OR, ECO-004360 | 2026-09-11 |
| `ZN4PD-4R722+_dashboard.pdf` | Mini-Circuits ZN4PD-4R722+ 4-way splitter/combiner | `ZN4PD_4R722plus` | REV. OR, ECO-011123 | 2026-09-03 |
| `ZN8PD-02183+.pdf` | Mini-Circuits ZN8PD-02183+ 8-way splitter/combiner | `ZN8PD_02183plus` | REV. OR, M163108 | 2026-09-11 |
| `ZX60-14LN-S+.pdf` | Mini-Circuits ZX60-14LN-S+ LNA | `ZX60_14LN_Splus` | REV. OR, ECO-016347 | 2026-09-11 |
| `ZX60-153LN-S+.pdf` | Mini-Circuits ZX60-153LN-S+ LNA | `ZX60_153LN_Splus` | REV. D, ECO-016183 | 2026-09-11 |
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
9a2e48c414e891a519b22a35e64722f1360f5a91dc4b604719187ae33db8e8ac  lnf-xxxxc4_12a.pdf
cb0156c488590c5e7a53e6bb6ce8f9ec83bbc705f93a0a5cb3f5f3213ddd02e8  rg223-data-sheet.pdf
2fb12f580e6b30683fb0717ba493faaf307a5901cfd579e144365ca46266c664  RG316-SMAcable-HUBERSUHNERRG316UDataSheet.pdf
81e25337f96fa20aec016a474bbad1884d726982479b126a04bb964229a6fd76  VHF-5050+.pdf
e9e5a9a8f9e5d6e240a02ee54feaf3b2abc02d3ceacbeec0bacc613b170b5e90  VLF-6700+.pdf
47dabd1b238dc782705f0ad645b0b053f96fdfd437760a28beeb25e652efd64a  VLFG-2000+_dashboard.pdf
cb76df8396958c17e785ecd1e8a264207e19f33c6ba6d1ad50bfa7a038a9c690  ZC16PD-02183-S+.pdf
879208550a105029d08914f2b447fd78df7cedc56cbf911f3edce446c9de540d  ZN4PD-4R722+_dashboard.pdf
bd12f1fff64c5b5122805541c05fe7f9701385954808c5e644e7dfd1f3bf9775  ZN8PD-02183+.pdf
a3744635a25ae9e9d64336a959a65ee5894b3950f85c01b52c309eb4b2284f49  ZX60-14LN-S+.pdf
50b53837d48e33fa3effd0ce97a514666660f22bfb4a12f647542004ea065f15  ZX60-153LN-S+.pdf
0d09ff885bd31620bec944d399915ed29d0e5f9a4dcd791c2d1541fff5ef5273  ZX60-83LN-S+.pdf
```

## Modelled narrower than the datasheet

**`ZN4PD-4R722+`** is in the library as the loss along one output arm, which is
all a linear cascade can hold - `SignalChain` is a chain, so there is nowhere to
put the other three ports. The loss is the datasheet's Total Loss, insertion
loss with the 6 dB of splitting already included, averaged across the four
measured arms. Deliberately absent, and on the datasheet if you need them: the
amplitude and phase unbalance between arms, the isolation between outputs, the
fact that a combiner sums four inputs rather than dividing one, the 30 W rating
and the DC-pass path. A chain that turns on any of those is not one this model
belongs in.

**`ZN8PD-02183+`** and **`ZC16PD-02183-S+`** are modelled the same way and for
the same reason - the datasheet's Total Loss along one output arm, 9 dB and
12 dB of splitting already included, with the isolation, unbalance, combining
direction, power ratings and DC-pass path all left on the PDF. The ZN8PD
averages the six arms its table publishes, of eight; ports 5 and 7 are not
tabulated at all. The ZC16PD tabulates one arm, S-1, so nothing is averaged
there and the model is one port of one unit, with the quoted 0.06-0.24 dB
amplitude unbalance as the scale on which the other fifteen differ.

Both are reactive rather than resistive, which is worth recording because it is
the question that decides whether the split is dissipation. Three things say so
on each datasheet. The split is quoted at 10*log10(N) - 9 dB and 12 dB - where a
resistive star costs 20*log10(N), 18 dB and 24 dB, and the measured Total Loss
starts at 9.34 and 12.78 dB. Isolation between outputs is 20 dB typical on the
ZN8PD and 24-37 dB on the ZC16PD, which a resistive star cannot give and which
takes the isolation resistors of a Wilkinson. And both quote a separate
"Internal Dissipation" rating far below the input rating - 0.5 W against 20 W,
1.6 W against 20 W - which is what those resistors are allowed to absorb; the
ZC16PD makes it plainer still by rating itself 20 W as a splitter and 1.6 W as a
combiner, the asymmetry you get when uncorrelated inputs land in the isolation
resistors instead of the sum port. So the loss these models carry is conductor
and dielectric loss in a three- and four-stage corporate network, and the models
are noiseless because the split itself is division rather than dissipation.

**`RG223`** is the only model here whose coefficients are fitted rather than
read off, and the table they are fitted to does not obey the physics. Coax loss
cannot grow more slowly than sqrt(f), and three of the seven intervals in this
datasheet's eight-row attenuation table do: 14 to 16 dB/100m over 50-100 MHz
where sqrt alone demands 19.8, 16 to 28 over 100-400 MHz where it demands 32,
and 37 to 44 over 500-900 MHz where it demands 49.6. Against a pure sqrt law
anchored at 3 GHz the rows scatter from -13% to +23%. This is a compiled or
rounded table rather than a measurement series, and no choice of coefficients
fits it.

The model fits `a*sqrt(f) + b*f` to all eight rows by absolute least squares,
which weights the large high-frequency rows - the self-consistent ones, and the
ones that set the extrapolation the part was added for. Fitting only the
900 MHz-3 GHz rows instead gives 1.87 dB/m at 10 GHz where this fit gives 1.69,
so treat anything above 3 GHz as carrying 10-15% beyond what the fit says.
Fitting in log space is worse than either: the bad 50 MHz row pulls the
dielectric term negative, which would have loss turn over and fall at high
frequency. The span reported is the table's own 3 GHz, not the datasheet's
12.4 GHz "Max Frequency", which is the usable limit of the cable rather than a
range over which its loss was characterised.

**`LNF-xxxxC4_12A`** is in the library as its insertion loss and nothing else,
which was the scope it was added under and is also most of what a cascade can
take. The datasheet's other three headline numbers - 30 dB isolation, 16 dB
port match, the third port - describe a non-reciprocal three-port, and
`SignalChain` is a linear one-way cascade with no way to express any of it. So
the model prices the loss the signal pays going the intended way and is silent
on the isolation that loss is bought for. Also absent: the internal magnet's
stray field, the external field the part tolerates, the 30 dBm drive limit and
the DC rating.

One model covers all four order codes. `ISIS`, `CICI`, `ISCI` and `CIIS` -
dual isolator, dual circulator and the two mixed pairs - share this datasheet
and its single insertion-loss chart, so nothing in the document distinguishes
them here.

Its numbers are digitised rather than transcribed, the only ones in the library
that are. There is no insertion-loss table on this datasheet, only the
"Insertion Loss of 5 Units at 77 K" chart and a single "0.4 dB typical" in the
specification table. The chart is vector art, though, so the five traces are
the plotted samples exactly - 201 points each, 3 to 13 GHz in 50 MHz steps -
and the model carries their mean, calibrated on the plot frame against the
printed tick labels. Recovering it needs the drawing operators rather than a
text extractor: `mutool trace lnf-xxxxc4_12a.pdf 2` prints them. The 4-12 GHz
mean of what came out is 0.38 dB against the front page's 0.4 dB typical, which
is the check that it was read correctly. Two things follow that a transcribed
table would not need saying: the digitisation is only as good as that
calibration, and the 77 K measured curve is the only one - the datasheet says
insertion loss "improves slightly" at 5 K and 10 mK without saying by how much,
so a millikelvin chain is being quoted the warm end of the part's range.

**`VLFG-2000+`** is modelled from the +25 °C column alone. Its performance table
is the only one here published at three temperatures, -55 °C, +25 °C and
+125 °C, and the part is genuinely temperature stable at the scale of the
plots - but not at the tenth of a dB the table prints, since the 2 GHz passband
loss runs 0.73 dB cold and 1.15 dB hot around the 0.92 dB the model uses. The
other two columns are on the PDF; carrying them needs a temperature parameter
the filter models do not have.

Note also that this file bundles two documents of different revisions, and their
insertion-loss tables disagree in the deep stopband: the REV. A spec sheet reads
54.29 dB at 5 GHz and 44.25 dB at 7.5 GHz where the REV. OR performance data
reads 73.67 and 52.57. They agree through the skirt and from 9 GHz up. The model
takes the denser REV. OR table as it stands - the disagreement is 44 dB down at
worst, past the point where a cascade can tell - so anyone checking the model
against the front page of its own datasheet will find those two decades off.

**`ZX60-153LN-S+`** stops at 14 GHz where its swept performance table does,
one GHz short of the 15 GHz the part is sold over. The specification table's
15 GHz typicals exist - 14.9 dB gain, 3.6 dB noise figure - and are deliberately
not joined on: 14.9 dB sits above the swept table's 14.63 dB at 14 GHz, inside
the two tables' mutual scatter but enough to reverse the sign of the band-edge
slope, and since an extrapolation extends that slope the model would then climb
with frequency above 15 GHz instead of rolling off. An out-of-band estimate that
is too generous is the one kind this library will not carry. A chain that needs
the top of that part's band wants its own measurement.

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
