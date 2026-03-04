import os
import sys

# Add the 'src' directory to Python path so the 'scr' module can be imported
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

from scr.web import create_app

# Vercel's Node/Python runtime looks for an object named 'app'
app = create_app()
