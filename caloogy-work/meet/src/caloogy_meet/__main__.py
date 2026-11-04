import sys

from .cli import main

# python -m caloogy_meet [meet|call] <command> ...
kind = sys.argv.pop(1) if len(sys.argv) > 1 and sys.argv[1] in ("meet", "call") else "meet"
main(kind)
