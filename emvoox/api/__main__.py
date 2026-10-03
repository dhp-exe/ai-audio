"""python -m emvoox.api  ==  python -m emvoox serve"""

from emvoox.cli import main

if __name__ == "__main__":
    raise SystemExit(main(["serve"]))
