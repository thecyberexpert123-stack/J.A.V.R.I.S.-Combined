# Third-Party Notices

This project is distributed under the MIT License (see `LICENSE`). It depends on the
following third-party software.

## PySide6 / Qt 6

- **Project:** Qt for Python (PySide6), The Qt Company and contributors
- **Homepage:** https://www.qt.io/qt-for-python
- **Licence:** LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only (a commercial licence is
  also available from The Qt Company). Source:
  [PySide6 on PyPI](https://pypi.org/project/PySide6/).
- **How it is used:** imported as an unmodified library and dynamically linked, via a
  standard `pip install`. Qt itself is neither modified nor statically linked, and no
  Qt source is vendored into this repository.

This project relies on the **LGPLv3** option. Under the LGPL, using an unmodified
library in this way does not place its terms on this project's own source, which
remains MIT-licensed. Anyone redistributing this application together with Qt must
still honour the LGPL's obligations, in particular:

- provide these notices and a copy of the LGPLv3 text to recipients;
- keep Qt replaceable by the user — dynamic linking, as used here, satisfies this;
- make the corresponding source of Qt available, or state where to obtain it
  (https://download.qt.io/).

PySide6 was chosen over PyQt6 specifically for this reason: PyQt6 is GPLv3, which
would impose source-disclosure obligations on any application that uses it. The
analysis is recorded in `docs/RESEARCH.md` §3.3.

### Runtime components bundled in the PySide6 wheels

The PySide6 wheels bundle Qt shared libraries and QML modules. Those files remain
under the Qt licensing above, and are not covered by this project's MIT licence. Qt in
turn incorporates third-party code under its own set of licences, catalogued at
https://doc.qt.io/qt-6/licenses-used-in-qt.html.

## Fonts

No fonts are bundled. The interface requests the generic `monospace` family and uses
whatever the host system provides, so no font licence obligations arise from this
repository.

## Design and pattern attribution

No third-party source code is copied into this project. Architectural patterns adapted
from other open-source work, and the research sources behind the visual design, are
credited in `docs/CREDITS.md`.
