import os
import sys

# Make ``app`` importable when pytest is run from the repository root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
