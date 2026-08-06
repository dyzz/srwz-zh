#!/usr/bin/env python3
"""Build a VT1 font component from an explicit profile and proposal.

The implementation remains in the historical ``build_first_five_font``
module so old evidence commands keep working.  Active release automation uses
this neutral entry point and always supplies explicit inputs and outputs.
"""

from build_first_five_font import main


if __name__ == "__main__":
    raise SystemExit(main())
