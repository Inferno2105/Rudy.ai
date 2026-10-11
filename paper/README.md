# The paper

An IEEE conference paper (`IEEEtran`) on the system and its evaluation.

| File | What it is |
|---|---|
| `main.tex` | Title, authors, abstract, macros; includes the sections |
| `sections/01-introduction.tex` … `07-conclusion.tex` | One file per section, so several people can edit at once |
| `references.bib` | Bibliography |
| `tables/`, `figures/` | **Generated** by `meeting-assistant paper build` from stored runs. Never edit by hand. |

## Building

```powershell
powershell -File paper/build.ps1          # draft: placeholders print in red
powershell -File paper/build.ps1 -Final   # submission.pdf: fails while any placeholder is left
```

The script uses a local `latexmk` if you have one, otherwise the TeX Live
Docker image. You can also upload the `paper/` folder to Overleaf (compiler:
pdfLaTeX).

## Rules for writing it

- **No hand-typed results.** Every number in the Results section comes from a
  generated table or figure (`\resulttable{name}{…}`, `\resultfigure{name}{…}`).
  Until the file exists, a red "Pending" box shows what will go there.
- **Mark what is unknown.** Write `\pending{what is missing}` for anything not
  yet decided or measured (author names, dataset size, findings). It prints in
  red, and the `-Final` build refuses to finish while any is left.
- **Describe the code as it is.** The System section quotes the real
  thresholds and settings (`config.py`, `language/detection.py`,
  `audio/vad.py`…). If one changes, update the paper in the same commit.
- **Check references before submitting.** Page numbers are given only where
  verified; add pages and DOIs from each publisher's page.

## Still to decide

- The system's name (`\system` in `main.tex`, currently "HinglishMeet").
- Authors, affiliations, target venue (the template may change).
- Dataset details, consent and ethics approval.
